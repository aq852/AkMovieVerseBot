import os
import re
import time
import asyncio
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from hydrogram.errors import FloodWait, MessageNotModified
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from pyrogram.errors import FloodWait, MessageNotModified

from config import Config
from database.mongo import mongo
from database.files import save_file, save_files_bulk
from utils.helpers import get_chat_type_str
from utils.title_cleaner import PIRATE_SITES_PATTERN, URL_AND_WWW_PATTERN

logger = logging.getLogger(__name__)

# In-memory skip offsets and indexing status
SKIP_OFFSETS = {}
ACTIVE_INDEXES = set()
# channel_id -> {"status": "running" | "paused" | "stopped", "pause_event": asyncio.Event(), "task": asyncio.Task | None}
INDEXING_CONTROLS = {}

# Non-video junk extensions to filter out from indexing
JUNK_EXTENSIONS = {
    ".txt", ".nfo", ".html", ".htm", ".apk", ".exe", ".torrent",
    ".srt", ".sub", ".vtt", ".ass", ".jpg", ".jpeg", ".png",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso"
}


def sanitize_file_name(raw_name: str) -> str:
    """Auto-clean promotional tags, channels, links, websites, brackets while preserving title & extension."""
    if not raw_name:
        return "Untitled_Video.mp4"

    name, ext = os.path.splitext(raw_name)
    if not ext:
        ext = ".mp4"

    # 1. Strip promotional bracketed tags first so [Join t.me...] is not split: [Join @...], [Uploaded by ...], [Team ...], [Exclusive ...], (Telegram: ...)
    name = re.sub(r'\[\s*(?:join|team|uploaded|telegram|channel|exclusive|official|backup|promo|link|download|paid)[^\]]*\]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\(\s*(?:join|team|uploaded|telegram|channel|exclusive|official|backup|promo|link|download|paid)[^\)]*\)', '', name, flags=re.IGNORECASE)

    # 2. Strip URLs, domains, and t.me invite links
    name = URL_AND_WWW_PATTERN.sub('', name)
    name = re.sub(r'https?://[^\s\]\)]+', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(?:t\.me|telegram\.me|tg://)[^\s\]\)]*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'@[\w_]+', '', name)

    # 3. Strip domains with any TLD (.com, .nl, .lat, etc.) even with pirate site prefix: VegaMovies.nl, BollyFlix.org
    name = re.sub(r'\b[\w\-]+\.(?:com|in|org|net|me|site|xyz|top|live|info|to|tv|cc|pw|cz|co|nl|lat|baby|trade|vip|space|buzz|lol|fun|icu|app|is|pm|cx|wf|pro|biz|eu|asia|mobi|cam|style)\b', '', name, flags=re.IGNORECASE)

    # 4. Strip comprehensive pirate sites and scene rippers (VegaMovies, 1TamilMV, BollyFlix, KatmovieHD, etc.)
    name = PIRATE_SITES_PATTERN.sub('', name)

    # 5. Strip standalone leftover TLD extensions like .nl, .lat, .xyz if left behind
    name = re.sub(r'(?:^|[\s\._\-\[])\.(?:com|in|org|net|me|site|xyz|top|live|info|to|tv|cc|pw|cz|co|nl|lat|baby|trade|vip|space|buzz|lol|fun|icu|app|is|pm|cx|wf|pro|biz|eu|asia|mobi|cam|style)\b', '', name, flags=re.IGNORECASE)

    # 6. Clean multiple dots, underscores, brackets, and extra spaces
    name = re.sub(r'[\[\]\(\)\{\}]', ' ', name)
    name = re.sub(r'[\._\-]{2,}', '.', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip(' ._-')

    if not name or len(name) < 2:
        name = "Movie_Video"

    return f"{name}{ext}"


def is_junk_file(media_info: dict) -> tuple[bool, str]:
    """Check if file is junk/spam or a tiny sample/trailer video.
    Returns (is_junk: bool, reason: str)
    """
    file_name = (media_info.get("file_name") or "").lower()
    file_size = int(media_info.get("file_size") or 0)

    _, ext = os.path.splitext(file_name)
    if ext.lower() in JUNK_EXTENSIONS:
        return True, f"Junk extension: {ext}"

    # Sample video filtering: files < 20MB with sample/trailer in name
    if file_size < 20 * 1024 * 1024:
        if any(keyword in file_name for keyword in ["sample", "trailer", "preview"]):
            return True, "Sample/trailer video under 20MB"

    return False, ""


def make_progress_bar(pct: int, length: int = 10) -> str:
    """Generate visual progress bar e.g. [██████░░░░] 60%"""
    clamped_pct = max(0, min(100, pct))
    filled = int(length * clamped_pct / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {clamped_pct}%"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable form."""
    if seconds <= 0:
        return "0s"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def get_indexer_keyboard(channel_id: int, status: str = "running") -> InlineKeyboardMarkup:
    """Inline control keyboard for live indexing progress messages."""
    if status == "paused":
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("▶️ Resume", callback_data=f"idx_resume_{channel_id}"),
                InlineKeyboardButton("⏹️ Stop", callback_data=f"idx_stop_{channel_id}")
            ]
        ])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸️ Pause", callback_data=f"idx_pause_{channel_id}"),
            InlineKeyboardButton("⏹️ Stop", callback_data=f"idx_stop_{channel_id}")
        ]
    ])


