import re
import os
import time
import uuid
import asyncio
import logging
from html import escape as html_escape

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message,
        CallbackQuery,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        InputMediaPhoto
    )
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message,
        CallbackQuery,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        InputMediaPhoto
    )

from PIL import Image

from config import Config
from database.users import is_premium
from database.mongo import mongo
from utils.helpers import get_readable_size
from utils.downloader import (
    detect_platform,
    is_telegram_url,
    is_instagram_url,
    download_media,
    clean_temp_dir,
    DownloadProgress,
    format_progress_caption,
    make_progress_bar,
    extract_video_metadata,
    generate_video_thumbnail
)

logger = logging.getLogger("autofilter.downloader")

# In-memory cooldown tracker: {user_id: timestamp}
_USER_LAST_DL: dict[int, float] = {}

URL_REGEX = re.compile(r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)")

# Global Download Queue & Task Tracker
DOWNLOAD_QUEUE: asyncio.Queue = asyncio.Queue()
_WORKER_TASK: asyncio.Task | None = None
_CURRENT_ACTIVE_JOB: dict | None = None
_ALL_TASKS: dict[str, dict] = {}  # {task_id: job_dict}


def ensure_worker_started(client: Client):
    """Ensure the singleton download queue worker is running."""
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_TASK = asyncio.create_task(download_queue_worker(client))
        logger.info("Universal Downloader queue worker started.")


async def check_force_sub(client: Client, message: Message) -> bool:
    """Verify if user has joined mandatory Force Sub channels before allowing downloads."""
    if not Config.FORCE_SUB_CHANNELS or Config.is_admin(message.from_user.id):
        return True

    for channel_id in Config.FORCE_SUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel_id, message.from_user.id)
            if member.status.value in ("banned", "left", "kicked"):
                return False
        except Exception:
            return False
    return True


async def auto_delete_messages(client: Client, chat_id: int, message_ids: list[int], delay: int = 900):
    """Auto-delete delivered copyright messages after specified seconds (default 15 minutes)."""
    try:
        await asyncio.sleep(delay)
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
        logger.info(f"Auto-deleted {len(message_ids)} copyright messages in chat {chat_id} after {delay}s.")
    except Exception as e:
        logger.debug(f"Auto-delete notice for chat {chat_id}: {e}")


async def verify_downloader_access(client: Client, message: Message, url: str | None = None) -> bool:
    """Check whether user is authorized to use the downloader based on DOWNLOADER_ACCESS.
    Telegram cloud forwards and Instagram downloads are open to everyone (with 15s cooldown & force-sub).
    External links (YouTube, TeraBox, Direct URLs) respect DOWNLOADER_ACCESS.
    """
    user = message.from_user
    if not user:
        return False

    user_id = user.id
    is_admin = Config.is_admin(user_id)
    is_tg = bool(url and is_telegram_url(url))
    is_insta = bool(url and is_instagram_url(url))
    is_exempt = is_tg or is_insta

    # 1. External downloader access policy (Telegram & Instagram are open to everyone)
    if not is_exempt and not is_admin:
        if Config.DOWNLOADER_ACCESS == "admin":
            await message.reply_text(
                "⚠️ <b>Access Restricted:</b>\n"
                "External video downloading (YouTube, TeraBox, Direct URLs) is currently reserved strictly for Bot Administrators.\n\n"
                "💡 <i>Tip: Telegram post forwarding and Instagram downloads are completely free and open to everyone!</i>"
            )
            return False
        elif Config.DOWNLOADER_ACCESS == "premium":
            user_is_prem = await is_premium(user_id)
            if not user_is_prem:
                await message.reply_text(
                    "⭐ <b>VIP / Premium Exclusive Feature:</b>\n\n"
                    "External video downloading is exclusively reserved for <b>Premium VIP Members</b> and Admins.\n\n"
                    "✨ <b>VIP Perks:</b>\n"
                    "• ⚡ Unlimited video & social media downloads\n"
                    "• 🚀 Ultra-fast cloud speed without wait time\n"
                    "• 🚫 Zero ads & zero shortener verification\n\n"
                    "💡 <i>Telegram post forwarding and Instagram downloads are completely free for everyone!</i>",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💎 View VIP Plans", callback_data="buy_premium")
                    ]])
                )
                return False

    # 2. Cooldown Check (Non-admins only)
    now = time.time()
    if not is_admin:
        last_dl = _USER_LAST_DL.get(user_id, 0)
        cooldown_time = 15 if is_exempt else Config.DOWNLOADER_COOLDOWN
        cooldown_rem = int(cooldown_time - (now - last_dl))
        if cooldown_rem > 0:
            await message.reply_text(
                f"⏳ <b>Please wait {cooldown_rem}s</b> before requesting another download."
            )
            return False

    # 3. Force Subscribe Check (Applies to all non-admins)
    if not await check_force_sub(client, message):
        channel_link = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
        await message.reply_text(
            "⚠️ <b>Please Join Our Channel to Download:</b>\n\n"
            f"You must join {channel_link} before downloading or forwarding files.\n"
            "Join and try sending your link again!",
            disable_web_page_preview=True
        )
        return False

    return True


# ==========================================
# CUSTOM THUMBNAIL MANAGEMENT (LISA-KOREA)
# ==========================================

