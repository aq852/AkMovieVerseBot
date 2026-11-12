import sys
import os
import logging
import asyncio
try:
    from hydrogram import Client, idle, enums
except ImportError:
    from pyrogram import Client, idle, enums

from config import Config
from database.mongo import init_indexes
from utils.web_server import run_web_server

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt="%d-%b-%y %H:%M:%S"
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger("AutoFilterBot")

class Bot(Client):
    def __init__(self):
        super().__init__(
            name="AutoFilterBot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            plugins=dict(root="plugins"),
            workers=50,
            parse_mode=enums.ParseMode.HTML
        )

    async def start(self):
        await super().start()
        Config.MASTER_CLIENT = self
        me = await self.get_me()
        Config.BOT_USERNAME = me.username
        logger.info(f"Auto Filter Bot @{me.username} successfully started!")

        # 1. Initialize MongoDB Indexes & Hydrate Dynamic Settings
        await init_indexes()
        try:
            from database.mongo import load_dynamic_settings
            await load_dynamic_settings()
        except Exception as e:
            logger.warning(f"Could not load dynamic settings: {e}")

        # Notify pending restart origin
        try:
            pending = None
            restart_file = "/tmp/autofilterbot_restart.json"
            if os.path.exists(restart_file):
                try:
                    import json
                    with open(restart_file, "r") as f:
                        pending = json.load(f)
                    os.remove(restart_file)
                except Exception:
                    pass

            if not pending:
                from database.mongo import get_bot_setting
                pending = await get_bot_setting("restart_notification", None)

            if pending and "chat_id" in pending and "message_id" in pending:
                try:
                    from database.mongo import set_bot_setting
                    await set_bot_setting("restart_notification", None)
                except Exception:
                    pass
                await self.edit_message_text(
                    chat_id=pending["chat_id"],
                    message_id=pending["message_id"],
                    text="🚀 <b>AutoFilterBot is successfully RESTARTED & ONLINE!</b>"
                )
        except Exception as e:
            logger.warning(f"Error sending restart notification: {e}")

        # 2. Launch Background Web Server for Cloud Health Checks (Koyeb/Render)
        asyncio.create_task(run_web_server())

        # 3. Notify Log Channel
        if Config.LOG_CHANNEL:
            try:
                from database.files import get_total_files_count
                from database.users import get_total_users_count
                from database.chats import get_total_chats_count

                files_count = await get_total_files_count()
                users_count = await get_total_users_count()
                chats_count = await get_total_chats_count()

                startup_text = (
                    "🚀 <b>AutoFilterBot Online & Active!</b>\n\n"
                    f"🤖 <b>Bot:</b> @{me.username}\n"
                    f"📁 <b>Indexed Files:</b> <code>{files_count:,}</code>\n"
                    f"👤 <b>Total Users:</b> <code>{users_count:,}</code>\n"
                    f"👥 <b>Connected Groups:</b> <code>{chats_count:,}</code>\n"
                    f"⚡ <b>Shortener:</b> <code>{'Enabled' if Config.SHORTENER_ENABLED else 'Disabled'}</code>\n"
                    f"🍿 <b>Fast Streaming:</b> <code>{'Enabled' if Config.ENABLE_STREAMING else 'Disabled'}</code>\n"
                    f"☁️ <b>Platform:</b> Hydrogram MTProto / Python 3.11\n"
                    f"🌐 <b>Web Port:</b> <code>{Config.PORT}</code>"
                )
                await self.send_message(Config.LOG_CHANNEL, startup_text)
            except Exception as e:
                logger.warning(f"Could not send log channel notification: {e}")

        # 4. Auto-register Bot Commands across All Scopes (Users, Group Admins, Bot Admins)
        try:
            from utils.bot_commands import register_all_bot_commands
            asyncio.create_task(register_all_bot_commands(self))
            logger.info("Triggered automatic Telegram bot commands registration.")
        except Exception as e:
            logger.warning(f"Could not trigger bot commands setup: {e}")

        # 5. Start Universal Downloader Queue Worker
        try:
            from plugins.downloader import ensure_worker_started
            ensure_worker_started(self)
        except Exception as e:
            logger.warning(f"Could not initialize downloader worker: {e}")

        # 6. Purge any stale temporary downloads from prior crashes/restarts
        try:
            from utils.downloader import purge_stale_temp_downloads
            purge_stale_temp_downloads()
        except Exception as e:
            logger.warning(f"Could not purge stale temp downloads: {e}")

        # 7. Start Daily Auto-Broadcast Scheduler (Fresh Drops & Hidden Gems)
        try:
            from plugins.daily_broadcast import start_daily_broadcast_scheduler
            asyncio.create_task(start_daily_broadcast_scheduler(self))
            logger.info("Launched Daily Auto-Broadcast background scheduler.")
        except Exception as e:
            logger.warning(f"Could not launch daily broadcast scheduler: {e}")

        # 8. Start Weekly Sunday Database Auto-Backup Scheduler
        try:
            from plugins.backup import start_weekly_backup_scheduler
            asyncio.create_task(start_weekly_backup_scheduler(self))
            logger.info("Launched Weekly Auto-Backup background scheduler.")
        except Exception as e:
            logger.warning(f"Could not launch weekly backup scheduler: {e}")

        # 8b. Start Weekly Sunday Database Housekeeping & Storage Auto-Cleaner
        try:
            from plugins.housekeeping import start_weekly_housekeeping_scheduler
            asyncio.create_task(start_weekly_housekeeping_scheduler(self))
            logger.info("Launched Weekly Database Housekeeping background scheduler.")
        except Exception as e:
            logger.warning(f"Could not launch weekly housekeeping scheduler: {e}")

        # 9. Start Periodic MongoDB Storage Health & Alert Checker (Every 15 Minutes)
        try:
            async def _storage_health_loop():
                while True:
                    try:
                        await asyncio.sleep(900)
                        from database.files import get_active_target_collection
                        await get_active_target_collection()
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        pass
            asyncio.create_task(_storage_health_loop())
            logger.info("Launched MongoDB Storage Health & Alert monitor.")
        except Exception as e:
            logger.warning(f"Could not launch storage health monitor: {e}")

        # 10. Check for Interrupted Channel Indexing Checkpoints (Resume Alert)
        try:
            from plugins.channel_indexer import check_and_notify_interrupted_checkpoints
            asyncio.create_task(check_and_notify_interrupted_checkpoints(self))
            logger.info("Launched Interrupted Indexer Checkpoints detector.")
        except Exception as e:
            logger.warning(f"Could not launch indexer checkpoint checker: {e}")

        # 11. Start Auto-Gift Scheduled Drip Feed Queue Worker
        try:
            from plugins.gifts import start_gift_queue_worker
            start_gift_queue_worker(self)
            logger.info("Launched Auto-Gift Scheduled Drip Feed Queue Worker.")
        except Exception as e:
            logger.warning(f"Could not launch gift queue worker: {e}")

        # 12. Initialize Flixify Store Catalog
        try:
            from database.store import init_default_store_items
            asyncio.create_task(init_default_store_items())
            logger.info("Initialized Flixify Store Catalog.")
        except Exception as e:
            logger.warning(f"Could not initialize store catalog: {e}")

        # 13. Channel Access Auto-Eviction Worker (Runs Every 10 Minutes)
        try:
            async def _channel_eviction_loop():
                while True:
                    try:
                        await asyncio.sleep(600)
                        from database.channel_access import check_and_evict_expired_channel_members
                        evicted = await check_and_evict_expired_channel_members(self)
                        if evicted > 0:
                            logger.info(f"Channel Eviction Worker: evicted {evicted} expired members.")
                    except asyncio.CancelledError:
                        break
                    except Exception as e_evict:
                        logger.debug(f"Channel eviction loop notice: {e_evict}")

            asyncio.create_task(_channel_eviction_loop())
            logger.info("Launched Channel Access Auto-Eviction Worker.")
        except Exception as e:
            logger.warning(f"Could not launch channel eviction loop: {e}")

    async def stop(self, *args):
        try:
            from utils.downloader import purge_stale_temp_downloads
            purge_stale_temp_downloads()
        except Exception:
            pass
        await super().stop()
        logger.info("Bot has stopped.")

