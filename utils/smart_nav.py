import re
import time
import math
import logging
from bson.objectid import ObjectId

try:
    from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database.mongo import mongo
from utils.helpers import get_readable_size, format_clean_title

logger = logging.getLogger("autofilter.smart_nav")

# In-memory session cache: {sid: session_dict}
# Automatic TTL cleanup after 2 hours
_SESSIONS: dict[str, dict] = {}

LANGUAGE_DISPLAY = {
    "hindi": "🌐 Hindi",
    "english": "🌐 English",
    "dual": "🌐 Dual Audio",
    "multi": "🌐 Multi Audio",
    "tamil": "🌐 Tamil",
    "telugu": "🌐 Telugu",
    "malayalam": "🌐 Malayalam",
    "kannada": "🌐 Kannada"
}

QUALITY_ORDER = ["4K", "1080p", "720p", "480p"]


def create_nav_session(query: str, user_id: int, chat_id: int, is_pm: bool, bot_username: str) -> str:
    """Create a lightweight navigator session and return 6-character session ID."""
    _clean_expired_sessions()
    import uuid
    sid = uuid.uuid4().hex[:6]
    _SESSIONS[sid] = {
        "sid": sid,
        "query": query.strip(),
        "user_id": user_id,
        "chat_id": chat_id,
        "is_pm": is_pm,
        "bot_username": bot_username,
        "media_type": None,  # "movie" or "series"
        "season": None,
        "mode": None,        # "pack" or "episode"
        "episode": None,
        "language": None,
        "quality": None,
        "page": 1,
        "ep_page": 1,
        "created_at": time.time()
    }
    return sid


def get_nav_session(sid: str) -> dict | None:
    """Fetch session data by ID."""
    return _SESSIONS.get(sid)


def update_nav_session(sid: str, **kwargs):
    """Update fields in an active session."""
    if sid in _SESSIONS:
        _SESSIONS[sid].update(kwargs)


def _clean_expired_sessions():
    """Purge sessions older than 2 hours."""
    now = time.time()
    expired = [k for k, v in _SESSIONS.items() if now - v.get("created_at", 0) > 7200]
    for k in expired:
        _SESSIONS.pop(k, None)


def parse_filename_metadata(filename: str) -> dict:
    """Accurately identify season, episodes, packs, language, and quality from filename."""
    if not filename:
        return {
            "season": None,
            "episodes": [],
            "is_pack": False,
            "language": None,
            "quality": None,
            "is_series": False
        }

    norm = re.sub(r"[\._]", " ", filename)

    # 1. Season detection
    season = None
    s_m = re.search(r"\b(?:s|season)[\s._-]*(\d{1,2})(?:(?=[A-Z])|\b)", norm, re.I)
    if s_m:
        season = int(s_m.group(1))

    # 2. Episode range detection (e.g. [E01-E05], Ep 1 to 5, [1-10])
    range_m = re.search(r"\[\s*(?:E|EP)?\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\s*\]", norm, re.I)
    if not range_m:
        range_m = re.search(r"\b(?:E|EP)\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\b", norm, re.I)

    # Pack / Combined indicator
    is_pack_word = bool(re.search(r"\b(COMBINED|COMPLETE|PACK|ALL\s*EPISODES|ZIP|FULL)\b", norm, re.I))

    episodes = set()
    is_pack = is_pack_word

    if range_m:
        start_e, end_e = int(range_m.group(1)), int(range_m.group(2))
        if start_e <= end_e and (end_e - start_e) <= 60:
            episodes.update(range(start_e, end_e + 1))
            is_pack = True

    # 3. Single episode detection (e.g. S01E03, E03, Ep 08, Episode 1050)
    for ep_find in re.finditer(r"(?:\b|S\d{1,2})(?:E|EP|Episode)[\s._-]*(\d{1,4})\b", norm, re.I):
        episodes.add(int(ep_find.group(1)))

    # If season exists but NO episode numbers exist at all (like Matargashti.2026.S01.720p.mkv)
    # Then it is a Complete Season single file!
    if season is not None and not episodes and not range_m:
        is_pack = True

    is_series = bool(season is not None or episodes or is_pack_word)

    # 4. Language detection
    lang = None
    if re.search(r"\b(Dual[\s\.\-_]?Audio|Dual)\b", norm, re.I):
        lang = "dual"
    elif re.search(r"\b(Multi[\s\.\-_]?Audio|Multi)\b", norm, re.I):
        lang = "multi"
    elif re.search(r"\b(Hindi|Hin)\b", norm, re.I):
        lang = "hindi"
    elif re.search(r"\b(English|Eng)\b", norm, re.I):
        lang = "english"
    elif re.search(r"\b(Telugu|Tel)\b", norm, re.I):
        lang = "telugu"
    elif re.search(r"\b(Tamil|Tam)\b", norm, re.I):
        lang = "tamil"
    elif re.search(r"\b(Malayalam|Mal)\b", norm, re.I):
        lang = "malayalam"
    elif re.search(r"\b(Kannada|Kan)\b", norm, re.I):
        lang = "kannada"

    # 5. Quality detection
    qual = None
    q_m = re.search(r"\b(2160p|4k|1080p|720p|540p|480p|360p)\b", norm, re.I)
    if q_m:
        q_raw = q_m.group(1).lower()
        if q_raw in ("2160p", "4k"):
            qual = "4K"
        elif q_raw == "1080p":
            qual = "1080p"
        elif q_raw == "720p":
            qual = "720p"
        else:
            qual = "480p"

    return {
        "season": season,
        "episodes": sorted(list(episodes)),
        "is_pack": is_pack,
        "language": lang,
        "quality": qual,
        "is_series": is_series
    }


