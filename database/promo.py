import re
import uuid
import datetime
import logging
from database.mongo import mongo
from database.users import add_premium

logger = logging.getLogger(__name__)

async def create_promo_code(
    code: str,
    days: int,
    max_uses: int = 1,
    expiry_days: int = 30,
    created_by: int = 0
) -> tuple[bool, str, dict | None]:
    """Create a new promotional VIP coupon code with configurable validity and maximum uses.
    Returns (success, message, promo_doc).
    """
    clean_code = re.sub(r"[^A-Za-z0-9_\-]", "", code.strip().upper())
    if not clean_code or len(clean_code) < 3 or len(clean_code) > 30:
        return False, "Code must be 3-30 alphanumeric characters.", None

    if days <= 0 or days > 3650:
        return False, "Days must be between 1 and 3650.", None

    if max_uses <= 0:
        return False, "Max uses must be at least 1.", None

    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(days=expiry_days)

    try:
        existing = await mongo.db["promo_codes"].find_one({"code": clean_code})
        if existing:
            return False, f"Promo code '{clean_code}' already exists.", None

        doc = {
            "code": clean_code,
            "days": days,
            "max_uses": max_uses,
            "claimed_count": 0,
            "claimed_by": [],
            "created_at": now,
            "expires_at": expires_at,
            "is_active": True,
            "created_by": created_by
        }
        await mongo.db["promo_codes"].insert_one(doc)
        logger.info(f"Promo code created: {clean_code} ({days} days, {max_uses} uses)")
        return True, "Promo code created successfully.", doc
    except Exception as e:
        logger.error(f"Error creating promo code {clean_code}: {e}")
        return False, f"Database error: {e}", None


async def redeem_promo_code(code: str, user_id: int) -> tuple[bool, str, int]:
    """Redeem a promo coupon code for a user and credit VIP Premium access.
    Returns (success, message, days_credited).
    """
    clean_code = re.sub(r"[^A-Za-z0-9_\-]", "", code.strip().upper())
    if not clean_code:
        return False, "Please provide a valid promo code.", 0

    now = datetime.datetime.utcnow()

    try:
        promo = await mongo.db["promo_codes"].find_one({"code": clean_code})
        if not promo:
            return False, "❌ Invalid promo code. Please double-check and try again.", 0

        if not promo.get("is_active", True):
            return False, "⚠️ This promo code is no longer active.", 0

        expires_at = promo.get("expires_at")
        if expires_at and expires_at < now:
            return False, "⏳ This promo code has expired.", 0

        max_uses = promo.get("max_uses", 1)
        claimed_count = promo.get("claimed_count", 0)
        claimed_by = promo.get("claimed_by", [])

        if user_id in claimed_by:
            return False, "⚠️ You have already redeemed this promo code!", 0

        if claimed_count >= max_uses:
            return False, "🔒 This promo code has reached its maximum claim limit.", 0

        # Atomically increment claim count and add user_id with race-condition guard
        res = await mongo.db["promo_codes"].find_one_and_update(
            {
                "code": clean_code,
                "is_active": True,
                "claimed_count": {"$lt": max_uses},
                "claimed_by": {"$ne": user_id}
            },
            {
                "$inc": {"claimed_count": 1},
                "$addToSet": {"claimed_by": user_id},
                "$set": {"last_claimed_at": now}
            },
            return_document=True
        )

        if not res:
            return False, "🔒 Could not claim code (limit reached or already redeemed).", 0

        days = promo.get("days", 1)
        seconds = days * 86400
        await add_premium(user_id, seconds)

        logger.info(f"User {user_id} redeemed promo {clean_code} for {days} days VIP.")
        return True, f"🎉 Success! You have unlocked {days} Day(s) of VIP Premium Access!", days

    except Exception as e:
        logger.error(f"Error redeeming promo {clean_code} for user {user_id}: {e}")
        return False, f"Error processing redemption: {e}", 0


async def get_all_promos(limit: int = 30) -> list[dict]:
    """Retrieve all promo codes for admin dashboard."""
    try:
        cursor = mongo.db["promo_codes"].find({}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error getting promo codes: {e}")
        return []


async def delete_promo_code(code: str) -> bool:
    """Delete or deactivate an existing promo code."""
    clean_code = code.strip().upper()
    try:
        res = await mongo.db["promo_codes"].delete_one({"code": clean_code})
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting promo code {clean_code}: {e}")
        return False
