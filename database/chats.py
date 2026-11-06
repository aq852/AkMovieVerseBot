import datetime
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

DEFAULT_CHAT_SETTINGS = {
    "auto_delete": True,
    "auto_delete_time": 300,
    "imdb_enabled": True,
    "shortener_enabled": True,
    "single_button": True,
    "custom_shortener_url": None,
    "custom_shortener_api": None,
    "tutorial_url": None,
    "custom_caption": None
}

async def add_chat(chat_id: int, title: str = "") -> dict:
    """Register or update a Telegram group chat in the database."""
    try:
        chat = await mongo.chats.find_one({"chat_id": chat_id})
        if not chat:
            new_chat = {
                "chat_id": chat_id,
                "title": title,
                "settings": DEFAULT_CHAT_SETTINGS.copy(),
                "connected_admins": [],
                "joined_at": datetime.datetime.utcnow()
            }
            await mongo.chats.insert_one(new_chat)
            return new_chat
        else:
            await mongo.chats.update_one({"chat_id": chat_id}, {"$set": {"title": title}})
            return chat
    except Exception as e:
        logger.error(f"Error adding chat {chat_id}: {e}")
        return {}


async def get_chat_settings(chat_id: int) -> dict:
    """Retrieve settings for a given chat, falling back to defaults if unset."""
    try:
        chat = await mongo.chats.find_one({"chat_id": chat_id})
        if not chat or "settings" not in chat:
            return DEFAULT_CHAT_SETTINGS.copy()

        # Merge with defaults to guarantee all keys exist
        merged = DEFAULT_CHAT_SETTINGS.copy()
        merged.update(chat["settings"])
        return merged
    except Exception as e:
        logger.error(f"Error fetching settings for chat {chat_id}: {e}")
        return DEFAULT_CHAT_SETTINGS.copy()


async def update_chat_setting(chat_id: int, key: str, value) -> bool:
    """Update a specific setting for a chat."""
    try:
        res = await mongo.chats.update_one(
            {"chat_id": chat_id},
            {"$set": {f"settings.{key}": value}},
            upsert=True
        )
        return res.modified_count > 0 or res.upserted_id is not None
    except Exception as e:
        logger.error(f"Error updating setting {key} for chat {chat_id}: {e}")
        return False


async def connect_user_to_chat(user_id: int, chat_id: int) -> bool:
    """Link a user/admin's PM to a group chat for remote settings management."""
    try:
        res = await mongo.chats.update_one(
            {"chat_id": chat_id},
            {"$addToSet": {"connected_admins": user_id}},
            upsert=True
        )
        return res.modified_count > 0 or res.matched_count > 0
    except Exception as e:
        logger.error(f"Error connecting user {user_id} to chat {chat_id}: {e}")
        return False


async def disconnect_user_from_chat(user_id: int, chat_id: int) -> bool:
    """Unlink a user/admin's PM from a group chat."""
    try:
        res = await mongo.chats.update_one(
            {"chat_id": chat_id},
            {"$pull": {"connected_admins": user_id}}
        )
        return res.modified_count > 0
    except Exception as e:
        logger.error(f"Error disconnecting user {user_id} from chat {chat_id}: {e}")
        return False


async def get_user_connected_chats(user_id: int) -> list[dict]:
    """Retrieve all chats connected to a user's PM."""
    try:
        cursor = mongo.chats.find({"connected_admins": user_id})
        return await cursor.to_list(length=100)
    except Exception as e:
        logger.error(f"Error fetching connected chats for user {user_id}: {e}")
        return []


async def get_total_chats_count() -> int:
    """Get total count of registered groups."""
    try:
        return await mongo.chats.count_documents({})
    except Exception as e:
        logger.error(f"Error counting chats: {e}")
        return 0


async def get_all_chat_ids() -> list[int]:
    """Retrieve all chat IDs for group broadcasting."""
    try:
        cursor = mongo.chats.find({}, {"chat_id": 1})
        chats = await cursor.to_list(length=100000)
        return [c["chat_id"] for c in chats if "chat_id" in c]
    except Exception as e:
        logger.error(f"Error fetching chat IDs for broadcast: {e}")
        return []


async def delete_chat(chat_id: int) -> bool:
    """Delete a group chat from database if bot was kicked or chat is dead."""
    try:
        res = await mongo.chats.delete_one({"chat_id": chat_id})
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting chat {chat_id}: {e}")
        return False
