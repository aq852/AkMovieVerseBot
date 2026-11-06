import asyncio
import datetime
import logging

try:
    from hydrogram import Client, filters, enums
    from hydrogram.types import Message
    from hydrogram.errors import (
        FloodWait,
        ChannelPrivate,
        PeerIdInvalid,
        UserNotParticipant
    )
except ImportError:
    from pyrogram import Client, filters, enums
    from pyrogram.types import Message
    from pyrogram.errors import (
        FloodWait,
        ChannelPrivate,
        PeerIdInvalid,
        UserNotParticipant
    )

from config import Config
from database.mongo import mongo, get_bot_setting, set_bot_setting
from database.chats import get_all_chat_ids, delete_chat

logger = logging.getLogger(__name__)


async def run_database_housekeeping(client: Client = None, triggered_by: str = "Manual Admin Request") -> dict:
    """Execute full database housekeeping:
    1. Safely checks and prunes dead/inaccessible group chats (where bot was kicked or group deleted).
    2. Purges expired batches (where expire_at < now or downloads_count >= max_downloads).
    3. Purges expired secret share links (where expire_at < now or downloads_count >= max_downloads).
    4. Purges expired verification tokens.
    5. Purges completed / stopped indexer checkpoints older than 14 days.
    6. Purges resolved/rejected movie requests older than 30 days.
    7. Purges notified upload alerts or alerts older than 45 days.

    CRITICAL SAFETY INVARIANTS:
    - User records in `mongo.users` are 100% UNTOUCHED (safe).
    - Channel post mappings in `channel_posts` are 100% UNTOUCHED (safe).
    - TMDB metadata cache in `tmdb_post_cache` is 100% UNTOUCHED (safe).
    """
    now = datetime.datetime.utcnow()
    stats = {
        "dead_chats": 0,
        "scanned_chats": 0,
        "expired_batches": 0,
        "expired_share_links": 0,
        "expired_verifications": 0,
        "stale_checkpoints": 0,
        "resolved_requests": 0,
        "notified_alerts": 0,
        "expired_ads": 0,
        "expired_gifts": 0,
        "total_purged": 0,
        "duration_seconds": 0.0,
        "triggered_by": triggered_by
    }
    t0 = datetime.datetime.utcnow()

    # 1. Dead Groups Cleanup (Only if Pyrogram Client is available)
    if client:
        try:
            chat_ids = await get_all_chat_ids()
            stats["scanned_chats"] = len(chat_ids)
            for cid in chat_ids:
                try:
                    await client.get_chat(cid)
                    await asyncio.sleep(0.08)  # Gentle rate limit protection
                except (ChannelPrivate, PeerIdInvalid, UserNotParticipant):
                    # Bot was kicked or group deleted / made private without bot
                    if await delete_chat(cid):
                        stats["dead_chats"] += 1
                except FloodWait as fw:
                    logger.warning(f"FloodWait {fw.value}s during dead chats cleanup; sleeping...")
                    await asyncio.sleep(fw.value)
                except Exception as chat_err:
                    # Other non-fatal errors (e.g. timeout) - preserve chat safely
                    logger.debug(f"Chat check exception for {cid}: {chat_err}")
        except Exception as e:
            logger.error(f"Error checking dead groups: {e}")

    # 2. Expired Batches (expired or downloads limit reached)
    try:
        res_b = await mongo.batches.delete_many({
            "$or": [
                {"expire_at": {"$ne": None, "$lte": now}},
                {
                    "$and": [
                        {"max_downloads": {"$ne": None, "$gt": 0}},
                        {"$expr": {"$gte": ["$downloads_count", "$max_downloads"]}}
                    ]
                }
            ]
        })
        stats["expired_batches"] = res_b.deleted_count
    except Exception as e:
        logger.error(f"Error purging expired batches: {e}")

    # 3. Expired Secret Share Links
    try:
        res_sl = await mongo.share_links.delete_many({
            "$or": [
                {"expire_at": {"$ne": None, "$lte": now}},
                {
                    "$and": [
                        {"max_downloads": {"$ne": None, "$gt": 0}},
                        {"$expr": {"$gte": ["$downloads_count", "$max_downloads"]}}
                    ]
                }
            ]
        })
        stats["expired_share_links"] = res_sl.deleted_count
    except Exception as e:
        logger.error(f"Error purging expired share links: {e}")

    # 4. Expired Verifications
    try:
        res_v = await mongo.verify.delete_many({"expires_at": {"$lte": now}})
        stats["expired_verifications"] = res_v.deleted_count
    except Exception as e:
        logger.error(f"Error purging expired verifications: {e}")

    # 5. Stale / Completed Indexer Checkpoints (older than 14 days)
    try:
        cutoff_14d = now - datetime.timedelta(days=14)
        res_chk = await mongo.db["indexer_checkpoints"].delete_many({
            "status": {"$in": ["completed", "stopped"]},
            "updated_at": {"$lte": cutoff_14d}
        })
        stats["stale_checkpoints"] = res_chk.deleted_count
    except Exception as e:
        logger.error(f"Error purging indexer checkpoints: {e}")

    # 6. Resolved / Rejected Movie Requests (older than 30 days)
    try:
        cutoff_30d = now - datetime.timedelta(days=30)
        res_req = await mongo.requests.delete_many({
            "status": {"$in": ["uploaded", "rejected"]},
            "updated_at": {"$lte": cutoff_30d}
        })
        stats["resolved_requests"] = res_req.deleted_count
    except Exception as e:
        logger.error(f"Error purging resolved movie requests: {e}")

    # 7. Notified Upload Alerts (already delivered or older than 45 days)
    try:
        cutoff_45d = now - datetime.timedelta(days=45)
        res_ua = await mongo.db["upload_alerts"].delete_many({
            "$or": [
                {"status": "notified"},
                {"created_at": {"$lte": cutoff_45d}}
            ]
        })
        stats["notified_alerts"] = res_ua.deleted_count
    except Exception as e:
        logger.error(f"Error purging upload alerts: {e}")

    # 8. Expired Inactive Sponsor Ads (older than 7 days)
    try:
        from database.ads import clean_expired_ads
        purged_ads = await clean_expired_ads(keep_days=7)
        stats["expired_ads"] = purged_ads
    except Exception as e:
        logger.error(f"Error purging expired ads in housekeeping: {e}")

    # 9. Expired Gift Tokens & Stale Inactive Gifts (older than 14 days)
    try:
        from database.gifts import clean_expired_gifts
        purged_gifts = await clean_expired_gifts(keep_days=14)
        stats["expired_gifts"] = purged_gifts
    except Exception as e:
        logger.error(f"Error purging expired gifts in housekeeping: {e}")

    stats["total_purged"] = (
        stats["dead_chats"] + stats["expired_batches"] +
        stats["expired_share_links"] + stats["expired_verifications"] +
        stats["stale_checkpoints"] + stats["resolved_requests"] +
        stats["notified_alerts"] + stats["expired_ads"] + stats["expired_gifts"]
    )
    stats["duration_seconds"] = round((datetime.datetime.utcnow() - t0).total_seconds(), 2)

    logger.info(f"Database housekeeping finished: {stats}")
    return stats


