import logging
from database.mongo import mongo
from config import Config

logger = logging.getLogger(__name__)

async def get_poster_settings(user_id: int) -> dict:
    """Retrieve custom poster studio settings for a user or admin with dual-cluster resilience."""
    try:
        doc = await mongo.poster_settings.find_one({"user_id": int(user_id)})
        if doc:
            return doc
        if mongo.has_secondary:
            doc2 = await mongo.db2["poster_settings"].find_one({"user_id": int(user_id)})
            if doc2:
                return doc2
        return {}
    except Exception as e:
        logger.error(f"Error fetching poster settings for {user_id}: {e}")
        return {}


async def get_poster_brand(user_id: int) -> str:
    """Get the custom branding/watermark text configured by user or return default."""
    try:
        settings = await get_poster_settings(user_id)
        brand = settings.get("brand")
        if brand and str(brand).strip():
            return str(brand).strip()
    except Exception as e:
        logger.error(f"Error retrieving poster brand for {user_id}: {e}")

    return Config.DEFAULT_POSTER_BRAND


async def set_poster_brand(user_id: int, brand: str) -> bool:
    """Save or update custom watermark/branding for a user or admin with dual-cluster sync."""
    try:
        clean_brand = str(brand).strip()[:40]
        await mongo.poster_settings.update_one(
            {"user_id": int(user_id)},
            {"$set": {"brand": clean_brand}},
            upsert=True
        )
        if mongo.has_secondary:
            try:
                await mongo.db2["poster_settings"].update_one(
                    {"user_id": int(user_id)},
                    {"$set": {"brand": clean_brand}},
                    upsert=True
                )
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Error saving poster brand for {user_id}: {e}")
        return False


async def get_poster_channel(user_id: int) -> int | None:
    """Get the destination channel ID configured by admin for direct 1-click publishing."""
    try:
        settings = await get_poster_settings(user_id)
        return settings.get("publish_channel")
    except Exception as e:
        logger.error(f"Error getting poster channel for {user_id}: {e}")
        return None


async def set_poster_channel(user_id: int, channel_id: int) -> bool:
    """Configure or update the destination channel for direct poster publishing with dual-cluster sync."""
    try:
        await mongo.poster_settings.update_one(
            {"user_id": int(user_id)},
            {"$set": {"publish_channel": int(channel_id)}},
            upsert=True
        )
        if mongo.has_secondary:
            try:
                await mongo.db2["poster_settings"].update_one(
                    {"user_id": int(user_id)},
                    {"$set": {"publish_channel": int(channel_id)}},
                    upsert=True
                )
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Error setting poster channel for {user_id}: {e}")
        return False


async def get_tmdb_credentials() -> dict:
    """Retrieve system TMDB credentials from database if configured with dual-cluster resilience."""
    try:
        doc = await mongo.poster_settings.find_one({"system_key": "tmdb_credentials"})
        if doc and (doc.get("api_key") or doc.get("token")):
            return doc
        if mongo.has_secondary:
            doc2 = await mongo.db2["poster_settings"].find_one({"system_key": "tmdb_credentials"})
            if doc2 and (doc2.get("api_key") or doc2.get("token")):
                return doc2
        return doc or {}
    except Exception as e:
        logger.error(f"Error getting TMDB credentials: {e}")
        return {}


async def set_tmdb_credentials(api_key: str = None, token: str = None) -> bool:
    """Store system TMDB API Key and Read Access Token in MongoDB with dual-cluster sync."""
    try:
        update_data = {}
        if api_key is not None:
            update_data["api_key"] = api_key.strip()
        if token is not None:
            update_data["token"] = token.strip()

        if update_data:
            await mongo.poster_settings.update_one(
                {"system_key": "tmdb_credentials"},
                {"$set": update_data},
                upsert=True
            )
            if mongo.has_secondary:
                try:
                    await mongo.db2["poster_settings"].update_one(
                        {"system_key": "tmdb_credentials"},
                        {"$set": update_data},
                        upsert=True
                    )
                except Exception:
                    pass
        return True
    except Exception as e:
        logger.error(f"Error setting TMDB credentials: {e}")
        return False
