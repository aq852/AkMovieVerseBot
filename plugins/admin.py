import time
import re
import datetime
import asyncio
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from hydrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, UserDeactivated, PeerIdInvalid
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, UserDeactivated, PeerIdInvalid

from config import Config
from database.mongo import mongo
from database.files import get_total_files_count, delete_camrip_files, delete_file_by_id, delete_all_files, purge_files_and_caches, purge_factory_reset
from database.users import get_total_users_count, get_all_user_ids, set_ban_status, add_premium, remove_premium, get_all_premium_users
from database.chats import get_total_chats_count, get_all_chat_ids

logger = logging.getLogger(__name__)

# 1. /stats Command (Pro Command Dashboard)
@Client.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    """Display comprehensive real-time system metrics, database health, user growth, and hardware stats."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    status_msg = await message.reply_text("⏳ <b>Compiling real-time system metrics...</b>")
    t0 = time.time()

    now = datetime.datetime.utcnow()
    last_24h = now - datetime.timedelta(hours=24)

    tasks = [
        mongo.files.count_documents({}),
        mongo.files.count_documents({"created_at": {"$gte": last_24h}}),
        mongo.users.count_documents({}),
        mongo.users.count_documents({"joined_at": {"$gte": last_24h}}),
        mongo.users.count_documents({"is_premium": True}),
        mongo.chats.count_documents({}),
        mongo.db["upload_alerts"].count_documents({"status": "pending"}),
        mongo.db["search_demand"].find_one({}, sort=[("count", -1)]),
        mongo.shorteners.count_documents({}),
        mongo.db.command("dbStats")
    ]
    if mongo._client:
        tasks.append(mongo._client.admin.command("listDatabases"))
    if mongo.has_secondary:
        tasks.append(mongo.files_secondary.count_documents({}))
        tasks.append(mongo.db2.command("dbStats"))
        if mongo._client2:
            tasks.append(mongo._client2.admin.command("listDatabases"))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        results = [0] * len(tasks)

    files_count = results[0] if isinstance(results[0], int) else 0
    files_today = results[1] if isinstance(results[1], int) else 0
    users_count = results[2] if isinstance(results[2], int) else 0
    users_today = results[3] if isinstance(results[3], int) else 0
    vip_count = results[4] if isinstance(results[4], int) else 0
    chats_count = results[5] if isinstance(results[5], int) else 0
    pending_alerts = results[6] if isinstance(results[6], int) else 0
    top_demand_doc = results[7] if isinstance(results[7], dict) else None
    shorteners_count = results[8] if isinstance(results[8], int) else 0
    db_stats = results[9] if len(results) > 9 and isinstance(results[9], dict) else {}
    
    idx = 10
    cluster1_info = {}
    if mongo._client and len(results) > idx:
        cluster1_info = results[idx] if isinstance(results[idx], dict) else {}
        idx += 1

    if mongo.has_secondary:
        sec_files = results[idx] if len(results) > idx and isinstance(results[idx], int) else 0
        files_count += sec_files
        idx += 1
        db2_stats = results[idx] if len(results) > idx and isinstance(results[idx], dict) else {}
        idx += 1
        cluster2_info = results[idx] if len(results) > idx and isinstance(results[idx], dict) else {}
        idx += 1
    else:
        db2_stats = {}
        cluster2_info = {}

    from utils.helpers import get_readable_size
    
    # Check if DB1 has writes blocked or is flagged full
    from database.files import is_db1_full, get_active_target_collection
    db1_blocked = is_db1_full()
    
    # Quick probe if not already known blocked
    if not db1_blocked:
        try:
            probe = await mongo.db["_write_probe"].insert_one({"t": time.time()})
            await mongo.db["_write_probe"].delete_one({"_id": probe.inserted_id})
        except Exception as e_probe:
            probe_err = str(e_probe).lower()
            if "quota" in probe_err or "writes are blocked" in probe_err or "code': 8000" in probe_err or "code 8000" in probe_err:
                db1_blocked = True
                import database.files as files_mod
                files_mod._DB1_FULL_STATUS = True

    cluster1_total = cluster1_info.get("totalSize", 0)
    mflix_sz = 0
    for d in cluster1_info.get("databases", []):
        if d.get("name") == "sample_mflix":
            mflix_sz = d.get("sizeOnDisk", 0)

    if db_stats:
        storage_sz = db_stats.get("storageSize", 0)
        index_sz = db_stats.get("indexSize", 0)
        total_mongo_bytes = storage_sz + index_sz
        mongo_used_str = get_readable_size(total_mongo_bytes)
        pct = (total_mongo_bytes / (512 * 1024 * 1024)) * 100
        
        if db1_blocked:
            cluster_str = f" (Cluster: {get_readable_size(cluster1_total)} / 512 MB)" if cluster1_total else ""
            mongo_storage_line = f"• <b>Primary DB (DB1):</b> <code>{mongo_used_str}</code>{cluster_str} ⛔ <b>WRITES BLOCKED!</b> 🔴\n"
            if mflix_sz > 0:
                mongo_storage_line += f"  ⚠️ <i>Atlas Space Quota Exceeded! Unused DB 'sample_mflix' is using {get_readable_size(mflix_sz)}! (Use /cleanupsampledb)</i>\n"
        else:
            mongo_icon = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")
            mongo_storage_line = f"• <b>Primary DB (DB1):</b> <code>{mongo_used_str} / 512 MB ({pct:.1f}%)</code> {mongo_icon}\n"
        
        mongo_details_line = f"• <b>DB1 Objects:</b> <code>{db_stats.get('objects', 0):,} docs ({get_readable_size(index_sz)} index)</code>\n"
    else:
        mongo_storage_line = "• <b>Primary DB (DB1):</b> <code>Online (Atlas Cloud)</code>\n"
        mongo_details_line = ""

    if mongo.has_secondary and db2_stats:
        storage_sz2 = db2_stats.get("storageSize", 0)
        index_sz2 = db2_stats.get("indexSize", 0)
        total_bytes2 = storage_sz2 + index_sz2
        pct2 = (total_bytes2 / (512 * 1024 * 1024)) * 100
        icon2 = "🟢" if pct2 < 70 else ("🟡" if pct2 < 90 else "🔴")
        mongo_storage_line += f"• <b>Secondary DB (DB2):</b> <code>{get_readable_size(total_bytes2)} / 512 MB ({pct2:.1f}%)</code> {icon2}\n"
        mongo_details_line += f"• <b>DB2 Objects:</b> <code>{db2_stats.get('objects', 0):,} docs ({get_readable_size(index_sz2)} index)</code>\n"
        combined_used = (total_mongo_bytes if db_stats else 0) + total_bytes2
        comb_pct = (combined_used / (1024 * 1024 * 1024)) * 100
        mongo_storage_line += f"• <b>Total Dual Storage:</b> <code>{get_readable_size(combined_used)} / 1024 MB ({comb_pct:.1f}%)</code>\n"
        _, target_status = await get_active_target_collection()
        mongo_storage_line += f"• <b>Active Upload Target:</b> <code>{target_status.upper()}</code>\n"
    elif not mongo.has_secondary:
        mongo_storage_line += "• <b>Secondary DB:</b> <code>⚪ Inactive (Single Cluster Mode)</code>\n"

    ping_ms = round((time.time() - t0) * 1000, 1)

    import psutil
    ram = psutil.virtual_memory()
    ram_str = f"{ram.percent}% ({ram.used / (1024**3):.1f} GB / {ram.total / (1024**3):.1f} GB)"
    cpu_percent = psutil.cpu_percent(interval=None)
    disk = psutil.disk_usage('.')
    disk_str = f"{disk.percent}% ({disk.free / (1024**3):.1f} GB Free)"

    start_t = getattr(Config, "START_TIME", time.time())
    elapsed = int(time.time() - start_t)
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    uptime_parts = []
    if days > 0:
        uptime_parts.append(f"{days}d")
    if hours > 0:
        uptime_parts.append(f"{hours}h")
    uptime_parts.append(f"{mins}m {secs}s")
    uptime_str = " ".join(uptime_parts)

    top_demand_str = "None"
    if top_demand_doc:
        top_demand_str = f"{top_demand_doc.get('title', 'N/A')} ({top_demand_doc.get('count', 0)} searches)"

    dashboard_text = (
        "📊 <b>AKMOVIEVERSE • PRO COMMAND DASHBOARD</b> 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>CONTENT & STORAGE METRICS:</b>\n"
        f"• <b>Total Indexed Files:</b> <code>{files_count:,}</code> files\n"
        f"• <b>Added Today (Last 24h):</b> <code>+{files_today:,}</code> files\n"
        f"{mongo_storage_line}"
        f"{mongo_details_line}"
        f"• <b>Host Disk Storage:</b> <code>{disk_str}</code>\n\n"

        "👥 <b>AUDIENCE & MONETIZATION:</b>\n"
        f"• <b>Total Registered Users:</b> <code>{users_count:,}</code> users\n"
        f"• <b>New Users Today:</b> <code>+{users_today:,}</code> joined\n"
        f"• <b>Active VIP Members:</b> <code>{vip_count:,}</code> members 💎\n"
        f"• <b>Connected Groups:</b> <code>{chats_count:,}</code> groups\n"
        f"• <b>Shortener Gateways:</b> <code>{shorteners_count}</code> in rotation (Status: <code>{'ON' if Config.SHORTENER_ENABLED else 'OFF'}</code>)\n\n"

        "🔔 <b>AUDIENCE DEMAND & ALERTS:</b>\n"
        f"• <b>Active 'Notify Me' Alerts:</b> <code>{pending_alerts:,}</code> users waiting\n"
        f"• <b>Top Demanded Movie:</b> <code>{top_demand_str}</code>\n\n"

        "⚡ <b>SERVER HEALTH & ENGINE:</b>\n"
        f"• <b>Bot Uptime:</b> <code>{uptime_str}</code>\n"
        f"• <b>Server RAM:</b> <code>{ram_str}</code>\n"
        f"• <b>CPU Load:</b> <code>{cpu_percent}%</code>\n"
        f"• <b>Ping Latency:</b> <code>{ping_ms} ms</code>\n"
        f"• <b>Core Engine:</b> <code>Hydrogram MTProto • Python 3.11</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_admin_stats"),
            InlineKeyboardButton("📦 Full DB Backup", callback_data="trigger_quick_backup")
        ]
    ])

    await status_msg.edit_text(dashboard_text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^refresh_admin_stats$"))
async def refresh_admin_stats_callback(client: Client, query: CallbackQuery):
    """Live refresh of the admin stats dashboard."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied.", show_alert=True)

    await query.answer("🔄 Refreshing live metrics...")
    t0 = time.time()
    now = datetime.datetime.utcnow()
    last_24h = now - datetime.timedelta(hours=24)

    tasks = [
        mongo.files.count_documents({}),
        mongo.files.count_documents({"created_at": {"$gte": last_24h}}),
        mongo.users.count_documents({}),
        mongo.users.count_documents({"joined_at": {"$gte": last_24h}}),
        mongo.users.count_documents({"is_premium": True}),
        mongo.chats.count_documents({}),
        mongo.db["upload_alerts"].count_documents({"status": "pending"}),
        mongo.db["search_demand"].find_one({}, sort=[("count", -1)]),
        mongo.shorteners.count_documents({}),
        mongo.db.command("dbStats")
    ]
    if mongo._client:
        tasks.append(mongo._client.admin.command("listDatabases"))
    if mongo.has_secondary:
        tasks.append(mongo.files_secondary.count_documents({}))
        tasks.append(mongo.db2.command("dbStats"))
        if mongo._client2:
            tasks.append(mongo._client2.admin.command("listDatabases"))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        results = [0] * len(tasks)

    files_count = results[0] if isinstance(results[0], int) else 0
    files_today = results[1] if isinstance(results[1], int) else 0
    users_count = results[2] if isinstance(results[2], int) else 0
    users_today = results[3] if isinstance(results[3], int) else 0
    vip_count = results[4] if isinstance(results[4], int) else 0
    chats_count = results[5] if isinstance(results[5], int) else 0
    pending_alerts = results[6] if isinstance(results[6], int) else 0
    top_demand_doc = results[7] if isinstance(results[7], dict) else None
    shorteners_count = results[8] if isinstance(results[8], int) else 0
    db_stats = results[9] if len(results) > 9 and isinstance(results[9], dict) else {}
    
    idx = 10
    cluster1_info = {}
    if mongo._client and len(results) > idx:
        cluster1_info = results[idx] if isinstance(results[idx], dict) else {}
        idx += 1

    if mongo.has_secondary:
        sec_files = results[idx] if len(results) > idx and isinstance(results[idx], int) else 0
        files_count += sec_files
        idx += 1
        db2_stats = results[idx] if len(results) > idx and isinstance(results[idx], dict) else {}
        idx += 1
        cluster2_info = results[idx] if len(results) > idx and isinstance(results[idx], dict) else {}
        idx += 1
    else:
        db2_stats = {}
        cluster2_info = {}

    from utils.helpers import get_readable_size
    
    # Check if DB1 has writes blocked or is flagged full
    from database.files import is_db1_full, get_active_target_collection
    db1_blocked = is_db1_full()
    
    # Quick probe if not already known blocked
    if not db1_blocked:
        try:
            probe = await mongo.db["_write_probe"].insert_one({"t": time.time()})
            await mongo.db["_write_probe"].delete_one({"_id": probe.inserted_id})
        except Exception as e_probe:
            probe_err = str(e_probe).lower()
            if "quota" in probe_err or "writes are blocked" in probe_err or "code': 8000" in probe_err or "code 8000" in probe_err:
                db1_blocked = True
                import database.files as files_mod
                files_mod._DB1_FULL_STATUS = True

    cluster1_total = cluster1_info.get("totalSize", 0)
    mflix_sz = 0
    for d in cluster1_info.get("databases", []):
        if d.get("name") == "sample_mflix":
            mflix_sz = d.get("sizeOnDisk", 0)

    if db_stats:
        storage_sz = db_stats.get("storageSize", 0)
        index_sz = db_stats.get("indexSize", 0)
        total_mongo_bytes = storage_sz + index_sz
        mongo_used_str = get_readable_size(total_mongo_bytes)
        pct = (total_mongo_bytes / (512 * 1024 * 1024)) * 100
        
        if db1_blocked:
            cluster_str = f" (Cluster: {get_readable_size(cluster1_total)} / 512 MB)" if cluster1_total else ""
            mongo_storage_line = f"• <b>Primary DB (DB1):</b> <code>{mongo_used_str}</code>{cluster_str} ⛔ <b>WRITES BLOCKED!</b> 🔴\n"
            if mflix_sz > 0:
                mongo_storage_line += f"  ⚠️ <i>Atlas Space Quota Exceeded! Unused DB 'sample_mflix' is using {get_readable_size(mflix_sz)}! (Use /cleanupsampledb)</i>\n"
        else:
            mongo_icon = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")
            mongo_storage_line = f"• <b>Primary DB (DB1):</b> <code>{mongo_used_str} / 512 MB ({pct:.1f}%)</code> {mongo_icon}\n"
        
        mongo_details_line = f"• <b>DB1 Objects:</b> <code>{db_stats.get('objects', 0):,} docs ({get_readable_size(index_sz)} index)</code>\n"
    else:
        mongo_storage_line = "• <b>Primary DB (DB1):</b> <code>Online (Atlas Cloud)</code>\n"
        mongo_details_line = ""

    if mongo.has_secondary and db2_stats:
        storage_sz2 = db2_stats.get("storageSize", 0)
        index_sz2 = db2_stats.get("indexSize", 0)
        total_bytes2 = storage_sz2 + index_sz2
        pct2 = (total_bytes2 / (512 * 1024 * 1024)) * 100
        icon2 = "🟢" if pct2 < 70 else ("🟡" if pct2 < 90 else "🔴")
        mongo_storage_line += f"• <b>Secondary DB (DB2):</b> <code>{get_readable_size(total_bytes2)} / 512 MB ({pct2:.1f}%)</code> {icon2}\n"
        mongo_details_line += f"• <b>DB2 Objects:</b> <code>{db2_stats.get('objects', 0):,} docs ({get_readable_size(index_sz2)} index)</code>\n"
        combined_used = (total_mongo_bytes if db_stats else 0) + total_bytes2
        comb_pct = (combined_used / (1024 * 1024 * 1024)) * 100
        mongo_storage_line += f"• <b>Total Dual Storage:</b> <code>{get_readable_size(combined_used)} / 1024 MB ({comb_pct:.1f}%)</code>\n"
        _, target_status = await get_active_target_collection()
        mongo_storage_line += f"• <b>Active Upload Target:</b> <code>{target_status.upper()}</code>\n"
    elif not mongo.has_secondary:
        mongo_storage_line += "• <b>Secondary DB:</b> <code>⚪ Inactive (Single Cluster Mode)</code>\n"

    ping_ms = round((time.time() - t0) * 1000, 1)

    import psutil
    ram = psutil.virtual_memory()
    ram_str = f"{ram.percent}% ({ram.used / (1024**3):.1f} GB / {ram.total / (1024**3):.1f} GB)"
    cpu_percent = psutil.cpu_percent(interval=None)
    disk = psutil.disk_usage('.')
    disk_str = f"{disk.percent}% ({disk.free / (1024**3):.1f} GB Free)"

    start_t = getattr(Config, "START_TIME", time.time())
    elapsed = int(time.time() - start_t)
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    uptime_parts = []
    if days > 0:
        uptime_parts.append(f"{days}d")
    if hours > 0:
        uptime_parts.append(f"{hours}h")
    uptime_parts.append(f"{mins}m {secs}s")
    uptime_str = " ".join(uptime_parts)

    top_demand_str = "None"
    if top_demand_doc:
        top_demand_str = f"{top_demand_doc.get('title', 'N/A')} ({top_demand_doc.get('count', 0)} searches)"

    dashboard_text = (
        "📊 <b>AKMOVIEVERSE • PRO COMMAND DASHBOARD</b> 🚀\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>CONTENT & STORAGE METRICS:</b>\n"
        f"• <b>Total Indexed Files:</b> <code>{files_count:,}</code> files\n"
        f"• <b>Added Today (Last 24h):</b> <code>+{files_today:,}</code> files\n"
        f"{mongo_storage_line}"
        f"{mongo_details_line}"
        f"• <b>Host Disk Storage:</b> <code>{disk_str}</code>\n\n"

        "👥 <b>AUDIENCE & MONETIZATION:</b>\n"
        f"• <b>Total Registered Users:</b> <code>{users_count:,}</code> users\n"
        f"• <b>New Users Today:</b> <code>+{users_today:,}</code> joined\n"
        f"• <b>Active VIP Members:</b> <code>{vip_count:,}</code> members 💎\n"
        f"• <b>Connected Groups:</b> <code>{chats_count:,}</code> groups\n"
        f"• <b>Shortener Gateways:</b> <code>{shorteners_count}</code> in rotation (Status: <code>{'ON' if Config.SHORTENER_ENABLED else 'OFF'}</code>)\n\n"

        "🔔 <b>AUDIENCE DEMAND & ALERTS:</b>\n"
        f"• <b>Active 'Notify Me' Alerts:</b> <code>{pending_alerts:,}</code> users waiting\n"
        f"• <b>Top Demanded Movie:</b> <code>{top_demand_str}</code>\n\n"

        "⚡ <b>SERVER HEALTH & ENGINE:</b>\n"
        f"• <b>Bot Uptime:</b> <code>{uptime_str}</code>\n"
        f"• <b>Server RAM:</b> <code>{ram_str}</code>\n"
        f"• <b>CPU Load:</b> <code>{cpu_percent}%</code>\n"
        f"• <b>Ping Latency:</b> <code>{ping_ms} ms</code>\n"
        f"• <b>Core Engine:</b> <code>Hydrogram MTProto • Python 3.11</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_admin_stats"),
            InlineKeyboardButton("📦 Full DB Backup", callback_data="trigger_quick_backup")
        ]
    ])

    try:
        await query.message.edit_text(dashboard_text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^trigger_quick_backup$"))
async def trigger_quick_backup_callback(client: Client, query: CallbackQuery):
    """Trigger 1-click database backup directly from /stats."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied.", show_alert=True)

    await query.answer("📦 Generating full database backup...")
    try:
        from plugins.backup import backup_database
        await backup_database(client, query.message)
    except Exception as e:
        await query.message.reply_text(f"❌ <b>Backup Error:</b> <code>{e}</code>")


@Client.on_message(filters.command(["targetdb", "setwritedb"]))
async def target_db_command(client: Client, message: Message):
    """View or switch active MongoDB write target ('1', '2', or 'auto')."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    from database.mongo import get_bot_setting, set_bot_setting
    from database.files import get_active_target_collection

    args = message.text.split()[1:]
    current_setting = await get_bot_setting("target_write_db", "auto")
    _, active_status = await get_active_target_collection()

    if not args:
        sec_status = "🟢 Connected (Dual-Cluster Mode)" if mongo.has_secondary else "⚪ Not Configured (Single Cluster Mode)"
        return await message.reply_text(
            "🗄️ <b>MONGODB STORAGE ROUTING CONTROL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Primary DB (DB1):</b> <code>Active</code>\n"
            f"• <b>Secondary DB (DB2):</b> <code>{sec_status}</code>\n"
            f"• <b>Configured Mode:</b> <code>{current_setting.upper()}</code>\n"
            f"• <b>Active Write Target:</b> <code>{active_status.upper()}</code>\n\n"
            "<b>Usage to Switch:</b>\n"
            "• <code>/targetdb auto</code> - Auto-switch to DB2 when DB1 reaches 440MB (Alerts at 400MB, 420MB, 440MB)\n"
            "• <code>/targetdb 1</code> - Force write new uploads to Primary DB (DB1)\n"
            "• <code>/targetdb 2</code> - Force write new uploads to Secondary DB (DB2)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    val = args[0].lower().strip()
    if val not in ["1", "2", "auto"]:
        return await message.reply_text("❌ Invalid mode. Choose <code>1</code>, <code>2</code>, or <code>auto</code>.")

    if val == "2" and not mongo.has_secondary:
        return await message.reply_text("⚠️ <b>Secondary DB is not configured yet!</b>\nPlease add <code>SECONDARY_DATABASE_URI</code> in <code>config.py</code> first before selecting DB2.")

    await set_bot_setting("target_write_db", val)
    await message.reply_text(f"✅ <b>MongoDB Write Target updated to:</b> <code>{val.upper()}</code>\nNew file uploads will now be routed according to this mode.")


@Client.on_message(filters.command(["cleanupsampledb", "dropsampledb"]))
async def cleanup_sample_db_command(client: Client, message: Message):
    """Safely drop MongoDB Atlas default 'sample_mflix' database to free up 128MB+ space on Primary cluster."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    status_msg = await message.reply_text("⏳ <b>Inspecting MongoDB Primary Cluster for sample datasets...</b>")
    try:
        if not mongo._client:
            mongo.connect()
        dbs_res = await mongo._client.admin.command('listDatabases')
        db_names = [d['name'] for d in dbs_res.get('databases', [])]
        if 'sample_mflix' not in db_names:
            return await status_msg.edit_text("ℹ️ <b>'sample_mflix' was not found on your Primary Cluster.</b>\nNo sample databases to clean up.")

        mflix_sz = next((d['sizeOnDisk'] for d in dbs_res.get('databases', []) if d['name'] == 'sample_mflix'), 0)
        from utils.helpers import get_readable_size
        sz_str = get_readable_size(mflix_sz)

        # Drop the sample database or its collections if user lacks cluster-level dropDatabase
        try:
            await mongo._client.drop_database('sample_mflix')
        except Exception as e_drop:
            # Fallback: drop individual collections in sample_mflix
            mflix = mongo._client['sample_mflix']
            cols = await mflix.list_collection_names()
            for col in cols:
                try:
                    await mflix.drop_collection(col)
                except Exception:
                    pass

        # Reset DB1 full status
        import database.files as files_mod
        files_mod._DB1_FULL_STATUS = False
        files_mod._LAST_DB1_CHECK_TIME = 0

        await status_msg.edit_text(
            f"🎉 <b>SAMPLE DATABASE CLEANED UP SUCCESSFULLY!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗑️ Cleaned: <code>sample_mflix</code> (all sample collections purged)\n"
            f"💾 Storage Reclaimed: <code>~{sz_str}</code> (Atlas space quota restored!)\n"
            f"🔓 Primary DB (DB1) Writes: <b>UNLOCKED 🟢</b>\n\n"
            f"<i>You can now upload & index files to Primary DB without restrictions. Run /stats to verify.</i>"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Failed to drop sample database:</b> <code>{e}</code>")


@Client.on_message(filters.command(["setfreelimit", "freelimit", "set_free_limit"]) & filters.private)
async def set_free_limit_command(client: Client, message: Message):
    """View or update the daily free downloads quota per user."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    from database.mongo import set_bot_setting

    args = message.text.split()
    if len(args) < 2:
        current_limit = getattr(Config, "DAILY_FREE_LIMIT", 3)
        return await message.reply_text(
            "🎁 <b>Daily Free Download Limit Settings</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Current Limit:</b> <code>{current_limit} files/day</code>\n\n"
            "<b>Usage to Update:</b>\n"
            "• <code>/setfreelimit 3</code> — Set 3 free files daily per user\n"
            "• <code>/setfreelimit 1</code> — Set 1 free file daily per user\n"
            "• <code>/setfreelimit 0</code> — Disable free files (require verification for all)\n\n"
            "💡 <i>Users get this quota free every day. Once exhausted, they must verify for 24h pass or get VIP.</i>"
        )

    val_str = args[1].strip()
    if not val_str.isdigit():
        return await message.reply_text("❌ Please enter a valid number (e.g. <code>/setfreelimit 3</code>).")

    new_limit = int(val_str)
    Config.DAILY_FREE_LIMIT = new_limit
    await set_bot_setting("daily_free_limit", new_limit)

    status_str = f"<code>{new_limit} files/day</code>" if new_limit > 0 else "<b>Disabled (0)</b>"
    await message.reply_text(
        f"✅ <b>Daily Free Limit Updated!</b>\n\n"
        f"• <b>New Limit:</b> {status_str}\n"
        f"• Every normal user will now get <b>{new_limit}</b> free downloads each day before shortener verification.\n"
        f"• Saved dynamically in MongoDB (no bot restart required)."
    )


# 2. /broadcast Command (PM Broadcast to Users)
@Client.on_message(filters.command("broadcast") & filters.private)
async def user_broadcast_command(client: Client, message: Message):
    """Send broadcast message or media to all registered users."""
    if not Config.is_admin(message.from_user.id):
        return

    broadcast_msg = message.reply_to_message
    if not broadcast_msg:
        await message.reply_text("⚠️ <b>Reply to the message you want to broadcast!</b>")
        return

    user_ids = await get_all_user_ids()
    total_users = len(user_ids)
    if total_users == 0:
        await message.reply_text("❌ No users found in database.")
        return

    progress_msg = await message.reply_text(f"🚀 <b>Broadcasting to {total_users:,} users...</b>")

    sent = 0
    blocked = 0
    failed = 0
    last_update = time.time()

    for user_id in user_ids:
        try:
            await broadcast_msg.copy(chat_id=user_id)
            sent += 1
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
            try:
                await broadcast_msg.copy(chat_id=user_id)
                sent += 1
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid):
            blocked += 1
            try:
                await mongo.users.delete_one({"user_id": user_id})
            except Exception:
                pass
        except Exception:
            failed += 1

        if time.time() - last_update > 10:
            last_update = time.time()
            try:
                await progress_msg.edit_text(
                    f"📢 <b>Broadcast in Progress...</b>\n\n"
                    f"<b>Total Users:</b> <code>{total_users:,}</code>\n"
                    f"<b>Delivered:</b> <code>{sent:,}</code>\n"
                    f"<b>Blocked/Deleted:</b> <code>{blocked:,}</code>\n"
                    f"<b>Failed:</b> <code>{failed:,}</code>"
                )
            except Exception:
                pass

    await progress_msg.edit_text(
        f"🎉 <b>Broadcast Completed!</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{total_users:,}</code>\n"
        f"✅ <b>Delivered:</b> <code>{sent:,}</code>\n"
        f"🧹 <b>Blocked/Deleted (Purged from DB):</b> <code>{blocked:,}</code>\n"
        f"⚠️ <b>Failed:</b> <code>{failed:,}</code>"
    )


# 3. /grp_broadcast Command (Broadcast to Connected Groups)
@Client.on_message(filters.command("grp_broadcast") & filters.private)
async def group_broadcast_command(client: Client, message: Message):
    """Broadcast announcement to all registered groups."""
    if not Config.is_admin(message.from_user.id):
        return

    broadcast_msg = message.reply_to_message
    if not broadcast_msg:
        await message.reply_text("⚠️ <b>Reply to the message you want to broadcast to groups!</b>")
        return

    chat_ids = await get_all_chat_ids()
    total_chats = len(chat_ids)
    if total_chats == 0:
        await message.reply_text("❌ No groups found in database.")
        return

    progress_msg = await message.reply_text(f"🚀 <b>Broadcasting to {total_chats:,} groups...</b>")

    sent = 0
    failed = 0
    last_update = time.time()

    for chat_id in chat_ids:
        try:
            await broadcast_msg.copy(chat_id=chat_id)
            sent += 1
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
            try:
                await broadcast_msg.copy(chat_id=chat_id)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

        if time.time() - last_update > 10:
            last_update = time.time()
            try:
                await progress_msg.edit_text(
                    f"📢 <b>Group Broadcast in Progress...</b>\n\n"
                    f"<b>Total Groups:</b> <code>{total_chats:,}</code>\n"
                    f"<b>Delivered:</b> <code>{sent:,}</code>\n"
                    f"<b>Failed/Left:</b> <code>{failed:,}</code>"
                )
            except Exception:
                pass

    await progress_msg.edit_text(
        f"🎉 <b>Group Broadcast Completed!</b>\n\n"
        f"<b>Total Groups:</b> <code>{total_chats:,}</code>\n"
        f"<b>Delivered:</b> <code>{sent:,}</code>\n"
        f"<b>Failed/Left:</b> <code>{failed:,}</code>"
    )


# ------------------------------------------------------------------------------
# 3.1 Advanced Broadcast with Custom URL Buttons & Auto-Pin (/abroadcast)
# ------------------------------------------------------------------------------

def parse_broadcast_custom_buttons(text: str) -> InlineKeyboardMarkup | None:
    """Parse inline URL buttons formatted as [Button Title | https://link.com].
    Supports multiple rows (newlines) and multiple buttons per row.
    """
    if not text:
        return None
    keyboard = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        matches = re.findall(r"\[([^\|\]]+)\|\s*([^\]]+)\]", line)
        if matches:
            row = []
            for btn_text, btn_url in matches:
                b_text = btn_text.strip()
                b_url = btn_url.strip()
                if b_url.startswith(("http://", "https://", "tg://")):
                    row.append(InlineKeyboardButton(b_text, url=b_url))
            if row:
                keyboard.append(row)
    return InlineKeyboardMarkup(keyboard) if keyboard else None


@Client.on_message(filters.command(["preview_broadcast", "test_abroadcast"]) & filters.private)
async def preview_broadcast_command(client: Client, message: Message):
    """Admin tool to test and preview a broadcast message with custom buttons in PM first."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    broadcast_msg = message.reply_to_message
    if not broadcast_msg:
        return await message.reply_text(
            "⚠️ <b>Reply to the message you want to preview!</b>\n\n"
            "<b>Usage:</b>\n"
            "Reply to any post with:\n"
            "<code>/preview_broadcast\n"
            "[📢 Join Channel | https://t.me/Akmovieszone]\n"
            "[👑 Buy VIP Pass | https://t.me/Akmovieszone_bot?start=plans]</code>"
        )

    cmd_text = message.text or ""
    custom_markup = parse_broadcast_custom_buttons(cmd_text) or broadcast_msg.reply_markup

    try:
        await broadcast_msg.copy(
            chat_id=message.from_user.id,
            reply_markup=custom_markup
        )
        await message.reply_text("✅ <b>Above is your broadcast preview with attached custom buttons!</b>\n<i>If everything looks good, broadcast using <code>/abroadcast</code>.</i>")
    except Exception as e:
        await message.reply_text(f"❌ <b>Preview Error:</b> <code>{e}</code>")


@Client.on_message(filters.command(["abroadcast", "advbroadcast", "broadcast_btn"]) & filters.private)
async def advanced_broadcast_command(client: Client, message: Message):
    """Broadcast post to all users with custom inline URL buttons and optional -pin flag."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    broadcast_msg = message.reply_to_message
    if not broadcast_msg:
        return await message.reply_text(
            "📢 <b>ADVANCED BROADCAST WITH BUTTONS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Reply to any message (photo, video, text, document) with buttons:\n\n"
            "<b>Example 1 (With Buttons):</b>\n"
            "<code>/abroadcast\n"
            "[📢 Main Channel | https://t.me/Akmovieszone]\n"
            "[👑 Buy VIP | https://t.me/Akmovieszone_bot?start=plans]</code>\n\n"
            "<b>Example 2 (Buttons in same row):</b>\n"
            "<code>/abroadcast\n"
            "[📢 Channel | https://t.me/mychannel][👥 Group | https://t.me/mygroup]</code>\n\n"
            "<b>Optional Flags:</b>\n"
            "• <code>-pin</code> : Auto-pin message in PM for all users\n"
            "  <i>Example:</i> <code>/abroadcast -pin [Channel | https://t.me/mychannel]</code>\n\n"
            "💡 Tip: Use <code>/preview_broadcast</code> to test layout before sending!"
        )

    cmd_text = message.text or ""
    do_pin = "-pin" in cmd_text.lower().split()
    custom_markup = parse_broadcast_custom_buttons(cmd_text) or broadcast_msg.reply_markup

    user_ids = await get_all_user_ids()
    total_users = len(user_ids)
    if total_users == 0:
        return await message.reply_text("❌ No users found in database.")

    progress_msg = await message.reply_text(f"🚀 <b>Broadcasting to {total_users:,} users with custom buttons...</b>")

    sent = 0
    blocked = 0
    failed = 0
    pinned_count = 0
    last_update = time.time()

    for user_id in user_ids:
        try:
            sent_m = await broadcast_msg.copy(chat_id=user_id, reply_markup=custom_markup)
            sent += 1
            if do_pin and sent_m:
                try:
                    await sent_m.pin(both_sides=True)
                    pinned_count += 1
                except Exception:
                    pass
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
            try:
                sent_m = await broadcast_msg.copy(chat_id=user_id, reply_markup=custom_markup)
                sent += 1
                if do_pin and sent_m:
                    try:
                        await sent_m.pin(both_sides=True)
                        pinned_count += 1
                    except Exception:
                        pass
            except Exception:
                failed += 1
        except (UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid):
            blocked += 1
            try:
                await mongo.users.delete_one({"user_id": user_id})
            except Exception:
                pass
        except Exception:
            failed += 1

        if time.time() - last_update > 10:
            last_update = time.time()
            pin_txt = f"\n<b>Pinned:</b> <code>{pinned_count:,}</code>" if do_pin else ""
            try:
                await progress_msg.edit_text(
                    f"📢 <b>Advanced Broadcast in Progress...</b>\n\n"
                    f"<b>Total Users:</b> <code>{total_users:,}</code>\n"
                    f"<b>Delivered:</b> <code>{sent:,}</code>\n"
                    f"<b>Blocked/Deleted:</b> <code>{blocked:,}</code>\n"
                    f"<b>Failed:</b> <code>{failed:,}</code>"
                    f"{pin_txt}"
                )
            except Exception:
                pass

    pin_final = f"\n📌 <b>Messages Pinned:</b> <code>{pinned_count:,}</code>" if do_pin else ""
    await progress_msg.edit_text(
        f"🎉 <b>Advanced Broadcast Completed!</b>\n\n"
        f"👥 <b>Total Users:</b> <code>{total_users:,}</code>\n"
        f"✅ <b>Delivered:</b> <code>{sent:,}</code>\n"
        f"🧹 <b>Blocked/Deleted (Purged from DB):</b> <code>{blocked:,}</code>\n"
        f"⚠️ <b>Failed:</b> <code>{failed:,}</code>"
        f"{pin_final}"
    )


@Client.on_message(filters.command(["agrp_broadcast", "adv_grp_broadcast"]) & filters.private)
async def advanced_group_broadcast_command(client: Client, message: Message):
    """Broadcast announcement to all groups with custom inline URL buttons."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    broadcast_msg = message.reply_to_message
    if not broadcast_msg:
        return await message.reply_text(
            "⚠️ <b>Reply to the message you want to broadcast to groups!</b>\n"
            "Format: <code>/agrp_broadcast [Button Text | URL]</code>"
        )

    cmd_text = message.text or ""
    custom_markup = parse_broadcast_custom_buttons(cmd_text) or broadcast_msg.reply_markup

    chat_ids = await get_all_chat_ids()
    total_chats = len(chat_ids)
    if total_chats == 0:
        return await message.reply_text("❌ No groups found in database.")

    progress_msg = await message.reply_text(f"🚀 <b>Broadcasting to {total_chats:,} groups with buttons...</b>")

    sent = 0
    failed = 0
    last_update = time.time()

    for chat_id in chat_ids:
        try:
            await broadcast_msg.copy(chat_id=chat_id, reply_markup=custom_markup)
            sent += 1
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
            try:
                await broadcast_msg.copy(chat_id=chat_id, reply_markup=custom_markup)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

        if time.time() - last_update > 10:
            last_update = time.time()
            try:
                await progress_msg.edit_text(
                    f"📢 <b>Group Broadcast in Progress...</b>\n\n"
                    f"<b>Total Groups:</b> <code>{total_chats:,}</code>\n"
                    f"<b>Delivered:</b> <code>{sent:,}</code>\n"
                    f"<b>Failed/Left:</b> <code>{failed:,}</code>"
                )
            except Exception:
                pass

    await progress_msg.edit_text(
        f"🎉 <b>Group Advanced Broadcast Completed!</b>\n\n"
        f"<b>Total Groups:</b> <code>{total_chats:,}</code>\n"
        f"<b>Delivered:</b> <code>{sent:,}</code>\n"
        f"<b>Failed/Left:</b> <code>{failed:,}</code>"
    )


# 4. /deletecam (CamRip / PreDVD Purge)
@Client.on_message(filters.command(["deletecam", "purgecam", "deletefiles"]))
async def purge_camrip_command(client: Client, message: Message):
    """Clean out all low-quality CamRip and PreDVD files."""
    if not Config.is_admin(message.from_user.id):
        return

    msg = await message.reply_text("🧹 <b>Scanning and deleting CamRip/PreDVD files...</b>")
    deleted_count = await delete_camrip_files()
    await msg.edit_text(f"✅ <b>Cleaned Up!</b> Purged <code>{deleted_count}</code> low-quality CamRip/PreDVD files from database.")


# 5. /cleanfiles (Sanitize competitor site watermarks from stored filenames)
@Client.on_message(filters.command(["cleanfiles", "cleanfilenames", "fixfilenames"]))
async def clean_filenames_command(client: Client, message: Message):
    """Scan and clean competitor watermarks, websites, and ripper tags from all stored filenames in MongoDB."""
    if not Config.is_admin(message.from_user.id):
        return

    status_msg = await message.reply_text("🧹 <b>Scanning database for competitor watermarks & website tags...</b>")

    cleaned_count = 0
    total_scanned = 0

    collections = [mongo.files]
    if mongo.has_secondary:
        collections.append(mongo.files_secondary)

    from utils.title_cleaner import sanitize_stored_filename

    for col in collections:
        async for doc in col.find({}):
            total_scanned += 1
            fn = doc.get("file_name", "")
            cleaned = sanitize_stored_filename(fn)
            if cleaned and cleaned != fn:
                await col.update_one({"_id": doc["_id"]}, {"$set": {"file_name": cleaned}})
                cleaned_count += 1

    await status_msg.edit_text(
        f"✅ <b>Watermark Cleanup Completed!</b>\n\n"
        f"• <b>Total Files Scanned:</b> <code>{total_scanned:,}</code>\n"
        f"• <b>Filenames Cleaned:</b> <code>{cleaned_count:,}</code>\n\n"
        f"✨ <i>All competitor websites, telegram handles, and ripper tags have been permanently removed from stored files while keeping movie titles, print qualities, and extensions 100% intact!</i>"
    )


# 6. /deleteall (MongoDB Storage Wipe & Clean)
@Client.on_message(filters.command(["deleteall", "delall", "purgeall", "wipedb", "cleandb"]))
async def delete_all_files_command(client: Client, message: Message):
    """Wipe indexed files & caches with mandatory pre-wipe safety backup and interactive confirmation."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split()
    if len(args) >= 2 and args[1].lower() in ["confirm", "yes", "force"]:
        status_msg = await message.reply_text(
            "🛡️ <b>Step 1/2: Generating Safety Net Backup...</b>\n"
            "<i>Creating offsite compressed .zip archive of all MongoDB collections...</i>"
        )
        from plugins.backup import generate_and_send_backup
        success, backup_info = await generate_and_send_backup(
            client, message.chat.id, reason="Pre-Wipe Safety Net (/deleteall confirm)"
        )

        await status_msg.edit_text(
            "💥 <b>Step 2/2: Purging Files & Cache Bloat from MongoDB...</b>\n"
            "<i>Dropping files, tmdb cache, channel posts, checkpoints, and verifications...</i>"
        )

        res = await purge_files_and_caches()

        backup_status = f"<code>{backup_info}</code> (Sent to Admin &amp; LOG_CHANNEL)" if success else f"⚠️ Failed: {backup_info}"
        report = (
            "🎉 <b>MongoDB Storage Cleared Successfully!</b>\n\n"
            f"🛡️ <b>Pre-Wipe Backup:</b> {backup_status}\n\n"
            "<b>Purged Collections Summary:</b>\n"
            f"• <b>Primary DB Files:</b> <code>{res['files_primary']:,}</code> deleted\n"
            f"• <b>Secondary DB Files:</b> <code>{res['files_secondary']:,}</code> deleted\n"
            f"• <b>TMDB Metadata Cache:</b> <code>{res['tmdb_cache']:,}</code> deleted\n"
            f"• <b>Channel Post Mappings:</b> <code>{res['channel_posts']:,}</code> deleted\n"
            f"• <b>Indexer Checkpoints:</b> <code>{res['checkpoints']:,}</code> deleted\n"
            f"• <b>Verifications Cache:</b> <code>{res['verifications']:,}</code> deleted\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Documents Purged:</b> <code>{res['total']:,}</code>\n"
            "💾 <b>MongoDB Storage:</b> 🟢 <b>~0 MB (Clean & Free)</b>\n"
            "✨ <i>User accounts, VIP subscriptions, and bot settings were preserved safely!</i>"
        )
        return await status_msg.edit_text(report)

    # If called without arguments, show live metrics and interactive 2-step buttons
    c1 = await mongo.files.count_documents({})
    c2 = await mongo.files_secondary.count_documents({}) if mongo.has_secondary else 0
    try:
        c_tmdb = await mongo.db["tmdb_post_cache"].count_documents({})
    except Exception:
        c_tmdb = 0
    try:
        c_posts = await mongo.db["channel_posts"].count_documents({})
    except Exception:
        c_posts = 0

    warn_text = (
        "⚠️ <b>DANGER ZONE: MONGODB PURGE & STORAGE CLEANUP</b> ⚠️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "This tool allows you to wipe data to free up your 512 MB MongoDB Atlas storage.\n\n"
        "📊 <b>Current Storage Footprint:</b>\n"
        f"• <b>Primary DB (DB1) Files:</b> <code>{c1:,}</code> records\n"
        f"• <b>Secondary DB (DB2) Files:</b> <code>{c2:,}</code> records\n"
        f"• <b>TMDB Post Cache:</b> <code>{c_tmdb:,}</code> records\n"
        f"• <b>Channel Post Cache:</b> <code>{c_posts:,}</code> records\n\n"
        "🛡️ <b>Pre-Wipe Safety Guarantee:</b>\n"
        "An automatic full <code>.zip</code> backup will be generated and dispatched to your PM and <code>LOG_CHANNEL</code> before any deletion begins!\n\n"
        "<b>Select cleanup mode below:</b>\n"
        "• <b>Clean Files & Caches:</b> Purges all files and cache bloat. Storage drops to ~0 MB. Preserves users & VIPs.\n"
        "• <b>Full Factory Reset:</b> Purges files, batches, share links, requests, and alerts. Preserves users & bot credentials.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>Fast Confirm:</i> <code>/deleteall confirm</code>"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 Clean Files & Caches (~0 MB)", callback_data="wipe_files")],
        [InlineKeyboardButton("💥 Full Factory Reset (All Data)", callback_data="wipe_factory")],
        [InlineKeyboardButton("❌ Cancel Purge", callback_data="wipe_cancel")]
    ])

    await message.reply_text(warn_text, reply_markup=buttons)