def extract_media_info(message: Message, sanitize: bool = True) -> dict | None:
    """Extract standard media attributes from any Telegram document, video, or audio message."""
    media = message.document or message.video or message.audio
    if not media:
        return None

    file_type = "document"
    if message.video:
        file_type = "video"
    elif message.audio:
        file_type = "audio"

    # Derive file name with fallback to caption or generic name
    raw_file_name = getattr(media, "file_name", None)
    if not raw_file_name and message.caption:
        raw_file_name = message.caption.split("\n")[0][:64].strip()
    if not raw_file_name:
        raw_file_name = f"{file_type}_{media.file_unique_id}"

    file_name = sanitize_file_name(raw_file_name) if sanitize else raw_file_name

    return {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "file_name": file_name,
        "raw_file_name": raw_file_name,
        "file_size": media.file_size,
        "file_type": file_type,
        "mime_type": getattr(media, "mime_type", ""),
        "caption": message.caption or "",
        "channel_id": message.chat.id,
        "message_id": message.id
    }


# 1. Real-time Channel Listener
@Client.on_message(filters.channel & (filters.document | filters.video | filters.audio))
async def auto_channel_listener(client: Client, message: Message):
    """Automatically index media uploaded to configured storage channels."""
    if not Config.CHANNELS or message.chat.id not in Config.CHANNELS:
        return

    # Security Guard: Never auto-index from LOG_CHANNEL, UPDATES_CHANNEL, or DUMP_CHANNEL
    excluded_channels = {Config.LOG_CHANNEL, Config.UPDATES_CHANNEL, getattr(Config, "DUMP_CHANNEL", 0)}
    if message.chat.id in excluded_channels:
        return

    media_info = extract_media_info(message, sanitize=True)
    if not media_info:
        return

    # Skip junk files in auto listener
    is_junk, _ = is_junk_file(media_info)
    if is_junk:
        return

    media_info["source"] = "auto_index"
    try:
        from utils.web_server import get_stream_catalog_settings
        st_settings = await get_stream_catalog_settings()
        media_info["is_web_stream"] = not st_settings.get("is_paused", False) and st_settings.get("mode") != "cleared"
    except Exception:
        media_info["is_web_stream"] = True

    success, status = await save_file(media_info)
    if success:
        logger.info(f"Auto-indexed: {media_info['file_name']} from channel {message.chat.id}")
        # Automatically notify any users who requested this movie!
        try:
            from plugins.movie_requests import auto_notify_pending_requesters
            asyncio.create_task(auto_notify_pending_requesters(client, media_info))
        except Exception:
            pass

        # Automatically queue file for Auto-Post buffer (Updates Channel)
        try:
            from plugins.channel_post import queue_file_for_auto_post
            asyncio.create_task(queue_file_for_auto_post(client, media_info))
        except Exception as e:
            logger.debug(f"Error queueing auto post: {e}")

        # Check if newly uploaded file satisfies high audience demand
        try:
            from plugins.hype_drop import check_and_notify_high_demand
            asyncio.create_task(check_and_notify_high_demand(client, media_info))
        except Exception as e:
            logger.debug(f"Error checking high demand: {e}")

        # Automatically notify users who set a 'Notify Me' alert for this movie
        try:
            from plugins.upload_alerts import auto_notify_alert_subscribers
            asyncio.create_task(auto_notify_alert_subscribers(client, media_info))
        except Exception as e:
            logger.debug(f"Error notifying alert subscribers: {e}")


