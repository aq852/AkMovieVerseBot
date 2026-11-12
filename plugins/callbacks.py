import asyncio
import html
import math
import logging
import urllib.parse
try:
    from hydrogram import Client, filters
    from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from database.files import get_search_results, count_files, get_file_by_id
from database.chats import get_chat_settings
from database.verify import is_user_verified
from plugins.start import deliver_file_with_copyright_warning
from utils.helpers import build_filter_buttons, build_category_keyboard, format_search_results_text

logger = logging.getLogger(__name__)

# Active search message filters: {f"{chat_id}_{message_id}": {"quality": ..., "language": ..., "season": ...}}
MSG_FILTERS = {}

def _is_private_chat(query: CallbackQuery) -> bool:
    chat_type = query.message.chat.type
    return (
        getattr(chat_type, "value", None) == "private"
        or str(chat_type) in ("ChatType.PRIVATE", "private")
    )


@Client.on_callback_query(filters.regex(r"^noop_pages"))
async def noop_pages_callback(client: Client, query: CallbackQuery):
    await query.answer("You are currently viewing this page.", show_alert=False)


@Client.on_callback_query(filters.regex(r"^close_filter"))
async def close_filter_callback(client: Client, query: CallbackQuery):
    """Delete the search results message."""
    try:
        await query.message.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^openqual_"))
