import re
import html
import asyncio
import logging
import datetime
import urllib.parse
import aiohttp
import uuid
import random

try:
    from hydrogram import Client, filters, enums
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
    from hydrogram.errors import FloodWait, MessageNotModified, MessageIdInvalid
except ImportError:
    from pyrogram import Client, filters, enums
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
    from pyrogram.errors import FloodWait, MessageNotModified, MessageIdInvalid

from config import Config
from database.mongo import mongo
from database.files import _build_search_filter
from utils.helpers import parse_media_metadata, get_cached_poster_url
from utils.web_server import get_grouped_catalog

logger = logging.getLogger(__name__)

# Global runtime state & per-title debounce buffers
_AUTO_POST_TIMERS = {}
_AUTO_POST_PREFS = {"enabled": None, "channel_id": None}
_TMDB_POST_CACHE = {}
_POST_LOCKS: dict[str, asyncio.Lock] = {}
_DRAFT_PREVIEWS: dict[str, dict] = {}


def _get_post_lock(group_key: str) -> asyncio.Lock:
    if group_key not in _POST_LOCKS:
        _POST_LOCKS[group_key] = asyncio.Lock()
    return _POST_LOCKS[group_key]


async def is_autopost_enabled() -> bool:
    """Check whether auto-posting is currently enabled (runtime setting with config fallback)."""
    if _AUTO_POST_PREFS["enabled"] is not None:
        return _AUTO_POST_PREFS["enabled"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "autopost"})
        if doc and "enabled" in doc:
            _AUTO_POST_PREFS["enabled"] = bool(doc["enabled"])
            return _AUTO_POST_PREFS["enabled"]
    except Exception:
        pass
    return getattr(Config, "AUTO_POST_ENABLED", True)


async def get_target_updates_channel() -> int:
    """Get the target updates channel ID (runtime setting with config fallback)."""
    if _AUTO_POST_PREFS["channel_id"] is not None:
        return _AUTO_POST_PREFS["channel_id"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "autopost"})
        if doc and doc.get("channel_id"):
            _AUTO_POST_PREFS["channel_id"] = int(doc["channel_id"])
            return _AUTO_POST_PREFS["channel_id"]
    except Exception:
        pass
    return getattr(Config, "UPDATES_CHANNEL", -1003537939374)


async def set_autopost_state(enabled: bool = None, channel_id: int = None):
    """Persist autopost preferences to MongoDB."""
    updates = {}
    if enabled is not None:
        _AUTO_POST_PREFS["enabled"] = enabled
        updates["enabled"] = enabled
    if channel_id is not None:
        _AUTO_POST_PREFS["channel_id"] = channel_id
        updates["channel_id"] = channel_id

    if updates:
        try:
            await mongo.db["bot_settings"].update_one(
                {"key": "autopost"},
                {"$set": updates},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error persisting autopost settings: {e}")


# Auto Reactions on Channel Posts
_AUTO_REACTION_PREFS = {"enabled": None, "emojis": None}
DEFAULT_REACTION_EMOJIS = ["🔥", "❤️", "🍿", "⚡", "🎉", "😍", "👍"]


async def is_auto_reaction_enabled() -> bool:
    """Check whether auto reactions on channel posts are enabled."""
    if _AUTO_REACTION_PREFS["enabled"] is not None:
        return _AUTO_REACTION_PREFS["enabled"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "auto_post_reactions"})
        if doc and "enabled" in doc:
            _AUTO_REACTION_PREFS["enabled"] = bool(doc["enabled"])
            return _AUTO_REACTION_PREFS["enabled"]
    except Exception:
        pass
    return True  # Enabled by default


async def get_auto_reaction_emojis() -> list[str]:
    """Retrieve pool of emojis used for automatic channel reactions."""
    if _AUTO_REACTION_PREFS["emojis"] is not None:
        return _AUTO_REACTION_PREFS["emojis"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "auto_post_reactions"})
        if doc and doc.get("emojis"):
            _AUTO_REACTION_PREFS["emojis"] = list(doc["emojis"])
            return _AUTO_REACTION_PREFS["emojis"]
    except Exception:
        pass
    return DEFAULT_REACTION_EMOJIS


async def set_auto_reaction_state(enabled: bool = None, emojis: list[str] = None):
    """Persist auto reaction state & emojis to MongoDB."""
    updates = {}
    if enabled is not None:
        _AUTO_REACTION_PREFS["enabled"] = enabled
        updates["enabled"] = enabled
    if emojis is not None:
        _AUTO_REACTION_PREFS["emojis"] = emojis
        updates["emojis"] = emojis

    if updates:
        try:
            await mongo.db["bot_settings"].update_one(
                {"key": "auto_post_reactions"},
                {"$set": updates},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error persisting auto reaction settings: {e}")


# Channel Post "Watch Online" Button Setting
_AUTO_POST_WATCH_PREF = {"enabled": None}


async def is_auto_post_watch_enabled() -> bool:
    """Check whether Watch Online button is enabled on channel posts. Defaults to False."""
    if _AUTO_POST_WATCH_PREF["enabled"] is not None:
        return _AUTO_POST_WATCH_PREF["enabled"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "auto_post_watch"})
        if doc and "enabled" in doc:
            _AUTO_POST_WATCH_PREF["enabled"] = bool(doc["enabled"])
            return _AUTO_POST_WATCH_PREF["enabled"]
    except Exception:
        pass
    return False  # Disabled by default per user request