@Client.on_callback_query(filters.regex(r"^wipe_(files|factory|cancel)$"))
async def wipe_database_callback(client: Client, query: CallbackQuery):
    """Handle 2-step inline keyboard confirmation for database wipe."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied: Admin privileges required.", show_alert=True)

    action = query.data.split("_")[1]

    if action == "cancel":
        await query.answer("Cancelled")
        return await query.message.edit_text("✅ <b>Purge Operation Cancelled.</b> Your database remains untouched.")

    await query.answer("⚡ Initiating Safe Wipe...", show_alert=False)

    from plugins.backup import generate_and_send_backup

    if action == "files":
        await query.message.edit_text(
            "⏳ <b>Step 1/2: Generating Safety Backup...</b>\n"
            "<i>Exporting all MongoDB collections to compressed offsite ZIP...</i>"
        )
        success, backup_info = await generate_and_send_backup(
            client, query.message.chat.id, reason="Safety Net Before Files & Cache Purge"
        )

        await query.message.edit_text(
            "💥 <b>Step 2/2: Purging Files & Cache Bloat from MongoDB...</b>\n"
            "<i>Dropping files, tmdb cache, channel posts, checkpoints, and verifications...</i>"
        )

        res = await purge_files_and_caches()
        backup_status = f"<code>{backup_info}</code> (Sent to Admin &amp; LOG_CHANNEL)" if success else f"⚠️ Failed: {backup_info}"

        report = (
            "🎉 <b>MongoDB Storage Cleared Successfully!</b>\n\n"
            f"🛡️ <b>Pre-Wipe Backup:</b> {backup_status}\n\n"
            "<b>Purged Collections Summary:</b>\n"
            f"• <b>Primary DB Files:</b> <code>{res['files_primary']:,}</code> deleted\n"
            f"• <b>Secondary DB Files:</b> <code>{res['files_secondary']:,}</code> deleted\n"
            f"• <b>TMDB Metadata Cache:</b> <code>{res['tmdb_cache']:,}</code> deleted\n"
            f"• <b>Channel Post Mappings:</b> <code>{res['channel_posts']:,}</code> deleted\n"
            f"• <b>Indexer Checkpoints:</b> <code>{res['checkpoints']:,}</code> deleted\n"
            f"• <b>Verifications Cache:</b> <code>{res['verifications']:,}</code> deleted\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Documents Purged:</b> <code>{res['total']:,}</code>\n"
            "💾 <b>MongoDB Storage:</b> 🟢 <b>~0 MB (Clean & Free)</b>\n"
            "✨ <i>User accounts, VIP subscriptions, and bot settings were preserved safely!</i>"
        )
        return await query.message.edit_text(report)

    elif action == "factory":
        await query.message.edit_text(
            "⏳ <b>Step 1/2: Generating Full Safety Backup...</b>\n"
            "<i>Exporting all MongoDB collections to compressed offsite ZIP...</i>"
        )
        success, backup_info = await generate_and_send_backup(
            client, query.message.chat.id, reason="Safety Net Before Full Factory Reset"
        )

        await query.message.edit_text(
            "💥 <b>Step 2/2: Performing Full Factory Reset...</b>\n"
            "<i>Dropping files, caches, batches, links, requests, and alerts...</i>"
        )

        res = await purge_factory_reset()
        backup_status = f"<code>{backup_info}</code> (Sent to Admin &amp; LOG_CHANNEL)" if success else f"⚠️ Failed: {backup_info}"

        report = (
            "🎉 <b>Full Factory Reset Completed!</b>\n\n"
            f"🛡️ <b>Pre-Wipe Backup:</b> {backup_status}\n\n"
            "<b>Purged Collections Summary:</b>\n"
            f"• <b>Primary DB Files:</b> <code>{res['files_primary']:,}</code> deleted\n"
            f"• <b>Secondary DB Files:</b> <code>{res['files_secondary']:,}</code> deleted\n"
            f"• <b>Batches Collection:</b> <code>{res.get('batches', 0):,}</code> deleted\n"
            f"• <b>Share Links:</b> <code>{res.get('share_links', 0):,}</code> deleted\n"
            f"• <b>Movie Requests:</b> <code>{res.get('movie_requests', 0):,}</code> deleted\n"
            f"• <b>Upload Alerts:</b> <code>{res.get('upload_alerts', 0):,}</code> deleted\n"
            f"• <b>Manual Filters:</b> <code>{res.get('manual_filters', 0):,}</code> deleted\n"
            f"• <b>Caches (TMDB/Posts/Verify):</b> <code>{res['tmdb_cache'] + res['channel_posts'] + res['verifications']:,}</code> deleted\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Documents Purged:</b> <code>{res['total']:,}</code>\n"
            "💾 <b>MongoDB Storage:</b> 🟢 <b>~0 MB (Completely Fresh State)</b>\n"
            "✨ <i>User accounts and bot credentials were preserved safely!</i>"
        )
        return await query.message.edit_text(report)


# Quick Copyright Purge: /delbyname <name>
@Client.on_message(filters.command(["delbyname", "deletebyname", "purgebyname"]) & filters.private)
async def delete_by_name_command(client: Client, message: Message):
    """Admin command: Quick-purge all files matching a movie/series name for copyright risk protection."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/delbyname &lt;Movie or Series Name&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/delbyname Stree 2</code>\n"
            "• <code>/delbyname Mirzapur</code>\n\n"
            "💡 <i>Instantly deletes all 480p, 720p, 1080p, 4K files matching this title from the database!</i>"
        )

    keyword = args[1].strip()
    status = await message.reply_text(f"🔍 <b>Searching and purging all files matching:</b> <code>{keyword}</code>...")

    try:
        from database.mongo import mongo
        from utils.helpers import get_readable_size
        escaped_k = re.escape(keyword)
        cursor = mongo.files.find(
            {"file_name": {"$regex": escaped_k, "$options": "i"}},
            {"file_name": 1, "file_size": 1}
        )
        matching_files = await cursor.to_list(length=500)

        if not matching_files:
            return await status.edit_text(f"ℹ️ <b>No files found matching:</b> <code>{keyword}</code>")

        total_size = sum(f.get("file_size", 0) for f in matching_files)
        del_res = await mongo.files.delete_many({"file_name": {"$regex": escaped_k, "$options": "i"}})
        deleted_count = del_res.deleted_count

        report = (
            "🗑️ <b>Copyright Quick-Purge Completed!</b>\n\n"
            f"🎯 <b>Target Keyword:</b> <code>{keyword}</code>\n"
            f"📁 <b>Files Deleted:</b> <code>{deleted_count}</code>\n"
            f"💾 <b>Reclaimed DB Size:</b> <code>{get_readable_size(total_size)}</code>\n\n"
            "✅ <i>All matching resolutions and qualities have been purged from the search index.</i>"
        )
        await status.edit_text(report)

        if Config.LOG_CHANNEL:
            try:
                await client.send_message(Config.LOG_CHANNEL, report)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error in delbyname command: {e}", exc_info=True)
        await status.edit_text(f"❌ <b>Error purging files:</b> <code>{e}</code>")


