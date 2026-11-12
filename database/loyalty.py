import time
import datetime
import logging
from database.mongo import mongo

logger = logging.getLogger("flixify.loyalty")

RANKS_HIERARCHY = [
    (60, "👑 Flixify Immortal"),
    (30, "💎 Diamond Elite"),
    (15, "🥇 Gold Cinema Master"),
    (7, "🥈 Silver Cinephile"),
    (1, "🌟 Newbie Watcher")
]


def get_ist_now() -> datetime.datetime:
    """Return current timestamp in IST (Asia/Kolkata / UTC+5:30)."""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)


def get_ist_date_str(dt: datetime.datetime = None) -> str:
    """Format IST datetime as YYYY-MM-DD."""
    if dt is None:
        dt = get_ist_now()
    return dt.strftime("%Y-%m-%d")


def calculate_rank(longest_streak: int) -> str:
    """Derive permanent lifetime rank based on highest achieved streak."""
    for threshold, title in RANKS_HIERARCHY:
        if longest_streak >= threshold:
            return title
    return "🌟 Newbie Watcher"


def get_seconds_until_midnight_ist() -> int:
    """Seconds remaining until next 00:00:00 IST reset."""
    now_ist = get_ist_now()
    midnight_ist = (now_ist + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((midnight_ist - now_ist).total_seconds()))


async def get_loyalty_profile(user_id: int) -> dict:
    """Fetch user loyalty profile from MongoDB or create a clean default profile."""
    col = mongo.db["loyalty_users"]
    doc = await col.find_one({"user_id": int(user_id)})
    today_str = get_ist_date_str()

    if not doc:
        doc = {
            "user_id": int(user_id),
            "coins": 0,
            "current_streak": 1,
            "longest_streak": 1,
            "last_active_date": today_str,
            "last_spin_date": None,
            "referral_spins": 0,
            "daily_ref_spins_today": 0,
            "last_ref_spin_date": today_str,
            "lifetime_rank": "🌟 Newbie Watcher",
            "bonus_direct_passes": 0,
            "total_spins_count": 0,
            "created_at": time.time(),
            "updated_at": time.time()
        }
        try:
            await col.insert_one(doc)
        except Exception as e:
            logger.debug(f"loyalty_users insert note: {e}")
    else:
        # Check if daily referral counter needs reset for new IST day
        if doc.get("last_ref_spin_date") != today_str:
            filter_q = {"_id": doc["_id"]} if "_id" in doc else {"user_id": int(user_id)}
            await col.update_one(
                filter_q,
                {"$set": {"daily_ref_spins_today": 0, "last_ref_spin_date": today_str}}
            )
            doc["daily_ref_spins_today"] = 0
            doc["last_ref_spin_date"] = today_str

    return doc


async def record_daily_activity(user_id: int) -> dict:
    """Update streak progression and lifetime rank based on IST calendar days."""
    profile = await get_loyalty_profile(user_id)
    today_dt = get_ist_now()
    today_str = get_ist_date_str(today_dt)
    yesterday_str = get_ist_date_str(today_dt - datetime.timedelta(days=1))

    last_active = profile.get("last_active_date")
    current_streak = profile.get("current_streak", 1)
    longest_streak = profile.get("longest_streak", 1)

    if last_active == today_str:
        return profile  # Already recorded today

    if last_active == yesterday_str:
        current_streak += 1
    else:
        current_streak = 1  # Missed day resets current streak

    if current_streak > longest_streak:
        longest_streak = current_streak

    new_rank = calculate_rank(longest_streak)

    updates = {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "last_active_date": today_str,
        "lifetime_rank": new_rank,
        "updated_at": time.time()
    }

    col = mongo.db["loyalty_users"]
    await col.update_one({"user_id": int(user_id)}, {"$set": updates})
    profile.update(updates)
    return profile


async def can_spin_today(user_id: int) -> tuple[bool, str, int, int]:
    """Check if user has a spin available (Daily Free Spin or Referral Spins).
    Returns (allowed: bool, spin_type: 'free'|'referral'|'cooldown', extra_spins_left: int, cooldown_seconds: int).
    """
    profile = await get_loyalty_profile(user_id)
    today_str = get_ist_date_str()
    last_spin = profile.get("last_spin_date")
    ref_spins = profile.get("referral_spins", 0)

    if last_spin != today_str:
        return True, "free", ref_spins, 0

    if ref_spins > 0:
        return True, "referral", ref_spins, 0

    secs = get_seconds_until_midnight_ist()
    return False, "cooldown", 0, secs