async def set_auto_post_watch_state(enabled: bool):
    """Persist auto post watch online button state to MongoDB."""
    _AUTO_POST_WATCH_PREF["enabled"] = enabled
    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "auto_post_watch"},
            {"$set": {"enabled": enabled}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error persisting auto_post_watch: {e}")


async def fetch_tmdb_post_metadata(title: str, year: int = None, is_series: bool = False) -> dict:
    """Fetch official TMDB metadata (16:9 Backdrop, 2:3 Poster, Genres, OTT Platform, Storyline, Rating)."""
    from utils.title_cleaner import clean_movie_title, is_tmdb_match_valid

    # Master title sanitization: Strip website watermarks, ripper tags, clutter
    clean_q = clean_movie_title(title, keep_year=False)
    clean_q = re.sub(r"\s*\((?:19|20)\d{2}\).*", "", clean_q).strip()
    clean_q = re.sub(r"\s*Season.*", "", clean_q, flags=re.IGNORECASE).strip()
    clean_q = re.sub(r"[\-_:\[\]\(\)]", " ", clean_q).strip()
    clean_q = re.sub(r"\s+", " ", clean_q)

    cache_key = f"{clean_q.lower()}:{year or ''}:{1 if is_series else 0}"
    if cache_key in _TMDB_POST_CACHE:
        return _TMDB_POST_CACHE[cache_key]

    # Check custom manual poster override first!
    try:
        norm_key = re.sub(r"[^\w]", "", clean_q.lower())
        custom_doc = await mongo.db["custom_posters"].find_one({
            "$or": [{"key": norm_key}, {"title": clean_q}]
        })
        if custom_doc and custom_doc.get("poster_url"):
            custom_url = custom_doc["poster_url"]
            if cache_key in _TMDB_POST_CACHE:
                cached_data = _TMDB_POST_CACHE[cache_key]
                cached_data["poster_url"] = custom_url
                cached_data["backdrop_url"] = custom_url
                if custom_url not in cached_data.get("gallery", []):
                    cached_data["gallery"] = [custom_url] + cached_data.get("gallery", [])
                return cached_data
    except Exception:
        pass

    # Check MongoDB cache (require gallery to be present)
    try:
        cached_doc = await mongo.db["tmdb_post_cache"].find_one({"key": cache_key})
        if cached_doc and cached_doc.get("data") and len(cached_doc["data"].get("gallery", [])) >= 2:
            _TMDB_POST_CACHE[cache_key] = cached_doc["data"]
            return cached_doc["data"]
    except Exception:
        pass

    api_key = getattr(Config, "TMDB_API_KEY", "") or "56b50689afe7438a51aab0d653679865"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    result_data = {
        "title": title,
        "year": year,
        "rating": 0.0,
        "genres": [],
        "ott": "N/A",
        "overview": "",
        "backdrop_url": "",
        "poster_url": ""
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0)) as session:
            encoded = urllib.parse.quote(clean_q)
            search_url = f"https://tmdbapi.the-zake.workers.dev/3/search/multi?api_key={api_key}&query={encoded}"
            async with session.get(search_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        # Anti-Hallucination Guard: Filter only candidates that actually match the searched title
                        valid_candidates = []
                        for r in results:
                            res_title = r.get("title") or r.get("name") or ""
                            if is_tmdb_match_valid(clean_q, res_title):
                                valid_candidates.append(r)

                        if valid_candidates:
                            chosen = valid_candidates[0]
                            for r in valid_candidates:
                                m_type = r.get("media_type")
                                if is_series and m_type == "tv":
                                    chosen = r
                                    break
                                elif not is_series and m_type == "movie":
                                    chosen = r
                                    break

                            m_id = chosen.get("id")
                            m_type = chosen.get("media_type", "movie" if not is_series else "tv")
                            vote = chosen.get("vote_average") or 0.0
                            result_data["rating"] = round(float(vote), 1)
                            if chosen.get("overview"):
                                result_data["overview"] = chosen["overview"]

                        if chosen.get("backdrop_path"):
                            result_data["backdrop_url"] = f"https://image.tmdb.org/t/p/w1280{chosen['backdrop_path']}"
                        if chosen.get("poster_path"):
                            result_data["poster_url"] = f"https://image.tmdb.org/t/p/w780{chosen['poster_path']}"

                        # Fetch detail for genres, images gallery and OTT watch providers
                        detail_url = f"https://tmdbapi.the-zake.workers.dev/3/{m_type}/{m_id}?api_key={api_key}&append_to_response=images,watch/providers"
                        async with session.get(detail_url, headers=headers) as d_resp:
                            if d_resp.status == 200:
                                d_data = await d_resp.json()
                                result_data["genres"] = [g.get("name") for g in d_data.get("genres", []) if g.get("name")]
                                if not result_data["overview"] and d_data.get("overview"):
                                    result_data["overview"] = d_data["overview"]

                                # Images Gallery (Top backdrops + Top posters)
                                imgs_data = d_data.get("images", {})
                                gallery = []
                                for b in imgs_data.get("backdrops", [])[:6]:
                                    fp = b.get("file_path")
                                    if fp:
                                        gallery.append(f"https://image.tmdb.org/t/p/w1280{fp}")
                                for p in imgs_data.get("posters", [])[:6]:
                                    fp = p.get("file_path")
                                    if fp:
                                        gallery.append(f"https://image.tmdb.org/t/p/w780{fp}")
                                result_data["gallery"] = gallery

                                # OTT / Watch providers (India or global)
                                providers_data = d_data.get("watch/providers", {}).get("results", {})
                                in_prov = providers_data.get("IN", {}) or providers_data.get("US", {})
                                flatrate = in_prov.get("flatrate", [])
                                if flatrate:
                                    ott_list = [p.get("provider_name") for p in flatrate if p.get("provider_name")]
                                    if ott_list:
                                        result_data["ott"] = ", ".join(ott_list[:2])
    except Exception as e:
        logger.debug(f"TMDB post metadata fetch error for {title}: {e}")

    # Fallback gallery if empty
    if not result_data.get("gallery"):
        gal = []
        if result_data.get("backdrop_url"):
            gal.append(result_data["backdrop_url"])
        if result_data.get("poster_url") and result_data["poster_url"] not in gal:
            gal.append(result_data["poster_url"])
        result_data["gallery"] = gal

    # Inject custom manual poster override into result_data
    try:
        norm_key = re.sub(r"[^\w]", "", clean_q.lower())
        custom_doc = await mongo.db["custom_posters"].find_one({
            "$or": [{"key": norm_key}, {"title": clean_q}]
        })
        if custom_doc and custom_doc.get("poster_url"):
            custom_url = custom_doc["poster_url"]
            result_data["poster_url"] = custom_url
            result_data["backdrop_url"] = custom_url
            result_data["gallery"] = [custom_url] + [g for g in result_data.get("gallery", []) if g != custom_url]
    except Exception:
        pass

    # Fallback poster from poster cache if TMDB gave no image
    if not result_data["poster_url"] and not result_data["backdrop_url"]:
        cached_p = await get_cached_poster_url(clean_q)
        if cached_p:
            result_data["poster_url"] = cached_p
            result_data["backdrop_url"] = cached_p
            if not result_data.get("gallery"):
                result_data["gallery"] = [cached_p]

    # Save to MongoDB cache
    _TMDB_POST_CACHE[cache_key] = result_data
    try:
        asyncio.create_task(
            mongo.db["tmdb_post_cache"].update_one(
                {"key": cache_key},
                {"$set": {"data": result_data, "updated_at": datetime.datetime.utcnow()}},
                upsert=True
            )
        )
    except Exception:
        pass

    return result_data


async def get_autopost_style() -> int:
    """Retrieve active auto-post style: 1 = Cinematic Widescreen, 2 = Minimalist Single-Poster, 3 = Compact Text, 4 = Ultra-Clean Compact (Format 1)."""
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "autopost_style"})
        if doc and "style" in doc:
            return int(doc["style"])
    except Exception:
        pass
    return 4


async def set_autopost_style(style_id: int):
    """Set active auto-post style in MongoDB."""
    await mongo.db["bot_settings"].update_one(
        {"key": "autopost_style"},
        {"$set": {"style": int(style_id)}},
        upsert=True
    )


def format_episodes_range(episodes: list, has_complete_pack: bool = False) -> str:
    """Format episode numbers into clean contiguous ranges, e.g. '1-12' or '1-3, 5, 7-12'."""
    if not episodes and has_complete_pack:
        return "Complete Season"
    if not episodes:
        return "Complete"

    # Deduplicate and sort numerically
    valid_eps = [int(e) for e in episodes if str(e).isdigit()]
    if not valid_eps:
        return "Complete Season" if has_complete_pack else "Complete"

    sorted_eps = sorted(set(valid_eps))
    ranges = []
    start = sorted_eps[0]
    prev = sorted_eps[0]

    for ep in sorted_eps[1:]:
        if ep == prev + 1:
            prev = ep
        else:
            if start == prev:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{prev}")
            start = ep
            prev = ep

    if start == prev:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{prev}")

    res = ", ".join(ranges)
    if has_complete_pack:
        res += " (Pack)"
    return res