# 6. /ban & /unban
@Client.on_message(filters.command("ban"))
async def ban_user_command(client: Client, message: Message):
    """Blacklist a user from bot interaction."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply_text("⚠️ <b>Usage:</b> <code>/ban [user_id]</code>")
        return

    target_id = int(args[1])
    await set_ban_status(target_id, True)
    await message.reply_text(f"🚫 User <code>{target_id}</code> has been blacklisted.")


@Client.on_message(filters.command("unban"))
async def unban_user_command(client: Client, message: Message):
    """Remove user from blacklist."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply_text("⚠️ <b>Usage:</b> <code>/unban [user_id]</code>")
        return

    target_id = int(args[1])
    await set_ban_status(target_id, False)
    await message.reply_text(f"✅ User <code>{target_id}</code> has been unbanned.")


from html import escape as html_escape

# 7. /add_premium & /remove_premium
@Client.on_message(filters.command("add_premium"))
async def add_premium_command(client: Client, message: Message):
    """Grant VIP access to a user for specified duration and notify both admin & user with formatted details."""
    if not Config.is_admin(message.from_user.id):
        return

    target_id = None
    duration_str = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        parts = message.text.split(None, 1)
        if len(parts) > 1:
            duration_str = parts[1].strip()
    else:
        parts = message.text.split()
        if len(parts) >= 3 and parts[1].lstrip("-").isdigit():
            target_id = int(parts[1])
            duration_str = " ".join(parts[2:])
        elif len(parts) == 2 and parts[1].lstrip("-").isdigit():
            target_id = int(parts[1])
            duration_str = "30"

    if not target_id:
        await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/add_premium [user_id] [duration]</code>\n"
            "<i>Or reply to a user's message with</i> <code>/add_premium 7 day</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/add_premium 12345678 7 day</code>\n"
            "• <code>/add_premium 12345678 30 days</code>\n"
            "• <code>/add_premium 12345678 1 month</code>"
        )
        return

    days = 30
    seconds = 30 * 86400
    display_access = "30 day"

    if duration_str:
        m = re.search(r"(\d+)\s*([a-zA-Z]*)", duration_str.lower())
        if m:
            num = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("m"):
                days = num * 30
                seconds = days * 86400
                display_access = f"{num} month" if num == 1 else f"{num} months"
            elif unit.startswith("w"):
                days = num * 7
                seconds = days * 86400
                display_access = f"{num} week" if num == 1 else f"{num} weeks"
            elif unit.startswith("h"):
                days = max(1, num // 24)
                seconds = num * 3600
                display_access = f"{num} hour" if num == 1 else f"{num} hours"
            elif unit.startswith("y"):
                days = num * 365
                seconds = days * 86400
                display_access = f"{num} year" if num == 1 else f"{num} years"
            else:
                days = num
                seconds = days * 86400
                display_access = f"{num} day" if num == 1 else f"{num} days"

    # Fetch user display name
    user_name = "User"
    try:
        user_obj = await client.get_users(target_id)
        if user_obj:
            user_name = user_obj.first_name or user_obj.username or "User"
            if user_obj.last_name:
                user_name = f"{user_name} {user_obj.last_name}".strip()
    except Exception:
        db_user = await mongo.users.find_one({"user_id": target_id})
        if db_user and db_user.get("name"):
            user_name = db_user["name"]

    # IST timestamps (UTC+5:30)
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
    joining_date = now_ist.strftime("%d-%m-%Y")
    joining_time = now_ist.strftime("%I:%M:%S %p")

    await add_premium(target_id, seconds)

    # Fetch updated expiry
    user_doc = await mongo.users.find_one({"user_id": target_id})
    expiry_dt = user_doc.get("premium_expires") if user_doc else None
    if expiry_dt:
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=datetime.timezone.utc)
        expiry_ist = expiry_dt.astimezone(ist_tz)
        expiry_date = expiry_ist.strftime("%d-%m-%Y")
        expiry_time = expiry_ist.strftime("%I:%M:%S %p")
    else:
        exp_calc = now_ist + datetime.timedelta(seconds=seconds)
        expiry_date = exp_calc.strftime("%d-%m-%Y")
        expiry_time = exp_calc.strftime("%I:%M:%S %p")

    # Stremio pre-generation for VIP user
    install_url = None
    try:
        from database.stremio import create_or_get_stremio_token
        from plugins.stremio_admin import _get_stremio_base_url
        stremio_token, _ = await create_or_get_stremio_token(target_id)
        base_url = _get_stremio_base_url()
        install_url = f"{base_url}/stremio/{stremio_token}/install"
    except Exception as e_stremio:
        logger.warning(f"Stremio pre-generation skipped in add_premium: {e_stremio}")

    # 1. Send DM notification to User
    user_dm_text = (
        "<b>PREMIUM ADDED SUCCESSFULLY</b> ✅\n\n"
        f"👤 <b>USER :</b> {html_escape(user_name)}\n"
        f"⚡ <b>USER ID :</b> <code>{target_id}</code>\n"
        f"⏰ <b>PREMIUM ACCESS :</b> <code>{display_access}</code>\n\n"
        f"⏳ <b>JOINING DATE :</b> <code>{joining_date}</code>\n"
        f"🕒 <b>JOINING TIME :</b> <code>{joining_time}</code>\n\n"
        f"⌛ <b>EXPIRY DATE :</b> <code>{expiry_date}</code>\n"
        f"🕒 <b>EXPIRY TIME :</b> <code>{expiry_time}</code>\n\n"
        "🌟 <b>Your Active VIP Perks:</b>\n"
        "• 🚫 <b>Zero Ads & No Shorteners</b> (Direct instant downloads)\n"
        "• ⚡ <b>Superfast 1-Second Direct PM Delivery</b>\n"
        "• 📺 <b>Smart TV Stremio Addon Access (4K/1080p)</b>\n"
        "• 📦 <b>Bulk / Season Pack Deliveries</b>\n"
        "• 🔓 <b>Unlimited Daily Searches & Requests</b>\n\n"
        "💡 <i>Tip: Send /myplan anytime to inspect your subscription or /stremio for TV addon!</i>"
    )

    user_buttons = []
    if install_url:
        user_buttons.append([InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)])
    user_buttons.append([InlineKeyboardButton("⭐ Check My VIP Plan", callback_data="check_my_plan")])

    user_dm_sent = False
    try:
        await client.send_message(
            target_id,
            user_dm_text,
            reply_markup=InlineKeyboardMarkup(user_buttons)
        )
        user_dm_sent = True
    except Exception as e_dm:
        logger.warning(f"Failed to deliver premium DM to {target_id}: {e_dm}")

    # 2. Reply to Admin
    admin_reply = (
        "<b>PREMIUM ADDED SUCCESSFULLY</b> ✅\n\n"
        f"👤 <b>USER :</b> {html_escape(user_name)}\n"
        f"⚡ <b>USER ID :</b> <code>{target_id}</code>\n"
        f"⏰ <b>PREMIUM ACCESS :</b> <code>{display_access}</code>\n\n"
        f"⏳ <b>JOINING DATE :</b> <code>{joining_date}</code>\n"
        f"🕒 <b>JOINING TIME :</b> <code>{joining_time}</code>\n\n"
        f"⌛ <b>EXPIRY DATE :</b> <code>{expiry_date}</code>\n"
        f"🕒 <b>EXPIRY TIME :</b> <code>{expiry_time}</code>"
    )
    if user_dm_sent:
        admin_reply += "\n\n📬 <i>Private notification & Stremio link delivered to user!</i>"
    else:
        admin_reply += "\n\n⚠️ <i>User notification could not be delivered (bot not started in PM or blocked).</i>"

    await message.reply_text(admin_reply)


