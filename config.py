import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

class Config:
    START_TIME = time.time()
    # Telegram API Credentials
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
    MASTER_CLIENT = None

    # MongoDB Credentials
    DATABASE_URI = os.environ.get("DATABASE_URI", "")
    DATABASE_NAME = os.environ.get("DATABASE_NAME", "AutoFilterBot")
    COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "telegram_files")

    # Secondary MongoDB (Optional - Multi-Cluster Sharding for High Storage Scaling)
    SECONDARY_DATABASE_URI = os.environ.get("SECONDARY_DATABASE_URI", "")
    SECONDARY_DATABASE_NAME = os.environ.get("SECONDARY_DATABASE_NAME", "AutoFilterBot")
    PRIMARY_DB_MAX_SIZE_MB = int(os.environ.get("PRIMARY_DB_MAX_SIZE_MB", "440"))

    # Admins and Channels
    ADMINS = [int(admin) for admin in os.environ.get("ADMINS", "").split() if admin.isdigit()]
    CHANNELS = [int(ch) for ch in os.environ.get("CHANNELS", "").split() if ch.lstrip('-').isdigit()]
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1002247400551"))
    UPDATES_CHANNEL = int(os.environ.get("UPDATES_CHANNEL", "-1003537939374"))
    AUTO_POST_ENABLED = os.environ.get("AUTO_POST_ENABLED", "True").lower() == "true"
    AUTO_POST_DELAY = int(os.environ.get("AUTO_POST_DELAY", "120"))  # 2 minutes buffering window
    FORCE_SUB_CHANNELS = [ch.strip() for ch in os.environ.get("FORCE_SUB_CHANNELS", "").split() if ch.strip()]
    AUTO_APPROVE = os.environ.get("AUTO_APPROVE", "True").lower() == "true"
    AUTO_APPROVE_CHANNELS = [int(ch) for ch in os.environ.get("AUTO_APPROVE_CHANNELS", "").split() if ch.lstrip('-').isdigit()]

    # URL Shortener & Monetization Settings
    SHORTENER_ENABLED = os.environ.get("SHORTENER_ENABLED", "True").lower() == "true"
    SHORTENER_URL = os.environ.get("SHORTENER_URL", "linkshortify.com")
    SHORTENER_API = os.environ.get("SHORTENER_API", "")

    # Multi-Shortener Rotation & Fallback (Secondary & Tertiary)
    SHORTENER_URL2 = os.environ.get("SHORTENER_URL2", "")
    SHORTENER_API2 = os.environ.get("SHORTENER_API2", "")
    SHORTENER_URL3 = os.environ.get("SHORTENER_URL3", "")
    SHORTENER_API3 = os.environ.get("SHORTENER_API3", "")
    SHORTENER_ROTATION = os.environ.get("SHORTENER_ROTATION", "round_robin").lower()  # 'round_robin' or 'random'

    VERIFY_EXPIRE = int(os.environ.get("VERIFY_EXPIRE", "86400"))  # Default 24 hours in seconds
    TUTORIAL_URL = os.environ.get("TUTORIAL_URL", "https://t.me/how_to_open_link_ak/17")
    _raw_channel_url = os.environ.get("CHANNEL_URL", "https://t.me/AkMovieVerse").strip().rstrip("/")
    if _raw_channel_url.startswith("http://") or _raw_channel_url.startswith("https://"):
        CHANNEL_URL = "" if re.search(r"t\.me/-100\d+", _raw_channel_url) else _raw_channel_url
    elif _raw_channel_url.startswith("@") or (_raw_channel_url and not _raw_channel_url.lstrip("-").isdigit()):
        CHANNEL_URL = f"https://t.me/{_raw_channel_url.lstrip('@')}"
    else:
        CHANNEL_URL = ""

    # UI & Search Preferences
    ENABLE_IMDB = os.environ.get("ENABLE_IMDB", "True").lower() == "true"
    ENABLE_POSTER = os.environ.get("ENABLE_POSTER", "False").lower() == "true"
    DEFAULT_POSTER_BRAND = os.environ.get("DEFAULT_POSTER_BRAND", "Akmovieverse")
    IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
    TMDB_READ_ACCESS_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN", "")
    START_PIC = os.environ.get("START_PIC", "https://api.aniwallpaper.workers.dev/random")
    SINGLE_BUTTON = os.environ.get("SINGLE_BUTTON", "True").lower() == "true"
    AUTO_DELETE_TIME = int(os.environ.get("AUTO_DELETE_TIME", "300"))  # 5 minutes (Search Results)
    FILE_AUTO_DELETE_TIME = int(os.environ.get("FILE_AUTO_DELETE_TIME", "300"))  # 5 minutes (Delivered Files)
    PROTECT_CONTENT = os.environ.get("PROTECT_CONTENT", "False").lower() == "true"
    SHOW_NUM_BUTTONS = os.environ.get("SHOW_NUM_BUTTONS", "False").lower() == "true"

    # Web Server & Fast-Redirect Gateway URL (Koyeb, Render, VPS or Custom Domain)
    PORT = int(os.environ.get("PORT", "8080"))
    WEB_URL = os.environ.get("WEB_URL", "").rstrip("/")

    # Fast Streaming & Web Player Settings
    ENABLE_STREAMING = os.environ.get("ENABLE_STREAMING", "True").lower() == "true"
    ENABLE_WEB_DOWNLOAD = os.environ.get("ENABLE_WEB_DOWNLOAD", "True").lower() == "true"
    MAX_CONCURRENT_STREAMS = int(os.environ.get("MAX_CONCURRENT_STREAMS", "30"))
    STREAM_URL = os.environ.get("STREAM_URL", "").rstrip("/") or os.environ.get("WEB_URL", "").rstrip("/")
    STREAM_NEW_TAG_DAYS = int(os.environ.get("STREAM_NEW_TAG_DAYS", "2"))

    # VIP Payment & Portal Settings
    UPI_ID = os.environ.get("UPI_ID", "")
    UPI_QR_URL = os.environ.get("UPI_QR_URL", "")
    SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/AK_ownerbot")
    USDT_TRC20 = os.environ.get("USDT_TRC20", "")
    PLANS_WEB_URL = os.environ.get("PLANS_WEB_URL", "https://premiumplans.vercel.app/#plans")

    # File Store & Batch System Settings
    FILE_STORE_CHANNEL = int(os.environ.get("FILE_STORE_CHANNEL", "-1004384430212"))
    FILE_STORE_USER_DAILY_LIMIT = int(os.environ.get("FILE_STORE_USER_DAILY_LIMIT", "10"))
    FILE_STORE_USERS_ENABLED = os.environ.get("FILE_STORE_USERS_ENABLED", "True").lower() == "true"

    # Universal Downloader & Silent Dump Settings (Admin Only)
    DOWNLOADER_ACCESS = os.environ.get("DOWNLOADER_ACCESS", "admin").lower()  # "admin"
    DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", os.environ.get("LOG_CHANNEL", "0") or "0"))
    DOWNLOADER_MAX_SIZE = int(os.environ.get("DOWNLOADER_MAX_SIZE", "100"))  # in MB
    DOWNLOADER_COOLDOWN = int(os.environ.get("DOWNLOADER_COOLDOWN", "30"))  # in seconds
    COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return user_id in cls.ADMINS
