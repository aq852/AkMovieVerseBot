import re
import logging
from database.mongo import mongo

logger = logging.getLogger(__name__)

# Exhaustive catalog of pirated sites, Telegram rippers, and release groups
STATIC_PIRATE_SITES = [
    # 🇮🇳 South / Regional (Tamil, Telugu, Malayalam, Kannada)
    r"1TamilMV", r"TamilMV", r"TamilBlasters", r"1TamilBlasters", r"MovieRulz", r"7MovieRulz",
    r"Movierulz4", r"Movierulz123", r"ibomma", r"iBOMMA", r"TeluguPalaka", r"TeluguWap",
    r"JioRockers", r"TodayPk", r"Tamilrockers", r"Moviesda", r"Isaimini", r"Kuttymovies",
    r"CinemaVilla", r"MalluMV", r"Cinevez", r"Masstamilan", r"AhaMusic", r"Sensongs",
    # 🎬 Hindi / Bollywood / Dual Audio Portals
    r"VegaMovies", r"VegamoviesNL", r"BollyFlix", r"KatmovieHD", r"Katmovies", r"SkymoviesHD",
    r"SkyMovies", r"HDHub4u", r"HDHub", r"EonMovies", r"MoviezAdda", r"Cinevood", r"MoviesFlix",
    r"FilmyZilla", r"Filmywap", r"FilmyMeet", r"FilmyGod", r"Movies4u", r"WorldFree4u",
    r"9xmovies", r"7starhd", r"MKVcinemas", r"MKVking", r"DesireMovies", r"AllMoviesHub",
    r"MoviesVerse", r"MoviesMod", r"ExtraMovies", r"JalshaMoviez", r"MP4Moviez", r"Pagalmovies",
    r"RdxHD", r"Khatrimaza", r"CoolMoviez", r"UWatchFree", r"HDFriday", r"Bolly4u", r"Filmyfly",
    r"Moviesbaba", r"OlaMovies", r"Dotmovies", r"YoMovies", r"GdriveMovies", r"GoMovies",
    r"TopMovies", r"Filmiez", r"HDMovieArea", r"HubFlix", r"DownloadHub",
    # 🌐 Torrents & Scene/P2P Encoders
    r"1337x", r"YTS", r"YIFY", r"RARBG", r"ThePirateBay", r"TPB", r"EZTV", r"LimeTorrents",
    r"Kickass", r"KAT", r"TorrentGalaxy", r"TGx", r"BitSearch", r"Torrentz", r"PSA", r"Pahe",
    r"QxR", r"GalaxyRG", r"UTR", r"Tigole", r"Joy", r"Silence", r"Vyndros", r"MeGusta", r"EVO",
    r"CMRG", r"FGT", r"NTG", r"FLUX", r"SWAPNONIL", r"ADDYRIPS", r"Ironclad", r"neoDESU",
    r"KyoGo", r"Itachi_Uchiha", r"neoHEVC", r"Prof", r"mSD", r"ION10", r"SubsPlease",
    r"Erai-raws", r"HorribleSubs", r"Judg3", r"EMBER", r"TombDoc", r"DUST"
]

PIRATE_SITES_PATTERN = re.compile(r"\b(?:" + "|".join(STATIC_PIRATE_SITES) + r")\b", re.IGNORECASE)

URL_AND_WWW_PATTERN = re.compile(
    r"\bwww[\s\._-]*\S+?[\s\._-]*(?:style|com|net|org|in|vip|cc|to|cz|ms|tc|ws|me|lol|link|live|buzz|click|fun|icu|art|pw|space|top|club|site|app|is|pm|cx|wf|pro|info|biz|eu|asia|tv|guru|wiki|xyz|co|uk|us|ca|ru|io|yt|so|mobi|cam)\b|"
    r"\b(?:https?://|www\.)\S+|"
    r"\b[a-zA-Z0-9_\-]+\.(?:com|org|net|in|cz|top|club|vip|cc|xyz|to|ms|tc|site|app|link|buzz|icu|live|fun|info|pro|cx|wf|so|lol|me|is|pm|co|us|biz|tv|mx|cam)\b|"
    r"@[a-zA-Z0-9_]+|"
    r"\b(?:t\.me|telegram\.me|join[\s_]*telegram|join[\s_]*backup|join[\s_]*channel)[\s_:/@]*\S*",
    re.IGNORECASE
)