@Client.on_message(filters.command("remove_premium"))
async def remove_premium_command(client: Client, message: Message):
    """Revoke user's VIP status."""
    if not Config.is_admin(message.from_user.id):
        return

    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        args = message.text.split()
        if len(args) >= 2 and args[1].lstrip("-").isdigit():
            target_id = int(args[1])

    if not target_id:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/remove_premium [user_id]</code>")
        return

    await remove_premium(target_id)
    await message.reply_text(f"✅ Revoked VIP status for <code>{target_id}</code>.")
    try:
        await client.send_message(
            target_id,
            "ℹ️ <b>Your VIP Premium subscription has expired or been revoked.</b>\n\n"
            "To renew and regain instant direct downloads & Smart TV streaming, check /plans."
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^check_my_plan$"))
async def check_my_plan_callback(client: Client, query: CallbackQuery):
    """Allow user to check their active plan details from inline button."""
    user_id = query.from_user.id
    from database.users import is_premium, get_user_info
    user = await get_user_info(user_id)
    user_is_vip = await is_premium(user_id)

    if user_is_vip and user.get("premium_expires"):
        expiry_dt = user["premium_expires"]
        now = datetime.datetime.utcnow()
        remaining = expiry_dt - now
        days = max(0, remaining.days)
        hours = max(0, remaining.seconds // 3600)

        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=datetime.timezone.utc)
        exp_ist = expiry_dt.astimezone(ist_tz)

        text = (
            "💎 <b>YOUR VIP MEMBERSHIP STATUS</b> 💎\n\n"
            "• <b>Status:</b> <code>ACTIVE VIP 👑</code>\n"
            f"• <b>Remaining Time:</b> <code>{days} Days, {hours} Hours</code>\n"
            f"• <b>Expires On:</b> <code>{exp_ist.strftime('%d %b %Y, %I:%M %p IST')}</code>\n\n"
            "🌟 <b>Your Active Perks:</b>\n"
            "• 📺 Smart TV Stremio Addon access\n"
            "• 🚫 No shorteners or token verification\n"
            "• ⚡ Instant 1-second direct PM delivery\n"
            "• 🔓 Unlimited daily files & searches\n"
            "• 📦 SEND ALL batch season deliveries\n\n"
            "💡 <i>Enjoy your ultra-fast ad-free experience!</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Extend VIP Plan", callback_data="view_plans")],
            [InlineKeyboardButton("👥 Refer & Earn Free Days", callback_data="view_refer")]
        ])
        await query.message.edit_text(text, reply_markup=markup)
    else:
        from plugins.extra import get_plans_text, get_plans_markup
        await query.message.edit_text(get_plans_text(), reply_markup=get_plans_markup())


