import asyncio
import logging
import re
import urllib.parse
from typing import Optional, Dict, Any, List
import httpx

from config import Config

logger = logging.getLogger("autofilter.online_stream")

# In-memory TTL Cache for Cinemeta Search Results
# Key: clean_query -> (timestamp, data_dict)
_CINEMETA_CACHE: Dict[str, tuple[float, Optional[Dict[str, Any]]]] = {}
_CACHE_TTL = 3600.0  # 1 hour


def clean_search_title(raw_title: str) -> str:
    """Clean video file noise, brackets, resolutions, and quality tags for pure title search."""
    text = re.sub(r'\[.*?\]|\(.*?\)', ' ', raw_title)
    text = re.sub(r'\b(1080p|720p|480p|2160p|4k|uhd|hd|sd|hevc|x264|x265|10bit|web-dl|webrip|bluray|brrip|dvdrip|hdtc|camrip|aac|mp3|mkv|mp4|avi)\b', ' ', text, flags=re.I)
    text = re.sub(r'[._\-\+]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text or raw_title.strip()


def get_online_servers(
    imdb_id: str,
    tmdb_id: Optional[int] = None,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1
) -> Dict[str, Dict[str, str]]:
    """Generate embed streaming server URLs for all top reliable web players."""
    effective_id = imdb_id or (str(tmdb_id) if tmdb_id else "")
    if not effective_id:
        return {}

    is_series = (media_type == "series")
    # For TV series / Anime, pass TMDB numeric ID when available so providers never confuse anime with live-action
    series_id = str(tmdb_id) if (is_series and tmdb_id) else effective_id
    id_type = "imdb" if (imdb_id and imdb_id.startswith("tt")) else "tmdb"

    return {
        "vidlink": {
            "name": "Server 1: VidLink Pro (Fast / HD)",
            "icon": "⚡",
            "url": f"https://vidlink.pro/tv/{series_id}/{season}/{episode}?autoplay=true" if is_series else f"https://vidlink.pro/movie/{effective_id}?autoplay=true"
        },
        "videm": {
            "name": "Server 2: VidEm (Multi-Source)",
            "icon": "🎬",
            "url": f"https://videm.xyz/embed/tv/{effective_id}/{season}/{episode}?autoplay=true" if is_series else f"https://videm.xyz/embed/movie/{effective_id}?autoplay=true"
        },
        "vidsrc": {
            "name": "Server 3: VidSrc.pm (Dedicated)",
            "icon": "🌐",
            "url": f"https://vidsrc.pm/embed/tv/{effective_id}/{season}/{episode}?autoplay=1" if is_series else f"https://vidsrc.pm/embed/movie/{effective_id}?autoplay=1"
        },
        "smashystream": {
            "name": "Server 4: SmashyStream",
            "icon": "🚀",
            "url": f"https://player.smashystream.com/tv/{effective_id}?s={season}&e={episode}" if is_series else f"https://player.smashystream.com/movie/{effective_id}"
        },
        "twoembed": {
            "name": "Server 5: 2Embed Player",
            "icon": "🍿",
            "url": f"https://www.2embed.cc/embedtv/{effective_id}&s={season}&e={episode}" if is_series else f"https://www.2embed.cc/embed/{effective_id}"
        },
        "autoembed": {
            "name": "Server 6: AutoEmbed",
            "icon": "🔥",
            "url": f"https://autoembed.co/tv/{id_type}/{effective_id}/{season}/{episode}" if is_series else f"https://autoembed.co/movie/{id_type}/{effective_id}"
        },
        "vidsrc_su": {
            "name": "Server 7: VidSrc.su (Mirror)",
            "icon": "🛰️",
            "url": f"https://vidsrc.su/embed/tv/{effective_id}/{season}/{episode}" if is_series else f"https://vidsrc.su/embed/movie/{effective_id}"
        },
        "vidy": {
            "name": "Server 8: Vidy Stream",
            "icon": "📽️",
            "url": f"https://www.vidy.st/tv/{effective_id}/{season}/{episode}?color=DC2626&nextEpisode=true&episodeSelector=true" if is_series else f"https://www.vidy.st/movie/{effective_id}?color=DC2626"
        },
        "vidzee": {
            "name": "Server 9: VidZee Player",
            "icon": "⚡",
            "url": f"https://player.vidzee.wtf/embed/tv/{effective_id}/{season}/{episode}" if is_series else f"https://player.vidzee.wtf/embed/movie/{effective_id}"
        },
        "nontongo": {
            "name": "Server 10: NontonGo Multi-Stream",
            "icon": "💎",
            "url": f"https://www.NontonGo.win/embed/tv/{series_id}/{season}/{episode}" if is_series else f"https://www.NontonGo.win/embed/movie/{effective_id}"
        },
        "embedsu": {
            "name": "Server 11: SuperEmbed VIP",
            "icon": "✨",
            "url": f"https://embed.su/embed/tv/{effective_id}/{season}/{episode}" if is_series else f"https://embed.su/embed/movie/{effective_id}"
        }
    }


async def search_online_meta(query: str) -> Optional[Dict[str, Any]]:
    """Search Cinemeta API for movies and TV series by query.
    Returns parsed title, IMDb ID, poster, overview, rating, and stream servers.
    """
    clean_q = clean_search_title(query)
    if not clean_q or len(clean_q) < 2:
        return None

    # Parse season & episode if specified in query
    season_num = 1
    episode_num = 1
    s_match = re.search(r'\b(?:s|season)\s*0?(\d+)\b', query, re.I)
    if s_match:
        season_num = max(1, int(s_match.group(1)))
    e_match = re.search(r'\b(?:e|ep|episode)\s*0?(\d+)\b', query, re.I)
    if e_match:
        episode_num = max(1, int(e_match.group(1)))

    is_probable_series = bool(s_match or e_match or re.search(r'\b(s\d+|season|ep|episode|s\d+e\d+)\b', query, re.I))

    # Strip season / episode tokens to get pure search title for Cinemeta
    search_title = re.sub(r'\b(?:s|season)\s*0?\d+\b', ' ', clean_q, flags=re.I)
    search_title = re.sub(r'\b(?:e|ep|episode)\s*0?\d+\b', ' ', search_title, flags=re.I)
    search_title = re.sub(r'\s+', ' ', search_title).strip() or clean_q

    # Handle trailing number e.g. "one piece 2" -> search "one piece", season=2
    if not s_match:
        trail_m = re.search(r'^(.*?)\s+([2-9]|\d{2})$', search_title)
        if trail_m:
            candidate_base = trail_m.group(1).strip()
            if len(candidate_base) >= 3:
                search_title = candidate_base
                season_num = int(trail_m.group(2))
                is_probable_series = True

    cache_key = f"{search_title.lower()}_s{season_num}_e{episode_num}"
    now = asyncio.get_event_loop().time()
    if cache_key in _CINEMETA_CACHE:
        cached_time, cached_val = _CINEMETA_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_val

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    movie_url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(search_title)}.json"
    series_url = f"https://v3-cinemeta.strem.io/catalog/series/top/search={urllib.parse.quote(search_title)}.json"

    try:
        async with httpx.AsyncClient(timeout=4.0, headers=headers) as client:
            movie_task = client.get(movie_url)
            series_task = client.get(series_url)
            m_resp, s_resp = await asyncio.gather(movie_task, series_task, return_exceptions=True)

            candidates: List[Dict[str, Any]] = []
            seen_ids = set()

            raw_series = []
            raw_movies = []
            if not isinstance(s_resp, Exception) and getattr(s_resp, "status_code", 0) == 200:
                raw_series = s_resp.json().get("metas", [])
            if not isinstance(m_resp, Exception) and getattr(m_resp, "status_code", 0) == 200:
                raw_movies = m_resp.json().get("metas", [])

            all_raw = raw_series + raw_movies if is_probable_series else raw_movies + raw_series
            for item in all_raw:
                cid = item.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append(item)

            if not candidates:
                _CINEMETA_CACHE[cache_key] = (now, None)
                return None

            # Intelligent Candidate Scoring & Ranking
            from rapidfuzz import fuzz
            clean_q_lower = search_title.strip().lower()

            def score_candidate(c: Dict[str, Any]) -> float:
                c_name = (c.get("name") or "").strip().lower()
                c_type = c.get("type", "movie")
                
                # Base string similarities
                sim_ratio = fuzz.ratio(clean_q_lower, c_name)
                token_sim = fuzz.token_sort_ratio(clean_q_lower, c_name)
                sc = (sim_ratio * 0.6) + (token_sim * 0.4)

                # Exact match priority
                if c_name == clean_q_lower:
                    sc += 120.0
                elif c_name.startswith(clean_q_lower + " ") or c_name.startswith(clean_q_lower + ":"):
                    sc += 25.0

                # Type context priority
                if is_probable_series and c_type == "series":
                    sc += 40.0
                elif not is_probable_series and c_name == clean_q_lower and c_type == "series":
                    # For iconic anime/shows like 'One Piece', exact series match is super strong
                    sc += 30.0

                # Release year bonus
                rel_info = str(c.get("releaseInfo") or c.get("year") or "")
                y_m = re.search(r"\b(19\d{2}|20\d{2})\b", rel_info)
                if y_m:
                    yr = int(y_m.group(1))
                    # Favor original/classic anime/movie or recent popular
                    if yr <= 2000:
                        sc += 5.0

                return sc

            # Sort all candidates by score descending
            ranked_candidates = sorted(candidates, key=score_candidate, reverse=True)
            best = ranked_candidates[0]
            imdb_id = best.get("id")
            if not imdb_id:
                _CINEMETA_CACHE[cache_key] = (now, None)
                return None

            m_type = best.get("type", "series" if is_probable_series else "movie")
            title = best.get("name") or search_title.title()

            # Extract year
            rel_info = str(best.get("releaseInfo") or best.get("year") or "")
            y_match = re.search(r"\b(19\d{2}|20\d{2})\b", rel_info)
            year = int(y_match.group(1)) if y_match else None

            # Always fetch full Cinemeta metadata for best candidate to resolve moviedb_id and exact details
            detail_meta = await get_meta_by_imdb(imdb_id, m_type)
            tmdb_id = detail_meta.get("moviedb_id") or best.get("moviedb_id")

            rating = detail_meta.get("rating")
            if not rating and best.get("imdbRating"):
                try:
                    rating = float(best.get("imdbRating"))
                except (ValueError, TypeError):
                    pass

            genres = detail_meta.get("genres")
            if not genres:
                genres_val = best.get("genres")
                genres = ", ".join(genres_val) if isinstance(genres_val, list) else (str(genres_val) if genres_val else "")

            if not year and detail_meta.get("year"):
                year = detail_meta.get("year")

            servers = get_online_servers(
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
                media_type=m_type,
                season=season_num,
                episode=episode_num
            )

            # Collect distinct alternative matches (e.g. Movies, Anime releases, Spinoffs)
            alternatives = []
            for alt in ranked_candidates[1:5]:
                alt_id = alt.get("id")
                alt_name = alt.get("name")
                if not alt_id or not alt_name or alt_id == imdb_id:
                    continue
                alt_type = alt.get("type", "movie")
                rel = str(alt.get("releaseInfo") or alt.get("year") or "")
                ym = re.search(r"\b(19\d{2}|20\d{2})\b", rel)
                alt_year = int(ym.group(1)) if ym else None
                alternatives.append({
                    "imdb_id": alt_id,
                    "title": alt_name,
                    "year": alt_year,
                    "media_type": alt_type,
                    "rating": float(alt.get("imdbRating", 7.0)) if alt.get("imdbRating") else None
                })

            result = {
                "imdb_id": imdb_id,
                "tmdb_id": tmdb_id,
                "title": title,
                "year": year,
                "media_type": m_type,
                "rating": rating,
                "genres": genres,
                "poster": detail_meta.get("poster") or best.get("poster"),
                "backdrop": detail_meta.get("backdrop") or best.get("background") or best.get("poster"),
                "overview": detail_meta.get("overview") or best.get("description", ""),
                "season": season_num,
                "episode": episode_num,
                "servers": servers,
                "default_url": servers.get("vidlink", {}).get("url") if servers else "",
                "alternatives": alternatives
            }

            _CINEMETA_CACHE[cache_key] = (now, result)
            return result

    except Exception as e:
        logger.warning(f"Cinemeta online search failed for '{clean_q}': {e}")
        return None