async def consume_spin(user_id: int, spin_type: str) -> bool:
    """Consume an authorized spin for the user."""
    col = mongo.db["loyalty_users"]
    today_str = get_ist_date_str()

    if spin_type == "free":
        res = await col.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {"last_spin_date": today_str, "updated_at": time.time()},
                "$inc": {"total_spins_count": 1}
            }
        )
        return res.modified_count > 0
    elif spin_type == "referral":
        res = await col.update_one(
            {"user_id": int(user_id), "referral_spins": {"$gt": 0}},
            {
                "$inc": {"referral_spins": -1, "total_spins_count": 1},
                "$set": {"updated_at": time.time()}
            }
        )
        return res.modified_count > 0
    return False


async def credit_referral_spin(referrer_id: int, max_daily: int = 5) -> tuple[bool, str]:
    """Award +1 Extra Spin when an invited friend joins the bot (max 5 per day)."""
    profile = await get_loyalty_profile(referrer_id)
    today_str = get_ist_date_str()
    today_claims = profile.get("daily_ref_spins_today", 0)

    if today_claims >= max_daily:
        return False, "daily_limit_reached"

    col = mongo.db["loyalty_users"]
    await col.update_one(
        {"user_id": int(referrer_id)},
        {
            "$inc": {"referral_spins": 1, "daily_ref_spins_today": 1},
            "$set": {"last_ref_spin_date": today_str, "updated_at": time.time()}
        }
    )
    return True, "credited"


async def add_coins(user_id: int, amount: int, reason: str = "reward") -> int:
    """Credit coins to user's wallet. Returns updated balance."""
    if amount <= 0:
        profile = await get_loyalty_profile(user_id)
        return profile.get("coins", 0)

    col = mongo.db["loyalty_users"]
    res = await col.find_one_and_update(
        {"user_id": int(user_id)},
        {"$inc": {"coins": int(amount)}, "$set": {"updated_at": time.time()}},
        return_document=True,
        upsert=True
    )
    new_bal = res.get("coins", amount) if res else amount
    logger.info(f"User {user_id} credited +{amount} coins ({reason}). New balance: {new_bal}")
    return new_bal


async def deduct_coins(user_id: int, amount: int, reason: str = "spend") -> tuple[bool, int]:
    """Deduct coins from user's wallet if balance is sufficient.
    Returns (success: bool, new_balance: int).
    """
    if amount <= 0:
        profile = await get_loyalty_profile(user_id)
        return True, profile.get("coins", 0)

    col = mongo.db["loyalty_users"]
    res = await col.find_one_and_update(
        {"user_id": int(user_id), "coins": {"$gte": int(amount)}},
        {"$inc": {"coins": -int(amount)}, "$set": {"updated_at": time.time()}},
        return_document=True
    )
    if res:
        new_bal = res.get("coins", 0)
        logger.info(f"User {user_id} deducted -{amount} coins ({reason}). Remaining: {new_bal}")
        return True, new_bal

    profile = await get_loyalty_profile(user_id)
    return False, profile.get("coins", 0)


async def get_top_leaderboard(limit: int = 10) -> list[dict]:
    """Retrieve top users ranked by highest active streak and coin balance."""
    col = mongo.db["loyalty_users"]
    cursor = col.find({}, {"_id": 0, "user_id": 1, "coins": 1, "current_streak": 1, "longest_streak": 1, "lifetime_rank": 1}).sort([("longest_streak", -1), ("coins", -1)]).limit(limit)
    return await cursor.to_list(length=limit)


async def use_direct_pass(user_id: int) -> tuple[bool, int]:
    """Consume 1 Direct Download Pass if available. Returns (used: bool, passes_remaining: int)."""
    col = mongo.db["loyalty_users"]
    res = await col.find_one_and_update(
        {"user_id": int(user_id), "bonus_direct_passes": {"$gt": 0}},
        {"$inc": {"bonus_direct_passes": -1}, "$set": {"updated_at": time.time()}},
        return_document=True
    )
    if res:
        rem = res.get("bonus_direct_passes", 0)
        logger.info(f"User {user_id} used 1 Direct Download Pass. Remaining passes: {rem}")
        return True, rem
    profile = await get_loyalty_profile(user_id)
    return False, profile.get("bonus_direct_passes", 0)
