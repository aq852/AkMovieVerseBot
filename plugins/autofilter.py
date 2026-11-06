import re
import math
import asyncio
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from rapidfuzz import process

from config import Config
from database.files import get_search_results, count_files, get_sample_titles
from database.chats import add_chat, get_chat_settings
from database.filters import get_manual_filter
from utils.helpers import clean_search_query, build_filter_buttons, format_search_results_text, is_private_chat

logger = logging.getLogger(__name__)

# Cached catalog titles for rapid spell-check
TITLES_CACHE = []
LAST_CACHE_UPDATE = 0

async def refresh_titles_cache():
    global TITLES_CACHE, LAST_CACHE_UPDATE
    try:
        TITLES_CACHE = await get_sample_titles(limit=3000)
        LAST_CACHE_UPDATE = asyncio.get_event_loop().time()
    except Exception as e:
        logger.debug(f"Failed to refresh titles cache: {e}")


async def schedule_auto_delete(messages: list[Message], delay_seconds: int):
    """Background task to delete query and response messages after delay to keep chats clean."""
    if delay_seconds <= 0:
        return
    await asyncio.sleep(delay_seconds)
    for msg in messages:
        try:
            await msg.delete()
        except Exception:
            pass


COMMAND_EXCLUDES = [
    "start", "help", "settings", "stats", "index", "setskip", "stopindex",
    "broadcast", "grp_broadcast", "filter", "filters", "stop", "stopall",
    "id", "info", "imdb", "plans", "myplan", "refer",
    "premium_users", "premium_list", "add_premium", "remove_premium",
    "deletefiles", "delete", "deleteall", "ban", "unban", "send",
    "commands", "poster", "set_pic", "setpic", "shortlink", "connect", "disconnect", "cancel",
    "shorteners", "shortners", "shortener", "shortner", "add_shortener", "add_shortner", "del_shortener", "del_shortner", "set_web_url",
    "request", "req", "acceptall", "approveall", "accept", "approve",
    "declineall", "rejectall", "decline", "reject", "autoapprove",
    "set_welcome", "setwelcome", "get_welcome", "getwelcome", "reset_welcome", "resetwelcome",
    "sharelink", "createlink", "share", "sharefile", "test_welcome", "testwelcome", "set_welcome_pic", "setwelcomepic", "del_welcome_pic", "delwelcomepic", "reset_welcome_pic",
    "thumbnail", "art", "styles", "posterstyles", "set_poster_brand", "setposterbrand", "setbrand", "set_poster_channel", "setposterchannel",
    "set_tmdb_key", "settmdbkey", "set_tmdb_token", "settmdbtoken", "tmdb_status", "tmdbstatus",
    "dl", "download", "watch", "streamonline"
]

