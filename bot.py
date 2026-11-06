import sys
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
                    "🚀 **AutoFilterBot Online & Active!**\n\n"
                    f"🤖 **Bot:** @{me.username}\n"
                    f"📁 **Indexed Files:** `{files_count:,}`\n"
                    f"👤 **Total Users:** `{users_count:,}`\n"
                    f"👥 **Connected Groups:** `{chats_count:,}`\n"
                    f"⚡ **Shortener:** `{'Enabled' if Config.SHORTENER_ENABLED else 'Disabled'}`\n"
                    f"🍿 **Fast Streaming:** `{'Enabled' if Config.ENABLE_STREAMING else 'Disabled'}`\n"
                    f"☁️ **Platform:** Hydrogram MTProto / Python 3.11\n"
                    f"🌐 **Web Port:** `{Config.PORT}`"
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

    bot = Bot()
    bot.run()
