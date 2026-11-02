import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self._client = None
        self._db = None
        self._client2 = None
        self._db2 = None

    def connect(self):
        if not self._client and Config.DATABASE_URI:
            try:
                self._client = AsyncIOMotorClient(Config.DATABASE_URI)
                self._db = self._client[Config.DATABASE_NAME]
                logger.info(f"Connected to Primary MongoDB database: {Config.DATABASE_NAME}")
            except Exception as e:
                logger.error(f"Failed to connect to Primary MongoDB: {e}")

        # Connect secondary cluster if URI is configured (Multi-DB sharding)
        sec_uri = getattr(Config, "SECONDARY_DATABASE_URI", "")
        if not self._client2 and sec_uri:
            try:
                self._client2 = AsyncIOMotorClient(sec_uri)
                sec_db_name = getattr(Config, "SECONDARY_DATABASE_NAME", "AutoFilterBot")
                self._db2 = self._client2[sec_db_name]
                logger.info(f"Connected to Secondary MongoDB database: {sec_db_name}")
            except Exception as e:
                logger.error(f"Failed to connect to Secondary MongoDB: {e}")

    @property
    def has_secondary(self) -> bool:
        if self._db2 is None and getattr(Config, "SECONDARY_DATABASE_URI", ""):
            self.connect()
        return self._db2 is not None

    @property
    def db(self):
        if self._db is None:
            self.connect()
        return self._db

    @property
    def db2(self):
        if self._db2 is None and getattr(Config, "SECONDARY_DATABASE_URI", ""):
            self.connect()
        return self._db2

    @property
    def files(self):
        return self.db[Config.COLLECTION_NAME]

    @property
    def files_secondary(self):
        if self.has_secondary:
            return self.db2[Config.COLLECTION_NAME]
        return None

    @property
    def all_files_collections(self):
        cols = [self.files]
        if self.has_secondary:
            cols.append(self.files_secondary)
        return cols

    @property
    def users(self):
        return self.db["users"]

    @property
    def chats(self):
        return self.db["chats"]

    @property
    def verify(self):
        return self.db["verifications"]

    @property
    def filters(self):
        return self.db["manual_filters"]

    @property
    def shorteners(self):
        return self.db["multi_shorteners"]

    @property
    def requests(self):
        return self.db["movie_requests"]

    @property
    def share_links(self):
        return self.db["share_links"]

    @property
    def batches(self):
        return self.db["batches"]

    @property
    def poster_settings(self):
        return self.db["poster_settings"]

    @property
    def dl_stats(self):
        return self.db["downloader_stats"]

    @property
    def settings(self):
        return self.db["bot_settings"]

mongo = MongoDB()

async def get_bot_setting(key: str, default=None):
    """Retrieve global bot setting from MongoDB with fallback to default."""
    try:
        doc = await mongo.settings.find_one({"_id": key})
        if doc and "value" in doc:
            return doc["value"]
    except Exception as e:
        logger.debug(f"Error fetching bot setting {key}: {e}")
    return default