@Client.on_message((filters.group | filters.private) & filters.text & ~filters.command(COMMAND_EXCLUDES) & ~filters.bot & ~filters.via_bot & ~filters.outgoing)
async def group_auto_filter_handler(client: Client, message: Message):
    """Automatically search files when a user asks for a movie/series in group or PM."""
    if message.text.startswith("/") or (message.from_user and message.from_user.is_bot):
        return

    # Let the downloader plugin process direct URL messages in PM or group
    if re.search(r"^https?://\S+$", message.text.strip()):
        message.continue_propagation()
        return

    chat_id = message.chat.id
    is_pm = is_private_chat(message)

    # Ignore text input if user is actively setting title/PIN/expiry in filestore in PM
    if is_pm and message.from_user:
        try:
            from plugins.file_store import is_user_in_filestore_session
            if is_user_in_filestore_session(message.from_user.id):
                return
        except Exception:
            pass

    # Register chat and load settings
    if not is_pm:
        await add_chat(chat_id, message.chat.title or "")
        chat_settings = await get_chat_settings(chat_id)
    else:
        chat_settings = {
            "auto_delete": False,
            "auto_delete_time": 0,
            "imdb_enabled": Config.ENABLE_IMDB,
            "single_button": Config.SINGLE_BUTTON
        }

    raw_query = message.text.strip()
    # Ignore long paragraphs, forwarded command lists, or multi-line messages
    if len(raw_query) > 100 or (raw_query.count("\n") >= 2 and len(raw_query) > 50):
        return

    # 1. Check for manual keyword filters first
    manual_filter = await get_manual_filter(chat_id, raw_query)
    if manual_filter:
        reply_text = manual_filter.get("reply_text", "")
        file_id = manual_filter.get("file_id")
        if file_id:
            await message.reply_cached_media(file_id, caption=reply_text)
        else:
            await message.reply_text(reply_text)
        return

    # 2. Search MongoDB Files Database
    import time
    start_time = time.time()
    clean_q = clean_search_query(raw_query)
    if not clean_q or len(clean_q) < 2:
        return

    # In groups, ignore common conversational words so bot doesn't spam regular chatting
    CONVERSATIONAL_WORDS = {
        "hi", "hello", "hey", "ok", "okay", "thanks", "thank you", "thx",
        "bye", "good morning", "good night", "gm", "gn", "admin", "pls",
        "please", "bro", "bhai", "sir", "yes", "no", "kya", "ha", "haan"
    }
    if not is_pm and (clean_q.lower() in CONVERSATIONAL_WORDS or len(clean_q) < 3):
        return

    total_files = await count_files(clean_q)
    # Smart Year Fallback: if user typed a year (e.g. Jawan 2023) but filenames lack the release year, retry without the year
    if total_files == 0:
        year_m = re.search(r"\b(19\d{2}|20\d{2})\b", clean_q)
        if year_m:
            fallback_q = re.sub(r"\b(19\d{2}|20\d{2})\b", "", clean_q).strip()
            fallback_q = re.sub(r"\s+", " ", fallback_q)
            if len(fallback_q) >= 2:
                fallback_count = await count_files(fallback_q)
                if fallback_count > 0:
                    total_files = fallback_count
                    clean_q = fallback_q

    button_mode = "single" if chat_settings.get("single_button", True) else "double"

    if total_files > 0:
        results = await get_search_results(clean_q, offset=0, limit=10)
        total_pages = math.ceil(total_files / 10)
        elapsed_sec = f"{time.time() - start_time:.2f}"

        # Get bot username for deep-links
        bot_username = client.me.username if client.me else Config.BOT_USERNAME
        user_name = message.from_user.first_name if message.from_user else "User"
        user_mention = message.from_user.mention(user_name) if message.from_user else user_name

        reply_markup = build_filter_buttons(
            results=results,
            page=1,
            total_pages=total_pages,
            query=clean_q,
            bot_username=bot_username,
            is_pm=is_pm,
            mode=button_mode
        )

        # Build clean Image 2 style hyperlinked text with sizes & full filenames
        content_text = format_search_results_text(
            results=results,
            query=raw_query,
            total_files=total_files,
            bot_username=bot_username,
            user_mention=user_mention,
            elapsed_sec=elapsed_sec,
            page=1,
            total_pages=total_pages
        )

        # Send clean, instant text search results (<0.1s delivery) with link preview disabled
        sent_msg = await message.reply_text(content_text, reply_markup=reply_markup, disable_web_page_preview=True)

        # Handle auto-delete in both PM and groups
        auto_del_enabled = True if is_pm else chat_settings.get("auto_delete", True)
        if auto_del_enabled:
            from database.mongo import get_bot_setting
            search_del = await get_bot_setting("search_auto_delete_time", Config.AUTO_DELETE_TIME)
            auto_delete_time = search_del if is_pm else chat_settings.get("auto_delete_time", search_del)
            asyncio.create_task(schedule_auto_delete([message, sent_msg], auto_delete_time))

    else:
        # Record zero-result audience demand in MongoDB
        try:
            from plugins.hype_drop import record_search_demand
            asyncio.create_task(record_search_demand(clean_q, message.from_user.id if message.from_user else 0))
        except Exception:
            pass

        # Log zero-result movie demand to Log Channel in background task
        if Config.LOG_CHANNEL:
            u_name = message.from_user.first_name if message.from_user else "User"
            u_mention = message.from_user.mention(u_name) if message.from_user else "Anonymous"
            u_id = message.from_user.id if message.from_user else "N/A"
            c_name = "Private PM" if is_private_chat(message) else message.chat.title

            async def _safe_send_demand():
                try:
                    await client.send_message(
                        Config.LOG_CHANNEL,
                        f"🔍 **#MovieDemand (0 Results Found)**\n\n"
                        f"• **Query:** `{clean_q}`\n"
                        f"• **Requested By:** {u_mention} (`{u_id}`)\n"
                        f"• **Chat:** `{c_name}`\n"
                        f"💡 _Tip: Upload this movie to storage channel to satisfy demand!_"
                    )
                except Exception as ex:
                    logger.debug(f"Failed to send movie demand log: {ex}")

            asyncio.create_task(_safe_send_demand())

        # 3. Spell-Check / Fuzzy Suggestions or "No Results Found" Feedback
        global TITLES_CACHE, LAST_CACHE_UPDATE
        loop_time = asyncio.get_event_loop().time()
        if not TITLES_CACHE or (loop_time - LAST_CACHE_UPDATE > 600):
            await refresh_titles_cache()

        match = None
        if TITLES_CACHE:
            from rapidfuzz import fuzz
            from utils.title_cleaner import extract_core_title
            clean_q_core = extract_core_title(clean_q).lower().strip()
            # Only match actual non-numeric title words (filter out 4-digit years like 2026 to prevent year-traps)
            q_words = [w for w in clean_q_core.split() if len(w) >= 3 and not w.isdigit()]

            best_candidate = None
            best_clean_title = None
            best_score = 0

            # Only attempt fuzzy matching if query has actual alphabetic title words
            if q_words and clean_q_core:
                for raw_title in TITLES_CACHE:
                    candidate_core = extract_core_title(raw_title).lower().strip()
                    if not candidate_core or candidate_core == clean_q_core:
                        continue
                    c_words = [w for w in candidate_core.split() if len(w) >= 3 and not w.isdigit()]
                    if not c_words:
                        continue

                    # At least one meaningful query word must fuzzy-match a candidate word (>= 70 ratio)
                    word_match = any(
                        any(fuzz.ratio(qw, cw) >= 70 for cw in c_words)
                        for qw in q_words
                    )

                    if not word_match:
                        continue

                    w_score = fuzz.WRatio(clean_q_core, candidate_core)
                    score = w_score

                    if score > best_score and score >= 65:
                        best_score = score
                        best_candidate = raw_title
                        best_clean_title = extract_core_title(raw_title)

            if best_candidate and best_clean_title:
                match = (best_clean_title, best_score)

        # Fast background lookup on Cinemeta for online web stream player (TeleStream engine)
        from utils.online_stream import search_online_meta, get_online_player_url
        online_meta = None
        try:
            # Use raw_query so season/episode tokens are preserved, with 4.5s safe timeout
            online_meta = await asyncio.wait_for(search_online_meta(raw_query or clean_q), timeout=4.5)
        except Exception as e:
            logger.debug(f"Cinemeta online search skipped/timed out: {e}")

        import urllib.parse
        bot_username = client.me.username if client.me else Config.BOT_USERNAME
        base_url = (Config.STREAM_URL or Config.WEB_URL or "").strip().rstrip("/")
        encoded_query = urllib.parse.quote(clean_q)
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(f'{clean_q} movie')}"
        
        # Build direct 1-click browser stream URL
        if online_meta and online_meta.get("imdb_id"):
            online_stream_url = get_online_player_url(
                imdb_id=online_meta["imdb_id"],
                media_type=online_meta.get("media_type", "movie"),
                season=online_meta.get("season", 1),
                episode=online_meta.get("episode", 1),
                title=online_meta.get("title", ""),
                tmdb_id=online_meta.get("tmdb_id")
            )
        elif base_url:
            online_stream_url = f"{base_url}/watch_online/search?q={encoded_query}"
        else:
            online_stream_url = google_url

        if match:
            suggested_title = match[0].strip()
            disp_title = suggested_title if len(suggested_title) <= 32 else f"{suggested_title[:29]}..."
            buttons = [
                [InlineKeyboardButton(f"🔍 Search '{disp_title}'", callback_data=f"spell_{suggested_title[:25]}")],
                [InlineKeyboardButton("🔔 Notify Me When Uploaded", callback_data=f"notifme_{clean_q[:25]}")],
                [InlineKeyboardButton("🌐 Stream Online in HD ↗️", url=online_stream_url)],
                [InlineKeyboardButton("💬 Request Movie", callback_data=f"reqmovie_{clean_q[:25]}")]
            ]

            online_info = ""
            if online_meta:
                m_title = online_meta.get("title") or clean_q.title()
                year_val = f" ({online_meta['year']})" if online_meta.get("year") else ""
                rating_val = f"⭐ `{online_meta['rating']}`" if online_meta.get("rating") else "⭐ `8.0`"
                genres_val = f" | 🎭 {online_meta['genres']}" if online_meta.get("genres") else ""
                online_info = (
                    f"🍿 **Web Stream Available:**\n"
                    f"🎬 **{m_title}**{year_val}\n"
                    f"{rating_val}{genres_val}\n\n"
                )

            not_found_msg = await message.reply_text(
                f"⚠️ **Could not find any file for:** `{clean_q}`\n\n"
                f"💡 **Did you mean:** `{suggested_title}`?\n\n"
                f"{online_info}"
                f"_Click the suggested button below to search, or stream online in your browser._",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            buttons = [
                [InlineKeyboardButton("🔔 Notify Me When Uploaded", callback_data=f"notifme_{clean_q[:25]}")],
                [InlineKeyboardButton("🌐 Stream Online in HD ↗️", url=online_stream_url)],
                [InlineKeyboardButton("💬 Request Movie", callback_data=f"reqmovie_{clean_q[:25]}")]
            ]

            if online_meta:
                m_title = online_meta.get("title") or clean_q.title()
                season_label = f" [Season {online_meta['season']}]" if online_meta.get("season", 1) > 1 else ""
                year_val = f" ({online_meta['year']})" if online_meta.get("year") else ""
                rating_val = f"⭐ Rating: `{online_meta['rating']}`" if online_meta.get("rating") else "⭐ Rating: `8.0`"
                genres_val = f" | 🎭 {online_meta['genres']}" if online_meta.get("genres") else ""
                type_label = "TV Series / Anime" if online_meta.get("media_type") == "series" else "Movie"

                not_found_msg = await message.reply_text(
                    f"😕 **File Not Found in Local Channel!**\n\n"
                    f"❌ Direct Telegram file is not in our database for: `{clean_q}`\n\n"
                    f"🍿 **Great News! It's Available to Stream Online:**\n"
                    f"🎬 **{type_label}:** {m_title}{year_val}{season_label}\n"
                    f"{rating_val}{genres_val}\n"
                    f"⚡ Multi-server streaming ready (VidLink, VidEm, VidSrc, Smashy, AutoEmbed, 2Embed, Vidy, VidZee, NontonGo, SuperEmbed)!\n\n"
                    f"👇 _Tap the button below to stream directly in your browser:_ ",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                not_found_msg = await message.reply_text(
                    f"😕 **No Search Results Found!**\n\n"
                    f"❌ **Sorry!** We couldn't find any file matching: `{clean_q}` in our database.\n\n"
                    f"📌 **Search Tips:**\n"
                    f"• Check the spelling of the movie/series name.\n"
                    f"• Try searching with the release year (e.g. `{clean_q} 2024`).\n"
                    f"• Avoid extra symbols, dots, or quality tags.\n\n"
                    f"👇 _Stream online in your browser or request this file below!_",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        auto_del_enabled = True if is_pm else chat_settings.get("auto_delete", True)
        if auto_del_enabled:
            auto_delete_time = 60 if is_pm else chat_settings.get("auto_delete_time", 60)
            asyncio.create_task(schedule_auto_delete([message, not_found_msg], auto_delete_time))
