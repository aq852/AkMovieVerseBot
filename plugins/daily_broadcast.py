import os
import re
import time
import asyncio
import datetime
import logging
import urllib.parse

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
    from hydrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, UserDeactivated, PeerIdInvalid
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
    from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, UserDeactivated, PeerIdInvalid

from config import Config
from database.mongo import mongo, get_bot_setting, set_bot_setting
from database.users import get_all_user_ids
from utils.helpers import format_clean_title, get_cached_poster_url

logger = logging.getLogger(__name__)

# Pre-populated legendary gems across Movies, Anime, Web Series, and K-Dramas (Verified TMDB Posters)
DEFAULT_GEMS = [
    {
        "title": "Maharaja (2024)",
        "type": "movie",
        "rating": 8.5,
        "genre": "Crime • Suspense • Mystery",
        "audio": "Hindi Dubbed + Tamil",
        "hook": "Ek seedha-saadha naayi (barber) police station me FIR likhwane aata hai ki uske ghar se ek 'Dustbin' (Lakshmi) chori ho gaya hai... Lekin aakhri ke 30 minute ka suspense aapke hosh uda dega!",
        "search_query": "Maharaja",
        "poster": "https://image.tmdb.org/t/p/w500/s0m4TM1XRAftQStgKpw024RvkJo.jpg"
    },
    {
        "title": "Death Note (Anime Series)",
        "type": "anime",
        "rating": 8.9,
        "genre": "Psychological Thriller • Supernatural",
        "audio": "Hindi Dubbed + Japanese [Dual Audio]",
        "hook": "Ek genius high-school student ko aisi diary milti hai jisme kisi ka bhi naam likhte hi uski maut ho jaati hai... Aur shuru hota hai duniya ke sabse bade detective 'L' ke saath mind games ka tufaan!",
        "search_query": "Death Note",
        "poster": "https://image.tmdb.org/t/p/w500/tCZFfYTIwrR7n94J6G14Y4hAFU6.jpg"
    },
    {
        "title": "12th Fail (2023)",
        "type": "movie",
        "rating": 8.9,
        "genre": "Biography • Drama • Inspirational",
        "audio": "Hindi Original",
        "hook": "Chambal ke gaon se nikla ek ladka jo 12th me fail ho jata hai, par aisi zidd pakadta hai ki aakhri attempt me desh ka sabse bada IPS officer ban kar dikhata hai. Har student ke roongte khade kar dene wali kahani!",
        "search_query": "12th Fail",
        "poster": "https://image.tmdb.org/t/p/w500/eebUPRI4Z5e1Z7Hev4JZAwMIFkX.jpg"
    },
    {
        "title": "Asur: Welcome to Your Dark Side",
        "type": "series",
        "rating": 8.5,
        "genre": "Mythology • Serial Killer • Thriller",
        "audio": "Hindi Original [5.1 Audio]",
        "hook": "Varanasi ki galiyon me ek shatir serial killer jo Hindu mythology aur forensic science ko mila kar aisi hatyayein karta hai ki CBI dhang reh jaati hai!",
        "search_query": "Asur",
        "poster": "https://image.tmdb.org/t/p/w500/aw8W6JCrE3zsQexfvsu4cDjb1ub.jpg"
    },
    {
        "title": "Attack on Titan (Shingeki no Kyojin)",
        "type": "anime",
        "rating": 9.1,
        "genre": "Action • Dark Fantasy • War",
        "audio": "Hindi Dubbed + Japanese",
        "hook": "Deewaron ke peeche qaid insaniyat aur unhe kacha chaba jaane wale aadamkhor Titans... Plot twists aisi jo aapko har episode ke baad baith kar sochne pe majboor kar dengi!",
        "search_query": "Attack on Titan",
        "poster": "https://image.tmdb.org/t/p/w500/hTP1DtLGFamjfu8WqjnuQdP1n4i.jpg"
    },
    {
        "title": "Tumbbad (2018)",
        "type": "movie",
        "rating": 8.2,
        "genre": "Mythological Horror • Period Drama",
        "audio": "Hindi Original [Dolby Atmos]",
        "hook": "'Dadi so rahi hai to Hastar nahi aayega...' Lalach ki aisi bhayanak kahani jo Indian cinema me pehle kabhi nahi bani! Visuals aur sound design 10/10 masterclass.",
        "search_query": "Tumbbad",
        "poster": "https://image.tmdb.org/t/p/w500/z1xOCxw780WFJC5uCTMfCkQ4Agi.jpg"
    },
    {
        "title": "All of Us Are Dead (K-Drama)",
        "type": "kdrama",
        "rating": 7.5,
        "genre": "Zombie Apocalypse • High School Survival",
        "audio": "Hindi Dubbed + Korean",
        "hook": "Ek high-school science lab se failta hai ajeeb virus, aur poora school zombies se bhar jata hai... Bina kisi hathiyar ke students ka bacho aur apno ko bachaane ka ruthless struggle!",
        "search_query": "All of Us Are Dead",
        "poster": "https://image.tmdb.org/t/p/w500/pTEFqAjLd5YTsMD6NSUxV6Dq7A6.jpg"
    },
    {
        "title": "Ratsasan (2018)",
        "type": "movie",
        "rating": 8.3,
        "genre": "Psychological Crime Thriller",
        "audio": "Hindi Dubbed + Tamil",
        "hook": "School ki masoom ladkiyon ko target karne wala ek psycho killer, jiske chehre ke peeche ek aisi kahani hai jo aapke raungte khade kar degi. India ki best serial killer movies me se ek!",
        "search_query": "Ratsasan",
        "poster": "https://image.tmdb.org/t/p/w500/mRObdeazn263na5zXzZSRJTBvi7.jpg"
    },
    {
        "title": "Chernobyl (Miniseries)",
        "type": "series",
        "rating": 9.3,
        "genre": "Historical Disaster • Drama",
        "audio": "Hindi Dubbed + English",
        "hook": "1986 me Soviet nuclear plant me dhamaka hota hai... Sach chupane ke liye neta jhooth bolte hain, par scientist aur aam logon ki qurbani dilon ko jhinjhod kar rakh deti hai!",
        "search_query": "Chernobyl",
        "poster": "https://image.tmdb.org/t/p/w500/hlLXt2tOPT6RRnjiUmoxyG1LTFi.jpg"
    },
    {
        "title": "Squid Game (K-Drama)",
        "type": "kdrama",
        "rating": 8.0,
        "genre": "Survival Thriller • Drama",
        "audio": "Hindi Dubbed + Korean",
        "hook": "Karze me doobe 456 log 45.6 Billion Won ke inaam ke liye bachpan ke aam games khelte hain... Par har game harne wale ki seedhi maut hoti hai!",
        "search_query": "Squid Game",
        "poster": "https://image.tmdb.org/t/p/w500/1QdXdRYfktUSONkl1oD5gc6Be0s.jpg"
    }
]

