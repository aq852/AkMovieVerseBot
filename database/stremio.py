import time
import secrets
import logging
from database.mongo import mongo
from database.users import is_premium

logger = logging.getLogger("autofilter.stremio")


async def get_stremio_token(user_id: int) -> dict | None:
    """Fetch active Stremio VIP token document for a user."""
    return await mongo.stremio_tokens.find_one({"user_id": int(user_id), "is_active": True})


async def create_or_get_stremio_token(user_id: int) -> tuple[str, bool]:
    """Generate or retrieve existing 32-character secret Stremio token for a VIP user."""
    user_id = int(user_id)
    existing = await mongo.stremio_tokens.find_one({"user_id": user_id, "is_active": True})
    if existing and existing.get("token"):
        return existing["token"], False

    new_token = f"ak_{secrets.token_hex(16)}"
    doc = {
        "token": new_token,
        "user_id": user_id,
        "is_active": True,
        "created_at": time.time(),
        "active_ip": None,
        "last_stream_time": 0.0,
        "total_streams": 0
    }
    await mongo.stremio_tokens.insert_one(doc)
    logger.info(f"Generated new Stremio VIP token for user {user_id}")
    return new_token, True


async def reset_stremio_token(user_id: int) -> str:
    """Revoke existing token and generate a fresh un-guessable token."""
    user_id = int(user_id)
    await mongo.stremio_tokens.update_many(
        {"user_id": user_id},
        {"$set": {"is_active": False, "revoked_at": time.time()}}
    )
    new_token = f"ak_{secrets.token_hex(16)}"
    doc = {
        "token": new_token,
        "user_id": user_id,
        "is_active": True,
        "created_at": time.time(),
        "active_ip": None,
        "last_stream_time": 0.0,
        "total_streams": 0
    }
    await mongo.stremio_tokens.insert_one(doc)
    logger.info(f"Reset Stremio VIP token for user {user_id}")
    return new_token


async def revoke_stremio_token(user_id: int) -> bool:
    """Deactivate Stremio access for a user."""
    res = await mongo.stremio_tokens.update_many(
        {"user_id": int(user_id), "is_active": True},
        {"$set": {"is_active": False, "revoked_at": time.time()}}
    )
    return res.modified_count > 0


async def verify_stremio_access(token: str, client_ip: str | None = None) -> tuple[bool, str, dict | None]:
    """Verify Stremio token validity, VIP status, and enforce 1-IP concurrency limit."""
    if not token or not isinstance(token, str) or not token.startswith("ak_"):
        return False, "Invalid Stremio token format", None

    doc = await mongo.stremio_tokens.find_one({"token": token, "is_active": True})
    if not doc:
        return False, "Token not found or revoked", None

    user_id = doc["user_id"]
    is_vip = await is_premium(user_id)
    if not is_vip:
        return False, "VIP membership expired", doc

    now = time.time()
    if client_ip:
        active_ip = doc.get("active_ip")
        last_stream = float(doc.get("last_stream_time", 0.0))
        # 1-IP Concurrency Window: 180 seconds (3 mins of inactivity resets the active IP)
        if active_ip and active_ip != client_ip and (now - last_stream) < 180:
            logger.warning(
                f"Stremio multi-IP streaming blocked for user {user_id}: active {active_ip} vs new {client_ip}"
            )
            return False, "Concurrent streaming from multiple devices/IPs detected. Max 1 active device allowed.", doc

        # Update active streaming session
        try:
            await mongo.stremio_tokens.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "active_ip": client_ip,
                        "last_stream_time": now
                    },
                    "$inc": {"total_streams": 1}
                }
            )
        except Exception as e:
            logger.debug(f"Could not update stremio streaming activity: {e}")

    return True, "OK", doc


async def get_stremio_stats() -> dict:
    """Return aggregated statistics on Stremio active tokens and usage."""
    total_tokens = await mongo.stremio_tokens.count_documents({"is_active": True})
    now = time.time()
    # Active streams in last 10 minutes
    active_now = await mongo.stremio_tokens.count_documents({
        "is_active": True,
        "last_stream_time": {"$gte": now - 600}
    })
    return {
        "total_active_tokens": total_tokens,
        "currently_streaming": active_now
    }
