import secrets
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple
from database.mongo import mongo

logger = logging.getLogger(__name__)

# Default high-resolution gift / reward box poster (Luxury 3D Gold Ribbon Gift Box)
DEFAULT_GIFT_POSTER = "https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=1200&q=80"


async def create_gift(
    title: str,
    file_type: str = "single",
    file_doc: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
    total_files: int = 1,
    total_size: int = 0,
    poster_url: Optional[str] = None,
    channels: Optional[List[str]] = None,
    require_shortener: bool = False,
    is_vip_only: bool = False,
    protect_content: bool = True,
    auto_delete_seconds: int = 300,
    max_claims: int = 50,
    duration_seconds: int = 172800,  # Default 48h
    created_by: int = 0
) -> Dict[str, Any]:
    """Create a new gift reward campaign."""
    gift_id = secrets.token_hex(4).lower()  # 8 characters, e.g. "a9f2bc10"
    now = datetime.datetime.utcnow()
    expires_at = (now + datetime.timedelta(seconds=duration_seconds)) if duration_seconds > 0 else None

    clean_channels = []
    if channels:
        for ch in channels:
            ch_str = str(ch).strip()
            if ch_str and ch_str not in clean_channels:
                clean_channels.append(ch_str)

    doc = {
        "gift_id": gift_id,
        "title": title.strip() or "Exclusive Gift Reward",
        "file_type": file_type,  # "single" or "batch"
        "file_doc": file_doc or {},
        "batch_id": batch_id or "",
        "total_files": total_files,
        "total_size": total_size,
        "poster_url": poster_url.strip() if poster_url else DEFAULT_GIFT_POSTER,
        "channels": clean_channels,
        "require_shortener": bool(require_shortener),
        "is_vip_only": bool(is_vip_only),
        "protect_content": bool(protect_content),
        "auto_delete_seconds": auto_delete_seconds,
        "max_claims": max_claims,
        "claimed_count": 0,
        "claimed_users": [],
        "views_count": 0,
        "is_active": True,
        "created_at": now,
        "expires_at": expires_at,
        "created_by": created_by
    }

    try:
        await mongo.db["gift_rewards"].insert_one(doc)
        logger.info(f"Gift {gift_id} created by {created_by} (claims={max_claims}, vip_only={is_vip_only})")
        return doc
    except Exception as e:
        logger.error(f"Error inserting gift doc: {e}")
        return {}


async def get_gift(gift_id: str) -> Optional[Dict[str, Any]]:
    """Fetch gift document by gift_id. Automatically marks expired gifts as inactive."""
    try:
        doc = await mongo.db["gift_rewards"].find_one({"gift_id": gift_id})
        if not doc:
            return None

        # Check expiry in real-time
        now = datetime.datetime.utcnow()
        expires_at = doc.get("expires_at")
        if expires_at and expires_at < now and doc.get("is_active"):
            await mongo.db["gift_rewards"].update_one(
                {"gift_id": gift_id},
                {"$set": {"is_active": False}}
            )
            doc["is_active"] = False

        return doc
    except Exception as e:
        logger.error(f"Error fetching gift {gift_id}: {e}")
        return None


async def increment_gift_views(gift_id: str) -> None:
    """Increment view counter when gift card is opened."""
    try:
        await mongo.db["gift_rewards"].update_one(
            {"gift_id": gift_id},
            {"$inc": {"views_count": 1}}
        )
    except Exception as e:
        logger.debug(f"Error incrementing views for gift {gift_id}: {e}")


async def record_gift_claim(gift_id: str, user_id: int) -> Tuple[bool, str]:
    """Atomically claim a gift for a user. Enforces stock limits and 1-claim per user."""
    gift = await get_gift(gift_id)
    if not gift:
        return False, "Gift not found."

    if not gift.get("is_active"):
        return False, "This gift campaign has expired or been revoked."

    now = datetime.datetime.utcnow()
    expires_at = gift.get("expires_at")
    if expires_at and expires_at < now:
        return False, "This gift has expired."

    claimed_users = gift.get("claimed_users", [])
    if user_id in claimed_users:
        return False, "You have already claimed this gift reward!"

    max_claims = gift.get("max_claims", 0)
    claimed_count = gift.get("claimed_count", 0)

    if max_claims > 0 and claimed_count >= max_claims:
        return False, "All gift rewards have been claimed by lucky users!"

    # Atomic update query
    query = {
        "gift_id": gift_id,
        "is_active": True,
        "claimed_users": {"$ne": user_id}
    }
    if max_claims > 0:
        query["claimed_count"] = {"$lt": max_claims}

    try:
        res = await mongo.db["gift_rewards"].update_one(
            query,
            {
                "$inc": {"claimed_count": 1},
                "$push": {"claimed_users": user_id}
            }
        )
        if res.modified_count > 0:
            # Check if now exhausted
            if max_claims > 0 and (claimed_count + 1) >= max_claims:
                logger.info(f"Gift {gift_id} reached max claims ({max_claims}) and is now exhausted.")
            return True, "Success"
        return False, "Claim failed. Either all gifts are taken or you already claimed."
    except Exception as e:
        logger.error(f"Error claiming gift {gift_id} for user {user_id}: {e}")
        return False, f"Database error: {e}"