def format_housekeeping_report(stats: dict) -> str:
    """Format housekeeping statistics into a clean, human-readable HTML report."""
    return (
        "🛡️ <b>Database Housekeeping &amp; Cleanup Report</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Triggered By:</b> <code>{stats.get('triggered_by', 'System')}</code>\n"
        f"⏱️ <b>Duration:</b> <code>{stats.get('duration_seconds', 0)}s</code>\n\n"
        "<b>Purged Stale Items Summary:</b>\n"
        f"• <b>Dead Groups (Kicked/Deleted):</b> <code>{stats.get('dead_chats', 0):,}</code> (Scanned: {stats.get('scanned_chats', 0):,})\n"
        f"• <b>Expired Batches:</b> <code>{stats.get('expired_batches', 0):,}</code>\n"
        f"• <b>Expired Share Links:</b> <code>{stats.get('expired_share_links', 0):,}</code>\n"
        f"• <b>Expired Verifications:</b> <code>{stats.get('expired_verifications', 0):,}</code>\n"
        f"• <b>Stale Checkpoints (14d+):</b> <code>{stats.get('stale_checkpoints', 0):,}</code>\n"
        f"• <b>Resolved Requests (30d+):</b> <code>{stats.get('resolved_requests', 0):,}</code>\n"
        f"• <b>Notified Upload Alerts:</b> <code>{stats.get('notified_alerts', 0):,}</code>\n"
        f"• <b>Expired Sponsor Ads (7d+):</b> <code>{stats.get('expired_ads', 0):,}</code>\n"
        f"• <b>Expired Gift Drops (14d+):</b> <code>{stats.get('expired_gifts', 0):,}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧹 <b>Total Junk Records Cleared:</b> <code>{stats.get('total_purged', 0):,}</code>\n"
        "✨ <i>All Users, Channel Auto-Posts &amp; TMDB Cache were 100% preserved!</i>"
    )