# 2. Skip offset setter: /setskip <number>
@Client.on_message(filters.command("setskip") & filters.private)
async def set_skip_command(client: Client, message: Message):
    """Set how many messages to skip during the next /index run."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply_text("⚠️ <b>Usage:</b> <code>/setskip [number]</code>\nExample: <code>/setskip 1000</code>")
        return

    skip_count = int(args[1])
    SKIP_OFFSETS[message.from_user.id] = skip_count
    await message.reply_text(f"✅ <b>Skip Offset Set:</b> Next <code>/index</code> will skip <code>{skip_count}</code> messages.")


# 3. Stop active indexing: /stopindex
@Client.on_message(filters.command(["stopindex", "cancelindex"]) & filters.private)
async def stop_index_command(client: Client, message: Message):
    """Stop and abort any currently running channel indexing task."""
    if not Config.is_admin(message.from_user.id):
        return

    if not ACTIVE_INDEXES:
        await message.reply_text("ℹ️ No active indexing tasks are currently running.")
        return

    # Signal stop to all active controls
    for cid in list(ACTIVE_INDEXES):
        ctrl = INDEXING_CONTROLS.get(cid)
        if ctrl:
            ctrl["status"] = "stopped"
            ctrl["pause_event"].set()

    ACTIVE_INDEXES.clear()
    await message.reply_text("⏹️ <b>Indexing Cancelled!</b> Crawling tasks will terminate and save bookmarks.")


# 4. Core Indexing Engine (Ultra-Fast 50x Bulk + Checkpoints + Inline Controls)
async def run_channel_crawl(
    client: Client,
    chat_id: int,
    progress_msg: Message,
    start_id: int,
    end_id: int,
    is_resumed: bool = False,
    saved_count: int = 0,
    duplicate_count: int = 0,
    error_count: int = 0,
    junk_count: int = 0,
    channel_title: str = "Storage Channel",
    is_web_stream: bool = False
):
    """Ultra-fast batch crawling engine with MongoDB checkpoints and live interactive controls."""
    ACTIVE_INDEXES.add(chat_id)
    pause_event = asyncio.Event()
    pause_event.set()
    INDEXING_CONTROLS[chat_id] = {
        "status": "running",
        "pause_event": pause_event,
        "progress_msg": progress_msg,
        "channel_title": channel_title
    }

    # Automatically enable web streaming if channel is whitelisted or mode is "all" (when not paused)
    if not is_web_stream:
        try:
            from utils.web_server import get_stream_catalog_settings
            st_settings = await get_stream_catalog_settings()
            stream_chans = st_settings.get("channels", [])
            stream_mode = st_settings.get("mode", "auto")
            is_paused = st_settings.get("is_paused", False)
            if not is_paused and stream_mode != "cleared":
                if chat_id in stream_chans or stream_mode == "all":
                    is_web_stream = True
        except Exception:
            pass

    BATCH_SIZE = 200
    total_scanned = 0
    start_time = time.time()
    last_update_time = time.time()

    # Initial checkpoint status
    try:
        await mongo.db["indexer_checkpoints"].update_one(
            {"channel_id": chat_id},
            {"$set": {
                "channel_id": chat_id,
                "channel_title": channel_title,
                "start_id": start_id,
                "last_scanned_id": start_id - 1 if start_id > 1 else 0,
                "end_id": end_id,
                "saved_count": saved_count,
                "duplicate_count": duplicate_count,
                "error_count": error_count,
                "junk_count": junk_count,
                "status": "running",
                "updated_at": time.time()
            }},
            upsert=True
        )
    except Exception as e:
        logger.warning(f"Error initializing checkpoint: {e}")

    try:
        for batch_start in range(start_id, end_id + 1, BATCH_SIZE):
            # 1. Check control status (stop or pause)
            ctrl = INDEXING_CONTROLS.get(chat_id, {})
            current_status = ctrl.get("status", "running")

            if current_status == "stopped" or chat_id not in ACTIVE_INDEXES:
                try:
                    await mongo.db["indexer_checkpoints"].update_one(
                        {"channel_id": chat_id},
                        {"$set": {"status": "interrupted", "updated_at": time.time()}}
                    )
                except Exception:
                    pass
                try:
                    await progress_msg.edit_text(
                        "⏹️ <b>Indexing Aborted by Admin!</b>\n\n"
                        f"📁 <b>Channel:</b> <code>{channel_title}</code>\n"
                        f"📊 <b>Progress Saved:</b> Msg <code>{batch_start - 1}</code> / <code>{end_id}</code>\n"
                        f"💾 <b>Files Indexed So Far:</b> <code>{saved_count}</code>\n\n"
                        "💡 <i>Resume anytime by typing</i> <code>/index resume</code> <i>or using checkpoints.</i>"
                    )
                except Exception:
                    pass
                return

            if current_status == "paused":
                try:
                    await mongo.db["indexer_checkpoints"].update_one(
                        {"channel_id": chat_id},
                        {"$set": {"status": "paused", "updated_at": time.time()}}
                    )
                except Exception:
                    pass
                logger.info(f"Indexing for channel {chat_id} is paused. Awaiting resume...")
                await pause_event.wait()
                if INDEXING_CONTROLS.get(chat_id, {}).get("status") == "stopped":
                    return

            batch_end = min(batch_start + BATCH_SIZE - 1, end_id)
            batch_ids = list(range(batch_start, batch_end + 1))

            try:
                messages = await client.get_messages(chat_id, batch_ids)
            except FloodWait as fw:
                logger.warning(f"FloodWait of {fw.value}s during batch {batch_start}-{batch_end}")
                await asyncio.sleep(fw.value)
                messages = await client.get_messages(chat_id, batch_ids)
            except Exception as e:
                logger.error(f"Error fetching batch {batch_start}-{batch_end}: {e}")
                continue

            if not messages:
                continue

            if not isinstance(messages, list):
                messages = [messages]

            batch_media = []
            for msg in messages:
                if not msg or getattr(msg, "empty", False):
                    continue
                total_scanned += 1
                media_info = extract_media_info(msg, sanitize=True)
                if not media_info:
                    continue

                is_junk, _ = is_junk_file(media_info)
                if is_junk:
                    junk_count += 1
                    continue

                if is_web_stream:
                    media_info["source"] = "auto_index"
                    media_info["is_web_stream"] = True
                else:
                    media_info["source"] = "bulk_index"
                    media_info["is_web_stream"] = False
                batch_media.append(media_info)

            # High-performance 50x bulk save into MongoDB
            if batch_media:
                bulk_res = await save_files_bulk(batch_media)
                saved_count += bulk_res["saved"]
                duplicate_count += bulk_res["duplicate"]
                error_count += bulk_res["errors"]

                if is_web_stream:
                    try:
                        from utils.web_server import clear_catalog_cache
                        clear_catalog_cache()
                    except Exception:
                        pass

                # Notify movie requesters for newly indexed files
                for sm in bulk_res.get("saved_media", []):
                    try:
                        from plugins.movie_requests import auto_notify_pending_requesters
                        asyncio.create_task(auto_notify_pending_requesters(client, sm))
                    except Exception:
                        pass

            # Auto-save persistent checkpoint bookmark in MongoDB after every batch
            try:
                await mongo.db["indexer_checkpoints"].update_one(
                    {"channel_id": chat_id},
                    {"$set": {
                        "channel_id": chat_id,
                        "channel_title": channel_title,
                        "last_scanned_id": batch_end,
                        "end_id": end_id,
                        "saved_count": saved_count,
                        "duplicate_count": duplicate_count,
                        "error_count": error_count,
                        "junk_count": junk_count,
                        "status": "running",
                        "updated_at": time.time()
                    }},
                    upsert=True
                )
            except Exception:
                pass

            # Update live interactive progress message every 5-6 seconds
            now = time.time()
            if now - last_update_time >= 5.5:
                last_update_time = now
                elapsed = max(0.1, now - start_time)
                speed = total_scanned / elapsed
                remaining_msgs = max(0, end_id - batch_end)
                eta_secs = remaining_msgs / speed if speed > 0 else 0
                total_target = max(1, end_id - start_id + 1)
                pct = int((min(total_scanned, total_target) / total_target) * 100)
                bar = make_progress_bar(pct)
                eta_str = format_duration(eta_secs)

                progress_text = (
                    f"⚡ <b>Ultra-Fast Batch Indexing in Progress...</b>\n"
                    f"📁 <b>Channel:</b> <code>{channel_title}</code>\n"
                    f"📊 <b>Progress:</b> {bar}\n\n"
                    f"🔢 <b>Messages Scanned:</b> <code>{batch_end}</code> / <code>{end_id}</code>\n"
                    f"💾 <b>New Files Indexed:</b> <code>{saved_count:,}</code>\n"
                    f"⏩ <b>Duplicates Skipped:</b> <code>{duplicate_count:,}</code>\n"
                    f"🗑️ <b>Junk/Samples Filtered:</b> <code>{junk_count:,}</code>\n"
                    f"⚠️ <b>Errors:</b> <code>{error_count}</code>\n\n"
                    f"🚀 <b>Speed:</b> <code>{speed:.1f} msgs/sec</code>\n"
                    f"⏳ <b>ETA:</b> <code>{eta_str}</code>\n\n"
                    f"<i>💡 Progress auto-checkpoints every 200 msgs. Control crawl below:</i>"
                )
                try:
                    await progress_msg.edit_text(
                        progress_text,
                        reply_markup=get_indexer_keyboard(chat_id, status="running")
                    )
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except MessageNotModified:
                    pass
                except Exception as e:
                    logger.debug(f"Progress edit error: {e}")

            # Light pacing to respect Telegram MTProto limits
            await asyncio.sleep(0.08)

        # 100% Indexing Completed -> Mark checkpoint completed in MongoDB
        try:
            await mongo.db["indexer_checkpoints"].update_one(
                {"channel_id": chat_id},
                {"$set": {
                    "status": "completed",
                    "last_scanned_id": end_id,
                    "saved_count": saved_count,
                    "duplicate_count": duplicate_count,
                    "junk_count": junk_count,
                    "updated_at": time.time()
                }}
            )
        except Exception:
            pass

        total_elapsed = format_duration(time.time() - start_time)
        final_text = (
            f"🎉 <b>Indexing Completed Successfully!</b>\n\n"
            f"📁 <b>Channel:</b> <code>{channel_title}</code>\n"
            f"🔢 <b>Total Scanned:</b> <code>{total_scanned:,}</code> messages\n"
            f"💾 <b>New Files Indexed:</b> <code>{saved_count:,}</code>\n"
            f"⏩ <b>Duplicates Skipped:</b> <code>{duplicate_count:,}</code>\n"
            f"🗑️ <b>Junk Files Filtered:</b> <code>{junk_count:,}</code>\n"
            f"⏱️ <b>Time Taken:</b> <code>{total_elapsed}</code>\n\n"
            f"✨ All files are now searchable in bot PM, groups, and streaming website!"
        )
        try:
            await progress_msg.edit_text(final_text)
        except Exception:
            pass

    except FloodWait as fw:
        logger.warning(f"FloodWait in crawl: {fw.value}s")
        await asyncio.sleep(fw.value)
    except Exception as e:
        logger.error(f"Error during indexing of {chat_id}: {e}")
        try:
            await mongo.db["indexer_checkpoints"].update_one(
                {"channel_id": chat_id},
                {"$set": {"status": "interrupted", "updated_at": time.time()}}
            )
        except Exception:
            pass
        try:
            await progress_msg.edit_text(
                f"❌ <b>Indexing Interrupted due to error:</b> <code>{e}</code>\n\n"
                f"📁 <b>Channel:</b> <code>{channel_title}</code>\n"
                f"💾 <b>Saved So Far:</b> <code>{saved_count}</code> files\n\n"
                f"💡 <i>Your progress bookmark has been safely saved! You can resume anytime using:</i> <code>/index resume</code>"
            )
        except Exception:
            pass
    finally:
        ACTIVE_INDEXES.discard(chat_id)
        INDEXING_CONTROLS.pop(chat_id, None)


# 5. Batch Indexer: /index <channel_id_or_username_or_link>
@Client.on_message(filters.command("index"))
async def batch_index_command(client: Client, message: Message):
    """Batch crawl and index existing media history from a storage channel."""
    if not Config.is_admin(message.from_user.id):
        return

    chat_id = None
    last_msg_id = None
    raw_args = message.text.split()
    is_stream_index = any(a.lower() in ("-stream", "--stream", "-web", "--web") for a in raw_args)
    args = [a for a in raw_args if a.lower() not in ("-stream", "--stream", "-web", "--web")]

    is_resumed = False
    saved_count = 0
    duplicate_count = 0
    error_count = 0
    junk_count = 0
    start_id = 1
    end_id = 1000

    # Case 0: /index resume -> Pick up latest interrupted or paused checkpoint
    if len(args) > 1 and args[1].lower() in ("resume", "-resume", "--resume"):
        chk = await mongo.db["indexer_checkpoints"].find_one(
            {"status": {"$in": ["running", "paused", "interrupted"]}},
            sort=[("updated_at", -1)]
        )
        if not chk:
            # Fallback to any checkpoint where last_scanned_id < end_id
            chk = await mongo.db["indexer_checkpoints"].find_one(
                {"$expr": {"$lt": ["$last_scanned_id", "$end_id"]}},
                sort=[("updated_at", -1)]
            )
        if not chk:
            return await message.reply_text(
                "ℹ️ <b>No interrupted indexing checkpoints found.</b>\n"
                "All previous indexing jobs completed successfully!"
            )

        chat_id = chk["channel_id"]
        start_id = chk.get("last_scanned_id", 0) + 1
        end_id = chk.get("end_id", 1000)
        saved_count = chk.get("saved_count", 0)
        duplicate_count = chk.get("duplicate_count", 0)
        error_count = chk.get("error_count", 0)
        junk_count = chk.get("junk_count", 0)
        is_resumed = True

    # Case 1: Argument provided (/index <link_or_id>)
    elif len(args) > 1:
        raw_input = args[1].strip()

        # Check if argument is a private channel link: https://t.me/c/2001671856/20
        c_link = re.match(r"(?:https?://)?(?:t\.me|telegram\.me)/c/(\d+)/(\d+)", raw_input)
        if c_link:
            chat_id = int(f"-100{c_link.group(1)}")
            last_msg_id = int(c_link.group(2))
        else:
            # Check if argument is a public channel link: https://t.me/channel_name/20
            pub_link = re.match(r"(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)/(\d+)", raw_input)
            if pub_link:
                chat_id = pub_link.group(1)
                last_msg_id = int(pub_link.group(2))
            else:
                # Raw chat ID or username (/index -1002001671856 or /index @channel)
                if raw_input.lstrip("-").isdigit():
                    chat_id = int(raw_input)
                else:
                    chat_id = raw_input
                # Optional second argument for end_id: /index -1002001671856 500
                if len(args) > 2 and args[2].isdigit():
                    last_msg_id = int(args[2])

    # Case 2: Reply to a forwarded post
    elif message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            chat_id = reply.forward_from_chat.id
            last_msg_id = reply.forward_from_message_id
        elif reply.forward_from_message_id:
            last_msg_id = reply.forward_from_message_id

    # Case 3: Executed directly inside the channel or group
    elif get_chat_type_str(message.chat.type) in ["channel", "supergroup", "group"]:
        chat_id = message.chat.id
        last_msg_id = message.id

    if not chat_id:
        await message.reply_text(
            "⚠️ <b>How to Index a Channel:</b>\n\n"
            "1. <b>Via Post Link:</b> <code>/index https://t.me/c/2001671856/20</code>\n"
            "2. <b>Via Forward:</b> Forward the latest post from your channel here and reply to it with <code>/index</code>\n"
            "3. <b>Via Channel ID &amp; Message Count:</b> <code>/index -1002001671856 50</code>\n"
            "4. <b>Resume Interrupted Job:</b> <code>/index resume</code>\n"
            "5. <b>Index All Storage Channels:</b> <code>/indexall</code>\n\n"
            "<i>Make sure the bot is an Admin in the channel with post reading rights!</i>"
        )
        return

    # Verify access to chat
    try:
        chat_info = await client.get_chat(chat_id)
        chat_id = chat_info.id
        channel_title = chat_info.title
    except Exception as e:
        await message.reply_text(f"❌ <b>Error accessing channel:</b> <code>{e}</code>\nMake sure the bot is an Admin in the channel!")
        return

    if chat_id in ACTIVE_INDEXES:
        await message.reply_text("⚠️ An indexing job is already running for this channel!")
        return

    # If last_msg_id was not resolved from link or forward, probe the channel
    if not last_msg_id and not is_resumed:
        try:
            probe = await client.send_message(chat_id, "🔄 Connecting indexer...")
            last_msg_id = probe.id
            await probe.delete()
        except Exception:
            last_msg_id = 1000

    if not is_resumed:
        chk = await mongo.db["indexer_checkpoints"].find_one({"channel_id": chat_id})
        skip_count = SKIP_OFFSETS.pop(message.from_user.id, 0)
        if chk and chk.get("last_scanned_id", 0) > 0 and skip_count == 0 and chk.get("last_scanned_id", 0) < (chk.get("end_id") or last_msg_id):
            start_id = chk["last_scanned_id"] + 1
            end_id = chk.get("end_id") or last_msg_id
            saved_count = chk.get("saved_count", 0)
            duplicate_count = chk.get("duplicate_count", 0)
            error_count = chk.get("error_count", 0)
            junk_count = chk.get("junk_count", 0)
            is_resumed = True
        else:
            start_id = skip_count + 1
            end_id = last_msg_id or 1000

    stream_badge = "\n🌐 <b>Web Streaming Catalog:</b> 🟢 AUTO-PUBLISH ENABLED" if is_stream_index else ""
    heading_title = "🔄 <b>Resuming Indexing from Checkpoint:</b>" if is_resumed else "🔄 <b>Starting Batch Indexing for:</b>"
    progress_msg = await message.reply_text(
        f"{heading_title} <code>{channel_title}</code>\n"
        f"📊 <b>Target Range:</b> Message <code>{start_id}</code> to <code>{end_id}</code>\n"
        f"🚀 <b>Batch Size:</b> 200 messages / request{stream_badge}\n"
        f"<i>💡 Progress bookmark is auto-saved every 200 msgs. Control below:</i>",
        reply_markup=get_indexer_keyboard(chat_id, status="running")
    )

    asyncio.create_task(
        run_channel_crawl(
            client=client,
            chat_id=chat_id,
            progress_msg=progress_msg,
            start_id=start_id,
            end_id=end_id,
            is_resumed=is_resumed,
            saved_count=saved_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            junk_count=junk_count,
            channel_title=channel_title,
            is_web_stream=is_stream_index
        )
    )


# 6. Multi-Channel Batch Indexer: /indexall
@Client.on_message(filters.command(["indexall", "crawlall"]) & filters.private)
async def index_all_channels_command(client: Client, message: Message):
    """Sequentially crawl and index all configured storage channels in Config.CHANNELS."""
    if not Config.is_admin(message.from_user.id):
        return

    if not Config.CHANNELS:
        return await message.reply_text("⚠️ No storage channels configured in <code>Config.CHANNELS</code>!")

    is_stream_all = any(a.lower() in ("-stream", "--stream", "-web", "--web") for a in message.text.split())

    status_msg = await message.reply_text(
        f"🌐 <b>Multi-Channel Indexing Initializing...</b>\n"
        f"Found <code>{len(Config.CHANNELS)}</code> channels in configuration.\n"
        f"Starting sequential crawl with 50x bulk engine..."
        f"{' (Web Streaming Auto-Publish: ON)' if is_stream_all else ''}"
    )

    for i, cid in enumerate(Config.CHANNELS, 1):
        try:
            chat_info = await client.get_chat(cid)
            channel_title = chat_info.title
        except Exception as e:
            await message.reply_text(f"⚠️ Channel <code>{cid}</code> skipped: <code>{e}</code>")
            continue

        if cid in ACTIVE_INDEXES:
            await message.reply_text(f"⏩ Channel <code>{channel_title}</code> is already indexing. Skipping...")
            continue

        chk = await mongo.db["indexer_checkpoints"].find_one({"channel_id": cid})
        try:
            probe = await client.send_message(cid, "🔄 Connecting indexer...")
            latest_id = probe.id
            await probe.delete()
        except Exception:
            latest_id = 1000

        start_id = 1
        if chk and chk.get("last_scanned_id", 0) > 0 and chk.get("last_scanned_id", 0) < latest_id:
            start_id = chk["last_scanned_id"] + 1

        sub_progress = await message.reply_text(
            f"📁 <b>Channel {i}/{len(Config.CHANNELS)}:</b> <code>{channel_title}</code>\n"
            f"Range: <code>{start_id}</code> to <code>{latest_id}</code>\n"
            f"Starting bulk crawl...",
            reply_markup=get_indexer_keyboard(cid, status="running")
        )

        await run_channel_crawl(
            client=client,
            chat_id=cid,
            progress_msg=sub_progress,
            start_id=start_id,
            end_id=latest_id,
            is_resumed=(start_id > 1),
            saved_count=chk.get("saved_count", 0) if chk else 0,
            duplicate_count=chk.get("duplicate_count", 0) if chk else 0,
            error_count=chk.get("error_count", 0) if chk else 0,
            junk_count=chk.get("junk_count", 0) if chk else 0,
            channel_title=channel_title,
            is_web_stream=is_stream_all
        )

    await status_msg.edit_text("🎉 <b>All configured storage channels have been indexed successfully!</b>")


# 7. Interactive Callback Handler for Live Progress Buttons ([⏸ Pause], [▶️ Resume], [⏹ Stop])
@Client.on_callback_query(filters.regex(r"^idx_"))
async def indexer_callback_handler(client: Client, query: CallbackQuery):
    """Handle pause, resume, and stop buttons on live indexing progress messages."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Admin access required!", show_alert=True)

    data = query.data
    parts = data.split("_")
    action = parts[1]
    cid = int(parts[2])

    ctrl = INDEXING_CONTROLS.get(cid)

    # Action 1: Pause Indexing
    if action == "pause":
        if ctrl:
            ctrl["status"] = "paused"
            ctrl["pause_event"].clear()
        try:
            await mongo.db["indexer_checkpoints"].update_one(
                {"channel_id": cid},
                {"$set": {"status": "paused", "updated_at": time.time()}}
            )
        except Exception:
            pass
        try:
            await query.message.edit_reply_markup(reply_markup=get_indexer_keyboard(cid, status="paused"))
        except Exception:
            pass
        return await query.answer("⏸️ Indexing paused! Tap ▶️ Resume to continue.", show_alert=False)

    # Action 2: Resume Indexing
    elif action == "resume":
        if ctrl and ctrl.get("status") == "paused":
            ctrl["status"] = "running"
            ctrl["pause_event"].set()
            try:
                await mongo.db["indexer_checkpoints"].update_one(
                    {"channel_id": cid},
                    {"$set": {"status": "running", "updated_at": time.time()}}
                )
            except Exception:
                pass
            try:
                await query.message.edit_reply_markup(reply_markup=get_indexer_keyboard(cid, status="running"))
            except Exception:
                pass
            return await query.answer("▶️ Indexing resumed!", show_alert=False)

        # If not active in memory (e.g. after bot restart), pick up checkpoint directly
        chk = await mongo.db["indexer_checkpoints"].find_one({"channel_id": cid})
        if not chk:
            return await query.answer("⚠️ No checkpoint found for this channel!", show_alert=True)

        if cid in ACTIVE_INDEXES:
            return await query.answer("⚠️ An indexing job is already active for this channel!", show_alert=True)

        start_id = chk.get("last_scanned_id", 0) + 1
        end_id = chk.get("end_id", 1000)
        channel_title = chk.get("channel_title", "Storage Channel")

        await query.answer("🚀 Resuming indexing from checkpoint...")
        await query.message.edit_text(
            f"🔄 <b>Resuming Indexing for:</b> <code>{channel_title}</code>\n"
            f"📊 <b>Target Range:</b> Message <code>{start_id}</code> to <code>{end_id}</code>\n"
            f"🚀 <b>Batch Size:</b> 200 messages / request",
            reply_markup=get_indexer_keyboard(cid, status="running")
        )

        asyncio.create_task(
            run_channel_crawl(
                client=client,
                chat_id=cid,
                progress_msg=query.message,
                start_id=start_id,
                end_id=end_id,
                is_resumed=True,
                saved_count=chk.get("saved_count", 0),
                duplicate_count=chk.get("duplicate_count", 0),
                error_count=chk.get("error_count", 0),
                junk_count=chk.get("junk_count", 0),
                channel_title=channel_title
            )
        )

    # Action 3: Stop Indexing
    elif action == "stop":
        if ctrl:
            ctrl["status"] = "stopped"
            ctrl["pause_event"].set()
        try:
            await mongo.db["indexer_checkpoints"].update_one(
                {"channel_id": cid},
                {"$set": {"status": "interrupted", "updated_at": time.time()}}
            )
        except Exception:
            pass
        ACTIVE_INDEXES.discard(cid)
        INDEXING_CONTROLS.pop(cid, None)
        try:
            await query.message.edit_text(
                "⏹️ <b>Indexing Cancelled by Admin!</b>\n\n"
                "💡 <i>Progress bookmark has been saved to MongoDB. You can resume anytime using:</i> <code>/index resume</code>"
            )
        except Exception:
            pass
        return await query.answer("⏹️ Indexing cancelled!", show_alert=False)


