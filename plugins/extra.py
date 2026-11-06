import re
import logging
import datetime
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto

from config import Config
from database.users import add_premium, get_user_info, is_premium
from utils.imdb import get_imdb_details
from utils.helpers import get_readable_size, get_random_start_pic, is_private_chat

logger = logging.getLogger(__name__)

# State cache for users submitting payment proofs: {user_id: "plan_key"}
AWAITING_PAYMENT_PROOF = {}

VIP_PLANS = {
    "7d": {"name": "7 Days", "days": 7, "price": "₹19", "usd": "$0.25", "note": "Try Premium"},
    "15d": {"name": "15 Days", "days": 15, "price": "₹39", "usd": "$0.5", "note": "Two-week pass"},
    "30d": {"name": "30 Days (1 Month)", "days": 30, "price": "₹69", "usd": "$0.9", "note": "Most Popular ⭐"},
    "60d": {"name": "60 Days (2 Months)", "days": 60, "price": "₹119", "usd": "$1.5", "note": "Best Value"},
    "180d": {"name": "6 Months", "days": 180, "price": "₹249", "usd": "$3.0", "note": "Super Saver"},
    "365d": {"name": "1 Year (365 Days)", "days": 365, "price": "₹499", "usd": "$6.0", "note": "Full-Year Access 👑"}
}

def get_plans_text() -> str:
    return (
        "👑 <b><u>AKMOVIEVERSE VIP PREMIUM PASS</u></b> 👑\n"
        "<i>Scan QR to pay with GPay / PhonePe / Paytm / Any UPI</i>\n\n"
        "🌟 <b>VIP Exclusive Privileges:</b>\n"
        "• 🚫 <b>100% Ad-Free:</b> Zero shortener links or tokens\n"
        "• ⚡ <b>SEND ALL Unlocked:</b> 1-Tap full season delivery\n"
        "• ⏳ <b>30-Min Safe Time:</b> 6x longer before auto-delete (Free: 5m)\n"
        "• 🔥 <b>Priority Requests:</b> Admin fast-track uploads\n"
        "• 📥 <b>Web Cinema Player:</b> Direct offline downloads\n\n"
        "💎 <b>VIP Pricing Plans:</b>\n"
        "• 🥉 <b>7 Days:</b> ₹19  |  🥈 <b>15 Days:</b> ₹39\n"
        "• 🥇 <b>30 Days:</b> ₹69 ⭐  |  ⚡ <b>60 Days:</b> ₹119\n"
        "• ⭐ <b>6 Months:</b> ₹249  |  👑 <b>1 Year:</b> ₹499\n\n"
        "👇 <b>Tap below to select your plan & activate:</b>"
    )

def get_plans_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🥉 7 Days • ₹19", callback_data="buyplan_7d"),
            InlineKeyboardButton("🥈 15 Days • ₹39", callback_data="buyplan_15d")
        ],
        [
            InlineKeyboardButton("🥇 30 Days • ₹69 ⭐", callback_data="buyplan_30d"),
            InlineKeyboardButton("⚡ 60 Days • ₹119", callback_data="buyplan_60d")
        ],
        [
            InlineKeyboardButton("⭐ 6 Months • ₹249", callback_data="buyplan_180d"),
            InlineKeyboardButton("👑 1 Year • ₹499", callback_data="buyplan_365d")
        ],
        [
            InlineKeyboardButton("🌐 USDT / Crypto", callback_data="buyplan_crypto"),
            InlineKeyboardButton("👥 Refer & Earn Free", callback_data="view_refer")
        ],
        [
            InlineKeyboardButton("💬 VIP Support (@AK_ownerbot)", url=Config.SUPPORT_URL)
        ],
        [
            InlineKeyboardButton("◀️ Back to Home", callback_data="back_home")
        ]
    ])