async def init_gems_collection():
    """Ensure pre-populated gems exist in MongoDB with verified poster URLs."""
    try:
        coll = mongo.db["hidden_gems"]
        count = await coll.count_documents({})
        if count == 0:
            for g in DEFAULT_GEMS:
                g["created_at"] = datetime.datetime.utcnow()
                g["last_shown"] = None
                await coll.insert_one(g)
            logger.info("Initialized default curated Hidden Gems pool in MongoDB.")
        else:
            # Sync any old 404/broken poster URLs in MongoDB with verified working ones
            for g in DEFAULT_GEMS:
                await coll.update_one(
                    {"search_query": g["search_query"]},
                    {"$set": {"poster": g["poster"]}}
                )
    except Exception as e:
        logger.error(f"Error initializing gems collection: {e}")


def get_rating_badge(rating: float) -> str:
    """Return dynamic badge text based on rating value."""
    if rating >= 8.5:
        return f"🏆 **ALL-TIME MASTERPIECE (IMDb: {rating}/10)**"
    elif rating >= 7.8:
        return f"🔥 **MUST WATCH MASTERPIECE (IMDb: {rating}/10)**"
    elif rating >= 7.0:
        return f"⭐ **HIGHLY RECOMMENDED (IMDb: {rating}/10)**"
    else:
        return f"🍿 **POPULAR BINGE WATCH (IMDb: {rating}/10)**"


def get_category_label(c_type: str) -> str:
    """Format category icon & name."""
    c = (c_type or "").lower()
    if "anime" in c:
        return "⛩️ **Anime Series**"
    elif "series" in c or "web" in c:
        return "📺 **Web Series**"
    elif "kdrama" in c or "k-drama" in c or "drama" in c:
        return "🎭 **K-Drama / Asian Drama**"
    else:
        return "🎬 **Movie**"


