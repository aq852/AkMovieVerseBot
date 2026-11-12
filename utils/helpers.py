import asyncio
import re
import time
import uuid
import random
import logging
import humanize
try:
    from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
except ImportError:
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from config import Config

logger = logging.getLogger(__name__)

def get_random_start_pic(pic_url: str = None) -> str:
    """Return START_PIC URL with dynamic cache-busting query parameter to prevent Telegram DC caching.
    Supports single URL, comma-separated URLs, or Telegram file_id.
    """
    raw_pic = pic_url or Config.START_PIC
    if not raw_pic:
        return ""

    # Support multiple URLs separated by space or comma
    if "," in raw_pic:
        pics = [p.strip() for p in raw_pic.split(",") if p.strip()]
        pic = random.choice(pics) if pics else raw_pic
    elif " " in raw_pic and (raw_pic.startswith("http://") or raw_pic.startswith("https://")):
        pics = [p.strip() for p in raw_pic.split() if p.strip()]
        pic = random.choice(pics) if pics else raw_pic
    else:
        pic = raw_pic.strip()

    if pic.startswith("http://") or pic.startswith("https://"):
        sep = "&" if "?" in pic else "?"
        return f"{pic}{sep}_t={int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    return pic

def get_chat_type_str(chat_or_message) -> str:
    """Return normalized chat type string ('private', 'group', 'supergroup', 'channel')."""
    if hasattr(chat_or_message, "chat"):
        chat_type = chat_or_message.chat.type
    elif hasattr(chat_or_message, "message") and hasattr(chat_or_message.message, "chat"):
        chat_type = chat_or_message.message.chat.type
    elif hasattr(chat_or_message, "type"):
        chat_type = chat_or_message.type
    else:
        chat_type = chat_or_message

    val = getattr(chat_type, "value", None)
    if val:
        return str(val).lower()
    s = str(chat_type).lower()
    if "." in s:
        s = s.split(".")[-1]
    return s


def is_private_chat(chat_or_message) -> bool:
    """Check if a chat, message, or callback query is a private PM."""
    return get_chat_type_str(chat_or_message) == "private"


NOISE_WORDS = {
    "download", "movie", "movies", "series", "season", "episode",
    "link", "links", "free", "full", "hd", "watch", "online"
}

def clean_search_query(query: str) -> str:
    """Strip punctuation and common search noise words to optimize search precision."""
    if not query:
        return ""

    clean = re.sub(r"[^\w\s]", " ", query)
    tokens = [t for t in clean.split() if t.lower() not in NOISE_WORDS]
    return " ".join(tokens) if tokens else query.strip()


def get_readable_size(size_bytes: int) -> str:
    """Format file size into clean representation (e.g., 454.47 MB, 2.68 GB)."""
    try:
        if size_bytes >= 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        elif size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} B"
    except Exception:
        return humanize.naturalsize(size_bytes, binary=True)