@Client.on_message(filters.command(["setthumb", "set_thumb"]) & filters.private)
async def set_custom_thumb_handler(client: Client, message: Message):
    """Save custom video thumbnail for admin / user in MongoDB."""
    if not Config.is_admin(message.from_user.id):
        return

    photo = message.photo or (message.reply_to_message.photo if message.reply_to_message else None)
    if not photo:
        return await message.reply_text(
            "📸 <b>Set Custom Thumbnail:</b>\n\n"
            "Please send a photo or reply to a photo with <code>/setthumb</code>.\n"
            "This thumbnail will be automatically applied to all your video downloads!"
        )

    thumb_file_id = photo.file_id
    await mongo.users.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"custom_thumb": thumb_file_id}},
        upsert=True
    )
    await message.reply_text("✅ <b>Custom Thumbnail Saved!</b>\nAll your future downloaded videos will use this custom cover thumbnail.")


@Client.on_message(filters.command(["showthumb", "viewthumb"]) & filters.private)
async def view_custom_thumb_handler(client: Client, message: Message):
    """View active custom thumbnail."""
    if not Config.is_admin(message.from_user.id):
        return

    doc = await mongo.users.find_one({"user_id": message.from_user.id})
    thumb_id = doc.get("custom_thumb") if doc else None
    if not thumb_id:
        return await message.reply_text("❌ <b>No Custom Thumbnail Found.</b>\nSend a photo with <code>/setthumb</code> to save one.")

    await message.reply_photo(photo=thumb_id, caption="🖼️ <b>Your Active Custom Thumbnail</b>\nUse <code>/delthumb</code> to remove it.")


@Client.on_message(filters.command(["delthumb", "clrthumb"]) & filters.private)
async def delete_custom_thumb_handler(client: Client, message: Message):
    """Remove active custom thumbnail."""
    if not Config.is_admin(message.from_user.id):
        return

    await mongo.users.update_one({"user_id": message.from_user.id}, {"$unset": {"custom_thumb": ""}})
    await message.reply_text("🗑️ <b>Custom Thumbnail Deleted!</b>\nVideos will now use their native platform thumbnails.")


# ==========================================
# DOWNLOAD DISPATCHER & LINK HANDLERS
# ==========================================

TG_POST_REGEX = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:c/(\d+)|([a-zA-Z0-9_]+))/(\d+)(?:-(\d+))?")