def clean_media_title(raw: str) -> str:
    """Format and strip all technical codec, site watermarks, extensions, and group episodes into clean show/movie titles."""
    if not raw:
        return "Untitled"

    from utils.helpers import parse_media_metadata
    meta = parse_media_metadata(raw)
    clean_name = meta.get("clean_name")
    if clean_name:
        year = meta.get("year")
        yr_str = f" ({year})" if year else ""
        return f"{clean_name}{yr_str}".strip()

    from utils.title_cleaner import clean_movie_title
    return clean_movie_title(raw, keep_year=True)


def get_dedup_key(title: str) -> str:
    """Extract canonical alphanumeric key to collapse duplicates across resolutions, seasons, audio, and rip variants."""
    base = re.sub(r"\b(19\d\d|20\d\d)\b", "", title.lower())
    base = re.sub(r"season\s*\d+", "", base)
    clean_base = re.sub(r"[^a-z0-9]", "", base)
    return clean_base


_RATING_CACHE: dict[str, tuple[float, int]] = {}

async def fetch_media_rating(title: str) -> tuple[float, int]:
    """Fetch TMDB rating (vote_average) and release year with memory & MongoDB caching."""
    clean_q = re.sub(r"\s*\((?:19|20)\d{2}\).*", "", title).strip()
    clean_q = re.sub(r"\s*Season.*", "", clean_q, flags=re.IGNORECASE).strip()
    clean_q = re.sub(r"[\-_:\[\]\(\)]", " ", clean_q).strip()
    clean_q = re.sub(r"\s+", " ", clean_q).strip()

    y_match = re.search(r"\b(19\d\d|20\d\d)\b", title)
    fallback_year = int(y_match.group(1)) if y_match else 0

    if not clean_q or len(clean_q) < 2:
        return 0.0, fallback_year

    cache_key = clean_q.lower()
    if cache_key in _RATING_CACHE:
        return _RATING_CACHE[cache_key]

    # Check MongoDB cache
    try:
        doc = await mongo.db["rating_cache"].find_one({"key": cache_key})
        if doc and "rating" in doc:
            res = (float(doc["rating"]), int(doc.get("year", fallback_year)))
            _RATING_CACHE[cache_key] = res
            return res
    except Exception:
        pass

    api_key = getattr(Config, "TMDB_API_KEY", "") or "56b50689afe7438a51aab0d653679865"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    encoded_q = urllib.parse.quote(clean_q)
    endpoints = [
        f"https://tmdbapi.the-zake.workers.dev/3/search/multi?api_key={api_key}&query={encoded_q}",
        f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={encoded_q}"
    ]

    try:
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3.0)) as session:
            for url in endpoints:
                try:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            results = data.get("results", [])
                            if results:
                                vote = round(float(results[0].get("vote_average") or 0.0), 1)
                                rel_date = results[0].get("release_date") or results[0].get("first_air_date") or ""
                                rel_year = int(rel_date[:4]) if rel_date and rel_date[:4].isdigit() else fallback_year
                                res = (vote, rel_year)
                                _RATING_CACHE[cache_key] = res
                                try:
                                    await mongo.db["rating_cache"].update_one(
                                        {"key": cache_key},
                                        {"$set": {"rating": vote, "year": rel_year, "title": clean_q}},
                                        upsert=True
                                    )
                                except Exception:
                                    pass
                                return res
                except Exception:
                    continue
    except Exception:
        pass

    res = (0.0, fallback_year)
    _RATING_CACHE[cache_key] = res
    return res


