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
    Config.COLLECTION_NAME,  # e.g. telegram_files
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
    "upload_alerts"
]

@Client.on_message(filters.command(["backup", "dbbackup"]) & filters.private)
async def backup_database(client: Client, message: Message):
    """Admin command: Dump MongoDB collections to a compressed ZIP and send to Admin & Log Channel."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**: Only bot administrators can execute database backups.")

    status_msg = await message.reply_text("⏳ **Generating Database Backup...**\n_Reading MongoDB collections and serializing documents..._")
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"autofilterbot_backup_{timestamp}.zip"
    temp_dir = os.path.join(os.getcwd(), "temp_backup")
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, zip_filename)

    try:
        total_docs = 0
        stats_lines = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for coll_name in BACKUP_COLLECTIONS:
                try:
                    coll = mongo.db[coll_name]
                    cursor = coll.find({})
                    docs = await cursor.to_list(length=None)
                    count = len(docs)
                    total_docs += count
                    stats_lines.append(f"• `{coll_name}`: **{count}** records")

                    json_data = json_util.dumps(docs, indent=2)
                    zf.writestr(f"{coll_name}.json", json_data)
                except Exception as coll_err:
                    logger.error(f"Error backing up collection {coll_name}: {coll_err}")
                    stats_lines.append(f"• `{coll_name}`: ⚠️ Error ({coll_err})")

        zip_size = os.path.getsize(zip_path)
        readable_size = get_readable_size(zip_size)

        summary_caption = (
            f"📦 **AkMovieVerse Database Backup**\n\n"
            f"📅 **Timestamp (UTC)**: `{timestamp}`\n"
            f"📊 **Total Collections**: `{len(BACKUP_COLLECTIONS)}`\n"
            f"📄 **Total Documents**: `{total_docs:,}`\n"
            f"💾 **Archive Size**: `{readable_size}`\n\n"
            f"__Collection Breakdown:__\n" + "\n".join(stats_lines[:15]) +
            f"\n\n_To restore: Reply to this zip with /restore_"
        )

        # Send to Admin Private Chat
        await client.send_document(
            chat_id=message.chat.id,
            document=zip_path,
            file_name=zip_filename,
            caption=summary_caption
        )

        # Send copy to LOG_CHANNEL for safe off-site persistence
        if Config.LOG_CHANNEL:
            try:
                await client.send_document(
                    chat_id=Config.LOG_CHANNEL,
                    document=zip_path,
                    file_name=zip_filename,
                    caption=f"🛡️ **System Automated Log Backup**\n{summary_caption}"
                )
            except Exception as log_err:
                logger.warning(f"Could not deliver backup to LOG_CHANNEL: {log_err}")

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Failed to generate database backup: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Backup Failed**: `{e}`")
    finally:
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass


@Client.on_message(filters.command(["restore", "dbrestore"]) & filters.private)
async def restore_database(client: Client, message: Message):
    """Admin command: Reply to a backup ZIP document to restore collections to MongoDB via upsert."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**: Only bot administrators can restore database backups.")

    reply = message.reply_to_message
    if not reply or not reply.document:
        return await message.reply_text("ℹ️ **Usage**: Reply to an `autofilterbot_backup_*.zip` document with `/restore`.")

    if not reply.document.file_name.endswith(".zip"):
        return await message.reply_text("⚠️ **Invalid File**: The replied document must be a `.zip` backup archive.")

    status_msg = await message.reply_text("⏳ **Downloading & Inspecting Backup Archive...**")
    temp_dir = os.path.join(os.getcwd(), "temp_restore")
    os.makedirs(temp_dir, exist_ok=True)
    temp_zip = os.path.join(temp_dir, reply.document.file_name)

    try:
        await reply.download(file_name=temp_zip)
        await status_msg.edit_text("⏳ **Extracting and restoring records to MongoDB...**\n_Using idempotent upserts to prevent duplicate errors..._")

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
                restored_stats.append(f"• `{coll_name}`: **{coll_count}** upserted")

        await status_msg.edit_text(
            f"✅ **Database Restoration Successful!**\n\n"
            f"📊 **Collections Restored**: `{len(restored_stats)}`\n"
            f"📄 **Total Documents Processed**: `{total_restored:,}`\n\n"
            f"__Details:__\n" + "\n".join(restored_stats)
        )

    except Exception as e:
        logger.error(f"Error restoring backup: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Restoration Failed**: `{e}`")
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
        return await message.reply_text("⛔ **Access Denied**.")

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text(
            "ℹ️ **Channel Cloner Usage**:\n"
            "`/clonechannel <source_channel_id> <target_channel_id> [limit]`\n\n"
            "Example:\n"
            "`/clonechannel -1002001671856 -1009876543210 500`\n\n"
            "⚠️ Both channels must have the bot added as an administrator with posting rights."
        )

    try:
        source_id = int(args[1])
        target_id = int(args[2])
        limit = int(args[3]) if len(args) > 3 else 100
    except ValueError:
        return await message.reply_text("❌ Channel IDs and limit must be valid integers.")

    status_msg = await message.reply_text(f"⏳ **Starting channel clone from `{source_id}` to `{target_id}` (Limit: {limit})...**")

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
            f"✅ **Channel Cloning Complete!**\n\n"
            f"📤 **Source Channel**: `{source_id}`\n"
            f"📥 **Target Channel**: `{target_id}`\n"
            f"✔️ **Successfully Copied**: `{copied_count}`\n"
            f"⚠️ **Failed / Skipped**: `{failed_count}`"
        )
    except Exception as e:
        logger.error(f"Clone channel error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Cloning Failed**: `{e}`")


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
                                stats_lines.append(f"• `{coll_name}`: **{count}**")
                                zf.writestr(f"{coll_name}.json", json_util.dumps(docs, indent=2))
                            except Exception as c_err:
                                stats_lines.append(f"• `{coll_name}`: ⚠️ {c_err}")

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
        return await message.reply_text("⛔ **Access Denied**: Admin privileges required.")

    from database.mongo import get_bot_setting, set_bot_setting
    args = message.text.split()
    if len(args) > 1:
        arg = args[1].lower()
        if arg == "on":
            await set_bot_setting("auto_backup_enabled", True)
            return await message.reply_text("✅ **Automated Weekly Backup Enabled!**\nA full DB backup will be dispatched every Sunday at 23:00 IST.")
        elif arg == "off":
            await set_bot_setting("auto_backup_enabled", False)
            return await message.reply_text("⏸️ **Automated Weekly Backup Disabled.**")

    enabled = await get_bot_setting("auto_backup_enabled", True)
    last_sent = await get_bot_setting("last_auto_backup_date", "None")
    status_str = "🟢 **ENABLED**" if enabled else "🔴 **DISABLED**"

    await message.reply_text(
        f"🛡️ **Automated Weekly Backup Status**\n\n"
        f"• **Status:** {status_str}\n"
        f"• **Schedule:** Every Sunday at 23:00 IST (11:00 PM)\n"
        f"• **Last Backup Date:** `{last_sent}`\n"
        f"• **Destination:** Log Channel & Admin PMs\n\n"
        "**Commands:**\n"
        "• `/autobackup on` — Enable weekly backups\n"
        "• `/autobackup off` — Disable weekly backups\n"
        "• `/backup` — Trigger manual backup immediately"
    )