async def _fallback_stream_and_send(client: Client, message: Message, target_chat, msg_id: int, custom_name: str | None = None) -> Message | None:
    """Fallback when copy_message fails (e.g. protected content): download media and send with correct native type."""
    temp_dir = os.path.join("temp_downloads", f"tg_fall_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_dir, exist_ok=True)
    try:
        target_msg = await client.get_messages(target_chat, message_ids=msg_id)
        if not target_msg:
            return None

        caption = target_msg.caption or ""

        if target_msg.photo:
            ext = ".jpg"
            dest = os.path.join(temp_dir, (custom_name or f"photo_{msg_id}") + (ext if not (custom_name or "").endswith(ext) else ""))
            dl = await client.download_media(target_msg, file_name=dest)
            if dl and os.path.exists(dl):
                return await message.reply_photo(photo=dl, caption=caption)
        elif target_msg.video:
            fn = custom_name or getattr(target_msg.video, "file_name", None) or f"video_{msg_id}.mp4"
            if not any(fn.lower().endswith(e) for e in (".mp4", ".mkv", ".webm", ".avi", ".mov")):
                fn += ".mp4"
            dest = os.path.join(temp_dir, fn)
            dl = await client.download_media(target_msg, file_name=dest)
            if dl and os.path.exists(dl):
                return await message.reply_video(video=dl, caption=caption, supports_streaming=True)
        elif target_msg.audio:
            fn = custom_name or getattr(target_msg.audio, "file_name", None) or f"audio_{msg_id}.mp3"
            dest = os.path.join(temp_dir, fn)
            dl = await client.download_media(target_msg, file_name=dest)
            if dl and os.path.exists(dl):
                return await message.reply_audio(audio=dl, caption=caption)
        elif target_msg.voice:
            dest = os.path.join(temp_dir, f"voice_{msg_id}.ogg")
            dl = await client.download_media(target_msg, file_name=dest)
            if dl and os.path.exists(dl):
                return await message.reply_voice(voice=dl, caption=caption)
        elif target_msg.document:
            fn = custom_name or getattr(target_msg.document, "file_name", None) or f"file_{msg_id}.bin"
            dest = os.path.join(temp_dir, fn)
            dl = await client.download_media(target_msg, file_name=dest)
            if dl and os.path.exists(dl):
                return await message.reply_document(document=dl, caption=caption)
        elif target_msg.text:
            return await message.reply_text(target_msg.text)
    except Exception as fe:
        logger.warning(f"Fallback send failed for {target_chat}/{msg_id}: {fe}")
    finally:
        clean_temp_dir(temp_dir)
    return None


async def handle_telegram_cloud_forward(client: Client, message: Message, url: str, custom_name: str | None = None):
    """Zero-load instant Telegram cloud forwarder with batch range support, 15m auto-delete, and auto-indexing."""
    match = TG_POST_REGEX.search(url)
    if not match:
        return await message.reply_text(
            "❌ <b>Invalid Telegram link:</b>\n"
            "Please provide a link like <code>https://t.me/channel/123</code> or a range like <code>https://t.me/channel/100-110</code>."
        )

    c_id, u_name, start_id_str, end_id_str = match.groups()
    target_chat = int(f"-100{c_id}") if c_id else u_name
    start_id = int(start_id_str)
    end_id = int(end_id_str) if end_id_str else start_id

    # Handle reverse range if user entered e.g. 110-100
    if end_id < start_id:
        start_id, end_id = end_id, start_id

    total_count = end_id - start_id + 1
    # Cap batch range to max 10 for stability and flood prevention
    max_batch = 10
    capped = False
    if total_count > max_batch:
        end_id = start_id + max_batch - 1
        total_count = max_batch
        capped = True

    status_msg = await message.reply_text(
        f"⚡ <b>Connecting to Telegram Cloud...</b>\n"
        f"📦 <b>Target:</b> <code>{target_chat}</code>\n"
        f"📄 <b>Processing:</b> {total_count} message(s)"
        f"{' (Capped to max 10 for safety)' if capped else ''}..."
    )

    user_id = message.from_user.id
    _USER_LAST_DL[user_id] = time.time()

    is_pm = message.chat.type.value == "private" if hasattr(message.chat.type, "value") else str(message.chat.type).endswith("PRIVATE")
    dump_channel = getattr(Config, "DUMP_CHANNEL", 0) or getattr(Config, "LOG_CHANNEL", 0)

    delivered_msg_ids = []
    success_count = 0
    fail_count = 0

    for msg_id in range(start_id, end_id + 1):
        delivered = None
        try:
            # 1. Native Telegram Cloud Copy (Fastest, 0 bandwidth, preserves exact media type)
            delivered = await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=target_chat,
                message_id=msg_id
            )
        except Exception as e_copy:
            err_str = str(e_copy).upper()
            if "CHAT_ADMIN_REQUIRED" in err_str or "CHANNEL_PRIVATE" in err_str:
                logger.warning(f"Bot lacks access to private chat {target_chat}: {e_copy}")
                fail_count += 1
                continue

            # 2. Fallback: Download via MTProto and upload with exact media type
            try:
                delivered = await _fallback_stream_and_send(client, message, target_chat, msg_id, custom_name=custom_name)
            except Exception as e_fall:
                logger.warning(f"Fallback failed for {target_chat}/{msg_id}: {e_fall}")
                fail_count += 1
                continue

        if delivered:
            success_count += 1
            delivered_msg_ids.append(delivered.id)

            # Silent Dump Channel Copy (Backup without polluting search database)
            if dump_channel:
                try:
                    await client.copy_message(
                        chat_id=dump_channel,
                        from_chat_id=message.chat.id,
                        message_id=delivered.id
                    )
                except Exception as e_dump:
                    logger.debug(f"Dump copy notice: {e_dump}")

        # Pacing delay between batch messages
        if total_count > 1:
            await asyncio.sleep(0.8)

    # Clean up status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    if success_count == 0:
        bot_uname = Config.BOT_USERNAME or "bot"
        return await message.reply_text(
            f"❌ <b>Download Failed:</b>\n\n"
            f"Could not access message(s) from <code>{target_chat}</code>.\n\n"
            f"<b>Possible Causes:</b>\n"
            f"• Message does not exist or was deleted.\n"
            f"• If it is a private channel (<code>t.me/c/...</code>), @{bot_uname} must be added as an admin or member first!"
        )

    # 15-Minute Copyright Auto-Delete Warning / Batch Summary (in PM)
    if is_pm and delivered_msg_ids:
        if total_count > 1:
            summary_msg = await message.reply_text(
                f"✅ <b>Batch Download Completed!</b>\n\n"
                f"📦 <b>Total Delivered:</b> <code>{success_count}</code> Media Files\n"
                f"⚠️ <b>Auto-Delete Notice:</b> All delivered files will be automatically deleted in 15 minutes due to copyright issues.\n\n"
                f"<i>💡 Please forward these files to your <b>Saved Messages</b> now to keep them permanently!</i>"
            )
            auto_del_ids = delivered_msg_ids + [summary_msg.id]
        else:
            warn_msg = await message.reply_text(
                "⚠️ <b>THIS FILE/VIDEO WILL BE DELETED IN 15 MINUTES DUE TO COPYRIGHT ISSUES.</b>\n\n"
                "<i>Please forward this file to your <b>Saved Messages</b> or personal chat immediately to keep it permanently!</i>"
            )
            auto_del_ids = delivered_msg_ids + [warn_msg.id]

        asyncio.create_task(auto_delete_messages(client, message.chat.id, auto_del_ids, delay=900))

    # Update global stats
    try:
        await mongo.dl_stats.update_one(
            {"_id": "global"},
            {
                "$inc": {
                    "total_downloads": success_count,
                    "platforms.Telegram": success_count
                }
            },
            upsert=True
        )
    except Exception:
        pass


@Client.on_message(filters.command(["dl", "download"]) & (filters.private | filters.group))
async def download_command_handler(client: Client, message: Message):
    """Handle /dl <url> or /dl <url> | <custom_filename.mp4> commands."""
    text_parts = message.text.split(None, 1)
    if len(text_parts) < 2:
        return await message.reply_text(
            "ℹ️ <b>How to Use Universal Downloader:</b>\n\n"
            "Send a link directly or use:\n"
            "<code>/dl https://instagram.com/reel/...</code>\n"
            "<code>/dl https://youtube.com/watch?v=...</code>\n"
            "<code>/dl https://luluvido.com/...</code>\n"
            "<code>/dl https://t.me/channel/123</code>\n"
            "<code>/dl https://t.me/channel/100-110</code> (Batch Range)\n"
            "<code>/dl https://example.com/movie.mp4 | New_Movie_Name.mp4</code>"
        )

    raw_payload = text_parts[1].strip()
    custom_name = None
    if "|" in raw_payload:
        url_part, name_part = raw_payload.split("|", 1)
        url = url_part.strip()
        custom_name = name_part.strip()
    else:
        url = raw_payload.strip()

    if not await verify_downloader_access(client, message, url=url):
        return

    await handle_download_request(client, message, url, custom_name=custom_name)


