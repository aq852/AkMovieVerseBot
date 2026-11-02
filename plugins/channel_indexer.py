import re
import time
import asyncio
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message
    from hydrogram.errors import FloodWait
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message
    from pyrogram.errors import FloodWait

from config import Config
from database.mongo import mongo
from database.files import save_file
from utils.helpers import get_chat_type_str

logger = logging.getLogger(__name__)

# In-memory skip offsets and indexing status
SKIP_OFFSETS = {}
ACTIVE_INDEXES = set()

def extract_media_info(message: Message) -> dict | None:
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
    file_name = getattr(media, "file_name", None)
    if not file_name and message.caption:
        file_name = message.caption.split("\n")[0][:64].strip()
    if not file_name:
        file_name = f"{file_type}_{media.file_unique_id}"

    return {
        "file_id": media.file_id,
        "file_unique_id": media.file_unique_id,
        "file_name": file_name,
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

    media_info = extract_media_info(message)
    if not media_info:
        return

    success, status = await save_file(media_info)
    if success:
        logger.info(f"Auto-indexed: {media_info['file_name']} from channel {message.chat.id}")
        # Automatically notify any users who requested this movie!
        from plugins.movie_requests import auto_notify_pending_requesters
        asyncio.create_task(auto_notify_pending_requesters(client, media_info))

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
        await message.reply_text("⚠️ **Usage:** `/setskip [number]`\nExample: `/setskip 1000`")
        return

    skip_count = int(args[1])
    SKIP_OFFSETS[message.from_user.id] = skip_count
    await message.reply_text(f"✅ **Skip Offset Set:** Next `/index` will skip `{skip_count}` messages.")


# 3. Stop active indexing: /stopindex
@Client.on_message(filters.command(["stopindex", "cancelindex"]) & filters.private)
async def stop_index_command(client: Client, message: Message):
    """Stop and abort any currently running channel indexing task."""
    if not Config.is_admin(message.from_user.id):
        return

    if not ACTIVE_INDEXES:
        await message.reply_text("ℹ️ No active indexing tasks are currently running.")
        return

    ACTIVE_INDEXES.clear()
    await message.reply_text("⏹️ **Indexing Cancelled!** Crawling task will terminate immediately.")


# 4. Batch Indexer: /index <channel_id_or_username_or_link>
@Client.on_message(filters.command("index"))
async def batch_index_command(client: Client, message: Message):
    """Batch crawl and index existing media history from a storage channel."""
    if not Config.is_admin(message.from_user.id):
        return

    chat_id = None
    last_msg_id = None
    args = message.text.split()

    is_resumed = False
    # Check if user requested to resume an interrupted job: /index resume
    if len(args) > 1 and args[1].lower() in ("resume", "-resume", "--resume"):
        chk = await mongo.db["indexer_checkpoints"].find_one(sort=[("updated_at", -1)])
        if not chk:
            return await message.reply_text("ℹ️ <b>No interrupted indexing checkpoints found.</b>\nAll previous indexing jobs completed successfully!")
        chat_id = chk["channel_id"]
        start_id = chk.get("last_scanned_id", 0) + 1
        end_id = chk.get("end_id", 1000)
        saved_count = chk.get("saved_count", 0)
        duplicate_count = chk.get("duplicate_count", 0)
        error_count = chk.get("error_count", 0)
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
            "⚠️ **How to Index a Channel:**\n\n"
            "1. **Via Post Link:** `/index https://t.me/c/2001671856/20`\n"
            "2. **Via Forward:** Forward the latest post from your channel here and reply to it with `/index`\n"
            "3. **Via Channel ID & Message Count:** `/index -1002001671856 50`\n\n"
            "_Make sure the bot is an Admin in the channel with post reading rights!_"
        )
        return

    # Verify access to chat
    try:
        chat_info = await client.get_chat(chat_id)
        chat_id = chat_info.id
    except Exception as e:
        await message.reply_text(f"❌ **Error accessing channel:** `{e}`\nMake sure the bot is an Admin in the channel!")
        return

    if chat_id in ACTIVE_INDEXES:
        await message.reply_text("⚠️ An indexing job is already running for this channel!")
        return

    # If last_msg_id was not resolved from link or forward, probe the channel
    if not last_msg_id:
        try:
            probe = await client.send_message(chat_id, "🔄 Connecting indexer...")
            last_msg_id = probe.id
            await probe.delete()
        except Exception:
            last_msg_id = 1000

    ACTIVE_INDEXES.add(chat_id)
    if not is_resumed:
        chk = await mongo.db["indexer_checkpoints"].find_one({"channel_id": chat_id})
        skip_count = SKIP_OFFSETS.pop(message.from_user.id, 0)
        if chk and chk.get("last_scanned_id", 0) > 0 and skip_count == 0:
            start_id = chk["last_scanned_id"] + 1
            end_id = chk.get("end_id") or last_msg_id
            saved_count = chk.get("saved_count", 0)
            duplicate_count = chk.get("duplicate_count", 0)
            error_count = chk.get("error_count", 0)
            is_resumed = True
        else:
            start_id = skip_count + 1
            end_id = last_msg_id
            saved_count = 0
            duplicate_count = 0
            error_count = 0
    else:
        # Values already loaded from resume check
        pass

    heading_title = "🔄 **Resuming Indexing from Checkpoint:**" if is_resumed else "🔄 **Starting Batch Indexing for:**"
    progress_msg = await message.reply_text(
        f"{heading_title} `{chat_info.title}`\n"
        f"📊 **Target Range:** Message `{start_id}` to `{end_id}`\n"
        f"🚀 **Batch Size:** 200 messages / request\n"
        f"<i>💡 Progress bookmark is auto-saved every 200 msgs.</i>"
    )

    total_scanned = 0
    last_update_time = time.time()
    BATCH_SIZE = 200

    try:
        for batch_start in range(start_id, end_id + 1, BATCH_SIZE):
            if chat_id not in ACTIVE_INDEXES:
                await progress_msg.edit_text("⏹️ **Indexing Aborted by Admin!**\n<i>Checkpoint bookmark saved. You can continue later with:</i> <code>/index resume</code>")
                return
            batch_end = min(batch_start + BATCH_SIZE, end_id + 1)
            batch_ids = list(range(batch_start, batch_end))

            try:
                messages = await client.get_messages(chat_id, batch_ids)
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                messages = await client.get_messages(chat_id, batch_ids)
            except Exception as e:
                logger.error(f"Error fetching batch {batch_start}-{batch_end}: {e}")
                continue

            if not messages:
                continue

            if not isinstance(messages, list):
                messages = [messages]

            for msg in messages:
                if not msg or getattr(msg, "empty", False):
                    continue
                total_scanned += 1
                media_info = extract_media_info(msg)
                if media_info:
                    success, status = await save_file(media_info)
                    if success:
                        saved_count += 1
                        from plugins.movie_requests import auto_notify_pending_requesters
                        asyncio.create_task(auto_notify_pending_requesters(client, media_info))
                    elif status == "duplicate":
                        duplicate_count += 1
                    else:
                        error_count += 1

            # Auto-save checkpoint bookmark in MongoDB every batch
            try:
                await mongo.db["indexer_checkpoints"].update_one(
                    {"channel_id": chat_id},
                    {"$set": {
                        "channel_id": chat_id,
                        "channel_title": chat_info.title,
                        "last_scanned_id": batch_end,
                        "end_id": end_id,
                        "saved_count": saved_count,
                        "duplicate_count": duplicate_count,
                        "error_count": error_count,
                        "updated_at": time.time()
                    }},
                    upsert=True
                )
            except Exception:
                pass

            # Progress edit every 6 seconds
            if time.time() - last_update_time > 6:
                last_update_time = time.time()
                pct = int((batch_end / end_id) * 100) if end_id else 0
                try:
                    await progress_msg.edit_text(
                        f"📊 **Indexing in Progress... ({pct}%)**\n\n"
                        f"📁 **Channel:** `{chat_info.title}`\n"
                        f"🔢 **Messages Scanned:** `{batch_end}` / `{end_id}`\n"
                        f"💾 **New Files Indexed:** `{saved_count}`\n"
                        f"⏩ **Duplicates Skipped:** `{duplicate_count}`\n"
                        f"⚠️ **Errors:** `{error_count}`"
                    )
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception:
                    pass

            # Gentle throttle to prevent Telegram MTProto FloodWait during massive crawls (e.g. 5 lakh files)
            await asyncio.sleep(0.15)

        # 100% Indexing Completed -> Auto-clear checkpoint from MongoDB immediately!
        try:
            await mongo.db["indexer_checkpoints"].delete_one({"channel_id": chat_id})
        except Exception:
            pass

        # Final completion report
        await progress_msg.edit_text(
            f"🎉 **Indexing Completed Successfully!**\n\n"
            f"📁 **Channel:** `{chat_info.title}`\n"
            f"🔢 **Total Scanned:** `{total_scanned}` messages\n"
            f"💾 **New Files Indexed:** `{saved_count}`\n"
            f"⏩ **Duplicates Skipped:** `{duplicate_count}`\n"
            f"⚠️ **Errors:** `{error_count}`\n\n"
            f"✨ All files are now searchable in groups and PM!"
        )

    except FloodWait as fw:
        await asyncio.sleep(fw.value)
    except Exception as e:
        logger.error(f"Error during indexing of {chat_id}: {e}")
        await progress_msg.edit_text(
            f"❌ **Indexing Interrupted due to error:** `{e}`\n\n"
            f"💡 <i>Your progress bookmark has been safely saved! You can resume anytime using:</i> <code>/index resume</code>"
        )
    finally:
        ACTIVE_INDEXES.discard(chat_id)


# 5. View/Clear Saved Checkpoints: /checkpoints
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
    for it in items:
        out += (
            f"📁 <b>{it.get('channel_title', 'Channel')}</b> (<code>{it.get('channel_id')}</code>)\n"
            f"  • Progress: Msg <code>#{it.get('last_scanned_id')}</code> / <code>#{it.get('end_id')}</code>\n"
            f"  • Indexed so far: <code>{it.get('saved_count', 0)}</code> files\n\n"
        )
    out += "<i>To continue crawling:</i> <code>/index resume</code>\n<i>To clear checkpoints:</i> <code>/checkpoints clear</code>"
    await message.reply_text(out)
