import os
import re
import random
import asyncio
import logging
import datetime
import uuid
import urllib.parse
import aiohttp
from io import BytesIO

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, User
    )
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, User
    )

from config import Config
from database.batches import (
    create_batch, get_batch, delete_batch, increment_batch_views,
    increment_batch_downloads, get_recent_batches, get_user_batches, count_total_batches,
    toggle_batch_protection, set_batch_pin, set_batch_expiry
)
from database.users import is_premium, can_user_create_filestore_link, record_filestore_link_created
from database.verify import is_user_verified, create_verify_token
from utils.helpers import get_readable_size, is_private_chat
from plugins.start import (
    check_fsub, build_fsub_markup, deliver_file_with_copyright_warning
)

logger = logging.getLogger(__name__)

# State cache for interactive batch file collection: {user_id: {"files": list, "title": str}}
AWAITING_BATCH_FILES: dict[int, dict] = {}


def get_clean_media_name(msg: Message) -> str:
    """Extract clean, human-readable file name from media attributes or caption."""
    media = msg.document or msg.video or msg.audio or msg.photo or msg.animation or msg.voice
    if not media:
        return "Unknown File"

    # 1. Direct file_name attribute (if valid and not raw unique_id hash)
    fname = getattr(media, "file_name", None)
    if fname and fname.strip() and not fname.startswith("File_"):
        return fname.strip()

    # 2. Audio title + artist
    if msg.audio:
        title = getattr(msg.audio, "title", None)
        performer = getattr(msg.audio, "performer", None)
        if title and performer:
            return f"{performer} - {title}"
        if title:
            return title

    # 3. Message caption: pick first informative non-empty line
    if msg.caption:
        lines = [l.strip() for l in msg.caption.splitlines() if l.strip()]
        for line in lines:
            if line.startswith("http://") or line.startswith("https://") or line.startswith("www.") or line.startswith("#"):
                continue
            clean_l = re.sub(r"<[^>]+>", "", line).strip()
            clean_l = re.sub(r"[*_`~]", "", clean_l).strip()
            if len(clean_l) >= 3:
                return clean_l[:80]

    # 4. Fallback to existing fname
    if fname and fname.strip():
        return fname.strip()

    # 5. Fallback based on media type
    if msg.video:
        return f"Video_{msg.id}.mp4"
    if msg.photo:
        return f"Photo_{msg.id}.jpg"
    if msg.animation:
        return f"GIF_{msg.id}.mp4"
    if msg.audio:
        return f"Audio_{msg.id}.mp3"
    if msg.voice:
        return f"Voice_{msg.id}.ogg"
    return f"File_{msg.id}"


def extract_media_from_message(msg: Message) -> dict | None:
    """Extract standard file metadata dictionary from a Pyrogram/Hydrogram message."""
    media = msg.document or msg.video or msg.audio or msg.photo or msg.animation or msg.voice
    if not media:
        return None

    file_name = get_clean_media_name(msg)
    file_size = getattr(media, "file_size", 0)

    if msg.photo:
        mime_type = "image/jpeg"
    elif msg.animation:
        mime_type = getattr(media, "mime_type", "video/mp4")
    elif msg.voice:
        mime_type = getattr(media, "mime_type", "audio/ogg")
    else:
        mime_type = getattr(media, "mime_type", "application/octet-stream")

    caption = msg.caption.html if msg.caption else file_name

    return {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": mime_type,
        "caption": caption,
        "channel_id": msg.chat.id if msg.chat else None,
        "message_id": msg.id
    }


def parse_channel_post_link(link: str) -> tuple[int | str | None, int | None, int | None]:
    """
    Parse Telegram message links.
    Supports:
      - https://t.me/c/2001671856/9470
      - https://t.me/c/2001671856/9470-9480 (range)
      - https://t.me/mychannel/9470
    Returns (chat_id, start_id, end_id).
    """
    link = link.strip()
    m_priv = re.search(r"t\.me/c/(\d+)/(\d+)(?:-(\d+))?", link)
    if m_priv:
        raw_cid = int(m_priv.group(1))
        chat_id = int(f"-100{raw_cid}")
        start_id = int(m_priv.group(2))
        end_id = int(m_priv.group(3)) if m_priv.group(3) else start_id
        return chat_id, start_id, end_id

    m_pub = re.search(r"t\.me/([^/]+)/(\d+)(?:-(\d+))?", link)
    if m_pub:
        chat_id = m_pub.group(1)
        start_id = int(m_pub.group(2))
        end_id = int(m_pub.group(3)) if m_pub.group(3) else start_id
        return chat_id, start_id, end_id

    return None, None, None


async def archive_batch_to_storage_channel(
    client: Client,
    user: User | None,
    title: str,
    batch_id: str,
    files: list[dict],
    share_url: str
) -> list[dict]:
    """
    Copies/forwards all batch media files to the dedicated private storage channel
    (Config.FILE_STORE_CHANNEL: -1004384430212) to ensure permanent cloud persistence,
    updates each file's channel_id and message_id, and sends an audit log card
    with creator information, batch metrics, and the generated link.
    """
    target_channel = getattr(Config, "FILE_STORE_CHANNEL", -1004384430212)
    if not target_channel:
        return files

    user_id = user.id if user else 0
    first_name = user.first_name if user else "User"
    username = f"@{user.username}" if user and user.username else "No Username"
    mention = f'<a href="tg://user?id={user_id}">{first_name}</a>'

    updated_files = []
    for f_info in files:
        item = dict(f_info)
        src_chat = item.get("channel_id")
        src_mid = item.get("message_id")
        copied = False

        # Method 1: Try forwarding from original source message so Telegram natively
        # displays "Forwarded from [User]" with clickable profile attribution
        if src_chat and src_mid:
            try:
                fwd_res = await client.forward_messages(
                    chat_id=target_channel,
                    from_chat_id=src_chat,
                    message_ids=src_mid
                )
                sent_msg = fwd_res[0] if isinstance(fwd_res, list) else fwd_res
                if sent_msg:
                    item["channel_id"] = target_channel
                    item["message_id"] = sent_msg.id
                    media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo or sent_msg.animation or sent_msg.voice
                    if media:
                        item["file_id"] = media.file_id
                        item["file_unique_id"] = media.file_unique_id
                    copied = True
            except Exception as fwd_err:
                logger.debug(f"forward_messages failed for {item.get('file_name')}, falling back to copy: {fwd_err}")
                try:
                    sent_msg = await client.copy_message(
                        chat_id=target_channel,
                        from_chat_id=src_chat,
                        message_id=src_mid,
                        caption=item.get("caption") or item.get("file_name")
                    )
                    if sent_msg:
                        item["channel_id"] = target_channel
                        item["message_id"] = sent_msg.id
                        media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo or sent_msg.animation or sent_msg.voice
                        if media:
                            item["file_id"] = media.file_id
                            item["file_unique_id"] = media.file_unique_id
                        copied = True
                except Exception as copy_err:
                    logger.debug(f"copy_message failed as well: {copy_err}")

        # Method 2: Fallback to sending via cached file_id if copy_message failed
        if not copied and item.get("file_id"):
            try:
                mime = item.get("mime_type", "")
                caption = item.get("caption") or item.get("file_name")
                fid = item["file_id"]

                if "photo" in mime or "image" in mime:
                    sent_msg = await client.send_photo(chat_id=target_channel, photo=fid, caption=caption)
                elif "animation" in mime or "gif" in mime:
                    sent_msg = await client.send_animation(chat_id=target_channel, animation=fid, caption=caption)
                elif "voice" in mime:
                    sent_msg = await client.send_voice(chat_id=target_channel, voice=fid, caption=caption)
                elif "video" in mime:
                    sent_msg = await client.send_video(chat_id=target_channel, video=fid, caption=caption)
                elif "audio" in mime:
                    sent_msg = await client.send_audio(chat_id=target_channel, audio=fid, caption=caption)
                else:
                    sent_msg = await client.send_document(chat_id=target_channel, document=fid, caption=caption)

                if sent_msg:
                    item["channel_id"] = target_channel
                    item["message_id"] = sent_msg.id
                    media = sent_msg.document or sent_msg.video or sent_msg.audio or sent_msg.photo or sent_msg.animation or sent_msg.voice
                    if media:
                        item["file_id"] = media.file_id
                        item["file_unique_id"] = media.file_unique_id
                    copied = True
            except Exception as send_err:
                logger.warning(f"send fallback failed for {item.get('file_name')} to storage channel: {send_err}")

        updated_files.append(item)

    # Post Audit Log Card in FILE_STORE_CHANNEL
    try:
        total_sz = sum(int(f.get("file_size", 0)) for f in updated_files)
        total_sz_str = get_readable_size(total_sz)
        is_adm = Config.is_admin(user_id)
        is_vip = await is_premium(user_id)
        role_badge = "👑 Administrator" if is_adm else ("🌟 VIP Member" if is_vip else "👤 Regular User")
        now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        is_single = len(updated_files) == 1
        header_text = "📥 <b><u>NEW FILE ARCHIVE AUDIT</u></b>" if is_single else "📥 <b><u>NEW BATCH PACK ARCHIVE AUDIT</u></b>"
        label_key = "🎬 <b>File:</b>" if is_single else "📦 <b>Collection:</b>"

        audit_text = (
            f"{header_text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{label_key} <code>{title}</code>\n"
            f"🔑 <b>ID:</b> <code>{batch_id}</code>\n"
            f"📁 <b>Total Files:</b> <code>{len(updated_files)} Files</code>\n"
            f"📊 <b>Total Size:</b> <code>{total_sz_str}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Created By:</b> {mention} ({username})\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🎖️ <b>Account Status:</b> {role_badge}\n"
            f"⏱️ <b>Timestamp:</b> <code>{now_utc}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Shareable Access Link:</b>\n<code>{share_url}</code>"
        )

        audit_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Open in Bot ↗️", url=share_url)]
        ])

        await client.send_message(
            chat_id=target_channel,
            text=audit_text,
            reply_markup=audit_markup,
            disable_web_page_preview=True
        )
    except Exception as audit_err:
        logger.error(f"Failed to post audit log in FILE_STORE_CHANNEL {target_channel}: {audit_err}")

    return updated_files


def format_daily_quota_reached_msg(daily_limit: int) -> tuple[str, InlineKeyboardMarkup]:
    """Generate quota exceeded message prompting user to upgrade to VIP."""
    text = (
        "⛔ <b>Daily File Store Limit Reached!</b>\n\n"
        f"You have already created <b>{daily_limit}/{daily_limit} links today</b>.\n"
        "Your daily quota will automatically reset at <b>00:00 UTC (Midnight)</b>.\n\n"
        "👑 <b>Need Unlimited Link Storage?</b>\n"
        "Upgrade to <b>VIP Membership</b> to enjoy:\n"
        "• ♾️ Unlimited File Store & Batch links\n"
        "• ⚡ Instant downloads with Zero Ads\n"
        "• ⏱️ 30-Minute extended auto-delete time\n"
        "• 🍿 4K/1080p Ultra-fast streaming"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 View VIP Plans & Upgrade", callback_data="view_plans")],
        [InlineKeyboardButton("💬 Contact Support", url=Config.SUPPORT_URL)]
    ])
    return text, markup