async def open_qual_menu_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("openqual_"):]
    markup = build_category_keyboard(search_q, cat_type="quality")
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^openlang_"))
async def open_lang_menu_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("openlang_"):]
    markup = build_category_keyboard(search_q, cat_type="language")
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^openseas_"))
async def open_seas_menu_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("openseas_"):]
    markup = build_category_keyboard(search_q, cat_type="season")
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^setqual_"))
async def set_quality_callback(client: Client, query: CallbackQuery):
    """Apply quality filter (480p, 720p, 1080p, 2160p) to the current query."""
    data = query.data[len("setqual_"):]
    quality, search_q = data.split("_", 1)
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    filters_dict = MSG_FILTERS.setdefault(msg_key, {})

    # Check if matching files exist with this quality
    total = await count_files(
        search_q,
        quality=quality,
        language=filters_dict.get("language"),
        season=filters_dict.get("season")
    )
    if total == 0:
        await query.answer(f"❌ No {quality} files found for '{search_q}'!", show_alert=True)
        return

    filters_dict["quality"] = quality
    await query.answer(f"✅ Filter applied: {quality} ({total} files)", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^setlang_"))
async def set_language_callback(client: Client, query: CallbackQuery):
    """Apply language filter (Hindi, English, Tamil, Telugu, Dual) to the current query."""
    data = query.data[len("setlang_"):]
    lang, search_q = data.split("_", 1)
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    filters_dict = MSG_FILTERS.setdefault(msg_key, {})

    total = await count_files(
        search_q,
        quality=filters_dict.get("quality"),
        language=lang,
        season=filters_dict.get("season")
    )
    if total == 0:
        await query.answer(f"❌ No {lang.capitalize()} files found for '{search_q}'!", show_alert=True)
        return

    filters_dict["language"] = lang
    await query.answer(f"✅ Filter applied: {lang.capitalize()} ({total} files)", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^setseas_"))
async def set_season_callback(client: Client, query: CallbackQuery):
    """Apply season filter (s01, s02, etc.) to the current query."""
    data = query.data[len("setseas_"):]
    season, search_q = data.split("_", 1)
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    filters_dict = MSG_FILTERS.setdefault(msg_key, {})

    total = await count_files(
        search_q,
        quality=filters_dict.get("quality"),
        language=filters_dict.get("language"),
        season=season
    )
    if total == 0:
        await query.answer(f"❌ No {season.upper()} files found for '{search_q}'!", show_alert=True)
        return

    filters_dict["season"] = season
    await query.answer(f"✅ Filter applied: {season.upper()} ({total} files)", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^clearqual_"))
async def clear_qual_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("clearqual_"):]
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    if msg_key in MSG_FILTERS:
        MSG_FILTERS[msg_key].pop("quality", None)
    await query.answer("🔄 Quality filter cleared", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^clearlang_"))
async def clear_lang_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("clearlang_"):]
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    if msg_key in MSG_FILTERS:
        MSG_FILTERS[msg_key].pop("language", None)
    await query.answer("🔄 Language filter cleared", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^clearseas_"))
async def clear_seas_callback(client: Client, query: CallbackQuery):
    search_q = query.data[len("clearseas_"):]
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    if msg_key in MSG_FILTERS:
        MSG_FILTERS[msg_key].pop("season", None)
    await query.answer("🔄 Season filter cleared", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^resetfilter_"))
async def reset_filter_callback(client: Client, query: CallbackQuery):
    """Clear all active category filters."""
    search_q = query.data[len("resetfilter_"):]
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    MSG_FILTERS.pop(msg_key, None)
    await query.answer("🔄 All filters reset", show_alert=False)
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^backres_"))
async def back_results_callback(client: Client, query: CallbackQuery):
    """Return from category sub-menu to search results."""
    search_q = query.data[len("backres_"):]
    await refresh_filtered_results(client, query, search_q, page=1)


@Client.on_callback_query(filters.regex(r"^page_"))
async def pagination_callback(client: Client, query: CallbackQuery):
    """Switch pages in search results."""
    data = query.data[len("page_"):]
    page_str, search_q = data.split("_", 1)
    page = int(page_str)
    await refresh_filtered_results(client, query, search_q, page=page)


async def refresh_filtered_results(client: Client, query: CallbackQuery, search_q: str, page: int):
    """Helper to recalculate results with active filters and update the keyboard."""
    msg_key = f"{query.message.chat.id}_{query.message.id}"
    filters_dict = MSG_FILTERS.get(msg_key, {})
    quality = filters_dict.get("quality")
    language = filters_dict.get("language")
    season = filters_dict.get("season")

    total_files = await count_files(search_q, quality=quality, language=language, season=season)
    if total_files == 0:
        # Fallback to no filters if everything was 0
        MSG_FILTERS.pop(msg_key, None)
        quality, language, season = None, None, None
        total_files = await count_files(search_q)

    offset = (page - 1) * 10
    results = await get_search_results(
        search_q, offset=offset, limit=10,
        quality=quality, language=language, season=season
    )
    total_pages = max(1, math.ceil(total_files / 10))

    is_pm = _is_private_chat(query)
    chat_settings = await get_chat_settings(query.message.chat.id) if not is_pm else {}
    button_mode = "single" if chat_settings.get("single_button", True) else "double"
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    markup = build_filter_buttons(
        results=results,
        page=page,
        total_pages=total_pages,
        query=search_q,
        bot_username=bot_username,
        is_pm=is_pm,
        mode=button_mode,
        quality=quality,
        language=language,
        season=season
    )

    user_name = query.from_user.first_name if query.from_user else "User"
    user_mention = query.from_user.mention(user_name) if query.from_user else user_name

    sponsor_ad = None
    u_id = query.from_user.id if query.from_user else 0
    if u_id:
        try:
            from database.users import is_premium
            from database.ads import get_active_sponsor_ad
            if not await is_premium(u_id):
                sponsor_ad = await get_active_sponsor_ad()
        except Exception as e:
            logger.debug(f"Error fetching sponsor ad for callback: {e}")

    content_text = format_search_results_text(
        results=results,
        query=search_q,
        total_files=total_files,
        bot_username=bot_username,
        user_mention=user_mention,
        page=page,
        total_pages=total_pages,
        sponsor_ad=sponsor_ad
    )

    try:
        await query.message.edit_text(content_text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=markup)
        except Exception:
            pass
    try:
        await query.answer()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^sendall_"))
async def send_all_callback(client: Client, query: CallbackQuery):
    """Handle click on SEND ALL button."""
    data = query.data[len("sendall_"):]
    search_q, page_str = data.rsplit("_", 1)
    page = int(page_str)

    msg_key = f"{query.message.chat.id}_{query.message.id}"
    filters_dict = MSG_FILTERS.get(msg_key, {})
    quality = filters_dict.get("quality")
    language = filters_dict.get("language")
    season = filters_dict.get("season")

    offset = (page - 1) * 10
    results = await get_search_results(
        search_q, offset=offset, limit=10,
        quality=quality, language=language, season=season
    )

    if not results:
        await query.answer("No files to send!", show_alert=True)
        return

    is_pm = _is_private_chat(query)
    user_id = query.from_user.id
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    # Check VIP / Premium status for SEND ALL feature
    from database.users import is_premium
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if not is_vip:
        await query.answer(
            "🔒 SEND ALL is an Exclusive VIP Feature!\n\n"
            "Upgrade to VIP Premium to dispatch complete seasons & movie packages with 1 tap.\n"
            "Send /plans in PM to unlock!",
            show_alert=True
        )
        if is_pm:
            try:
                await query.message.reply_text(
                    "💎 <b>SEND ALL is an Exclusive VIP Feature!</b>\n\n"
                    "• Upgrade to <b>VIP Premium</b> to download entire seasons & movie collections with 1 single click.\n"
                    "• Plus get <b>30-Minute Auto-Delete</b> (Free: 5 mins) & Priority Requests!\n\n"
                    "👉 <i>Tap below to unlock VIP instantly:</i>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎟️ VIEW VIP PLANS ↗️", callback_data="view_plans")]
                    ])
                )
            except Exception:
                pass
        return

    if not is_pm:
        await query.answer(f"Sending {len(results)} files to your PM...", show_alert=False)
        try:
            for item in results:
                await deliver_file_with_copyright_warning(client, user_id, item)
                if len(results) > 1:
                    await asyncio.sleep(0.5)
            await query.message.reply_text(f"✅ Dispatched {len(results)} files to {query.from_user.mention}'s PM!")
        except Exception:
            await query.answer("Please start the bot in PM first so it can send you files!", show_alert=True)
    else:
        await query.answer(f"Sending {len(results)} files...", show_alert=False)
        for item in results:
            try:
                await deliver_file_with_copyright_warning(client, user_id, item)
                if len(results) > 1:
                    await asyncio.sleep(0.5)
            except Exception:
                pass