def format_clean_title(file_name: str) -> str:
    """Format file title into a clean, readable name with dots, hyphens, and extensions removed."""
    name = re.sub(r"[\._\-]+", " ", file_name)
    name = re.sub(r"\b(mkv|mp4|avi|webm|zip|rar)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip()
    return name or file_name


_POSTER_CACHE: dict[str, str] = {}

async def get_cached_poster_url(title: str) -> str:
    """Fetch poster URL from TMDB with memory and persistent MongoDB caching.
    Returns direct CDN image URL (e.g. https://image.tmdb.org/t/p/w500/...) or empty string.
    Zero VPS disk or bandwidth usage - images stream straight from TMDB CDN to user browser.
    """
    import urllib.parse
    import aiohttp
    from config import Config

    clean_q = re.sub(r"\s*\((?:19|20)\d{2}\).*", "", title).strip()
    clean_q = re.sub(r"\s*Season.*", "", clean_q, flags=re.IGNORECASE).strip()
    clean_q = re.sub(r"[\-_:\[\]\(\)]", " ", clean_q).strip()
    clean_q = re.sub(r"\s+", " ", clean_q)
    if not clean_q or len(clean_q) < 2 or clean_q.lower() in ["untitled", "movie video", "video", "none", "clip", "mediaclip"]:
        return ""

    # 1. Fast in-memory cache check
    if clean_q in _POSTER_CACHE and _POSTER_CACHE[clean_q]:
        return _POSTER_CACHE[clean_q]

    # 2. Custom manual poster check & Persistent MongoDB cache check
    try:
        from database.mongo import mongo
        norm_key = re.sub(r"[^\w]", "", clean_q.lower())
        custom_doc = await mongo.db["custom_posters"].find_one({
            "$or": [{"key": norm_key}, {"title": clean_q}]
        })
        if custom_doc and custom_doc.get("poster_url"):
            url = custom_doc["poster_url"]
            _POSTER_CACHE[clean_q] = url
            return url

        cached_doc = await mongo.db["poster_cache"].find_one({"title": clean_q})
        if cached_doc and cached_doc.get("poster_url"):
            url = cached_doc["poster_url"]
            _POSTER_CACHE[clean_q] = url
            return url
    except Exception:
        pass

    # 3. Live TMDB fetch via high-speed worker proxy with official API Key & progressive fallback
    api_key = getattr(Config, "TMDB_API_KEY", "") or "56b50689afe7438a51aab0d653679865"
    key_param = f"api_key={api_key}&" if api_key else ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    # Progressive queries: 1. Full clean title, 2. Truncate trailing subtitle/tag words (e.g. "Akka The Protectors" -> "Akka")
    queries_to_try = [clean_q]
    words = clean_q.split()
    if len(words) >= 2:
        for w_len in range(len(words) - 1, 0, -1):
            sub_q = " ".join(words[:w_len]).strip()
            if len(sub_q) >= 2 and sub_q not in queries_to_try:
                queries_to_try.append(sub_q)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0)) as session:
            for q_term in queries_to_try:
                encoded = urllib.parse.quote(q_term)
                endpoint = f"https://tmdbapi.the-zake.workers.dev/3/search/multi?{key_param}query={encoded}"
                async with session.get(endpoint, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        for r in results:
                            poster_path = r.get("poster_path")
                            if poster_path:
                                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                                _POSTER_CACHE[clean_q] = poster_url
                                _POSTER_CACHE[q_term] = poster_url
                                # Persist asynchronously to MongoDB
                                try:
                                    from database.mongo import mongo
                                    asyncio.create_task(
                                        mongo.db["poster_cache"].update_one(
                                            {"title": clean_q},
                                            {"$set": {"poster_url": poster_url}},
                                            upsert=True
                                        )
                                    )
                                    if q_term != clean_q:
                                        asyncio.create_task(
                                            mongo.db["poster_cache"].update_one(
                                                {"title": q_term},
                                                {"$set": {"poster_url": poster_url}},
                                                upsert=True
                                            )
                                        )
                                except Exception:
                                    pass
                                return poster_url
    except Exception:
        pass

    # Do NOT store empty string permanently on network hiccup/timeout, so next refresh can retry cleanly!
    return ""


def parse_media_metadata(filename: str, caption: str = "") -> dict:
    """Parse raw release filenames into clean titles, series/episode info, quality, and audio/codec badges."""
    if not filename:
        return {"title": "Movie Video", "quality": None, "badges": [], "is_dual_audio": False, "is_combined": False}

    raw = filename.strip()
    raw_no_ext = re.sub(r"\.(mkv|mp4|avi|webm|flv|mov|zip|rar)$", "", raw, flags=re.IGNORECASE).strip()
    norm = re.sub(r"[\._]", " ", raw_no_ext)

    # 1. Detect Quality
    qual_match = re.search(r"\b(2160p|4k|1080p|720p|540p|480p|360p)\b", norm, re.IGNORECASE)
    quality = qual_match.group(1).upper() if qual_match else None
    if quality == "2160P":
        quality = "4K"

    # 2. Detect Codec
    codec_match = re.search(r"\b(HEVC|H\.?265|x265|H\.?264|x264|AV1|10bit)\b", norm, re.IGNORECASE)
    codec = codec_match.group(1).upper() if codec_match else None

    # 3. Detect Source
    src_match = re.search(r"\b(WEB-?DL|WEBRip|BluRay|BRRip|HDRip|HDTV|CAMRip|PreDVD|HDCam|HDTS|TeleSync|DVDScr)\b", norm, re.IGNORECASE)
    src_map = {
        "predvd": "PreDVD",
        "hdcam": "HDCam",
        "hdts": "HDTS",
        "telesync": "TeleSync",
        "dvdscr": "DVDScr",
        "web-dl": "WEB-DL",
        "webdl": "WEB-DL",
        "webrip": "WEBRip",
        "bluray": "BluRay",
        "brrip": "BRRip",
        "hdrip": "HDRip",
        "hdtv": "HDTV",
        "camrip": "CAMRip"
    }
    source = src_map.get(src_match.group(1).lower(), src_match.group(1)) if src_match else None

    # 4. Detect Audio & Languages
    audio_tags = []
    languages = []
    lang_patterns = [
        ("Hindi", r"\b(Hindi|Hin)\b"),
        ("English", r"\b(English|Eng)\b"),
        ("Tamil", r"\b(Tamil|Tam)\b"),
        ("Telugu", r"\b(Telugu|Tel)\b"),
        ("Malayalam", r"\b(Malayalam|Mal)\b"),
        ("Kannada", r"\b(Kannada|Kan)\b"),
        ("Bengali", r"\b(Bengali|Ben|Bangla)\b"),
        ("Punjabi", r"\b(Punjabi|Panjabi|Pun)\b"),
        ("Marathi", r"\b(Marathi|Mar)\b"),
        ("Korean", r"\b(Korean|Kor)\b"),
        ("Japanese", r"\b(Japanese|Jap)\b"),
        ("Chinese", r"\b(Chinese|Chi)\b")
    ]
    is_dual = bool(re.search(r"\b(Dual[\s\.\-_]?Audio|Dual)\b", norm, re.IGNORECASE))
    is_multi = bool(re.search(r"\b(Multi[\s\.\-_]?Audio|Multi)\b", norm, re.IGNORECASE))

    for l_name, l_pat in lang_patterns:
        if re.search(l_pat, norm, re.IGNORECASE):
            languages.append(l_name)

    if is_multi or len(languages) >= 3:
        audio_tags.append("Multi Audio")
    elif is_dual or len(languages) >= 2:
        audio_tags.append("Dual Audio")

    for l in languages:
        if l not in audio_tags:
            audio_tags.append(l)

    if re.search(r"\b(DDP?[\s\.\-_]?5\.1|5\.1|Dolby|Atmos)\b", norm, re.IGNORECASE):
        audio_tags.append("Dolby 5.1")

    # 5. Detect Combined / Series / Episode Range Patterns
    range_m = re.search(r'\[\s*(?:E|EP)?\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\s*\]', norm, re.IGNORECASE)
    if not range_m:
        range_m = re.search(r'\(?\s*(?:E|EP)\s*\(?\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\s*\)?', norm, re.IGNORECASE)
    if not range_m:
        range_m = re.search(r'\b(?:E|EP)\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\b', norm, re.IGNORECASE)
    
    has_combined_word = bool(re.search(r'\b(COMBINED|COMPLETE|PACK|ALL\s*EPISODES)\b', norm, re.IGNORECASE))
    season_m = re.search(r'\b(?:S|Season)[\s._-]*(\d{1,2})(?:[\s._-]*(?:E|EP|Episode|x)[\s._-]*(\d{1,3}))\b', norm, re.IGNORECASE)
    if not season_m:
        season_m = re.search(r'\b(?:S|Season)[\s._-]*(\d{1,2})[\s._-]+(\d{1,3})\b', norm, re.IGNORECASE)
    if not season_m:
        season_m = re.search(r'\b(?:S|Season)[\s._-]*(\d{1,2})\b', norm, re.IGNORECASE)

    single_ep_m = re.search(r'\b(?:E|EP|Episode)[\s._-]*(\d{1,4})\b', norm, re.IGNORECASE)
    has_single_ep = bool(single_ep_m or (season_m and len(season_m.groups()) >= 2 and season_m.group(2)))
    year_m = re.search(r'\b(19\d{2}|20\d{2})\b', norm)

    # 5.a Detect Movie Multi-Part / CD / Disc (Part 1, Part 2, CD 1, CD 2, Disc 1, Disc 2, Pt 1, Pt 2, part001, part002, _001, _002)
    part_regex = re.compile(r'(?:[\s._\-\(\[]|^)(?:part|pt|cd|disc|disk)[\s._\-]*0*([1-9]\d?)(?:[\s._\-\)\]]|$)', re.IGNORECASE)
    segment_regex = re.compile(r'[_.-]00([1-9])\.(?:mkv|mp4|avi)$', re.IGNORECASE)

    is_part = False
    part_num = None
    part_label = None
    part_match_start = None

    if not season_m and not single_ep_m and not range_m:
        matches = list(part_regex.finditer(norm))
        if matches:
            last_m = matches[-1]
            part_num = int(last_m.group(1))
            matched_text = last_m.group(0)
            prefix = "CD" if re.search(r'\bCD\b', matched_text, re.IGNORECASE) else ("Disc" if re.search(r'\bDisc\b', matched_text, re.IGNORECASE) else "Part")
            part_label = f"{prefix} {part_num}"
            is_part = True
            part_match_start = last_m.start()
        else:
            seg_m = segment_regex.search(raw)
            if seg_m:
                part_num = int(seg_m.group(1))
                part_label = f"Part {part_num}"
                is_part = True
                part_match_start = seg_m.start()

    # 5.b Trailing and Leading episode numbers without 'E' prefix (e.g. "Title - 01 480p", "04 - Title")
    trail_ep_m = None
    lead_ep_m = None
    if not season_m and not single_ep_m and not range_m and not has_combined_word and not is_part:
        trail_match = re.search(
            r'(?:[-_–\s]+|\b)(?:(?:ep|e|episode|eps)[\s._-]*([1-9]\d{0,3})|(0[1-9]\d?))\s*(?:[-_–\s]+(?:480p|720p|1080p|2160p|4k|hevc|x264|x265|bluray|web|hdrip|dvdscr|aac|flac|hindi|english|dual)|$)',
            norm, re.IGNORECASE
        )
        if trail_match:
            cand_str = trail_match.group(1) or trail_match.group(2)
            if cand_str:
                cand_ep = int(cand_str)
                if not (year_m and trail_match.start() == year_m.start()):
                    trail_ep_m = trail_match

        if not trail_ep_m:
            lead_match = re.match(r'^\s*(0[1-9]\d?)\s*[-_–\s]+(.*?)$', norm, re.IGNORECASE)
            if lead_match:
                cand_lead_title = lead_match.group(2)
                if not re.search(r'\b(?:the[\s._-]*movie|movie)\b', cand_lead_title, re.IGNORECASE):
                    lead_ep_m = lead_match

    # A file with movie parts (Part 1, Part 2, CD 1) without an explicit Season marker is a MOVIE, NOT a series!
    is_series = bool((season_m or single_ep_m or range_m or has_combined_word or trail_ep_m or lead_ep_m) and not (is_part and not season_m))
    s_num = int(season_m.group(1)) if season_m else (1 if is_series else None)
    
    ep_num = None
    if is_series:
        if season_m and len(season_m.groups()) >= 2 and season_m.group(2):
            ep_num = int(season_m.group(2))
        elif single_ep_m:
            ep_num = int(single_ep_m.group(1))
        elif trail_ep_m:
            cand_s = trail_ep_m.group(1) or trail_ep_m.group(2)
            ep_num = int(cand_s) if cand_s else None
        elif lead_ep_m:
            ep_num = int(lead_ep_m.group(1))

    combined_badge = None
    extra_title = ""
    is_combined = False
    start_ep = None
    end_ep = None

    if range_m and int(range_m.group(1)) < int(range_m.group(2)):
        start_ep = int(range_m.group(1))
        end_ep = int(range_m.group(2))
        combined_badge = f"📦 Ep {start_ep:02d}–{end_ep:02d} (Combined)"
        s_num = int(season_m.group(1)) if season_m else 1
        extra_title = f" Season {s_num} (Ep {start_ep:02d}–{end_ep:02d})"
        is_combined = True
    elif has_combined_word and season_m:
        s_num = int(season_m.group(1))
        combined_badge = f"📁 Complete Season {s_num}"
        extra_title = f" Season {s_num} [Complete]"
        is_combined = True
        start_ep = 1
    elif season_m and not has_single_ep:
        s_num = int(season_m.group(1))
        combined_badge = f"📁 Season {s_num} Pack"
        extra_title = f" Season {s_num}"
        is_combined = True
        start_ep = 1

    # 6. Extract Clean Base Title (Everything before Year / Season / Episode / Part / Resolution)
    split_indices = []
    if season_m:
        split_indices.append(season_m.start())
    if single_ep_m:
        split_indices.append(single_ep_m.start())
    if trail_ep_m:
        split_indices.append(trail_ep_m.start())
    if range_m:
        split_indices.append(range_m.start())
    if part_match_start is not None:
        split_indices.append(part_match_start)
    if year_m:
        split_indices.append(year_m.start())
    if qual_match:
        split_indices.append(qual_match.start())
    if src_match:
        split_indices.append(src_match.start())

    from utils.title_cleaner import clean_movie_title

    base_title = ""
    # 6.a Leading number format (e.g. "04 - Suicide Squad Isekai" or "15 - Doraemon The Movie")
    lead_raw_m = re.match(r'^\s*0*([1-9]\d{0,2})\s*[-_–\s]+(.*?)$', norm, re.IGNORECASE)
    if lead_raw_m:
        cand_lead = lead_raw_m.group(2)
        clean_lead = clean_movie_title(cand_lead, keep_year=False) if cand_lead else ""
        if clean_lead and clean_lead.lower() not in ["untitled", "movie video", "video", "none"]:
            base_title = clean_lead

    # 6.b Candidate from text BEFORE season / episode / part / year / qual / src
    if not base_title and split_indices and min(split_indices) > 0:
        cand_before = norm[:min(split_indices)].strip(" -_~|:")
        clean_before = clean_movie_title(cand_before, keep_year=False) if cand_before else ""
        if clean_before and clean_before.lower() not in ["untitled", "movie video", "video", "none"]:
            base_title = clean_before

    # 6.c If base_title before was empty/generic, and it has season/episode tags (e.g. S01E01 Title or Episode 01 Title),
    # look AFTER the season/episode tag!
    if not base_title or base_title.lower() in ["untitled", "movie video", "video", "none"]:
        ep_ends = []
        if season_m:
            ep_ends.append(season_m.end())
        if single_ep_m:
            ep_ends.append(single_ep_m.end())
        if range_m:
            ep_ends.append(range_m.end())
        if ep_ends:
            last_ep_end = max(ep_ends)
            after_text = norm[last_ep_end:].strip(" -_~|:")
            cuts = []
            for pat in [
                r"\b(2160p|4k|1080p|720p|540p|480p|360p)\b",
                r"\b(19\d{2}|20\d{2})\b",
                r"\b(WEB-?DL|WEBRip|BluRay|BRRip|HDRip|HDTV|CAMRip)\b",
                r"\b(HEVC|H\.?265|x265|H\.?264|x264|AV1|10bit)\b"
            ]:
                m = re.search(pat, after_text, re.IGNORECASE)
                if m:
                    cuts.append(m.start())
            cand_after = after_text[:min(cuts)].strip(" -_~|:") if cuts else after_text
            clean_after = clean_movie_title(cand_after, keep_year=False) if cand_after else ""
            if clean_after and clean_after.lower() not in ["untitled", "movie video", "video", "none"]:
                base_title = clean_after

    # 6.d If still no clean title or title is a bare code (e.g. S02E01 720p AMZN...) and caption is provided:
    is_bare_code = bool(re.match(r'^(?:S\d{1,2}|E\d{1,3}|Season|Episode)\b', base_title, re.IGNORECASE)) if base_title else False
    if (not base_title or is_bare_code or base_title.lower() in ["untitled", "movie video", "video", "none"]) and caption:
        first_line = caption.strip().split("\n")[0].strip()
        if first_line:
            has_ep_in_cap = bool(re.search(r"\b(?:S\d{1,2}[\s._-]*E\d{1,3}|E\d{1,3}|Episode[\s._-]*\d{1,3})\b", first_line, re.IGNORECASE))
            if has_ep_in_cap:
                cap_meta = parse_media_metadata(first_line, caption="")
                cap_clean = cap_meta.get("clean_name")
                if cap_clean and not re.match(r"^(?:S\d{1,2}|E\d{1,3}|Season|Episode)\b", cap_clean, re.IGNORECASE) and cap_clean.lower() not in ["untitled", "movie video", "video", "none"]:
                    base_title = cap_clean
            if not base_title or is_bare_code or base_title.lower() in ["untitled", "movie video", "video", "none"]:
                clean_cap = clean_movie_title(first_line, keep_year=False)
                if clean_cap and not re.match(r"^(?:S\d{1,2}|E\d{1,3}|Season|Episode)\b", clean_cap, re.IGNORECASE) and clean_cap.lower() not in ["untitled", "movie video", "video", "none"]:
                    base_title = clean_cap

    # 6.e Final fallback to raw cleaned name
    if not base_title or base_title.lower() in ["untitled", "movie video", "video", "none"]:
        base_title = clean_movie_title(raw_no_ext, keep_year=False)
        if not base_title or base_title.lower() in ["untitled", "movie video", "video", "none"]:
            base_title = raw_no_ext[:40].strip() or "Media Clip"

    is_bare_code = bool(re.match(r'^(?:S\d{1,2}[\s._-]*E\d{1,3}|S\d{1,2}|E\d{1,3}|Season|Episode)\b', base_title, re.IGNORECASE)) if base_title else False

    yr_str = f" ({year_m.group(1)})" if year_m and year_m.group(1) not in base_title else ""
    part_suffix = f" [{part_label}]" if is_part and part_label else ""
    clean_title = f"{base_title}{yr_str}{extra_title}{part_suffix}".strip()
    clean_title = re.sub(r"\s+", " ", clean_title)

    badges = []
    if combined_badge:
        badges.append(combined_badge)
    if is_part and part_label:
        badges.append(f"🧩 {part_label}")
    if source:
        if source in ["PreDVD", "HDCam", "HDTS", "TeleSync", "DVDScr"]:
            badges.append(f"📹 {source}")
        else:
            badges.append(source)
    if quality:
        badges.append(quality)
    if codec:
        badges.append(codec)
    for at in audio_tags[:2]:
        if at not in badges:
            badges.append(at)

    return {
        "title": clean_title or raw,
        "clean_name": base_title,
        "is_bare_code": is_bare_code,
        "year": int(year_m.group(1)) if year_m else None,
        "season": s_num,
        "episode": ep_num,
        "start_ep": start_ep,
        "end_ep": end_ep,
        "is_series": is_series,
        "is_part": is_part,
        "part": part_num,
        "part_label": part_label,
        "quality": quality,
        "badges": badges,
        "languages": languages,
        "is_dual_audio": is_dual or "Dual Audio" in audio_tags or len(languages) >= 2,
        "is_multi_audio": is_multi or "Multi Audio" in audio_tags or len(languages) >= 3,
        "is_combined": is_combined
    }


def format_search_results_text(
    results: list,
    query: str,
    total_files: int,
    bot_username: str,
    user_mention: str = "User",
    elapsed_sec: str = None,
    page: int = 1,
    total_pages: int = 1,
    sponsor_ad: dict = None
) -> str:
    """Format search results as clean numbered clickable text links with exact sizes (Image 2 style)."""
    import html
    import urllib.parse
    lines = [
        f"🏷️ <b>TITLE :</b> <code>{html.escape(query)}</code>",
        f"📦 <b>TOTAL FILES :</b> <code>{total_files}</code>"
    ]
    if elapsed_sec:
        lines.append(f"⏰ <b>RESULT IN :</b> <code>{elapsed_sec} SECONDS</code>")
    lines.append("")
    lines.append(f"📝 <b>REQUESTED BY :</b> {user_mention}")
    lines.append(f"⚜️ <b>POWERED BY :</b> ⚡ @{bot_username}")
    lines.append("")
    lines.append("⏳ <i>This message will self-destruct in 5 minutes for privacy.</i>")
    lines.append("")
    lines.append("🧾 <u><b>Your Requested Files Are Here</b></u> 👇")
    lines.append("")

    start_idx = (page - 1) * 10 + 1 if page > 1 else 1
    for idx, item in enumerate(results, start=start_idx):
        f_id = item.get("file_unique_id")
        raw_name = item.get("file_name", "File")
        # Replace underscores with spaces so Telegram word-wraps cleanly without line breaks
        clean_name = html.escape(raw_name.replace("_", " "))
        size_str = get_readable_size(item.get("file_size", 0))
        link = f"https://t.me/{bot_username}?start=file_{f_id}"

        # Bold link with size & title so results pop out vibrantly in Telegram chat
        lines.append(f"<b>{idx}. <a href=\"{link}\">[{size_str}] {clean_name}</a></b>\n")

    # Dynamic Sponsor Ad Text Link (Clean, non-intrusive, zero keyboard clutter)
    if sponsor_ad and sponsor_ad.get("text") and sponsor_ad.get("url"):
        ad_title = html.escape(sponsor_ad["text"])
        ad_link = html.escape(sponsor_ad["url"])
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📢 <b>Sponsor:</b> <a href=\"{ad_link}\">{ad_title}</a>\n")

    return "\n".join(lines).strip()


