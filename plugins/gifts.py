import re
import html
import logging
import datetime
from typing import Optional

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from utils.helpers import get_readable_size, format_clean_title
from database.ads import parse_duration_string
from database.gifts import (
    create_gift,
    get_gift,
    delete_gift,
    get_all_gifts,
    gift_ban_user,
    gift_unban_user,
    is_gift_banned
)
from database.batches import get_batch

logger = logging.getLogger(__name__)


def parse_short_duration(dur_str: str) -> Optional[int]:
    """Parse time string supporting seconds (s), minutes (m), hours (h), days (d), weeks (w)."""
    m = re.match(r"^(\d+)\s*(s|sec|m|min|h|hr|d|day|w|week)?$", dur_str.strip().lower())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2) or "m"
    if unit in ("s", "sec"):
        return val
    elif unit in ("m", "min"):
        return val * 60
    elif unit in ("h", "hr"):
        return val * 3600
    elif unit in ("d", "day"):
        return val * 86400
    elif unit in ("w", "week"):
        return val * 7 * 86400
    return None


def parse_gift_flags(arg_list: list[str]) -> dict:
    """Parse command line flags like -viponly, -shortener, -protect, -del 3m, -img <url>, -unlimited."""
    flags = {
        "is_vip_only": False,
        "require_shortener": False,
        "protect_content": True,
        "auto_delete_seconds": 300,  # 5 minutes default
        "poster_url": None,
        "channels": [],
        "claims": 50,
        "duration_seconds": 172800  # 48 hours default
    }

    seen_numbers = 0
    skip_next = False
    for i, token in enumerate(arg_list):
        if skip_next:
            skip_next = False
            continue

        tok_low = token.lower()
        if tok_low in ("-unlimited", "-nolimit", "-forever", "-inf"):
            flags["claims"] = 0
            flags["duration_seconds"] = 0
        elif tok_low in ("unlimited", "nolimit", "inf"):
            flags["claims"] = 0
        elif tok_low in ("forever", "lifetime", "never", "0h", "0d", "0s"):
            flags["duration_seconds"] = 0
        elif tok_low == "-viponly":
            flags["is_vip_only"] = True
        elif tok_low in ("-shortener", "-short", "-ad"):
            flags["require_shortener"] = True
        elif tok_low == "-noprotect":
            flags["protect_content"] = False
        elif tok_low == "-protect":
            flags["protect_content"] = True
        elif tok_low == "-del":
            if i + 1 < len(arg_list):
                dur = parse_short_duration(arg_list[i + 1])
                if dur is not None:
                    flags["auto_delete_seconds"] = dur
                skip_next = True
        elif tok_low in ("-img", "-poster"):
            if i + 1 < len(arg_list):
                flags["poster_url"] = arg_list[i + 1]
                skip_next = True
        elif token.startswith("@") or token.startswith("-100"):
            flags["channels"].append(token)
        elif token.isdigit():
            val = int(token)
            if seen_numbers == 0:
                flags["claims"] = val
            elif seen_numbers == 1:
                # 2nd numeric token without unit: 0 means no time limit, else hours
                flags["duration_seconds"] = 0 if val == 0 else (val * 3600)
            seen_numbers += 1
        elif re.match(r"^\d+\s*([hdwHDW]|days?|hours?|weeks?)$", token):
            dur = parse_short_duration(token)
            if dur is not None:
                flags["duration_seconds"] = dur

    return flags


# ==============================================================================
# Admin Command: /gift (Reply to any File / Media Message)
# ==============================================================================