@Client.on_callback_query(filters.regex(r"^spell_"))
async def spell_check_callback(client: Client, query: CallbackQuery):
    """Handle click on 'Did you mean?' suggestion button."""
    suggested_q = query.data[len("spell_"):]
    total_files = await count_files(suggested_q)

    if total_files == 0:
        tokens = suggested_q.split()
        while len(tokens) > 1 and total_files == 0:
            tokens.pop()
            fallback_q = " ".join(tokens)
            cnt = await count_files(fallback_q)
            if cnt > 0:
                suggested_q = fallback_q
                total_files = cnt
                break

    if total_files == 0:
        await query.answer("⚠️ Files not found for this suggestion.", show_alert=True)
        return

    results = await get_search_results(suggested_q, offset=0, limit=10)
    total_pages = math.ceil(total_files / 10)
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    is_pm = _is_private_chat(query)

    markup = build_filter_buttons(
        results=results,
        page=1,
        total_pages=total_pages,
        query=suggested_q,
        bot_username=bot_username,
        is_pm=is_pm,
        mode="single"
    )

    user_name = query.from_user.first_name if query.from_user else "User"
    user_mention = query.from_user.mention(user_name) if query.from_user else user_name

    sponsor_ad = None
    u_id = query.from_user.id if query.from_user else 0
    if u_id:
        try:
            from database.users import is_premium
            from database.ads import get_active_sponsor_ad
            if not await is_premium(u_id):
                sponsor_ad = await get_active_sponsor_ad()
        except Exception as e:
            logger.debug(f"Error fetching sponsor ad for spell-check: {e}")

    text = format_search_results_text(
        results=results,
        query=suggested_q,
        total_files=total_files,
        bot_username=bot_username,
        user_mention=user_mention,
        page=1,
        total_pages=total_pages,
        sponsor_ad=sponsor_ad
    )
    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^getfile_"))