# 8. /premium_users or /premium_list
@Client.on_message(filters.command(["premium_users", "premium_list"]))
async def premium_users_command(client: Client, message: Message):
    """List all active VIP premium subscribers with remaining time."""
    if not Config.is_admin(message.from_user.id):
        return

    users = await get_all_premium_users()
    if not users:
        await message.reply_text("ℹ️ <b>No active VIP Premium users found.</b>")
        return

    import datetime
    now = datetime.datetime.utcnow()
    lines = [f"💎 <b>Active VIP Premium Members ({len(users)} Total):</b>\n"]

    for i, u in enumerate(users[:30], 1):
        uid = u.get("user_id")
        name = u.get("name", "User")
        uname = f"@{u['username']}" if u.get("username") else "No username"
        exp = u.get("premium_expires")
        if exp:
            rem = exp - now
            days = max(0, rem.days)
            hours = max(0, rem.seconds // 3600)
            exp_str = f"{days}d {hours}h left ({exp.strftime('%d %b %Y')})"
        else:
            exp_str = "Unknown"

        lines.append(f"{i}. <b>{name}</b> ({uname})\n   🆔 <code>{uid}</code> | ⏳ <code>{exp_str}</code>")

    lines.append("\n💡 <b>Manage:</b>\n• <code>/add_premium [user_id] [days]</code>\n• <code>/remove_premium [user_id]</code>")
    await message.reply_text("\n".join(lines))


# 8. /send <user_id>
@Client.on_message(filters.command("send"))
async def direct_send_command(client: Client, message: Message):
    """Directly send replied media to a specific user ID."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit() or not message.reply_to_message:
        await message.reply_text("⚠️ <b>Usage:</b> Reply to any file/message with <code>/send [user_id]</code>")
        return

    target_id = int(args[1])
    try:
        await message.reply_to_message.copy(chat_id=target_id)
        await message.reply_text(f"✅ Dispatched media to <code>{target_id}</code> successfully.")
    except Exception as e:
        await message.reply_text(f"❌ Failed to dispatch media: <code>{e}</code>")


# 9. /commands (Auto register commands with Telegram Menu)
@Client.on_message(filters.command("commands"))
async def setup_commands_menu(client: Client, message: Message):
    """Auto-register bot commands into Telegram autocomplete menu across all scopes."""
    if not Config.is_admin(message.from_user.id):
        return

    from utils.bot_commands import register_all_bot_commands
    wait_msg = await message.reply_text("🔄 <b>Syncing bot commands with Telegram servers across all scopes...</b>")

    results = await register_all_bot_commands(client)
    text = (
        "✅ <b>Bot Commands Successfully Registered in Telegram!</b>\n\n"
        f"• 👤 <b>Private Chat Commands:</b> <code>{results['user_commands']}</code> commands set\n"
        f"• 👥 <b>Group Admin Commands:</b> <code>{results['group_admin_commands']}</code> commands set\n"
        f"• 👑 <b>Admin Scoped Chats:</b> <code>{results['admin_scoped']}</code> admin accounts configured\n\n"
        "✨ Whenever you type <code>/</code> in this chat or tap the Menu button, all admin commands will automatically appear!"
    )
    if results["errors"]:
        text += f"\n\n⚠️ <b>Notice:</b> Some scopes reported warnings: <code>{results['errors']}</code>"

    await wait_msg.edit_text(text)



# 11. /set_pic <url_or_reply> (Update /start Welcome photo)
@Client.on_message(filters.command(["set_pic", "setpic"]))
async def update_start_pic_command(client: Client, message: Message):
    """Update /start welcome picture or GIF."""
    if not Config.is_admin(message.from_user.id):
        return

    pic_url = None
    if message.reply_to_message and message.reply_to_message.photo:
        pic_url = message.reply_to_message.photo.file_id
    elif len(message.text.split()) > 1:
        pic_url = message.text.split(maxsplit=1)[1].strip()

    if not pic_url:
        await message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "• <code>/set_pic [photo_or_gif_url]</code>\n"
            "• Reply to any photo with <code>/set_pic</code>"
        )
        return

    Config.START_PIC = pic_url
    from database.mongo import set_bot_setting
    await set_bot_setting("start_pic", pic_url)
    await message.reply_text(
        f"✅ <b>Welcome photo updated successfully!</b>\n\n"
        f"• <b>New Pic:</b> <code>{pic_url[:40]}...</code>\n"
        f"💾 <i>Saved permanently to database (persists across restarts).</i>"
    )


# 12. /shorteners (View & toggle URL shortener verification)
@Client.on_message(filters.command(["shorteners", "shortners", "shortener", "shortner", "toggleshortener", "shortener_toggle"]))
async def list_shorteners_command(client: Client, message: Message):
    """View and toggle URL shortener verification: /shortener [on|off|status]"""
    if not Config.is_admin(message.from_user.id):
        return

    from database.mongo import set_bot_setting
    args = message.text.split()
    if len(args) > 1:
        action = args[1].lower()
        if action in ("on", "enable", "true", "yes"):
            Config.SHORTENER_ENABLED = True
            await set_bot_setting("shortener_enabled", True)
            await message.reply_text(
                "🟢 <b>Shortener Verification Enabled!</b>\n\n"
                "• All normal users must now complete a 24-hour shortener verification to download files.\n"
                "• Active VIP members and Admins will automatically bypass all links.\n"
                "• '⚜️ Remove ads ⚜️' button will now appear on search results.\n\n"
                "💾 <i>Saved permanently to database (persists across restarts).</i>"
            )
            return
        elif action in ("off", "disable", "false", "no"):
            Config.SHORTENER_ENABLED = False
            await set_bot_setting("shortener_enabled", False)
            await message.reply_text(
                "🔴 <b>Shortener Verification Disabled!</b>\n\n"
                "• All files are now <b>100% Free & Direct</b> without any ads or shortener tokens.\n"
                "• '⚜️ Remove ads ⚜️' button is automatically hidden from search results.\n"
                "• <i>No verification required for anyone.</i>\n\n"
                "💾 <i>Saved permanently to database (persists across restarts).</i>"
            )
            return
        elif action in ("toggle",):
            new_state = not Config.SHORTENER_ENABLED
            Config.SHORTENER_ENABLED = new_state
            await set_bot_setting("shortener_enabled", new_state)
            state_str = "🟢 ENABLED" if new_state else "🔴 DISABLED"
            await message.reply_text(
                f"🔄 <b>Shortener Verification Toggled:</b> {state_str}\n\n"
                "💾 <i>Saved permanently to database (persists across restarts).</i>"
            )
            return

    from utils.shortener import get_all_active_shorteners
    shorteners = await get_all_active_shorteners()

    status_str = "🟢 <b>ENABLED (24h Verification Active)</b>" if Config.SHORTENER_ENABLED else "🔴 <b>DISABLED (100% Free Direct Delivery)</b>"
    mode = "Round-Robin (50/50 Alternating)" if Config.SHORTENER_ROTATION == "round_robin" else "Random (Balanced)"
    gateway_str = Config.WEB_URL if Config.WEB_URL else "Direct Links (Set via /set_web_url)"

    text = (
        "🌐 <b>URL Shortener Configuration & Status</b>\n"
        "────────────────────────\n"
        f"• <b>Status:</b> {status_str}\n"
        f"• <b>Rotation Mode:</b> <code>{mode}</code>\n"
        f"• <b>Fast-Redirect Gateway:</b> <code>{gateway_str}</code>\n"
        f"• <b>Total Active Providers:</b> <code>{len(shorteners)}</code>\n"
        "────────────────────────\n\n"
    )

    if shorteners:
        for i, s in enumerate(shorteners, 1):
            dom = s["domain"]
            api = s["api"]
            source = s.get("source", "Config")
            masked_api = f"{api[:6]}...{api[-4:]}" if len(api) > 10 else "***"
            text += f"{i}. <b>{dom}</b> ({source})\n   🔑 API: <code>{masked_api}</code>\n\n"
    else:
        text += "ℹ️ <i>No external shortener domains configured. Add one with /add_shortener.</i>\n\n"

    text += (
        "💡 <b>Admin Commands:</b>\n"
        "• <code>/shortener on</code> — Turn shorteners & verification ON\n"
        "• <code>/shortener off</code> — Turn shorteners OFF (Free direct delivery)\n"
        "• <code>/add_shortener [domain] [api_key]</code> — Add provider\n"
        "• <code>/del_shortener [domain]</code> — Remove provider\n"
        "• <code>/set_web_url [public_url]</code> — Set 5s timer gateway"
    )
    await message.reply_text(text)


# 13. /add_shortener <domain> <api>
@Client.on_message(filters.command(["add_shortener", "add_shortner", "addshortener", "addshortner"]))
async def add_shortener_command(client: Client, message: Message):
    """Add or update an extra shortener in the rotation database."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 3:
        await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/add_shortener [website_domain] [api_key]</code>\n\n"
            "<b>Example:</b> <code>/add_shortener shareus.io 1234abcd5678efgh</code>"
        )
        return

    domain = args[1].strip()
    api_key = args[2].strip()

    from utils.shortener import add_custom_shortener
    success = await add_custom_shortener(domain, api_key)
    if success:
        await message.reply_text(
            f"✅ <b>Shortener Added to Rotation & Fallback!</b>\n\n"
            f"• <b>Domain:</b> <code>{domain}</code>\n"
            f"• <b>Status:</b> Active in rotation\n\n"
            "View all active providers anytime via <code>/shorteners</code>."
        )
    else:
        await message.reply_text("❌ Failed to save shortener to database.")


