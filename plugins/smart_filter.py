import math
import logging
from html import escape as html_escape

try:
    from hydrogram import Client, filters
    from hydrogram.types import CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import CallbackQuery

from config import Config
from database.files import get_search_results, count_files
from utils.helpers import build_filter_buttons, format_search_results_text, is_private_chat
from utils.smart_nav import (
    create_nav_session,
    get_nav_session,
    update_nav_session,
    build_navigator_root_view,
    build_season_picker_view,
    build_season_options_view,
    build_episode_grid_view,
    build_movie_filter_view,
    build_filtered_results_view
)

logger = logging.getLogger("autofilter.smart_filter")


@Client.on_callback_query(filters.regex(r"^snav:"))
async def smart_nav_callback_handler(client: Client, query: CallbackQuery):
    """Central callback router for R2-style Smart Interactive Navigator."""
    data = query.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    # 1. Initialize Navigator from main results button [ 🔍 Filter Results ]
    if action == "init":
        # Data format: snav:init:<query_str_or_sid>
        raw_target = ":".join(parts[2:])
        # Check if existing session or new query string
        sess = get_nav_session(raw_target)
        if sess:
            sid = raw_target
            # Reset any previously applied filters in session
            update_nav_session(sid, media_type=None, season=None, mode=None, episode=None, language=None, quality=None, page=1)
        else:
            bot_uname = client.me.username if client.me else Config.BOT_USERNAME
            is_pm = is_private_chat(query)
            sid = create_nav_session(
                query=raw_target,
                user_id=query.from_user.id,
                chat_id=query.message.chat.id,
                is_pm=is_pm,
                bot_username=bot_uname
            )

        text, markup = await build_navigator_root_view(sid)
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception as e:
            logger.debug(f"Error editing message for snav init: {e}")
        await query.answer()
        return

    # For subsequent steps, parts[2] is always the sid
    sid = parts[2] if len(parts) > 2 else ""
    sess = get_nav_session(sid)
    if not sess:
        import re
        msg_text = query.message.text or query.message.caption or ""
        q_match = re.search(r"(?:Title|Series|Query)\s*:\s*`?([^`\n]+)`?", msg_text, re.I)
        if q_match:
            raw_match = q_match.group(1).strip()
            # Cleanly strip HTML tags like </b>, <code>, </code> and backticks
            recovered_q = re.sub(r"<[^>]+>", "", raw_match).replace("`", "").strip()
            if recovered_q:
                bot_uname = client.me.username if client.me else Config.BOT_USERNAME
                is_pm = is_private_chat(query)
                new_sid = create_nav_session(
                    query=recovered_q,
                    user_id=query.from_user.id,
                    chat_id=query.message.chat.id,
                    is_pm=is_pm,
                    bot_username=bot_uname
                )
                # Re-render root view with restored session
                text, markup = await build_navigator_root_view(new_sid)
                try:
                    await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
                except Exception:
                    pass
                await query.answer("🔄 Session restored!")
                return
        await query.answer("⚠️ Session expired. Please search again.", show_alert=True)
        return

    # Security / authorization check (only requester can use the filter)
    req_uid = sess.get("user_id")
    if req_uid and req_uid != query.from_user.id and not Config.is_admin(query.from_user.id):
        await query.answer("⚠️ This search was requested by another user.", show_alert=True)
        return

    # 2. Type Branch: Movies vs Series
    if action == "type":
        # Data: snav:type:<sid>:<m|s>
        m_type = parts[3] if len(parts) > 3 else "m"
        if m_type == "s":
            update_nav_session(sid, media_type="series", season=None, mode=None, episode=None)
            text, markup = await build_season_picker_view(sid)
        else:
            update_nav_session(sid, media_type="movie", language=None, quality=None)
            text, markup = await build_movie_filter_view(sid)

        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    # 3. Season Selection
    if action == "seas":
        # Data: snav:seas:<sid>:<season_num>
        season_num = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        update_nav_session(sid, media_type="series", season=season_num, mode=None, episode=None)
        text, markup = await build_season_options_view(sid, season_num)
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    # 4. Season Mode Selection (Complete Pack vs Episode Wise)
    if action == "smode":
        # Data: snav:smode:<sid>:<season_num>:<pack|ep>
        season_num = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        mode_val = parts[4] if len(parts) > 4 else "pack"

        if mode_val == "pack":
            update_nav_session(sid, media_type="series", season=season_num, mode="pack", episode=None, page=1)
            text, markup = await build_filtered_results_view(sid, page=1)
        else:
            update_nav_session(sid, media_type="series", season=season_num, mode="episode", episode=None, ep_page=1)
            text, markup = await build_episode_grid_view(sid, season_num, page=1)

        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()
        return

    # 5. Episode Grid Pagination
    if action == "epgrid":
        # Data: snav:epgrid:<sid>:<season_num>:<page>
        season_num = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        page = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
        update_nav_session(sid, ep_page=page)
        text, markup = await build_episode_grid_view(sid, season_num, page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    # 6. Specific Episode Selection
    if action == "ep":
        # Data: snav:ep:<sid>:<season_num>:<ep_num>
        season_num = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        ep_num = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
        update_nav_session(sid, media_type="series", season=season_num, mode="episode", episode=ep_num, page=1)
        text, markup = await build_filtered_results_view(sid, page=1)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()
        return

    # 7. Movie Language Toggle/Select
    if action == "mlang":
        # Data: snav:mlang:<sid>:<lang>
        lang_val = parts[3] if len(parts) > 3 else None
        curr = sess.get("language")
        new_lang = None if curr == lang_val else lang_val
        update_nav_session(sid, language=new_lang)
        text, markup = await build_movie_filter_view(sid)
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    # 8. Movie Quality Toggle/Select
    if action == "mqual":
        # Data: snav:mqual:<sid>:<qual>
        qual_val = parts[3] if len(parts) > 3 else None
        curr = sess.get("quality")
        new_qual = None if curr == qual_val else qual_val
        update_nav_session(sid, quality=new_qual)
        text, markup = await build_movie_filter_view(sid)
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    # 9. Movie Show Filtered Results
    if action == "mresults":
        # Data: snav:mresults:<sid>
        update_nav_session(sid, media_type="movie", page=1)
        text, markup = await build_filtered_results_view(sid, page=1)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()
        return

    # 10. Filtered Results Pagination
    if action == "rpage":
        # Data: snav:rpage:<sid>:<page>
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        update_nav_session(sid, page=page)
        text, markup = await build_filtered_results_view(sid, page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()
        return

    # 11. Return to Main Unfiltered Search Results
    if action in ("back_res", "clear"):
        # Reset all filters
        clean_q = sess["query"]
        bot_uname = sess.get("bot_username") or (client.me.username if client.me else Config.BOT_USERNAME)
        is_pm = sess.get("is_pm", True)
        u_name = query.from_user.first_name or "User"
        u_mention = query.from_user.mention(u_name)

        total_files = await count_files(clean_q)
        results = await get_search_results(clean_q, offset=0, limit=10)
        total_pages = math.ceil(total_files / 10) if total_files > 0 else 1

        reply_markup = build_filter_buttons(
            results=results,
            page=1,
            total_pages=total_pages,
            query=clean_q,
            bot_username=bot_uname,
            is_pm=is_pm
        )

        sponsor_ad = None
        u_id = query.from_user.id if query.from_user else 0
        if u_id:
            try:
                from database.users import is_premium
                from database.ads import get_active_sponsor_ad
                if not await is_premium(u_id):
                    sponsor_ad = await get_active_sponsor_ad()
            except Exception as e:
                logger.debug(f"Error fetching sponsor ad for smart filter clear: {e}")

        content_text = format_search_results_text(
            results=results,
            query=clean_q,
            total_files=total_files,
            bot_username=bot_uname,
            user_mention=u_mention,
            page=1,
            total_pages=total_pages,
            sponsor_ad=sponsor_ad
        )

        try:
            await query.message.edit_text(content_text, reply_markup=reply_markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer("All filters cleared!" if action == "clear" else "")
        return

    await query.answer()