async def build_fresh_drops_content(bot_username: str) -> tuple[str, InlineKeyboardMarkup]:
    """Build Top Rated uploads of the day sorted by highest rating."""
    now = datetime.datetime.utcnow()
    recent_threshold = now - datetime.timedelta(hours=24)

    cursor = mongo.files.find(
        {"created_at": {"$gte": recent_threshold}},
        {"file_name": 1, "created_at": 1}
    ).sort("created_at", -1).limit(200)

    docs = await cursor.to_list(length=200)

    # Fallback to recent 200 files if nothing added in last 24h
    if len(docs) < 5:
        cursor = mongo.files.find(
            {},
            {"file_name": 1, "created_at": 1}
        ).sort("created_at", -1).limit(200)
        docs = await cursor.to_list(length=200)

    # Clean & Deduplicate titles
    seen_keys = set()
    cleaned_items = []

    for d in docs:
        raw_name = d.get("file_name", "")
        if not raw_name:
            continue
        cleaned = clean_media_title(raw_name)
        key = get_dedup_key(cleaned)

        if key and key not in seen_keys:
            seen_keys.add(key)
            cleaned_items.append(cleaned[:60])

    # If still empty, supply representative popular items
    if not cleaned_items:
        cleaned_items = [
            "Kantara (2022)",
            "Joker: Folie a Deux (2024)",
            "Asur (Season 2)",
            "Stree 2 (2024)",
            "Devara: Part 1 (2024)"
        ]

    # Fetch TMDB ratings concurrently
    rating_tasks = [fetch_media_rating(t) for t in cleaned_items[:30]]
    ratings = await asyncio.gather(*rating_tasks, return_exceptions=True)

    items_with_ratings = []
    for title, r in zip(cleaned_items[:30], ratings):
        if isinstance(r, tuple):
            vote, year = r
        else:
            vote, year = 0.0, 0
        items_with_ratings.append({
            "title": title,
            "rating": vote,
            "year": year
        })

    # Sort by rating descending (highest first), then year descending
    items_with_ratings.sort(key=lambda x: (x["rating"], x["year"]), reverse=True)

    # Take Top 5 Highest Rated uploads
    list_lines = []
    for idx, item in enumerate(items_with_ratings[:5], start=1):
        title = item["title"]
        rating = item["rating"]
        clean_param = re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_")[:55]
        deep_link = f"https://t.me/{bot_username}?start=search_{clean_param}"
        if rating > 0:
            list_lines.append(f"⭐ {idx}. <a href=\"{deep_link}\">{title}</a> — <b>{rating}/10</b>")
        else:
            list_lines.append(f"⭐ {idx}. <a href=\"{deep_link}\">{title}</a>")

    vertical_list_text = "\n".join(list_lines)

    caption = (
        "🌟 <b>AKMOVIEVERSE • TODAY TOP RATED UPLOADS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{vertical_list_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👆 <i>Click to download</i>"
    )

    channel_url = Config.CHANNEL_URL or f"https://t.me/{bot_username}"

    btn_rows = [
        [
            InlineKeyboardButton("📢 Updates Channel", url=channel_url)
        ],
        [
            InlineKeyboardButton("💎 Get Ad-Free VIP", url=f"https://t.me/{bot_username}?start=plans")
        ]
    ]

    return caption, InlineKeyboardMarkup(btn_rows)