async def get_series_episodes_meta(imdb_id: str) -> Optional[Dict[str, Any]]:
    """Fetch all seasons and episodes for a TV series from Cinemeta."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json")
            if res.status_code != 200:
                return None
            meta = res.json().get("meta", {})
            videos = meta.get("videos", [])
            valid_videos = [v for v in videos if v.get("season", 0) > 0] or videos

            seasons = sorted(list(set(v.get("season", 1) for v in valid_videos)))
            episodes_by_season = {}
            for s in seasons:
                eps = [v for v in valid_videos if v.get("season") == s]
                eps_sorted = sorted(eps, key=lambda x: x.get("number") or x.get("episode", 1))
                episodes_by_season[str(s)] = [
                    {
                        "season": ep.get("season", 1),
                        "episode": ep.get("number") or ep.get("episode", 1),
                        "title": ep.get("name") or f"Episode {ep.get('number') or ep.get('episode', 1)}",
                        "overview": ep.get("overview") or ep.get("description", ""),
                        "thumbnail": ep.get("thumbnail")
                    }
                    for ep in eps_sorted
                ]

            return {
                "title": meta.get("name"),
                "year": meta.get("year"),
                "seasons": seasons,
                "episodes_by_season": episodes_by_season,
                "total_episodes": len(valid_videos)
            }
    except Exception as e:
        logger.warning(f"Failed to fetch series episodes for {imdb_id}: {e}")
        return None


# Cache for direct IMDb metadata lookups
_IMDB_META_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}


async def get_meta_by_imdb(imdb_id: str, media_type: str = "movie") -> Dict[str, Any]:
    """Fetch complete metadata (poster, name, year, overview, rating, genres) for any IMDb ID."""
    if not imdb_id:
        return {}
    now = asyncio.get_event_loop().time()
    if imdb_id in _IMDB_META_CACHE:
        t, data = _IMDB_META_CACHE[imdb_id]
        if now - t < _CACHE_TTL:
            return data

    m_catalog = "series" if media_type == "series" else "movie"
    url = f"https://v3-cinemeta.strem.io/meta/{m_catalog}/{imdb_id}.json"

    try:
        # 1. Fetch official localized title & aliases from IMDb global CDN (handles AKA titles like My Royal Nemesis)
        alt_titles = []
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
                imdb_res = await client.get(f"https://v3.sg.media-imdb.com/suggestion/x/{imdb_id}.json")
                if imdb_res.status_code == 200:
                    for item in imdb_res.json().get("d", []):
                        if item.get("id") == imdb_id and item.get("l"):
                            alt_titles.append(item["l"].strip())
        except Exception as e_imdb:
            logger.debug(f"IMDb suggestion fetch skipped for {imdb_id}: {e_imdb}")

        # 2. Fetch full metadata from Cinemeta with redirect following
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            res = await client.get(url)
            # If not found under specified type, try alternate catalog
            if res.status_code != 200:
                alt_catalog = "movie" if m_catalog == "series" else "series"
                res = await client.get(f"https://v3-cinemeta.strem.io/meta/{alt_catalog}/{imdb_id}.json")

            if res.status_code == 200:
                meta = res.json().get("meta", {})
                genres_raw = meta.get("genres", [])
                genres = ", ".join(genres_raw) if isinstance(genres_raw, list) else str(genres_raw or "")
                
                # Extract year
                rel_info = str(meta.get("releaseInfo") or meta.get("year") or "")
                y_match = re.search(r"\b(19\d{2}|20\d{2})\b", rel_info)
                year = int(y_match.group(1)) if y_match else None

                rating = None
                if meta.get("imdbRating"):
                    try:
                        rating = float(meta.get("imdbRating"))
                    except (ValueError, TypeError):
                        pass

                c_name = meta.get("name")
                if c_name and c_name not in alt_titles:
                    alt_titles.append(c_name.strip())

                # Primary title prefers IMDb display title, fallback to Cinemeta name
                chosen_title = alt_titles[0] if alt_titles else (c_name or "Online Cinema")

                data = {
                    "title": chosen_title,
                    "alt_titles": alt_titles,
                    "year": year,
                    "poster": meta.get("poster"),
                    "backdrop": meta.get("background") or meta.get("poster"),
                    "rating": rating,
                    "genres": genres,
                    "overview": meta.get("description", ""),
                    "media_type": meta.get("type", media_type),
                    "moviedb_id": meta.get("moviedb_id"),
                    "tvdb_id": meta.get("tvdb_id")
                }
                _IMDB_META_CACHE[imdb_id] = (now, data)
                return data
            elif alt_titles:
                # Cinemeta failed but IMDb suggestion gave title
                data = {
                    "title": alt_titles[0],
                    "alt_titles": alt_titles,
                    "year": None,
                    "poster": None,
                    "backdrop": None,
                    "rating": None,
                    "genres": "",
                    "overview": "",
                    "media_type": media_type,
                    "moviedb_id": None,
                    "tvdb_id": None
                }
                _IMDB_META_CACHE[imdb_id] = (now, data)
                return data
    except Exception as e:
        logger.warning(f"Failed to fetch metadata for {imdb_id}: {e}")

    return {}


def get_online_player_url(
    imdb_id: str,
    media_type: str = "movie",
    season: int = 1,
    episode: int = 1,
    title: str = "",
    tmdb_id: Optional[int] = None
) -> str:
    """Return effective URL for Telegram button.
    If bot has a public STREAM_URL / WEB_URL configured, points to bot's cinema player page.
    Otherwise, points directly to top reliable embed player (VidLink).
    Guarantees no 'localhost' or invalid URL that would cause Telegram 400 error.
    """
    base_url = (Config.STREAM_URL or Config.WEB_URL or "").strip().rstrip("/")
    if base_url:
        q_params = [f"type={media_type}"]
        if media_type == "series":
            q_params.append(f"s={season}")
            q_params.append(f"e={episode}")
        if title:
            q_params.append(f"title={urllib.parse.quote(title)}")
        if tmdb_id:
            q_params.append(f"tmdb={tmdb_id}")
        query_str = "&".join(q_params)
        return f"{base_url}/watch_online/{imdb_id}?{query_str}"

    # Direct embed fallback
    effective_series_id = str(tmdb_id) if tmdb_id else imdb_id
    if media_type == "series":
        return f"https://vidlink.pro/tv/{effective_series_id}/{season}/{episode}?autoplay=true"
    return f"https://vidlink.pro/movie/{imdb_id}?autoplay=true"