async def get_file_pm_callback(client: Client, query: CallbackQuery):
    """Handle direct file download button clicks when interacted with inside PM."""
    file_unique_id = query.data[len("getfile_"):]
    file_doc = await get_file_by_id(file_unique_id)

    if not file_doc:
        await query.answer("❌ File not found or has been deleted from database.", show_alert=True)
        return

    user_id = query.from_user.id

    # Check 24-hour verification or Daily Free Quota (VIP and Admin are exempt)
    from database.users import is_premium, check_daily_free_download, consume_daily_free_download
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    delivered_under_free = False
    used_pass_flag = False
    passes_left = 0
    used_count = 0
    quota_limit = getattr(Config, "DAILY_FREE_LIMIT", 3)

    if not is_vip and Config.SHORTENER_ENABLED and not await is_user_verified(user_id):
        # 1. First check bonus direct download passes from /store or rewards
        try:
            from database.loyalty import use_direct_pass
            used_pass, passes_left = await use_direct_pass(user_id)
            if used_pass:
                used_pass_flag = True
        except Exception:
            used_pass_flag = False

        if not used_pass_flag:
            has_free, used_today, limit = await check_daily_free_download(user_id)
            if has_free:
                used_count = await consume_daily_free_download(user_id)
                quota_limit = limit
                delivered_under_free = True
            else:
                await query.answer(
                    f"⏳ Daily Free Quota Exhausted ({used_today}/{limit})!\n\nPlease search or use /start to verify for 24h unlimited access, or get passes in /store.",
                    show_alert=True
                )
                return

    # Dispatch cached media with backup channel and 5-min auto-delete warning
    try:
        await deliver_file_with_copyright_warning(client, user_id, file_doc)
        if used_pass_flag:
            await query.answer(f"⚡ Direct Download Pass Used! ({passes_left} remaining)", show_alert=False)
        elif delivered_under_free:
            rem = max(0, quota_limit - used_count)
            await query.answer(f"🎁 Daily Free File ({used_count}/{quota_limit})! {rem} remaining today.", show_alert=False)
        else:
            await query.answer("✅ File sent to your PM!", show_alert=False)
    except Exception as e:
        logger.error(f"Failed to send cached file: {e}")
        await query.answer(f"❌ Error sending file: {e}", show_alert=True)


@Client.on_callback_query(filters.regex(r"^allservers_"))
async def all_servers_callback(client: Client, query: CallbackQuery):
    """Show all online streaming servers in an interactive list."""
    parts = query.data.split("_")
    imdb_id = parts[1]
    season = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    episode = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1

    from utils.online_stream import get_online_servers, get_meta_by_imdb
    imdb_meta = await get_meta_by_imdb(imdb_id)
    media_type = imdb_meta.get("media_type", "movie")
    tmdb_id = imdb_meta.get("moviedb_id")

    servers = get_online_servers(imdb_id=imdb_id, tmdb_id=tmdb_id, media_type=media_type, season=season, episode=episode)

    buttons = [
        [InlineKeyboardButton("⚡ Server 1: VidLink Pro (Fast / Ad-Free) ↗️", url=servers["vidlink"]["url"])],
        [InlineKeyboardButton("🎬 Server 2: Videm (HD Multi-Source) ↗️", url=servers["videm"]["url"])],
        [InlineKeyboardButton("🍿 Server 3: 2Embed Player ↗️", url=servers["twoembed"]["url"])],
        [InlineKeyboardButton("🚀 Server 4: SmashyStream ↗️", url=servers["smashystream"]["url"])],
        [InlineKeyboardButton("📽️ Server 5: Vidy Player ↗️", url=servers["vidy"]["url"])],
        [InlineKeyboardButton("🌐 Server 6: VidSrc (Multi-Mirror) ↗️", url=servers["vidsrc"]["url"])],
    ]

    base_url = (Config.STREAM_URL or Config.WEB_URL or "").strip().rstrip("/")
    if base_url:
        m_title = imdb_meta.get("title") or "Online Cinema"
        q_params = [f"type={media_type}"]
        if media_type == "series":
            q_params.extend([f"s={season}", f"e={episode}"])
        if m_title:
            q_params.append(f"title={urllib.parse.quote(m_title)}")
        if tmdb_id:
            q_params.append(f"tmdb={tmdb_id}")
        web_hub_url = f"{base_url}/watch_online/{imdb_id}?{'&'.join(q_params)}"
        buttons.append([InlineKeyboardButton("🖥️ Open Full Cinema Web Hub ↗️", url=web_hub_url)])

    buttons.append([InlineKeyboardButton("🔙 Back to Quick View", callback_data=f"backservers_{imdb_id}_{season}_{episode}")])

    try:
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"Error updating allservers keyboard: {e}")
    await query.answer("🍿 Showing all online streaming servers!")