def build_filter_buttons(
    results: list,
    page: int,
    total_pages: int,
    query: str,
    bot_username: str,
    is_pm: bool = False,
    mode: str = "single",
    quality: str = None,
    language: str = None,
    season: str = None
) -> InlineKeyboardMarkup:
    """Construct clean compact buttons with quick numbers, filter trigger, VIP, and pagination."""
    keyboard = []
    short_q = query[:20]

    # Row 0: 🪐 MovieVerse 3D (Explore Results) 🚀
    stream_base = getattr(Config, "STREAM_BASE_URL", None) or "https://akmovieverse.duckdns.org"
    if not stream_base or any(h in stream_base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
        stream_base = "https://akmovieverse.duckdns.org"

    import urllib.parse
    galaxy_search_url = f"{stream_base}/galaxy?q={urllib.parse.quote_plus(query)}"

    if is_pm:
        btn_3d = InlineKeyboardButton("🪐 MovieVerse 3D (Explore Results) 🚀", web_app=WebAppInfo(url=galaxy_search_url))
    else:
        btn_3d = InlineKeyboardButton("🪐 MovieVerse 3D (Explore Results) 🚀", url=f"https://t.me/{bot_username}?start=galaxy_{urllib.parse.quote_plus(short_q)}")

    keyboard.append([btn_3d])

    # Row 1: Single clean prominent Filter Button
    keyboard.append([
        InlineKeyboardButton("🔍 Filter Results", callback_data=f"snav:init:{short_q}")
    ])

    # Row 2: VIP / Remove Ads & Send All
    btn_send_all = InlineKeyboardButton("📥 SEND ALL", callback_data=f"sendall_{short_q}_{page}")
    if getattr(Config, "SHORTENER_ENABLED", True):
        btn_label = "⚜️ Remove ads ⚜️"
    else:
        btn_label = "👑 VIP Plans 👑"

    if is_pm:
        btn_vip = InlineKeyboardButton(btn_label, callback_data="view_plans")
    else:
        plans_url = f"https://t.me/{bot_username}?start=plans"
        btn_vip = InlineKeyboardButton(f"{btn_label} ↗️", url=plans_url)
    keyboard.append([btn_vip, btn_send_all])

    # Optional Quick Number Buttons (default OFF to eliminate mobile screen clutter; direct title clicks handle file delivery)
    if getattr(Config, "SHOW_NUM_BUTTONS", False) and results:
        number_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        num_row = []
        for idx, item in enumerate(results):
            f_id = item.get("file_unique_id")
            icon = number_icons[idx] if idx < len(number_icons) else f"{idx + 1}"
            if is_pm:
                btn = InlineKeyboardButton(icon, callback_data=f"getfile_{f_id}")
            else:
                btn = InlineKeyboardButton(icon, url=f"https://t.me/{bot_username}?start=file_{f_id}")
            num_row.append(btn)
            if len(num_row) == 5:
                keyboard.append(num_row)
                num_row = []
        if num_row:
            keyboard.append(num_row)

    # Pagination navigation row
    if total_pages <= 1:
        keyboard.append([InlineKeyboardButton("↔️ NO MORE PAGES AVAILABLE ↔️", callback_data="noop_pages")])
    else:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ PREV", callback_data=f"page_{page - 1}_{short_q}"))

        nav_row.append(InlineKeyboardButton(f"📄 {page} / {total_pages}", callback_data="noop_pages"))

        if page < total_pages:
            nav_row.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"page_{page + 1}_{short_q}"))

        keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)



