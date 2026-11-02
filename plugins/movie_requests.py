import logging
import datetime
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from utils.helpers import is_private_chat
from database.requests import (
    create_movie_request,
    get_movie_request,
    update_movie_request_status
)

logger = logging.getLogger(__name__)

async def dispatch_request_to_admin(
    client: Client,
    req_id: str,
    user_id: int,
    user_name: str,
    username: str,
    movie_name: str,
    chat_title: str
):
    """Forward a new movie request ticket to the Log Channel and Admins."""
    user_mention = f"[{user_name}](tg://user?id={user_id})"
    uname_str = f"@{username}" if username else "No username"

    from database.users import is_premium
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if is_vip:
        header_text = "📩 <b><u>#VIP_REQUEST Ticket [HIGH PRIORITY ⭐]</u></b>\n\n"
        vip_line = "💎 <b>Membership:</b> <code>VIP MEMBER 👑 (High Priority)</code>\n"
    else:
        header_text = "📩 <b>#MovieRequest Ticket</b>\n\n"
        vip_line = "👤 <b>Membership:</b> <code>Standard User</code>\n"

    ticket_text = (
        f"{header_text}"
        f"🎬 <b>Movie / Series:</b> <code>{movie_name}</code>\n"
        f"👤 <b>Requested By:</b> {user_mention} ({uname_str})\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"{vip_line}"
        f"💬 <b>Source:</b> <code>{chat_title}</code>\n"
        f"⏳ <b>Status:</b> <code>Pending Review 🟡</code>\n"
        f"📅 <b>Date:</b> {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        "👇 _Admins: Tap below once the movie has been uploaded or if unavailable:_"
    )
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Mark Uploaded", callback_data=f"reqappr_{req_id}"),
            InlineKeyboardButton("❌ Reject / Unavailable", callback_data=f"reqrej_{req_id}")
        ]
    ])

    targets = []
    if Config.LOG_CHANNEL:
        targets.append(Config.LOG_CHANNEL)
    if Config.ADMINS:
        for a in Config.ADMINS:
            if a not in targets:
                targets.append(a)

    for target in targets:
        try:
            sent = await client.send_message(chat_id=target, text=ticket_text, reply_markup=markup)
            if sent and target == Config.LOG_CHANNEL:
                from database.requests import record_log_message_for_request
                await record_log_message_for_request(req_id, target, sent.id)
        except Exception as e:
            logger.debug(f"Could not dispatch ticket to {target}: {e}")