@Client.on_message(filters.command(["gift", "creategift", "reward"]) & filters.private)
async def create_single_gift_handler(client: Client, message: Message):
    """Admin tool to create a task-locked gift reward link for any file."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    reply = message.reply_to_message
    if not reply:
        return await message.reply_text(
            "🎁 <b>CREATE TASK-LOCKED REWARD / GIFT LINK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b> Reply to any file, video, APK, or document with:\n"
            "<code>/gift [claims] [duration] [@channel...] [flags]</code>\n\n"
            "<b>Supported Flags:</b>\n"
            "• <code>-viponly</code> : Reserved only for VIP subscribers\n"
            "• <code>-shortener</code> : Require 1-time shortener/ad bypass\n"
            "• <code>-protect</code> : Block forwarding and saving\n"
            "• <code>-del 3m</code> : Auto-delete delivered file in 3 minutes\n"
            "• <code>-img &lt;url&gt;</code> : Custom gift poster picture URL\n\n"
            "<b>Examples:</b>\n"
            "• <code>/gift 50 48h @AkMoviesOfficial</code>\n"
            "• <code>/gift 100 7d @AkMoviesOfficial @BackupZone -shortener -del 3m</code>\n"
            "• <code>/gift 50 24h -viponly</code> (Exclusive VIP Giveaway)"
        )

    # Extract media from reply
    media = (
        reply.document or reply.video or reply.audio or
        reply.photo or reply.animation or reply.voice
    )
    if not media:
        return await message.reply_text("❌ <b>No supported file or media found in replied message.</b>")

    raw_name = getattr(media, "file_name", None) or "Exclusive Reward File"
    file_id = media.file_id
    file_unique_id = getattr(media, "file_unique_id", "")
    file_size = getattr(media, "file_size", 0)

    file_doc = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_name": raw_name,
        "file_size": file_size
    }

    # Parse command arguments & flags
    cmd_args = message.text.split()[1:]
    flags = parse_gift_flags(cmd_args)

    clean_title = format_clean_title(raw_name)
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    # Create gift record in database
    doc = await create_gift(
        title=clean_title,
        file_type="single",
        file_doc=file_doc,
        total_files=1,
        total_size=file_size,
        poster_url=flags["poster_url"],
        channels=flags["channels"],
        require_shortener=flags["require_shortener"],
        is_vip_only=flags["is_vip_only"],
        protect_content=flags["protect_content"],
        auto_delete_seconds=flags["auto_delete_seconds"],
        max_claims=flags["claims"],
        duration_seconds=flags["duration_seconds"],
        created_by=message.from_user.id
    )

    if not doc:
        return await message.reply_text("❌ <b>Database error:</b> Failed to create gift reward.")

    gift_id = doc["gift_id"]
    gift_link = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

    # Build Ready-to-Forward Channel Post
    vip_badge = "👑 <b>VIP Members Only</b>" if flags["is_vip_only"] else "🌐 <b>Public Drop (Tasks Required)</b>"
    protect_badge = "🔒 Content Protected (No Forward)" if flags["protect_content"] else "🔓 Standard"
    del_mins = flags["auto_delete_seconds"] // 60
    del_str = f"{del_mins} Minute(s)" if del_mins > 0 else f"{flags['auto_delete_seconds']}s"
    stock_str = f"First {flags['claims']} Users Only!" if flags["claims"] > 0 else "Unlimited (Open for Everyone!)"
    validity_str = "Permanent / Lifetime Drop" if flags["duration_seconds"] == 0 else "Limited Time"

    card_text = (
        "🎁 <b>EXCLUSIVE REWARD DROP!</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Reward:</b> <code>{html.escape(clean_title)}</code>\n"
        f"💾 <b>Size:</b> <code>{get_readable_size(file_size)}</code>\n"
        f"👥 <b>Available Stock:</b> <code>{stock_str}</code>\n"
        f"⏳ <b>Campaign Validity:</b> <code>{validity_str}</code>\n"
        f"🛡️ <b>Access:</b> {vip_badge}\n"
        f"⏱️ <b>Self-Destruct:</b> <code>Auto-Deletes in {del_str}</code>\n"
        f"🔐 <b>Protection:</b> <code>{protect_badge}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>Claim your gift below:</b>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 CLAIM EXCLUSIVE REWARD ↗️", url=gift_link)]
    ])

    admin_summary = (
        f"✅ <b>GIFT REWARD LINK CREATED SUCCESSFULLY!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
        f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n\n"
        f"📢 <i>You can forward the ready-made card below directly to your channel!</i>"
    )

    await message.reply_text(admin_summary, disable_web_page_preview=True)

    poster = doc.get("poster_url")
    if poster:
        try:
            return await message.reply_photo(photo=poster, caption=card_text, reply_markup=markup)
        except Exception:
            pass

    await message.reply_text(card_text, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /giftbatch <batch_id> [claims] [duration] ...
# ==============================================================================

@Client.on_message(filters.command(["giftbatch", "rewardbatch"]) & filters.private)
async def create_batch_gift_handler(client: Client, message: Message):
    """Admin tool to create a gift reward for an entire batch (multi-file pack)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text(
            "🎁 <b>CREATE MULTI-FILE BATCH GIFT LINK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b>\n"
            "<code>/giftbatch &lt;batch_id&gt; [claims] [duration] [@channel...] [flags]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/giftbatch b_abc123 50 48h @AkMoviesOfficial -protect -del 5m</code>"
        )

    batch_id = parts[1].strip()
    batch = await get_batch(batch_id)
    if not batch:
        return await message.reply_text(f"❌ <b>Batch not found:</b> <code>{html.escape(batch_id)}</code>")

    files = batch.get("files", [])
    total_files = len(files)
    total_size = batch.get("total_size", 0)

    cmd_args = parts[2:]
    flags = parse_gift_flags(cmd_args)

    batch_title = f"{files[0].get('file_name', 'Batch Pack')} (+{total_files - 1} Files)" if total_files > 1 else files[0].get("file_name", "Batch File")
    clean_title = format_clean_title(batch_title)
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    doc = await create_gift(
        title=clean_title,
        file_type="batch",
        batch_id=batch_id,
        total_files=total_files,
        total_size=total_size,
        poster_url=flags["poster_url"],
        channels=flags["channels"],
        require_shortener=flags["require_shortener"],
        is_vip_only=flags["is_vip_only"],
        protect_content=flags["protect_content"],
        auto_delete_seconds=flags["auto_delete_seconds"],
        max_claims=flags["claims"],
        duration_seconds=flags["duration_seconds"],
        created_by=message.from_user.id
    )

    if not doc:
        return await message.reply_text("❌ <b>Database error:</b> Failed to create batch gift reward.")

    gift_id = doc["gift_id"]
    gift_link = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

    del_mins = flags["auto_delete_seconds"] // 60
    del_str = f"{del_mins} Minute(s)" if del_mins > 0 else f"{flags['auto_delete_seconds']}s"
    stock_str = f"First {flags['claims']} Users Only!" if flags["claims"] > 0 else "Unlimited (Open for Everyone!)"
    validity_str = "Permanent / Lifetime Drop" if flags["duration_seconds"] == 0 else "Limited Time"

    card_text = (
        "🎁 <b>EXCLUSIVE BATCH REWARD PACK!</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Package:</b> <code>{html.escape(clean_title)}</code>\n"
        f"📁 <b>Total Files:</b> <code>{total_files} Files</code>\n"
        f"💾 <b>Total Size:</b> <code>{get_readable_size(total_size)}</code>\n"
        f"👥 <b>Available Stock:</b> <code>{stock_str}</code>\n"
        f"⏳ <b>Campaign Validity:</b> <code>{validity_str}</code>\n"
        f"⏱️ <b>Self-Destruct:</b> <code>Auto-Deletes in {del_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>Claim complete pack below:</b>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 CLAIM COMPLETE BATCH PACK ↗️", url=gift_link)]
    ])

    admin_summary = (
        f"✅ <b>BATCH GIFT REWARD CREATED SUCCESSFULLY!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
        f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n\n"
        f"📢 <i>You can forward the ready-made card below directly to your channel!</i>"
    )

    await message.reply_text(admin_summary, disable_web_page_preview=True)
    poster = doc.get("poster_url")
    if poster:
        try:
            return await message.reply_photo(photo=poster, caption=card_text, reply_markup=markup)
        except Exception:
            pass

    await message.reply_text(card_text, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /gifts or /giftstats (Active Gifts Dashboard)
# ==============================================================================

@Client.on_message(filters.command(["gifts", "giftstats"]) & filters.private)
async def list_gifts_dashboard(client: Client, message: Message):
    """Admin dashboard to inspect live gift campaigns, claim progress, and revoke."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) > 1:
        # Specific gift details
        gid = parts[1].strip()
        gift = await get_gift(gid)
        if not gift:
            return await message.reply_text(f"❌ <b>Gift not found:</b> <code>{html.escape(gid)}</code>")

        claimed = gift.get("claimed_count", 0)
        max_c = gift.get("max_claims", 0)
        views = gift.get("views_count", 0)
        active = gift.get("is_active", False)
        status_str = "🟢 Active" if active else "🔴 Inactive / Expired"

        exp = gift.get("expires_at")
        exp_str = exp.strftime("%d %b %Y, %H:%M UTC") if exp else "Never"

        bot_uname = client.me.username if client.me else Config.BOT_USERNAME
        link = f"https://t.me/{bot_uname}?start=gift_{gid}"

        text = (
            f"🎁 <b>GIFT REWARD CAMPAIGN #{gid}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Title:</b> <code>{html.escape(gift.get('title', 'Gift'))}</code>\n"
            f"• <b>Status:</b> {status_str}\n"
            f"• <b>Claimed:</b> <code>{claimed} / {max_c if max_c else '∞'} Users</code>\n"
            f"• <b>Views / Clicks:</b> <code>{views:,} Views</code>\n"
            f"• <b>VIP Only:</b> <code>{'Yes' if gift.get('is_vip_only') else 'No'}</code>\n"
            f"• <b>Shortener Task:</b> <code>{'Yes' if gift.get('require_shortener') else 'No'}</code>\n"
            f"• <b>Required Channels:</b> <code>{', '.join(gift.get('channels', [])) or 'None'}</code>\n"
            f"• <b>Expires At:</b> <code>{exp_str}</code>\n"
            f"• <b>Link:</b> <code>{link}</code>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Revoke / Delete Gift", callback_data=f"delgift_cb_{gid}")]
        ])
        return await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)

    # General list
    gifts = await get_all_gifts(limit=15, only_active=True)
    if not gifts:
        return await message.reply_text(
            "ℹ️ <b>No active gift campaigns found.</b>\n"
            "Use <code>/gift</code> (by replying to any file) or <code>/giftbatch &lt;id&gt;</code> to create one."
        )

    text_lines = [
        "🎁 <b>ACTIVE GIFT CAMPAIGNS DASHBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    buttons = []
    for g in gifts:
        gid = g["gift_id"]
        title = g.get("title", "Gift")[:25]
        claimed = g.get("claimed_count", 0)
        max_c = g.get("max_claims", 0)
        text_lines.append(f"• <code>{gid}</code> : <b>{html.escape(title)}</b> ({claimed}/{max_c})")
        buttons.append([
            InlineKeyboardButton(f"🔍 {title} ({claimed}/{max_c})", callback_data=f"gift_info_{gid}")
        ])

    text_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    text_lines.append("💡 <i>Tap any gift below to inspect or revoke it.</i>")

    await message.reply_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))


# ==============================================================================
# Admin Command: /delgift <gift_id>
# ==============================================================================

@Client.on_message(filters.command(["delgift", "revokegift"]) & filters.private)
async def delete_gift_handler(client: Client, message: Message):
    """Admin tool to immediately revoke and stop a gift reward link."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("<b>Usage:</b> <code>/delgift &lt;gift_id&gt;</code>")

    gid = parts[1].strip()
    ok = await delete_gift(gid)
    if ok:
        await message.reply_text(f"🗑️ <b>Gift campaign <code>{html.escape(gid)}</code> has been revoked successfully!</b>")
    else:
        await message.reply_text("❌ Gift not found or already inactive.")


# ==============================================================================
# Admin Commands: /giftban & /giftunban
# ==============================================================================

@Client.on_message(filters.command(["giftban"]) & filters.private)
async def gift_ban_handler(client: Client, message: Message):
    """Globally blacklist a user from claiming any gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/giftban &lt;user_id&gt; [reason]</code>")

    target_id = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts) > 2 else "Left sponsor channel / Rule violation"

    ok = await gift_ban_user(user_id=target_id, reason=reason, banned_by=message.from_user.id)
    if ok:
        await message.reply_text(
            f"🚫 <b>User <code>{target_id}</code> has been blacklisted from gifts!</b>\n"
            f"<b>Reason:</b> <code>{html.escape(reason)}</code>"
        )
        try:
            await client.send_message(
                chat_id=target_id,
                text=f"⚠️ <b>Notice:</b> You have been restricted from claiming reward gifts on @{client.me.username}.\n<b>Reason:</b> {html.escape(reason)}"
            )
        except Exception:
            pass
    else:
        await message.reply_text("❌ Error blacklisting user.")


@Client.on_message(filters.command(["giftunban"]) & filters.private)
async def gift_unban_handler(client: Client, message: Message):
    """Unban user from claiming gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/giftunban &lt;user_id&gt;</code>")

    target_id = int(parts[1])
    ok = await gift_unban_user(target_id)
    if ok:
        await message.reply_text(f"✅ <b>User <code>{target_id}</code> is now unbanned and can claim gifts.</b>")
    else:
        await message.reply_text("ℹ️ User was not in gift blacklist.")