async def has_user_claimed_gift(gift_id: str, user_id: int) -> bool:
    """Check if user has already claimed this specific gift."""
    try:
        doc = await mongo.db["gift_rewards"].find_one({
            "gift_id": gift_id,
            "claimed_users": user_id
        })
        return doc is not None
    except Exception as e:
        logger.error(f"Error checking gift claim for user {user_id}: {e}")
        return False


async def delete_gift(gift_id: str) -> bool:
    """Manually revoke / deactivate an active gift."""
    try:
        res = await mongo.db["gift_rewards"].update_one(
            {"gift_id": gift_id},
            {"$set": {"is_active": False, "revoked_at": datetime.datetime.utcnow()}}
        )
        return res.modified_count > 0
    except Exception as e:
        logger.error(f"Error revoking gift {gift_id}: {e}")
        return False


async def get_all_gifts(limit: int = 50, only_active: bool = False) -> List[Dict[str, Any]]:
    """Retrieve list of gifts for admin dashboard."""
    query = {"is_active": True} if only_active else {}
    try:
        cursor = mongo.db["gift_rewards"].find(query).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error listing gifts: {e}")
        return []


# ==============================================================================
# Gift Blacklist (Global Ban from Gifts)
# ==============================================================================

async def gift_ban_user(user_id: int, reason: str = "Rule violation", banned_by: int = 0) -> bool:
    """Globally blacklist a user from claiming any gifts."""
    try:
        doc = {
            "user_id": user_id,
            "reason": reason.strip(),
            "banned_by": banned_by,
            "banned_at": datetime.datetime.utcnow()
        }
        await mongo.db["gift_blacklist"].update_one(
            {"user_id": user_id},
            {"$set": doc},
            upsert=True
        )
        logger.info(f"User {user_id} blacklisted from gifts by {banned_by} (Reason: {reason})")
        return True
    except Exception as e:
        logger.error(f"Error banning user {user_id} from gifts: {e}")
        return False


async def gift_unban_user(user_id: int) -> bool:
    """Remove a user from gift blacklist."""
    try:
        res = await mongo.db["gift_blacklist"].delete_one({"user_id": user_id})
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error unbanning user {user_id} from gifts: {e}")
        return False


async def is_gift_banned(user_id: int) -> bool:
    """Check if user is blacklisted from claiming gifts."""
    try:
        doc = await mongo.db["gift_blacklist"].find_one({"user_id": user_id})
        return doc is not None
    except Exception as e:
        logger.error(f"Error checking gift ban for {user_id}: {e}")
        return False


# ==============================================================================
# Gift Task Verification Tokens (Shortener & External Ad Bypass)
# ==============================================================================

async def create_gift_task_token(gift_id: str, user_id: int, task_type: str = "shortener") -> str:
    """Generate a unique 1-time verification token for shortener/ad task."""
    token = f"gtok_{secrets.token_hex(6)}"
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(hours=2)

    doc = {
        "token": token,
        "gift_id": gift_id,
        "user_id": user_id,
        "task_type": task_type,
        "is_verified": False,
        "created_at": now,
        "expires_at": expires_at
    }

    try:
        # Clear prior unverified tokens for this user & gift
        await mongo.db["gift_task_tokens"].delete_many({
            "gift_id": gift_id,
            "user_id": user_id,
            "task_type": task_type,
            "is_verified": False
        })
        await mongo.db["gift_task_tokens"].insert_one(doc)
        return token
    except Exception as e:
        logger.error(f"Error creating gift task token: {e}")
        return ""


async def verify_gift_task_token(token: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Verify and consume a task completion token."""
    try:
        doc = await mongo.db["gift_task_tokens"].find_one({"token": token})
        if not doc:
            return False, "Invalid or expired verification token.", None

        now = datetime.datetime.utcnow()
        if doc.get("expires_at") and doc["expires_at"] < now:
            return False, "This verification key has expired. Please try again.", None

        # Mark verified
        await mongo.db["gift_task_tokens"].update_one(
            {"token": token},
            {"$set": {"is_verified": True, "verified_at": now}}
        )
        return True, "Task verified successfully!", doc
    except Exception as e:
        logger.error(f"Error verifying gift token {token}: {e}")
        return False, f"Verification error: {e}", None


async def is_gift_task_verified(gift_id: str, user_id: int, task_type: str = "shortener") -> bool:
    """Check if user has verified the required task for this gift."""
    try:
        doc = await mongo.db["gift_task_tokens"].find_one({
            "gift_id": gift_id,
            "user_id": user_id,
            "task_type": task_type,
            "is_verified": True
        })
        return doc is not None
    except Exception as e:
        logger.error(f"Error checking gift task verification: {e}")
        return False


# ==============================================================================
# Housekeeping Auto-Clean
# ==============================================================================

async def clean_expired_gifts(keep_days: int = 14) -> int:
    """Purge stale expired gift tokens and gifts older than keep_days."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=keep_days)
    purged_total = 0
    try:
        # 1. Purge expired task tokens
        res_tokens = await mongo.db["gift_task_tokens"].delete_many({
            "expires_at": {"$lt": datetime.datetime.utcnow()}
        })
        purged_total += res_tokens.deleted_count

        # 2. Purge old inactive gifts
        res_gifts = await mongo.db["gift_rewards"].delete_many({
            "is_active": False,
            "expires_at": {"$ne": None, "$lt": cutoff}
        })
        purged_total += res_gifts.deleted_count

        logger.info(f"Housekeeping: Purged {purged_total} expired gift records.")
        return purged_total
    except Exception as e:
        logger.error(f"Error purging expired gifts: {e}")
        return purged_total