async def analyze_query_media(query: str) -> dict:
    """Scan matching files from MongoDB to dynamically discover seasons, episodes, languages, and media type."""
    from database.files import _build_search_filter
    filter_dict = _build_search_filter(query)

    cursor = mongo.files.find(filter_dict).sort([("_id", -1)]).limit(300)
    docs = await cursor.to_list(300)

    seasons_dict = {}
    movie_langs = set()
    movie_quals = set()
    series_count = 0
    movie_count = 0

    for doc in docs:
        fn = doc.get("file_name", "")
        meta = parse_filename_metadata(fn)

        if meta["is_series"]:
            series_count += 1
            s_num = meta["season"] or 1
            if s_num not in seasons_dict:
                seasons_dict[s_num] = {
                    "episodes": set(),
                    "has_complete": False,
                    "has_episodes": False,
                    "file_count": 0
                }
            seasons_dict[s_num]["file_count"] += 1

            if meta["is_pack"]:
                seasons_dict[s_num]["has_complete"] = True

            if meta["episodes"]:
                seasons_dict[s_num]["has_episodes"] = True
                seasons_dict[s_num]["episodes"].update(meta["episodes"])
        else:
            movie_count += 1
            if meta["language"]:
                movie_langs.add(meta["language"])
            if meta["quality"]:
                movie_quals.add(meta["quality"])

    # Finalize sorted seasons data
    final_seasons = {}
    for s_num in sorted(seasons_dict.keys()):
        s_data = seasons_dict[s_num]
        final_seasons[s_num] = {
            "episodes": sorted(list(s_data["episodes"])),
            "has_complete": s_data["has_complete"],
            "has_episodes": s_data["has_episodes"],
            "file_count": s_data["file_count"]
        }

    return {
        "query": query,
        "total_files": len(docs),
        "has_series": series_count > 0,
        "has_movies": movie_count > 0,
        "series_count": series_count,
        "movie_count": movie_count,
        "seasons": final_seasons,
        "movie_languages": sorted(list(movie_langs)),
        "movie_qualities": [q for q in QUALITY_ORDER if q in movie_quals]
    }


