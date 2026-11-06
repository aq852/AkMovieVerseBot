import uuid
import datetime
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

COOLDOWN_MINUTES = 3

async def create_movie_request(
    user_id: int,
    user_name: str,
    username: str,
    movie_name: str,
    chat_title: str = "Private PM"
) -> tuple[bool, str, str]:
    """Create a new movie request ticket with anti-spam rate limiting.
    Returns (success, request_id, message).
    """
    clean_movie = movie_name.strip()
    if len(clean_movie) < 2:
        return False, "", "Movie name is too short."

    now = datetime.datetime.utcnow()
    cooldown_threshold = now - datetime.timedelta(minutes=COOLDOWN_MINUTES)

    try:
        # Check if user made a request recently
        recent = await mongo.requests.find_one({
            "user_id": user_id,
            "created_at": {"$gte": cooldown_threshold}
        })
        if recent:
            rem_sec = int((recent["created_at"] + datetime.timedelta(minutes=COOLDOWN_MINUTES) - now).total_seconds())
            rem_min = max(1, rem_sec // 60)
            return False, "", f"Please wait {rem_min} minute(s) before submitting another request."

        req_id = uuid.uuid4().hex[:10]
        doc = {
            "request_id": req_id,
            "user_id": user_id,
            "user_name": user_name,
            "username": username or "",
            "movie_name": clean_movie,
            "chat_title": chat_title,
            "status": "pending",  # pending | uploaded | rejected
            "created_at": now,
            "updated_at": now,
            "resolved_by": ""
        }
        await mongo.requests.insert_one(doc)
        return True, req_id, "Request created successfully."
    except Exception as e:
        logger.error(f"Error creating movie request: {e}")
        return False, "", "Database error creating request."


async def get_movie_request(request_id: str) -> dict | None:
    """Retrieve details for a specific request ID."""
    try:
        return await mongo.requests.find_one({"request_id": request_id})
    except Exception as e:
        logger.error(f"Error getting movie request {request_id}: {e}")
        return None


async def update_movie_request_status(request_id: str, status: str, admin_name: str) -> bool:
    """Update status of a request (uploaded or rejected)."""
    try:
        res = await mongo.requests.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": status,
                    "resolved_by": admin_name,
                    "updated_at": datetime.datetime.utcnow()
                }
            }
        )
        return res.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating request {request_id}: {e}")
        return False


async def get_pending_requests_count() -> int:
    """Count total pending review requests."""
    try:
        return await mongo.requests.count_documents({"status": "pending"})
    except Exception as e:
        logger.debug(f"Error counting pending requests: {e}")
        return 0


async def get_user_requests(user_id: int, limit: int = 10) -> list[dict]:
    """Retrieve recent movie requests submitted by a specific user."""
    try:
        cursor = mongo.requests.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error getting requests for user {user_id}: {e}")
        return []


async def record_log_message_for_request(request_id: str, chat_id: int, message_id: int):
    """Store the log channel message reference to auto-update upon resolution."""
    try:
        await mongo.requests.update_one(
            {"request_id": request_id},
            {"$set": {"log_chat_id": chat_id, "log_msg_id": message_id}}
        )
    except Exception as e:
        logger.debug(f"Error recording log msg for request {request_id}: {e}")


def is_movie_request_match(requested_title: str, filename: str) -> bool:
    """Accurately match requested movie title against uploaded filename without false positives."""
    import re
    if not requested_title or not filename:
        return False

    req = requested_title.strip().lower()
    fn = filename.strip().lower()

    # Exact substring match
    if req in fn:
        return True

    # Normalize separators
    norm_fn = re.sub(r"[\._-]", " ", fn)
    norm_req = re.sub(r"[\._-]", " ", req)

    # Normalize Season indicators: S03 / S3 -> season 3
    norm_fn = re.sub(r"\bs0*(\d{1,2})\b", r"season \1", norm_fn, flags=re.I)
    norm_req = re.sub(r"\bs0*(\d{1,2})\b", r"season \1", norm_req, flags=re.I)

    # Tokenize and filter common noise words
    req_tokens = [w for w in norm_req.split() if w not in ("movie", "series", "full", "hd", "the", "a", "an")]
    if not req_tokens:
        req_tokens = norm_req.split()

    if not req_tokens:
        return False

    fn_tokens = norm_fn.split()
    fn_set = set(fn_tokens)

    # All significant request tokens must exist in filename
    for t in req_tokens:
        if t not in fn_set and not any(t in ft for ft in fn_tokens if len(t) >= 4):
            return False

    return True


async def find_and_resolve_pending_requests(filename: str) -> list[dict]:
    """Find all pending requests matching an uploaded filename and mark them resolved."""
    matched = []
    try:
        cursor = mongo.requests.find({"status": "pending"})
        pending = await cursor.to_list(300)

        for req in pending:
            req_title = req.get("movie_name", "")
            if is_movie_request_match(req_title, filename):
                # Mark as auto_uploaded so future uploads don't double notify
                await mongo.requests.update_one(
                    {"_id": req["_id"]},
                    {
                        "$set": {
                            "status": "auto_uploaded",
                            "resolved_by": "Auto Channel Upload",
                            "resolved_file": filename,
                            "updated_at": datetime.datetime.utcnow()
                        }
                    }
                )
                matched.append(req)
    except Exception as e:
        logger.error(f"Error matching pending requests: {e}")
    return matched