# 8. View/Clear Saved Checkpoints: /checkpoints
@Client.on_message(filters.command(["checkpoints", "indexcheckpoints"]) & filters.private)
async def list_checkpoints_command(client: Client, message: Message):
    """View active interrupted indexing checkpoints or clear them."""
    if not Config.is_admin(message.from_user.id):
        return

    text_parts = message.text.split()
    if len(text_parts) > 1 and text_parts[1].lower() in ("clear", "wipe", "del", "clean"):
        await mongo.db["indexer_checkpoints"].delete_many({})
        return await message.reply_text("🗑️ <b>All Indexing Checkpoints Cleared!</b>")

    cursor = mongo.db["indexer_checkpoints"].find({})
    items = await cursor.to_list(length=20)

    if not items:
        return await message.reply_text("✅ <b>No Pending Checkpoints!</b>\nAll channel indexing crawls have completed 100% successfully.")

    out = "📋 <b>Interrupted Indexing Checkpoints:</b>\n────────────────────────\n"
    buttons = []
    for it in items:
        cid = it.get("channel_id")
        status_icon = "⏸️" if it.get("status") == "paused" else ("⏹️" if it.get("status") == "interrupted" else "🔄")
        out += (
            f"📁 <b>{it.get('channel_title', 'Channel')}</b> (<code>{cid}</code>)\n"
            f"  • Status: {status_icon} <code>{it.get('status', 'saved')}</code>\n"
            f"  • Progress: Msg <code>#{it.get('last_scanned_id')}</code> / <code>#{it.get('end_id')}</code>\n"
            f"  • Indexed so far: <code>{it.get('saved_count', 0)}</code> files\n\n"
        )
        if it.get("last_scanned_id", 0) < it.get("end_id", 0):
            buttons.append([InlineKeyboardButton(f"▶️ Resume {it.get('channel_title', 'Channel')[:18]}", callback_data=f"idx_resume_{cid}")])

    out += "<i>To continue crawling:</i> <code>/index resume</code>\n<i>To clear checkpoints:</i> <code>/checkpoints clear</code>"
    kb = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(out, reply_markup=kb)