# 14. /del_shortener <domain>
@Client.on_message(filters.command(["del_shortener", "del_shortner", "delshortener", "delshortner"]))
async def delete_shortener_command(client: Client, message: Message):
    """Remove a shortener from the dynamic rotation database."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/del_shortener [domain]</code>\nExample: <code>/del_shortener shareus.io</code>")
        return

    domain = args[1].strip()
    from utils.shortener import remove_custom_shortener
    success = await remove_custom_shortener(domain)
    if success:
        await message.reply_text(f"✅ Shortener <code>{domain}</code> removed from database rotation.")
    else:
        await message.reply_text(f"❌ Shortener <code>{domain}</code> not found in database (or it is in .env file).")


# 15. /set_web_url <url>
@Client.on_message(filters.command(["set_web_url", "setweburl"]))
async def set_web_url_command(client: Client, message: Message):
    """Configure or update the public domain URL for the 5s Fast-Redirect Gateway."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        current = f"<code>{Config.WEB_URL}</code>" if Config.WEB_URL else "<code>None (Disabled, using direct links)</code>"
        await message.reply_text(
            f"🌐 <b>Fast-Redirect Gateway URL:</b> {current}\n\n"
            "<b>Usage:</b> <code>/set_web_url [public_url]</code>\n"
            "<b>Example:</b> <code>/set_web_url https://my-bot.koyeb.app</code>\n\n"
            "💡 When set, Telegram verify buttons will mask raw shortener URLs and run the 5s animated countdown gateway page!"
        )
        return

    url = args[1].strip().rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"

    Config.WEB_URL = url
    from database.mongo import set_bot_setting
    await set_bot_setting("web_url", url)
    await message.reply_text(
        f"✅ <b>Fast-Redirect Gateway URL Updated!</b>\n\n"
        f"🌐 <b>New Gateway Base:</b> <code>{Config.WEB_URL}</code>\n\n"
        "All verify buttons will now route through this branded URL with the 5s animated background timer!\n"
        "💾 <i>Saved permanently to database (persists across restarts).</i>"
    )