@Client.on_callback_query(filters.regex(r"^backservers_"))
async def back_servers_callback(client: Client, query: CallbackQuery):
    """Restore default multi-server view with Request & VIP buttons."""
    parts = query.data.split("_")
    imdb_id = parts[1]
    season = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    episode = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1

    from utils.online_stream import get_online_servers, get_meta_by_imdb
    imdb_meta = await get_meta_by_imdb(imdb_id)
    media_type = imdb_meta.get("media_type", "movie")
    tmdb_id = imdb_meta.get("moviedb_id")

    servers = get_online_servers(imdb_id=imdb_id, tmdb_id=tmdb_id, media_type=media_type, season=season, episode=episode)

    base_url = (Config.STREAM_URL or Config.WEB_URL or "").strip().rstrip("/")
    if base_url:
        m_title = imdb_meta.get("title") or "Online Cinema"
        q_params = [f"type={media_type}"]
        if media_type == "series":
            q_params.extend([f"s={season}", f"e={episode}"])
        if m_title:
            q_params.append(f"title={urllib.parse.quote(m_title)}")
        if tmdb_id:
            q_params.append(f"tmdb={tmdb_id}")
        web_hub_url = f"{base_url}/watch_online/{imdb_id}?{'&'.join(q_params)}"
    else:
        web_hub_url = ""

    row_more = [InlineKeyboardButton("🍿 All Streaming Servers ⚡", callback_data=f"allservers_{imdb_id}_{season}_{episode}")]
    if web_hub_url:
        row_more.append(InlineKeyboardButton("🖥️ Cinema Hub ↗️", url=web_hub_url))

    buttons = [
        [
            InlineKeyboardButton("⚡ Server 1: VidLink ↗️", url=servers["vidlink"]["url"]),
            InlineKeyboardButton("🎬 Server 2: Videm ↗️", url=servers["videm"]["url"])
        ],
        [
            InlineKeyboardButton("🍿 Server 3: 2Embed ↗️", url=servers["twoembed"]["url"]),
            InlineKeyboardButton("🚀 Server 4: Smashy ↗️", url=servers["smashystream"]["url"])
        ],
        row_more,
        [
            InlineKeyboardButton("💬 Request Movie", callback_data=f"reqmovie_{imdb_id}")
        ]
    ]

    try:
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"Error restoring backservers keyboard: {e}")
    await query.answer()