def format_post_caption(group: dict, tmdb_data: dict, style: int = 1) -> str:
    """Format the post caption in chosen style matching Screenshot 2 layout."""
    raw_title = group.get("title") or group.get("clean_name", "Movie")
    from utils.title_cleaner import clean_movie_title
    title = clean_movie_title(raw_title, keep_year=False)
    # Strip any trailing season or year tags from title string
    title = re.sub(r"\s*\(?(?:19|20)\d{2}\)?.*", "", title).strip()
    title = re.sub(r"\s*Season.*", "", title, flags=re.IGNORECASE).strip()

    year = group.get("year") or tmdb_data.get("year")
    yr_str = f" ({year})" if year else ""
    full_title = f"{title}{yr_str}".strip()

    # 1. Rating
    rating_str = tmdb_data.get("rating_str")
    if not rating_str:
        rating = tmdb_data.get("rating", 0.0)
        rating_str = f"{float(rating):.1f}/10 IMDb" if rating and float(rating) > 0 else "8.0/10 IMDb"

    # 2. Genres
    genres = tmdb_data.get("genres", [])
    genres_str = ", ".join(genres[:3]) if genres else "Action, Drama"

    # 3. Audio detection
    langs = group.get("languages_list", [])
    if "Dual Audio" in langs or len(langs) >= 2:
        audio_str = "Dual Audio [" + " + ".join([l for l in langs if l != "Dual Audio"] or ["Hindi", "English"]) + "]"
    elif langs:
        audio_str = ", ".join(langs)
    else:
        fn_all = " ".join([f.get("file_name", "") for f in group.get("files", [])]).lower()
        found_langs = []
        for l_name in ["Hindi", "English", "Telugu", "Tamil", "Kannada", "Malayalam", "Bengali", "Marathi", "Punjabi"]:
            if l_name.lower() in fn_all:
                found_langs.append(l_name)
        if len(found_langs) >= 2:
            audio_str = ", ".join(found_langs[:3])
        elif found_langs:
            audio_str = ", ".join(found_langs)
        elif "dual" in fn_all:
            audio_str = "Dual Audio [Hindi + English]"
        else:
            audio_str = "Hindi"

    # 4. Clean Quality line (e.g. 1080p, bluray or 1080p, 720p, hevc)
    sorted_q = group.get("sorted_qualities", [])
    fn_all = " ".join([f.get("file_name", "") for f in group.get("files", [])]).lower()
    has_hevc = "hevc" in fn_all or "x265" in fn_all or "10bit" in fn_all
    has_bluray = "bluray" in fn_all or "blu-ray" in fn_all or "bdrip" in fn_all
    has_web = "web-dl" in fn_all or "webrip" in fn_all or "web" in fn_all

    q_parts = []
    if sorted_q:
        q_parts.extend([q.lower() for q in sorted_q])
    else:
        q_parts.append("1080p")

    if has_bluray and "bluray" not in q_parts:
        q_parts.append("bluray")
    elif has_web and "web-dl" not in q_parts:
        q_parts.append("web-dl")
    if has_hevc and "hevc" not in q_parts:
        q_parts.append("hevc")

    quality_str = ", ".join(q_parts)

    # 5. OTT Platform
    ott = tmdb_data.get("ott")
    if not ott or ott == "N/A":
        fn_all_upper = " ".join([f.get("file_name", "") for f in group.get("files", [])]).upper()
        if "NF" in fn_all_upper or "NETFLIX" in fn_all_upper:
            ott = "Netflix"
        elif "AMZN" in fn_all_upper or "PRIME" in fn_all_upper:
            ott = "Amazon Prime Video"
        elif "DSNP" in fn_all_upper or "HOTSTAR" in fn_all_upper:
            ott = "Disney+ Hotstar"
        elif "ZEE5" in fn_all_upper:
            ott = "ZEE5"
        elif "JIOCINEMA" in fn_all_upper:
            ott = "JioCinema"
        else:
            ott = "N/A"

    # 6. Series Episodes lines (Unified multi-season layout matching Screenshot 2)
    is_series = group.get("is_series", False)
    episodes_section = ""
    if is_series:
        ep_lines = []
        seasons_map = group.get("seasons_map", {})
        if seasons_map:
            for s_num in sorted(seasons_map.keys()):
                s_info = seasons_map[s_num]
                eps_list = list(s_info.get("episodes", []))
                has_pack = s_info.get("has_pack", False)
                range_str = format_episodes_range(eps_list, has_pack)
                ep_lines.append(f"S{s_num}: {range_str}")
        elif group.get("episodes_map"):
            s_num = group.get("season", 1)
            eps_list = list(group["episodes_map"].keys())
            range_str = format_episodes_range(eps_list)
            ep_lines.append(f"S{s_num}: {range_str}")

        if ep_lines:
            episodes_str = "\n".join(ep_lines)
            episodes_section = f"📺 <b>Episodes :</b>\n{episodes_str}"
        else:
            episodes_section = "📺 <b>Episodes :</b> All Episodes Available"

    # 7. Storyline for movies & series (Guaranteed fallback so Telegram blockquote ALWAYS collapses!)
    overview = (tmdb_data.get("overview") or "").strip()
    if not overview:
        if is_series:
            overview = f"Follow the complete gripping story and full season episodes of {title} in ultra high-definition with multi-audio and verified fast streaming links."
        else:
            overview = f"Stream and download {title} in multiple resolutions with crystal clear audio, verified prints, and fast direct links."
    else:
        if len(overview) > 260:
            overview = overview[:257].rsplit(" ", 1)[0] + "..."

    bot_username = Config.BOT_USERNAME or "bot"

    if style == 4:
        # Style 4: Ultra-Clean Compact 4-Line (Format 1 - No Fluff, No Blockquotes)
        caption = (
            f"🎬 <b>{html.escape(full_title)}</b>\n"
            f"⭐ <b>{rating_str}</b> • {html.escape(genres_str)}\n"
            f"🌐 <b>Audio:</b> {html.escape(audio_str)}\n"
            f"💿 <b>Quality:</b> {html.escape(quality_str)}"
        )
        if is_series:
            caption += f"\n{episodes_section}"

    elif style == 2:
        # Style 2: Minimalist Single-Poster
        caption = (
            f"🎬 <b>Title :</b> {html.escape(full_title)}\n"
            f"⭐ <b>Rating :</b> {rating_str}\n"
            f"🎭 <b>Genres :</b> {html.escape(genres_str)}\n"
            f"🌐 <b>Audio :</b> {html.escape(audio_str)}\n"
            f"🎬 <b>Quality :</b> {html.escape(quality_str)}"
        )
        if is_series:
            caption += f"\n{episodes_section}"
        else:
            caption += f"\n📺 <b>OTT :</b> {html.escape(ott)}"

    elif style == 3:
        # Style 3: Clean Compact Text Release
        header = "🎬 <b>#Series</b>" if is_series else "🎬 <b>#Movie</b>"
        caption = (
            f"{header} <b>{html.escape(full_title)}</b>\n"
            f"⭐ <b>Rating :</b> {rating_str} | 📺 <b>OTT :</b> {html.escape(ott)}\n"
            f"📦 <b>Qualities :</b> <code>{html.escape(quality_str)}</code>\n"
            f"🌐 <b>Audio :</b> {html.escape(audio_str)}"
        )
        if is_series:
            caption += f"\n{episodes_section}"

    else:
        # Style 1: Cinematic Expandable Dropdown (Collapsible Blockquote)
        header_tag = "📬 <b>New #SERIES Added</b>" if is_series else "📬 <b>New #MOVIE Added</b>"
        caption = (
            f"{header_tag}\n\n"
            f"✨ <b>Title :</b> {html.escape(full_title)}\n"
            f"⭐ <b>Rating :</b> {rating_str}\n\n"
            f"<blockquote expandable>"
            f"🎭 <b>Genres :</b> {html.escape(genres_str)}\n"
            f"📺 <b>OTT :</b> {html.escape(ott)}\n"
            f"🎬 <b>Quality :</b> {html.escape(quality_str)}\n"
            f"🌐 <b>Audio :</b> {html.escape(audio_str)}"
        )
        if is_series:
            caption += f"\n\n{episodes_section}"
        caption += f"\n\n📝 <b>Storyline :</b>\n<i>{html.escape(overview)}</i>"
        caption += "\n</blockquote>"

    return caption


_CUSTOM_BTN_CACHE = {"btn": None, "loaded": False}


async def get_autopost_custom_button() -> dict | None:
    """Retrieve custom promotional button for channel posts: {'text': ..., 'url': ...} or None."""
    if _CUSTOM_BTN_CACHE["loaded"]:
        return _CUSTOM_BTN_CACHE["btn"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "autopost_custom_btn"})
        if doc and doc.get("text") and doc.get("url"):
            _CUSTOM_BTN_CACHE["btn"] = {"text": doc["text"], "url": doc["url"]}
        else:
            _CUSTOM_BTN_CACHE["btn"] = None
        _CUSTOM_BTN_CACHE["loaded"] = True
        return _CUSTOM_BTN_CACHE["btn"]
    except Exception:
        return None


async def set_autopost_custom_button(text: str | None, url: str | None):
    """Set or remove custom promotional button for channel posts in MongoDB."""
    _CUSTOM_BTN_CACHE["loaded"] = True
    if text and url:
        _CUSTOM_BTN_CACHE["btn"] = {"text": text, "url": url}
        await mongo.db["bot_settings"].update_one(
            {"key": "autopost_custom_btn"},
            {"$set": {"text": text, "url": url}},
            upsert=True
        )
    else:
        _CUSTOM_BTN_CACHE["btn"] = None
        await mongo.db["bot_settings"].delete_one({"key": "autopost_custom_btn"})


def build_post_buttons(group: dict, custom_btn: dict | None = None, enable_watch: bool | None = None) -> InlineKeyboardMarkup:
    """Build channel post buttons: [🤖 Get File], optional [▶️ Watch Online], and optional custom button."""
    web_url = getattr(Config, "WEB_URL", "http://127.0.0.1:8088").rstrip("/")
    bot_username = Config.BOT_USERNAME or "bot"

    clean_name = group.get("clean_name", "")
    is_series = group.get("is_series", False)
    files = group.get("files", [])
    qualities = group.get("qualities", set())
    encoded_name = urllib.parse.quote_plus(clean_name)

    if is_series:
        slug = group.get("slug") or re.sub(r"[^\w\-]", "-", clean_name.lower())
        watch_url = f"{web_url}/series/{slug}"
        # Series: Route to Smart Navigator with Season and Episode picker
        bot_file_url = f"https://t.me/{bot_username}?start=filter_{encoded_name}"
    else:
        pid = group.get("primary_file_id") or "0"
        watch_url = f"{web_url}/watch/{pid}"
        # Movie: If multiple files or qualities exist (e.g. 480p, 720p, 1080p, 4K),
        # route to Smart Quality Navigator so user can pick their desired quality!
        # If only 1 file exists, link directly to file_{pid} for instant 1-click delivery.
        if len(files) > 1 or len(qualities) > 1:
            bot_file_url = f"https://t.me/{bot_username}?start=filter_{encoded_name}"
        else:
            bot_file_url = f"https://t.me/{bot_username}?start=file_{pid}"

    # Determine whether Watch Online button is enabled (Defaults to False)
    show_watch = enable_watch if enable_watch is not None else (_AUTO_POST_WATCH_PREF["enabled"] is True)

    first_row = []
    if show_watch:
        first_row.append(InlineKeyboardButton("▶️ Watch Online", url=watch_url))
    first_row.append(InlineKeyboardButton("🤖 Get File", url=bot_file_url))

    rows = [first_row]

    if custom_btn and custom_btn.get("text") and custom_btn.get("url"):
        rows.append([
            InlineKeyboardButton(custom_btn["text"], url=custom_btn["url"])
        ])

    return InlineKeyboardMarkup(rows)