# 16. TMDB API Credentials Management
@Client.on_message(filters.command(["set_tmdb_key", "settmdbkey"]))
async def set_tmdb_key_command(client: Client, message: Message):
    """Save or update official TMDB v3 API Key."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text(
            "🔑 <b>Set TMDB API Key (v3):</b>\n\n"
            "<b>Usage:</b> <code>/set_tmdb_key [api_key]</code>\n"
            "<b>Example:</b> <code>/set_tmdb_key 1a2b3c4d5e6f7g8h9i0j</code>\n\n"
            "💡 Get your free API key from https://www.themoviedb.org/settings/api"
        )
        return

    new_key = args[1].strip()
    from database.poster import set_tmdb_credentials
    from database.mongo import set_bot_setting
    await set_tmdb_credentials(api_key=new_key)
    await set_bot_setting("tmdb_api_key", new_key)
    Config.TMDB_API_KEY = new_key
    await message.reply_text(
        f"✅ <b>Official TMDB API Key Saved!</b>\n\n"
        f"🔑 <b>Key:</b> <code>{new_key[:6]}...{new_key[-4:]}</code>\n"
        "Poster Studio will now query TMDB directly with maximum priority!\n"
        "💾 <i>Saved permanently to database (persists across restarts).</i>"
    )


@Client.on_message(filters.command(["set_tmdb_token", "settmdbtoken"]))
async def set_tmdb_token_command(client: Client, message: Message):
    """Save or update official TMDB v4 Read Access Token (Bearer)."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text(
            "🎟️ <b>Set TMDB Read Access Token (v4 Bearer):</b>\n\n"
            "<b>Usage:</b> <code>/set_tmdb_token [token]</code>\n"
            "<b>Example:</b> <code>/set_tmdb_token eyJhbGciOiJIUzI1NiJ9...</code>\n\n"
            "💡 Recommended for highest API performance and no rate limit issues!"
        )
        return

    new_token = args[1].strip()
    from database.poster import set_tmdb_credentials
    from database.mongo import set_bot_setting
    await set_tmdb_credentials(token=new_token)
    await set_bot_setting("tmdb_read_access_token", new_token)
    Config.TMDB_READ_ACCESS_TOKEN = new_token
    await message.reply_text(
        f"✅ <b>Official TMDB Read Access Token Saved!</b>\n\n"
        f"🎟️ <b>Token:</b> <code>{new_token[:8]}...{new_token[-6:]}</code>\n"
        "Direct v4 Bearer authorization is now active for all Poster Studio queries.\n"
        "💾 <i>Saved permanently to database (persists across restarts).</i>"
    )


@Client.on_message(filters.command(["tmdb_status", "tmdbstatus", "tmdb"]))
async def tmdb_status_command(client: Client, message: Message):
    """Display active TMDB authentication status and fallback mode."""
    if not Config.is_admin(message.from_user.id):
        return

    from database.poster import get_tmdb_credentials
    creds = await get_tmdb_credentials()
    token = Config.TMDB_READ_ACCESS_TOKEN or creds.get("token", "")
    key = Config.TMDB_API_KEY or creds.get("api_key", "")

    token_status = f"✅ Active (<code>{token[:8]}...{token[-4:]}</code>)" if token else "❌ Not configured"
    key_status = f"✅ Active (<code>{key[:6]}...{key[-4:]}</code>)" if key else "❌ Not configured"
    fallback_status = "⚡ Public High-Speed Worker Proxy (Active)"

    primary = "Official v4 Bearer Token" if token else ("Official v3 API Key" if key else "Public Worker Proxy")

    text = (
        "🎬 <b>TMDB Poster Scraper Connection Status:</b>\n\n"
        f"• <b>Active Primary Engine:</b> <code>{primary}</code>\n"
        f"• <b>v4 Read Access Token:</b> {token_status}\n"
        f"• <b>v3 API Key:</b> {key_status}\n"
        f"• <b>Automated Fallback:</b> {fallback_status}\n\n"
        "💡 <b>Commands to configure:</b>\n"
        "• <code>/set_tmdb_token [token]</code> — Recommended\n"
        "• <code>/set_tmdb_key [api_key]</code>"
    )
    await message.reply_text(text)


def _parse_time_str(time_str: str) -> int:
    t = time_str.strip().lower()
    if t.endswith("m"):
        return int(t[:-1]) * 60
    elif t.endswith("h"):
        return int(t[:-1]) * 3600
    elif t.endswith("s"):
        return int(t[:-1])
    elif t.isdigit():
        return int(t)
    return 300


@Client.on_message(filters.command(["autodelete", "set_autodelete", "deltime"]))
async def autodelete_settings_command(client: Client, message: Message):
    """View or update auto-delete duration for files and search results."""
    if not Config.is_admin(message.from_user.id):
        return

    from database.mongo import get_bot_setting, set_bot_setting
    args = message.text.split()

    if len(args) >= 3:
        target = args[1].lower()
        val_str = args[2].lower()
        try:
            seconds = _parse_time_str(val_str)
        except ValueError:
            await message.reply_text("❌ <b>Invalid time format.</b> Examples: <code>5m</code>, <code>10m</code>, <code>300</code>, <code>1h</code>")
            return

        if "file" in target:
            await set_bot_setting("file_auto_delete_time", seconds)
            lbl = f"{seconds // 60}m" if seconds >= 60 else f"{seconds}s"
            if seconds == 0:
                lbl = "Disabled"
            await message.reply_text(f"✅ <b>Delivered Files Auto-Delete updated to:</b> <code>{lbl}</code> ({seconds}s)")
            return
        elif "search" in target:
            await set_bot_setting("search_auto_delete_time", seconds)
            lbl = f"{seconds // 60}m" if seconds >= 60 else f"{seconds}s"
            await message.reply_text(f"✅ <b>Search Results Auto-Delete updated to:</b> <code>{lbl}</code> ({seconds}s)")
            return
        else:
            await message.reply_text("❌ Specify target: <code>file</code> or <code>search</code>.\nExample: <code>/set_autodelete file 10m</code>")
            return

    text, markup = await build_autodelete_panel()
    await message.reply_text(text, reply_markup=markup)