@Client.on_message(filters.private & filters.text & filters.regex(r"https?://"))
async def auto_url_detect_handler(client: Client, message: Message):
    """Automatically detect and download any URL sent directly in Private Message."""
    if not message.text or message.text.startswith("/"):
        message.continue_propagation()
        return

    match = URL_REGEX.search(message.text)
    if not match:
        message.continue_propagation()
        return

    raw_text = message.text.strip()
    custom_name = None
    if "|" in raw_text:
        parts = raw_text.split("|", 1)
        url = URL_REGEX.search(parts[0]).group(0).strip()
        custom_name = parts[1].strip()
    else:
        url = match.group(0).strip()

    if not await verify_downloader_access(client, message, url=url):
        return

    await handle_download_request(client, message, url, custom_name=custom_name)


async def handle_download_request(client: Client, message: Message, url: str, custom_name: str | None = None):
    """Route Telegram links to zero-load cloud forwarder; prompt quality for YouTube, or queue external downloads."""
    # 1. Instant Telegram Cloud Forwarder (zero server bandwidth/disk, batch range support)
    if is_telegram_url(url):
        return await handle_telegram_cloud_forward(client, message, url, custom_name=custom_name)

    platform = detect_platform(url)
    task_id = uuid.uuid4().hex[:8]

    # If YouTube, offer quality options
    if "youtube.com" in url.lower() or "youtu.be" in url.lower():
        _ALL_TASKS[task_id] = {
            "client": client,
            "message": message,
            "url": url,
            "platform": platform,
            "task_id": task_id,
            "custom_name": custom_name,
            "user_id": message.from_user.id
        }

        buttons = [
            [
                InlineKeyboardButton("⚡ 360p (Fast)", callback_data=f"dl_q:{task_id}:360"),
                InlineKeyboardButton("🎬 720p (HD)", callback_data=f"dl_q:{task_id}:720")
            ],
            [
                InlineKeyboardButton("📺 Best Quality", callback_data=f"dl_q:{task_id}:best")
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"dl_cancel:{task_id}")
            ]
        ]

        await message.reply_text(
            f"🎬 <b>Select Download Resolution:</b>\n\n"
            f"🌐 <b>Platform:</b> {platform}\n"
            f"🔗 <b>Link:</b> <code>{html_escape(url[:55])}...</code>\n"
            f"{f'🏷️ <b>Rename to:</b> <code>{html_escape(custom_name)}</code>' if custom_name else ''}\n"
            f"<i>Choose your preferred video quality below:</i>",
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True
        )
        return

    # Direct enqueue for LuLuStream, Instagram, Pinterest, Direct links
    await enqueue_download(client, message, url, quality="best", task_id=task_id, custom_name=custom_name)


@Client.on_callback_query(filters.regex(r"^dl_q:"))
async def quality_selector_callback(client: Client, query: CallbackQuery):
    """Handle YouTube video quality selection button click."""
    parts = query.data.split(":")
    if len(parts) < 3:
        return await query.answer("Invalid selection.", show_alert=True)

    task_id = parts[1]
    quality = parts[2]

    task_info = _ALL_TASKS.get(task_id)
    if not task_info:
        return await query.answer("This download session has expired.", show_alert=True)

    if query.from_user.id != task_info["user_id"] and not Config.is_admin(query.from_user.id):
        return await query.answer("⚠️ You can only select quality for your own requests!", show_alert=True)

    await query.answer(f"Selected: {quality.upper()}")
    message = task_info["message"]
    url = task_info["url"]
    custom_name = task_info.get("custom_name")

    try:
        await query.message.delete()
    except Exception:
        pass

    await enqueue_download(client, message, url, quality=quality, task_id=task_id, custom_name=custom_name)


@Client.on_callback_query(filters.regex(r"^dl_cancel:"))
async def cancel_download_callback(client: Client, query: CallbackQuery):
    """Handle instant cancellation of queued or actively downloading tasks."""
    task_id = query.data.split(":")[1]
    job = _ALL_TASKS.get(task_id)

    if not job:
        return await query.answer("Task not found or already completed.", show_alert=True)

    if query.from_user.id != job["user_id"] and not Config.is_admin(query.from_user.id):
        return await query.answer("⚠️ You can only cancel your own downloads!", show_alert=True)

    job["cancelled"] = True
    progress: DownloadProgress | None = job.get("progress")
    if progress:
        progress.is_cancelled = True

    status_msg: Message | None = job.get("status_msg")
    if status_msg:
        try:
            await status_msg.edit_text("❌ <b>Download Cancelled by user.</b>")
        except Exception:
            pass

    await query.answer("Download cancelled successfully!", show_alert=True)