async def build_aggregated_post_group(group_key: str) -> dict | None:
    """Build canonical aggregated media group for auto-posting or admin /post command.
    For series ('series:<norm_key>'): Aggregates ALL seasons, all episodes, qualities, and audios across the entire show.
    For movies ('movie:<norm_key>:<year>'): Aggregates all releases, qualities, parts, and audios.
    """
    is_series = group_key.startswith("series:")
    raw_key = group_key.split(":", 1)[1] if ":" in group_key else group_key
    norm_key = raw_key.split(":")[0]

    # Query all matching files across all connected clusters
    query_filter = _build_search_filter(norm_key)
    all_matched = []
    for col in mongo.all_files_collections:
        if col is not None:
            try:
                docs = await col.find(query_filter).to_list(1500)
                all_matched.extend(docs)
            except Exception as e:
                logger.debug(f"Error querying files for {norm_key}: {e}")

    if not all_matched:
        return None

    matched_files = []
    clean_name = None
    year = None
    seasons_map = {}
    qualities = set()
    languages = set()
    total_size = 0
    primary_file_id = None

    for d in all_matched:
        fn = d.get("file_name", "")
        meta = parse_media_metadata(fn)
        file_clean = meta.get("clean_name") or fn
        file_norm = re.sub(r"[^\w]", "", file_clean.lower())

        if is_series and not meta.get("is_series", False):
            continue
        if not is_series and meta.get("is_series", False):
            continue
        # Robust name match: exact match, substring match, or year-stripped match
        norm_key_noyear = re.sub(r"(19|20)\d{2}$", "", norm_key)
        matched_norm = (file_norm == norm_key or norm_key in file_norm)
        if not matched_norm and norm_key_noyear:
            matched_norm = (file_norm == norm_key_noyear or norm_key_noyear in file_norm)
        if not matched_norm:
            continue

        matched_files.append(d)
        if not clean_name:
            clean_name = meta.get("clean_name") or fn
        if not year and meta.get("year"):
            year = meta["year"]
        if not primary_file_id:
            primary_file_id = d.get("file_unique_id") or str(d.get("_id"))

        total_size += int(d.get("file_size", 0))

        if is_series:
            s_num = meta.get("season") or 1
            e_num = meta.get("episode")
            seasons_map.setdefault(s_num, {"episodes": set(), "has_pack": False})
            if e_num is not None:
                seasons_map[s_num]["episodes"].add(e_num)
            else:
                seasons_map[s_num]["has_pack"] = True

        q = meta.get("quality")
        if q:
            qualities.add(q)
        langs = meta.get("languages", [])
        if langs:
            languages.update(langs)

    if not matched_files:
        return None

    quality_priority = ["2160p", "4k", "1080p", "720p", "480p", "360p"]
    sorted_qualities = sorted(
        qualities,
        key=lambda x: quality_priority.index(x.lower()) if x.lower() in quality_priority else 99
    )

    clean_name = clean_name or norm_key.capitalize()
    disp_title = f"{clean_name} ({year})" if year else clean_name
    slug = re.sub(r"[^\w\-]", "-", disp_title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)

    return {
        "key": group_key,
        "slug": slug,
        "title": disp_title,
        "clean_name": clean_name,
        "is_series": is_series,
        "year": year,
        "files": matched_files,
        "qualities": qualities,
        "sorted_qualities": sorted_qualities,
        "languages": languages,
        "languages_list": list(languages),
        "seasons_map": seasons_map,
        "total_size": total_size,
        "primary_file_id": primary_file_id
    }


async def publish_or_upgrade_channel_post(
    client: Client,
    group: dict,
    channel_id: int = None,
    prefer_poster: bool = False,
    custom_photo: str = None
) -> tuple[bool, str, int | None]:
    """Publish a new post or silently upgrade/edit an existing post in the channel (Zero duplicate spam)."""
    target_channel = channel_id or await get_target_updates_channel()
    if not target_channel:
        return False, "Target channel not configured", None

    clean_name = group.get("clean_name") or group.get("title", "")
    tmdb_meta = await fetch_tmdb_post_metadata(
        clean_name,
        year=group.get("year"),
        is_series=group.get("is_series", False)
    )

    active_style = await get_autopost_style()
    caption = format_post_caption(group, tmdb_meta, style=active_style)
    custom_btn = await get_autopost_custom_button()
    watch_enabled = await is_auto_post_watch_enabled()
    buttons = build_post_buttons(group, custom_btn=custom_btn, enable_watch=watch_enabled)

    # Use explicit custom_photo if chosen in admin preview, else default backdrop or poster
    if custom_photo:
        photo_url = custom_photo
    elif active_style in (2, 4) or prefer_poster:
        photo_url = tmdb_meta.get("poster_url") or tmdb_meta.get("backdrop_url")
    else:
        photo_url = tmdb_meta.get("backdrop_url") or tmdb_meta.get("poster_url")

    if not photo_url:
        photo_url = await get_cached_poster_url(clean_name)
    if not photo_url:
        photo_url = getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")

    group_key = group["key"]

    # 1. Check if an existing post is recorded in MongoDB for this movie/series
    # For series, also check any legacy season-specific keys (like series:dexter:s1) to upgrade into master post
    existing = await mongo.db["channel_posts"].find_one({
        "channel_id": target_channel,
        "$or": [
            {"key": group_key},
            {"key": {"$regex": f"^{re.escape(group_key)}(:s\\d+)?$"}}
        ]
    })

    if existing and existing.get("message_id"):
        msg_id = existing["message_id"]
        try:
            await client.edit_message_caption(
                chat_id=target_channel,
                message_id=msg_id,
                caption=caption,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=buttons
            )
            await mongo.db["channel_posts"].update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "key": group_key,
                        "updated_at": datetime.datetime.utcnow(),
                        "qualities": list(group.get("qualities", [])),
                        "seasons": list(group.get("seasons_map", {}).keys()),
                        "last_caption": caption
                    }
                }
            )
            # Clean up any leftover duplicate season records in MongoDB
            if group.get("is_series"):
                await mongo.db["channel_posts"].delete_many({
                    "channel_id": target_channel,
                    "key": {"$regex": f"^{re.escape(group_key)}:s\\d+"},
                    "_id": {"$ne": existing["_id"]}
                })

            logger.info(f"Silently upgraded channel post for {group_key} (Message ID: {msg_id})")
            return True, "upgraded", msg_id
        except MessageNotModified:
            logger.info(f"Channel post {msg_id} already up to date.")
            return True, "already_up_to_date", msg_id
        except MessageIdInvalid:
            logger.info(f"Existing post {msg_id} was deleted in Telegram. Will publish fresh post.")
        except Exception as e:
            logger.warning(f"Failed to edit existing post {msg_id}: {e}. Falling back to fresh post.")

    # 2. Publish fresh post to channel
    try:
        sent_msg = await client.send_photo(
            chat_id=target_channel,
            photo=photo_url,
            caption=caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=buttons
        )

        await mongo.db["channel_posts"].update_one(
            {"key": group_key, "channel_id": target_channel},
            {
                "$set": {
                    "key": group_key,
                    "channel_id": target_channel,
                    "message_id": sent_msg.id,
                    "title": group.get("title"),
                    "clean_name": group.get("clean_name"),
                    "qualities": list(group.get("qualities", [])),
                    "seasons": list(group.get("seasons_map", {}).keys()),
                    "photo_url": photo_url,
                    "created_at": datetime.datetime.utcnow(),
                    "updated_at": datetime.datetime.utcnow()
                }
            },
            upsert=True
        )
        logger.info(f"Published new post for {group_key} to channel {target_channel} (Msg ID: {sent_msg.id})")

        # Automatically trigger reaction on channel post
        if await is_auto_reaction_enabled():
            try:
                emojis = await get_auto_reaction_emojis()
                if emojis:
                    chosen_emoji = random.choice(emojis)
                    await client.send_reaction(
                        chat_id=target_channel,
                        message_id=sent_msg.id,
                        emoji=chosen_emoji
                    )
                    logger.info(f"Auto-reacted '{chosen_emoji}' to post {sent_msg.id} in {target_channel}")
            except Exception as e_react:
                logger.debug(f"Auto reaction failed for post {sent_msg.id}: {e_react}")

        return True, "published", sent_msg.id
    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        return await publish_or_upgrade_channel_post(client, group, channel_id, prefer_poster, custom_photo=custom_photo)
    except Exception as e:
        logger.error(f"Error publishing post to channel {target_channel}: {e}")
        return False, str(e), None