async def build_autodelete_panel() -> tuple[str, InlineKeyboardMarkup]:
    from database.mongo import get_bot_setting
    f_del = await get_bot_setting("file_auto_delete_time", getattr(Config, "FILE_AUTO_DELETE_TIME", 300))
    s_del = await get_bot_setting("search_auto_delete_time", getattr(Config, "AUTO_DELETE_TIME", 300))

    f_lbl = f"{f_del // 60}m" if f_del >= 60 else (f"{f_del}s" if f_del > 0 else "❌ Disabled")
    s_lbl = f"{s_del // 60}m" if s_del >= 60 else f"{s_del}s"

    text = (
        "⏱️ <b>AUTO-DELETE CONFIGURATION</b>\n"
        "────────────────────────\n"
        f"📁 <b>Delivered Movie Files Timer:</b> <code>{f_lbl}</code>\n"
        f"🔍 <b>Search Results Timer (PM):</b> <code>{s_lbl}</code>\n"
        "────────────────────────\n\n"
        "👇 <i>Tap a button below to quickly set timer, or use commands:</i>\n"
        "• <code>/set_autodelete file 10m</code>\n"
        "• <code>/set_autodelete search 5m</code>"
    )

    keyboard = [
        [
            InlineKeyboardButton("📁 File: 5m", callback_data="set_del_file_300"),
            InlineKeyboardButton("📁 File: 10m", callback_data="set_del_file_600"),
            InlineKeyboardButton("📁 File: 15m", callback_data="set_del_file_900"),
        ],
        [
            InlineKeyboardButton("🔍 Search: 3m", callback_data="set_del_search_180"),
            InlineKeyboardButton("🔍 Search: 5m", callback_data="set_del_search_300"),
            InlineKeyboardButton("🔍 Search: 10m", callback_data="set_del_search_600"),
        ],
        [
            InlineKeyboardButton("❌ Disable File Auto-Delete", callback_data="set_del_file_0"),
            InlineKeyboardButton("🔒 Close", callback_data="close_autodel")
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


@Client.on_callback_query(filters.regex(r"^set_del_"))
async def autodelete_callback(client: Client, query: CallbackQuery):
    if not Config.is_admin(query.from_user.id):
        await query.answer("⚠️ Admin only.", show_alert=True)
        return

    from database.mongo import set_bot_setting
    data = query.data[len("set_del_"):]
    target, sec_str = data.split("_", 1)
    seconds = int(sec_str)

    if target == "file":
        await set_bot_setting("file_auto_delete_time", seconds)
    elif target == "search":
        await set_bot_setting("search_auto_delete_time", seconds)

    text, markup = await build_autodelete_panel()
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass
    await query.answer("✅ Updated!")


@Client.on_callback_query(filters.regex(r"^close_autodel$"))
async def close_autodel_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.answer()


# 18.5 /streaming (Toggle Fast Video Streaming Engine & Web Player)
@Client.on_message(filters.command(["streaming", "streamtoggle", "togglestream", "setstreaming"]) & filters.private)
async def streaming_toggle_command(client: Client, message: Message):
    """Toggle fast video streaming & web player: /streaming on|off|status"""
    if not Config.is_admin(message.from_user.id):
        return

    from database.mongo import set_bot_setting
    args = message.text.split()
    if len(args) > 1:
        action = args[1].lower()
        if action in ("on", "enable", "true", "yes"):
            Config.ENABLE_STREAMING = True
            await set_bot_setting("enable_streaming", True)
            await message.reply_text(
                "🟢 <b>Fast Video Streaming & Web Player Enabled!</b>\n\n"
                "• Users can now stream videos directly in-browser, VLC, and MX Player.\n"
                "• <i>Saved permanently to database (persists across restarts).</i>"
            )
            return
        elif action in ("off", "disable", "false", "no"):
            Config.ENABLE_STREAMING = False
            await set_bot_setting("enable_streaming", False)
            await message.reply_text(
                "🔴 <b>Fast Video Streaming & Web Player Disabled!</b>\n\n"
                "• Fast streaming engine is now turned OFF.\n"
                "• Streaming buttons will be hidden from file delivery & search results.\n"
                "• <i>Saved permanently to database (persists across restarts).</i>"
            )
            return

    status_str = "🟢 <b>ENABLED</b>" if Config.ENABLE_STREAMING else "🔴 <b>DISABLED</b>"
    await message.reply_text(
        f"⚡ <b>Fast Video Streaming Engine Status:</b> {status_str}\n"
        f"────────────────────────\n"
        f"• <b>Base Stream URL:</b> <code>{Config.STREAM_URL or 'Auto-Detect Port ' + str(Config.PORT)}</code>\n"
        f"• <b>New Tag Duration:</b> <code>{getattr(Config, 'STREAM_NEW_TAG_DAYS', 2)} days</code>\n"
        f"────────────────────────\n\n"
        f"<b>Commands:</b>\n"
        f"• <code>/streaming on</code> — Enable fast streaming & web player\n"
        f"• <code>/streaming off</code> — Disable fast streaming engine\n"
        f"• <code>/stream_download [on|off]</code> — Web player download button toggle"
    )


# 19. /stream_download (Toggle direct download button in web streaming player)
@Client.on_message(filters.command(["stream_download", "player_download"]) & filters.private)
async def stream_download_toggle_command(client: Client, message: Message):
    """Toggle direct fast download button inside web player: /stream_download on|off|status"""
    if not Config.is_admin(message.from_user.id):
        return

    from utils.web_server import is_web_download_enabled, set_web_download_enabled

    args = message.text.split()
    if len(args) > 1:
        action = args[1].lower()
        if action == "on":
            await set_web_download_enabled(True)
            await message.reply_text(
                "✅ <b>Web Player Fast Download Enabled!</b>\n\n"
                "• Users can now download files directly from the web player.\n"
                "• <i>Tip: If you want all downloads to pass through shorteners/VIP in the bot, use:</i> <code>/stream_download off</code>"
            )
            return
        elif action == "off":
            await set_web_download_enabled(False)
            await message.reply_text(
                "🛑 <b>Web Player Fast Download Disabled!</b>\n\n"
                "• Direct downloads in the web player are now replaced with a <code>✈️ Download in Bot</code> button.\n"
                "• <b>Streaming is 100% Free</b> in the player, but offline file downloads require bot verification / VIP!"
            )
            return

    current = await is_web_download_enabled()
    status_str = "🟢 ENABLED (Direct Web Download)" if current else "🔴 DISABLED (Redirects to Bot for Verification)"
    await message.reply_text(
        f"🌐 <b>Web Player Download Configuration</b>\n"
        f"────────────────────────\n"
        f"• <b>Status:</b> {status_str}\n"
        f"• <b>Streaming:</b> Always Free for everyone\n"
        f"────────────────────────\n\n"
        f"<b>Commands:</b>\n"
        f"• <code>/stream_download on</code> — Enable direct web downloads\n"
        f"• <code>/stream_download off</code> — Disable & enforce bot verification"
    )


# 20. /cleanduplicates — Purge 100% exact duplicate files from MongoDB
@Client.on_message(filters.command(["cleanduplicates", "purgeduplicates", "del_duplicates"]) & filters.private)
async def clean_duplicates_command(client: Client, message: Message):
    """Purge 100% exact duplicate file records from MongoDB files collection."""
    if not Config.is_admin(message.from_user.id):
        return

    status_msg = await message.reply_text(
        "🔍 <b>Scanning database for duplicate files...</b>\n"
        "<i>Checking strict 100% match on File Unique ID or exact file size & name...</i>"
    )
    from database.files import clean_duplicate_files
    deleted_count, preserved_count = await clean_duplicate_files()

    if deleted_count > 0:
        await status_msg.edit_text(
            f"✅ <b>Duplicate Cleanup Complete!</b>\n\n"
            f"🗑️ <b>Duplicate Copies Removed:</b> <code>{deleted_count:,}</code> entries\n"
            f"📁 <b>Unique Files Preserved:</b> <code>{preserved_count:,}</code> files\n\n"
            f"✨ Database is now completely optimized and clean!"
        )
    else:
        await status_msg.edit_text(
            f"🎉 <b>No Duplicates Found!</b>\n\n"
            f"📁 All <code>{preserved_count:,}</code> files in your database are 100% unique and optimized."
        )


# 21. /shortenerstats — Shortener Traffic & Verification Dashboard
@Client.on_message(filters.command(["shortenerstats", "shortnerstats", "shortener_stats"]) & filters.private)
async def shortener_stats_command(client: Client, message: Message):
    """Display real-time traffic, daily clicks per shortener domain, and VIP bypasses."""
    if not Config.is_admin(message.from_user.id):
        return

    import datetime
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    today_doc = await mongo.db["shortener_stats"].find_one({"date": today_str}) or {}
    all_time_doc = await mongo.db["shortener_stats"].find_one({"date": "all_time"}) or {}

    today_total = today_doc.get("total", 0)
    today_vip = today_doc.get("vip_bypasses", 0)
    all_time_total = all_time_doc.get("total", 0)

    today_domains = today_doc.get("domains", {})

    from utils.shortener import get_all_active_shorteners
    active_shorteners = await get_all_active_shorteners()

    dom_text = ""
    if today_domains:
        for raw_dom, count in sorted(today_domains.items(), key=lambda x: x[1], reverse=True):
            clean_d = raw_dom.replace("_", ".")
            pct = int((count / today_total) * 100) if today_total else 0
            dom_text += f"  • <b>{clean_d}:</b> <code>{count:,}</code> clicks ({pct}%)\n"
    else:
        dom_text = "  <i>No clicks recorded yet today.</i>\n"

    active_pool_text = ""
    for s in active_shorteners:
        active_pool_text += f"  • <code>{s['domain']}</code> ({s['source']})\n"

    stats_text = (
        f"📊 <b>Shortener Monetization Analytics</b>\n"
        f"📅 <b>Date:</b> <code>{today_str} (UTC)</code>\n"
        f"────────────────────────\n"
        f"⚡ <b>Today's Total Link Clicks:</b> <code>{today_total:,}</code>\n"
        f"💎 <b>VIP Direct Bypasses:</b> <code>{today_vip:,}</code>\n"
        f"📈 <b>All-Time Link Clicks:</b> <code>{all_time_total:,}</code>\n\n"
        f"🌐 <b>Today's Traffic Share per Provider:</b>\n{dom_text}\n"
        f"🔄 <b>Rotation Mode:</b> <code>{Config.SHORTENER_ROTATION.upper()}</code>\n"
        f"📋 <b>Active Shortener Pool ({len(active_shorteners)}):</b>\n{active_pool_text}"
        f"────────────────────────\n"
        f"<i>Tip: Add more shorteners via</i> <code>/add_shortener &lt;domain&gt; &lt;api&gt;</code>"
    )

    await message.reply_text(stats_text)


# ============================================================
# Dynamic Junk Words / Ripper Tag Filter Commands
# ============================================================

@Client.on_message(filters.command(["addjunk", "add_junk"]) & filters.private)
async def add_junk_command(client: Client, message: Message):
    """Add a new custom pirated site name or junk tag to the universal title cleaner."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/addjunk &lt;word_or_domain&gt;</code>\n"
            "<b>Example:</b> <code>/addjunk 1TamilMV</code> or <code>/addjunk BollyFlix.Org</code>"
        )

    word = args[1].strip()
    from utils.title_cleaner import add_dynamic_junk_word
    success = await add_dynamic_junk_word(word)
    if success:
        await message.reply_text(
            f"✅ <b>Successfully Blacklisted Junk Word:</b> <code>{word}</code>\n"
            f"The bot will now automatically strip this watermark from all titles, channel posts, and TMDB searches!"
        )
    else:
        await message.reply_text("❌ Failed to add junk word. Please try again.")


@Client.on_message(filters.command(["deljunk", "del_junk", "removejunk"]) & filters.private)
async def del_junk_command(client: Client, message: Message):
    """Remove a custom junk word from the universal title cleaner."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text("⚠️ <b>Usage:</b> <code>/deljunk &lt;word&gt;</code>")

    word = args[1].strip()
    from utils.title_cleaner import remove_dynamic_junk_word
    success = await remove_dynamic_junk_word(word)
    if success:
        await message.reply_text(f"🗑️ <b>Removed Junk Word:</b> <code>{word}</code> from blacklist.")
    else:
        await message.reply_text(f"⚠️ Word <code>{word}</code> was not found in custom junk list.")


@Client.on_message(filters.command(["junkwords", "listjunk", "junklist"]) & filters.private)
async def list_junk_command(client: Client, message: Message):
    """List all custom blacklisted junk words."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    from utils.title_cleaner import get_dynamic_junk_words, STATIC_PIRATE_SITES
    dynamic_words = await get_dynamic_junk_words()

    dyn_text = "\n".join([f"• <code>{w}</code>" for w in sorted(dynamic_words)]) if dynamic_words else "<i>No custom junk words added yet.</i>"

    await message.reply_text(
        "🧹 <b>UNIVERSAL TITLE CLEANER • JUNK FILTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Pre-configured Sites & Encoders:</b> <code>{len(STATIC_PIRATE_SITES)}+ known domains & groups</code>\n"
        "<i>(Includes 1TamilMV, TamilBlasters, MovieRulz, VegaMovies, BollyFlix, 1337x, YTS, etc.)</i>\n\n"
        f"📝 <b>Custom Admin Blacklist ({len(dynamic_words)}):</b>\n{dyn_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Commands:</b>\n"
        "• <code>/addjunk &lt;tag&gt;</code> - Add new site tag\n"
        "• <code>/deljunk &lt;tag&gt;</code> - Remove site tag\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


