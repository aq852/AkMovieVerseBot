import re
import datetime
import logging
from typing import Optional, Dict, Any, Tuple
from database.mongo import mongo

logger = logging.getLogger(__name__)

DURATION_REGEX = re.compile(r"^(\d+)\s*([hdmyw])$", re.IGNORECASE)


def parse_duration_string(dur_str: str) -> Optional[int]:
    """Parse duration string like '24h', '3d', '7d', '1w', '30d' into seconds.
    Returns seconds or None if invalid.
    """
    match = DURATION_REGEX.match(dur_str.strip())
    if not match:
        return None

    val = int(match.group(1))
    unit = match.group(2).lower()

    if unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    elif unit == "w":
        return val * 7 * 86400
    elif unit == "m":
        return val * 30 * 86400
    elif unit == "y":
        return val * 365 * 86400
    return None


async def set_sponsor_ad(
    text: str,
    url: str,
    duration_str: str,
    duration_seconds: int,
    created_by: int = 0
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Create or overwrite the active sponsor advertisement.
    Returns (success, message, ad_doc).
    """
    clean_text = text.strip()
    clean_url = url.strip()

    if not clean_text or len(clean_text) < 2 or len(clean_text) > 120:
        return False, "Ad text must be between 2 and 120 characters.", None

    if not clean_url.startswith(("http://", "https://", "tg://")):
        return False, "URL must start with http://, https://, or tg://", None

    if duration_seconds <= 0 or duration_seconds > (365 * 86400):
        return False, "Duration must be between 1 hour and 365 days.", None

    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(seconds=duration_seconds)

    doc = {
        "text": clean_text,
        "url": clean_url,
        "duration_str": duration_str.lower(),
        "created_at": now,
        "expires_at": expires_at,
        "is_active": True,
        "impressions": 0,
        "created_by": created_by
    }

    try:
        # Mark all prior active ads as inactive
        await mongo.db["sponsor_ads"].update_many(
            {"is_active": True},
            {"$set": {"is_active": False}}
        )

        res = await mongo.db["sponsor_ads"].insert_one(doc)
        doc["_id"] = res.inserted_id
        logger.info(f"Sponsor ad activated: '{clean_text}' for {duration_str} (expires {expires_at})")
        return True, "Sponsor ad activated successfully.", doc
    except Exception as e:
        logger.error(f"Error setting sponsor ad: {e}")
        return False, f"Database error: {e}", None


async def get_active_sponsor_ad(track_impression: bool = True) -> Optional[Dict[str, Any]]:
    """Retrieve currently active sponsor advertisement.
    Automatically deactivates expired ads in real time.
    """
    try:
        ad = await mongo.db["sponsor_ads"].find_one({"is_active": True})
        if not ad:
            return None

        now = datetime.datetime.utcnow()
        expires_at = ad.get("expires_at")

        if expires_at and expires_at < now:
            # Auto-expire immediately
            await mongo.db["sponsor_ads"].update_one(
                {"_id": ad["_id"]},
                {"$set": {"is_active": False}}
            )
            logger.info(f"Sponsor ad '{ad.get('text')}' has expired and was auto-deactivated.")
            return None

        if track_impression:
            # Increment impression count non-blocking
            await mongo.db["sponsor_ads"].update_one(
                {"_id": ad["_id"]},
                {"$inc": {"impressions": 1}}
            )

        return ad
    except Exception as e:
        logger.error(f"Error getting active sponsor ad: {e}")
        return None


async def delete_sponsor_ad() -> bool:
    """Manually deactivate/delete currently active sponsor ad."""
    try:
        res = await mongo.db["sponsor_ads"].update_many(
            {"is_active": True},
            {"$set": {"is_active": False, "revoked_at": datetime.datetime.utcnow()}}
        )
        return res.modified_count > 0
    except Exception as e:
        logger.error(f"Error deleting sponsor ad: {e}")
        return False


async def get_ad_stats() -> Optional[Dict[str, Any]]:
    """Get active ad statistics for admin dashboard."""
    try:
        ad = await mongo.db["sponsor_ads"].find_one({"is_active": True})
        if not ad:
            # Fetch latest inactive/expired ad for history preview
            latest = await mongo.db["sponsor_ads"].find_one(
                {},
                sort=[("created_at", -1)]
            )
            return latest

        now = datetime.datetime.utcnow()
        expires_at = ad.get("expires_at")
        if expires_at and expires_at < now:
            await mongo.db["sponsor_ads"].update_one(
                {"_id": ad["_id"]},
                {"$set": {"is_active": False}}
            )
            ad["is_active"] = False

        return ad
    except Exception as e:
        logger.error(f"Error getting ad stats: {e}")
        return None


async def clean_expired_ads(keep_days: int = 7) -> int:
    """Delete expired inactive ads older than keep_days to keep database pristine."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=keep_days)
    try:
        res = await mongo.db["sponsor_ads"].delete_many({
            "is_active": False,
            "expires_at": {"$lt": cutoff}
        })
        logger.info(f"Housekeeping: Purged {res.deleted_count} old expired sponsor ads.")
        return res.deleted_count
    except Exception as e:
        logger.error(f"Error purging expired ads: {e}")
        return 0