@Client.on_callback_query(filters.regex(r"^altstream_"))
async def alt_stream_callback(client: Client, query: CallbackQuery):
    """Show alternative movie/series releases and versions for the search query."""
    search_q = query.data[len("altstream_"):].strip()
    from utils.online_stream import search_online_meta

    meta = await search_online_meta(search_q)
    if not meta or not meta.get("alternatives"):
        await query.answer("No alternative releases found for this title.", show_alert=True)
        return

    # Combined candidate list: primary + alternatives
    candidates = [{
        "imdb_id": meta["imdb_id"],
        "title": meta["title"],
        "year": meta.get("year"),
        "media_type": meta.get("media_type", "movie"),
        "rating": meta.get("rating")
    }] + meta.get("alternatives", [])

    buttons = []
    text_lines = [
        f"🍿 <b>Available Releases & Versions for:</b> <code>{search_q}</code>\n",
        f"👇 <i>Select which version you want to stream:</i>\n"
    ]

    for i, item in enumerate(candidates[:5], 1):
        type_icon = "📺 Series/Anime" if item.get("media_type") == "series" else "🎬 Movie"
        yr_str = f" ({item.get('year')})" if item.get("year") else ""
        btn_text = f"{i}. {item.get('title')}{yr_str} [{type_icon}]"
        # Clicking any alternative opens its 7 streaming servers
        buttons.append([
            InlineKeyboardButton(btn_text[:40], callback_data=f"allservers_{item['imdb_id']}_1_1")
        ])

    buttons.append([
        InlineKeyboardButton("🔙 Back to Quick View", callback_data=f"backservers_{meta['imdb_id']}_1_1")
    ])

    try:
        await query.message.edit_text(
            "\n".join(text_lines),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error in alt_stream_callback: {e}")
    await query.answer()


# ==============================================================================
# Gift Reward Flow Callbacks
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^claimgift_"))
async def claim_gift_callback_handler(client: Client, query: CallbackQuery):
    """Handle interactive task verification and reward claiming."""
    gift_id = query.data.split("claimgift_")[1]
    user_id = query.from_user.id
    from utils.gift_flow import render_gift_page
    await render_gift_page(client=client, user_id=user_id, gift_id=gift_id, callback_query=query)


@Client.on_callback_query(filters.regex(r"^delgift_cb_"))
async def del_gift_cb_handler(client: Client, query: CallbackQuery):
    """Admin callback to revoke gift campaign."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied: Admin privileges required.", show_alert=True)
    gid = query.data.split("delgift_cb_")[1]
    from database.gifts import delete_gift
    ok = await delete_gift(gid)
    if ok:
        await query.answer("🗑️ Gift campaign revoked successfully!", show_alert=True)
        try:
            await query.message.edit_text(f"🗑️ <b>Gift campaign <code>{gid}</code> has been revoked and stopped!</b>")
        except Exception:
            pass
    else:
        await query.answer("❌ Failed to revoke gift.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^gift_info_"))
async def gift_info_cb_handler(client: Client, query: CallbackQuery):
    """Admin callback to inspect specific gift details."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied: Admin privileges required.", show_alert=True)
    gid = query.data.split("gift_info_")[1]
    from database.gifts import get_gift
    gift = await get_gift(gid)
    if not gift:
        return await query.answer("❌ Gift not found.", show_alert=True)

    claimed = gift.get("claimed_count", 0)
    max_c = gift.get("max_claims", 0)
    views = gift.get("views_count", 0)
    active = gift.get("is_active", False)
    status_str = "🟢 Active" if active else "🔴 Inactive / Expired"

    bot_uname = client.me.username if client.me else Config.BOT_USERNAME
    link = f"https://t.me/{bot_uname}?start=gift_{gid}"

    text = (
        f"🎁 <b>GIFT REWARD #{gid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Title:</b> <code>{html.escape(gift.get('title', 'Gift'))}</code>\n"
        f"• <b>Status:</b> {status_str}\n"
        f"• <b>Claimed:</b> <code>{claimed} / {max_c if max_c else '∞'} Users</code>\n"
        f"• <b>Re-Downloads:</b> <code>{gift.get('redownloads_count', 0):,} Times</code>\n"
        f"• <b>Views:</b> <code>{views:,} Views</code>\n"
        f"• <b>Mode:</b> <code>{'Hybrid (Re-download Allowed)' if gift.get('allow_reclaim', True) else 'Strict (1-Claim Only)'}</code>\n"
        f"• <b>VIP Only:</b> <code>{'Yes' if gift.get('is_vip_only') else 'No'}</code>\n"
        f"• <b>Shortener:</b> <code>{'Yes' if gift.get('require_shortener') else 'No'}</code>\n"
        f"• <b>Channels:</b> <code>{', '.join(gift.get('channels', [])) or 'None'}</code>\n"
        f"• <b>Link:</b> <code>{link}</code>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Revoke Gift", callback_data=f"delgift_cb_{gid}")]
    ])
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass
    await query.answer()