def build_category_keyboard(query: str, cat_type: str = "all") -> InlineKeyboardMarkup:
    """Build sub-filter selection keyboard matching requested category."""
    short_q = query[:20]

    if cat_type == "quality":
        keyboard = [
            [
                InlineKeyboardButton("🟠 480p", callback_data=f"setqual_480p_{short_q}"),
                InlineKeyboardButton("🔵 720p", callback_data=f"setqual_720p_{short_q}")
            ],
            [
                InlineKeyboardButton("🟢 1080p", callback_data=f"setqual_1080p_{short_q}"),
                InlineKeyboardButton("🟡 4K (2160p)", callback_data=f"setqual_2160p_{short_q}")
            ],
            [
                InlineKeyboardButton("🔄 Clear Quality Filter", callback_data=f"clearqual_{short_q}"),
                InlineKeyboardButton("◀️ Back to Results", callback_data=f"backres_{short_q}")
            ]
        ]
    elif cat_type == "language":
        keyboard = [
            [
                InlineKeyboardButton("🇮🇳 Hindi", callback_data=f"setlang_hindi_{short_q}"),
                InlineKeyboardButton("🇬🇧 English", callback_data=f"setlang_english_{short_q}")
            ],
            [
                InlineKeyboardButton("🇮🇳 Tamil", callback_data=f"setlang_tamil_{short_q}"),
                InlineKeyboardButton("🇮🇳 Telugu", callback_data=f"setlang_telugu_{short_q}")
            ],
            [
                InlineKeyboardButton("🌐 Dual / Multi Audio", callback_data=f"setlang_dual_{short_q}")
            ],
            [
                InlineKeyboardButton("🔄 Clear Language Filter", callback_data=f"clearlang_{short_q}"),
                InlineKeyboardButton("◀️ Back to Results", callback_data=f"backres_{short_q}")
            ]
        ]
    elif cat_type == "season":
        keyboard = [
            [
                InlineKeyboardButton("Season 1", callback_data=f"setseas_s01_{short_q}"),
                InlineKeyboardButton("Season 2", callback_data=f"setseas_s02_{short_q}")
            ],
            [
                InlineKeyboardButton("Season 3", callback_data=f"setseas_s03_{short_q}"),
                InlineKeyboardButton("Season 4", callback_data=f"setseas_s04_{short_q}")
            ],
            [
                InlineKeyboardButton("Season 5", callback_data=f"setseas_s05_{short_q}"),
                InlineKeyboardButton("Season 6", callback_data=f"setseas_s06_{short_q}")
            ],
            [
                InlineKeyboardButton("🔄 Clear Season Filter", callback_data=f"clearseas_{short_q}"),
                InlineKeyboardButton("◀️ Back to Results", callback_data=f"backres_{short_q}")
            ]
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton("QUALITY", callback_data=f"openqual_{short_q}"),
                InlineKeyboardButton("LANGUAGE", callback_data=f"openlang_{short_q}"),
                InlineKeyboardButton("SEASON", callback_data=f"openseas_{short_q}")
            ],
            [
                InlineKeyboardButton("🔄 Reset All Filters", callback_data=f"resetfilter_{short_q}"),
                InlineKeyboardButton("◀️ Back to Results", callback_data=f"backres_{short_q}")
            ]
        ]

    return InlineKeyboardMarkup(keyboard)


