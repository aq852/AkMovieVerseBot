import datetime
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

async def add_user(user_id: int, name: str = "", username: str = "") -> tuple[dict, bool]:
    """Register or update a user record in MongoDB. Returns (user_doc, is_new)."""
    try:
        user = await mongo.users.find_one({"user_id": user_id})
        if not user:
            new_user = {
                "user_id": user_id,
                "name": name,
                "username": username,
                "is_banned": False,
                "is_premium": False,
                "premium_expires": None,
                "refer_by": None,
                "refer_count": 0,
                "joined_at": datetime.datetime.utcnow()
            }
            await mongo.users.insert_one(new_user)
            return new_user, True
        else:
            # Update name/username if changed
            await mongo.users.update_one(
                {"user_id": user_id},
                {"$set": {"name": name, "username": username}}
            )
            return user, False
    except Exception as e:
        logger.error(f"Error adding/updating user {user_id}: {e}")
        return {}, False


async def is_banned(user_id: int) -> bool:
    """Check if user is blacklisted."""
    try:
        user = await mongo.users.find_one({"user_id": user_id}, {"is_banned": 1})
        return bool(user and user.get("is_banned"))
    except Exception as e:
        logger.error(f"Error checking ban status for {user_id}: {e}")
        return False


async def set_ban_status(user_id: int, status: bool) -> bool:
    """Ban or unban a user."""
    try:
        res = await mongo.users.update_one({"user_id": user_id}, {"$set": {"is_banned": status}})
        return res.modified_count > 0 or res.matched_count > 0
    except Exception as e:
        logger.error(f"Error setting ban status for {user_id}: {e}")
        return False


async def get_total_users_count() -> int:
    """Get total count of registered users."""
    try:
        return await mongo.users.count_documents({})
    except Exception as e:
        logger.error(f"Error counting users: {e}")
        return 0


async def get_all_user_ids() -> list[int]:
    """Retrieve all user IDs for async broadcasting."""
    try:
        cursor = mongo.users.find({}, {"user_id": 1})
        users = await cursor.to_list(length=1000000)
        return [u["user_id"] for u in users if "user_id" in u]
    except Exception as e:
        logger.error(f"Error fetching user IDs for broadcast: {e}")
        return []


async def add_premium(user_id: int, seconds: int) -> bool:
    """Grant or extend premium subscription for a user."""
    try:
        user = await mongo.users.find_one({"user_id": user_id})
        now = datetime.datetime.utcnow()
        cur_exp = user.get("premium_expires") if user else None
        if cur_exp and hasattr(cur_exp, "replace") and getattr(cur_exp, "tzinfo", None):
            cur_exp = cur_exp.replace(tzinfo=None)

        if user and user.get("is_premium") and cur_exp and cur_exp > now:
            # Extend existing active premium
            new_expiry = cur_exp + datetime.timedelta(seconds=seconds)
        else:
            new_expiry = now + datetime.timedelta(seconds=seconds)

        await mongo.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_premium": True, "premium_expires": new_expiry}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error granting premium to {user_id}: {e}")
        return False


async def remove_premium(user_id: int) -> bool:
    """Revoke premium status from a user."""
    try:
        await mongo.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_premium": False, "premium_expires": None}}
        )
        return True
    except Exception as e:
        logger.error(f"Error removing premium for {user_id}: {e}")
        return False


async def is_premium(user_id: int) -> bool:
    """Check if user has an active premium subscription."""
    try:
        user = await mongo.users.find_one({"user_id": user_id})
        if not user or not user.get("is_premium"):
            return False

        expiry = user.get("premium_expires")
        if not expiry:
            # Lifetime / unlimited premium subscription
            return True

        if hasattr(expiry, "replace") and getattr(expiry, "tzinfo", None):
            expiry = expiry.replace(tzinfo=None)

        now = datetime.datetime.utcnow()
        if expiry > now:
            return True

        # Expired: update status
        await mongo.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_premium": False, "premium_expires": None}}
        )
        return False
    except Exception as e:
        logger.error(f"Error checking premium status for {user_id}: {e}")
        return False