async def build_hidden_gem_content(bot_username: str) -> tuple[str, InlineKeyboardMarkup, str | None]:
    """Build Curated Hidden Gem recommendation from genuine files existing in MongoDB."""
    await init_gems_collection()
    coll = mongo.db["hidden_gems"]

    # 1. First check if any gem in hidden_gems collection actually exists in mongo.files using real search engine!
    cursor = coll.find({}).sort("last_shown", 1)
    gem = None
    from database.files import get_search_results
    from utils.helpers import clean_search_query

    async for g in cursor:
        s_q = g.get("search_query") or g.get("title")
        if s_q:
            results = await get_search_results(clean_search_query(s_q), limit=1)
            if results:
                gem = g
                await coll.update_one({"_id": g["_id"]}, {"$set": {"last_shown": datetime.datetime.utcnow()}})
                break

    # 2. If NO curated gem exists in user's channel, dynamically pick a real movie from mongo.files!
    if not gem:
        cursor_files = mongo.files.find({}).sort("created_at", -1).limit(100)
        file_docs = await cursor_files.to_list(length=100)

        last_shown_titles = await get_bot_setting("last_shown_gem_titles", [])
        if not isinstance(last_shown_titles, list):
            last_shown_titles = []

        chosen_doc = None
        chosen_title = None

        for doc in file_docs:
            c_name = clean_media_title(doc.get("file_name", ""))
            if c_name and c_name not in last_shown_titles:
                matches = await get_search_results(clean_search_query(c_name), limit=1)
                if matches:
                    chosen_doc = doc
                    chosen_title = c_name
                    break

        if not chosen_doc and file_docs:
            chosen_doc = file_docs[0]
            chosen_title = clean_media_title(chosen_doc.get("file_name", "Must Watch Movie"))

        if not chosen_title:
            # Fallback to first default gem if library is completely empty
            gem = DEFAULT_GEMS[0]
        else:
            # Save to rotation
            last_shown_titles.append(chosen_title)
            if len(last_shown_titles) > 30:
                last_shown_titles = last_shown_titles[-30:]
            await set_bot_setting("last_shown_gem_titles", last_shown_titles)

            # Search query clean name
            search_term = re.sub(r"\s*\(?(?:19|20)\d{2}\)?.*", "", chosen_title).strip()

            # Fetch official TMDB metadata
            tmdb_meta = {}
            try:
                from plugins.channel_post import fetch_tmdb_post_metadata
                tmdb_meta = await fetch_tmdb_post_metadata(search_term or chosen_title) or {}
            except Exception as tmdb_e:
                logger.debug(f"TMDB fetch error for gem {chosen_title}: {tmdb_e}")

            rating_val = 8.2
            if tmdb_meta.get("rating_str"):
                m = re.search(r"(\d+(?:\.\d+)?)", tmdb_meta["rating_str"])
                if m:
                    rating_val = float(m.group(1))
            elif tmdb_meta.get("rating"):
                try:
                    rating_val = float(tmdb_meta["rating"])
                except Exception:
                    pass

            genre_str = " • ".join(tmdb_meta.get("genres", [])[:3]) if tmdb_meta.get("genres") else "Drama • Thriller"
            hook_str = tmdb_meta.get("overview") or "Ek shaandar release jo aapko shuru se aakhri tak baandhe rakhegi! Abhi full HD me watch ya download karein."
            if len(hook_str) > 220:
                hook_str = hook_str[:215] + "..."

            poster_url = tmdb_meta.get("backdrop_url") or tmdb_meta.get("poster_url")
            if not poster_url:
                poster_url = await get_cached_poster_url(search_term or chosen_title)

            is_series = tmdb_meta.get("media_type") == "tv" or "season" in chosen_title.lower()
            gem = {
                "title": chosen_title,
                "type": "series" if is_series else "movie",
                "rating": rating_val,
                "genre": genre_str,
                "audio": "Hindi Dubbed + Multi Audio",
                "hook": hook_str,
                "search_query": search_term or chosen_title,
                "poster": poster_url
            }

    title = gem.get("title", "Must Watch")
    g_type = gem.get("type", "movie")
    rating = gem.get("rating", 8.0)
    genre = gem.get("genre", "Drama • Thriller")
    audio = gem.get("audio", "Hindi Dubbed")
    hook = gem.get("hook", "Ek aisi kahani jo aapko hila kar rakh degi!")
    search_q = gem.get("search_query", title)
    poster = gem.get("poster")

    # If no poster set, attempt TMDB lookup
    if not poster:
        try:
            poster = await get_cached_poster_url(search_q)
        except Exception:
            poster = None

    if not poster:
        poster = getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")

    badge = get_rating_badge(rating)
    cat_label = get_category_label(g_type)

    caption = (
        "🌟 <b>AKMOVIEVERSE • FEATURED RELEASE OF THE DAY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 <b>{title}</b>\n"
        f"🏷️ <b>Category:</b> {cat_label}\n"
        f"⭐ <b>Rating:</b> <code>{rating}/10</code> | 🎭 <b>Genre:</b> {genre}\n"
        f"🎙️ <b>Audio:</b> {audio}\n\n"
        f"💬 <b>Storyline Hook:</b>\n"
        f"<i>\"{hook}\"</i>\n\n"
        f"{badge}"
    )

    clean_search_param = re.sub(r"[^a-zA-Z0-9]+", "_", search_q).strip("_")[:55]
    download_url = f"https://t.me/{bot_username}?start=search_{clean_search_param}"
    channel_url = Config.CHANNEL_URL or f"https://t.me/{bot_username}"

    # Mobile-optimized 3-row layout: no button text gets truncated on mobile screens!
    btn_rows = [
        [
            InlineKeyboardButton("⚡ Watch Online", url=download_url),
            InlineKeyboardButton("📥 Download Now", url=download_url)
        ],
        [
            InlineKeyboardButton("💎 Get Ad-Free VIP", url=f"https://t.me/{bot_username}?start=plans")
        ],
        [
            InlineKeyboardButton("📢 Join Updates Channel", url=channel_url)
        ]
    ]

    return caption, InlineKeyboardMarkup(btn_rows), poster