# /id Command
# /id Command
@Client.on_message(filters.command("id"))
async def id_command_handler(client: Client, message: Message):
    """Retrieve Telegram IDs for user, chat, replied message, or media."""
    chat = message.chat
    reply = message.reply_to_message

    user_id = message.from_user.id if message.from_user else (message.sender_chat.id if message.sender_chat else "Anonymous")
    text = f"👤 <b>Your ID:</b> <code>{user_id}</code>\n"
    text += f"💬 <b>Chat ID:</b> <code>{chat.id}</code>\n"
    if not is_private_chat(chat):
        text += f"🏷️ <b>Chat Type:</b> <code>{chat.type}</code>\n"

    if reply:
        if reply.from_user:
            text += f"↩️ <b>Replied User ID:</b> <code>{reply.from_user.id}</code>\n"
        elif reply.sender_chat:
            text += f"📢 <b>Replied Channel/Chat ID:</b> <code>{reply.sender_chat.id}</code>\n"
        if reply.forward_from_chat:
            text += f"📢 <b>Forwarded Channel ID:</b> <code>{reply.forward_from_chat.id}</code>\n"
        media = reply.document or reply.video or reply.audio or reply.photo
        if media:
            file_id = getattr(media, "file_id", "N/A")
            unique_id = getattr(media, "file_unique_id", "N/A")
            text += f"\n📁 <b>File Unique ID:</b> <code>{unique_id}</code>\n"
            text += f"🔑 <b>File ID:</b> <code>{file_id}</code>\n"

    await message.reply_text(text)


# /info Command
@Client.on_message(filters.command("info"))
async def info_command_handler(client: Client, message: Message):
    """Retrieve detailed technical metadata about user or replied media."""
    reply = message.reply_to_message
    if reply and (reply.document or reply.video or reply.audio):
        media = reply.document or reply.video or reply.audio
        file_name = getattr(media, "file_name", "N/A")
        file_size = get_readable_size(getattr(media, "file_size", 0))
        mime = getattr(media, "mime_type", "N/A")
        duration = getattr(media, "duration", "N/A")
        dc_id = getattr(media, "dc_id", "N/A")

        text = (
            f"ℹ️ <b>Media Information:</b>\n\n"
            f"📄 <b>Name:</b> <code>{file_name}</code>\n"
            f"📦 <b>Size:</b> <code>{file_size}</code>\n"
            f"🏷️ <b>MIME:</b> <code>{mime}</code>\n"
            f"⏱️ <b>Duration:</b> <code>{duration}s</code>\n"
            f"🌐 <b>Data Center (DC):</b> <code>{dc_id}</code>\n"
            f"🔑 <b>Unique ID:</b> <code>{getattr(media, 'file_unique_id', 'N/A')}</code>"
        )
        await message.reply_text(text)
        return

    target_user = reply.from_user if (reply and reply.from_user) else message.from_user
    if not target_user:
        if reply and reply.sender_chat:
            await message.reply_text(
                f"📢 <b>Channel / Group Profile:</b>\n\n"
                f"• <b>Title:</b> <code>{reply.sender_chat.title}</code>\n"
                f"• <b>ID:</b> <code>{reply.sender_chat.id}</code>\n"
                f"• <b>Username:</b> @{reply.sender_chat.username or 'None'}"
            )
            return
        await message.reply_text("❌ Could not determine user profile.")
        return

    full_name = f"{target_user.first_name} {target_user.last_name or ''}".strip()
    uname_str = f"@{target_user.username}" if target_user.username else "No username"
    mention_url = f"tg://user?id={target_user.id}"
    dc_val = target_user.dc_id if target_user.dc_id else "Unknown"

    text = (
        "👤 <b>User Profile Information</b>\n"
        "────────────────────────\n"
        f"• <b>Full Name:</b> <code>{full_name}</code>\n"
        f"• <b>User ID:</b> <code>{target_user.id}</code>\n"
        f"• <b>Username:</b> {uname_str}\n"
        f"• <b>Data Center (DC):</b> <code>DC-{dc_val}</code>\n"
        f"• <b>Permanent Link:</b> <a href=\"{mention_url}\">Click to View Profile</a>\n"
        f"• <b>Is Bot:</b> <code>{'Yes' if target_user.is_bot else 'No'}</code>\n"
        "────────────────────────"
    )

    import urllib.parse
    profile_link = f"https://t.me/{target_user.username}" if target_user.username else f"tg://user?id={target_user.id}"
    share_payload = (
        f"👤 User Profile:\n"
        f"• Name: {full_name}\n"
        f"• Profile Link: {profile_link}\n"
        f"• ID: {target_user.id}\n"
        f"• Username: {uname_str}\n"
        f"• DC: DC-{dc_val}"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(profile_link)}&text={urllib.parse.quote(share_payload)}"
    profile_btn_url = profile_link

    buttons = [
        [
            InlineKeyboardButton("📤 Share Details", url=share_url),
            InlineKeyboardButton("👤 View Profile ↗️", url=profile_btn_url)
        ]
    ]
    markup = InlineKeyboardMarkup(buttons)

    # Attempt to fetch profile photo
    try:
        photos = [p async for p in client.get_chat_photos(target_user.id, limit=1)]
        if photos and photos[0].file_id:
            await client.send_photo(
                chat_id=message.chat.id,
                photo=photos[0].file_id,
                caption=text,
                reply_markup=markup
            )
            return
    except Exception as photo_err:
        logger.debug(f"Could not fetch profile photo for {target_user.id}: {photo_err}")

    await message.reply_text(text, reply_markup=markup)