CLUTTER_WORDS_PATTERN = re.compile(
    r"\b(?:style|clean[\s._-]*audio|line[\s._-]*audio|hq[\s._-]*mic|hq[\s._-]*rip|cleaned[\s._-]*audio|"
    r"exclusive|unrated|v[1-4]|proper|repack|pre-?dvd|hdcam|hdts|telesync|dvdscr|camrip|"
    r"x264|x265|hevc|10bit|ddp5\.1|5\.1|atmos|aac|mp3|ac3)\b",
    re.IGNORECASE
)

# In-memory cache for dynamic junk words
_DYNAMIC_JUNK_CACHE = None


async def get_dynamic_junk_words() -> set[str]:
    """Retrieve dynamic junk words from MongoDB with in-memory caching."""
    global _DYNAMIC_JUNK_CACHE
    if _DYNAMIC_JUNK_CACHE is not None:
        return _DYNAMIC_JUNK_CACHE

    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "dynamic_junk_words"})
        if doc and "words" in doc:
            _DYNAMIC_JUNK_CACHE = set(w.lower().strip() for w in doc["words"] if w.strip())
            return _DYNAMIC_JUNK_CACHE
    except Exception as e:
        logger.debug(f"Error fetching dynamic junk words: {e}")

    _DYNAMIC_JUNK_CACHE = set()
    return _DYNAMIC_JUNK_CACHE