# 1. /request <movie_name> or /req <movie_name> Command
@Client.on_message(filters.command(["request", "req"]))
async def request_movie_command(client: Client, message: Message):
    """Submit a request for an unindexed movie or series."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text(
            "⚠️ **Usage:** `/request [movie or series name]`\n\n"
            "**Example:** `/request Inception 2010`"
        )
        return

    movie_query = args[1].strip()
    user = message.from_user
    user_id = user.id if user else message.chat.id
    user_name = user.first_name if user else "User"
    username = user.username if user else ""
    chat_title = "Private PM" if is_private_chat(message) else message.chat.title

    success, req_id, msg = await create_movie_request(
        user_id=user_id,
        user_name=user_name,
        username=username,
        movie_name=movie_query,
        chat_title=chat_title
    )

    if not success:
        await message.reply_text(f"⚠️ {msg}")
        return

    # Dispatch ticket to Log Channel
    await dispatch_request_to_admin(
        client=client,
        req_id=req_id,
        user_id=user_id,
        user_name=user_name,
        username=username,
        movie_name=movie_query,
        chat_title=chat_title
    )

    from database.users import is_premium
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    vip_note = "\n👑 <b>VIP Priority Active:</b> Your request is marked with High Priority in our Admin queue!\n" if is_vip else ""

    reply_text = (
        "✅ <b>Movie Request Submitted!</b>\n\n"
        f"🎬 <b>Title:</b> <code>{movie_query}</code>\n"
        f"🎟️ <b>Ticket ID:</b> <code>#{req_id}</code>\n"
        f"{vip_note}\n"
        "Your request has been forwarded to our Admin team.\n"
        "🔔 <b>You will receive an automated notification here as soon as it is uploaded to our channel!</b>"
    )
    await message.reply_text(reply_text)


# 2. Callback for 1-click Request Button from "No Results Found" card
@Client.on_callback_query(filters.regex(r"^reqmovie_"))
async def request_movie_callback(client: Client, query: CallbackQuery):
    """Handle 1-click movie request from search results."""
    movie_query = query.data.split("reqmovie_")[1].strip()
    user = query.from_user
    user_id = user.id
    user_name = user.first_name
    username = user.username or ""
    chat_title = "Private PM" if is_private_chat(query) else query.message.chat.title

    success, req_id, msg = await create_movie_request(
        user_id=user_id,
        user_name=user_name,
        username=username,
        movie_name=movie_query,
        chat_title=chat_title
    )

    if not success:
        await query.answer(f"⚠️ {msg}", show_alert=True)
        return

    # Dispatch to Admin/Log Channel
    await dispatch_request_to_admin(
        client=client,
        req_id=req_id,
        user_id=user_id,
        user_name=user_name,
        username=username,
        movie_name=movie_query,
        chat_title=chat_title
    )

    await query.answer("✅ Request submitted! You will be notified when uploaded.", show_alert=True)
    try:
        await query.message.reply_text(
            f"✅ **Request Registered!**\n"
            f"Your request for `{movie_query}` (#{req_id}) has been forwarded to Admins."
        )
    except Exception:
        pass


# 3. Admin Approval: reqappr_{req_id}
@Client.on_callback_query(filters.regex(r"^reqappr_"))
async def approve_request_callback(client: Client, query: CallbackQuery):
    """Admin marks request as uploaded and triggers automated user notification."""
    if not Config.is_admin(query.from_user.id):
        await query.answer("⛔ Only Bot Admins can approve movie requests!", show_alert=True)
        return

    req_id = query.data.split("reqappr_")[1]
    req_doc = await get_movie_request(req_id)
    if not req_doc:
        await query.answer("❌ Request ticket not found in database.", show_alert=True)
        return

    admin_name = query.from_user.first_name
    await update_movie_request_status(req_id, "uploaded", admin_name)

    # Edit log message
    updated_caption = (
        f"{query.message.text or query.message.caption}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ **STATUS: UPLOADED TO DATABASE**\n"
        f"👤 **Resolved By:** {admin_name}\n"
        f"🔔 **User notified automatically in PM!**"
    )
    try:
        await query.message.edit_text(updated_caption, reply_markup=None)
    except Exception:
        pass

    await query.answer("✅ Request marked as Uploaded! User notified.", show_alert=False)

    # Notify requesting user in PM
    target_user_id = req_doc["user_id"]
    movie_name = req_doc["movie_name"]
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    clean_slug = movie_name.replace(" ", "_")[:30]

    user_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔍 Search '{movie_name[:25]}'", url=f"https://t.me/{bot_username}?start=search_{clean_slug}")]
    ])
    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 **GREAT NEWS! YOUR REQUEST IS READY!** 🎉\n\n"
                f"🎬 **Title:** `{movie_name}`\n\n"
                "Your requested movie/series has been added to our database!\n"
                "👇 Click the button below to download your file instantly:"
            ),
            reply_markup=user_markup
        )
    except Exception as e:
        logger.debug(f"Could not deliver upload notification to user {target_user_id}: {e}")


# 4. Admin Rejection: reqrej_{req_id}
@Client.on_callback_query(filters.regex(r"^reqrej_"))
async def reject_request_callback(client: Client, query: CallbackQuery):
    """Admin marks request as rejected / unavailable."""
    if not Config.is_admin(query.from_user.id):
        await query.answer("⛔ Only Bot Admins can reject requests!", show_alert=True)
        return

    req_id = query.data.split("reqrej_")[1]
    req_doc = await get_movie_request(req_id)
    if not req_doc:
        await query.answer("❌ Request ticket not found in database.", show_alert=True)
        return

    admin_name = query.from_user.first_name
    await update_movie_request_status(req_id, "rejected", admin_name)

    updated_caption = (
        f"{query.message.text or query.message.caption}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"❌ **STATUS: REJECTED / UNAVAILABLE**\n"
        f"👤 **Marked By:** {admin_name}"
    )
    try:
        await query.message.edit_text(updated_caption, reply_markup=None)
    except Exception:
        pass

    await query.answer("❌ Request marked as Unavailable.", show_alert=False)

    # Notify user in PM
    target_user_id = req_doc["user_id"]
    movie_name = req_doc["movie_name"]
    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "⚠️ **MOVIE REQUEST UPDATE** ⚠️\n\n"
                f"🎬 **Movie:** `{movie_name}`\n\n"
                "Sorry! We could not fulfill this request at the moment (e.g. not released on OTT yet, only poor CAM prints available, or unavailable).\n"
                "Please check back later or request another title!"
            )
        )
    except Exception as e:
        logger.debug(f"Could not notify user {target_user_id} of rejection: {e}")


async def auto_notify_pending_requesters(client: Client, media_info: dict):
    """Automatically notify users in PM when their requested movie is indexed in channel."""
    file_name = media_info.get("file_name", "")
    f_unique_id = media_info.get("file_unique_id", "")
    f_size = media_info.get("file_size", 0)

    from database.requests import find_and_resolve_pending_requests
    from utils.helpers import get_readable_size, format_clean_title

    matched_requests = await find_and_resolve_pending_requests(file_name)
    if not matched_requests:
        return

    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    size_str = get_readable_size(f_size)
    clean_display = format_clean_title(file_name)

    for req in matched_requests:
        user_id = req.get("user_id")
        movie_title = req.get("movie_name", "Movie")
        import urllib.parse
        clean_slug = urllib.parse.quote(movie_title[:25].strip().replace(" ", "_"))

        buttons = [
            [
                InlineKeyboardButton("📥 Download Movie Now", url=f"https://t.me/{bot_username}?start=file_{f_unique_id}")
            ]
        ]
        if Config.ENABLE_STREAMING:
            buttons.append([
                InlineKeyboardButton("⚡ Stream & Watch Online ↗️", url=f"https://t.me/{bot_username}?start=stream_{f_unique_id}")
            ])
        buttons.append([
            InlineKeyboardButton(f"🔍 Search All Prints of '{movie_title[:20]}'", url=f"https://t.me/{bot_username}?start=search_{clean_slug}")
        ])

        markup = InlineKeyboardMarkup(buttons)
        notify_text = (
            "🎉 <b>GREAT NEWS! YOUR REQUESTED MOVIE IS UPLOADED!</b> 🎉\n"
            "────────────────────────\n"
            f"🎬 <b>You Requested:</b> <code>{movie_title}</code>\n"
            f"📁 <b>Uploaded File:</b> <code>{clean_display}</code>\n"
            f"💾 <b>File Size:</b> <code>{size_str}</code>\n"
            "────────────────────────\n\n"
            "👇 <i>Tap a button below to download or stream your movie right now:</i>"
        )

        try:
            await client.send_message(
                chat_id=user_id,
                text=notify_text,
                reply_markup=markup,
                disable_web_page_preview=True
            )
            logger.info(f"Auto-notified user {user_id} for requested movie: {movie_title}")
        except Exception as e:
            logger.debug(f"Failed to auto-notify user {user_id}: {e}")

        # Update log ticket in Log Channel if available
        log_chat_id = req.get("log_chat_id")
        log_msg_id = req.get("log_msg_id")
        if log_chat_id and log_msg_id:
            try:
                resolved_text = (
                    "📩 <b>#MovieRequest Ticket (RESOLVED)</b>\n\n"
                    f"🎬 <b>Movie / Series:</b> <code>{movie_title}</code>\n"
                    f"👤 <b>Requested By:</b> <code>{user_id}</code>\n"
                    f"📁 <b>Matched File:</b> <code>{clean_display}</code>\n"
                    f"✅ <b>Status:</b> <code>Auto-Resolved & User Notified in PM! 🟢</code>"
                )
                await client.edit_message_text(
                    chat_id=log_chat_id,
                    message_id=log_msg_id,
                    text=resolved_text
                )
            except Exception:
                pass
