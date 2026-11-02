import re
import html
import urllib.parse
import aiohttp
import logging
from config import Config

logger = logging.getLogger(__name__)

OFFICIAL_TMDB_API = "https://api.themoviedb.org/3"
TMDB_WORKER = "https://tmdbapi.the-zake.workers.dev/3"
TMDB_IMG = "https://image.tmdb.org/t/p/original"
ANILIST_URL = "https://graphql.anilist.co"

TMDB_GENRES = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance", 878: "Sci-Fi",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
    10759: "Action & Adventure", 10762: "Kids", 10763: "News", 10764: "Reality",
    10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
}

ANILIST_QUERY = """
query ($search: String) {
    Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
        id
        title { romaji english native }
        bannerImage
        coverImage { extraLarge large }
        averageScore
        genres
        episodes
        duration
        description(asHtml: false)
        startDate { year }
        studios(isMain: true) { nodes { name } }
    }
}
"""


def extract_title_from_url(url: str) -> tuple[str, str]:
    """Parse OTT or database URL and extract candidate query title and detected platform."""
    url = url.strip()
    platform = "Web"
    query = ""

    if "netflix.com" in url:
        platform = "Netflix"
        m = re.search(r"netflix\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?title/(\d+)", url)
        slug_match = re.search(r"netflix\.com/.*?[?&]title=([^&]+)", url)
        if slug_match:
            query = urllib.parse.unquote(slug_match.group(1)).replace("-", " ")
        elif m:
            query = f"netflix {m.group(1)}"

    elif "crunchyroll.com" in url:
        platform = "Crunchyroll"
        m = re.search(r"crunchyroll\.com/(?:series|watch)/([a-zA-Z0-9]+)/?([a-zA-Z0-9-]+)?", url)
        if m and m.group(2):
            query = m.group(2).replace("-", " ")

    elif "primevideo.com" in url or "amazon." in url:
        platform = "Prime Video"
        m = re.search(r"(?:detail|gp/video/detail)/[^/]+/([a-zA-Z0-9-]+)", url)
        if m:
            query = m.group(1).replace("-", " ")

    elif "hotstar.com" in url or "disneyplus" in url:
        platform = "Disney+ Hotstar"
        m = re.search(r"hotstar\.com/(?:[a-z]{2}/)?(?:movies|shows)/([a-zA-Z0-9-]+)/", url)
        if m:
            query = m.group(1).replace("-", " ")

    elif "zee5.com" in url:
        platform = "Zee5"
        m = re.search(r"zee5\.com/(?:movies|tv-shows)/details/([^/]+)/", url)
        if m:
            query = m.group(1).replace("-", " ")

    elif "sonyliv.com" in url:
        platform = "SonyLIV"
        m = re.search(r"sonyliv\.com/(?:movies|shows)/([a-zA-Z0-9-]+)", url)
        if m:
            query = m.group(1).replace("-", " ")

    elif "imdb.com" in url:
        platform = "IMDb"
        m = re.search(r"imdb\.com/title/(tt\d+)", url)
        if m:
            query = m.group(1)

    elif "themoviedb.org" in url:
        platform = "TMDB"
        m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)-?([a-zA-Z0-9-]*)", url)
        if m:
            query = m.group(3).replace("-", " ") if m.group(3) else m.group(2)

    return query, platform


