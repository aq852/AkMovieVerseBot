import random
import aiohttp
import asyncio
import datetime
import logging
from config import Config
from database.mongo import mongo

logger = logging.getLogger(__name__)

_ROTATION_INDEX = 0


async def record_shortener_click(domain: str):
    """Increment daily and total click/generation count for a shortener domain in MongoDB."""
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    clean_dom = domain.strip().replace(".", "_")
    try:
        await mongo.db["shortener_stats"].update_one(
            {"date": today_str},
            {"$inc": {f"domains.{clean_dom}": 1, "total": 1}},
            upsert=True
        )
        await mongo.db["shortener_stats"].update_one(
            {"date": "all_time"},
            {"$inc": {f"domains.{clean_dom}": 1, "total": 1}},
            upsert=True
        )
    except Exception as e:
        logger.debug(f"Failed to record shortener stat: {e}")


async def record_vip_bypass():
    """Increment daily and total count of VIP members who bypass shorteners."""
    today_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    try:
        await mongo.db["shortener_stats"].update_one(
            {"date": today_str},
            {"$inc": {"vip_bypasses": 1}},
            upsert=True
        )
        await mongo.db["shortener_stats"].update_one(
            {"date": "all_time"},
            {"$inc": {"vip_bypasses": 1}},
            upsert=True
        )
    except Exception as e:
        logger.debug(f"Failed to record VIP bypass stat: {e}")

async def shorten_url_single(destination_url: str, shortener_url: str, shortener_api: str) -> str | None:
    """Send an API request to a single shortener provider and parse result."""
    if not shortener_url or not shortener_api:
        return None

    base_url = shortener_url.strip()
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    api_endpoint = f"{base_url.rstrip('/')}/api?api={shortener_api.strip()}&url={destination_url}"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3.5)) as session:
            async with session.get(api_endpoint) as response:
                if response.status == 200:
                    try:
                        data = await response.json(content_type=None)
                        if isinstance(data, dict):
                            short_url = data.get("shortenedUrl") or data.get("link") or data.get("url") or data.get("short_url")
                            if short_url and str(short_url).startswith("http"):
                                return str(short_url).strip()
                    except Exception:
                        text = (await response.text()).strip()
                        if text.startswith("http"):
                            return text
    except Exception as e:
        logger.warning(f"Error shortening URL via {base_url}: {e}")

    return None


async def get_all_active_shorteners() -> list[dict]:
    """Retrieve all configured shorteners from environment variables and MongoDB collection."""
    shorteners = []
    seen_domains = set()

    # 1. Load from environment Config
    configs = [
        (Config.SHORTENER_URL, Config.SHORTENER_API, "Primary"),
        (Config.SHORTENER_URL2, Config.SHORTENER_API2, "Secondary"),
        (Config.SHORTENER_URL3, Config.SHORTENER_API3, "Tertiary")
    ]
    for url, api, tag in configs:
        if url and api and url.strip() and api.strip():
            clean_dom = url.strip().replace("https://", "").replace("http://", "").rstrip("/")
            if clean_dom not in seen_domains:
                shorteners.append({"domain": clean_dom, "api": api.strip(), "source": tag})
                seen_domains.add(clean_dom)

    # 2. Load dynamic shorteners from MongoDB with secondary DB fallback
    try:
        cursor = mongo.shorteners.find({})
        db_items = await cursor.to_list(length=50)
        for item in db_items:
            clean_dom = item["domain"].strip().replace("https://", "").replace("http://", "").rstrip("/")
            if clean_dom not in seen_domains and item.get("api"):
                shorteners.append({"domain": clean_dom, "api": item["api"].strip(), "source": "Dynamic DB"})
                seen_domains.add(clean_dom)
        if mongo.has_secondary:
            try:
                cursor2 = mongo.db2["multi_shorteners"].find({})
                db_items2 = await cursor2.to_list(length=50)
                for item in db_items2:
                    clean_dom = item["domain"].strip().replace("https://", "").replace("http://", "").rstrip("/")
                    if clean_dom not in seen_domains and item.get("api"):
                        shorteners.append({"domain": clean_dom, "api": item["api"].strip(), "source": "Dynamic DB Secondary"})
                        seen_domains.add(clean_dom)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Could not load shorteners from MongoDB: {e}")

    return shorteners


async def get_rotated_shortlink(destination_url: str) -> tuple[str, str]:
    """Shorten URL using rotation across active shorteners with automatic fallback.
    Returns (shortened_url, provider_domain).
    """
    global _ROTATION_INDEX
    shorteners = await get_all_active_shorteners()

    if not shorteners:
        logger.warning("No active shortener configured. Returning direct destination URL.")
        return destination_url, "Direct"

    count = len(shorteners)

    # 1. Select initial shortener based on rotation mode
    if Config.SHORTENER_ROTATION == "random":
        start_idx = random.randint(0, count - 1)
    else:  # round_robin
        start_idx = _ROTATION_INDEX % count
        _ROTATION_INDEX += 1

    # 2. Create rotation attempt order (starting from selected, then fallbacks in circular order)
    attempt_order = [shorteners[(start_idx + i) % count] for i in range(count)]

    for idx, shortener in enumerate(attempt_order):
        dom = shortener["domain"]
        api = shortener["api"]
        short_url = await shorten_url_single(destination_url, dom, api)
        if short_url:
            if idx > 0:
                logger.info(f"Fallback shortener succeeded: {dom} (attempt {idx + 1}/{count})")
            else:
                logger.info(f"Rotated shortener succeeded: {dom}")
            asyncio.create_task(record_shortener_click(dom))
            return short_url, dom

        logger.warning(f"Shortener {dom} failed! Attempting next fallback in rotation...")

    # If all shorteners fail, fallback to direct destination URL
    logger.error("All shorteners in rotation and fallback failed! Delivering direct link.")
    return destination_url, "DirectFallback"


async def get_shortlink(destination_url: str, shortener_url: str = None, shortener_api: str = None) -> str:
    """Backward-compatible helper: shortens using specific credentials or rotation."""
    if shortener_url and shortener_api:
        res = await shorten_url_single(destination_url, shortener_url, shortener_api)
        return res or destination_url
    short_url, _ = await get_rotated_shortlink(destination_url)
    return short_url


# MongoDB Dynamic Shorteners Management Helpers
async def add_custom_shortener(domain: str, api_key: str) -> bool:
    """Dynamically add or update a shortener in the rotation database with dual-cluster sync."""
    clean_dom = domain.strip().replace("https://", "").replace("http://", "").rstrip("/")
    try:
        await mongo.shorteners.update_one(
            {"domain": clean_dom},
            {"$set": {"domain": clean_dom, "api": api_key.strip()}},
            upsert=True
        )
        if mongo.has_secondary:
            try:
                await mongo.db2["multi_shorteners"].update_one(
                    {"domain": clean_dom},
                    {"$set": {"domain": clean_dom, "api": api_key.strip()}},
                    upsert=True
                )
            except Exception:
                pass
        return True
    except Exception as e:
        logger.error(f"Error adding shortener {domain}: {e}")
        return False


async def remove_custom_shortener(domain: str) -> bool:
    """Remove a shortener from the dynamic database with dual-cluster sync."""
    clean_dom = domain.strip().replace("https://", "").replace("http://", "").rstrip("/")
    try:
        res = await mongo.shorteners.delete_one({"domain": clean_dom})
        if mongo.has_secondary:
            try:
                await mongo.db2["multi_shorteners"].delete_one({"domain": clean_dom})
            except Exception:
                pass
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"Error removing shortener {domain}: {e}")
        return False