async def add_dynamic_junk_word(word: str) -> bool:
    """Add a new custom junk word or site tag to MongoDB blacklist."""
    global _DYNAMIC_JUNK_CACHE
    clean_w = word.strip().lower()
    if not clean_w:
        return False

    current_words = await get_dynamic_junk_words()
    current_words.add(clean_w)
    _DYNAMIC_JUNK_CACHE = current_words

    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "dynamic_junk_words"},
            {"$set": {"words": list(current_words)}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error saving dynamic junk word '{clean_w}': {e}")
        return False


async def remove_dynamic_junk_word(word: str) -> bool:
    """Remove a custom junk word from MongoDB blacklist."""
    global _DYNAMIC_JUNK_CACHE
    clean_w = word.strip().lower()
    current_words = await get_dynamic_junk_words()
    if clean_w in current_words:
        current_words.remove(clean_w)
        _DYNAMIC_JUNK_CACHE = current_words
        try:
            await mongo.db["bot_settings"].update_one(
                {"key": "dynamic_junk_words"},
                {"$set": {"words": list(current_words)}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error removing dynamic junk word '{clean_w}': {e}")
            return False
    return False


def clean_movie_title(raw_name: str, keep_year: bool = True) -> str:
    """Master Title Sanitizer: Strip site URLs, pirate watermarks, rip words, and clutter while keeping clean movie title."""
    if not raw_name:
        return "Untitled"

    s = raw_name.strip()

    # 1. Strip file extension (with dot or preceding whitespace)
    s = re.sub(r"[\s\.]+(?:mkv|mp4|avi|webm|flv|mov|zip|rar)$", "", s, flags=re.IGNORECASE)

    # 2. Strip URLs, domain names, and www prefixes (e.g. 'www 1TamilMV style')
    s = URL_AND_WWW_PATTERN.sub(" ", s)

    # 3. Strip known pirate websites and release groups
    s = PIRATE_SITES_PATTERN.sub(" ", s)

    # 4. Strip dynamic junk words if cached in memory
    if _DYNAMIC_JUNK_CACHE:
        for jw in _DYNAMIC_JUNK_CACHE:
            s = re.sub(rf"\b{re.escape(jw)}\b", " ", s, flags=re.IGNORECASE)

    # 5. Extract year if present
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    year_val = year_m.group(1) if year_m else None

    # 6. Strip clutter words, codecs, audio tags
    s = CLUTTER_WORDS_PATTERN.sub(" ", s)

    # 7. Strip square brackets promos [ ... ] and orphan domain extensions
    s = re.sub(r"\[\s*\]", " ", s)
    s = re.sub(r"\[.*?\]", " ", s)
    s = re.sub(r"\b(?:org|com|net|vip|cc|cz|link|buzz|site|club|app)\b", " ", s, flags=re.IGNORECASE)

    # 8. Punctuation cleanup (replace dots and symbols with spaces)
    s = re.sub(r"[\._]", " ", s)
    s = re.sub(r"[\[\]\(\)\{\}\-\:,\/\\@~|'\"]", " ", s)

    # 9. Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip(" -_~|:[]()")

    # If keep_year is requested and title doesn't contain year, re-append clean (YYYY)
    if keep_year and year_val and year_val not in s:
        s = f"{s} ({year_val})"

    return s if s else "Movie Video"


def is_tmdb_match_valid(query_title: str, result_title: str) -> bool:
    """Anti-Hallucination Guard: Validates that TMDB match actually corresponds to the searched movie title."""
    if not query_title or not result_title:
        return False

    q_clean = query_title.strip().lower()
    r_clean = result_title.strip().lower()
    if q_clean == r_clean:
        return True

    ignore = {
        "the", "a", "an", "movie", "film", "house", "no", "part", "pt", "vol",
        "season", "s", "ep", "episode", "rule", "story", "chapter", "edition", "series"
    }

    q_tokens_list = [t for t in re.findall(r"\w+", q_clean) if t not in ignore and not t.isdigit() and len(t) >= 2]
    r_tokens_list = [t for t in re.findall(r"\w+", r_clean) if t not in ignore and not t.isdigit() and len(t) >= 2]

    # If completely filtered out, fall back to non-ignore tokens
    if not q_tokens_list:
        q_tokens_list = [t for t in re.findall(r"\w+", q_clean) if len(t) >= 2]
    if not r_tokens_list:
        r_tokens_list = [t for t in re.findall(r"\w+", r_clean) if len(t) >= 2]

    q_sig = set(q_tokens_list)
    r_sig = set(r_tokens_list)
    overlap = q_sig.intersection(r_sig)

    if not overlap:
        return False

    q_primary = q_tokens_list[0] if q_tokens_list else None

    # Primary token of query must be present in result
    if q_primary and q_primary in r_sig:
        # If both query and result have >= 2 tokens, ensure at least 2 tokens overlap or one is a subset
        if len(q_sig) >= 2 and len(r_sig) >= 2:
            return len(overlap) >= 2 or r_sig.issubset(q_sig) or q_sig.issubset(r_sig)
        return True

    # High token overlap fallback (e.g. >= 60%)
    if len(q_sig) > 0 and (len(overlap) / len(q_sig)) >= 0.6:
        return True

    return False


def sanitize_stored_filename(fn: str) -> str:
    """Sanitize filename stored in database by removing website watermarks, ripper tags, and clutter while keeping extension, movie title, and quality intact."""
    if not fn:
        return fn

    # Only clean if watermark/pirate sites or URL pattern is present
    has_pirate = bool(PIRATE_SITES_PATTERN.search(fn))
    has_url = bool(re.search(r'\b(?:www|http|t\.me|\.style|\.org|\.com|\.net|\.xyz|\.cam|\.ms|\.cc|\.vip|\.club|\.buzz)\b|@[a-zA-Z0-9_]+', fn, re.IGNORECASE))
    has_dynamic = False
    if _DYNAMIC_JUNK_CACHE:
        has_dynamic = any(re.search(rf'\b{re.escape(w)}\b', fn, re.IGNORECASE) for w in _DYNAMIC_JUNK_CACHE)

    if not (has_pirate or has_url or has_dynamic):
        return fn

    ext_m = re.search(r'\.([a-zA-Z0-9]{2,4})$', fn)
    ext = f'.{ext_m.group(1)}' if ext_m else ''
    base = fn[:-len(ext)] if ext else fn

    # 1. Strip URLs & www patterns
    base = re.sub(r'\bwww[\s\._-]*\S+?[\s\._-]*(?:style|com|net|org|in|vip|cc|to|cz|ms|tc|ws|me|lol|link|live|buzz|click|fun|icu|art|pw|space|top|club|site|app|is|pm|cx|wf|pro|info|biz|eu|asia|tv|guru|wiki|xyz|co|uk|us|ca|ru|io|yt|so|mobi|cam)\b', '', base, flags=re.IGNORECASE)
    base = re.sub(r'\b(?:https?://|www\.)\S+', '', base, flags=re.IGNORECASE)
    base = re.sub(r'\b[a-zA-Z0-9_\-]+\.(?:com|org|net|xyz|club|site|link|buzz|icu|top|vip|cc|cz|ms|tc|click|pw|space|guru|wiki|tv|biz|cam)\b', '', base, flags=re.IGNORECASE)
    base = re.sub(r'@[a-zA-Z0-9_]+', '', base)
    base = re.sub(r'\b(?:t\.me|telegram\.me|join[\s_]*telegram|join[\s_]*backup|join[\s_]*channel)[\s_:/@]*\S*', '', base, flags=re.IGNORECASE)

    # 2. Strip pirate sites
    base = PIRATE_SITES_PATTERN.sub('', base)

    # 3. Strip dynamic junk words if any
    if _DYNAMIC_JUNK_CACHE:
        for jw in _DYNAMIC_JUNK_CACHE:
            base = re.sub(rf'\b{re.escape(jw)}\b', '', base, flags=re.IGNORECASE)

    # 4. Strip brackets containing remaining extensions or empties
    base = re.sub(r'\[\s*(?:\.\w+)?\s*\]', '', base)
    base = re.sub(r'-\s*\[.*?\]', '', base)
    base = re.sub(r'\[\s*\]|\(\s*\)', '', base)
    base = re.sub(r'\[\s*$', '', base)
    base = re.sub(r'--+|__+|\.\.+', '.', base)
    base = re.sub(r'^\s*[-_.\s]+|\s*[-_.\s]+$', '', base)
    base = re.sub(r'\s+', ' ', base).strip()
    return f'{base}{ext}' if base else fn


def extract_core_title(raw_name: str) -> str:
    """Extract clean core movie/series title without years, episodes, season packs, audio channels, or codecs.
    Used by fuzzy spell-check and search fallback to prevent release years and tags from triggering false matches.
    """
    if not raw_name:
        return ""
    # 1. Remove bracket promos, paren groups, dots, and separators
    s = re.sub(r"\[.*?\]|\(.*?\)", " ", raw_name)
    s = re.sub(r"[\._\-\+]", " ", s)
    # 2. Remove 4-digit release years (1900-2099) so they never trigger fuzzy false matches
    s = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", s)
    # 3. Remove season, episode, pack tags
    s = re.sub(r"\b(?:s\d+|e\d+(?:-\d+)?|season\s*\d+|episode\s*\d+|ep\s*\d+|combined|complete|pack|part\s*\d+)\b", " ", s, flags=re.IGNORECASE)
    # 4. Remove qualities, codecs, audio, rip tags
    s = re.sub(r"\b(?:1080p|720p|480p|2160p|4k|uhd|hd|sd|hevc|x264|x265|10bit|web-?dl|webrip|bluray|brrip|dvdrip|hdtc|camrip|aac|mp3|mkv|mp4|avi|ddp5\.1|5\.1|dual[\s_]*audio|multi[\s_]*audio|hindi|english|telugu|tamil|kannada|malayalam|imax)\b", " ", s, flags=re.IGNORECASE)
    # 5. Remove trailing orphan single letters
    s = re.sub(r"\b[a-zA-Z]\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
