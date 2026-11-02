import datetime
import uuid
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)


async def create_batch(
    files: list[dict],
    title: str,
    created_by: int,
    is_vip_only: bool = False,
    protect_content: bool = False,
    expire_seconds: int | None = None,
    max_downloads: int | None = None,
    pin_code: str | None = None,
    batch_id: str | None = None
) -> dict:
    """
    Package multiple files into a shareable batch collection.
    Supports optional time-based expiration, download limits, content protection, and PIN lock.
    Returns the created batch document with unique batch_id.
    """
    batch_id = batch_id or uuid.uuid4().hex[:10]
    now = datetime.datetime.utcnow()
    expire_at = now + datetime.timedelta(seconds=expire_seconds) if expire_seconds and expire_seconds > 0 else None

    total_size = sum(int(f.get("file_size", 0)) for f in files)

    doc = {
        "batch_id": batch_id,
        "title": title.strip() if title else f"Batch Pack ({len(files)} Files)",
        "created_by": created_by,
        "created_at": now,
        "expire_at": expire_at,
        "max_downloads": int(max_downloads) if max_downloads and int(max_downloads) > 0 else None,
        "pin_code": str(pin_code).strip() if pin_code and str(pin_code).strip() else None,
        "is_vip_only": bool(is_vip_only),
        "protect_content": bool(protect_content),
        "total_files": len(files),
        "total_size": total_size,
        "files": files,
        "views_count": 0,
        "downloads_count": 0
    }

    try:
        await mongo.batches.insert_one(doc)
        logger.info(f"Created batch {batch_id} with {len(files)} files by {created_by} (pin={bool(pin_code)}, exp={bool(expire_at)}, max_dl={max_downloads})")
        return doc
    except Exception as e:
        logger.error(f"Error creating batch in MongoDB: {e}")
        return {}


async def get_batch(batch_id: str) -> dict | None:
    """Fetch batch document by batch_id."""
    try:
        return await mongo.batches.find_one({"batch_id": batch_id})
    except Exception as e:
        logger.error(f"Error fetching batch {batch_id}: {e}")
        return None


async def increment_batch_views(batch_id: str):
    """Increment batch view/open count."""
    try:
        await mongo.batches.update_one({"batch_id": batch_id}, {"$inc": {"views_count": 1}})
    except Exception as e:
        logger.debug(f"Error incrementing batch views: {e}")


async def increment_batch_downloads(batch_id: str):
    """Increment batch download count and schedule TTL purge if limit reached."""
    try:
        await mongo.batches.update_one({"batch_id": batch_id}, {"$inc": {"downloads_count": 1}})
        batch = await mongo.batches.find_one({"batch_id": batch_id})
        if batch:
            max_dl = batch.get("max_downloads")
            cur_dl = batch.get("downloads_count", 0)
            if max_dl and cur_dl >= max_dl:
                now = datetime.datetime.utcnow()
                grace_purge = now + datetime.timedelta(hours=24)
                cur_exp = batch.get("expire_at")
                if cur_exp and hasattr(cur_exp, "replace") and getattr(cur_exp, "tzinfo", None):
                    cur_exp = cur_exp.replace(tzinfo=None)
                if not cur_exp or cur_exp > grace_purge:
                    await mongo.batches.update_one(
                        {"batch_id": batch_id},
                        {"$set": {"expire_at": grace_purge}}
                    )
    except Exception as e:
        logger.debug(f"Error incrementing batch downloads: {e}")


async def delete_batch(batch_id: str) -> bool:
    """Delete a batch collection from MongoDB."""
    try:
        res = await mongo.batches.delete_one({"batch_id": batch_id})
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting batch {batch_id}: {e}")
        return False


async def get_recent_batches(limit: int = 20) -> list[dict]:
    """Retrieve list of recently created batches."""
    try:
        cursor = mongo.batches.find().sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error fetching recent batches: {e}")
        return []


async def get_user_batches(created_by: int, limit: int = 20) -> list[dict]:
    """Retrieve batches created by a specific user."""
    try:
        cursor = mongo.batches.find({"created_by": created_by}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error fetching user batches for {created_by}: {e}")
        return []


async def count_total_batches() -> int:
    """Return total count of batches in MongoDB."""
    try:
        return await mongo.batches.count_documents({})
    except Exception as e:
        logger.error(f"Error counting batches: {e}")
        return 0


async def toggle_batch_protection(batch_id: str) -> bool | None:
    """Toggle protect_content flag on a batch collection. Returns new boolean state or None on error."""
    try:
        doc = await mongo.batches.find_one({"batch_id": batch_id})
        if not doc:
            return None
        new_val = not bool(doc.get("protect_content", False))
        await mongo.batches.update_one({"batch_id": batch_id}, {"$set": {"protect_content": new_val}})
        return new_val
    except Exception as e:
        logger.error(f"Error toggling protection for batch {batch_id}: {e}")
        return None


async def set_batch_pin(batch_id: str, pin: str | None) -> bool:
    """Set or remove pin_code on a batch."""
    try:
        clean_pin = pin.strip() if pin else None
        res = await mongo.batches.update_one({"batch_id": batch_id}, {"$set": {"pin_code": clean_pin}})
        return res.modified_count > 0 or res.matched_count > 0
    except Exception as e:
        logger.error(f"Error setting pin on batch {batch_id}: {e}")
        return False


async def set_batch_expiry(batch_id: str, expire_seconds: int | None = None, max_downloads: int | None = None) -> bool:
    """Update expiry datetime and/or max_downloads on a batch."""
    try:
        update_fields = {}
        now = datetime.datetime.utcnow()
        if expire_seconds is not None:
            update_fields["expire_at"] = now + datetime.timedelta(seconds=expire_seconds) if expire_seconds > 0 else None
        if max_downloads is not None:
            update_fields["max_downloads"] = int(max_downloads) if int(max_downloads) > 0 else None

        if update_fields:
            res = await mongo.batches.update_one({"batch_id": batch_id}, {"$set": update_fields})
            return res.modified_count > 0 or res.matched_count > 0
        return True
    except Exception as e:
        logger.error(f"Error setting expiry on batch {batch_id}: {e}")
        return False