async def _buffer_post_worker(client: Client, group_key: str, delay: int):
    """Wait for debounce window (2 mins) to let all parts/qualities finish uploading, then publish/upgrade."""
    try:
        await asyncio.sleep(delay)
        async with _get_post_lock(group_key):
            current_task = _AUTO_POST_TIMERS.get(group_key)
            if current_task and current_task is not asyncio.current_task():
                # A newer debounce timer was started for this title
                return

            target_group = await build_aggregated_post_group(group_key)
            if not target_group:
                catalog = await get_grouped_catalog()
                for it in catalog:
                    if it.get("key") == group_key or group_key in it.get("aliases", []):
                        target_group = it
                        break

            if target_group:
                success, action, msg_id = await publish_or_upgrade_channel_post(client, target_group)
                logger.info(f"Auto-post triggered for {group_key}: {action} (Msg ID: {msg_id})")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Error in auto-post worker for {group_key}: {e}", exc_info=True)
    finally:
        if _AUTO_POST_TIMERS.get(group_key) is asyncio.current_task():
            _AUTO_POST_TIMERS.pop(group_key, None)


async def queue_file_for_auto_post(client: Client, media_info: dict):
    """Queue newly uploaded/indexed file for per-title isolated auto-posting."""
    if not await is_autopost_enabled():
        return

    file_name = media_info.get("file_name", "")
    meta = parse_media_metadata(file_name)
    clean = meta.get("clean_name") or file_name
    is_series = meta.get("is_series", False)
    yr = meta.get("year")

    norm_key = re.sub(r"[^\w]", "", clean.lower())
    if is_series:
        # Show-level canonical group key: ALL seasons & episodes group under this master key
        group_key = f"series:{norm_key}"
    else:
        yr_str = str(yr) if yr else ""
        group_key = f"movie:{norm_key}:{yr_str}"

    # If this title already has an active timer, cancel and refresh it (rolling debounce buffer)
    if group_key in _AUTO_POST_TIMERS:
        old_task = _AUTO_POST_TIMERS[group_key]
        if not old_task.done():
            old_task.cancel()

    delay = getattr(Config, "AUTO_POST_DELAY", 120)
    task = asyncio.create_task(_buffer_post_worker(client, group_key, delay))
    _AUTO_POST_TIMERS[group_key] = task
    logger.info(f"Queued auto-post for '{clean}' ({group_key}) with {delay}s buffer.")


async def resolve_draft_group(token: str) -> dict | None:
    """Resolve draft media group from in-memory cache or database lookup with year-stripping resilience."""
    if not token:
        return None

    if token in _DRAFT_PREVIEWS:
        return _DRAFT_PREVIEWS[token]

    # 1. Direct key match (e.g. series:dexter or movie:kantara:2022)
    if token.startswith("series:") or token.startswith("movie:"):
        grp = await build_aggregated_post_group(token)
        if grp:
            _DRAFT_PREVIEWS[token] = grp
            return grp

    # 2. Strip trailing year from token / slug (e.g. 'dexter-2006' -> 'dexter', 'doraemon-1979' -> 'doraemon')
    clean_token = re.sub(r"-?\b(19|20)\d{2}\b.*", "", token).strip("-")
    norm = re.sub(r"[^\w]", "", clean_token.lower())

    if norm:
        grp = await build_aggregated_post_group(f"series:{norm}")
        if not grp:
            grp = await build_aggregated_post_group(f"movie:{norm}:")
        if grp:
            _DRAFT_PREVIEWS[token] = grp
            return grp

    # 3. Direct norm of the full token
    full_norm = re.sub(r"[^\w]", "", token.lower())
    if full_norm:
        grp = await build_aggregated_post_group(f"series:{full_norm}")
        if not grp:
            grp = await build_aggregated_post_group(f"movie:{full_norm}:")
        if grp:
            _DRAFT_PREVIEWS[token] = grp
            return grp

    # 4. Catalog fallback
    catalog = await get_grouped_catalog()
    for item in catalog:
        if (
            item.get("slug") == token or
            item.get("key") == token or
            token in item.get("aliases", []) or
            item.get("clean_name", "").lower() == clean_token.lower()
        ):
            _DRAFT_PREVIEWS[token] = item
            return item

    return None


# ==========================================
# ADMIN COMMANDS: /post, /autopost, /setupdateschannel
# ==========================================

@Client.on_message(filters.command(["post", "cpost", "publish"]) & filters.private)
async def admin_post_command(client: Client, message: Message):
    """Admin interactive command to search, preview, and publish or upgrade any movie/series release card."""
    if not Config.is_admin(message.from_user.id):
        return

    query = " ".join(message.command[1:]).strip()
    if not query:
        await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/post &lt;movie or series name&gt;</code>\n"
            "<i>Example:</i> <code>/post Ranbaali</code> or <code>/post Hercai</code>"
        )
        return

    status_msg = await message.reply_text("🔍 <i>Searching catalog and generating preview...</i>")
    norm_q = re.sub(r"[^\w]", "", query.lower())

    # 1. Try unified master group first (e.g. series:dexter or movie:xxx)
    chosen_group = await build_aggregated_post_group(f"series:{norm_q}")
    if not chosen_group:
        chosen_group = await build_aggregated_post_group(f"movie:{norm_q}:")

    # 2. Fallback to catalog search
    if not chosen_group:
        catalog = await get_grouped_catalog()
        matches = []
        for item in catalog:
            c_name = item.get("clean_name", "").lower()
            title = item.get("title", "").lower()
            if norm_q in re.sub(r"[^\w]", "", c_name) or norm_q in re.sub(r"[^\w]", "", title):
                matches.append(item)
        if matches:
            chosen_group = matches[0]

    if not chosen_group:
        await status_msg.edit_text(f"❌ No matching media found in catalog for '<b>{html.escape(query)}</b>'.")
        return
    tmdb_meta = await fetch_tmdb_post_metadata(
        chosen_group["clean_name"],
        year=chosen_group.get("year"),
        is_series=chosen_group.get("is_series", False)
    )

    active_style = await get_autopost_style()
    caption = format_post_caption(chosen_group, tmdb_meta, style=active_style)
    channel_id = await get_target_updates_channel()

    # Images Gallery
    gallery = tmdb_meta.get("gallery") or []
    if not gallery:
        if tmdb_meta.get("backdrop_url"): gallery.append(tmdb_meta["backdrop_url"])
        if tmdb_meta.get("poster_url") and tmdb_meta["poster_url"] not in gallery: gallery.append(tmdb_meta["poster_url"])
    if not gallery:
        cached_p = await get_cached_poster_url(chosen_group["clean_name"])
        gallery = [cached_p] if cached_p else [getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")]

    total_imgs = len(gallery)
    photo_url = gallery[0]
    next_idx = 1 % total_imgs

    # Register draft preview in cache for instant button handling
    draft_id = uuid.uuid4().hex[:8]
    _DRAFT_PREVIEWS[draft_id] = chosen_group
    if chosen_group.get("slug"):
        _DRAFT_PREVIEWS[chosen_group["slug"]] = chosen_group
    if chosen_group.get("key"):
        _DRAFT_PREVIEWS[chosen_group["key"]] = chosen_group

    # Preview Buttons with Admin Controls
    preview_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Publish to Channel", callback_data=f"cp|pub|0|{draft_id}"),
            InlineKeyboardButton(f"🖼️ Next Photo (1/{total_imgs}) ➔", callback_data=f"cp|sw|{next_idx}|{draft_id}")
        ],
        [
            InlineKeyboardButton("❌ Discard", callback_data=f"cp|del|{draft_id}")
        ]
    ])

    await status_msg.delete()
    await client.send_photo(
        chat_id=message.chat.id,
        photo=photo_url,
        caption=(
            f"<b>👁️ [DRAFT PREVIEW FOR CHANNEL <code>{channel_id}</code>]</b>\n\n"
            f"{caption}"
        ),
        parse_mode=enums.ParseMode.HTML,
        reply_markup=preview_markup
    )