async def enqueue_download(client: Client, message: Message, url: str, quality: str = "best", task_id: str | None = None, custom_name: str | None = None):
    """Validate request, display queue position with Cancel button, and enqueue."""
    user = message.from_user
    user_id = user.id
    is_admin = Config.is_admin(user_id)

    max_size_bytes = (2000 if is_admin else Config.DOWNLOADER_MAX_SIZE) * 1024 * 1024
    platform = detect_platform(url)
    queue_len = DOWNLOAD_QUEUE.qsize()
    if not task_id:
        task_id = uuid.uuid4().hex[:8]

    cancel_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data=f"dl_cancel:{task_id}")
    ]])

    rename_text = f"\n🏷️ <b>Rename to:</b> <code>{html_escape(custom_name)}</code>" if custom_name else ""

    # If worker is currently busy, display queue position
    if _CURRENT_ACTIVE_JOB is not None or queue_len > 0:
        pos = queue_len + 1
        status_msg = await message.reply_text(
            f"🕒 <b>Added to Queue (Position #{pos})</b>\n\n"
            f"🌐 <b>Platform:</b> {platform}\n"
            f"🎬 <b>Quality:</b> {quality.upper()}{rename_text}\n"
            f"🔗 <b>Link:</b> <code>{html_escape(url[:50])}...</code>\n\n"
            f"<i>⏳ Your download will start automatically once earlier jobs complete!</i>",
            reply_markup=cancel_btn,
            disable_web_page_preview=True
        )
    else:
        status_msg = await message.reply_text(
            f"⚡ <b>Analyzing link from {platform}...</b>{rename_text}\n"
            f"<i>Please wait while your media is being fetched...</i>",
            reply_markup=cancel_btn,
            disable_web_page_preview=True
        )

    job = {
        "client": client,
        "message": message,
        "status_msg": status_msg,
        "url": url,
        "platform": platform,
        "quality": quality,
        "custom_name": custom_name,
        "task_id": task_id,
        "user_id": user_id,
        "is_admin": is_admin,
        "max_size_bytes": max_size_bytes,
        "cancelled": False,
        "progress": None,
        "enqueued_at": time.time()
    }

    _ALL_TASKS[task_id] = job
    await DOWNLOAD_QUEUE.put(job)
    ensure_worker_started(client)


async def live_download_reporter(status_msg: Message, platform: str, progress: DownloadProgress, task_id: str):
    """Background coroutine to periodically edit Telegram message with live download progress and Cancel button."""
    last_edit_time = 0
    last_text = ""
    cancel_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel Download", callback_data=f"dl_cancel:{task_id}")
    ]])

    while not progress.is_done and not progress.is_cancelled:
        await asyncio.sleep(2.5)
        now = time.time()
        if progress.total > 0 and (now - last_edit_time) >= 2.5:
            text = format_progress_caption(
                "⬇️ <b>Downloading</b>",
                platform,
                progress.current,
                progress.total,
                progress.speed,
                progress.eta
            )
            if text != last_text:
                try:
                    await status_msg.edit_text(text, reply_markup=cancel_btn)
                    last_text = text
                    last_edit_time = now
                except Exception:
                    pass


