import uuid
import datetime
import logging
from config import Config
from database.mongo import mongo
from database.users import is_premium

logger = logging.getLogger(__name__)

async def create_verify_token(user_id: int, file_id: str, short_link: str = "", shortener_name: str = "") -> str:
    """Generate a temporary verification token with automated TTL expiration."""
    try:
        token = str(uuid.uuid4()).replace("-", "")[:16]
        now = datetime.datetime.utcnow()
        # Token itself valid for 15 minutes to complete
        token_doc = {
            "token": token,
            "user_id": user_id,
            "file_id": file_id,
            "short_link": short_link,
            "shortener_name": shortener_name,
            "created_at": now,
            "expires_at": now + datetime.timedelta(minutes=15)
        }
        await mongo.verify.insert_one(token_doc)
        return token
    except Exception as e:
        logger.error(f"Error creating verification token for {user_id}: {e}")
        return ""


async def update_token_shortlink(token: str, short_link: str, shortener_name: str = "") -> bool:
    """Update stored shortlink destination and provider name for a token."""
    try:
        res = await mongo.verify.update_one(
            {"token": token},
            {"$set": {"short_link": short_link, "shortener_name": shortener_name}}
        )
        return res.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating token {token} shortlink: {e}")
        return False


async def get_verify_token_info(token: str) -> dict | None:
    """Retrieve token document for the web fast-redirect gateway."""
    try:
        return await mongo.verify.find_one({"token": token})
    except Exception as e:
        logger.error(f"Error finding verify token {token}: {e}")
        return None


async def verify_user_token(token: str) -> tuple[bool, str, int]:
    """Validate token, extend user access for VERIFY_EXPIRE duration, and return pending file_id."""
    try:
        doc = await mongo.verify.find_one({"token": token})
        if not doc:
            return False, "", 0

        user_id = doc["user_id"]
        file_id = doc.get("file_id", "")
        duration = Config.VERIFY_EXPIRE

        # Set user verified_until
        verified_until = datetime.datetime.utcnow() + datetime.timedelta(seconds=duration)
        await mongo.users.update_one(
            {"user_id": user_id},
            {"$set": {"verified_until": verified_until}},
            upsert=True
        )

        # Delete token after successful verification
        await mongo.verify.delete_one({"token": token})
        return True, file_id, user_id
    except Exception as e:
        logger.error(f"Error validating verification token {token}: {e}")
        return False, "", 0


async def is_user_verified(user_id: int) -> bool:
    """Check if user has an active 24h verification or is exempt (admin / premium / no verify gateway configured)."""
    try:
        # Admins always exempt
        if Config.is_admin(user_id):
            return True

        # Premium VIP users always exempt
        if await is_premium(user_id):
            return True

        # If neither shorteners nor clean 3s web gateway is configured, exempt everyone
        verification_required = Config.SHORTENER_ENABLED or bool(getattr(Config, "WEB_URL", ""))
        if not verification_required:
            return True

        user = await mongo.users.find_one({"user_id": user_id}, {"verified_until": 1})
        if not user or not user.get("verified_until"):
            return False

        v_until = user["verified_until"]
        if hasattr(v_until, "replace") and getattr(v_until, "tzinfo", None):
            v_until = v_until.replace(tzinfo=None)
        return v_until > datetime.datetime.utcnow()
    except Exception as e:
        logger.error(f"Error checking verification status for {user_id}: {e}")
        return False
