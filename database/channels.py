import logging
from config import Config
from database.mongo import get_bot_setting, set_bot_setting

logger = logging.getLogger("autofilter.channels")

_STORAGE_CHANNELS_CACHE: set[int] | None = None


async def get_storage_channels(force_refresh: bool = False) -> list[int]:
    """Retrieve all active storage/DB channels from Config and MongoDB.
    Merges static Config.CHANNELS with persistent dynamic channels.
    """
    global _STORAGE_CHANNELS_CACHE
    if _STORAGE_CHANNELS_CACHE is not None and not force_refresh:
        return list(_STORAGE_CHANNELS_CACHE)

    channels = set()
    # 1. Config.CHANNELS from .env / environment
    if Config.CHANNELS:
        for cid in Config.CHANNELS:
            try:
                channels.add(int(cid))
            except (ValueError, TypeError):
                pass

    # 2. Dynamic persistent channels stored in MongoDB
    try:
        dyn_list = await get_bot_setting("storage_channels", [])
        if dyn_list:
            for cid in dyn_list:
                try:
                    channels.add(int(cid))
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        logger.debug(f"Error loading dynamic storage channels: {e}")

    _STORAGE_CHANNELS_CACHE = channels
    return list(channels)


async def add_storage_channel(channel_id: int) -> bool:
    """Add a channel ID to persistent storage_channels in MongoDB and active cache."""
    global _STORAGE_CHANNELS_CACHE
    try:
        cid = int(channel_id)
        current = await get_storage_channels(force_refresh=True)
        ch_set = set(current)
        ch_set.add(cid)

        # Save to MongoDB
        ok = await set_bot_setting("storage_channels", list(ch_set))
        if ok:
            _STORAGE_CHANNELS_CACHE = ch_set
            # Also keep in-memory Config.CHANNELS synchronized
            if Config.CHANNELS is None:
                Config.CHANNELS = []
            if cid not in Config.CHANNELS:
                Config.CHANNELS.append(cid)
            logger.info(f"Added storage channel: {cid}. Total active: {len(ch_set)}")
            return True
    except Exception as e:
        logger.error(f"Error adding storage channel {channel_id}: {e}")
    return False


async def remove_storage_channel(channel_id: int) -> bool:
    """Remove a channel ID from persistent storage_channels in MongoDB and active cache."""
    global _STORAGE_CHANNELS_CACHE
    try:
        cid = int(channel_id)
        current = await get_storage_channels(force_refresh=True)
        ch_set = set(current)
        ch_set.discard(cid)

        # Save to MongoDB
        ok = await set_bot_setting("storage_channels", list(ch_set))
        if ok:
            _STORAGE_CHANNELS_CACHE = ch_set
            if Config.CHANNELS and cid in Config.CHANNELS:
                Config.CHANNELS.remove(cid)
            logger.info(f"Removed storage channel: {cid}. Remaining: {len(ch_set)}")
            return True
    except Exception as e:
        logger.error(f"Error removing storage channel {channel_id}: {e}")
    return False


async def is_storage_channel(channel_id: int) -> bool:
    """Check if given chat ID is an active storage channel."""
    try:
        cid = int(channel_id)
        channels = await get_storage_channels()
        return cid in channels
    except (ValueError, TypeError):
        return False