async def format_batch_success_response(
    user_id: int,
    title: str,
    batch_id: str,
    total_files: int,
    total_size: int,
    share_url: str,
    used_today: int,
    daily_limit: int
) -> tuple[str, InlineKeyboardMarkup]:
    """Format rich success response for user with quota indicator."""
    total_sz_str = get_readable_size(total_size)
    is_adm = Config.is_admin(user_id)
    is_vip = await is_premium(user_id)

    if is_adm:
        status_line = "👑 <b>Account Role:</b> <code>Administrator (Unlimited)</code>"
    elif is_vip:
        status_line = "🌟 <b>Account Role:</b> <code>VIP Member (Unlimited)</code>"
    else:
        used_now = min(daily_limit, used_today + 1)
        status_line = f"📊 <b>Daily Quota:</b> <code>{used_now}/{daily_limit} used today</code> <i>(Resets at 00:00 UTC)</i>"

    if total_files <= 1:
        text = (
            "🎉 <b>FILE LINK GENERATED SUCCESSFULLY!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 <b>File:</b> <code>{title}</code>\n"
            f"💾 <b>Size:</b> <code>{total_sz_str}</code>\n"
            f"{status_line}\n\n"
            f"🔗 <b>Shareable Link:</b>\n<code>{share_url}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Anyone who opens this link can download this file in 1-Click!</i>"
        )
        tg_share = f"https://t.me/share/url?url={urllib.parse.quote(share_url)}&text={urllib.parse.quote(f'🎬 {title} ({total_sz_str}) - Download Link:')}"
        btn_rows = [
            [InlineKeyboardButton("📤 Share File Link", url=tg_share)],
            [InlineKeyboardButton("🔗 Open in Bot ↗️", url=share_url)]
        ]
    else:
        text = (
            "🎉 <b>BATCH PACK GENERATED SUCCESSFULLY!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Title:</b> <code>{title}</code>\n"
            f"📁 <b>Total Files:</b> <code>{total_files} Files</code>\n"
            f"💾 <b>Total Size:</b> <code>{total_sz_str}</code>\n"
            f"{status_line}\n\n"
            f"🔗 <b>Shareable Link:</b>\n<code>{share_url}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Anyone who opens this link can download all files in 1-Click!</i>"
        )
        tg_share = f"https://t.me/share/url?url={urllib.parse.quote(share_url)}&text={urllib.parse.quote(f'🎬 {title} ({total_files} Files) - Download Pack:')}"
        btn_rows = [
            [InlineKeyboardButton("📤 Share Batch Link", url=tg_share)],
            [InlineKeyboardButton("🔗 Open in Bot ↗️", url=share_url)]
        ]
    if not is_adm and not is_vip:
        btn_rows.append([InlineKeyboardButton("👑 Upgrade to VIP for Unlimited Links", callback_data="view_plans")])

    return text, InlineKeyboardMarkup(btn_rows)


# ==========================================
# 0. Interactive Link Configuration, Security & PIN System
# ==========================================
PENDING_NAMING: dict[str, dict] = {}
VERIFIED_PIN_SESSIONS: set[tuple[int, str]] = set()  # (user_id, batch_id)
PIN_INPUT_BUFFER: dict[tuple[int, str], str] = {}    # (user_id, batch_id) -> current entered pin string
PIN_ATTEMPTS: dict[tuple[int, str], int] = {}        # (user_id, batch_id) -> failed count


def is_user_in_filestore_session(user_id: int) -> bool:
    """Return True if user is actively in a filestore naming, PIN, custom limit, or batch collection session."""
    for p in PENDING_NAMING.values():
        if p.get("user_id") == user_id and p.get("waiting_input"):
            return True
    for (uid, _) in PIN_INPUT_BUFFER.keys():
        if uid == user_id:
            return True
    if user_id in AWAITING_BATCH_FILES:
        return True
    return False


def parse_time_duration(time_str: str) -> int | None:
    """Parse string like '45m', '3h', '2d' into seconds."""
    time_str = time_str.strip().lower()
    m = re.match(r"^(\d+)\s*([mhd])$", time_str)
    if not m:
        if time_str.isdigit():
            return int(time_str) * 60
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return None


def is_batch_expired(batch_doc: dict) -> tuple[bool, str]:
    """Check if batch link has expired due to time or maximum download limits."""
    expire_at = batch_doc.get("expire_at")
    if expire_at:
        if hasattr(expire_at, "replace") and getattr(expire_at, "tzinfo", None):
            expire_at = expire_at.replace(tzinfo=None)
        now = datetime.datetime.utcnow()
        if now >= expire_at:
            exp_str = expire_at.strftime("%d %b %Y, %H:%M UTC")
            return True, f"Time limit passed on {exp_str}"

    max_dl = batch_doc.get("max_downloads")
    if max_dl and max_dl > 0:
        cur_dl = batch_doc.get("downloads_count", 0)
        if cur_dl >= max_dl:
            return True, f"Download limit of {max_dl} users reached ({cur_dl}/{max_dl})"

    return False, ""