async def fetch_anilist_data(title: str) -> dict | None:
    """Query AniList GraphQL API for anime details, banners, and character art."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
            async with session.post(ANILIST_URL, json={"query": ANILIST_QUERY, "variables": {"search": title}}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media = data.get("data", {}).get("Media")
                    if media:
                        t = media.get("title", {})
                        eng = t.get("english") or t.get("romaji") or title
                        rom = t.get("romaji") or eng
                        native = t.get("native") or rom
                        desc = media.get("description") or "No synopsis available."
                        desc = re.sub(r"<[^>]+>", "", desc).strip()

                        cover = media.get("coverImage", {}).get("extraLarge") or media.get("coverImage", {}).get("large")
                        banner = media.get("bannerImage") or cover

                        score = media.get("averageScore") or 82
                        episodes = media.get("episodes")
                        ep_text = f"{episodes} Episodes" if episodes else "TV Series"
                        year = media.get("startDate", {}).get("year") or 2024

                        studios_nodes = media.get("studios", {}).get("nodes", [])
                        studio = studios_nodes[0].get("name") if studios_nodes else "Anime Studio"

                        return {
                            "title": {"english": eng, "romaji": rom, "native": native},
                            "display_title": eng,
                            "year": year,
                            "rating": round(score / 10.0, 1) if score and score > 0 else None,
                            "match_pct": score,
                            "maturity": "16+",
                            "genres": media.get("genres", ["Animation", "Action"]),
                            "episodes": ep_text,
                            "duration": ep_text,
                            "description": desc,
                            "bannerImage": banner,
                            "coverImage": {"extraLarge": cover},
                            "images": {
                                "banner_backdrop": banner,
                                "landscape_poster": banner,
                                "portrait_poster": cover,
                                "all_posters": [cover] if cover else [],
                                "all_backdrops": [banner] if banner else []
                            },
                            "studio": studio,
                            "platform": "Anime",
                            "media_type": "ANIME"
                        }
    except Exception as e:
        logger.debug(f"AniList lookup failed for '{title}': {e}")

    return None


async def fetch_tmdb_images(media_type: str, tmdb_id: int, api_key: str = "", read_token: str = "") -> dict:
    """Fetch official transparent logos, textless posters, and backdrops from TMDB."""
    candidates = []
    # Priority 1: High-Speed Worker Proxy with official API Key (Fast & immune to ISP throttling)
    if api_key:
        worker_url = f"{TMDB_WORKER}/{media_type}/{tmdb_id}/images?api_key={api_key}&include_image_language=en,hi,null"
        candidates.append((worker_url, {"accept": "application/json"}))
    elif read_token:
        worker_url = f"{TMDB_WORKER}/{media_type}/{tmdb_id}/images?include_image_language=en,hi,null"
        candidates.append((worker_url, {"Authorization": f"Bearer {read_token}", "accept": "application/json"}))

    # Priority 2: Official TMDB API endpoints
    if read_token:
        url = f"{OFFICIAL_TMDB_API}/{media_type}/{tmdb_id}/images?include_image_language=en,hi,null"
        candidates.append((url, {"Authorization": f"Bearer {read_token}", "accept": "application/json"}))
    if api_key:
        url = f"{OFFICIAL_TMDB_API}/{media_type}/{tmdb_id}/images?api_key={api_key}&include_image_language=en,hi,null"
        candidates.append((url, {"accept": "application/json"}))

    for endpoint, headers in candidates:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
                async with session.get(endpoint, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logos = data.get("logos", [])
                        posters = data.get("posters", [])
                        backdrops = data.get("backdrops", [])

                        # 1. Best official transparent PNG logo (priority: en -> null -> first)
                        best_logo = None
                        if logos:
                            best_logo = next((l for l in logos if l.get("iso_639_1") == "en"), logos[0])

                        # 2. Collect ALL available textless and rated high-res posters (up to 30)
                        textless = [p for p in posters if p.get("iso_639_1") is None]
                        best_poster = textless[0] if textless else (posters[0] if posters else None)

                        textless_urls = [f"{TMDB_IMG}{p['file_path']}" for p in textless if p.get("file_path")]
                        other_posters = [p for p in posters if p.get("iso_639_1") is not None]
                        other_posters.sort(key=lambda x: (x.get("vote_count", 0), x.get("vote_average", 0)), reverse=True)
                        other_urls = [f"{TMDB_IMG}{p['file_path']}" for p in other_posters if p.get("file_path") and f"{TMDB_IMG}{p['file_path']}" not in textless_urls]
                        all_posters = (textless_urls + other_urls)[:30]

                        # 3. Best backdrop and all backdrops list (up to 30)
                        best_backdrop = backdrops[0] if backdrops else None
                        backdrops.sort(key=lambda x: (x.get("vote_count", 0), x.get("vote_average", 0)), reverse=True)
                        all_backdrops = [f"{TMDB_IMG}{b['file_path']}" for b in backdrops if b.get("file_path")][:30]

                        return {
                            "logo_url": f"{TMDB_IMG}{best_logo['file_path']}" if best_logo else None,
                            "textless_poster_url": f"{TMDB_IMG}{best_poster['file_path']}" if best_poster else None,
                            "backdrop_url": f"{TMDB_IMG}{best_backdrop['file_path']}" if best_backdrop else None,
                            "all_posters": all_posters,
                            "all_backdrops": all_backdrops
                        }
        except Exception as e:
            logger.debug(f"TMDB images fetch failed on {endpoint}: {e}")
            continue

    return {}


async def fetch_tmdb_data(title: str) -> dict | None:
    """Query TMDB API using official Read Access Token / API Key or fallback worker."""
    is_imdb = bool(re.match(r"^tt\d+$", title.strip()))
    encoded_q = urllib.parse.quote(title)

    try:
        from database.poster import get_tmdb_credentials
        db_creds = await get_tmdb_credentials()
        read_token = (Config.TMDB_READ_ACCESS_TOKEN or db_creds.get("token", "")).strip()
        api_key = (Config.TMDB_API_KEY or db_creds.get("api_key", "")).strip()
    except Exception:
        read_token = Config.TMDB_READ_ACCESS_TOKEN.strip()
        api_key = Config.TMDB_API_KEY.strip()

    # Prepare endpoints: 1. Public Worker Proxy with key (fastest & reliable), 2. Official API
    candidates = []

    # Priority 1: High-Speed Worker Proxy with API Key
    if api_key:
        w_url = f"{TMDB_WORKER}/find/{title}?api_key={api_key}&external_source=imdb_id" if is_imdb else f"{TMDB_WORKER}/search/multi?api_key={api_key}&query={encoded_q}"
        candidates.append((w_url, {"accept": "application/json"}))
    elif read_token:
        w_url = f"{TMDB_WORKER}/find/{title}?external_source=imdb_id" if is_imdb else f"{TMDB_WORKER}/search/multi?query={encoded_q}"
        candidates.append((w_url, {"Authorization": f"Bearer {read_token}", "accept": "application/json"}))

    # Priority 2: Official TMDB API
    if read_token:
        url = f"{OFFICIAL_TMDB_API}/find/{title}?external_source=imdb_id" if is_imdb else f"{OFFICIAL_TMDB_API}/search/multi?query={encoded_q}"
        headers = {
            "Authorization": f"Bearer {read_token}",
            "accept": "application/json"
        }
        candidates.append((url, headers))

    if api_key:
        url = f"{OFFICIAL_TMDB_API}/find/{title}?api_key={api_key}&external_source=imdb_id" if is_imdb else f"{OFFICIAL_TMDB_API}/search/multi?api_key={api_key}&query={encoded_q}"
        candidates.append((url, {"accept": "application/json"}))

    for endpoint, headers in candidates:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(endpoint, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = []
                        if is_imdb:
                            results = data.get("movie_results", []) or data.get("tv_results", [])
                        else:
                            results = data.get("results", [])

                        if results:
                            best = next((r for r in results if r.get("media_type") in ("movie", "tv") and r.get("backdrop_path")), results[0])

                            name = best.get("title") or best.get("name") or title
                            orig_name = best.get("original_title") or best.get("original_name") or name
                            rel_date = best.get("release_date") or best.get("first_air_date") or ""
                            year = rel_date.split("-")[0] if rel_date else "2024"

                            backdrop_path = best.get("backdrop_path")
                            poster_path = best.get("poster_path")
                            backdrop = f"{TMDB_IMG}{backdrop_path}" if backdrop_path else None
                            poster = f"{TMDB_IMG}{poster_path}" if poster_path else None

                            vote = best.get("vote_average", 0)
                            rating_val = round(vote, 1) if vote and vote > 0 else None
                            match_pct = int(min(99, max(60, vote * 10 + 5))) if rating_val else None

                            genre_ids = best.get("genre_ids", [])
                            genres = [TMDB_GENRES[gid] for gid in genre_ids if gid in TMDB_GENRES] or ["Action", "Drama"]

                            overview = best.get("overview") or ""
                            media_type = "MOVIE" if best.get("media_type") == "movie" else "SERIES"
                            ep_text = "Feature Film" if media_type == "MOVIE" else "TV Series"

                            # Query TMDB official transparent logo and textless artwork
                            m_id = best.get("id")
                            raw_type = best.get("media_type") or ("movie" if "title" in best else "tv")
                            extra = {}
                            if m_id:
                                extra = await fetch_tmdb_images(raw_type, m_id, api_key, read_token)

                            logo_url = extra.get("logo_url")
                            textless_poster = extra.get("textless_poster_url")
                            clean_backdrop = extra.get("backdrop_url") or backdrop
                            all_posters = extra.get("all_posters") or ([poster] if poster else [])
                            all_backdrops = extra.get("all_backdrops") or ([backdrop] if backdrop else [])

                            return {
                                "title": {"english": name, "romaji": orig_name, "native": orig_name},
                                "display_title": name,
                                "year": year,
                                "rating": rating_val,
                                "match_pct": match_pct,
                                "maturity": "18+" if any(g in ("Crime", "Horror") for g in genres) else "16+",
                                "genres": genres,
                                "episodes": ep_text,
                                "duration": ep_text,
                                "description": overview,
                                "bannerImage": clean_backdrop or backdrop or poster,
                                "coverImage": {"extraLarge": textless_poster or poster or backdrop},
                                "images": {
                                    "logo": logo_url,
                                    "textless_poster": textless_poster or poster,
                                    "banner_backdrop": clean_backdrop or backdrop or poster,
                                    "landscape_poster": clean_backdrop or backdrop or poster,
                                    "portrait_poster": textless_poster or poster or backdrop,
                                    "all_posters": all_posters,
                                    "all_backdrops": all_backdrops
                                },
                                "platform": "Cinema",
                                "media_type": media_type
                            }
        except Exception as e:
            logger.debug(f"Candidate endpoint {endpoint} failed: {e}")
            continue

    return None


async def fetch_imdb_fallback(title: str) -> dict | None:
    """Fallback to IMDb suggestion API when other sources are unavailable."""
    try:
        clean_q = re.sub(r"[^\w\s]", "", title).strip().lower()
        if not clean_q:
            return None
        url = f"https://v2.sg.media-imdb.com/suggestion/{clean_q[0]}/{clean_q.replace(' ', '_')}.json"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("d", [])
                    if results:
                        best = results[0]
                        name = best.get("l", title.title())
                        year = best.get("y", 2024)
                        poster = best.get("i", {}).get("imageUrl")
                        cast = best.get("s", "Actors")

                        return {
                            "title": {"english": name, "romaji": name, "native": name},
                            "display_title": name,
                            "year": year,
                            "rating": 7.8,
                            "match_pct": 88,
                            "maturity": "16+",
                            "genres": [best.get("q", "Movie").title()],
                            "episodes": "HD Release",
                            "duration": "HD Release",
                            "description": f"Starring: {cast}. A prominent cinema release.",
                            "bannerImage": poster,
                            "coverImage": {"extraLarge": poster},
                            "images": {
                                "banner_backdrop": poster,
                                "landscape_poster": poster,
                                "portrait_poster": poster,
                                "all_posters": [poster] if poster else [],
                                "all_backdrops": [poster] if poster else []
                            },
                            "platform": "IMDb",
                            "media_type": "MOVIE"
                        }
    except Exception as e:
        logger.debug(f"IMDb fallback error for '{title}': {e}")

    return None


async def resolve_media_metadata(user_input: str) -> tuple[dict | None, str]:
    """Unified resolver: takes raw text or URL, queries appropriate providers, and returns standard media dict."""
    user_input = user_input.strip()
    detected_platform = None

    # 1. Check if user provided an OTT or direct database URL
    if user_input.startswith(("http://", "https://")):
        slug_title, platform = extract_title_from_url(user_input)
        detected_platform = platform
        if slug_title:
            user_input = slug_title

    # 2. If Crunchyroll or known Anime keyword, prioritize AniList
    is_anime_hint = detected_platform == "Crunchyroll" or any(k in user_input.lower() for k in ["anime", "season", "naruto", "titan", "leveling", "jujutsu", "piece"])

    data = None
    if is_anime_hint:
        data = await fetch_anilist_data(user_input)
        if not data:
            data = await fetch_tmdb_data(user_input)
    else:
        # Standard movie/series: Prioritize TMDB for 16:9 backdrops + posters
        data = await fetch_tmdb_data(user_input)
        if not data:
            data = await fetch_anilist_data(user_input)

    # 3. Final Fallback to IMDb
    if not data:
        data = await fetch_imdb_fallback(user_input)

    if data and detected_platform:
        data["platform"] = detected_platform

    return data, detected_platform or (data.get("platform", "Cinema") if data else "Unknown")