# /imdb <movie_name> Command
@Client.on_message(filters.command("imdb"))
async def imdb_lookup_command(client: Client, message: Message):
    """Direct lookup of movie or series details from IMDb."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/imdb [movie or series name]</code>\nExample: <code>/imdb Inception</code>")
        return

    query = args[1]
    wait_msg = await message.reply_text("🔎 <b>Searching IMDb...</b>")

    imdb_data = await get_imdb_details(query)
    if not imdb_data:
        await wait_msg.edit_text(f"❌ No IMDb results found for: <code>{query}</code>")
        return

    caption = (
        f"🎬 <b>{imdb_data['title']} ({imdb_data['year']})</b>\n\n"
        f"🌟 <b>Rating:</b> <code>{imdb_data['rating']}</code>\n"
        f"🎭 <b>Type:</b> <code>{imdb_data['genres']}</code>\n"
        f"👥 <b>Cast:</b> <code>{imdb_data['cast']}</code>\n\n"
        f"⚡ <i>Powered by Auto Filter Bot</i>"
    )

    import urllib.parse
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    raw_title = imdb_data["title"]
    clean_search_str = re.sub(r"[^\w\s]", " ", raw_title).strip()
    encoded_search = urllib.parse.quote_plus(clean_search_str)

    cb_words = []
    curr_len = 0
    for w in clean_search_str.split():
        if curr_len + len(w) + 1 <= 45:
            cb_words.append(w)
            curr_len += len(w) + 1
        else:
            break
    cb_q = " ".join(cb_words) if cb_words else clean_search_str[:45]

    # In PM: Direct 1-click callback so search runs instantly without re-routing or START buttons!
    # In Groups: Deep-link URL to PM
    if is_private_chat(message):
        imdb_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔍 Search '{raw_title[:24]}' in Bot", callback_data=f"imdbsearch_{cb_q}")]
        ])
    else:
        imdb_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔍 Search '{raw_title[:24]}' in Bot ↗️", url=f"https://t.me/{bot_username}?start=filter_{encoded_search}")]
        ])

    await wait_msg.delete()
    if imdb_data.get("poster"):
        try:
            await message.reply_photo(photo=imdb_data["poster"], caption=caption, reply_markup=imdb_markup)
            return
        except Exception:
            pass

    await message.reply_text(caption, reply_markup=imdb_markup)


@Client.on_callback_query(filters.regex(r"^imdbsearch_(.+)"))
async def imdb_search_callback_handler(client: Client, query: CallbackQuery):
    """Direct 1-click search from /imdb result in PM."""
    search_q = query.matches[0].group(1).strip()
    await query.answer(f"🔍 Searching: {search_q}...")
    from plugins.autofilter import group_auto_filter_handler
    query.message.text = search_q
    query.message.from_user = query.from_user
    await group_auto_filter_handler(client, query.message)


# /help Command
@Client.on_message(filters.command("help"))
async def help_command_handler(client: Client, message: Message):
    """Display comprehensive help guide and commands."""
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    if not is_private_chat(message):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 VIEW HELP GUIDE IN PM ↗️", url=f"https://t.me/{bot_username}?start=help")]
        ])
        await message.reply_text(
            "❓ <b>Auto Filter Bot — Help & Commands</b>\n\n"
            "• Search movies/series by typing the title directly in chat\n"
            "• Use sub-filters for Quality, Language, and Seasons\n"
            "• Use <code>/settings</code> to configure group preferences\n\n"
            "👉 Tap below to view the complete guide in PM:",
            reply_markup=markup
        )
        return

    # If invoked by Bot Administrator, display rich interactive Admin Hub
    if message.from_user and Config.is_admin(message.from_user.id):
        from plugins.admin_help import send_admin_help_hub
        await send_admin_help_hub(client, message)
        return

    text = (
        "❓ <b><u>Auto Filter Bot — Help & Commands</u></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔍 <b>Search Files:</b> Just type any movie or series title in chat or group!\n"
        "🎬 <b>Online Streaming:</b> Use <code>/watch &lt;name&gt;</code> to stream movies in 4K/1080p\n"
        "📦 <b>File Store & Batches:</b>\n"
        "  • <code>/batch</code> — Create 1-click batch download packs in PM\n"
        "  • <code>/genlink</code> — Reply to any file/video for an instant shareable link\n"
        "  • <code>/batches</code> — View and manage your saved batch packs\n"
        "🚀 <b>Media CDN & Telegraph:</b>\n"
        "  • <code>/tgm</code> — Reply to image/sticker/GIF for direct CDN link\n"
        "  • <code>/paste</code> — Publish text/notes to Telegraph Instant View\n"
        "  • <code>/editpaste</code> — Edit Telegraph article (URL stays unchanged)\n"
        "  • <code>/delpaste</code> — Wipe content of Telegraph article\n"
        "💎 <b>VIP & Ad-Free:</b> Use <code>/plans</code> to unlock unlimited fast downloads\n"
        "👥 <b>Group Settings:</b> Send <code>/connect</code> in group, then manage via <code>/settings</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎟️ VIP Plans", callback_data="view_plans")],
        [InlineKeyboardButton("📖 About", callback_data="about_menu"), InlineKeyboardButton("⬅️ Back to Home", callback_data="back_home")]
    ])
    await message.reply_text(text, reply_markup=markup)


# Help & About Callbacks
@Client.on_callback_query(filters.regex(r"^help_menu"))
async def help_menu_callback(client: Client, query: CallbackQuery):
    if Config.is_admin(query.from_user.id):
        from plugins.admin_help import get_hub_text, get_admin_hub_markup
        text = get_hub_text()
        markup = get_admin_hub_markup()
        try:
            if query.message.photo:
                await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
            else:
                await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
        await query.answer()
        return
    text = (
        "❓ <b><u>Auto Filter Bot — Help & Commands</u></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔍 <b>Search Files:</b> Just type any movie or series title in chat or group!\n"
        "🎬 <b>Online Streaming:</b> Use <code>/watch &lt;name&gt;</code> to stream movies in 4K/1080p\n"
        "📦 <b>File Store & Batches:</b>\n"
        "  • <code>/batch</code> — Create 1-click batch download packs in PM\n"
        "  • <code>/genlink</code> — Reply to any file/video for an instant shareable link\n"
        "  • <code>/batches</code> — View and manage your saved batch packs\n"
        "🚀 <b>Media CDN & Telegraph:</b>\n"
        "  • <code>/tgm</code> — Reply to image/sticker/GIF for direct CDN link\n"
        "  • <code>/paste</code> — Publish text/notes to Telegraph Instant View\n"
        "  • <code>/editpaste</code> — Edit Telegraph article (URL stays unchanged)\n"
        "  • <code>/delpaste</code> — Wipe content of Telegraph article\n"
        "💎 <b>VIP & Ad-Free:</b> Use <code>/plans</code> to unlock unlimited fast downloads\n"
        "👥 <b>Group Settings:</b> Send <code>/connect</code> in group, then manage via <code>/settings</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    back_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Home", callback_data="back_home")]
    ])
    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=back_markup)
        else:
            await query.message.edit_text(text, reply_markup=back_markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=back_markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^about_menu"))
async def about_menu_callback(client: Client, query: CallbackQuery):
    text = (
        "ℹ️ <b>About This Bot</b>\n\n"
        "• <b>Engine:</b> Hydrogram (MTProto 2.0)\n"
        "• <b>Database:</b> MongoDB Atlas (Motor Async)\n"
        "• <b>Max File Size:</b> Up to 2GB (4GB for Premium)\n"
        "• <b>Hosting:</b> Koyeb, Heroku, Render, VPS & Docker\n"
        "• <b>Version:</b> v3.0 Pro Ultimate\n\n"
        "Built with ❤️ for high-speed file sharing."
    )
    back_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Home", callback_data="back_home")]
    ])
    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=back_markup)
        else:
            await query.message.edit_text(text, reply_markup=back_markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=back_markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^back_home"))
async def back_home_callback(client: Client, query: CallbackQuery):
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    name = query.from_user.first_name
    welcome_text = (
        f"🚩<i>JAI SHRI RAM</i>🚩\n\n"
        f"HEY <b>{name}</b>!\n\n"
        f"🤖 I AM <b>{bot_username}</b>, THE MOST POWERFUL AUTO FILTER BOT WITH PREMIUM FEATURES."
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{bot_username}?startgroup=true")],
        [
            InlineKeyboardButton("HELP 📢", callback_data="help_menu"),
            InlineKeyboardButton("ABOUT 📖", callback_data="about_menu")
        ],
        [
            InlineKeyboardButton("UPGRADE TO VIP 🎟️", callback_data="view_plans")
        ]
    ])

    start_pic = get_random_start_pic()

    try:
        if query.message.photo:
            if start_pic:
                try:
                    await query.message.edit_media(
                        media=InputMediaPhoto(start_pic, caption=welcome_text),
                        reply_markup=markup
                    )
                    await query.answer()
                    return
                except Exception as e:
                    logger.debug(f"Failed to edit_media in back_home: {e}")
            await query.message.edit_caption(caption=welcome_text, reply_markup=markup)
        else:
            await query.message.edit_text(welcome_text, reply_markup=markup)
    except Exception:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^view_plans"))
async def view_plans_callback(client: Client, query: CallbackQuery):
    text = get_plans_text()
    markup = get_plans_markup()

    try:
        if query.message.photo:
            if Config.UPI_QR_URL:
                try:
                    await query.message.edit_media(
                        media=InputMediaPhoto(Config.UPI_QR_URL, caption=text),
                        reply_markup=markup
                    )
                    await query.answer()
                    return
                except Exception:
                    pass
            await query.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^buyplan_"))
async def buy_plan_callback(client: Client, query: CallbackQuery):
    plan_key = query.data.split("buyplan_")[1]

    if plan_key == "crypto":
        text = (
            "🌐 <b>AKMOVIEVERSE VIP — CRYPTO / USDT TRC-20</b>\n\n"
            "Pay using USDT on the TRC-20 network or Binance Pay.\n\n"
            f"💎 <b>USDT TRC-20 Address:</b> (tap to copy)\n<code>{Config.USDT_TRC20}</code>\n\n"
            "💰 <b>Crypto Pricing Equivalents:</b>\n"
            "• <b>30 Days:</b> 1 USDT\n"
            "• <b>60 Days:</b> 1.5 USDT\n"
            "• <b>6 Months:</b> 3 USDT\n"
            "• <b>1 Year (Max):</b> 6 USDT\n\n"
            "📝 <i>After sending the transaction, click 'Send Crypto Proof' below or message @AK_ownerbot with your TXID.</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Send Crypto Proof / TXID", callback_data="proof_start_crypto")],
            [InlineKeyboardButton("💬 Support (@AK_ownerbot)", url=Config.SUPPORT_URL)],
            [InlineKeyboardButton("◀️ Back to Plans", callback_data="view_plans")]
        ])
        try:
            if query.message.photo:
                await query.message.edit_caption(caption=text, reply_markup=markup)
            else:
                await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            await query.message.reply_text(text, reply_markup=markup)
        await query.answer()
        return

    plan = VIP_PLANS.get(plan_key)
    if not plan:
        await query.answer("Plan not found!", show_alert=True)
        return

    text = (
        f"💎 <b>AKMOVIEVERSE VIP — {plan['name'].upper()}</b>\n"
        f"💰 <b>Amount to Pay:</b> <code>{plan['price']}</code> ({plan['usd']})\n\n"
        f"📲 <b>UPI ID:</b> (tap to copy)\n"
        f"<code>{Config.UPI_ID}</code>\n\n"
        f"📝 <b>Easy Steps to Activate:</b>\n"
        f"1. Scan the QR code or pay <b>{plan['price']}</b> to <code>{Config.UPI_ID}</code>.\n"
        f"2. Take a screenshot of the successful transaction.\n"
        f"3. Click <b>'📸 Send Payment Proof'</b> below and upload your screenshot.\n"
        f"4. Your VIP will be verified & activated within minutes!"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Send Payment Proof", callback_data=f"proof_start_{plan_key}")],
        [InlineKeyboardButton("💬 Talk on Telegram", url=Config.SUPPORT_URL)],
        [InlineKeyboardButton("◀️ Back to Plans", callback_data="view_plans")]
    ])

    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=markup)
        else:
            if Config.UPI_QR_URL:
                try:
                    await query.message.delete()
                    await client.send_photo(
                        chat_id=query.message.chat.id,
                        photo=Config.UPI_QR_URL,
                        caption=text,
                        reply_markup=markup
                    )
                except Exception:
                    await query.message.edit_text(text, reply_markup=markup)
            else:
                await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^proof_start_"))
async def proof_start_callback(client: Client, query: CallbackQuery):
    plan_key = query.data.split("proof_start_")[1]
    user_id = query.from_user.id
    AWAITING_PAYMENT_PROOF[user_id] = plan_key

    plan_title = VIP_PLANS.get(plan_key, {}).get("name", "VIP Plan") if plan_key != "crypto" else "Crypto / USDT"
    plan_price = VIP_PLANS.get(plan_key, {}).get("price", "") if plan_key != "crypto" else ""

    text = (
        f"📸 <b>UPLOAD PAYMENT SCREENSHOT FOR {plan_title.upper()} {plan_price}</b>\n\n"
        f"Please send your <b>payment screenshot</b> or transaction receipt right here in this chat.\n\n"
        f"⚠️ <b>Important:</b> Ensure the UTR / Ref No / Transaction ID is clearly readable.\n\n"
        f"<i>Send /cancel anytime to exit.</i>"
    )
    await query.message.reply_text(text)
    await query.answer("Please send your payment screenshot now!", show_alert=False)


@Client.on_message(filters.photo & filters.private)
async def payment_proof_receiver(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in AWAITING_PAYMENT_PROOF:
        return

    plan_key = AWAITING_PAYMENT_PROOF.pop(user_id)
    plan = VIP_PLANS.get(plan_key, {"name": "VIP Plan", "days": 30, "price": "Custom"}) if plan_key != "crypto" else {"name": "Crypto USDT", "days": 30, "price": "USDT"}
    days = plan.get("days", 30)

    user_name = message.from_user.first_name
    user_mention = message.from_user.mention(user_name)
    user_username = f"@{message.from_user.username}" if message.from_user.username else "No Username"

    admin_caption = (
        "📩 <b>NEW VIP PAYMENT PROOF RECEIVED!</b>\n\n"
        f"👤 <b>User:</b> {user_mention} ({user_username})\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📦 <b>Selected Plan:</b> {plan['name']} ({plan['price']})\n"
        f"⏱️ <b>Duration to Grant:</b> <code>{days} Days</code>\n"
        f"📅 <b>Submitted:</b> {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        "👇 <i>Click below to approve and automatically activate VIP for this user:</i>"
    )
    admin_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Approve ({days} Days)", callback_data=f"vipappr_{user_id}_{days}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"viprej_{user_id}")
        ]
    ])

    targets = []
    if Config.LOG_CHANNEL:
        targets.append(Config.LOG_CHANNEL)
    admin_target = Config.ADMINS[0] if Config.ADMINS else None
    if admin_target and admin_target not in targets:
        targets.append(admin_target)

    for target in targets:
        try:
            await client.send_photo(
                chat_id=target,
                photo=message.photo.file_id,
                caption=admin_caption,
                reply_markup=admin_markup
            )
        except Exception as e:
            logger.error(f"Failed to forward proof to {target}: {e}")

    await message.reply_text(
        "✅ <b>Payment Screenshot Received!</b>\n\n"
        "Your receipt has been submitted to Admin for verification.\n"
        "⏱️ Verification usually takes <b>2–5 minutes</b>.\n"
        "You will receive an automated notification as soon as your VIP is activated!\n\n"
        f"💬 For urgent inquiries, contact {Config.SUPPORT_URL}"
    )


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_proof_command(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in AWAITING_PAYMENT_PROOF:
        AWAITING_PAYMENT_PROOF.pop(user_id, None)
        await message.reply_text("❌ <b>Payment proof submission cancelled.</b>")
        try:
            message.stop_propagation()
        except Exception:
            pass
        return
    message.continue_propagation()


@Client.on_callback_query(filters.regex(r"^vipappr_"))
async def vip_approve_callback(client: Client, query: CallbackQuery):
    if not Config.is_admin(query.from_user.id):
        await query.answer("⚠️ Only Bot Admins can approve payments!", show_alert=True)
        return

    parts = query.data.split("_")
    target_user_id = int(parts[1])
    days = int(parts[2])

    seconds = days * 86400
    success = await add_premium(target_user_id, seconds)

    if success:
        admin_name = query.from_user.first_name
        try:
            await query.message.edit_caption(
                caption=(
                    f"{query.message.caption}\n\n"
                    f"✅ <b>APPROVED by {admin_name}</b>\n"
                    f"🎉 <code>{days} Days</code> VIP added to user <code>{target_user_id}</code>!"
                ),
                reply_markup=None
            )
        except Exception:
            pass
        await query.answer(f"✅ Approved {days} days VIP!", show_alert=True)

        try:
            await client.send_message(
                chat_id=target_user_id,
                text=(
                    f"🎉 <b>CONGRATULATIONS! PAYMENT VERIFIED!</b> 🎉\n\n"
                    f"Your <b>AkMovieVerse VIP Premium Membership</b> has been activated for <b>{days} Days</b>!\n\n"
                    f"🌟 <b>Your Active Perks:</b>\n"
                    f"• 🚫 <b>100% Ad-Free:</b> Zero shorteners or waiting time!\n"
                    f"• ⚡ <b>Direct PM Files:</b> Instant file delivery.\n"
                    f"• 🔓 <b>Unlimited Daily Downloads:</b> No limits.\n"
                    f"• 📦 <b>SEND ALL Packages:</b> 1-click batch download.\n\n"
                    f"Enjoy your cinema experience! 🍿"
                )
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id} of approval: {e}")
    else:
        await query.answer("❌ Error activating premium in database.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^viprej_"))
async def vip_reject_callback(client: Client, query: CallbackQuery):
    if not Config.is_admin(query.from_user.id):
        await query.answer("⚠️ Only Bot Admins can reject payments!", show_alert=True)
        return

    target_user_id = int(query.data.split("_")[1])
    admin_name = query.from_user.first_name

    try:
        await query.message.edit_caption(
            caption=(
                f"{query.message.caption}\n\n"
                f"❌ <b>REJECTED by {admin_name}</b>"
            ),
            reply_markup=None
        )
    except Exception:
        pass
    await query.answer("❌ Payment rejected.", show_alert=True)

    try:
        await client.send_message(
            chat_id=target_user_id,
            text=(
                "❌ <b>Payment Verification Unsuccessful</b>\n\n"
                "Your payment proof could not be verified by Admin.\n"
                f"If you believe this is an error, please contact Support directly: {Config.SUPPORT_URL}"
            )
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^view_refer"))
async def view_refer_callback(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    from database.users import get_user_info
    user = await get_user_info(user_id)
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    refer_link = f"https://t.me/{bot_username}?start=refer_{user_id}"

    refer_count = user.get("refer_count", 0)
    rewards_earned = user.get("refer_rewards_earned", 0)
    needed = 5 - (refer_count % 5)
    rem = refer_count % 5
    pct = int((rem / 5) * 100)
    filled = int(rem / 5 * 10)
    progress_bar = f"[{'█' * filled}{'░' * (10 - filled)}] {rem}/5 ({pct}%)"

    text = (
        "👥 <b><u>REFER & EARN FREE VIP ACCESS</u></b> 👥\n\n"
        "Invite your friends and earn <b>1 Day of Free VIP Premium</b> for every 5 friends!\n\n"
        f"📊 <b>Your Referral Performance:</b>\n"
        f"• <b>Total Friends Invited:</b> <code>{refer_count}</code>\n"
        f"• <b>Free VIP Days Earned:</b> <code>{rewards_earned} Days 👑</code>\n"
        f"• <b>Progress:</b> <code>{progress_bar}</code>\n"
        f"• <b>Next Reward:</b> in <code>{needed}</code> more friends!\n\n"
        f"🔗 <b>Your Personal Invite Link:</b>\n"
        f"<code>{refer_link}</code>"
    )

    import urllib.parse
    share_caption = "🍿 Search & download unlimited movies and web series in high quality for free!"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(refer_link)}&text={urllib.parse.quote(share_caption)}"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Link with Friends", url=share_url)],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_home")]
    ])
    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, reply_markup=markup)
    await query.answer()


# --- Time-Based & One-Time Secret File Share Link Generator ---

@Client.on_message(filters.command(["share", "sharefile"]))
async def share_file_command(client: Client, message: Message):
    """Generate time-based or one-time use secret download link for any replied file."""
    if not Config.is_admin(message.from_user.id):
        return

    reply = message.reply_to_message
    media = None
    if reply:
        media = reply.document or reply.video or reply.audio or reply.photo

    if not media:
        await message.reply_text(
            "📦 <b>Time-Based & One-Time File Link Generator:</b>\n\n"
            "<b>How to use:</b>\n"
            "Reply to any file, video, or movie with <code>/share</code>:\n"
            "• <code>/share onetime</code> — 1-Person Single-Use link (Burn after reading! 🔥)\n"
            "• <code>/share 1h</code> — Valid for 1 Hour only\n"
            "• <code>/share 10m onetime</code> — Expires in 10 mins OR after 1 user opens it\n"
            "• <code>/share 24h 5</code> — Valid for 24 hours up to 5 users\n\n"
            "<b>Examples:</b>\n"
            "• Reply with <code>/share 1h onetime</code>\n"
            "• Reply with <code>/share 24h</code>\n"
            "• Reply with <code>/share onetime</code>"
        )
        return

    file_unique_id = media.file_unique_id
    file_name = getattr(media, "file_name", "Shared File")

    # Ensure file is saved in DB
    from database.files import save_file
    await save_file(media)

    # Parse duration and max uses
    from database.share_links import parse_duration, create_share_link
    args = message.text.split()[1:]
    duration_sec = None
    duration_label = "Permanent (No Expiry)"
    max_uses = 1  # Default to one-time use

    for arg in args:
        val = arg.lower().strip()
        parsed = parse_duration(val)
        if parsed:
            duration_sec = parsed
            duration_label = val
        elif val in ["onetime", "single", "once", "1"]:
            max_uses = 1
        elif val in ["unlimited", "none", "0"]:
            max_uses = None
        elif val.isdigit():
            max_uses = int(val)

    link_doc = await create_share_link(
        file_unique_id=file_unique_id,
        created_by=message.from_user.id,
        duration_seconds=duration_sec,
        max_uses=max_uses
    )

    if not link_doc:
        await message.reply_text("❌ Failed to generate share link.")
        return

    bot_uname = client.me.username if client.me else Config.BOT_USERNAME
    secret_url = f"https://t.me/{bot_uname}?start=share_{link_doc['token']}"

    uses_label = "Single-Use (1 Person Only - Self Destructing 🔥)" if max_uses == 1 else (f"{max_uses} Users" if max_uses else "Unlimited")

    await message.reply_text(
        "🔐 <b>Secret File Share Link Created!</b>\n\n"
        f"📁 <b>File:</b> <code>{file_name}</code>\n"
        f"🔗 <b>Link:</b> <code>{secret_url}</code>\n\n"
        f"⏱️ <b>Time Limit:</b> <code>{duration_label}</code>\n"
        f"👤 <b>Access Limit:</b> <code>{uses_label}</code>\n\n"
        "💡 When clicked, the recipient will instantly receive the file, and the link will automatically enforce your time and usage limits!"
    )