async def execute_broadcast_with_dead_user_purging(
    client: Client,
    text: str,
    markup: InlineKeyboardMarkup = None,
    photo_url: str = None
) -> dict:
    """Deliver broadcast to all users in MongoDB, auto-deleting blocked/deactivated users in real-time."""
    user_ids = await get_all_user_ids()
    total_users = len(user_ids)

    sent = 0
    blocked_purged = 0
    failed = 0

    for uid in user_ids:
        try:
            if photo_url:
                try:
                    await client.send_photo(
                        chat_id=uid,
                        photo=photo_url,
                        caption=text,
                        reply_markup=markup
                    )
                except Exception as p_err:
                    logger.warning(f"send_photo failed for user {uid} ({p_err}). Retrying with text message fallback...")
                    await client.send_message(
                        chat_id=uid,
                        text=text,
                        reply_markup=markup,
                        disable_web_page_preview=True
                    )
            else:
                await client.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=markup,
                    disable_web_page_preview=True
                )
            sent += 1
            await asyncio.sleep(0.04)  # ~25 msgs/sec safe rate
        except FloodWait as fw:
            await asyncio.sleep(fw.value + 1)
            try:
                if photo_url:
                    try:
                        await client.send_photo(chat_id=uid, photo=photo_url, caption=text, reply_markup=markup)
                    except Exception:
                        await client.send_message(chat_id=uid, text=text, reply_markup=markup, disable_web_page_preview=True)
                else:
                    await client.send_message(chat_id=uid, text=text, reply_markup=markup, disable_web_page_preview=True)
                sent += 1
            except Exception as e2:
                failed += 1
                logger.warning(f"Broadcast delivery retry failed for user {uid}: {e2}")
        except (UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid):
            blocked_purged += 1
            try:
                # 🧹 Real-time Auto-Purge: Delete dead/blocked user from MongoDB
                await mongo.users.delete_one({"user_id": uid})
            except Exception as del_err:
                logger.debug(f"Could not purge dead user {uid}: {del_err}")
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast delivery failed for user {uid}: {e}")

    return {
        "total": total_users,
        "sent": sent,
        "purged": blocked_purged,
        "failed": failed
    }


# Background Daily Scheduler Task
_DAILY_SCHEDULER_RUNNING = False

async def start_daily_broadcast_scheduler(client: Client):
    """Background async daemon that evaluates daily broadcast schedule every 30 seconds."""
    global _DAILY_SCHEDULER_RUNNING
    if _DAILY_SCHEDULER_RUNNING:
        return
    _DAILY_SCHEDULER_RUNNING = True
    logger.info("Daily Auto-Broadcast Scheduler task started.")

    while True:
        try:
            await asyncio.sleep(30)

            # Check if enabled
            enabled = await get_bot_setting("daily_broadcast_enabled", True)
            if not enabled:
                continue

            # Read scheduled time (Default: 20:00 IST = 8:00 PM)
            sched_time_str = await get_bot_setting("daily_broadcast_time", "20:00")
            try:
                sched_hour, sched_min = map(int, sched_time_str.split(":"))
            except Exception:
                sched_hour, sched_min = 20, 0

            # Current time in IST (UTC + 5:30)
            now_utc = datetime.datetime.utcnow()
            now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
            today_str = now_ist.strftime("%Y-%m-%d")

            last_sent_date = await get_bot_setting("last_broadcast_date", "")
            if last_sent_date == today_str:
                # Already sent today
                continue

            # Trigger window: if current IST matches target hour & minute
            if now_ist.hour == sched_hour and now_ist.minute >= sched_min:
                logger.info(f"Triggering scheduled daily broadcast for {today_str} (IST {now_ist.strftime('%H:%M')})...")

                bot_username = client.me.username if client.me else Config.BOT_USERNAME

                # Always broadcast rich Poster + Card Style (Featured Release / Gem with HD Poster)
                broadcast_type = "poster_card"
                text, markup, photo = await build_hidden_gem_content(bot_username)
                if not photo:
                    photo = getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")

                # Execute with dead user pruning
                stats = await execute_broadcast_with_dead_user_purging(client, text, markup, photo)

                if stats.get("sent", 0) > 0:
                    await set_bot_setting("last_broadcast_date", today_str)

                # Report to Log Channel & Admins
                summary_report = (
                    f"📢 <b>Daily Automated Broadcast Dispatched!</b>\n\n"
                    f"📅 <b>Date:</b> <code>{today_str}</code> (IST: <code>{now_ist.strftime('%H:%M')}</code>)\n"
                    f"🎯 <b>Type:</b> <code>{broadcast_type.upper()}</code>\n"
                    f"👥 <b>Target Users:</b> <code>{stats['total']:,}</code>\n"
                    f"✅ <b>Successfully Delivered:</b> <code>{stats['sent']:,}</code>\n"
                    f"🧹 <b>Dead / Blocked Users Purged from DB:</b> <code>{stats['purged']:,}</code>\n"
                    f"⚠️ <b>Failed / Network:</b> <code>{stats['failed']:,}</code>"
                )

                if Config.LOG_CHANNEL:
                    try:
                        await client.send_message(Config.LOG_CHANNEL, summary_report)
                    except Exception as log_e:
                        logger.warning(f"Could not log broadcast report: {log_e}")

        except Exception as loop_e:
            logger.error(f"Error in daily broadcast scheduler: {loop_e}", exc_info=True)
            await asyncio.sleep(60)