async def fetch_filtered_files(
    query: str,
    media_type: str = None,
    season: int = None,
    mode: str = None,
    episode: int = None,
    language: str = None,
    quality: str = None,
    offset: int = 0,
    limit: int = 10
) -> tuple[list, int]:
    """Retrieve exactly matched files with newest uploads first (Rank 1)."""
    from database.files import _build_search_filter
    base_filter = _build_search_filter(query)

    # Pull candidate matching docs sorted strictly by latest upload (_id: -1)
    cursor = mongo.files.find(base_filter).sort([("_id", -1)]).limit(300)
    all_candidates = await cursor.to_list(300)

    matched = []

    for doc in all_candidates:
        fn = doc.get("file_name", "")
        meta = parse_filename_metadata(fn)

        if media_type == "movie":
            # Exclude series files
            if meta["is_series"] and meta["season"] is not None:
                continue
            if language and meta["language"] != language.lower():
                continue
            if quality and meta["quality"] != quality:
                continue
            matched.append(doc)

        elif media_type == "series":
            # Must match target season
            file_s = meta["season"] or 1
            if season is not None and file_s != season:
                continue

            if mode == "pack":
                # Only complete/combined pack files
                if meta["is_pack"]:
                    matched.append(doc)

            elif mode == "episode":
                # Must match exact episode or be an episode range containing target episode
                if episode is not None:
                    if episode in meta["episodes"]:
                        matched.append(doc)
                    elif not meta["episodes"] and meta["is_pack"]:
                        pass  # Don't show pure full season packs in single episode view
                else:
                    matched.append(doc)
            else:
                matched.append(doc)

        else:
            matched.append(doc)

    total_matched = len(matched)
    paginated = matched[offset: offset + limit]
    return paginated, total_matched


# ==========================================
# UI VIEW BUILDERS (R2-Style Guided Flow)
# ==========================================