# 9. Startup Checkpoint Notifier (Alerts admin if an indexing job was active before restart)
async def check_and_notify_interrupted_checkpoints(client: Client):
    """Detect interrupted indexing jobs on bot startup and alert admin with 1-click resume button."""
    try:
        await asyncio.sleep(8)  # Allow client to fully initialize
        cursor = mongo.db["indexer_checkpoints"].find({"status": {"$in": ["running", "paused", "interrupted"]}})
        items = await cursor.to_list(length=10)
        if not items:
            return

        for it in items:
            cid = it.get("channel_id")
            last_id = it.get("last_scanned_id", 0)
            end_id = it.get("end_id", 0)
            if last_id >= end_id:
                continue

            channel_title = it.get("channel_title", "Storage Channel")
            saved = it.get("saved_count", 0)

            alert_text = (
                f"⚠️ <b>Interrupted Indexing Job Detected!</b>\n\n"
                f"Bot restart hone se pehle is channel ki indexing chal rahi thi:\n"
                f"📁 <b>Channel:</b> <code>{channel_title}</code>\n"
                f"🔢 <b>Last Scanned:</b> Msg <code>{last_id}</code> / <code>{end_id}</code>\n"
                f"💾 <b>Files Indexed:</b> <code>{saved:,}</code> files\n\n"
                f"Ek click me vahi se continue karne ke liye neeche button dabayein:"
            )
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("▶️ Resume Indexing", callback_data=f"idx_resume_{cid}"),
                    InlineKeyboardButton("⏹️ Dismiss", callback_data=f"idx_stop_{cid}")
                ]
            ])

            # Send to primary admin
            admin_id = Config.ADMINS[0] if Config.ADMINS else None
            if admin_id:
                try:
                    await client.send_message(admin_id, alert_text, reply_markup=kb)
                except Exception as e:
                    logger.debug(f"Could not alert admin {admin_id}: {e}")
                    if Config.LOG_CHANNEL:
                        await client.send_message(Config.LOG_CHANNEL, alert_text, reply_markup=kb)
    except Exception as e:
        logger.warning(f"Error checking interrupted checkpoints on startup: {e}")