# ==============================================================================
# Admin Commands for Daily Broadcast Control & Testing
# ==============================================================================

@Client.on_message(filters.command("dailybroadcast") & filters.private)
async def toggle_daily_broadcast_command(client: Client, message: Message):
    """Admin command: /dailybroadcast [on|off|status]"""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**: Admin privileges required.")

    args = message.text.split()
    if len(args) > 1:
        arg = args[1].lower()
        if arg == "on":
            await set_bot_setting("daily_broadcast_enabled", True)
            return await message.reply_text("✅ **Daily Auto-Broadcast Enabled!**\nScheduled broadcasts will run daily at the configured time.")
        elif arg == "off":
            await set_bot_setting("daily_broadcast_enabled", False)
            return await message.reply_text("⏸️ **Daily Auto-Broadcast Paused!**\nNo automated broadcasts will be sent until re-enabled.")

    enabled = await get_bot_setting("daily_broadcast_enabled", True)
    sched_time = await get_bot_setting("daily_broadcast_time", "20:00")
    last_sent = await get_bot_setting("last_broadcast_date", "None")

    status_str = "🟢 **ENABLED**" if enabled else "🔴 **DISABLED**"
    await message.reply_text(
        f"📊 **Daily Auto-Broadcast Status**\n\n"
        f"• **Status:** {status_str}\n"
        f"• **Scheduled Time (IST):** `{sched_time}` (8:00 PM)\n"
        f"• **Last Sent Date:** `{last_sent}`\n"
        f"• **Schedule Format:**\n"
        f"  - _Mon–Thu:_ 🚀 Fresh Drops (Vertical Blockquote List)\n"
        f"  - _Fri–Sun:_ 🌟 Hidden Gem (Movie/Anime/Series/K-Drama)\n\n"
        f"**Commands:**\n"
        f"• `/dailybroadcast [on|off]`\n"
        f"• `/set_broadcast_time <HH:MM>` (e.g. `/set_broadcast_time 20:30`)\n"
        f"• `/test_broadcast [fresh|gem]` (Preview in your PM)\n"
        f"• `/send_broadcast [fresh|gem]` (Send to all users now)"
    )


@Client.on_message(filters.command("set_broadcast_time") & filters.private)
async def set_broadcast_time_command(client: Client, message: Message):
    """Admin command: /set_broadcast_time <HH:MM> (e.g. 20:00 for 8 PM IST)"""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    args = message.text.split()
    if len(args) < 2 or not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", args[1]):
        return await message.reply_text("⚠️ **Usage:** `/set_broadcast_time <HH:MM>` in 24-hour IST format.\nExample: `/set_broadcast_time 20:00` (8:00 PM)")

    new_time = args[1]
    await set_bot_setting("daily_broadcast_time", new_time)
    await message.reply_text(f"✅ **Broadcast Time Updated!**\nDaily auto-broadcast will now trigger at **{new_time} IST**.")