async def set_bot_setting(key: str, value) -> bool:
    """Store or update global bot setting in MongoDB."""
    try:
        await mongo.settings.update_one(
            {"_id": key},
            {"$set": {"value": value}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error saving bot setting {key}: {e}")
        return False

async def load_dynamic_settings():
    """Hydrate in-memory Config attributes from persistent MongoDB bot_settings on bot startup."""
    try:
        from config import Config

        # Mapping: MongoDB _id key -> (Config attribute name, type caster)
        settings_map = {
            "shortener_enabled": ("SHORTENER_ENABLED", lambda v: bool(v)),
            "enable_streaming": ("ENABLE_STREAMING", lambda v: bool(v)),
            "enable_web_download": ("ENABLE_WEB_DOWNLOAD", lambda v: bool(v)),
            "start_pic": ("START_PIC", lambda v: str(v)),
            "web_url": ("WEB_URL", lambda v: str(v).rstrip("/")),
            "stream_url": ("STREAM_URL", lambda v: str(v).rstrip("/")),
            "tmdb_api_key": ("TMDB_API_KEY", lambda v: str(v)),
            "tmdb_read_access_token": ("TMDB_READ_ACCESS_TOKEN", lambda v: str(v)),
            "target_write_db": ("TARGET_WRITE_DB", lambda v: str(v)),
            "shortener_rotation": ("SHORTENER_ROTATION", lambda v: str(v)),
            "tutorial_url": ("TUTORIAL_URL", lambda v: str(v)),
            "stream_new_tag_days": ("STREAM_NEW_TAG_DAYS", lambda v: int(v)),
        }

        async for doc in mongo.settings.find({}):
            key = doc.get("_id")
            val = doc.get("value")
            if key in settings_map and val is not None:
                attr_name, caster = settings_map[key]
                try:
                    setattr(Config, attr_name, caster(val))
                except Exception as cast_err:
                    logger.warning(f"Failed to cast dynamic setting '{key}' = {val}: {cast_err}")

        logger.info(
            f"⚡ Persistent settings loaded from MongoDB: "
            f"SHORTENER_ENABLED={Config.SHORTENER_ENABLED}, "
            f"ENABLE_STREAMING={Config.ENABLE_STREAMING}, "
            f"ENABLE_WEB_DOWNLOAD={getattr(Config, 'ENABLE_WEB_DOWNLOAD', False)}, "
            f"WEB_URL={Config.WEB_URL or 'None'}"
        )
    except Exception as e:
        logger.error(f"Error loading dynamic settings from MongoDB: {e}")

async def init_indexes():
    """Ensure database indexes exist for ultra-fast query lookups and automatic TTL cleanup."""
    try:
        # Files indexes
        await mongo.files.create_index("file_unique_id", unique=True)
        await mongo.files.create_index([("file_name", "text")])
        await mongo.files.create_index("file_name")
        await mongo.files.create_index([("created_at", -1)])

        # Users and Chats unique indexes
        await mongo.users.create_index("user_id", unique=True)
        await mongo.chats.create_index("chat_id", unique=True)

        # Verification tokens with automatic MongoDB TTL expiration
        await mongo.verify.create_index("token", unique=True)
        await mongo.verify.create_index("expires_at", expireAfterSeconds=0)

        # Manual filters index
        await mongo.filters.create_index([("chat_id", 1), ("keyword", 1)], unique=True)

        # Multi-shorteners index
        await mongo.shorteners.create_index("domain", unique=True)

        # Movie Requests index
        await mongo.requests.create_index("request_id", unique=True)
        await mongo.requests.create_index("user_id")

        # Time-based and One-time Share Links with MongoDB TTL cleanup
        await mongo.share_links.create_index("token", unique=True)
        await mongo.share_links.create_index("expire_at", expireAfterSeconds=0)

        # File Store Batches index
        try:
            await mongo.batches.create_index("batch_id", unique=True)
            await mongo.batches.create_index("created_at")
            await mongo.batches.create_index("expire_at", expireAfterSeconds=0)
        except Exception:
            pass

        # Poster Studio User/Channel Settings index
        await mongo.poster_settings.create_index("user_id", unique=True)

        # Search Demands index with automatic 30-Day TTL cleanup
        try:
            await mongo.db["search_demand"].create_index("query", unique=True)
            await mongo.db["search_demand"].create_index("last_searched", expireAfterSeconds=30 * 86400)
        except Exception:
            pass

        # Secondary MongoDB files indexes (if secondary cluster is connected)
        if mongo.has_secondary:
            try:
                await mongo.files_secondary.create_index("file_unique_id", unique=True)
                await mongo.files_secondary.create_index([("file_name", "text")])
                await mongo.files_secondary.create_index("file_name")
                await mongo.files_secondary.create_index([("created_at", -1)])
                logger.info("Secondary MongoDB files indexes successfully initialized.")
            except Exception as se:
                logger.warning(f"Error creating secondary MongoDB indexes: {se}")

        logger.info("MongoDB indexes successfully verified and initialized.")
    except Exception as e:
        logger.warning(f"Error initializing MongoDB indexes (possibly URI not configured yet): {e}")