async def record_referral(referrer_id: int, new_user_id: int) -> tuple[bool, str]:
    """Track a successful unique referral with anti-abuse protection and award free VIP."""
    try:
        if referrer_id == new_user_id:
            return False, "self_referral"

        new_user = await mongo.users.find_one({"user_id": new_user_id})
        # If user was already referred by someone else, ignore
        if new_user and new_user.get("refer_by"):
            return False, "already_referred"

        # Check if referrer already has this user recorded in referred_users array
        referrer = await mongo.users.find_one({"user_id": referrer_id})
        if referrer and new_user_id in referrer.get("referred_users", []):
            return False, "already_counted"

        # Mark referrer on new user
        await mongo.users.update_one(
            {"user_id": new_user_id},
            {"$set": {"refer_by": referrer_id}},
            upsert=True
        )

        # Atomically add new_user_id to referred_users and increment refer_count
        updated_referrer = await mongo.users.find_one_and_update(
            {"user_id": referrer_id, "referred_users": {"$ne": new_user_id}},
            {
                "$addToSet": {"referred_users": new_user_id},
                "$inc": {"refer_count": 1}
            },
            return_document=True,
            upsert=True
        )

        if not updated_referrer:
            return False, "already_counted"

        # Award 1 day (86400s) VIP for every 5 unique referrals
        count = updated_referrer.get("refer_count", 0)
        if count > 0 and count % 5 == 0:
            await add_premium(referrer_id, 86400)
            await mongo.users.update_one(
                {"user_id": referrer_id},
                {"$inc": {"refer_rewards_earned": 1}}
            )
            return True, "awarded_premium"

        return True, "recorded"
    except Exception as e:
        logger.error(f"Error recording referral {referrer_id} -> {new_user_id}: {e}")
        return False, str(e)


async def get_all_premium_users() -> list[dict]:
    """Retrieve all users with active premium subscriptions."""
    try:
        now = datetime.datetime.utcnow()
        cursor = mongo.users.find({
            "is_premium": True,
            "premium_expires": {"$gt": now}
        }).sort("premium_expires", 1)
        return await cursor.to_list(length=1000)
    except Exception as e:
        logger.error(f"Error fetching premium users: {e}")
        return []


async def get_user_info(user_id: int) -> dict:
    """Retrieve full user profile document."""
    try:
        return await mongo.users.find_one({"user_id": user_id}) or {}
    except Exception as e:
        logger.error(f"Error fetching user info {user_id}: {e}")
        return {}


async def can_user_create_filestore_link(user_id: int) -> tuple[bool, int, int]:
    """
    Check if user is allowed to generate a File Store link based on daily limit.
    Returns (allowed, used_today, daily_limit).
    VIP and Admins have unlimited links.
    """
    from config import Config
    if Config.is_admin(user_id):
        return True, 0, 999999

    is_vip = await is_premium(user_id)
    if is_vip:
        return True, 0, 999999

    limit = getattr(Config, "FILE_STORE_USER_DAILY_LIMIT", 10)
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    try:
        user = await mongo.users.find_one({"user_id": user_id}) or {}
        last_date = user.get("filestore_date")
        used_today = user.get("filestore_count", 0) if last_date == today else 0

        if used_today >= limit:
            return False, used_today, limit

        return True, used_today, limit
    except Exception as e:
        logger.error(f"Error checking filestore limit for {user_id}: {e}")
        return True, 0, limit


async def record_filestore_link_created(user_id: int):
    """Increment user's daily File Store links created counter."""
    from config import Config
    if Config.is_admin(user_id):
        return

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    try:
        user = await mongo.users.find_one({"user_id": user_id}) or {}
        if user.get("filestore_date") == today:
            await mongo.users.update_one(
                {"user_id": user_id},
                {"$inc": {"filestore_count": 1}}
            )
        else:
            await mongo.users.update_one(
                {"user_id": user_id},
                {"$set": {"filestore_date": today, "filestore_count": 1}}
            )
    except Exception as e:
        logger.error(f"Error recording filestore link for {user_id}: {e}")