@Client.on_callback_query(filters.regex(r"^cp\|"))
async def post_preview_callbacks(client: Client, callback_query: CallbackQuery):
    """Handle interactive Admin preview buttons."""
    if not Config.is_admin(callback_query.from_user.id):
        await callback_query.answer("⚠️ Admin only action.", show_alert=True)
        return

    data = callback_query.data
    parts = data.split("|")
    action = parts[1] if len(parts) > 1 else ""

    if action == "del":
        token = parts[2] if len(parts) > 2 else ""
        _DRAFT_PREVIEWS.pop(token, None)
        await callback_query.message.delete()
        await callback_query.answer("Preview discarded.")
        return

    photo_idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    token = parts[3] if len(parts) > 3 else ""

    chosen_group = await resolve_draft_group(token)
    if not chosen_group:
        await callback_query.answer("❌ Media item not found in catalog.", show_alert=True)
        return

    tmdb_meta = await fetch_tmdb_post_metadata(
        chosen_group["clean_name"],
        year=chosen_group.get("year"),
        is_series=chosen_group.get("is_series", False)
    )

    gallery = tmdb_meta.get("gallery") or []
    if not gallery:
        if tmdb_meta.get("backdrop_url"): gallery.append(tmdb_meta["backdrop_url"])
        if tmdb_meta.get("poster_url") and tmdb_meta["poster_url"] not in gallery: gallery.append(tmdb_meta["poster_url"])
    if not gallery:
        cached_p = await get_cached_poster_url(chosen_group["clean_name"])
        gallery = [cached_p] if cached_p else [getattr(Config, "START_PIC", "https://api.aniwallpaper.workers.dev/random")]

    total_imgs = len(gallery)

    if action == "sw":
        curr_idx = photo_idx % total_imgs
        next_idx = (curr_idx + 1) % total_imgs
        new_photo = gallery[curr_idx]

        active_style = await get_autopost_style()
        caption = format_post_caption(chosen_group, tmdb_meta, style=active_style)
        target_ch = await get_target_updates_channel()
        new_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Publish to Channel", callback_data=f"cp|pub|{curr_idx}|{token}"),
                InlineKeyboardButton(f"🖼️ Next Photo ({curr_idx + 1}/{total_imgs}) ➔", callback_data=f"cp|sw|{next_idx}|{token}")
            ],
            [
                InlineKeyboardButton("❌ Discard", callback_data=f"cp|del|{token}")
            ]
        ])

        try:
            await callback_query.message.edit_media(
                media=InputMediaPhoto(
                    media=new_photo,
                    caption=f"<b>👁️ [DRAFT PREVIEW FOR CHANNEL <code>{target_ch}</code>]</b>\n\n{caption}",
                    parse_mode=enums.ParseMode.HTML
                ),
                reply_markup=new_markup
            )
            await callback_query.answer(f"Photo {curr_idx + 1} of {total_imgs}")
        except Exception as e:
            await callback_query.answer(f"Switch error: {e}", show_alert=True)

    elif action == "pub":
        await callback_query.answer("🚀 Publishing to channel...", show_alert=False)
        target_ch = await get_target_updates_channel()
        chosen_photo = gallery[photo_idx % total_imgs]

        success, result_action, msg_id = await publish_or_upgrade_channel_post(
            client,
            chosen_group,
            channel_id=target_ch,
            custom_photo=chosen_photo
        )

        if success:
            action_desc = "Silently upgraded existing post" if result_action == "upgraded" else "Successfully published new post"
            await callback_query.message.edit_caption(
                f"✅ <b>{action_desc}!</b>\n\n"
                f"📁 <b>Title:</b> {chosen_group['title']}\n"
                f"📢 <b>Channel:</b> <code>{target_ch}</code>\n"
                f"🆔 <b>Message ID:</b> <code>{msg_id}</code>"
            )
            _DRAFT_PREVIEWS.pop(token, None)
        else:
            await callback_query.message.reply_text(f"❌ <b>Publishing failed:</b> <code>{result_action}</code>")


@Client.on_message(filters.command("autopost") & filters.private)
async def autopost_control_command(client: Client, message: Message):
    """Toggle or inspect auto-posting status: /autopost on | off | status"""
    if not Config.is_admin(message.from_user.id):
        return

    cmd = message.command[1].lower() if len(message.command) > 1 else "status"
    target_ch = await get_target_updates_channel()
    delay = getattr(Config, "AUTO_POST_DELAY", 120)

    if cmd == "on":
        await set_autopost_state(enabled=True)
        await message.reply_text(
            f"✅ <b>Auto-Post Enabled!</b>\n\n"
            f"📢 <b>Target Channel:</b> <code>{target_ch}</code>\n"
            f"⏱️ <b>Debounce Buffer:</b> <code>{delay} seconds</code>\n\n"
            f"<i>Newly uploaded files in storage channels will automatically be grouped and published!</i>"
        )
    elif cmd == "off":
        await set_autopost_state(enabled=False)
        await message.reply_text(
            "🛑 <b>Auto-Post Paused / Disabled!</b>\n\n"
            "<i>Files uploaded to storage channels will still be indexed for search, but no posts will be sent to the updates channel.</i>\n"
            "You can always use <code>/post &lt;title&gt;</code> to publish manually."
        )
    else:
        is_on = await is_autopost_enabled()
        status_badge = "🟢 ACTIVE / ON" if is_on else "🔴 PAUSED / OFF"
        pending_cnt = len(_AUTO_POST_TIMERS)
        await message.reply_text(
            f"📊 <b>Auto-Post System Status:</b>\n\n"
            f"• <b>Status:</b> {status_badge}\n"
            f"• <b>Target Channel:</b> <code>{target_ch}</code>\n"
            f"• <b>Buffer Delay:</b> <code>{delay}s</code>\n"
            f"• <b>Active Debounce Queues:</b> <code>{pending_cnt} titles buffering</code>\n\n"
            f"<b>Commands:</b>\n"
            f"• <code>/autopost on</code> — Enable auto-post\n"
            f"• <code>/autopost off</code> — Pause auto-post\n"
            f"• <code>/setupdateschannel &lt;id&gt;</code> — Change target channel\n"
            f"• <code>/post &lt;title&gt;</code> — Manual publish"
        )


@Client.on_message(filters.command(["autoreaction", "postreaction"]) & filters.private)
async def auto_reaction_control_command(client: Client, message: Message):
    """Toggle or configure automatic reactions on channel posts:
    /autoreaction on | off | status | set <emojis> | reset
    """
    if not Config.is_admin(message.from_user.id):
        return

    cmd = message.command[1].lower() if len(message.command) > 1 else "status"

    if cmd == "on":
        await set_auto_reaction_state(enabled=True)
        emojis = await get_auto_reaction_emojis()
        await message.reply_text(
            f"✅ <b>Auto Reactions Enabled!</b>\n\n"
            f"Bot will now automatically react to every channel post.\n"
            f"🎯 <b>Active Emojis:</b> {' '.join(emojis)}\n\n"
            f"<i>To customize emojis, send:</i> <code>/autoreaction set 🔥 ❤️ 🍿 ⚡</code>"
        )
    elif cmd == "off":
        await set_auto_reaction_state(enabled=False)
        await message.reply_text(
            "🛑 <b>Auto Reactions Disabled!</b>\n\n"
            "Channel posts will no longer receive automated reactions.\n"
            "To re-enable anytime, send <code>/autoreaction on</code>."
        )
    elif cmd == "reset":
        await set_auto_reaction_state(enabled=True, emojis=DEFAULT_REACTION_EMOJIS)
        await message.reply_text(
            f"🔄 <b>Auto Reactions Reset to Default!</b>\n\n"
            f"🎯 <b>Active Emojis:</b> {' '.join(DEFAULT_REACTION_EMOJIS)}"
        )
    elif cmd == "set":
        raw_parts = message.text.split(None, 2)
        if len(raw_parts) < 3 or not raw_parts[2].strip():
            return await message.reply_text(
                "⚠️ <b>Usage:</b> <code>/autoreaction set 🔥 ❤️ 🍿 ⚡ 🎉</code>\n\n"
                "Please provide one or more emojis separated by spaces."
            )
        input_emojis = [e.strip() for e in raw_parts[2].split() if e.strip()]
        if not input_emojis:
            return await message.reply_text("❌ No valid emojis found. Example: <code>/autoreaction set 🔥 ❤️ 🍿</code>")

        await set_auto_reaction_state(enabled=True, emojis=input_emojis)
        await message.reply_text(
            f"✅ <b>Custom Auto Reaction Emojis Saved!</b>\n\n"
            f"🎯 <b>Active Emojis ({len(input_emojis)}):</b> {' '.join(input_emojis)}\n\n"
            f"Bot will randomly pick from this pool for each channel post."
        )
    else:
        is_on = await is_auto_reaction_enabled()
        emojis = await get_auto_reaction_emojis()
        status_badge = "🟢 ACTIVE / ON" if is_on else "🔴 PAUSED / OFF"
        await message.reply_text(
            f"🎭 <b>Auto Reaction System:</b>\n\n"
            f"• <b>Status:</b> {status_badge}\n"
            f"• <b>Active Pool:</b> {' '.join(emojis)}\n\n"
            f"<b>Commands:</b>\n"
            f"• <code>/autoreaction on</code> — Turn ON\n"
            f"• <code>/autoreaction off</code> — Turn OFF\n"
            f"• <code>/autoreaction set 🔥 ❤️ 🍿 ⚡</code> — Set custom emojis\n"
            f"• <code>/autoreaction reset</code> — Reset to default emojis"
        )