async def build_navigator_root_view(sid: str) -> tuple[str, InlineKeyboardMarkup]:
    """Build root filter view: Movie or Series selection, or direct jump if only one type exists."""
    sess = get_nav_session(sid)
    if not sess:
        return "❌ <b>Session Expired.</b> Please search again.", InlineKeyboardMarkup([[InlineKeyboardButton("🔍 New Search", callback_data="noop")]])

    query = sess["query"]
    analysis = await analyze_query_media(query)

    # Case 0: No files found
    if analysis.get("total_files", 0) == 0:
        return f"⚠️ <b>No files found matching '{query}'.</b>", InlineKeyboardMarkup([])

    # Case 1: Only Series exist
    if analysis["has_series"] and not analysis["has_movies"]:
        update_nav_session(sid, media_type="series")
        return await build_season_picker_view(sid, analysis)

    # Case 2: Only Movies exist
    if analysis["has_movies"] and not analysis["has_series"]:
        update_nav_session(sid, media_type="movie")
        # If only 1 file exists, OR if there are no sub-filters (languages/qualities) to choose from,
        # jump directly to filtered results so user gets instant 1-click download buttons!
        has_subfilters = bool(analysis.get("movie_languages") or analysis.get("movie_qualities"))
        if analysis.get("movie_count", 0) <= 1 or not has_subfilters:
            return await build_filtered_results_view(sid, page=1)
        return await build_movie_filter_view(sid, analysis)

    # Case 3: Both Movies and Series exist (like Mirzapur)
    text = (
        f"🎯 <b>FILTER NAVIGATOR</b>\n"
        f"────────────────────────\n"
        f"🏷️ <b>Query:</b> <code>{query}</code>\n"
        f"📦 <b>Total Files:</b> <code>{analysis['total_files']} Files</code>\n"
        f"────────────────────────\n\n"
        f"🎬 <b>Please select whether you want a Movie or a Series:</b>"
    )

    keyboard = [
        [
            InlineKeyboardButton("🎬 Movies", callback_data=f"snav:type:{sid}:m"),
            InlineKeyboardButton("📺 Series", callback_data=f"snav:type:{sid}:s")
        ],
        [
            InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


async def build_season_picker_view(sid: str, analysis: dict = None) -> tuple[str, InlineKeyboardMarkup]:
    """Step 2 (Series): Season selection buttons with Single Season Auto-Skip and Episode tags."""
    sess = get_nav_session(sid)
    if not sess:
        return "❌ Session Expired.", InlineKeyboardMarkup([])

    query = sess["query"]
    if not analysis:
        analysis = await analyze_query_media(query)

    seasons = analysis["seasons"]
    if not seasons:
        return (
            f"⚠️ No seasons found for <b>{query}</b>.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")]])
        )

    # 🌟 SINGLE SEASON AUTO-SKIP!
    # If only 1 season exists in database (e.g. Hostel S01 or Matargashti S01), skip season question!
    if len(seasons) == 1:
        only_s = list(seasons.keys())[0]
        update_nav_session(sid, media_type="series", season=only_s)
        return await build_season_options_view(sid, only_s)

    text = (
        f"📺 <b>SERIES NAVIGATOR</b>\n"
        f"────────────────────────\n"
        f"🏷️ <b>Title:</b> <code>{query}</code>\n"
        f"📁 <b>Available Seasons:</b> <code>{len(seasons)} Seasons</code>\n"
        f"────────────────────────\n\n"
        f"📺 <b>Which season are you looking for?</b>\n"
        f"👇 <i>Select a season below:</i>"
    )

    keyboard = []
    season_keys = list(seasons.keys())

    # 2 buttons per row with informative episode/pack tag!
    row = []
    for s_num in season_keys:
        s_data = seasons[s_num]
        eps_count = len(s_data.get("episodes", []))
        if eps_count > 0:
            btn_text = f"📁 Season {s_num} ({eps_count} Eps)"
        elif s_data.get("has_complete"):
            btn_text = f"📁 Season {s_num} (Full Pack)"
        else:
            btn_text = f"📁 Season {s_num} ({s_data.get('file_count', 1)} Files)"

        row.append(InlineKeyboardButton(btn_text, callback_data=f"snav:seas:{sid}:{s_num}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Back button
    if analysis["has_movies"]:
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"snav:init:{sid}")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")])

    return text, InlineKeyboardMarkup(keyboard)


async def build_season_options_view(sid: str, season: int) -> tuple[str, InlineKeyboardMarkup]:
    """Step 3 (Series): Complete Season vs Episode Wise selection (with smart skip if only single pack exists)."""
    sess = get_nav_session(sid)
    if not sess:
        return "❌ Session Expired.", InlineKeyboardMarkup([])

    query = sess["query"]
    analysis = await analyze_query_media(query)
    s_info = analysis["seasons"].get(season)

    if not s_info:
        return await build_season_picker_view(sid, analysis)

    # Smart Auto-Skip:
    # If Season has ONLY complete/merged single files (like Matargashti S01 from user screenshot):
    # Don't ask "How would you like your files?", directly jump to Season 1 files!
    if s_info["has_complete"] and not s_info["has_episodes"]:
        update_nav_session(sid, season=season, mode="pack", page=1)
        return await build_filtered_results_view(sid)

    # If Season has ONLY episode files (no packs):
    # Directly jump to Episode Grid!
    if s_info["has_episodes"] and not s_info["has_complete"]:
        update_nav_session(sid, season=season, mode="episode")
        return await build_episode_grid_view(sid, season, page=1, analysis=analysis)

    # If Season has BOTH (e.g. Mirzapur with packs and episodes):
    text = (
        f"📁 <b>SEASON {season} SELECTED</b>\n"
        f"────────────────────────\n"
        f"🏷️ <b>Title:</b> <code>{query}</code>\n"
        f"📦 <b>Files Available:</b> <code>{s_info['file_count']} Files</code>\n"
        f"────────────────────────\n\n"
        f"✅ <b>You selected Season {season}! How would you like your files?</b>"
    )

    # Back button logic: if only 1 season existed, back should go to Results or Root
    if len(analysis["seasons"]) == 1:
        if analysis["has_movies"]:
            back_btn = InlineKeyboardButton("⬅️ Back", callback_data=f"snav:init:{sid}")
        else:
            back_btn = InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")
    else:
        back_btn = InlineKeyboardButton("⬅️ Back to Seasons", callback_data=f"snav:type:{sid}:s")

    keyboard = [
        [
            InlineKeyboardButton("📦 Get Complete Season File", callback_data=f"snav:smode:{sid}:{season}:pack")
        ],
        [
            InlineKeyboardButton("🍿 Episode Wise Files", callback_data=f"snav:smode:{sid}:{season}:ep")
        ],
        [
            back_btn
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


async def build_episode_grid_view(sid: str, season: int, page: int = 1, analysis: dict = None) -> tuple[str, InlineKeyboardMarkup]:
    """Step 4 (Series): Episode Grid (3-column layout) with auto-pagination for large episode counts."""
    sess = get_nav_session(sid)
    if not sess:
        return "❌ Session Expired.", InlineKeyboardMarkup([])

    query = sess["query"]
    if not analysis:
        analysis = await analyze_query_media(query)

    s_info = analysis["seasons"].get(season, {})
    episodes = s_info.get("episodes", [])

    if not episodes:
        update_nav_session(sid, season=season, mode="pack", page=1)
        return await build_filtered_results_view(sid)

    total_eps = len(episodes)
    per_page = 12
    total_pages = math.ceil(total_eps / per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_eps = episodes[start_idx:end_idx]

    text = (
        f"🎬 <b>EPISODE SELECTOR</b>\n"
        f"────────────────────────\n"
        f"🏷️ <b>Series:</b> <code>{query}</code>\n"
        f"📁 <b>Season:</b> <code>Season {season} ({total_eps} Episodes)</code>\n"
        f"────────────────────────\n\n"
        f"🎬 <b>Which episode of Season {season} do you want to watch?</b>\n"
        f"👇 <i>Choose an episode to get all available qualities:</i>"
    )

    keyboard = []
    # 3-column episode grid
    row = []
    for ep in page_eps:
        row.append(InlineKeyboardButton(f"Episode {ep}", callback_data=f"snav:ep:{sid}:{season}:{ep}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Pagination navigation if > 12 episodes
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"snav:epgrid:{sid}:{season}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page} / {total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"snav:epgrid:{sid}:{season}:{page + 1}"))
        keyboard.append(nav_row)

    # Back buttons
    if s_info.get("has_complete"):
        keyboard.append([InlineKeyboardButton("⬅️ Back to Season Options", callback_data=f"snav:seas:{sid}:{season}")])
    elif len(analysis["seasons"]) == 1:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Seasons", callback_data=f"snav:type:{sid}:s")])

    return text, InlineKeyboardMarkup(keyboard)


async def build_movie_filter_view(sid: str, analysis: dict = None) -> tuple[str, InlineKeyboardMarkup]:
    """Step 2 (Movie): Clean Language & Quality filters without useless release year."""
    sess = get_nav_session(sid)
    if not sess:
        return "❌ Session Expired.", InlineKeyboardMarkup([])

    query = sess["query"]
    if not analysis:
        analysis = await analyze_query_media(query)

    curr_lang = sess.get("language")
    curr_qual = sess.get("quality")

    text = (
        f"🎬 <b>MOVIE FILTERS</b>\n"
        f"────────────────────────\n"
        f"🏷️ <b>Title:</b> <code>{query}</code>\n"
        f"📦 <b>Available Prints:</b> <code>{analysis['movie_count']} Files</code>\n"
        f"────────────────────────\n\n"
        f"🗣️ <b>Select your preferred Language or Quality:</b>\n"
        f"<i>(Tap a filter below to refine results)</i>"
    )

    keyboard = []

    # Languages Row
    langs = analysis.get("movie_languages", [])
    if langs:
        lang_row = []
        for l in langs[:4]:
            label = LANGUAGE_DISPLAY.get(l, l.title())
            if curr_lang == l:
                label = f"✅ {label}"
            lang_row.append(InlineKeyboardButton(label, callback_data=f"snav:mlang:{sid}:{l}"))
        keyboard.append(lang_row)

    # Qualities Row
    quals = analysis.get("movie_qualities", [])
    if quals:
        qual_row = []
        for q in quals:
            label = q
            if curr_qual == q:
                label = f"✅ {label}"
            qual_row.append(InlineKeyboardButton(label, callback_data=f"snav:mqual:{sid}:{q}"))
        keyboard.append(qual_row)

    # View results button
    keyboard.append([
        InlineKeyboardButton("🚀 Show Filtered Results", callback_data=f"snav:mresults:{sid}")
    ])

    # Back button
    if analysis["has_series"]:
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"snav:init:{sid}")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}")])

    return text, InlineKeyboardMarkup(keyboard)


async def build_filtered_results_view(sid: str, page: int = 1) -> tuple[str, InlineKeyboardMarkup]:
    """Render the final filtered files list in clean hyperlinked text format with quick number buttons."""
    import html
    sess = get_nav_session(sid)
    if not sess:
        return "❌ Session Expired.", InlineKeyboardMarkup([])

    query = sess["query"]
    analysis = await analyze_query_media(query)

    media_type = sess.get("media_type")
    season = sess.get("season")
    mode = sess.get("mode")
    episode = sess.get("episode")
    language = sess.get("language")
    quality = sess.get("quality")
    bot_username = sess.get("bot_username", "bot")
    is_pm = sess.get("is_pm", True)

    per_page = 10
    offset = (page - 1) * per_page

    files, total_files = await fetch_filtered_files(
        query=query,
        media_type=media_type,
        season=season,
        mode=mode,
        episode=episode,
        language=language,
        quality=quality,
        offset=offset,
        limit=per_page
    )

    total_pages = math.ceil(total_files / per_page) if total_files > 0 else 1
    page = max(1, min(page, total_pages))

    # Header title banner
    filter_tag = ""
    if media_type == "series":
        if mode == "pack":
            filter_tag = f"Season {season} [Complete Pack]"
        elif episode is not None:
            filter_tag = f"Season {season} Episode {episode}"
        else:
            filter_tag = f"Season {season}"
    elif media_type == "movie":
        tags = []
        if language:
            tags.append(language.title())
        if quality:
            tags.append(quality)
        filter_tag = " - ".join(tags) if tags else "Movies"

    f_label = "File" if total_files == 1 else "Files"
    text_lines = [
        f"🎯 <b>FILTERED RESULTS</b>",
        f"────────────────────────",
        f"🏷️ <b>Title:</b> <code>{html.escape(query)}</code>",
        f"🔍 <b>Active Filter:</b> <code>{filter_tag or 'All Files'}</code>",
        f"📦 <b>Files Found:</b> <code>{total_files} {f_label}</code>",
        f"────────────────────────",
        "",
        f"🧾 <u><b>Your Requested Files Are Here</b></u> 👇",
        ""
    ]

    for idx, item in enumerate(files, start=1):
        f_id = item.get("file_unique_id")
        raw_name = item.get("file_name", "File")
        clean_name = html.escape(raw_name.replace("_", " "))
        size_str = get_readable_size(item.get("file_size", 0))
        link = f"https://t.me/{bot_username}?start=file_{f_id}"

        # Exact 2nd photo style: size is inside the clickable link right with title
        text_lines.append(f"<b>{idx}.</b> <a href=\"{link}\">[{size_str}] {clean_name}</a>\n")

    user_id = sess.get("user_id", 0)
    try:
        from database.users import is_premium
        from database.ads import get_active_sponsor_ad
        if not await is_premium(user_id):
            ad = await get_active_sponsor_ad()
            if ad and ad.get("text") and ad.get("url"):
                ad_title = html.escape(ad["text"])
                ad_link = html.escape(ad["url"])
                text_lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
                text_lines.append(f"📢 <b>Sponsor:</b> <a href=\"{ad_link}\">{ad_title}</a>\n")
    except Exception as e:
        logger.debug(f"Could not load sponsor ad in smart nav: {e}")

    text = "\n".join(text_lines).strip()

    keyboard = []

    # Quick number download buttons for 1-click delivery
    number_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    if files:
        num_row = []
        for idx, item in enumerate(files):
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

    # Filter status bar with Clear Filter button
    filter_bar = [
        InlineKeyboardButton(f"🎯 Filter: {filter_tag[:20]}", callback_data=f"snav:init:{sid}"),
        InlineKeyboardButton("🔄 Clear", callback_data=f"snav:clear:{sid}")
    ]
    keyboard.append(filter_bar)

    # Pagination navigation
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"snav:rpage:{sid}:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page} / {total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"snav:rpage:{sid}:{page + 1}"))
        keyboard.append(nav_row)

    # Back Navigation
    back_row = []
    if media_type == "series":
        if mode == "episode" and episode is not None:
            back_row.append(InlineKeyboardButton("⬅️ Back to Episodes", callback_data=f"snav:smode:{sid}:{season}:ep"))
            back_row.append(InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}"))
        elif len(analysis.get("seasons", {})) > 1:
            back_row.append(InlineKeyboardButton("⬅️ Back to Seasons", callback_data=f"snav:type:{sid}:s"))
            back_row.append(InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}"))
        else:
            back_row.append(InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}"))
    elif media_type == "movie":
        back_row.append(InlineKeyboardButton("⬅️ Back to Filters", callback_data=f"snav:type:{sid}:m"))
        back_row.append(InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}"))
    else:
        back_row.append(InlineKeyboardButton("⬅️ Back to Results", callback_data=f"snav:back_res:{sid}"))

    keyboard.append(back_row)

    return text, InlineKeyboardMarkup(keyboard)