async def download_queue_worker(client: Client):
    """Singleton background worker pulling download tasks from DOWNLOAD_QUEUE sequentially."""
    global _CURRENT_ACTIVE_JOB
    logger.info("Download queue worker running.")

    while True:
        job = await DOWNLOAD_QUEUE.get()
        _CURRENT_ACTIVE_JOB = job

        task_id = job["task_id"]
        message: Message = job["message"]
        status_msg: Message = job["status_msg"]
        url: str = job["url"]
        platform: str = job["platform"]
        quality: str = job.get("quality", "best")
        custom_name: str | None = job.get("custom_name")
        user = message.from_user
        user_id: int = job["user_id"]
        max_size_bytes: int = job["max_size_bytes"]

        if job.get("cancelled"):
            _CURRENT_ACTIVE_JOB = None
            _ALL_TASKS.pop(task_id, None)
            DOWNLOAD_QUEUE.task_done()
            continue

        temp_dir = os.path.join("temp_downloads", f"{user_id}_{uuid.uuid4().hex[:8]}")
        os.makedirs(temp_dir, exist_ok=True)
        start_time = time.time()

        cancel_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel Download", callback_data=f"dl_cancel:{task_id}")
        ]])

        try:
            try:
                await status_msg.edit_text(
                    f"⚡ <b>Downloading from {platform}...</b>\n"
                    f"<i>Connecting to media stream...</i>",
                    reply_markup=cancel_btn
                )
            except Exception:
                pass

            progress = DownloadProgress()
            job["progress"] = progress
            reporter_task = asyncio.create_task(live_download_reporter(status_msg, platform, progress, task_id))

            media = None
            # Check if Telegram Post / Channel Link (from telegram_media_downloader)
            if is_telegram_url(url):
                t_match = re.search(r"t\.me/(?:c/(\d+)|([a-zA-Z0-9_]+))/(\d+)", url)
                if not t_match:
                    raise ValueError("Invalid Telegram post link format.")
                c_id, u_name, m_id = t_match.groups()
                target_chat = int(f"-100{c_id}") if c_id else f"@{u_name}"
                target_msg_id = int(m_id)

                try:
                    target_msg = await client.get_messages(target_chat, message_ids=target_msg_id)
                except Exception as te:
                    raise ValueError(f"Could not access Telegram message: {te}. Bot must be an admin or member of private channels.")

                if not target_msg or not target_msg.media:
                    raise ValueError("Telegram message contains no media or has been deleted.")

                # Download media using Pyrogram MTProto streamer with proper file extension
                is_p = bool(target_msg.photo)
                is_v = bool(target_msg.video or (not is_p and not target_msg.audio and not target_msg.voice and not target_msg.document))
                is_a = bool(target_msg.audio or target_msg.voice)

                if is_p:
                    f_name = custom_name or f"photo_{target_msg_id}.jpg"
                    if not any(f_name.lower().endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp")):
                        f_name += ".jpg"
                elif target_msg.video:
                    f_name = custom_name or getattr(target_msg.video, "file_name", None) or f"video_{target_msg_id}.mp4"
                    if not any(f_name.lower().endswith(e) for e in (".mp4", ".mkv", ".webm", ".avi", ".mov")):
                        f_name += ".mp4"
                elif is_a:
                    f_name = custom_name or getattr(target_msg.audio, "file_name", None) or f"audio_{target_msg_id}.mp3"
                else:
                    f_name = custom_name or getattr(target_msg.document, "file_name", None) or f"file_{target_msg_id}.bin"

                file_dest = os.path.join(temp_dir, f_name)
                last_tg_time = [time.time()]
                last_tg_bytes = [0]

                def tg_progress(current, total):
                    if progress.is_cancelled:
                        raise asyncio.CancelledError("Download cancelled by user.")
                    progress.total = total
                    progress.current = current
                    now = time.time()
                    diff = now - last_tg_time[0]
                    if diff >= 1.0:
                        speed = (current - last_tg_bytes[0]) / diff
                        progress.speed = speed
                        if total > current and speed > 0:
                            progress.eta = int((total - current) / speed)
                        last_tg_time[0] = now
                        last_tg_bytes[0] = current

                downloaded_file = await client.download_media(
                    target_msg,
                    file_name=file_dest,
                    progress=tg_progress
                )

                if not downloaded_file or not os.path.exists(downloaded_file):
                    raise FileNotFoundError("Could not download Telegram media to disk.")

                f_size = os.path.getsize(downloaded_file)
                f_name = os.path.basename(downloaded_file)
                v_dur = getattr(target_msg.video or target_msg.audio, "duration", None)
                v_w = getattr(target_msg.video, "width", None)
                v_h = getattr(target_msg.video, "height", None)

                media = {
                    "file_path": downloaded_file,
                    "file_name": f_name,
                    "file_size": f_size,
                    "title": f_name,
                    "is_photo": is_p,
                    "is_video": is_v,
                    "is_audio": is_a,
                    "duration": v_dur,
                    "width": v_w,
                    "height": v_h
                }
            else:
                try:
                    media = await download_media(url, temp_dir, max_size_bytes, progress=progress, quality=quality)
                finally:
                    progress.is_done = True
                    await reporter_task

            if job.get("cancelled") or progress.is_cancelled:
                raise asyncio.CancelledError("Download cancelled by user.")

            elapsed = round(time.time() - start_time, 1)

            file_path = media.get("file_path")
            file_name = media.get("file_name", "media.mp4")
            file_size = media.get("file_size", 0)
            title = media.get("title") or file_name
            is_photo = media.get("is_photo", False)
            is_video = media.get("is_video", not is_photo)
            is_audio = media.get("is_audio", False)
            duration = media.get("duration")
            width = media.get("width")
            height = media.get("height")
            extra_photos = media.get("extra_photos", [])

            # Handle custom renaming if requested
            if custom_name:
                ext = os.path.splitext(file_path)[1] or (".mp4" if is_video else ".bin")
                if not any(custom_name.lower().endswith(e) for e in (".mp4", ".mkv", ".webm", ".mp3", ".zip", ".rar", ".pdf")):
                    custom_name += ext
                new_clean_path = os.path.join(temp_dir, custom_name)
                try:
                    if file_path != new_clean_path:
                        os.rename(file_path, new_clean_path)
                        file_path = new_clean_path
                        file_name = custom_name
                        title = custom_name
                except Exception as re_err:
                    logger.warning(f"Could not rename file: {re_err}")

            readable_size = get_readable_size(file_size)

            try:
                await status_msg.edit_text(
                    f"📤 <b>Preparing Telegram upload...</b>\n\n"
                    f"<code>{make_progress_bar(0, file_size)}</code>\n"
                    f"📦 <b>Size:</b> {readable_size}"
                )
            except Exception:
                pass

            bot_uname = Config.BOT_USERNAME or "bot"
            icon = "📸" if is_photo else ("🎵" if is_audio else "🎬")
            user_caption = (
                f"{icon} <b>{html_escape(title[:60])}</b>\n\n"
                f"🌐 <b>Platform:</b> {platform}\n"
                f"📦 <b>Size:</b> {readable_size}\n"
                f"⚡ <b>Fast Delivery via:</b> @{bot_uname}"
            )

            # Multi-tier Thumbnail Resolution:
            # 1. Custom User Thumbnail (/setthumb in MongoDB)
            # 2. Extracted Platform Thumbnail (from YouTube, Instagram, LuLuStream, etc. in media["thumbnail"])
            # 3. Source Telegram Post Thumbnail (if source was a Telegram post)
            # 4. Auto-generated Video Frame (via PyAV + Pillow)
            thumb_path = None

            # Tier 1: Check user custom thumbnail
            user_doc = await mongo.users.find_one({"user_id": user_id})
            if user_doc and user_doc.get("custom_thumb"):
                try:
                    thumb_dest = os.path.join(temp_dir, "custom_thumb.jpg")
                    c_thumb = await client.download_media(user_doc["custom_thumb"], file_name=thumb_dest)
                    if c_thumb and os.path.exists(c_thumb):
                        thumb_path = c_thumb
                except Exception as th_err:
                    logger.warning(f"Could not fetch custom thumb: {th_err}")

            # Tier 2: Extractor / platform thumbnail
            if not thumb_path and media and media.get("thumbnail"):
                cand = media["thumbnail"]
                if isinstance(cand, str) and os.path.exists(cand) and os.path.getsize(cand) > 100:
                    thumb_path = cand

            # Tier 3: Telegram post thumbnail if downloading from Telegram
            if not thumb_path and is_telegram_url(url):
                try:
                    if 'target_msg' in locals() and target_msg and getattr(target_msg, "video", None) and target_msg.video.thumbs:
                        tg_thumb_dest = os.path.join(temp_dir, "tg_thumb.jpg")
                        downloaded_tg_th = await client.download_media(target_msg.video.thumbs[0].file_id, file_name=tg_thumb_dest)
                        if downloaded_tg_th and os.path.exists(downloaded_tg_th):
                            thumb_path = downloaded_tg_th
                except Exception as e_tgth:
                    logger.debug(f"Could not download Telegram message thumbnail: {e_tgth}")

            # Tier 4: Auto-extract video frame & fill duration/width/height if video
            if is_video and os.path.exists(file_path):
                try:
                    auto_thumb_dest = os.path.join(temp_dir, "auto_frame.jpg") if not thumb_path else None
                    vid_meta = await asyncio.to_thread(extract_video_metadata, file_path, auto_thumb_dest)
                    if not thumb_path and vid_meta.get("thumb_path"):
                        thumb_path = vid_meta["thumb_path"]
                    if not duration and vid_meta.get("duration"):
                        duration = vid_meta["duration"]
                    if not width and vid_meta.get("width"):
                        width = vid_meta["width"]
                    if not height and vid_meta.get("height"):
                        height = vid_meta["height"]
                except Exception as e_meta:
                    logger.debug(f"Could not extract video metadata/frame: {e_meta}")

            # Sanitize and normalize thumbnail to RGB JPEG <= 640x360
            if thumb_path and os.path.exists(thumb_path):
                try:
                    ready_thumb = os.path.join(temp_dir, "thumb_ready.jpg")
                    def _sanitize_thumb():
                        with Image.open(thumb_path) as im:
                            im = im.convert("RGB")
                            im.thumbnail((640, 360), Image.Resampling.LANCZOS)
                            im.save(ready_thumb, "JPEG", quality=85, optimize=True)
                    await asyncio.to_thread(_sanitize_thumb)
                    thumb_path = ready_thumb
                except Exception as proc_err:
                    logger.warning(f"Failed to process thumbnail image: {proc_err}")

            # Live upload progress tracker
            last_upload_edit = [0]
            last_upload_time = [time.time()]
            last_upload_bytes = [0]

            async def upload_progress_callback(current, total):
                now = time.time()
                if (now - last_upload_edit[0]) >= 3.0:
                    time_diff = now - last_upload_time[0]
                    speed = (current - last_upload_bytes[0]) / time_diff if time_diff > 0 else 0
                    eta = int((total - current) / speed) if speed > 0 and total > current else 0
                    
                    last_upload_edit[0] = now
                    last_upload_time[0] = now
                    last_upload_bytes[0] = current

                    up_text = format_progress_caption(
                        "📤 <b>Uploading to Telegram</b>",
                        "",
                        current,
                        total,
                        speed,
                        eta
                    )
                    try:
                        await status_msg.edit_text(up_text)
                    except Exception:
                        pass

            sent_msg = None
            if is_photo:
                if extra_photos:
                    try:
                        all_photos = [file_path] + [p for p in extra_photos if os.path.exists(p)]
                        media_group = [
                            InputMediaPhoto(p, caption=user_caption if idx == 0 else "")
                            for idx, p in enumerate(all_photos[:10])
                        ]
                        sent_msgs = await message.reply_media_group(media=media_group)
                        sent_msg = sent_msgs[0] if sent_msgs else None
                    except Exception as alb_err:
                        logger.warning(f"Failed to send media group, falling back to single photo: {alb_err}")
                        sent_msg = await message.reply_photo(photo=file_path, caption=user_caption)
                else:
                    sent_msg = await message.reply_photo(
                        photo=file_path,
                        caption=user_caption
                    )
            elif is_video:
                video_kwargs = {
                    "video": file_path,
                    "caption": user_caption,
                    "supports_streaming": True,
                    "progress": upload_progress_callback
                }
                if isinstance(duration, int) and duration > 0:
                    video_kwargs["duration"] = duration
                if isinstance(width, int) and width > 0:
                    video_kwargs["width"] = width
                if isinstance(height, int) and height > 0:
                    video_kwargs["height"] = height
                if thumb_path and os.path.exists(thumb_path):
                    video_kwargs["thumb"] = thumb_path

                sent_msg = await message.reply_video(**video_kwargs)

            elif is_audio:
                audio_kwargs = {
                    "audio": file_path,
                    "caption": user_caption,
                    "title": title,
                    "progress": upload_progress_callback
                }
                if isinstance(duration, int) and duration > 0:
                    audio_kwargs["duration"] = duration
                if thumb_path and os.path.exists(thumb_path):
                    audio_kwargs["thumb"] = thumb_path

                sent_msg = await message.reply_audio(**audio_kwargs)

            else:
                doc_kwargs = {
                    "document": file_path,
                    "caption": user_caption,
                    "progress": upload_progress_callback
                }
                if thumb_path and os.path.exists(thumb_path):
                    doc_kwargs["thumb"] = thumb_path

                sent_msg = await message.reply_document(**doc_kwargs)

            # Silent Dump Channel Audit
            dump_channel = getattr(Config, "DUMP_CHANNEL", 0) or getattr(Config, "LOG_CHANNEL", 0)
            if dump_channel:
                try:
                    dump_caption = (
                        f"📥 <b>#DOWNLOAD_AUDIT_LOG</b>\n\n"
                        f"👤 <b>User:</b> {user.mention} (<code>{user.id}</code>)\n"
                        f"🌐 <b>Platform:</b> {platform}\n"
                        f"🔗 <b>Source URL:</b> <code>{url}</code>\n"
                        f"📁 <b>File:</b> <code>{html_escape(file_name)}</code> ({readable_size})\n"
                        f"⏱️ <b>Time:</b> {elapsed}s"
                    )
                    if sent_msg:
                        await sent_msg.copy(chat_id=dump_channel, caption=dump_caption)
                    else:
                        valid_th = thumb_path if (thumb_path and os.path.exists(thumb_path)) else None
                        if is_photo:
                            await client.send_photo(dump_channel, photo=file_path, caption=dump_caption)
                        elif is_video:
                            await client.send_video(dump_channel, video=file_path, caption=dump_caption, supports_streaming=True, thumb=valid_th)
                        elif is_audio:
                            await client.send_audio(dump_channel, audio=file_path, caption=dump_caption, thumb=valid_th)
                        else:
                            await client.send_document(dump_channel, document=file_path, caption=dump_caption, thumb=valid_th)
                except Exception as e:
                    logger.warning(f"Could not forward to silent dump channel: {e}")

            # Update cooldown timestamp & global statistics
            _USER_LAST_DL[user_id] = time.time()
            clean_platform_key = re.sub(r'[^\w]', '', platform) or "Other"
            try:
                await mongo.dl_stats.update_one(
                    {"_id": "global"},
                    {
                        "$inc": {
                            "total_downloads": 1,
                            "total_bytes": file_size,
                            f"platforms.{clean_platform_key}": 1
                        }
                    },
                    upsert=True
                )
            except Exception:
                pass

            # Delete the status/progress message on completion
            try:
                await status_msg.delete()
            except Exception:
                pass

        except asyncio.CancelledError:
            logger.info(f"Download cancelled for task {task_id}")
            try:
                await status_msg.edit_text("❌ <b>Download Cancelled by user.</b>")
            except Exception:
                pass
        except ValueError as ve:
            logger.warning(f"Download notice for {url}: {ve}")
            try:
                await status_msg.edit_text(f"{str(ve)}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error processing {url} for user {user_id}: {e}", exc_info=True)
            try:
                await status_msg.edit_text(
                    f"❌ <b>Download Failed:</b>\n"
                    f"Could not fetch media from this link.\n\n"
                    f"<i>Error: {html_escape(str(e)[:160])}</i>"
                )
            except Exception:
                pass
        finally:
            clean_temp_dir(temp_dir)
            _CURRENT_ACTIVE_JOB = None
            _ALL_TASKS.pop(task_id, None)
            DOWNLOAD_QUEUE.task_done()


@Client.on_message(filters.command(["dlstats", "downloaderstats"]) & filters.private)
async def downloader_stats_handler(client: Client, message: Message):
    """Admin-only live dashboard for the Universal Downloader."""
    if not Config.is_admin(message.from_user.id):
        return

    doc = await mongo.dl_stats.find_one({"_id": "global"}) or {}
    total_dl = doc.get("total_downloads", 0)
    total_bytes = doc.get("total_bytes", 0)
    platforms = doc.get("platforms", {})

    active_queue = DOWNLOAD_QUEUE.qsize()
    is_busy = "⚡ Active Download Running" if _CURRENT_ACTIVE_JOB is not None else "🟢 Idle / Ready"

    top_platforms_str = ""
    if platforms:
        for p, count in sorted(platforms.items(), key=lambda x: x[1], reverse=True)[:5]:
            top_platforms_str += f"  • <b>{p}:</b> <code>{count:,}</code>\n"
    else:
        top_platforms_str = "  <i>No downloads logged yet.</i>\n"

    access_mode = Config.DOWNLOADER_ACCESS.upper()
    max_mb = Config.DOWNLOADER_MAX_SIZE

    stats_text = (
        "📊 <b>Universal Downloader Dashboard</b>\n\n"
        f"📥 <b>Total Downloads:</b> <code>{total_dl:,}</code>\n"
        f"📦 <b>Total Bandwidth:</b> <code>{get_readable_size(total_bytes)}</code>\n"
        f"🕒 <b>Active Queue:</b> <code>{active_queue}</code> waiting\n"
        f"⚡ <b>Worker Status:</b> <code>{is_busy}</code>\n"
        f"🛡️ <b>Access Policy:</b> <code>{access_mode}</code>\n"
        f"📏 <b>Max File Limit:</b> <code>{max_mb} MB</code>\n\n"
        f"🌐 <b>Top Platforms:</b>\n{top_platforms_str}"
    )

    await message.reply_text(stats_text)