if __name__ == "__main__":
    if not Config.API_ID or not Config.API_HASH or not Config.BOT_TOKEN:
        logger.error("Missing mandatory credentials in environment! Please configure API_ID, API_HASH, and BOT_TOKEN.")
        sys.exit(1)

    # Single-Instance Lock to prevent duplicate broadcasts and port 8080 conflicts
    _lock_handle = None
    if sys.platform != "win32":
        lock_path = "/tmp/autofilterbot_master.lock"
        try:
            import fcntl
            _lock_handle = open(lock_path, "w")
            fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_handle.write(str(os.getpid()))
            _lock_handle.flush()
        except (IOError, BlockingIOError):
            old_pid = None
            is_alive = False
            try:
                if os.path.exists(lock_path):
                    with open(lock_path, "r") as f:
                        old_pid = int(f.read().strip())
                    if old_pid and old_pid != os.getpid():
                        os.kill(old_pid, 0)
                        is_alive = True
            except Exception:
                is_alive = False

            if not is_alive:
                try:
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                    _lock_handle = open(lock_path, "w")
                    fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    _lock_handle.write(str(os.getpid()))
                    _lock_handle.flush()
                except Exception:
                    pass
            else:
                logger.error(
                    f"❌ CRITICAL CONFLICT DETECTED: Another instance of AutoFilterBot (PID {old_pid}) is already running! "
                    f"To fix, run 'kill -9 {old_pid}' or 'pkill -9 -f bot.py' in VPS terminal."
                )
                sys.exit(0)

    bot = Bot()
    bot.run()