async def start_weekly_housekeeping_scheduler(client: Client):
    """Background task: Automatically executes database housekeeping every Sunday night at 23:20 IST."""
    await asyncio.sleep(60)  # Wait for startup to settle
    logger.info("Weekly Database Housekeeping scheduler started.")

    while True:
        try:
            enabled = await get_bot_setting("auto_clean_enabled", True)
            if not enabled:
                await asyncio.sleep(300)
                continue

            now_utc = datetime.datetime.utcnow()
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            today_str = now_ist.strftime("%Y-%m-%d")

            # Check if today is Sunday (weekday == 6) and time is 23:20 IST
            if now_ist.weekday() == 6 and now_ist.hour == 23 and now_ist.minute >= 20:
                last_clean_date = await get_bot_setting("last_auto_clean_date", "None")
                if last_clean_date != today_str:
                    logger.info("Executing scheduled weekly Sunday database housekeeping...")
                    await set_bot_setting("last_auto_clean_date", today_str)

                    stats = await run_database_housekeeping(client=client, triggered_by="Weekly Sunday Scheduler")
                    report = format_housekeeping_report(stats)

                    # Dispatch report to LOG_CHANNEL and ADMINS
                    targets = []
                    if Config.LOG_CHANNEL:
                        targets.append(Config.LOG_CHANNEL)
                    for a in Config.ADMINS:
                        if a not in targets:
                            targets.append(a)

                    for target in targets:
                        try:
                            await client.send_message(chat_id=target, text=report, parse_mode=enums.ParseMode.HTML)
                        except Exception as send_err:
                            logger.debug(f"Could not send weekly clean report to {target}: {send_err}")

            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as loop_e:
            logger.error(f"Error in weekly housekeeping scheduler: {loop_e}", exc_info=True)
            await asyncio.sleep(120)


@Client.on_message(filters.command(["autoclean", "housekeeping", "cleanhouse"]) & filters.private)
async def auto_clean_command(client: Client, message: Message):
    """Admin command: Run on-demand database housekeeping or toggle weekly auto-clean."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split()[1:]
    if args:
        sub = args[0].lower()
        if sub == "on":
            await set_bot_setting("auto_clean_enabled", True)
            return await message.reply_text("✅ <b>Weekly Auto-Clean Enabled!</b> Runs automatically every Sunday at 23:20 IST.")
        elif sub == "off":
            await set_bot_setting("auto_clean_enabled", False)
            return await message.reply_text("⏸️ <b>Weekly Auto-Clean Disabled!</b> (You can still run it manually with <code>/autoclean</code>).")
        elif sub == "status":
            enabled = await get_bot_setting("auto_clean_enabled", True)
            last_run = await get_bot_setting("last_auto_clean_date", "Never")
            status_icon = "🟢 Active" if enabled else "🔴 Disabled"
            return await message.reply_text(
                f"⚙️ <b>Weekly Database Auto-Clean Status:</b>\n\n"
                f"• <b>Status:</b> {status_icon}\n"
                f"• <b>Schedule:</b> Every Sunday at 23:20 IST\n"
                f"• <b>Last Run:</b> <code>{last_run}</code>\n\n"
                f"<i>Toggle:</i> <code>/autoclean on</code> or <code>/autoclean off</code>"
            )

    status_msg = await message.reply_text(
        "🧹 <b>Executing Database Housekeeping...</b>\n"
        "<i>Checking dead groups, expired batches, secret share links, and old checkpoints...</i>"
    )

    stats = await run_database_housekeeping(client=client, triggered_by=f"Admin {message.from_user.id}")
    report = format_housekeeping_report(stats)

    await status_msg.edit_text(report)