_RESOLVED_CHANNEL_CACHE: dict[str, tuple[str, str]] = {}

async def resolve_channel_display_and_url(client, target=None) -> tuple[str, str]:
    """
    Safely resolve channel target into (display_name, clickable_telegram_url).
    Never produces invalid URLs like 'https://t.me/-100...'.
    Handles channel IDs, usernames, and invite links with caching.
    """
    bot_username = Config.BOT_USERNAME or (getattr(client, "me", None).username if getattr(client, "me", None) else "")
    if not bot_username and hasattr(client, "get_me"):
        try:
            me = await client.get_me()
            bot_username = me.username or ""
        except Exception:
            pass

    default_fallback_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"
    default_title = "Updates Channel"

    # Candidates to inspect in priority order
    candidates = []
    if target is not None and str(target).strip():
        candidates.append(str(target).strip())
    if Config.CHANNEL_URL:
        candidates.append(str(Config.CHANNEL_URL).strip())
    if Config.FORCE_SUB_CHANNELS:
        for ch in Config.FORCE_SUB_CHANNELS:
            candidates.append(str(ch).strip())
    if getattr(Config, "UPDATES_CHANNEL", None):
        candidates.append(str(Config.UPDATES_CHANNEL).strip())

    for cand in candidates:
        if not cand:
            continue

        # 1. Already a full URL
        if cand.startswith("http://") or cand.startswith("https://"):
            # Check if someone passed a broken https://t.me/-100... URL
            if re.search(r"t\.me/-100\d+", cand):
                m = re.search(r"-100\d+", cand)
                if m:
                    cand = m.group(0)
                else:
                    continue
            else:
                name = cand.rstrip("/").split("/")[-1].lstrip("+").lstrip("@")
                return (name or default_title, cand)

        # 2. Public Channel username (e.g. @AkMovieVerse or AkMovieVerse)
        if not cand.lstrip("-").isdigit():
            clean_user = cand.lstrip("@").strip()
            if clean_user:
                return (clean_user, f"https://t.me/{clean_user}")

        # 3. Numeric Channel ID (e.g. -1002779576540)
        if cand in _RESOLVED_CHANNEL_CACHE:
            return _RESOLVED_CHANNEL_CACHE[cand]

        if cand.lstrip("-").isdigit():
            try:
                chat_id = int(cand)
                chat = await client.get_chat(chat_id)
                title = chat.title or default_title
                if chat.username:
                    url = f"https://t.me/{chat.username}"
                elif chat.invite_link:
                    url = chat.invite_link
                else:
                    url = await client.export_chat_invite_link(chat_id)
                _RESOLVED_CHANNEL_CACHE[cand] = (title, url)
                return (title, url)
            except Exception as e:
                logger.debug(f"Could not resolve channel id {cand}: {e}")
                continue

    return (default_title, default_fallback_url)