def build_pin_numpad_markup(batch_id: str, current_input: str) -> InlineKeyboardMarkup:
    """Build interactive 0-9 Numpad markup for entering 4-digit PIN."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data=f"pin_in_{batch_id}_1"),
            InlineKeyboardButton("2", callback_data=f"pin_in_{batch_id}_2"),
            InlineKeyboardButton("3", callback_data=f"pin_in_{batch_id}_3")
        ],
        [
            InlineKeyboardButton("4", callback_data=f"pin_in_{batch_id}_4"),
            InlineKeyboardButton("5", callback_data=f"pin_in_{batch_id}_5"),
            InlineKeyboardButton("6", callback_data=f"pin_in_{batch_id}_6")
        ],
        [
            InlineKeyboardButton("7", callback_data=f"pin_in_{batch_id}_7"),
            InlineKeyboardButton("8", callback_data=f"pin_in_{batch_id}_8"),
            InlineKeyboardButton("9", callback_data=f"pin_in_{batch_id}_9")
        ],
        [
            InlineKeyboardButton("⌫ Clear", callback_data=f"pin_in_{batch_id}_clear"),
            InlineKeyboardButton("0", callback_data=f"pin_in_{batch_id}_0"),
            InlineKeyboardButton("✅ OK", callback_data=f"pin_in_{batch_id}_ok")
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data=f"pin_in_{batch_id}_cancel")
        ]
    ])


async def deliver_batch_files_to_user(client: Client, user_id: int, batch_doc: dict, target_msg: Message = None):
    """Deliver single or multi-file batch to the user with protection & auto-delete."""
    batch_id = batch_doc.get("batch_id")
    files = batch_doc.get("files", [])
    if not files:
        if target_msg:
            try:
                await target_msg.reply_text("❌ No files found in this collection.")
            except Exception:
                pass
        return

    is_protected = bool(batch_doc.get("protect_content", False))

    # Increment download counter in DB
    if batch_id:
        asyncio.create_task(increment_batch_downloads(batch_id))

    if len(files) <= 1:
        try:
            await deliver_file_with_copyright_warning(
                client=client,
                user_id=user_id,
                file_doc=files[0],
                custom_protect=True if is_protected else None,
                is_protected_viewing=is_protected
            )
        except Exception as e:
            logger.error(f"Error delivering single file ({files[0].get('file_name')}): {e}")
            if target_msg:
                try:
                    await target_msg.reply_text("❌ Failed to deliver file. Please try again later.")
                except Exception:
                    pass
        return

    # Multi-file batch dispatch
    progress_msg = None
    if target_msg:
        try:
            progress_msg = await target_msg.reply_text(f"⏳ <b>Dispatching {len(files)} files to your chat...</b>")
        except Exception:
            pass

    sent_count = 0
    for idx, f_info in enumerate(files, 1):
        try:
            await deliver_file_with_copyright_warning(
                client=client,
                user_id=user_id,
                file_doc=f_info,
                custom_protect=True if is_protected else None,
                is_protected_viewing=is_protected
            )
            sent_count += 1
            if len(files) > 1:
                await asyncio.sleep(0.6)  # Flood prevention
        except Exception as e:
            logger.error(f"Error dispatching batch file #{idx} ({f_info.get('file_name')}): {e}")

    if progress_msg:
        try:
            await progress_msg.edit_text(f"✅ <b>Successfully delivered all {sent_count} files!</b>")
            await asyncio.sleep(4)
            await progress_msg.delete()
        except Exception:
            pass


def build_naming_prompt(p: dict, token: str) -> tuple[str, InlineKeyboardMarkup]:
    title = p["default_title"]
    prot_badge = "🛡️ ON (Anti-Forward)" if p.get("protect_content") else "❌ OFF"
    pin_badge = f"<code>{p['pin_code']}</code> 🔑" if p.get("pin_code") else "None 🔓"

    exp_s = p.get("expire_seconds")
    if exp_s:
        if exp_s >= 86400:
            exp_str = f"{exp_s // 86400}d"
        elif exp_s >= 3600:
            exp_str = f"{exp_s // 3600}h"
        else:
            exp_str = f"{exp_s // 60}m"
    else:
        exp_str = "Never"

    max_dl = p.get("max_downloads")
    dl_str = f"{max_dl} DLs" if max_dl else "∞"

    files = p.get("files", [])
    if p.get("is_single"):
        meta_header = f"🎬 <b>File:</b> <code>{title}</code>\n"
    else:
        total_sz = sum(int(f.get("file_size", 0)) for f in files)
        total_sz_str = get_readable_size(total_sz)
        meta_header = (
            f"📦 <b>Batch:</b> <code>{title}</code>\n"
            f"📁 <b>Contents:</b> <code>{len(files)} Items ({total_sz_str})</code>\n"
        )

    text = (
        "🏷️ <b>LINK CONFIGURATION & SECURITY:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{meta_header}"
        f"🔒 <b>Protection:</b> <code>{prot_badge}</code>\n"
        f"🔑 <b>PIN Lock:</b> {pin_badge}\n"
        f"⏳ <b>Self-Destruct:</b> <code>⏱️ {exp_str} • 🎯 {dl_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ <i>Auto-creating with defaults in <b>15 seconds</b>...</i>"
    )

    prot_btn = "🛡️ Protect: ON ✅" if p.get("protect_content") else "🔒 Protect: OFF (VIP)"
    pin_btn = f"🔑 PIN: {p['pin_code']}" if p.get("pin_code") else "🔑 Set PIN (VIP)"
    exp_btn = f"⏳ Expire: {exp_str}" if p.get("expire_seconds") or p.get("max_downloads") else "⏳ Self-Destruct (VIP)"

    rows = [
        [
            InlineKeyboardButton("✏️ Set Title", callback_data=f"opt_title_{token}"),
            InlineKeyboardButton(prot_btn, callback_data=f"opt_prot_{token}")
        ],
        [
            InlineKeyboardButton(pin_btn, callback_data=f"opt_pin_{token}"),
            InlineKeyboardButton(exp_btn, callback_data=f"opt_exp_{token}")
        ],
        [
            InlineKeyboardButton("⚡ Confirm & Create Now", callback_data=f"name_confirm_{token}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"name_cancel_{token}")
        ]
    ]
    return text, InlineKeyboardMarkup(rows)


def build_pin_menu(p: dict, token: str) -> tuple[str, InlineKeyboardMarkup]:
    pin_val = p.get("pin_code") or "None"
    text = (
        "🔑 <b><u>4-DIGIT PIN SECURITY LOCK</u></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Current PIN: <code>{pin_val}</code>\n\n"
        "Select an option below:\n"
        "• <b>Random PIN:</b> Auto-generate a secure 4-digit code\n"
        "• <b>Custom PIN:</b> Type your own custom 4 digits\n"
        "• <b>Remove PIN:</b> Unlock link so anyone can open directly"
    )
    rows = [
        [
            InlineKeyboardButton("🎲 Generate Random PIN", callback_data=f"opt_pin_rnd_{token}"),
            InlineKeyboardButton("✏️ Type Custom PIN", callback_data=f"opt_pin_type_{token}")
        ],
        [
            InlineKeyboardButton("❌ Remove PIN", callback_data=f"opt_pin_clr_{token}"),
            InlineKeyboardButton("🔙 Back to Settings", callback_data=f"opt_back_{token}")
        ]
    ]
    return text, InlineKeyboardMarkup(rows)


def build_expiry_menu(p: dict, token: str) -> tuple[str, InlineKeyboardMarkup]:
    exp_s = p.get("expire_seconds")
    if exp_s:
        if exp_s >= 86400:
            exp_str = f"{exp_s // 86400} Days"
        elif exp_s >= 3600:
            exp_str = f"{exp_s // 3600} Hours"
        else:
            exp_str = f"{exp_s // 60} Minutes"
    else:
        exp_str = "Never (Unlimited)"

    max_dl = p.get("max_downloads")
    dl_str = f"{max_dl} Downloads" if max_dl else "Unlimited"

    text = (
        "⏳ <b><u>SELF-DESTRUCT & DOWNLOAD LIMITS</u></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <b>Time Expiry:</b> <code>{exp_str}</code>\n"
        f"🎯 <b>Download Limit:</b> <code>{dl_str}</code>\n\n"
        "Select a quick preset or type a custom value below:"
    )
    rows = [
        [
            InlineKeyboardButton("⏱️ 1 Hour", callback_data=f"exp_t_{token}_3600"),
            InlineKeyboardButton("⏱️ 6 Hours", callback_data=f"exp_t_{token}_21600"),
            InlineKeyboardButton("⏱️ 24 Hours", callback_data=f"exp_t_{token}_86400")
        ],
        [
            InlineKeyboardButton("✏️ Custom Time", callback_data=f"exp_t_cust_{token}"),
            InlineKeyboardButton("♾️ No Time Expiry", callback_data=f"exp_t_{token}_0")
        ],
        [
            InlineKeyboardButton("🎯 10 DLs", callback_data=f"exp_d_{token}_10"),
            InlineKeyboardButton("🎯 50 DLs", callback_data=f"exp_d_{token}_50"),
            InlineKeyboardButton("🎯 100 DLs", callback_data=f"exp_d_{token}_100")
        ],
        [
            InlineKeyboardButton("✏️ Custom Limit", callback_data=f"exp_d_cust_{token}"),
            InlineKeyboardButton("♾️ Unlimited DLs", callback_data=f"exp_d_{token}_0")
        ],
        [
            InlineKeyboardButton("🔙 Back to Settings", callback_data=f"opt_back_{token}")
        ]
    ]
    return text, InlineKeyboardMarkup(rows)


async def finalize_filestore_creation(
    client: Client,
    user: User,
    title: str,
    files: list[dict],
    status_msg: Message,
    used_today: int,
    daily_limit: int,
    is_single: bool,
    protect_content: bool = False,
    pin_code: str | None = None,
    expire_seconds: int | None = None,
    max_downloads: int | None = None
):
    """Archive files to storage channel -1004384430212, store DB record, and reply with success card."""
    try:
        await status_msg.edit_text("⏳ <b>Archiving to permanent cloud storage & generating link...</b>")
    except Exception:
        pass

    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    batch_id = uuid.uuid4().hex[:10]
    prefix = "file" if is_single else "batch"
    share_url = f"https://t.me/{bot_username}?start={prefix}_{batch_id}"

    final_files = await archive_batch_to_storage_channel(
        client=client,
        user=user,
        title=title,
        batch_id=batch_id,
        files=files,
        share_url=share_url
    )

    await create_batch(
        files=final_files,
        title=title,
        created_by=user.id,
        protect_content=protect_content,
        expire_seconds=expire_seconds,
        max_downloads=max_downloads,
        pin_code=pin_code,
        batch_id=batch_id
    )

    await record_filestore_link_created(user.id)

    resp_text, markup = await format_batch_success_response(
        user_id=user.id,
        title=title,
        batch_id=batch_id,
        total_files=len(final_files),
        total_size=sum(int(f.get("file_size", 0)) for f in final_files),
        share_url=share_url,
        used_today=used_today,
        daily_limit=daily_limit
    )

    try:
        await status_msg.edit_text(resp_text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await client.send_message(user.id, resp_text, reply_markup=markup, disable_web_page_preview=True)


def restart_naming_timer(token: str, delay_seconds: int = 15):
    """Start or restart the auto-finalize countdown for a pending link session."""
    p = PENDING_NAMING.get(token)
    if not p:
        return

    if p.get("timer_task"):
        try:
            p["timer_task"].cancel()
        except Exception:
            pass

    async def _timer_worker(tok: str):
        try:
            await asyncio.sleep(delay_seconds)
            item = PENDING_NAMING.get(tok)
            if item and not item.get("waiting_input"):
                PENDING_NAMING.pop(tok, None)
                await finalize_filestore_creation(
                    client=item["client"],
                    user=item["user"],
                    title=item["default_title"],
                    files=item["files"],
                    status_msg=item["status_msg"],
                    used_today=item["used_today"],
                    daily_limit=item["daily_limit"],
                    is_single=item["is_single"],
                    protect_content=item.get("protect_content", False),
                    pin_code=item.get("pin_code"),
                    expire_seconds=item.get("expire_seconds"),
                    max_downloads=item.get("max_downloads")
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in naming timer worker: {e}")

    p["timer_task"] = asyncio.create_task(_timer_worker(token))


async def prompt_naming_or_finalize(
    client: Client,
    message: Message,
    files: list[dict],
    custom_title: str | None,
    default_title: str,
    status_msg: Message,
    used_today: int,
    daily_limit: int,
    is_single: bool,
    protect_content: bool = False
):
    """
    Presents the user with the Link Configuration & Security prompt (Title, Protect, PIN, Self-Destruct).
    Auto-finalizes with defaults after 15 seconds if no interaction occurs, or immediately on Confirm.
    """
    user = message.from_user
    resolved_title = custom_title.strip() if custom_title and custom_title.strip() else default_title

    token = uuid.uuid4().hex[:8]

    p_data = {
        "user_id": user.id,
        "client": client,
        "user": user,
        "files": files,
        "default_title": resolved_title,
        "status_msg": status_msg,
        "timer_task": None,
        "used_today": used_today,
        "daily_limit": daily_limit,
        "is_single": is_single,
        "protect_content": protect_content,
        "pin_code": None,
        "expire_seconds": None,
        "max_downloads": None,
        "waiting_input": None
    }

    prompt_text, markup = build_naming_prompt(p_data, token)
    await status_msg.edit_text(prompt_text, reply_markup=markup)
    PENDING_NAMING[token] = p_data
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^opt_title_([a-zA-Z0-9_\-]+)$"))
async def opt_title_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_title_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired or already processed.", show_alert=True)
        return
    if query.from_user.id != p["user_id"]:
        await query.answer("⛔ Only the link creator can change settings.", show_alert=True)
        return

    if p.get("timer_task"):
        try:
            p["timer_task"].cancel()
        except Exception:
            pass

    p["waiting_input"] = "title"
    await query.answer()

    # Safety worker: if user opens title prompt and never sends a message within 45s, auto-create with default title
    async def _title_timeout_worker(tok: str):
        try:
            await asyncio.sleep(45)
            item = PENDING_NAMING.get(tok)
            if item and item.get("waiting_input") == "title":
                PENDING_NAMING.pop(tok, None)
                await finalize_filestore_creation(
                    client=item["client"],
                    user=item["user"],
                    title=item["default_title"],
                    files=item["files"],
                    status_msg=item["status_msg"],
                    used_today=item["used_today"],
                    daily_limit=item["daily_limit"],
                    is_single=item["is_single"],
                    protect_content=item.get("protect_content", False),
                    pin_code=item.get("pin_code"),
                    expire_seconds=item.get("expire_seconds"),
                    max_downloads=item.get("max_downloads")
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in title timeout worker: {e}")

    p["timer_task"] = asyncio.create_task(_title_timeout_worker(token))

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data=f"opt_back_{token}")]])
    await query.message.edit_text(
        "✏️ <b>Enter Custom Title:</b>\n\n"
        "Send your desired name/title as a text message in this chat:\n"
        f"<i>(Current: <code>{p['default_title']}</code>)</i>\n\n"
        "💡 <i>Once sent, the title will update and you can configure PIN / Expiry or tap Confirm!</i>",
        reply_markup=back_btn
    )


@Client.on_callback_query(filters.regex(r"^opt_prot_([a-zA-Z0-9_\-]+)$"))
async def opt_prot_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_prot_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired or already processed.", show_alert=True)
        return
    user_id = query.from_user.id
    if user_id != p["user_id"]:
        await query.answer("⛔ Only the link creator can change settings.", show_alert=True)
        return

    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if not is_vip:
        await query.answer("👑 Content Protection (Anti-Forward & Save Lock) is a VIP exclusive feature!\n\nUpgrade to VIP to enable this.", show_alert=True)
        return

    new_prot = not p.get("protect_content", False)
    p["protect_content"] = new_prot
    await query.answer(f"🔒 Content Protection {'ENABLED 🛡️' if new_prot else 'DISABLED 🔓'}!")
    prompt_text, markup = build_naming_prompt(p, token)
    try:
        await query.message.edit_text(prompt_text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^opt_pin_([a-zA-Z0-9_\-]+)$"))
async def opt_pin_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_pin_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired or already processed.", show_alert=True)
        return
    user_id = query.from_user.id
    if user_id != p["user_id"]:
        await query.answer("⛔ Only the link creator can change settings.", show_alert=True)
        return

    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if not is_vip:
        await query.answer("👑 4-Digit PIN Security is a VIP exclusive feature!\n\nUpgrade to VIP to enable this.", show_alert=True)
        return

    if p.get("timer_task"):
        p["timer_task"].cancel()

    await query.answer()
    text, markup = build_pin_menu(p, token)
    await query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^opt_pin_rnd_([a-zA-Z0-9_\-]+)$"))
async def opt_pin_rnd_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_pin_rnd_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    rnd_pin = str(random.randint(1000, 9999))
    p["pin_code"] = rnd_pin
    p["waiting_input"] = None
    await query.answer(f"🔑 PIN set to: {rnd_pin}!", show_alert=True)
    text, markup = build_naming_prompt(p, token)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^opt_pin_type_([a-zA-Z0-9_\-]+)$"))
async def opt_pin_type_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_pin_type_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["waiting_input"] = "pin"
    await query.answer()
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to PIN Menu", callback_data=f"opt_pin_{token}")]])
    await query.message.edit_text(
        "✏️ <b>Enter Custom 4-Digit PIN:</b>\n\n"
        "Send your desired 4-digit numeric code (e.g. <code>4821</code>):",
        reply_markup=back_btn
    )


@Client.on_callback_query(filters.regex(r"^opt_pin_clr_([a-zA-Z0-9_\-]+)$"))
async def opt_pin_clr_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_pin_clr_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["pin_code"] = None
    p["waiting_input"] = None
    await query.answer("🔓 PIN protection removed.")
    text, markup = build_naming_prompt(p, token)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^opt_exp_([a-zA-Z0-9_\-]+)$"))
async def opt_exp_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_exp_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired or already processed.", show_alert=True)
        return
    user_id = query.from_user.id
    if user_id != p["user_id"]:
        await query.answer("⛔ Only the link creator can change settings.", show_alert=True)
        return

    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if not is_vip:
        await query.answer("👑 Self-Destruct Timers & Limits are VIP exclusive features!\n\nUpgrade to VIP to enable this.", show_alert=True)
        return

    if p.get("timer_task"):
        p["timer_task"].cancel()

    await query.answer()
    text, markup = build_expiry_menu(p, token)
    await query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^exp_t_([a-zA-Z0-9_\-]+)_(\d+)$"))
async def exp_time_preset_callback(client: Client, query: CallbackQuery):
    parts = query.data.split("_")
    token = parts[2]
    secs = int(parts[3])
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["expire_seconds"] = secs if secs > 0 else None
    await query.answer("⏱️ Expiry time updated!")
    text, markup = build_expiry_menu(p, token)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^exp_t_cust_([a-zA-Z0-9_\-]+)$"))
async def exp_time_custom_callback(client: Client, query: CallbackQuery):
    token = query.data.split("exp_t_cust_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["waiting_input"] = "custom_time"
    await query.answer()
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Expiry Menu", callback_data=f"opt_exp_{token}")]])
    await query.message.edit_text(
        "⏱️ <b>Enter Custom Expiry Duration:</b>\n\n"
        "Send your desired duration (e.g. <code>45m</code> for 45 mins, <code>3h</code> for 3 hours, <code>2d</code> for 2 days):",
        reply_markup=back_btn
    )


@Client.on_callback_query(filters.regex(r"^exp_d_([a-zA-Z0-9_\-]+)_(\d+)$"))
async def exp_dl_preset_callback(client: Client, query: CallbackQuery):
    parts = query.data.split("_")
    token = parts[2]
    max_d = int(parts[3])
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["max_downloads"] = max_d if max_d > 0 else None
    await query.answer("🎯 Download limit updated!")
    text, markup = build_expiry_menu(p, token)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^exp_d_cust_([a-zA-Z0-9_\-]+)$"))
async def exp_dl_custom_callback(client: Client, query: CallbackQuery):
    token = query.data.split("exp_d_cust_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["waiting_input"] = "custom_limit"
    await query.answer()
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Expiry Menu", callback_data=f"opt_exp_{token}")]])
    await query.message.edit_text(
        "🎯 <b>Enter Custom Download Limit:</b>\n\n"
        "Send max download count as a number (e.g. <code>25</code> or <code>200</code>):",
        reply_markup=back_btn
    )


@Client.on_callback_query(filters.regex(r"^opt_back_([a-zA-Z0-9_\-]+)$"))
async def opt_back_callback(client: Client, query: CallbackQuery):
    token = query.data.split("opt_back_")[1]
    p = PENDING_NAMING.get(token)
    if not p:
        await query.answer("⚠️ Session expired.", show_alert=True)
        return
    p["waiting_input"] = None
    await query.answer()
    text, markup = build_naming_prompt(p, token)
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    restart_naming_timer(token, 15)


@Client.on_callback_query(filters.regex(r"^name_confirm_([a-zA-Z0-9_\-]+)$"))
async def name_confirm_callback(client: Client, query: CallbackQuery):
    token = query.data.split("name_confirm_")[1]
    p = PENDING_NAMING.pop(token, None)
    if not p:
        await query.answer("⚠️ Session expired or already processed.", show_alert=True)
        return

    if query.from_user.id != p["user_id"]:
        await query.answer("⛔ Only the link creator can confirm this.", show_alert=True)
        PENDING_NAMING[token] = p
        return

    if p.get("timer_task"):
        p["timer_task"].cancel()

    await query.answer("⚡ Creating link with selected settings...")
    await finalize_filestore_creation(
        client=p["client"],
        user=p["user"],
        title=p["default_title"],
        files=p["files"],
        status_msg=p["status_msg"],
        used_today=p["used_today"],
        daily_limit=p["daily_limit"],
        is_single=p["is_single"],
        protect_content=p.get("protect_content", False),
        pin_code=p.get("pin_code"),
        expire_seconds=p.get("expire_seconds"),
        max_downloads=p.get("max_downloads")
    )


@Client.on_callback_query(filters.regex(r"^name_cancel_([a-zA-Z0-9_\-]+)$"))
async def name_cancel_callback(client: Client, query: CallbackQuery):
    token = query.data.split("name_cancel_")[1]
    p = PENDING_NAMING.pop(token, None)
    if not p:
        await query.answer("Already cancelled.")
        return

    if p.get("timer_task"):
        p["timer_task"].cancel()

    await query.answer("❌ Cancelled.", show_alert=False)
    await query.message.edit_text("❌ <b>Link creation cancelled.</b>")


@Client.on_message(filters.text & filters.private & ~filters.command(["start", "cancel", "batch", "genlink", "link", "help", "batches", "delbatch", "done"]), group=-1)
async def custom_title_text_receiver(client: Client, message: Message):
    user_id = message.from_user.id
    input_text = message.text.strip()

    # 1. Check if user is typing PIN in chat to unlock a file
    active_pin_session = None
    for (uid, bid), buf in list(PIN_INPUT_BUFFER.items()):
        if uid == user_id:
            active_pin_session = bid
            break

    if active_pin_session and re.match(r"^\d{4}$", input_text):
        batch_doc = await get_batch(active_pin_session)
        if batch_doc:
            req_pin = batch_doc.get("pin_code")
            s_key = (user_id, active_pin_session)
            if input_text == req_pin:
                VERIFIED_PIN_SESSIONS.add(s_key)
                PIN_INPUT_BUFFER.pop(s_key, None)
                PIN_ATTEMPTS.pop(s_key, None)
                await message.reply_text("✅ <b>PIN Verified!</b> Delivering files...")
                await deliver_batch_files_to_user(client, user_id, batch_doc, message)
                try:
                    message.stop_propagation()
                except Exception:
                    pass
                return
            else:
                att = PIN_ATTEMPTS.get(s_key, 0) + 1
                PIN_ATTEMPTS[s_key] = att
                if att >= 3:
                    await message.reply_text("⛔ <b>Maximum PIN attempts exceeded.</b> Access denied.")
                    PIN_INPUT_BUFFER.pop(s_key, None)
                else:
                    await message.reply_text(f"❌ <b>Incorrect PIN!</b> ({att}/3 attempts used). Try again:")
                try:
                    message.stop_propagation()
                except Exception:
                    pass
                return

    # 2. Check pending creation config
    matched_token = None
    for tok, p in list(PENDING_NAMING.items()):
        if p.get("user_id") == user_id and p.get("waiting_input"):
            matched_token = tok
            break

    if not matched_token:
        return

    p = PENDING_NAMING[matched_token]
    w_mode = p.get("waiting_input")

    if w_mode == "title":
        clean_title = input_text.strip()
        p["default_title"] = clean_title
        p["waiting_input"] = None

        if p.get("timer_task"):
            try:
                p["timer_task"].cancel()
            except Exception:
                pass

        await message.reply_text(
            f"✅ <b>Title set to:</b> <code>{clean_title}</code>\n"
            "⌛ <i>Auto-creating link in 15 seconds if no further changes...</i>\n"
            "👉 <i>You can now configure PIN / Self-Destruct / Protection, or tap <b>'Confirm & Create Now'</b>!</i>"
        )

        text, markup = build_naming_prompt(p, matched_token)
        try:
            await p["status_msg"].edit_text(text, reply_markup=markup)
        except Exception:
            pass
        restart_naming_timer(matched_token, 15)
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    elif w_mode == "pin":
        if not re.match(r"^\d{4}$", input_text):
            await message.reply_text("⚠️ <b>Invalid PIN:</b> Please send exactly 4 digits (e.g. <code>1234</code>):")
            try:
                message.stop_propagation()
            except Exception:
                pass
            return
        p["pin_code"] = input_text
        p["waiting_input"] = None
        await message.reply_text(
            f"✅ <b>Security PIN set to:</b> <code>{input_text}</code>\n"
            "⌛ <i>Auto-creating link in 15 seconds if no further changes...</i>"
        )
        text, markup = build_naming_prompt(p, matched_token)
        try:
            await p["status_msg"].edit_text(text, reply_markup=markup)
        except Exception:
            pass
        restart_naming_timer(matched_token, 15)
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    elif w_mode == "custom_time":
        secs = parse_time_duration(input_text)
        if not secs:
            await message.reply_text("⚠️ <b>Invalid format:</b> Examples: <code>45m</code> (45 mins), <code>3h</code> (3 hours), <code>2d</code> (2 days). Try again:")
            try:
                message.stop_propagation()
            except Exception:
                pass
            return
        p["expire_seconds"] = secs
        p["waiting_input"] = None
        await message.reply_text(
            "✅ <b>Self-destruct time set successfully!</b>\n"
            "⌛ <i>Auto-creating link in 15 seconds if no further changes...</i>"
        )
        text, markup = build_naming_prompt(p, matched_token)
        try:
            await p["status_msg"].edit_text(text, reply_markup=markup)
        except Exception:
            pass
        restart_naming_timer(matched_token, 15)
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    elif w_mode == "custom_limit":
        if not (input_text.isdigit() and int(input_text) > 0):
            await message.reply_text("⚠️ <b>Invalid limit:</b> Please send a positive number (e.g. <code>25</code> or <code>100</code>):")
            try:
                message.stop_propagation()
            except Exception:
                pass
            return
        p["max_downloads"] = int(input_text)
        p["waiting_input"] = None
        await message.reply_text(
            f"✅ <b>Download limit set to:</b> <code>{input_text}</code> downloads\n"
            "⌛ <i>Auto-creating link in 15 seconds if no further changes...</i>"
        )
        text, markup = build_naming_prompt(p, matched_token)
        try:
            await p["status_msg"].edit_text(text, reply_markup=markup)
        except Exception:
            pass
        restart_naming_timer(matched_token, 15)
        try:
            message.stop_propagation()
        except Exception:
            pass
        return


# ==========================================
# 1. /batch Command (Range or Interactive)
# ==========================================
@Client.on_message(filters.command("batch") & filters.private)
async def batch_command_handler(client: Client, message: Message):
    """
    Generate shareable batch links from a channel range or launch interactive collector.
    Usage:
      /batch <link1> <link2> [Optional Title]
      /batch <link_with_range_e.g._10-20> [Optional Title]
      /batch (launches interactive multi-file collector in PM)
    """
    user_id = message.from_user.id
    if not Config.FILE_STORE_USERS_ENABLED and not Config.is_admin(user_id):
        await message.reply_text("⛔ File Store creation is currently restricted to Administrators.")
        return

    allowed, used_today, daily_limit = await can_user_create_filestore_link(user_id)
    if not allowed:
        text, markup = format_daily_quota_reached_msg(daily_limit)
        await message.reply_text(text, reply_markup=markup)
        return

    args = message.text.split(maxsplit=3)[1:]

    # Mode A: Range from channel links
    if args:
        first_arg = args[0]
        c_id, start_id, end_id = parse_channel_post_link(first_arg)

        # Check if second arg is an end link or number
        title = ""
        if len(args) > 1 and ("t.me/" in args[1] or args[1].isdigit()):
            _, s2, e2 = parse_channel_post_link(args[1])
            if s2:
                end_id = s2
            elif args[1].isdigit():
                end_id = int(args[1])
            title = args[2] if len(args) > 2 else ""
        else:
            title = args[1] if len(args) > 1 else ""

        if not c_id or not start_id or not end_id:
            await message.reply_text(
                "⚠️ <b>Invalid link format!</b>\n\n"
                "<b>Usage:</b>\n"
                "• <code>/batch https://t.me/c/123/10 https://t.me/c/123/20 [Title]</code>\n"
                "• <code>/batch https://t.me/c/123/10-20 [Title]</code>\n\n"
                "💡 Or send <code>/batch</code> with no arguments to collect files interactively in PM."
            )
            return

        if start_id > end_id:
            start_id, end_id = end_id, start_id

        total_msgs = end_id - start_id + 1
        if total_msgs > 100:
            await message.reply_text("⚠️ <b>Batch limit exceeded:</b> Maximum 100 messages can be packed per batch.")
            return

        status_msg = await message.reply_text(f"⏳ <b>Scanning {total_msgs} messages from channel...</b>")

        msg_ids = list(range(start_id, end_id + 1))
        collected_files = []

        try:
            messages = await client.get_messages(c_id, msg_ids)
            if not isinstance(messages, list):
                messages = [messages]

            for msg in messages:
                if msg:
                    f_info = extract_media_from_message(msg)
                    if f_info:
                        collected_files.append(f_info)

        except Exception as e:
            logger.error(f"Error reading channel range: {e}")
            await status_msg.edit_text(f"❌ <b>Failed to fetch channel messages:</b> <code>{e}</code>\n\nEnsure bot is Admin in the channel!")
            return

        if not collected_files:
            await status_msg.edit_text("❌ <b>No media files found in the specified range.</b>")
            return

        first_clean = collected_files[0].get("file_name", "File")
        default_title = first_clean if len(collected_files) == 1 else f"{first_clean} Pack ({len(collected_files)} Files)"

        await prompt_naming_or_finalize(
            client=client,
            message=message,
            files=collected_files,
            custom_title=title.strip() if title else None,
            default_title=default_title,
            status_msg=status_msg,
            used_today=used_today,
            daily_limit=daily_limit,
            is_single=(len(collected_files) == 1)
        )
        return

    # Mode B: Interactive Collector in PM
    AWAITING_BATCH_FILES[user_id] = {"files": [], "title": None}
    await message.reply_text(
        "📦 <b><u>Interactive Batch Link Builder</u></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Forward or send files, videos, audios, photos, or documents you want to pack into this batch!\n\n"
        "• Each item you send will be added to your current batch.\n"
        "• When finished, send: <code>/done [Optional Title]</code>\n"
        "• You can configure <b>Title, PIN Lock, Self-Destruct, & Content Protection</b> before final creation!\n"
        "• Send <code>/cancel</code> anytime to abort.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👉 <i>Send your first media file now:</i>"
    )


# ==========================================
# 2. Interactive Collector Message Receiver
# ==========================================
@Client.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo | filters.animation | filters.voice))
async def interactive_batch_file_receiver(client: Client, message: Message):
    """Accumulate files sent by user while in interactive batch mode."""
    user_id = message.from_user.id
    if user_id not in AWAITING_BATCH_FILES:
        return

    f_info = extract_media_from_message(message)
    if not f_info:
        return

    batch_state = AWAITING_BATCH_FILES[user_id]
    batch_state["files"].append(f_info)

    curr_count = len(batch_state["files"])
    file_name = f_info["file_name"]
    file_sz = get_readable_size(f_info["file_size"])

    await message.reply_text(
        f"✅ <b>Added #{curr_count}:</b> <code>{file_name}</code> ({file_sz})\n"
        f"📦 <b>Current Batch Size:</b> {curr_count} files\n\n"
        f"<i>Send more files, or send <code>/done [Title]</code> when finished!</i>"
    )


# ==========================================
# 3. /done Command (Finish Interactive Batch)
# ==========================================
@Client.on_message(filters.command("done") & filters.private)
async def batch_done_handler(client: Client, message: Message):
    """Finalize interactive batch collection, archive to storage channel and generate shareable link."""
    user_id = message.from_user.id
    if user_id not in AWAITING_BATCH_FILES:
        return

    batch_state = AWAITING_BATCH_FILES.pop(user_id)
    collected_files = batch_state.get("files", [])

    if not collected_files:
        await message.reply_text("❌ <b>No files were added.</b> Batch collection cancelled.")
        return

    allowed, used_today, daily_limit = await can_user_create_filestore_link(user_id)
    if not allowed:
        text, markup = format_daily_quota_reached_msg(daily_limit)
        await message.reply_text(text, reply_markup=markup)
        return

    args = message.text.split(maxsplit=1)
    custom_title = args[1].strip() if len(args) > 1 else None
    first_clean = collected_files[0].get("file_name", "File")
    default_title = first_clean if len(collected_files) == 1 else f"{first_clean} Pack ({len(collected_files)} Files)"

    status_msg = await message.reply_text("⏳ <b>Processing batch files...</b>")

    await prompt_naming_or_finalize(
        client=client,
        message=message,
        files=collected_files,
        custom_title=custom_title,
        default_title=default_title,
        status_msg=status_msg,
        used_today=used_today,
        daily_limit=daily_limit,
        is_single=(len(collected_files) == 1)
    )


# ==========================================
# 4. /cancel Command (Abort Batch Builder)
# ==========================================
@Client.on_message(filters.command("cancel") & filters.private)
async def batch_cancel_handler(client: Client, message: Message):
    user_id = message.from_user.id
    cancelled = False
    if user_id in AWAITING_BATCH_FILES:
        AWAITING_BATCH_FILES.pop(user_id, None)
        cancelled = True

    for tok, p in list(PENDING_NAMING.items()):
        if p.get("user_id") == user_id:
            if p.get("timer_task"):
                p["timer_task"].cancel()
            PENDING_NAMING.pop(tok, None)
            cancelled = True

    if cancelled:
        await message.reply_text("❌ <b>Operation cancelled.</b>")
    else:
        await message.reply_text("ℹ️ No active batch or naming session to cancel.")


# ==========================================
# 5. /genlink / /link (Instant Single Link)
# ==========================================
@Client.on_message(filters.command(["genlink", "link"]))
async def genlink_command_handler(client: Client, message: Message):
    """Generate instant shareable link for a single replied media file."""
    user_id = message.from_user.id if message.from_user else 0
    if not Config.FILE_STORE_USERS_ENABLED and not Config.is_admin(user_id):
        await message.reply_text("⛔ File Store creation is currently restricted to Administrators.")
        return

    allowed, used_today, daily_limit = await can_user_create_filestore_link(user_id)
    if not allowed:
        text, markup = format_daily_quota_reached_msg(daily_limit)
        await message.reply_text(text, reply_markup=markup)
        return

    reply = message.reply_to_message
    if not reply or not (reply.document or reply.video or reply.audio or reply.photo or reply.animation or reply.voice):
        await message.reply_text("⚠️ <b>Please reply to a media file</b> with <code>/genlink [Optional Title]</code>.")
        return

    f_info = extract_media_from_message(reply)
    if not f_info:
        await message.reply_text("❌ Could not extract file information from replied message.")
        return

    args = message.text.split(maxsplit=1)
    custom_title = args[1].strip() if len(args) > 1 else None
    default_title = f_info["file_name"]

    status_msg = await message.reply_text("⏳ <b>Processing file...</b>")

    await prompt_naming_or_finalize(
        client=client,
        message=message,
        files=[f_info],
        custom_title=custom_title,
        default_title=default_title,
        status_msg=status_msg,
        used_today=used_today,
        daily_limit=daily_limit,
        is_single=True
    )


# ==========================================
# 6. /batches / /batchlist (Dashboard)
# ==========================================
@Client.on_message(filters.command(["batches", "batchlist"]) & filters.private)
async def list_batches_command(client: Client, message: Message):
    """Display batch dashboard (Global for Admins, Personal for Users)."""
    user_id = message.from_user.id
    is_adm = Config.is_admin(user_id)

    if is_adm:
        batches = await get_recent_batches(limit=10)
        total_b = await count_total_batches()
        header_title = "📊 <b><u>GLOBAL BATCH COLLECTIONS DASHBOARD (ADMIN)</u></b>"
        extra_info = f"• <b>Total Global Batches:</b> <code>{total_b}</code>\n"
    else:
        batches = await get_user_batches(created_by=user_id, limit=10)
        header_title = "📦 <b><u>MY SAVED BATCH COLLECTIONS</u></b>"
        allowed, used_today, daily_limit = await can_user_create_filestore_link(user_id)
        is_vip = await is_premium(user_id)
        quota_str = "Unlimited 👑" if is_vip else f"{used_today}/{daily_limit} used today"
        extra_info = f"• <b>Daily Quota:</b> <code>{quota_str}</code>\n"

    if not batches:
        await message.reply_text(
            "ℹ️ <b>No batch links found.</b>\n\n"
            "Use <code>/batch</code> or reply to any file with <code>/genlink</code> to create your first shareable link!"
        )
        return

    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    text = (
        f"{header_title}\n"
        f"{extra_info}"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    btn_rows = []
    for i, b in enumerate(batches, 1):
        b_id = b["batch_id"]
        title = b.get("title", "Batch")[:24]
        n_files = b.get("total_files", 0)
        n_dl = b.get("downloads_count", 0)
        n_v = b.get("views_count", 0)
        sz = get_readable_size(b.get("total_size", 0))
        is_prot = bool(b.get("protect_content", False))
        prot_str = "Active 🛡️" if is_prot else "Off 🔓"
        prot_btn_label = "🛡️ Prot: ON" if is_prot else "🔒 Prot: OFF"

        prefix = "file" if n_files <= 1 else "batch"
        text += (
            f"<b>{i}. {title}</b>\n"
            f"   📁 <code>{n_files} Files</code> • 📦 <code>{sz}</code>\n"
            f"   🛡️ <b>Protection:</b> <code>{prot_str}</code>\n"
            f"   👁️ <code>{n_v} Views</code> • 📥 <code>{n_dl} Downloads</code>\n"
            f"   🔗 <code>t.me/{bot_username}?start={prefix}_{b_id}</code>\n\n"
        )
        btn_rows.append([
            InlineKeyboardButton(prot_btn_label, callback_data=f"toggle_prot_{b_id}"),
            InlineKeyboardButton(f"🗑️ Delete #{i}", callback_data=f"delbatch_cb_{b_id}")
        ])

    btn_rows.append([InlineKeyboardButton("❌ Close Dashboard", callback_data="close_stream_hub")])
    markup = InlineKeyboardMarkup(btn_rows)

    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^toggle_prot_([a-zA-Z0-9_\-]+)$"))
async def toggle_batch_prot_callback(client: Client, query: CallbackQuery):
    """Toggle protection setting live from dashboard (VIP/Admins only)."""
    batch_id = query.data.split("toggle_prot_")[1]
    user_id = query.from_user.id

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await query.answer("❌ Batch link not found.", show_alert=True)
        return

    is_adm = Config.is_admin(user_id)
    is_vip = await is_premium(user_id)

    if not is_adm and batch_doc.get("created_by") != user_id:
        await query.answer("⛔ You can only modify settings for your own links.", show_alert=True)
        return

    if not is_adm and not is_vip:
        await query.answer(
            "👑 Content Protection (Anti-Forward & Save Lock) is an exclusive VIP feature!\n\nUpgrade to VIP to enable this.",
            show_alert=True
        )
        return

    from database.batches import toggle_batch_protection
    new_state = await toggle_batch_protection(batch_id)
    if new_state is None:
        await query.answer("❌ Failed to update protection setting.", show_alert=True)
        return

    status_str = "ENABLED 🛡️ (Anti-Forward Locked)" if new_state else "DISABLED 🔓 (Forward Allowed)"
    await query.answer(f"Content Protection {status_str}!", show_alert=True)

    # Re-render dashboard
    if is_adm:
        batches = await get_recent_batches(limit=10)
        total_b = await count_total_batches()
        header_title = "📊 <b><u>GLOBAL BATCH COLLECTIONS DASHBOARD (ADMIN)</u></b>"
        extra_info = f"• <b>Total Global Batches:</b> <code>{total_b}</code>\n"
    else:
        batches = await get_user_batches(created_by=user_id, limit=10)
        header_title = "📦 <b><u>MY SAVED BATCH COLLECTIONS</u></b>"
        allowed, used_today, daily_limit = await can_user_create_filestore_link(user_id)
        quota_str = "Unlimited 👑" if is_vip else f"{used_today}/{daily_limit} used today"
        extra_info = f"• <b>Daily Quota:</b> <code>{quota_str}</code>\n"

    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    text = (
        f"{header_title}\n"
        f"{extra_info}"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    btn_rows = []
    for i, b in enumerate(batches, 1):
        b_id = b["batch_id"]
        title = b.get("title", "Batch")[:24]
        n_files = b.get("total_files", 0)
        n_dl = b.get("downloads_count", 0)
        n_v = b.get("views_count", 0)
        sz = get_readable_size(b.get("total_size", 0))
        is_prot = bool(b.get("protect_content", False))
        prot_str = "Active 🛡️" if is_prot else "Off 🔓"
        prot_btn_label = "🛡️ Prot: ON" if is_prot else "🔒 Prot: OFF"

        prefix = "file" if n_files <= 1 else "batch"
        text += (
            f"<b>{i}. {title}</b>\n"
            f"   📁 <code>{n_files} Files</code> • 📦 <code>{sz}</code>\n"
            f"   🛡️ <b>Protection:</b> <code>{prot_str}</code>\n"
            f"   👁️ <code>{n_v} Views</code> • 📥 <code>{n_dl} Downloads</code>\n"
            f"   🔗 <code>t.me/{bot_username}?start={prefix}_{b_id}</code>\n\n"
        )
        btn_rows.append([
            InlineKeyboardButton(prot_btn_label, callback_data=f"toggle_prot_{b_id}"),
            InlineKeyboardButton(f"🗑️ Delete #{i}", callback_data=f"delbatch_cb_{b_id}")
        ])

    btn_rows.append([InlineKeyboardButton("❌ Close Dashboard", callback_data="close_stream_hub")])
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btn_rows), disable_web_page_preview=True)
    except Exception:
        pass


# ==========================================
# 7. /delbatch <batch_id>
# ==========================================
@Client.on_message(filters.command("delbatch") & filters.private)
async def delete_batch_command(client: Client, message: Message):
    """Delete a batch link by ID."""
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/delbatch &lt;batch_id&gt;</code>\nExample: <code>/delbatch a1b2c3d4</code>")
        return

    b_id = args[1].strip()
    batch_doc = await get_batch(b_id)
    if not batch_doc:
        await message.reply_text(f"❌ <b>Batch <code>{b_id}</code> not found.</b>")
        return

    if not Config.is_admin(user_id) and batch_doc.get("created_by") != user_id:
        await message.reply_text("⛔ <b>Unauthorized:</b> You can only delete batches created by your account.")
        return

    success = await delete_batch(b_id)
    if success:
        await message.reply_text(f"✅ <b>Batch <code>{b_id}</code> has been permanently deleted.</b>")
    else:
        await message.reply_text(f"❌ <b>Failed to delete batch <code>{b_id}</code>.</b>")


# ==========================================
# 8. Multi-CDN Media Uploader (/tgm)
# ==========================================
async def upload_media_to_cdn(file_path: str, filename: str = "media.jpg", mime_type: str = "image/jpeg") -> tuple[str | None, str | None]:
    """
    Intelligent Size-based CDN Routing:
      • Under 10 MB:
          1. If <= 5 MB: Try Graph.org (Telegraph CDN) first.
          2. Try ImgBB API (if IMGBB_API_KEY configured).
          3. Fallback to Catbox.moe if Graph/ImgBB fails.
      • 10 MB to 50 MB:
          Directly upload to Catbox CDN (catbox.moe).
      • Above 50 MB:
          Rejected (exceeds 50MB limit).
    Returns (url, provider_name).
    """
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    if file_size > 50 * 1024 * 1024:
        logger.warning(f"File {filename} ({file_size} bytes) exceeds 50MB CDN limit.")
        return None, "LIMIT_EXCEEDED"

    # Tier 1: Under 10 MB (Graph.org or ImgBB, with Catbox safety net)
    if file_size < 10 * 1024 * 1024:
        # A. Try Graph.org (up to 5MB supported)
        if file_size <= 5 * 1024 * 1024:
            try:
                async with aiohttp.ClientSession() as session:
                    with open(file_path, "rb") as f:
                        data = aiohttp.FormData()
                        data.add_field("file", f, filename=filename)
                        async with session.post("https://graph.org/upload", data=data, timeout=10) as resp:
                            if resp.status == 200:
                                res_json = await resp.json()
                                if isinstance(res_json, list) and len(res_json) > 0 and "src" in res_json[0]:
                                    return f"https://graph.org{res_json[0]['src']}", "Graph.org (Telegraph CDN)"
            except Exception as e:
                logger.warning(f"Graph.org upload failed: {e}. Trying ImgBB...")

        # B. Try ImgBB (up to 32MB supported)
        imgbb_key = getattr(Config, "IMGBB_API_KEY", "") or os.environ.get("IMGBB_API_KEY", "")
        if imgbb_key:
            try:
                import base64
                with open(file_path, "rb") as f:
                    b64_content = base64.b64encode(f.read()).decode("utf-8")
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json"
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    data = aiohttp.FormData()
                    data.add_field("image", b64_content)
                    async with session.post(f"https://api.imgbb.com/1/upload?key={imgbb_key}", data=data, timeout=12) as resp:
                        if resp.status == 200:
                            res_json = await resp.json()
                            if res_json.get("success") and "data" in res_json and "url" in res_json["data"]:
                                return res_json["data"]["url"], "ImgBB CDN"
            except Exception as e:
                logger.warning(f"ImgBB upload failed: {e}. Falling back to Catbox...")

        # C. Fallback for <10MB if both Graph and ImgBB failed
        try:
            async with aiohttp.ClientSession() as session:
                with open(file_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("reqtype", "fileupload")
                    data.add_field("fileToUpload", f, filename=filename, content_type=mime_type)
                    async with session.post("https://catbox.moe/user/api.php", data=data, timeout=15) as resp:
                        if resp.status == 200:
                            url = (await resp.text()).strip()
                            if url.startswith("http"):
                                return url, "Catbox CDN (Auto-Fallback)"
        except Exception as e:
            logger.error(f"Catbox fallback failed: {e}")

    # Tier 2: 10 MB to 50 MB (Direct to Catbox)
    else:
        try:
            async with aiohttp.ClientSession() as session:
                with open(file_path, "rb") as f:
                    data = aiohttp.FormData()
                    data.add_field("reqtype", "fileupload")
                    data.add_field("fileToUpload", f, filename=filename, content_type=mime_type)
                    async with session.post("https://catbox.moe/user/api.php", data=data, timeout=25) as resp:
                        if resp.status == 200:
                            url = (await resp.text()).strip()
                            if url.startswith("http"):
                                return url, "Catbox CDN (10-50MB)"
        except Exception as e:
            logger.error(f"Catbox upload failed for 10-50MB media: {e}")

    return None, None


@Client.on_message(filters.command(["tgm", "img", "cdn"]))
async def telegraph_uploader(client: Client, message: Message):
    """Upload replied photo, sticker, animation, or video to Telegraph / Multi-CDN."""
    reply = message.reply_to_message
    if not reply or not (reply.photo or reply.sticker or reply.animation or reply.video or reply.document):
        await message.reply_text(
            "⚠️ <b>Please reply to an image, sticker, GIF, or video</b> with <code>/tgm</code> to get a direct CDN URL.\n\n"
            "📏 <b>Size Routing:</b>\n"
            "• Under 10 MB ➔ Graph.org / ImgBB CDN\n"
            "• 10 MB to 50 MB ➔ Catbox CDN\n"
            "• Max limit: 50 MB"
        )
        return

    # Pre-check size before downloading to save bandwidth
    media = reply.document or reply.video or reply.animation or reply.sticker
    if media and getattr(media, "file_size", 0) > 50 * 1024 * 1024:
        await message.reply_text("⚠️ <b>File too large!</b> Maximum media size allowed for CDN upload is 50 MB.")
        return

    status_msg = await message.reply_text("⚡ <b>Uploading to CDN (Smart Size-Routing)...</b>")

    temp_path = None
    try:
        temp_path = await reply.download()
        if not temp_path or not os.path.exists(temp_path):
            await status_msg.edit_text("❌ Failed to download media from Telegram.")
            return

        filename = os.path.basename(temp_path)
        mime_type = "image/jpeg"
        if reply.video:
            mime_type = "video/mp4"
        elif reply.animation:
            mime_type = "video/mp4"
        elif reply.sticker:
            mime_type = "image/webp"
        elif reply.document and reply.document.mime_type:
            mime_type = reply.document.mime_type

        file_sz = get_readable_size(os.path.getsize(temp_path))
        cdn_url, provider = await upload_media_to_cdn(temp_path, filename=filename, mime_type=mime_type)

        if provider == "LIMIT_EXCEEDED":
            await status_msg.edit_text("⚠️ <b>File too large!</b> Maximum 50 MB media can be uploaded to CDN.")
            return

        if cdn_url:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Open Media ↗️", url=cdn_url)],
                [InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={urllib.parse.quote(cdn_url)}&text={urllib.parse.quote('Direct CDN Media Link:')}")]
            ])
            await status_msg.edit_text(
                "🚀 <b>MEDIA CDN LINK GENERATED!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌐 <b>Provider:</b> <code>{provider}</code>\n"
                f"📦 <b>Size:</b> <code>{file_sz}</code>\n\n"
                f"🔗 <b>Direct Link:</b>\n<code>{cdn_url}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>Tap the code block above to 1-Click Copy the URL!</i>",
                reply_markup=markup,
                disable_web_page_preview=False
            )
        else:
            await status_msg.edit_text("❌ Failed to upload media to any CDN. Please try again later.")

    except Exception as e:
        logger.error(f"Error in telegraph upload: {e}")
        await status_msg.edit_text(f"❌ <b>Upload Error:</b> <code>{e}</code>")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ==========================================
# 8B. Telegraph Instant View Page Creator (/paste, /tgraph)
# ==========================================
TELEGRAPH_TOKEN: str | None = None


async def get_telegraph_token() -> str | None:
    """Get or create cached Telegraph / Graph.org access token with MongoDB persistence."""
    global TELEGRAPH_TOKEN
    if TELEGRAPH_TOKEN:
        return TELEGRAPH_TOKEN

    try:
        from database.mongo import get_bot_setting, set_bot_setting
        saved_token = await get_bot_setting("telegraph_access_token")
        if saved_token:
            TELEGRAPH_TOKEN = saved_token
            return TELEGRAPH_TOKEN
    except Exception as db_err:
        logger.debug(f"Could not load telegraph token from DB: {db_err}")

    author_url = getattr(Config, "CHANNEL_URL", "") or "https://t.me/AkMovieVerse"
    payload = {
        "short_name": "AkMoviesZone",
        "author_name": "AkMovieVerse",
        "author_url": author_url
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.graph.org/createAccount",
                json=payload,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8
            ) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    if res.get("ok"):
                        TELEGRAPH_TOKEN = res["result"]["access_token"]
                        try:
                            from database.mongo import set_bot_setting
                            await set_bot_setting("telegraph_access_token", TELEGRAPH_TOKEN)
                        except Exception as save_err:
                            logger.error(f"Failed to persist telegraph token to MongoDB: {save_err}")
                        return TELEGRAPH_TOKEN
    except Exception as e:
        logger.error(f"Error creating Telegraph account on graph.org: {e}")
    return None


def extract_telegraph_path(url_or_path: str) -> str:
    """Extract page path slug from a Telegraph/graph.org URL or raw path."""
    raw = url_or_path.strip().split("?")[0].split("#")[0]
    if "/" in raw:
        return raw.rstrip("/").split("/")[-1]
    return raw


def text_to_telegraph_nodes(text: str) -> list[dict]:
    """Convert raw text or markdown into Telegraph JSON DOM nodes."""
    nodes = []
    lines = text.strip().split("\n")

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            nodes.append({"tag": "h4", "children": [line[4:].strip()]})
        elif line.startswith("## "):
            nodes.append({"tag": "h4", "children": [line[3:].strip()]})
        elif line.startswith("# "):
            nodes.append({"tag": "h3", "children": [line[2:].strip()]})
        elif line.startswith("> "):
            nodes.append({"tag": "blockquote", "children": [line[2:].strip()]})
        elif line.startswith("---") or line.startswith("===") or line.startswith("___"):
            nodes.append({"tag": "hr"})
        else:
            nodes.append({"tag": "p", "children": [line]})

    return nodes or [{"tag": "p", "children": [text]}]


async def create_telegraph_page(title: str, text: str, author_name: str = "AkMovieVerse", author_url: str = "") -> str | None:
    """Create a published Telegraph web page on graph.org."""
    token = await get_telegraph_token()
    if not token:
        return None

    nodes = text_to_telegraph_nodes(text)
    payload = {
        "access_token": token,
        "title": title[:250] if title else "Published Notes",
        "author_name": author_name[:120] if author_name else "AkMovieVerse",
        "author_url": author_url[:500] if author_url else (getattr(Config, "CHANNEL_URL", "") or "https://t.me/AkMovieVerse"),
        "content": nodes
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.graph.org/createPage",
                json=payload,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            ) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    if res.get("ok"):
                        return res["result"]["url"]
                    else:
                        logger.warning(f"createPage returned error: {res}")
    except Exception as e:
        logger.error(f"Error creating Telegraph page: {e}")

    return None


async def edit_telegraph_page(
    path: str,
    title: str,
    text: str,
    author_name: str = "AkMovieVerse",
    author_url: str = ""
) -> str | None:
    """Edit an existing Telegraph web page on graph.org using the persistent bot token."""
    token = await get_telegraph_token()
    if not token:
        return None

    clean_path = extract_telegraph_path(path)
    nodes = text_to_telegraph_nodes(text)
    payload = {
        "access_token": token,
        "path": clean_path,
        "title": title[:250] if title else "Updated Article",
        "author_name": author_name[:120] if author_name else "AkMovieVerse",
        "author_url": author_url[:500] if author_url else (getattr(Config, "CHANNEL_URL", "") or "https://t.me/AkMovieVerse"),
        "content": nodes
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.graph.org/editPage",
                json=payload,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            ) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    if res.get("ok"):
                        return res["result"]["url"]
                    else:
                        logger.warning(f"editPage returned error: {res}")
    except Exception as e:
        logger.error(f"Error editing Telegraph page {clean_path}: {e}")

    return None


@Client.on_message(filters.command(["paste", "tgraph", "telegraph"]))
async def paste_command_handler(client: Client, message: Message):
    """
    Publish text, movie lists, notes, or replied message/document into a Telegraph Instant View article.
    Usage:
      - Reply to any text message with /paste [Optional Title]
      - Reply to a .txt file with /paste [Title]
      - Or write: /paste <Title> | <Content>
      - Or write: /paste <Content>
    """
    reply = message.reply_to_message
    args = message.text.split(maxsplit=1)
    passed_text = args[1].strip() if len(args) > 1 else ""

    # Smart Routing: If user replied to an image/video/sticker with /telegraph, route to tgm!
    if reply and (reply.photo or reply.sticker or reply.animation or reply.video or (reply.document and reply.document.mime_type and "image" in reply.document.mime_type)):
        await telegraph_uploader(client, message)
        return

    content_to_publish = ""
    title = ""

    # Case 1: Replied to a document (.txt, .md, .log, etc.)
    if reply and reply.document:
        doc = reply.document
        if doc.file_size > 500 * 1024:
            await message.reply_text("⚠️ <b>File too large!</b> Maximum 500 KB text file can be published to Telegraph.")
            return
        status_msg = await message.reply_text("⏳ <b>Reading document content...</b>")
        temp_file = None
        try:
            temp_file = await reply.download()
            with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
                content_to_publish = f.read()
            title = passed_text or doc.file_name or "Document"
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to read document: <code>{e}</code>")
            return
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
    # Case 2: Replied to a text message
    elif reply and (reply.text or reply.caption):
        content_to_publish = reply.text or reply.caption
        title = passed_text or (content_to_publish.split("\n")[0][:60] if content_to_publish else "Telegraph Article")
        status_msg = await message.reply_text("⚡ <b>Publishing article to Telegraph (graph.org)...</b>")
    # Case 3: Text provided directly in command arguments
    elif passed_text:
        if "|" in passed_text:
            parts = passed_text.split("|", 1)
            title = parts[0].strip()
            content_to_publish = parts[1].strip()
        else:
            first_line = passed_text.split("\n")[0].strip()
            title = first_line[:60] if len(first_line) > 5 else "Telegraph Article"
            content_to_publish = passed_text
        status_msg = await message.reply_text("⚡ <b>Publishing article to Telegraph (graph.org)...</b>")
    else:
        # Help guide
        await message.reply_text(
            "📝 <b><u>Telegraph Article / Page Creator</u></b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Turn any text, collection list, or notes into a beautiful Telegraph Webpage with Instant View!\n\n"
            "<b>Usage:</b>\n"
            "• Reply to any text message with <code>/paste [Optional Title]</code>\n"
            "• Reply to a <code>.txt</code> file with <code>/paste [Title]</code>\n"
            "• Or write directly:\n"
            "  <code>/paste Title | Your detailed content here...</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Tip: Markdown headers (#, ##, >) are automatically styled!</i>"
        )
        return

    if not content_to_publish.strip():
        await status_msg.edit_text("❌ No text content found to publish.")
        return

    author_name = message.from_user.first_name if message.from_user else "AkMovieVerse"
    page_url = await create_telegraph_page(title=title, text=content_to_publish, author_name=author_name)

    if not page_url:
        await status_msg.edit_text("❌ Failed to create Telegraph article. Please try again later.")
        return

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Read on Telegraph (Instant View) ↗️", url=page_url)],
        [InlineKeyboardButton("📤 Share Article", url=f"https://t.me/share/url?url={urllib.parse.quote(page_url)}&text={urllib.parse.quote(f'📄 {title}:')}") ]
    ])

    await status_msg.edit_text(
        "🎉 <b>TELEGRAPH ARTICLE PUBLISHED!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📑 <b>Title:</b> <code>{title}</code>\n"
        f"🌐 <b>Article URL:</b>\n<code>{page_url}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Open the link in Telegram to view with Instant View!</i>",
        reply_markup=markup,
        disable_web_page_preview=False
    )


@Client.on_message(filters.command(["editpaste", "epaste"]))
async def edit_paste_command_handler(client: Client, message: Message):
    """
    Edit an existing Telegraph Instant View page created by the bot.
    The URL remains unchanged!
    Usage:
      - Reply to text or .txt file with:
        /editpaste <telegraph_link> [Optional New Title]
      - Direct command:
        /editpaste <telegraph_link> | <New Content>
      - Or:
        /editpaste <telegraph_link> New Title | <New Content>
    """
    reply = message.reply_to_message
    args = message.text.split(maxsplit=2)

    content_to_update = ""
    target_link = ""
    new_title = ""

    # Case 1: Replied to a document (.txt, .md, etc.)
    if reply and reply.document and len(args) > 1:
        target_link = args[1].strip()
        new_title = args[2].strip() if len(args) > 2 else ""
        doc = reply.document
        if doc.file_size > 500 * 1024:
            await message.reply_text("⚠️ <b>File too large!</b> Maximum 500 KB text file can be published to Telegraph.")
            return
        status_msg = await message.reply_text("⏳ <b>Reading updated document content...</b>")
        temp_file = None
        try:
            temp_file = await reply.download()
            with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
                content_to_update = f.read()
            new_title = new_title or doc.file_name or "Updated Document"
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to read document: <code>{e}</code>")
            return
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    # Case 2: Replied to a text message
    elif reply and (reply.text or reply.caption) and len(args) > 1:
        target_link = args[1].strip()
        new_title = args[2].strip() if len(args) > 2 else ""
        content_to_update = reply.text or reply.caption
        if not new_title:
            new_title = content_to_update.split("\n")[0][:60]
        status_msg = await message.reply_text("⚡ <b>Updating Telegraph article...</b>")

    # Case 3: Direct command format: /editpaste <url> | <content> or /editpaste <url> title | content
    elif len(message.text.split(maxsplit=1)) > 1:
        raw_tail = message.text.split(maxsplit=1)[1].strip()
        if "|" in raw_tail:
            first_part, content_to_update = raw_tail.split("|", 1)
            first_tokens = first_part.strip().split(maxsplit=1)
            target_link = first_tokens[0].strip()
            new_title = first_tokens[1].strip() if len(first_tokens) > 1 else ""
            content_to_update = content_to_update.strip()
            if not new_title:
                new_title = content_to_update.split("\n")[0][:60]
            status_msg = await message.reply_text("⚡ <b>Updating Telegraph article...</b>")
        else:
            await message.reply_text(
                "⚠️ <b>Invalid format!</b>\n\n"
                "<b>Usage:</b>\n"
                "• Reply to text with: <code>/editpaste &lt;link&gt; [New Title]</code>\n"
                "• Direct: <code>/editpaste &lt;link&gt; Title | New content here...</code>"
            )
            return
    else:
        # Help guide
        await message.reply_text(
            "✏️ <b><u>Telegraph Article Editor (/editpaste)</u></b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Edit and update any Telegraph page created by this bot — <b>The URL remains unchanged!</b>\n\n"
            "<b>Usage:</b>\n"
            "• <b>Option 1 (Reply to text or .txt file):</b>\n"
            "  <code>/editpaste https://graph.org/Sample-01 [New Title]</code>\n\n"
            "• <b>Option 2 (Direct Command):</b>\n"
            "  <code>/editpaste https://graph.org/Sample-01 New Title | Your updated content...</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return

    if not target_link or not content_to_update.strip():
        await status_msg.edit_text("❌ Please provide a valid Telegraph link and content to update.")
        return

    author_name = message.from_user.first_name if message.from_user else "AkMovieVerse"
    updated_url = await edit_telegraph_page(
        path=target_link,
        title=new_title or "Updated Article",
        text=content_to_update,
        author_name=author_name
    )

    if not updated_url:
        await status_msg.edit_text(
            "❌ <b>Update Failed!</b>\n\n"
            "Possible reasons:\n"
            "• The URL was not created by this bot\n"
            "• The link is invalid or malformed\n"
            "• Telegraph API temporary error"
        )
        return

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ View Updated Article (Instant View) ↗️", url=updated_url)],
        [InlineKeyboardButton("📤 Share Updated Link", url=f"https://t.me/share/url?url={urllib.parse.quote(updated_url)}&text={urllib.parse.quote(f'📄 {new_title}:')}")]
    ])

    await status_msg.edit_text(
        "🎉 <b>TELEGRAPH ARTICLE UPDATED SUCCESSFULLY!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📑 <b>Title:</b> <code>{new_title}</code>\n"
        f"🌐 <b>Permanent URL (Unchanged):</b>\n<code>{updated_url}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>The page has been updated live! Open in Telegram to view changes with Instant View.</i>",
        reply_markup=markup,
        disable_web_page_preview=False
    )


@Client.on_message(filters.command(["delpaste", "wipepaste"]))
async def delete_paste_command_handler(client: Client, message: Message):
    """
    Wipe all content from a Telegraph article created by the bot.
    Usage:
      /delpaste <telegraph_url>
      or reply to a message containing the link with /delpaste
    """
    args = message.text.split(maxsplit=1)
    target_link = ""

    if len(args) > 1:
        target_link = args[1].strip()
    elif message.reply_to_message:
        reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        m = re.search(r"https?://(?:graph\.org|telegra\.ph)/[^\s]+", reply_text)
        if m:
            target_link = m.group(0)

    if not target_link:
        await message.reply_text(
            "🗑️ <b><u>Telegraph Article Cleaner (/delpaste)</u></b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Wipe all content from any Telegraph article created by this bot.\n\n"
            "<b>Usage:</b>\n"
            "• <code>/delpaste https://graph.org/Sample-01</code>\n"
            "• Or reply to any message containing the Telegraph link with <code>/delpaste</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        return

    status_msg = await message.reply_text("⏳ <b>Wiping Telegraph article content...</b>")

    wipe_content = (
        "&gt; ⚠️ <b>This article has been permanently removed by the author.</b>\n\n"
        "<i>The content of this page is no longer available.</i>"
    )

    updated_url = await edit_telegraph_page(
        path=target_link,
        title="[Article Removed]",
        text=wipe_content,
        author_name="AkMovieVerse"
    )

    if not updated_url:
        await status_msg.edit_text(
            "❌ <b>Wipe Failed!</b>\n\n"
            "Ensure the Telegraph link was created by this bot and is valid."
        )
        return

    await status_msg.edit_text(
        "🗑️ <b>TELEGRAPH ARTICLE WIPED & CLEARED!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>Article URL:</b>\n<code>{updated_url}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>All content has been wiped clean. Anyone opening this link will see that it has been removed.</i>",
        disable_web_page_preview=True
    )



# ==========================================
# 9. Deep-link Handler: /start batch_<batch_id>
# ==========================================
async def handle_start_batch(client: Client, message: Message, batch_id: str):
    """Handle incoming user start deep-link for a batch collection."""
    user_id = message.from_user.id
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await message.reply_text(
            "❌ <b>Batch Link Expired or Invalid!</b>\n\n"
            "This collection link does not exist or has been removed by the administrator."
        )
        return

    # Check Self-Destruct / Expiration
    expired, exp_reason = is_batch_expired(batch_doc)
    if expired:
        await message.reply_text(
            "💥 <b>THIS LINK HAS EXPIRED & SELF-DESTRUCTED!</b>\n\n"
            f"⚠️ <b>Reason:</b> <code>{exp_reason}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 This link was configured with self-destruct limits (time duration or download count) and is no longer accessible."
        )
        return

    # Increment view analytics
    asyncio.create_task(increment_batch_views(batch_id))

    # FSub Verification
    is_member, unjoined = await check_fsub(client, user_id)
    if not is_member:
        markup = build_fsub_markup(unjoined, f"batch_{batch_id}")
        await message.reply_text(
            "📢 <b>Channel Membership Required!</b>\n\n"
            "To access this complete collection, you must first join our official update channel(s).\n"
            "Join using the button(s) below, then click <b>'Try Again'</b>:",
            reply_markup=markup
        )
        return

    # VIP check
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)

    # 24-Hour Session Verification (Free users must verify once every 24h)
    if not is_vip and not await is_user_verified(user_id):
        token = await create_verify_token(user_id, f"batch_{batch_id}")
        redirect_url = f"https://t.me/{bot_username}?start=verify_{token}"

        final_verify_url = None
        verify_markup = None
        verify_text = None

        if Config.SHORTENER_ENABLED:
            from utils.shortener import get_rotated_shortlink
            from database.verify import update_token_shortlink

            short_link, shortener_used = await get_rotated_shortlink(redirect_url)
            await update_token_shortlink(token, short_link, shortener_used)

            final_verify_url = f"{Config.WEB_URL}/verify/{token}" if Config.WEB_URL else short_link
            verify_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔓 Verify Access (24h Pass)", url=final_verify_url)],
                [InlineKeyboardButton("👑 Buy VIP (Skip Verification)", callback_data="view_plans")]
            ])
            verify_text = (
                "🔒 <b>24-Hour Verification Required!</b>\n\n"
                f"You are requesting: <b>{batch_doc.get('title', 'Collection')}</b> ({batch_doc.get('total_files', 0)} Files).\n\n"
                "⏱️ <b>Complete 1 quick verification to unlock 24 Hours of Unlimited Access to this batch and all other files!</b>"
            )
        elif getattr(Config, "WEB_URL", ""):
            from database.verify import update_token_shortlink
            await update_token_shortlink(token, redirect_url, "clean_gateway")
            final_verify_url = f"{Config.WEB_URL}/verify/{token}"

            verify_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡️ 1-Click Verification (24h Pass)", url=final_verify_url)],
                [InlineKeyboardButton("👑 VIP Members Skip All Checks", callback_data="view_plans")]
            ])
            verify_text = (
                "🛡️ <b>Quick Verification Required (Anti-Bot Check)</b>\n\n"
                f"Requesting: <b>{batch_doc.get('title', 'Collection')}</b> ({batch_doc.get('total_files', 0)} Files).\n\n"
                "Please complete a quick 5-second check to confirm you are human.\n"
                "⏱️ <b>Once done, you unlock 24 Hours of 100% Direct Downloads!</b>"
            )

        if final_verify_url and verify_markup:
            await message.reply_text(verify_text, reply_markup=verify_markup)
            return

    # Present Presentation Card (Differentiated for Single File vs Batch Pack)
    title = batch_doc.get("title", "File")
    files = batch_doc.get("files", [])
    n_files = batch_doc.get("total_files", len(files))
    total_sz_str = get_readable_size(batch_doc.get("total_size", 0))
    is_protected = bool(batch_doc.get("protect_content", False))
    del_label = "30 Minutes (Viewing Mode 🛡️)" if is_protected else ("30 Minutes (VIP Benefit 👑)" if is_vip else "5 Minutes (Auto-Delete ⏱️)")
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    pin_line = "🔒 <b>Access:</b> <code>PIN Protected 🔑</code>\n" if batch_doc.get("pin_code") else ""
    exp_lines = ""
    if batch_doc.get("expire_at"):
        exp_lines += f"⏱️ <b>Expires At:</b> <code>{batch_doc['expire_at'].strftime('%d %b %Y, %H:%M UTC')}</code>\n"
    if batch_doc.get("max_downloads"):
        cur_dl = batch_doc.get("downloads_count", 0)
        max_dl = batch_doc["max_downloads"]
        exp_lines += f"🎯 <b>Downloads:</b> <code>{cur_dl}/{max_dl} used</code>\n"

    if n_files <= 1:
        # Sleek Minimalist Single File Presentation Card
        if is_protected:
            caption = (
                f"🎬 <b><u>{title}</u></b>\n\n"
                f"{pin_line}"
                f"{exp_lines}"
                "🛡️ <b>Content Protection:</b> <code>Active (Anti-Forward Locked)</code>\n"
                f"⏱️ <b>Auto-Delete:</b> <code>30 Minutes (Viewing Mode)</code>\n"
                "<i>(Forwarding/Saving disabled by creator. Stream & watch inside Telegram!)</i>"
            )
        else:
            caption = (
                f"🎬 <b><u>{title}</u></b>\n\n"
                f"{pin_line}"
                f"{exp_lines}"
                f"⏱️ <b>Auto-Delete:</b> <code>{del_label}</code>\n"
                "<i>(Forward to 'Saved Messages' to keep forever)</i>"
            )
        share_url = f"https://t.me/{bot_username}?start=file_{batch_id}"
        tg_share = f"https://t.me/share/url?url={urllib.parse.quote(share_url)}&text={urllib.parse.quote(f'🎬 {title} ({total_sz_str})')}"
        btn_rows = [
            [InlineKeyboardButton(f"📥 Download File ({total_sz_str})", callback_data=f"sendbatch_{batch_id}")],
            [InlineKeyboardButton("📤 Share File", url=tg_share)]
        ]
    else:
        # Multi-file batch pack presentation card
        prot_line = "🛡️ <b>Protection:</b> <code>Active (Anti-Forward Locked)</code>\n" if is_protected else ""
        caption = (
            f"📦 <b><u>BATCH PACK: {title.upper()}</u></b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 <b>Total:</b> <code>{n_files} Episodes / Files</code>  •  💾 <code>{total_sz_str}</code>\n"
            f"{pin_line}"
            f"{exp_lines}"
            f"{prot_line}"
            f"⏱️ <b>Auto-Delete Time:</b> <code>{del_label}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>Tap below to receive all files directly in this chat:</b>"
        )
        share_url = f"https://t.me/{bot_username}?start=batch_{batch_id}"
        tg_share = f"https://t.me/share/url?url={urllib.parse.quote(share_url)}&text={urllib.parse.quote(f'🎬 {title} ({n_files} Files)')}"
        btn_rows = [
            [InlineKeyboardButton(f"📥 Send All ({n_files} Files • {total_sz_str})", callback_data=f"sendbatch_{batch_id}")],
            [InlineKeyboardButton("📋 View File List", callback_data=f"listbatch_{batch_id}_0")],
            [InlineKeyboardButton("📤 Share Batch Link", url=tg_share)]
        ]

    markup = InlineKeyboardMarkup(btn_rows)
    await message.reply_text(caption, reply_markup=markup)


# ==========================================
# 10. Callbacks: Send All & File List & Delete
# ==========================================
@Client.on_callback_query(filters.regex(r"^sendbatch_([a-zA-Z0-9_\-]+)$"))
async def send_batch_callback(client: Client, query: CallbackQuery):
    """Deliver files in a batch/single link with auto-delete protections."""
    batch_id = query.data.split("sendbatch_")[1]
    user_id = query.from_user.id

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await query.answer("❌ This link is no longer available.", show_alert=True)
        return

    # Expiration check
    expired, exp_reason = is_batch_expired(batch_doc)
    if expired:
        await query.answer(f"💥 Link Expired: {exp_reason}", show_alert=True)
        return

    files = batch_doc.get("files", [])
    if not files:
        await query.answer("❌ No files found in this link.", show_alert=True)
        return

    # PIN lock check
    pin_code = batch_doc.get("pin_code")
    s_key = (user_id, batch_id)
    if pin_code and s_key not in VERIFIED_PIN_SESSIONS:
        PIN_INPUT_BUFFER[s_key] = ""
        markup = build_pin_numpad_markup(batch_id, "")
        await query.answer("🔒 Secret PIN Required!", show_alert=False)
        await query.message.reply_text(
            "🔒 <b>PIN Protected Secret Vault!</b>\n\n"
            "This link is protected by a 4-digit security PIN.\n"
            "Enter the 4-digit PIN using the keypad below or type it in this chat:\n\n"
            "PIN: <code>_ _ _ _</code>",
            reply_markup=markup
        )
        return

    await query.answer("⚡ Sending files...", show_alert=False)
    await deliver_batch_files_to_user(client, user_id, batch_doc, query.message)


@Client.on_callback_query(filters.regex(r"^pin_in_([a-zA-Z0-9_\-]+)_([0-9a-zA-Z]+)$"))
async def pin_numpad_callback(client: Client, query: CallbackQuery):
    """Handle interactive numpad key presses for PIN verification."""
    match = re.match(r"^pin_in_([a-zA-Z0-9_\-]+)_([0-9a-zA-Z]+)$", query.data)
    if not match:
        await query.answer()
        return

    batch_id = match.group(1)
    key = match.group(2)
    user_id = query.from_user.id
    s_key = (user_id, batch_id)

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await query.answer("❌ Link no longer exists.", show_alert=True)
        return

    req_pin = batch_doc.get("pin_code")
    if not req_pin:
        VERIFIED_PIN_SESSIONS.add(s_key)
        await query.answer("✅ Unlocked!", show_alert=False)
        try:
            await query.message.delete()
        except Exception:
            pass
        await deliver_batch_files_to_user(client, user_id, batch_doc, query.message)
        return

    cur_buf = PIN_INPUT_BUFFER.get(s_key, "")

    if key == "cancel":
        PIN_INPUT_BUFFER.pop(s_key, None)
        await query.answer("❌ Cancelled")
        try:
            await query.message.edit_text("❌ <b>PIN entry cancelled.</b>")
        except Exception:
            pass
        return

    elif key == "clear":
        PIN_INPUT_BUFFER[s_key] = ""
        await query.answer("Cleared")
        try:
            markup = build_pin_numpad_markup(batch_id, "")
            await query.message.edit_text(
                "🔒 <b>PIN Protected Secret Vault!</b>\n\n"
                "This link is protected by a 4-digit security PIN.\n"
                "Enter the 4-digit PIN using the keypad below or type it in this chat:\n\n"
                "PIN: <code>_ _ _ _</code>",
                reply_markup=markup
            )
        except Exception:
            pass
        return

    elif key.isdigit():
        if len(cur_buf) < 4:
            cur_buf += key
            PIN_INPUT_BUFFER[s_key] = cur_buf

        if len(cur_buf) == 4:
            if cur_buf == req_pin:
                VERIFIED_PIN_SESSIONS.add(s_key)
                PIN_INPUT_BUFFER.pop(s_key, None)
                PIN_ATTEMPTS.pop(s_key, None)
                await query.answer("✅ PIN Correct!", show_alert=False)
                try:
                    await query.message.edit_text("✅ <b>PIN Verified! Delivering files...</b>")
                except Exception:
                    pass
                await deliver_batch_files_to_user(client, user_id, batch_doc, query.message)
                return
            else:
                att = PIN_ATTEMPTS.get(s_key, 0) + 1
                PIN_ATTEMPTS[s_key] = att
                PIN_INPUT_BUFFER[s_key] = ""
                if att >= 3:
                    await query.answer("⛔ Access Denied! Too many attempts.", show_alert=True)
                    try:
                        await query.message.edit_text("⛔ <b>Maximum PIN attempts exceeded.</b> Access blocked.")
                    except Exception:
                        pass
                    return
                else:
                    await query.answer(f"❌ Incorrect PIN! ({att}/3)", show_alert=True)
                    markup = build_pin_numpad_markup(batch_id, "")
                    try:
                        await query.message.edit_text(
                            f"❌ <b>Incorrect PIN!</b> ({att}/3 attempts used)\n\n"
                            "Please enter the correct 4-digit PIN:\n\n"
                            "PIN: <code>_ _ _ _</code>",
                            reply_markup=markup
                        )
                    except Exception:
                        pass
                    return
        else:
            await query.answer()
            masked = " ".join(["●"] * len(cur_buf) + ["_"] * (4 - len(cur_buf)))
            markup = build_pin_numpad_markup(batch_id, cur_buf)
            try:
                await query.message.edit_text(
                    "🔒 <b>PIN Protected Secret Vault!</b>\n\n"
                    "This link is protected by a 4-digit security PIN.\n"
                    "Enter the 4-digit PIN using the keypad below or type it in this chat:\n\n"
                    f"PIN: <code>{masked}</code>",
                    reply_markup=markup
                )
            except Exception:
                pass
            return

    elif key == "ok":
        if len(cur_buf) < 4:
            await query.answer("Please enter all 4 digits.", show_alert=True)
            return
        if cur_buf == req_pin:
            VERIFIED_PIN_SESSIONS.add(s_key)
            PIN_INPUT_BUFFER.pop(s_key, None)
            PIN_ATTEMPTS.pop(s_key, None)
            await query.answer("✅ PIN Correct!", show_alert=False)
            try:
                await query.message.edit_text("✅ <b>PIN Verified! Delivering files...</b>")
            except Exception:
                pass
            await deliver_batch_files_to_user(client, user_id, batch_doc, query.message)
        else:
            att = PIN_ATTEMPTS.get(s_key, 0) + 1
            PIN_ATTEMPTS[s_key] = att
            PIN_INPUT_BUFFER[s_key] = ""
            if att >= 3:
                await query.answer("⛔ Access Denied! Too many attempts.", show_alert=True)
                try:
                    await query.message.edit_text("⛔ <b>Maximum PIN attempts exceeded.</b> Access blocked.")
                except Exception:
                    pass
            else:
                await query.answer(f"❌ Incorrect PIN! ({att}/3)", show_alert=True)
                markup = build_pin_numpad_markup(batch_id, "")
                try:
                    await query.message.edit_text(
                        f"❌ <b>Incorrect PIN!</b> ({att}/3 attempts used)\n\n"
                        "Please enter the correct 4-digit PIN:\n\n"
                        "PIN: <code>_ _ _ _</code>",
                        reply_markup=markup
                    )
                except Exception:
                    pass
        return


@Client.on_callback_query(filters.regex(r"^listbatch_([a-zA-Z0-9_\-]+)_(\d+)$"))
async def list_batch_callback(client: Client, query: CallbackQuery):
    """Show paginated list of file names in the batch."""
    parts = query.data.split("_")
    batch_id = parts[1]
    page = int(parts[2])

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await query.answer("❌ Batch not found.", show_alert=True)
        return

    files = batch_doc.get("files", [])
    page_size = 8
    total_pages = max(1, (len(files) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(files))
    page_files = files[start_idx:end_idx]

    text = (
        f"📋 <b><u>FILES IN BATCH: {batch_doc.get('title', 'Collection')}</u></b>\n"
        f"• Page: <code>{page + 1}/{total_pages}</code> • Total: <code>{len(files)} Files</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for i, f in enumerate(page_files, start_idx + 1):
        f_name = f.get("file_name", "File")
        f_sz = get_readable_size(f.get("file_size", 0))
        text += f"<b>{i}.</b> <code>{f_name}</code> ({f_sz})\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"listbatch_{batch_id}_{page - 1}"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton("Next ➡️", callback_data=f"listbatch_{batch_id}_{page + 1}"))

    markup_rows = []
    if nav_btns:
        markup_rows.append(nav_btns)
    markup_rows.append([
        InlineKeyboardButton(f"📥 SEND ALL ({len(files)} FILES)", callback_data=f"sendbatch_{batch_id}")
    ])
    markup = InlineKeyboardMarkup(markup_rows)

    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^delbatch_cb_([a-zA-Z0-9_\-]+)$"))
async def delbatch_callback(client: Client, query: CallbackQuery):
    """Delete a batch callback (Admins or creator only)."""
    batch_id = query.data.split("delbatch_cb_")[1]
    user_id = query.from_user.id

    batch_doc = await get_batch(batch_id)
    if not batch_doc:
        await query.answer("❌ Batch not found or already deleted.", show_alert=True)
        return

    if not Config.is_admin(user_id) and batch_doc.get("created_by") != user_id:
        await query.answer("⛔ You are not authorized to delete this batch.", show_alert=True)
        return

    success = await delete_batch(batch_id)
    if success:
        await query.answer(f"✅ Batch {batch_id} deleted successfully!", show_alert=True)
        # Refresh dashboard
        await list_batches_command(client, query.message)
    else:
        await query.answer("❌ Error deleting batch.", show_alert=True)