@Client.on_message(filters.command("test_broadcast") & filters.private)
async def test_broadcast_command(client: Client, message: Message):
    """Admin command: /test_broadcast [card|text] - Send preview to Admin PM only."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    args = message.text.split()
    b_type = args[1].lower() if len(args) > 1 else "card"
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    status = await message.reply_text("⏳ **Generating test preview...**")

    try:
        if b_type.startswith("fresh") or b_type.startswith("text"):
            text, markup = await build_fresh_drops_content(bot_username)
            await status.delete()
            await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        else:
            text, markup, photo = await build_hidden_gem_content(bot_username)
            photo = photo or getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")
            await status.delete()
            await message.reply_photo(photo=photo, caption=text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error in test broadcast: {e}", exc_info=True)
        await status.edit_text(f"❌ **Error generating preview:** `{e}`")


@Client.on_message(filters.command("send_broadcast") & filters.private)
async def manual_send_broadcast_command(client: Client, message: Message):
    """Admin command: /send_broadcast [card|text] - Manually broadcast to all users right now."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    args = message.text.split()
    b_type = args[1].lower() if len(args) > 1 else "card"
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    status = await message.reply_text(f"🚀 **Preparing and launching manual `{b_type}` broadcast...**")

    try:
        if b_type.startswith("fresh") or b_type.startswith("text"):
            text, markup = await build_fresh_drops_content(bot_username)
            photo = None
        else:
            text, markup, photo = await build_hidden_gem_content(bot_username)
            photo = photo or getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")

        await status.edit_text("📢 **Broadcasting to all registered users... Auto-purging blocked accounts...**")
        stats = await execute_broadcast_with_dead_user_purging(client, text, markup, photo)

        await status.edit_text(
            f"🎉 **Manual Broadcast Complete!**\n\n"
            f"🎯 **Type:** `{b_type.upper()}`\n"
            f"👥 **Total Users:** `{stats['total']:,}`\n"
            f"✅ **Delivered:** `{stats['sent']:,}`\n"
            f"🧹 **Blocked/Deleted Purged from DB:** `{stats['purged']:,}`\n"
            f"⚠️ **Failed:** `{stats['failed']:,}`"
        )
    except Exception as e:
        logger.error(f"Error in manual broadcast: {e}", exc_info=True)
        await status.edit_text(f"❌ **Broadcast Failed:** `{e}`")


@Client.on_message(filters.command("addgem") & filters.private)
async def add_gem_command(client: Client, message: Message):
    """Admin command: /addgem <title> | <type> | <rating> | <hook> [| poster_url]
    Example:
    /addgem Death Note | anime | 8.9 | Ek aisi diary jisme naam likhne se maut hoti hai...
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or "|" not in raw[1]:
        return await message.reply_text(
            "ℹ️ **Usage to Add a Hidden Gem:**\n"
            "`/addgem <Title> | <Category: movie/anime/series/kdrama> | <Rating: 1-10> | <Hook Description> [| Poster URL]`\n\n"
            "Example:\n"
            "`/addgem Maharaja | movie | 8.5 | Ek barber ka dustbin chori ho jata hai aur aakhri 30 min hosh uda denge!`"
        )

    parts = [p.strip() for p in raw[1].split("|")]
    if len(parts) < 4:
        return await message.reply_text("❌ Please provide at least 4 fields: `Title | Type | Rating | Hook`.")

    title = parts[0]
    g_type = parts[1].lower()
    try:
        rating = float(parts[2])
    except ValueError:
        return await message.reply_text("❌ Rating must be a number (e.g. 8.5).")

    hook = parts[3]
    poster = parts[4] if len(parts) > 4 else None

    doc = {
        "title": title,
        "type": g_type,
        "rating": rating,
        "genre": "Curated Masterpiece",
        "audio": "Hindi Dubbed",
        "hook": hook,
        "search_query": title,
        "poster": poster,
        "last_shown": None,
        "created_at": datetime.datetime.utcnow()
    }

    await mongo.db["hidden_gems"].insert_one(doc)
    badge = get_rating_badge(rating)
    await message.reply_text(
        f"✅ **Added to Hidden Gems Rotation!**\n\n"
        f"🎬 **Title:** `{title}`\n"
        f"🏷️ **Category:** {get_category_label(g_type)}\n"
        f"⭐ **Rating Badge:** {badge}\n"
        f"💬 **Hook:** _{hook}_"
    )


@Client.on_message(filters.command("listgems") & filters.private)
async def list_gems_command(client: Client, message: Message):
    """Admin command: /listgems - List active gems in database rotation."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    await init_gems_collection()
    cursor = mongo.db["hidden_gems"].find({}).sort("rating", -1)
    gems = await cursor.to_list(length=50)

    if not gems:
        return await message.reply_text("ℹ️ No hidden gems found in database.")

    lines = []
    for idx, g in enumerate(gems, start=1):
        c_label = get_category_label(g.get("type", "movie"))
        lines.append(f"{idx}. **{g['title']}** — {c_label} • ⭐ `{g.get('rating')}/10`")

    text = (
        f"💎 **Active Hidden Gems Pool ({len(gems)} items)**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n" +
        "\n".join(lines[:30]) +
        f"\n\n_To add a new gem: use /addgem_"
    )

    await message.reply_text(text)
