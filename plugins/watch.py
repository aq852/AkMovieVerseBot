import logging
import urllib.parse
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from utils.online_stream import search_online_meta, get_online_player_url

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["watch", "streamonline"]))
async def watch_command_handler(client: Client, message: Message):
    """Direct /watch command to search and stream any movie/show online in browser with multi-servers."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text(
            "🍿 **How to Watch Movies & Series Online:**\n\n"
            "Use the `/watch` command followed by the title of any movie or show:\n"
            "👉 `/watch Thor`\n"
            "👉 `/watch Inception`\n"
            "👉 `/watch Kalki 2898 AD`\n"
            "👉 `/watch Stranger Things 4`\n\n"
            "⚡ _Opens instantly in our multi-server online cinema without downloading!_"
        )
        return

    query = parts[1].strip()
    status_msg = await message.reply_text(f"🔍 _Searching online streaming servers for:_ `{query}`...")

    online_meta = await search_online_meta(query)
    base_url = (Config.STREAM_URL or Config.WEB_URL or "").strip().rstrip("/")
    encoded_q = urllib.parse.quote(query)

    if not online_meta or not online_meta.get("imdb_id"):
        search_url = f"{base_url}/watch_online/search?q={encoded_q}" if base_url else f"https://www.google.com/search?q={urllib.parse.quote(f'{query} movie')}"
        buttons = [
            [InlineKeyboardButton("🌐 Search in Cinema Hub ↗️", url=search_url)],
            [InlineKeyboardButton("💬 Request Movie", callback_data=f"reqmovie_{query[:25]}")]
        ]
        await status_msg.edit_text(
            f"😕 **No direct online match found for:** `{query}`\n\n"
            "You can still try launching the online cinema search in your browser:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Build Player URL
    imdb_id = online_meta["imdb_id"]
    tmdb_id = online_meta.get("tmdb_id")
    m_title = online_meta.get("title") or query.title()
    media_type = online_meta.get("media_type", "movie")
    season = online_meta.get("season", 1)
    episode = online_meta.get("episode", 1)
    year_val = f" ({online_meta['year']})" if online_meta.get("year") else ""
    rating_val = f"⭐ `{online_meta['rating']}/10 IMDb`" if online_meta.get("rating") else "⭐ `8.0/10`"
    genres_val = f" • 🎭 {online_meta['genres']}" if online_meta.get("genres") else ""
    type_label = "TV Series / Anime" if media_type == "series" else "Movie"
    season_label = f" [Season {season}]" if season > 1 else ""

    player_url = get_online_player_url(
        imdb_id=imdb_id,
        media_type=media_type,
        season=season,
        episode=episode,
        title=m_title,
        tmdb_id=tmdb_id
    )

    buttons = [
        [InlineKeyboardButton("🍿 Stream Movie Online in HD ↗️", url=player_url)],
        [InlineKeyboardButton("💬 Request Movie", callback_data=f"reqmovie_{query[:25]}")]
    ]

    overview_text = (online_meta.get('overview') or "Stream directly with multiple fast servers. Switch servers if playback buffers.").strip()
    if len(overview_text) > 240:
        overview_text = overview_text[:237] + "..."

    caption = (
        f"🍿 **AkMovieVerse Online Cinema**\n\n"
        f"🎬 **{type_label}:** {m_title}{year_val}{season_label}\n"
        f"{rating_val}{genres_val}\n\n"
        f"⚡ **11+ Multi-Server Streaming Ready (VidLink, VidEm, VidSrc, Smashy, AutoEmbed, 2Embed, Vidy, VidZee, NontonGo, SuperEmbed)!**\n"
        f"_{overview_text}_\n\n"
        f"👇 _Tap the button below to watch directly in your browser:_"
    )

    poster_url = online_meta.get("poster")
    try:
        await status_msg.delete()
    except Exception:
        pass

    if poster_url:
        try:
            await message.reply_photo(photo=poster_url, caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
            return
        except Exception as e:
            logger.debug(f"Failed to send poster photo: {e}")

    await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons))
