import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

async def add_manual_filter(chat_id: int, keyword: str, reply_text: str, file_id: str = None, buttons: list = None) -> bool:
    """Store or update a custom manual keyword filter for a group."""
    try:
        filter_doc = {
            "chat_id": chat_id,
            "keyword": keyword.lower().strip(),
            "reply_text": reply_text,
            "file_id": file_id,
            "buttons": buttons or []
        }
        await mongo.filters.update_one(
            {"chat_id": chat_id, "keyword": keyword.lower().strip()},
            {"$set": filter_doc},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error adding manual filter for chat {chat_id}: {e}")
        return False


async def get_manual_filter(chat_id: int, keyword: str) -> dict | None:
    """Find a manual filter by keyword in a specific chat."""
    try:
        return await mongo.filters.find_one({
            "chat_id": chat_id,
            "keyword": keyword.lower().strip()
        })
    except Exception as e:
        logger.error(f"Error retrieving manual filter {keyword} in chat {chat_id}: {e}")
        return None


async def get_all_manual_filters(chat_id: int) -> list[str]:
    """List all active manual filter keywords in a chat."""
    try:
        cursor = mongo.filters.find({"chat_id": chat_id}, {"keyword": 1})
        docs = await cursor.to_list(length=1000)
        return [doc["keyword"] for doc in docs if "keyword" in doc]
    except Exception as e:
        logger.error(f"Error listing manual filters for chat {chat_id}: {e}")
        return []


async def delete_manual_filter(chat_id: int, keyword: str) -> bool:
    """Delete a specific manual keyword filter."""
    try:
        res = await mongo.filters.delete_one({
            "chat_id": chat_id,
            "keyword": keyword.lower().strip()
        })
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting manual filter {keyword} in chat {chat_id}: {e}")
        return False


async def delete_all_manual_filters(chat_id: int) -> int:
    """Purge all manual filters for a group."""
    try:
        res = await mongo.filters.delete_many({"chat_id": chat_id})
        return res.deleted_count
    except Exception as e:
        logger.error(f"Error deleting all manual filters for chat {chat_id}: {e}")
        return 0
