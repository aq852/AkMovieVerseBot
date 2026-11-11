import os
import io
import asyncio
import zipfile
import datetime
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message
from bson import json_util

from config import Config
from database.mongo import mongo
from utils.helpers import get_readable_size

logger = logging.getLogger(__name__)

BACKUP_COLLECTIONS = [
    "users",
    "chats",
    "verifications",
    "manual_filters",
    "multi_shorteners",
    "movie_requests",
    "share_links",
    "batches",
    "poster_settings",
    "downloader_stats",
    "bot_settings",
    "channel_posts",
    "search_demand",
    "upload_alerts",
    "storage_channels"
]

async def generate_and_send_backup(client: Client, chat_id: int, reason: str = "Manual Backup", include_files: bool = False) -> tuple[bool, str]:
    """Generate compressed JSON backup of MongoDB collections and dispatch to chat_id and LOG_CHANNEL.
    By default, backs up users, VIPs, channels, and configs instantly without loading millions of file docs into RAM.
    If include_files=True, streams indexed files with O(1) memory safely.
    """
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"autofilterbot_backup_{timestamp}.zip"
    temp_dir = os.path.join(os.getcwd(), "temp_backup")
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, zip_filename)

    try:
        total_docs = 0
        stats_lines = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Backup all administrative & user data collections (Fast & Lightweight)
            for coll_name in BACKUP_COLLECTIONS:
                try:
                    coll = mongo.db[coll_name]
                    cursor = coll.find({})
                    docs = await cursor.to_list(length=50000)
                    count = len(docs)
                    total_docs += count
                    stats_lines.append(f"• <code>{coll_name}</code>: <b>{count}</b> records")

                    json_data = json_util.dumps(docs, indent=2)
                    zf.writestr(f"{coll_name}.json", json_data)
                except Exception as coll_err:
                    logger.error(f"Error backing up collection {coll_name}: {coll_err}")
                    stats_lines.append(f"• <code>{coll_name}</code>: ⚠️ Error ({coll_err})")

            # 2. If files requested, stream them with minimal RAM to avoid OOM
            if include_files:
                file_targets = [(mongo.files, f"{Config.COLLECTION_NAME}.json")]
                if mongo.has_secondary:
                    file_targets.append((mongo.files_secondary, f"{Config.COLLECTION_NAME}_secondary.json"))

                for f_coll, f_fname in file_targets:
                    try:
                        f_count = await f_coll.count_documents({})
                        total_docs += f_count
                        stats_lines.append(f"• <code>{f_fname}</code>: <b>{f_count:,}</b> records")
                        with zf.open(f_fname, "w") as f_out:
                            f_out.write(b"[\n")
                            first = True
                            async for doc in f_coll.find({}):
                                if not first:
                                    f_out.write(b",\n")
                                f_out.write(json_util.dumps(doc).encode("utf-8"))
                                first = False
                            f_out.write(b"\n]")
                    except Exception as f_err:
                        logger.error(f"Error backing up files {f_fname}: {f_err}")
                        stats_lines.append(f"• <code>{f_fname}</code>: ⚠️ Error ({f_err})")

        zip_size = os.path.getsize(zip_path)
        readable_size = get_readable_size(zip_size)

        summary_caption = (
            f"📦 <b>AkMovieVerse Database Backup</b>\n\n"
            f"🛡️ <b>Trigger Reason:</b> <code>{reason}</code>\n"
            f"📅 <b>Timestamp (UTC):</b> <code>{timestamp}</code>\n"
            f"📊 <b>Total Collections:</b> <code>{len(BACKUP_COLLECTIONS)}</code>\n"
            f"📄 <b>Total Documents:</b> <code>{total_docs:,}</code>\n"
            f"💾 <b>Archive Size:</b> <code>{readable_size}</code>\n\n"
            f"<b>Collection Breakdown:</b>\n" + "\n".join(stats_lines[:15]) +
            f"\n\n<i>To restore: Reply to this zip with:</i> <code>/restore</code>"
        )

        # Send to target chat
        if chat_id:
            try:
                await client.send_document(
                    chat_id=chat_id,
                    document=zip_path,
                    file_name=zip_filename,
                    caption=summary_caption
                )
            except Exception as e:
                logger.warning(f"Could not deliver backup to chat {chat_id}: {e}")

        # Send copy to LOG_CHANNEL
        if Config.LOG_CHANNEL and Config.LOG_CHANNEL != chat_id:
            try:
                await client.send_document(
                    chat_id=Config.LOG_CHANNEL,
                    document=zip_path,
                    file_name=zip_filename,
                    caption=f"🛡️ <b>System Automated Log Backup</b>\n\n{summary_caption}"
                )
            except Exception as log_err:
                logger.warning(f"Could not deliver backup to LOG_CHANNEL: {log_err}")

        return True, readable_size
    except Exception as e:
        logger.error(f"Failed to generate database backup: {e}", exc_info=True)
        return False, str(e)
    finally:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass


@Client.on_message(filters.command(["backup", "dbbackup"]) & filters.private)
async def backup_database(client: Client, message: Message):
    """Admin command: Dump MongoDB collections to a compressed ZIP and send to Admin & Log Channel.
    Usage:
    - /backup : Instant backup of all users, chats, channels, VIPs & configs (< 1 sec)
    - /backup all : Streamed backup including all media files
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Only bot administrators can execute database backups.")

    args = message.text.split()
    include_files = len(args) > 1 and args[1].lower() in ["files", "all", "full"]
    mode_text = "including all media files (streamed)" if include_files else "users, chats, VIPs, channels & configs"

    status_msg = await message.reply_text(f"⏳ <b>Generating Database Backup...</b>\n<i>Exporting {mode_text}...</i>")
    success, result_str = await generate_and_send_backup(
        client, message.chat.id, reason=f"Manual Admin Request ({message.text})", include_files=include_files
    )
    if success:
        await status_msg.delete()
    else:
        await status_msg.edit_text(f"❌ <b>Backup Failed</b>: <code>{result_str}</code>")


@Client.on_message(filters.command(["restore", "dbrestore"]) & filters.private)
async def restore_database(client: Client, message: Message):
    """Admin command: Reply to a backup ZIP document to restore collections to MongoDB via upsert."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Only bot administrators can restore database backups.")

    reply = message.reply_to_message
    if not reply or not reply.document:
        return await message.reply_text("ℹ️ <b>Usage</b>: Reply to an <code>autofilterbot_backup_*.zip</code> document with <code>/restore</code>.")

    if not reply.document.file_name.endswith(".zip"):
        return await message.reply_text("⚠️ <b>Invalid File</b>: The replied document must be a <code>.zip</code> backup archive.")

    status_msg = await message.reply_text("⏳ <b>Downloading &amp; Inspecting Backup Archive...</b>")
    temp_dir = os.path.join(os.getcwd(), "temp_restore")
    os.makedirs(temp_dir, exist_ok=True)
    temp_zip = os.path.join(temp_dir, reply.document.file_name)

    try:
        await reply.download(file_name=temp_zip)
        await status_msg.edit_text("⏳ <b>Extracting and restoring records to MongoDB...</b>\n<i>Using idempotent upserts to prevent duplicate errors...</i>")

        restored_stats = []
        total_restored = 0

        with zipfile.ZipFile(temp_zip, "r") as zf:
            namelist = zf.namelist()
            for name in namelist:
                if not name.endswith(".json"):
                    continue
                coll_name = name[:-5] # remove .json
                raw_json = zf.read(name).decode("utf-8")
                docs = json_util.loads(raw_json)

                if not isinstance(docs, list):
                    continue

                coll = mongo.db[coll_name]
                coll_count = 0

                # Batch upsert documents using _id
                for doc in docs:
                    doc_id = doc.get("_id")
                    if doc_id:
                        await coll.update_one({"_id": doc_id}, {"$set": doc}, upsert=True)
                        coll_count += 1

                total_restored += coll_count
                restored_stats.append(f"• <code>{coll_name}</code>: <b>{coll_count}</b> upserted")

        await status_msg.edit_text(
            f"✅ <b>Database Restoration Successful!</b>\n\n"
            f"📊 <b>Collections Restored</b>: <code>{len(restored_stats)}</code>\n"
            f"📄 <b>Total Documents Processed</b>: <code>{total_restored:,}</code>\n\n"
            f"<b>Details:</b>\n" + "\n".join(restored_stats)
        )

    except Exception as e:
        logger.error(f"Error restoring backup: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Restoration Failed</b>: <code>{e}</code>")
    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass


@Client.on_message(filters.command(["clonechannel"]) & filters.private)
async def clone_channel_files(client: Client, message: Message):
    """Admin command: /clonechannel <source_channel_id> <target_channel_id> [limit]
    Copies messages from source storage channel to a backup channel and updates/links them.
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>.")

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text(
            "ℹ️ <b>Channel Cloner Usage</b>:\n"
            "<code>/clonechannel &lt;source_channel_id&gt; &lt;target_channel_id&gt; [limit]</code>\n\n"
            "Example:\n"
            "<code>/clonechannel -1002001671856 -1009876543210 500</code>\n\n"
            "⚠️ Both channels must have the bot added as an administrator with posting rights."
        )

    try:
        source_id = int(args[1])
        target_id = int(args[2])
        limit = int(args[3]) if len(args) > 3 else 100
    except ValueError:
        return await message.reply_text("❌ Channel IDs and limit must be valid integers.")

    status_msg = await message.reply_text(f"⏳ <b>Starting channel clone from <code>{source_id}</code> to <code>{target_id}</code> (Limit: {limit})...</b>")

    copied_count = 0
    failed_count = 0

    try:
        # Fetch file records from source_id
        cursor = mongo.files.find({"channel_id": source_id}).limit(limit)
        async for doc in cursor:
            msg_id = doc.get("message_id")
            if not msg_id:
                continue
            try:
                await client.copy_message(
                    chat_id=target_id,
                    from_chat_id=source_id,
                    message_id=msg_id
                )
                copied_count += 1
            except Exception as copy_err:
                failed_count += 1
                logger.debug(f"Failed to clone msg {msg_id}: {copy_err}")

        await status_msg.edit_text(
            f"✅ <b>Channel Cloning Complete!</b>\n\n"
            f"📤 <b>Source Channel</b>: <code>{source_id}</code>\n"
            f"📥 <b>Target Channel</b>: <code>{target_id}</code>\n"
            f"✔️ <b>Successfully Copied</b>: <code>{copied_count}</code>\n"
            f"⚠️ <b>Failed / Skipped</b>: <code>{failed_count}</code>"
        )
    except Exception as e:
        logger.error(f"Clone channel error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Cloning Failed</b>: <code>{e}</code>")


# ==============================================================================
# Automated Weekly Sunday Backup Scheduler
# ==============================================================================

async def start_weekly_backup_scheduler(client: Client):
    """Background task: Automatically dispatches a full DB backup zip every Sunday night at 23:00 IST."""
    await asyncio.sleep(45)  # Wait for bot startup to settle
    logger.info("Weekly Auto-Backup background scheduler started.")

    while True:
        try:
            from database.mongo import get_bot_setting, set_bot_setting
            enabled = await get_bot_setting("auto_backup_enabled", True)
            if not enabled:
                await asyncio.sleep(300)
                continue

            now_utc = datetime.datetime.utcnow()
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            today_str = now_ist.strftime("%Y-%m-%d")

            # Check if today is Sunday (weekday == 6) and time is 23:00 IST
            if now_ist.weekday() == 6 and now_ist.hour == 23 and now_ist.minute >= 0:
                last_backup_date = await get_bot_setting("last_auto_backup_date", "None")
                if last_backup_date != today_str:
                    logger.info("Executing scheduled weekly Sunday database backup...")
                    await set_bot_setting("last_auto_backup_date", today_str)

                    timestamp = now_utc.strftime("%Y%m%d_%H%M%S")
                    zip_filename = f"weekly_autobackup_{timestamp}.zip"
                    temp_dir = os.path.join(os.getcwd(), "temp_backup")
                    os.makedirs(temp_dir, exist_ok=True)
                    zip_path = os.path.join(temp_dir, zip_filename)

                    total_docs = 0
                    stats_lines = []

                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for coll_name in BACKUP_COLLECTIONS:
                            try:
                                coll = mongo.db[coll_name]
                                docs = await coll.find({}).to_list(length=None)
                                count = len(docs)
                                total_docs += count
                                stats_lines.append(f"• <code>{coll_name}</code>: <b>{count}</b>")
                                zf.writestr(f"{coll_name}.json", json_util.dumps(docs, indent=2))
                            except Exception as c_err:
                                stats_lines.append(f"• <code>{coll_name}</code>: ⚠️ {c_err}")

                    readable_size = get_readable_size(os.path.getsize(zip_path))
                    caption = (
                        f"🛡️ <b>Automated Sunday Database Backup</b>\n\n"
                        f"📅 <b>Date:</b> <code>{today_str}</code> (23:00 IST)\n"
                        f"📄 <b>Total Documents:</b> <code>{total_docs:,}</code>\n"
                        f"💾 <b>Archive Size:</b> <code>{readable_size}</code>\n\n"
                        "<i>Weekly disaster-recovery backup safely archived in Telegram.</i>"
                    )

                    targets = []
                    if Config.LOG_CHANNEL:
                        targets.append(Config.LOG_CHANNEL)
                    for a in Config.ADMINS:
                        if a not in targets:
                            targets.append(a)

                    for target in targets:
                        try:
                            await client.send_document(
                                chat_id=target,
                                document=zip_path,
                                file_name=zip_filename,
                                caption=caption
                            )
                        except Exception as send_err:
                            logger.debug(f"Could not send weekly backup to {target}: {send_err}")

                    try:
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                    except Exception:
                        pass

            await asyncio.sleep(60)

        except Exception as loop_e:
            logger.error(f"Error in weekly backup scheduler: {loop_e}", exc_info=True)
            await asyncio.sleep(120)


@Client.on_message(filters.command(["autobackup", "setautobackup"]) & filters.private)
async def toggle_auto_backup_command(client: Client, message: Message):
    """Admin command: /autobackup [on|off] - Toggle automated Sunday database backup."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    from database.mongo import get_bot_setting, set_bot_setting
    args = message.text.split()
    if len(args) > 1:
        arg = args[1].lower()
        if arg == "on":
            await set_bot_setting("auto_backup_enabled", True)
            return await message.reply_text("✅ <b>Automated Weekly Backup Enabled!</b>\nA full DB backup will be dispatched every Sunday at 23:00 IST.")
        elif arg == "off":
            await set_bot_setting("auto_backup_enabled", False)
            return await message.reply_text("⏸️ <b>Automated Weekly Backup Disabled.</b>")

    enabled = await get_bot_setting("auto_backup_enabled", True)
    last_sent = await get_bot_setting("last_auto_backup_date", "None")
    status_str = "🟢 <b>ENABLED</b>" if enabled else "🔴 <b>DISABLED</b>"

    await message.reply_text(
        f"🛡️ <b>Automated Weekly Backup Status</b>\n\n"
        f"• <b>Status:</b> {status_str}\n"
        f"• <b>Schedule:</b> Every Sunday at 23:00 IST (11:00 PM)\n"
        f"• <b>Last Backup Date:</b> <code>{last_sent}</code>\n"
        f"• <b>Destination:</b> Log Channel &amp; Admin PMs\n\n"
        "<b>Commands:</b>\n"
        "• <code>/autobackup on</code> — Enable weekly backups\n"
        "• <code>/autobackup off</code> — Disable weekly backups\n"
        "• <code>/backup</code> — Trigger manual backup immediately"
    )