@Client.on_message(filters.command(["postwatch", "watchbtn", "postwatchbtn"]) & filters.private)
async def post_watch_toggle_command(client: Client, message: Message):
    """Toggle Watch Online button on channel posts: /postwatch [on|off|status]"""
    if not Config.is_admin(message.from_user.id):
        return

    cmd = message.command[1].lower() if len(message.command) > 1 else "status"

    if cmd == "on":
        await set_auto_post_watch_state(enabled=True)
        await message.reply_text(
            "✅ <b>Watch Online Button Enabled!</b>\n\n"
            "Channel posts will now include the <code>[ ▶️ Watch Online ]</code> button alongside <code>[ 🤖 Get File ]</code>."
        )
    elif cmd == "off":
        await set_auto_post_watch_state(enabled=False)
        await message.reply_text(
            "🛑 <b>Watch Online Button Removed / Disabled!</b>\n\n"
            "Channel posts will now strictly display <code>[ 🤖 Get File ]</code> (Focusing 100% on bot delivery & shortener monetization).\n\n"
            "<i>To re-enable anytime, send:</i> <code>/postwatch on</code>"
        )
    else:
        is_on = await is_auto_post_watch_enabled()
        status_badge = "🟢 ENABLED / ON" if is_on else "🔴 DISABLED / OFF"
        await message.reply_text(
            f"🎬 <b>Channel Post 'Watch Online' Setting:</b>\n\n"
            f"• <b>Status:</b> {status_badge}\n"
            f"• <b>Active Buttons:</b> {'[ ▶️ Watch Online ] + [ 🤖 Get File ]' if is_on else '[ 🤖 Get File ] only'}\n\n"
            f"<b>Commands:</b>\n"
            f"• <code>/postwatch off</code> — Remove Watch Online button (Recommended)\n"
            f"• <code>/postwatch on</code> — Show Watch Online button"
        )


@Client.on_message(filters.command("setupdateschannel") & filters.private)
async def set_updates_channel_command(client: Client, message: Message):
    """Change the updates channel dynamically: /setupdateschannel <chat_id>"""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.command[1:]
    if not args:
        curr_ch = await get_target_updates_channel()
        await message.reply_text(
            f"ℹ️ <b>Current Updates Channel:</b> <code>{curr_ch}</code>\n\n"
            f"<b>Usage:</b> <code>/setupdateschannel -100xxxxxxxxxx</code>"
        )
        return

    target_str = args[0]
    try:
        new_ch_id = int(target_str)
        await set_autopost_state(channel_id=new_ch_id)
        await message.reply_text(f"✅ <b>Updates Channel successfully updated to:</b> <code>{new_ch_id}</code>")
    except ValueError:
        await message.reply_text("❌ Invalid channel ID. Please provide a numeric Telegram chat ID starting with -100.")


@Client.on_message(filters.command(["poststyle", "set_post_style"]) & filters.private)
async def set_post_style_command(client: Client, message: Message):
    """View or switch auto-post channel release card style: /poststyle 1|2|3|4"""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.command[1:]
    if args and args[0].isdigit():
        new_style = int(args[0])
        if new_style in (1, 2, 3, 4):
            await set_autopost_style(new_style)
            style_names = {
                1: "🎬 Style 1: Cinematic Widescreen (16:9 Backdrop + Expandable Storyline)",
                2: "📱 Style 2: Minimalist Single-Poster (2:3 Vertical Poster + 5-Line Info)",
                3: "📄 Style 3: Clean Compact Text (Fast release format)",
                4: "✨ Style 4: Ultra-Clean Compact 4-Line (Format 1 - No Fluff)"
            }
            await message.reply_text(f"✅ <b>Auto-Post Style Updated!</b>\n\nNow using: <b>{style_names[new_style]}</b>")
            return

    current = await get_autopost_style()
    text = (
        "🎨 <b>Channel Post Release Style Selector</b>\n"
        "────────────────────────\n"
        f"• <b>Current Active Style:</b> <b>Style {current}</b>\n\n"
        "<b>Available Styles:</b>\n"
        "✨ <b>Style 4: Ultra-Clean Compact 4-Line (Format 1 - Default)</b>\n"
        "   • Official 2:3 vertical poster\n"
        "   • Pure 4-line essentials (Title, Rating, Audio, Quality, Episodes) — zero fluff!\n\n"
        "1️⃣ <b>Style 1: Cinematic Widescreen</b>\n"
        "   • 16:9 Landscape backdrop\n"
        "   • Expandable dropdown quote with plot storyline\n\n"
        "2️⃣ <b>Style 2: Minimalist Single-Poster</b>\n"
        "   • 2:3 Vertical portrait poster\n"
        "   • Crisp 5-line details (Title, Rating, Genres, Audio, Quality, OTT) without long story\n\n"
        "3️⃣ <b>Style 3: Clean Compact Text</b>\n"
        "   • Fast release format, ultra-crisp\n"
        "────────────────────────\n"
        "👇 <i>Tap below to switch active channel release style:</i>"
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'✅ ' if current == 4 else ''}✨ Style 4 (Format 1)", callback_data="cp_setstyle:4")
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if current == 1 else ''}🎬 Style 1 (Cinematic)", callback_data="cp_setstyle:1"),
            InlineKeyboardButton(f"{'✅ ' if current == 2 else ''}📱 Style 2 (Poster)", callback_data="cp_setstyle:2")
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if current == 3 else ''}📄 Style 3 (Compact)", callback_data="cp_setstyle:3")
        ]
    ])
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^cp_setstyle:"))
async def post_style_callback(client: Client, query: CallbackQuery):
    if not Config.is_admin(query.from_user.id):
        await query.answer("Admin only.", show_alert=True)
        return

    style_id = int(query.data.split(":")[1])
    await set_autopost_style(style_id)
    await query.answer(f"✅ Switched to Style {style_id}!")

    current = style_id
    text = (
        "🎨 <b>Channel Post Release Style Selector</b>\n"
        "────────────────────────\n"
        f"• <b>Current Active Style:</b> <b>Style {current}</b>\n\n"
        "<b>Available Styles:</b>\n"
        "✨ <b>Style 4: Ultra-Clean Compact 4-Line (Format 1 - Default)</b>\n"
        "   • Official 2:3 vertical poster\n"
        "   • Pure 4-line essentials (Title, Rating, Audio, Quality, Episodes) — zero fluff!\n\n"
        "1️⃣ <b>Style 1: Cinematic Widescreen</b>\n"
        "   • 16:9 Landscape backdrop\n"
        "   • Expandable dropdown quote with plot storyline\n\n"
        "2️⃣ <b>Style 2: Minimalist Single-Poster</b>\n"
        "   • 2:3 Vertical portrait poster\n"
        "   • Crisp 5-line details (Title, Rating, Genres, Audio, Quality, OTT) without long story\n\n"
        "3️⃣ <b>Style 3: Clean Compact Text</b>\n"
        "   • Fast release format, ultra-crisp\n"
        "────────────────────────\n"
        "👇 <i>Tap below to switch active channel release style:</i>"
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'✅ ' if current == 4 else ''}✨ Style 4 (Format 1)", callback_data="cp_setstyle:4")
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if current == 1 else ''}🎬 Style 1 (Cinematic)", callback_data="cp_setstyle:1"),
            InlineKeyboardButton(f"{'✅ ' if current == 2 else ''}📱 Style 2 (Poster)", callback_data="cp_setstyle:2")
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if current == 3 else ''}📄 Style 3 (Compact)", callback_data="cp_setstyle:3")
        ]
    ])
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.command(["postbutton", "postbtn"]) & filters.private)
async def post_custom_button_command(client: Client, message: Message):
    """Set, view, or remove custom promotional button on channel posts:
    /postbutton <text> | <url>
    /postbutton off | clear
    /postbutton
    """
    if not Config.is_admin(message.from_user.id):
        return

    text_parts = message.text.split(None, 1)
    if len(text_parts) < 2:
        current = await get_autopost_custom_button()
        if current:
            status_text = (
                f"🔘 <b>Active Channel Post Button:</b>\n\n"
                f"• <b>Text:</b> <code>{html.escape(current['text'])}</code>\n"
                f"• <b>URL:</b> <code>{html.escape(current['url'])}</code>\n\n"
                f"<b>Commands:</b>\n"
                f"• Update: <code>/postbutton New Button Name | https://t.me/...</code>\n"
                f"• Remove: <code>/postbutton off</code>"
            )
        else:
            status_text = (
                "🔘 <b>Channel Post Custom Button:</b> <i>Disabled (None)</i>\n\n"
                "You can add a custom promotional button (like a Backup Channel or Discussion Group) to every channel release post!\n\n"
                "<b>Usage:</b>\n"
                "<code>/postbutton 📢 Join Backup Channel | https://t.me/AkMovieVerse</code>\n"
                "<code>/postbutton 💬 Request Group | https://t.me/my_group</code>\n"
                "<code>/postbutton off</code> (to disable)"
            )
        return await message.reply_text(status_text, disable_web_page_preview=True)

    arg = text_parts[1].strip()
    if arg.lower() in ("off", "clear", "del", "remove", "disable"):
        await set_autopost_custom_button(None, None)
        return await message.reply_text("✅ <b>Channel Post Custom Button Removed!</b>\nRelease posts will now show standard 2 buttons.")

    if "|" not in arg:
        return await message.reply_text(
            "⚠️ <b>Invalid Format!</b>\nPlease use:\n<code>/postbutton Button Text | https://t.me/...</code>"
        )

    btn_text, btn_url = arg.split("|", 1)
    btn_text = btn_text.strip()
    btn_url = btn_url.strip()

    if not btn_url.startswith(("http://", "https://", "tg://")):
        return await message.reply_text("⚠️ <b>Invalid URL!</b> The link must start with <code>https://</code> or <code>tg://</code>")

    await set_autopost_custom_button(btn_text, btn_url)
    await message.reply_text(
        f"✅ <b>Custom Channel Post Button Saved!</b>\n\n"
        f"• <b>Text:</b> <code>{html.escape(btn_text)}</code>\n"
        f"• <b>URL:</b> <code>{html.escape(btn_url)}</code>\n\n"
        f"All future auto-posts and release cards will include this button on Row 2!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(btn_text, url=btn_url)
        ]]),
        disable_web_page_preview=True
    )



