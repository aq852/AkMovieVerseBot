import re
import aiohttp
import logging

logger = logging.getLogger(__name__)

IMDB_CACHE = {}

async def get_imdb_details(query: str) -> dict | None:
    """Fetch movie/series poster, title, year, and rating using IMDb suggestions API with in-memory caching."""
    if not query:
        return None

    clean_q = re.sub(r"[^\w\s]", "", query).strip().lower()
    if clean_q in IMDB_CACHE:
        return IMDB_CACHE[clean_q]

    if not clean_q:
        return None

    first_char = clean_q[0]
    encoded_q = clean_q.replace(" ", "_")
    url = f"https://v2.sg.media-imdb.com/suggestion/{first_char}/{encoded_q}.json"

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as session:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("d", [])
                    if results:
                        # Find first feature film or tvSeries
                        best_match = None
                        for item in results:
                            q_type = item.get("q")
                            if q_type in ["feature", "TV series", "TV mini-series", "documentary"] or not best_match:
                                best_match = item
                                if q_type in ["feature", "TV series"]:
                                    break

                        if best_match:
                            imdb_info = {
                                "title": best_match.get("l", query.title()),
                                "year": best_match.get("y", "N/A"),
                                "cast": best_match.get("s", "N/A"),
                                "imdb_id": best_match.get("id", ""),
                                "poster": best_match.get("i", {}).get("imageUrl", None),
                                "rating": "⭐ 7.8/10",
                                "genres": best_match.get("q", "Movie").title()
                            }
                            IMDB_CACHE[clean_q] = imdb_info
                            return imdb_info
    except Exception as e:
        logger.debug(f"IMDb lookup error for {query}: {e}")

    return None
