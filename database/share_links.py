import datetime
import uuid
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

def parse_duration(duration_str: str) -> int | None:
    """Parse time string like '10m', '1h', '24h', '3d' into seconds."""
    if not duration_str:
        return None
    duration_str = duration_str.lower().strip()
    try:
        if duration_str.endswith("m"):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith("h"):
            return int(duration_str[:-1]) * 3600
        elif duration_str.endswith("d"):
            return int(duration_str[:-1]) * 86400
        elif duration_str.isdigit():
            # default to minutes if bare number
            return int(duration_str) * 60
    except Exception:
        return None
    return None


async def create_share_link(
    file_unique_id: str,
    created_by: int,
    duration_seconds: int | None = None,
    max_uses: int | None = 1
) -> dict:
    """
    Create a time-based and/or single-use file share link.
    Returns the created link document including the unique access token.
    """
    token = uuid.uuid4().hex[:12]
    now = datetime.datetime.utcnow()
    expire_at = now + datetime.timedelta(seconds=duration_seconds) if duration_seconds else None

    doc = {
        "token": token,
        "file_unique_id": file_unique_id,
        "created_by": created_by,
        "created_at": now,
        "expire_at": expire_at,
        "duration_seconds": duration_seconds,
        "max_uses": max_uses, # 1 for one-time, >1 for limited, None for unlimited
        "claimed_count": 0,
        "claimed_by": []
    }
    try:
        await mongo.share_links.insert_one(doc)
        return doc
    except Exception as e:
        logger.error(f"Error creating share link: {e}")
        return {}


async def get_share_link(token: str) -> dict | None:
    """Retrieve share link document by token."""
    try:
        return await mongo.share_links.find_one({"token": token})
    except Exception as e:
        logger.error(f"Error fetching share link {token}: {e}")
        return None


async def claim_share_link(token: str, user_id: int) -> tuple[bool, str, dict]:
    """
    Validate and claim a share link.
    Returns (success, reason_or_status, link_doc).
    Reasons: 'not_found', 'expired', 'limit_reached', 'success'.
    """
    try:
        doc = await mongo.share_links.find_one({"token": token})
        if not doc:
            return False, "not_found", {}

        now = datetime.datetime.utcnow()
        # 1. Check time-based expiration
        if doc.get("expire_at") and now > doc["expire_at"]:
            return False, "expired", doc

        # 2. Check maximum uses limit (One-time or N-times)
        max_uses = doc.get("max_uses")
        claimed_count = doc.get("claimed_count", 0)
        if max_uses is not None and claimed_count >= max_uses:
            return False, "limit_reached", doc

        # 3. Valid claim: record user and increment counter
        await mongo.share_links.update_one(
            {"token": token},
            {
                "$inc": {"claimed_count": 1},
                "$push": {"claimed_by": {"user_id": user_id, "claimed_at": now}}
            }
        )
        return True, "success", doc

    except Exception as e:
        logger.error(f"Error claiming share link {token}: {e}")
        return False, "error", {}