# ==========================================
# ADMIN COMMANDS: /setposter, /delposter, /getposter
# ==========================================

@Client.on_message(filters.command(["setposter", "set_poster"]) & filters.private)
async def set_custom_poster_command(client: Client, message: Message):
    """Admin command to set or replace poster for any movie/series in Web Catalog & Posts.
    Usage:
      1. With image link:
         /setposter Dexter https://example.com/poster.jpg
      2. By replying to a photo:
         Reply /setposter Dexter to any photo
    """
    if not Config.is_admin(message.from_user.id):
        return

    from utils.title_cleaner import clean_movie_title
    from utils.poster_engine.uploader import upload_to_imgbb

    args = message.text.split(maxsplit=2)
    reply = message.reply_to_message
    poster_url = None
    title = None

    if reply and (reply.photo or (reply.document and getattr(reply.document, "mime_type", "").startswith("image/"))):
        if len(args) < 2:
            return await message.reply_text("⚠️ <b>Usage:</b> Reply to a photo with <code>/setposter <movie/series name></code>")
        title = message.text.split(maxsplit=1)[1].strip()
        status_msg = await message.reply_text("⏳ <i>Uploading photo to cloud CDN...</i>")
        try:
            import io
            buf = io.BytesIO()
            await client.download_media(reply, file_name=buf)
            buf.seek(0)
            uploaded_url = await upload_to_imgbb(buf)
            if not uploaded_url:
                return await status_msg.edit_text("❌ <b>Failed to upload photo to CDN.</b> Please provide a direct image link instead.")
            poster_url = uploaded_url
            await status_msg.delete()
        except Exception as e:
            return await status_msg.edit_text(f"❌ <b>Upload error:</b> {e}")
    else:
        if len(args) < 3:
            return await message.reply_text(
                "🎨 <b>Custom Poster Manager:</b>\n\n"
                "Set a custom poster for any movie or series across the Web Catalog and /post release cards!\n\n"
                "<b>Usage Options:</b>\n"
                "1️⃣ <b>Via Direct Image Link:</b>\n"
                "👉 <code>/setposter Dexter https://example.com/poster.jpg</code>\n\n"
                "2️⃣ <b>Via Photo Reply:</b>\n"
                "👉 Send any photo in chat and reply with: <code>/setposter Dexter</code>\n\n"
                "3️⃣ <b>Revert to Default Poster:</b>\n"
                "👉 <code>/delposter Dexter</code>"
            )
        title = args[1].strip()
        poster_url = args[2].strip()

    if not poster_url or not (poster_url.startswith("http://") or poster_url.startswith("https://")):
        return await message.reply_text("❌ <b>Invalid Image URL!</b> Must start with <code>https://</code> or <code>http://</code>")

    clean_q = clean_movie_title(title, keep_year=False)
    clean_q = re.sub(r"\s*\(?(?:19|20)\d{2}\)?.*", "", clean_q).strip()
    norm_key = re.sub(r"[^\w]", "", clean_q.lower())

    # 1. Save to custom_posters collection in MongoDB
    import time
    await mongo.db["custom_posters"].update_one(
        {"key": norm_key},
        {"$set": {
            "key": norm_key,
            "title": title,
            "clean_name": clean_q,
            "poster_url": poster_url,
            "updated_at": time.time()
        }},
        upsert=True
    )

    # 2. Update poster_cache for Web Catalog
    await mongo.db["poster_cache"].update_one(
        {"title": clean_q},
        {"$set": {"title": clean_q, "poster_url": poster_url}},
        upsert=True
    )

    # 3. Update in-memory caches
    from utils.helpers import _POSTER_CACHE
    _POSTER_CACHE[clean_q] = poster_url
    _TMDB_POST_CACHE.clear()

    # 4. Invalidate MongoDB tmdb_post_cache
    try:
        await mongo.db["tmdb_post_cache"].delete_many({"key": {"$regex": f"^{norm_key}:"}})
    except Exception:
        pass

    await message.reply_photo(
        photo=poster_url,
        caption=(
            f"✅ <b>Custom Poster Successfully Set!</b>\n\n"
            f"🎬 <b>Title:</b> <code>{html.escape(title)}</code>\n"
            f"🖼️ <b>Poster URL:</b> <code>{html.escape(poster_url)}</code>\n\n"
            "✨ <b>Applied to:</b>\n"
            "• 🌐 Web Cinema Catalog (`/browse` and `/post/...` pages)\n"
            "• 📢 Channel Auto-Post & `/post` release cards\n\n"
            f"<i>Use <code>/delposter {html.escape(title)}</code> anytime to revert back to default TMDB poster.</i>"
        )
    )


@Client.on_message(filters.command(["delposter", "del_poster"]) & filters.private)
async def delete_custom_poster_command(client: Client, message: Message):
    """Admin command to remove custom poster override and revert to official TMDB."""
    if not Config.is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply_text("⚠️ <b>Usage:</b> <code>/delposter &lt;movie or series name&gt;</code>")

    title = parts[1].strip()
    from utils.title_cleaner import clean_movie_title
    clean_q = clean_movie_title(title, keep_year=False)
    clean_q = re.sub(r"\s*\(?(?:19|20)\d{2}\)?.*", "", clean_q).strip()
    norm_key = re.sub(r"[^\w]", "", clean_q.lower())

    await mongo.db["custom_posters"].delete_many({"$or": [{"key": norm_key}, {"title": clean_q}]})
    await mongo.db["poster_cache"].delete_many({"title": clean_q})

    from utils.helpers import _POSTER_CACHE
    _POSTER_CACHE.pop(clean_q, None)
    _TMDB_POST_CACHE.clear()

    await message.reply_text(
        f"🗑️ <b>Custom Poster Removed for:</b> <code>{html.escape(title)}</code>\n\n"
        "Web Catalog and /post will now automatically use the official TMDB poster!"
    )


@Client.on_message(filters.command(["getposter", "viewposter"]) & filters.private)
async def get_poster_command(client: Client, message: Message):
    """View active poster for any movie or series."""
    if not Config.is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply_text("⚠️ <b>Usage:</b> <code>/getposter &lt;movie or series name&gt;</code>")

    title = parts[1].strip()
    from utils.helpers import get_cached_poster_url
    url = await get_cached_poster_url(title)
    if not url:
        return await message.reply_text(f"❌ No poster found for <code>{html.escape(title)}</code>.")

    await message.reply_photo(
        photo=url,
        caption=f"🖼️ <b>Active Poster for:</b> <code>{html.escape(title)}</code>\n\n<code>{html.escape(url)}</code>"
    )
