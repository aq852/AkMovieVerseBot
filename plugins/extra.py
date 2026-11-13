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
        "• 📺 <b>Smart TV Stremio Addon:</b> Direct 4K & Multi-Audio streaming on Android TV, FireStick & PC\n"
        "• 🚫 <b>100% Ad-Free:</b> Zero shortener links, tokens, or captcha\n"
        "• 🔓 <b>Unlimited Downloads:</b> No daily download limits or caps\n"
        "• ⚡ <b>SEND ALL Unlocked:</b> 1-Tap complete season batch delivery\n"
        "• ⏳ <b>30-Min Safe Buffer:</b> 6x longer before auto-delete (Free: 5m)\n"
        "• 📥 <b>Web Cinema Player:</b> Direct high-speed offline downloads\n"
        "• 🔥 <b>Priority Requests:</b> Admin fast-track uploads & VIP support\n\n"
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
    user_id = query.from_user.id if query.from_user else 0
    name = (query.from_user.first_name if query.from_user else "Friend") or "Friend"

    from plugins.start import build_start_menu_content
    welcome_text, markup = await build_start_menu_content(user_id, name, bot_username)

    try:
        if query.message.photo:
            await query.message.edit_caption(caption=welcome_text, reply_markup=markup)
        else:
            await query.message.edit_text(welcome_text, reply_markup=markup)
    except Exception as e:
        logger.debug(f"Error restoring home in back_home: {e}")
        try:
            await query.message.reply_text(welcome_text, reply_markup=markup)
        except Exception:
            pass
    await query.answer()


async def get_vip_payment_info() -> dict:
    """Retrieve dynamic VIP payment info (UPI ID, QR URL, USDT Address) from MongoDB with Config fallback."""
    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"key": "vip_payment"})
        if doc:
            return {
                "upi_id": doc.get("upi_id") or Config.UPI_ID,
                "upi_qr_url": doc.get("upi_qr_url") or Config.UPI_QR_URL,
                "usdt_trc20": doc.get("usdt_trc20") or Config.USDT_TRC20
            }
    except Exception as e:
        logger.debug(f"Error reading vip_payment settings: {e}")
    return {
        "upi_id": Config.UPI_ID,
        "upi_qr_url": Config.UPI_QR_URL,
        "usdt_trc20": Config.USDT_TRC20
    }


@Client.on_callback_query(filters.regex(r"^view_plans"))
async def view_plans_callback(client: Client, query: CallbackQuery):
    text = get_plans_text()
    markup = get_plans_markup()

    try:
        if query.message.photo:
            pay_info = await get_vip_payment_info()
            qr_url = pay_info.get("upi_qr_url")
            if qr_url:
                try:
                    await query.message.edit_media(
                        media=InputMediaPhoto(qr_url, caption=text),
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
    pay_info = await get_vip_payment_info()
    active_usdt = pay_info.get("usdt_trc20") or Config.USDT_TRC20
    active_upi = pay_info.get("upi_id") or Config.UPI_ID
    active_qr = pay_info.get("upi_qr_url") or Config.UPI_QR_URL

    if plan_key == "crypto":
        text = (
            "🌐 <b>AKMOVIEVERSE VIP — CRYPTO / USDT TRC-20</b>\n\n"
            "Pay using USDT on the TRC-20 network or Binance Pay.\n\n"
            f"💎 <b>USDT TRC-20 Address:</b> (tap to copy)\n<code>{active_usdt}</code>\n\n"
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
        f"<code>{active_upi}</code>\n\n"
        f"📝 <b>Easy Steps to Activate:</b>\n"
        f"1. Scan the QR code or pay <b>{plan['price']}</b> to <code>{active_upi}</code>.\n"
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
            if active_qr:
                try:
                    await query.message.delete()
                    await client.send_photo(
                        chat_id=query.message.chat.id,
                        photo=active_qr,
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



# --- Dynamic VIP Payment Management Commands ---

@Client.on_message(filters.command(["setupi"]) & filters.private)
async def setupi_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    import html
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        info = await get_vip_payment_info()
        u = html.escape(str(info.get('upi_id', '')))
        await message.reply_text(
            f"📲 <b>Current UPI ID:</b> <code>{u}</code>\n\n"
            "<b>Usage:</b> <code>/setupi your_upi@id</code>"
        )
        return
    new_upi = args[1].strip()
    from database.mongo import mongo
    await mongo.db["bot_settings"].update_one(
        {"key": "vip_payment"},
        {"$set": {"upi_id": new_upi}},
        upsert=True
    )
    await message.reply_text(f"✅ <b>UPI ID Successfully Updated:</b>\n<code>{html.escape(new_upi)}</code>")


@Client.on_message(filters.command(["setupiqr"]) & filters.private)
async def setupiqr_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    import html
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        info = await get_vip_payment_info()
        q = html.escape(str(info.get('upi_qr_url', '')))
        await message.reply_text(
            f"🖼️ <b>Current UPI QR URL:</b> <code>{q}</code>\n\n"
            "<b>Usage:</b> <code>/setupiqr https://example.com/qr.jpg</code>"
        )
        return
    new_qr = args[1].strip()
    from database.mongo import mongo
    await mongo.db["bot_settings"].update_one(
        {"key": "vip_payment"},
        {"$set": {"upi_qr_url": new_qr}},
        upsert=True
    )
    await message.reply_text(f"✅ <b>UPI QR URL Successfully Updated:</b>\n<code>{html.escape(new_qr)}</code>")


@Client.on_message(filters.command(["setusdt"]) & filters.private)
async def setusdt_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    import html
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        info = await get_vip_payment_info()
        t = html.escape(str(info.get('usdt_trc20', '')))
        await message.reply_text(
            f"💎 <b>Current USDT TRC-20 Address:</b> <code>{t}</code>\n\n"
            "<b>Usage:</b> <code>/setusdt your_trc20_address</code>"
        )
        return
    new_usdt = args[1].strip()
    from database.mongo import mongo
    await mongo.db["bot_settings"].update_one(
        {"key": "vip_payment"},
        {"$set": {"usdt_trc20": new_usdt}},
        upsert=True
    )
    await message.reply_text(f"✅ <b>USDT Address Successfully Updated:</b>\n<code>{html.escape(new_usdt)}</code>")


@Client.on_message(filters.command(["vipsettings"]) & filters.private)
async def vipsettings_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    import html
    info = await get_vip_payment_info()
    u_id = html.escape(str(info.get('upi_id', '')))
    u_qr = html.escape(str(info.get('upi_qr_url', '')))
    u_trc = html.escape(str(info.get('usdt_trc20', '')))
    u_sup = html.escape(str(getattr(Config, "SUPPORT_URL", "") or ""))

    await message.reply_text(
        "💳 <b>Current Active VIP Payment Settings:</b>\n\n"
        f"📲 <b>UPI ID:</b> <code>{u_id}</code>\n"
        f"🖼️ <b>UPI QR:</b> <code>{u_qr}</code>\n"
        f"💎 <b>USDT TRC-20:</b> <code>{u_trc}</code>\n"
        f"💬 <b>Support:</b> <code>{u_sup}</code>\n\n"
        "<b>Admin Commands:</b>\n"
        "• <code>/setupi [new_upi]</code>\n"
        "• <code>/setupiqr [qr_image_url]</code>\n"
        "• <code>/setusdt [trc20_address]</code>"
    )


# -------------------------------------------------------------
# Streaming Website Catalog Management & Backlog Filter System
# -------------------------------------------------------------

@Client.on_message(filters.command(["streamstart", "startstream", "streamcutoff", "cutoff", "streamon"]) & filters.private)
async def stream_start_cmd(client: Client, message: Message):
    """Start or adjust the streaming website showroom timeline start point and ingestion."""
    if not Config.is_admin(message.from_user.id):
        return
    args = message.text.split()
    from database.mongo import set_bot_setting, get_bot_setting, mongo
    from utils.web_server import clear_catalog_cache
    from bson import ObjectId
    import datetime

    web_url = (getattr(Config, "STREAM_URL", "") or getattr(Config, "WEB_URL", "") or "http://localhost:8080").rstrip("/")

    if len(args) < 2:
        curr = await get_bot_setting("stream_catalog_cutoff_id", None)
        mode = await get_bot_setting("stream_catalog_mode", "auto")
        is_paused = await get_bot_setting("stream_catalog_paused", False)
        status = "⏸️ PAUSED" if is_paused else ("🧹 CLEARED" if mode == "cleared" else "🟢 ACTIVE")
        curr_str = f"<code>{curr}</code>" if curr else "<i>Beginning (All indexed files)</i>"
        await message.reply_text(
            f"🎬 <b>STREAM CATALOG START CONTROLLER</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> {status}\n"
            f"• <b>Current Start Point:</b> {curr_str}\n"
            f"• <b>Ingestion Mode:</b> <code>{mode.upper()}</code>\n\n"
            "<b>Usage:</b>\n"
            "• <code>/streamstart now</code> — Start stream live from NOW! All new files (from /index, auto-index, anyhow) automatically go to website showroom.\n"
            "• <code>/streamstart all</code> — Restore all 588k library files to website showroom.\n"
            "• <code>/streamstart auto</code> — Start stream in auto-only mode (live uploads only).\n"
            "• <code>/streamstart YYYY-MM-DD</code> — Start stream showroom from a specific date."
        )
        return

    sub = args[1].lower().strip()
    if sub in ("all", "reset"):
        await set_bot_setting("stream_catalog_cutoff_id", None)
        await set_bot_setting("stream_catalog_mode", "all")
        await set_bot_setting("stream_catalog_paused", False)
        clear_catalog_cache()
        await message.reply_text(
            "✅ <b>Full Stream Catalog Live!</b>\n\n"
            "• All 588k+ indexed files are now visible on the website catalog.\n"
            f"• <b>Web Catalog:</b> <a href=\"{web_url}/browse\">{web_url}/browse</a>"
        )
    elif sub == "auto":
        await set_bot_setting("stream_catalog_mode", "auto")
        await set_bot_setting("stream_catalog_paused", False)
        clear_catalog_cache()
        await message.reply_text(
            "✅ <b>Stream Mode: AUTO!</b>\n\n"
            "• Only live storage channel uploads will appear on the website.\n"
            "• Bulk /index history crawls remain bot-only."
        )
    elif sub == "now":
        latest = await mongo.files.find_one({}, {"_id": 1}, sort=[("_id", -1)])
        if not latest:
            await message.reply_text("⚠️ No files found in database to set start point.")
            return
        cutoff_id = str(latest["_id"])
        await set_bot_setting("stream_catalog_cutoff_id", cutoff_id)
        await set_bot_setting("stream_catalog_mode", "all")
        await set_bot_setting("stream_catalog_paused", False)
        clear_catalog_cache()
        await message.reply_text(
            f"✅ <b>Stream Showroom Started from NOW!</b>\n\n"
            f"• <b>Showroom Start Point:</b> Right now (Past backlog hidden from website)\n"
            f"• <b>Ingestion Mode:</b> 🔵 ALL (Whatever files come in from /index, auto-index, anyhow — ALL go to website!)\n"
            f"• <b>Bot Status:</b> All 588k+ files remain <b>100% indexed & searchable in Telegram</b>!\n"
            f"• <b>Catalog Link:</b> <a href=\"{web_url}/browse\">{web_url}/browse</a>"
        )
    else:
        try:
            dt = datetime.datetime.strptime(sub, "%Y-%m-%d")
            cutoff_id = str(ObjectId.from_datetime(dt))
            await set_bot_setting("stream_catalog_cutoff_id", cutoff_id)
            await set_bot_setting("stream_catalog_mode", "all")
            await set_bot_setting("stream_catalog_paused", False)
            clear_catalog_cache()
            await message.reply_text(
                f"✅ <b>Stream Started from Date:</b> <code>{sub}</code>\n\n"
                f"• Cutoff ObjectId: <code>{cutoff_id}</code>\n"
                f"• Content indexed on or after {sub} is now live on the website showroom."
            )
        except Exception:
            await message.reply_text("⚠️ Invalid parameter. Use <code>now</code>, <code>all</code>, <code>auto</code>, or <code>YYYY-MM-DD</code>.")


@Client.on_message(filters.command(["streamclear", "clearstream", "streamwipe"]) & filters.private)
async def stream_clear_cmd(client: Client, message: Message):
    """Clear the streaming website showroom completely or up to a specific date."""
    if not Config.is_admin(message.from_user.id):
        return
    args = message.text.split()
    from database.mongo import set_bot_setting, mongo
    from utils.web_server import clear_catalog_cache
    from bson import ObjectId
    import datetime

    sub = args[1].lower().strip() if len(args) > 1 else "all"

    if sub == "all":
        await set_bot_setting("stream_catalog_mode", "cleared")
        await set_bot_setting("stream_catalog_cutoff_id", None)
        clear_catalog_cache()
        await message.reply_text(
            "🧹 <b>Streaming Website Catalog Cleared!</b>\n\n"
            "• <b>Website Status:</b> 0 titles showing on website showroom (Clean Slate).\n"
            "• <b>Bot Status:</b> All 588k+ files remain <b>100% safe & searchable in Telegram</b>!\n\n"
            "💡 <i>To start publishing again anytime, use</i> <code>/streamstart now</code> <i>or click [Start From NOW] in /streamsettings</i>."
        )
    elif sub == "now":
        latest = await mongo.files.find_one({}, {"_id": 1}, sort=[("_id", -1)])
        if latest:
            cutoff_id = str(latest["_id"])
            await set_bot_setting("stream_catalog_cutoff_id", cutoff_id)
            clear_catalog_cache()
            await message.reply_text(
                "🧹 <b>Past Backlog Cleared from Website!</b>\n\n"
                "• All past files up to right now are hidden from the website catalog showroom.\n"
                "• Only fresh releases indexed from now on will appear on the website showroom.\n"
                "• <i>Files remain 100% searchable in Telegram bot!</i>"
            )
    else:
        try:
            dt = datetime.datetime.strptime(sub, "%Y-%m-%d")
            cutoff_id = str(ObjectId.from_datetime(dt))
            await set_bot_setting("stream_catalog_cutoff_id", cutoff_id)
            clear_catalog_cache()
            await message.reply_text(
                f"🧹 <b>Files Before {sub} Cleared from Website!</b>\n\n"
                f"• All files indexed before <code>{sub}</code> are now hidden from the website catalog showroom."
            )
        except Exception:
            await message.reply_text("⚠️ Use <code>/streamclear all</code>, <code>/streamclear now</code>, or <code>/streamclear YYYY-MM-DD</code>.")


@Client.on_message(filters.command(["streampause", "pause_stream", "pausecatalog"]) & filters.private)
async def stream_pause_cmd(client: Client, message: Message):
    """Freeze website streaming catalog updates temporarily."""
    if not Config.is_admin(message.from_user.id):
        return
    from database.mongo import set_bot_setting
    from utils.web_server import clear_catalog_cache
    await set_bot_setting("stream_catalog_paused", True)
    clear_catalog_cache()
    await message.reply_text(
        "⏸️ <b>Streaming Website Catalog PAUSED!</b>\n\n"
        "• Website showroom updates are now <b>frozen</b>.\n"
        "• New channel uploads and indexing will stay in Telegram bot only (100% searchable).\n"
        "• No new titles will enter the website showroom until resumed.\n\n"
        "💡 <i>Resume anytime using</i> <code>/streamresume</code> <i>or via /streamsettings</i>."
    )


@Client.on_message(filters.command(["streamresume", "resume_stream", "resumecatalog"]) & filters.private)
async def stream_resume_cmd(client: Client, message: Message):
    """Unfreeze and resume website streaming catalog updates."""
    if not Config.is_admin(message.from_user.id):
        return
    from database.mongo import set_bot_setting, get_bot_setting
    from utils.web_server import clear_catalog_cache
    await set_bot_setting("stream_catalog_paused", False)
    mode = await get_bot_setting("stream_catalog_mode", "auto")
    if mode == "cleared":
        await set_bot_setting("stream_catalog_mode", "all")
    clear_catalog_cache()
    web_url = (getattr(Config, "STREAM_URL", "") or getattr(Config, "WEB_URL", "") or "http://localhost:8080").rstrip("/")
    await message.reply_text(
        "▶️ <b>Streaming Website Catalog RESUMED!</b>\n\n"
        "• Website showroom is now <b>LIVE</b> again!\n"
        "• New uploads and indexing will automatically publish to the website.\n"
        f"• <b>Web Catalog:</b> <a href=\"{web_url}/browse\">{web_url}/browse</a>"
    )


@Client.on_message(filters.command(["streammode"]) & filters.private)
async def stream_mode_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    args = message.text.split()
    from database.mongo import set_bot_setting, get_bot_setting
    from utils.web_server import clear_catalog_cache

    if len(args) < 2:
        curr = await get_bot_setting("stream_catalog_mode", "auto")
        await message.reply_text(
            f"🎬 <b>Current Stream Mode:</b> <code>{curr.upper()}</code>\n\n"
            "<b>Modes:</b>\n"
            "• <code>/streammode auto</code> — Auto-index only (live channel uploads show on site; bulk /index crawls are bot-only)\n"
            "• <code>/streammode all</code> — Show all files (subject to cutoff date)\n"
            "• <code>/streammode channels</code> — Only show files from whitelisted channels (/streamchannels)"
        )
        return

    mode = args[1].lower().strip()
    if mode not in ["auto", "all", "channels"]:
        await message.reply_text("⚠️ Invalid mode. Choose: <code>auto</code>, <code>all</code>, or <code>channels</code>.")
        return

    await set_bot_setting("stream_catalog_mode", mode)
    clear_catalog_cache()
    await message.reply_text(f"✅ <b>Stream Catalog Mode Updated:</b> <code>{mode.upper()}</code>")


@Client.on_message(filters.command(["addstreamchannel"]) & filters.private)
async def add_stream_channel_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/addstreamchannel [channel_id]</code>")
        return
    try:
        cid = int(args[1])
    except ValueError:
        await message.reply_text("⚠️ Channel ID must be an integer (e.g. <code>-1001234567890</code>).")
        return

    from database.mongo import get_bot_setting, set_bot_setting
    from utils.web_server import clear_catalog_cache
    chans = await get_bot_setting("stream_catalog_channels", [])
    if cid not in chans:
        chans.append(cid)
        await set_bot_setting("stream_catalog_channels", chans)
        clear_catalog_cache()
        await message.reply_text(f"✅ Added channel <code>{cid}</code> to stream whitelist.")
    else:
        await message.reply_text(f"ℹ️ Channel <code>{cid}</code> is already in stream whitelist.")


@Client.on_message(filters.command(["delstreamchannel", "removestreamchannel"]) & filters.private)
async def del_stream_channel_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/delstreamchannel [channel_id]</code>")
        return
    try:
        cid = int(args[1])
    except ValueError:
        await message.reply_text("⚠️ Channel ID must be an integer.")
        return

    from database.mongo import get_bot_setting, set_bot_setting
    from utils.web_server import clear_catalog_cache
    chans = await get_bot_setting("stream_catalog_channels", [])
    if cid in chans:
        chans.remove(cid)
        await set_bot_setting("stream_catalog_channels", chans)
        clear_catalog_cache()
        await message.reply_text(f"✅ Removed channel <code>{cid}</code> from stream whitelist.")
    else:
        await message.reply_text(f"ℹ️ Channel <code>{cid}</code> is not in stream whitelist.")


@Client.on_message(filters.command(["streamchannels"]) & filters.private)
async def list_stream_channels_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    from database.mongo import get_bot_setting
    chans = await get_bot_setting("stream_catalog_channels", [])
    if not chans:
        await message.reply_text("ℹ️ No specific streaming channels whitelisted. All auto-indexed channels appear on site.")
    else:
        c_lines = "\n".join([f"• <code>{c}</code>" for c in chans])
        await message.reply_text(f"📺 <b>Whitelisted Streaming Channels:</b>\n\n{c_lines}")


@Client.on_message(filters.command(["streamadd", "addstream"]) & filters.private)
async def add_stream_cmd(client: Client, message: Message):
    """Publish a specific movie, series, or replied file to the Web Streaming Website."""
    if not Config.is_admin(message.from_user.id):
        return

    from database.files import set_web_stream_status_by_query, set_web_stream_status_by_id
    from utils.web_server import clear_catalog_cache
    from utils.helpers import parse_media_metadata

    web_url = (getattr(Config, "STREAM_URL", "") or getattr(Config, "WEB_URL", "") or "http://localhost:8080").rstrip("/")

    # Case 1: Reply to a file message
    reply = message.reply_to_message
    if reply and (reply.document or reply.video or reply.audio):
        media = reply.document or reply.video or reply.audio
        file_name = getattr(media, "file_name", "") or ""
        meta = parse_media_metadata(file_name)
        base_title = meta.get("base_title") if meta else ""

        args = message.text.split(maxsplit=1)
        target_title = args[1].strip() if len(args) > 1 else base_title

        if target_title:
            count = await set_web_stream_status_by_query(target_title, True)
        else:
            count = await set_web_stream_status_by_id(media.file_unique_id, True)

        clear_catalog_cache()
        display_name = target_title or file_name or "Selected File"
        return await message.reply_text(
            f"✅ <b>Added to Streaming Website!</b>\n\n"
            f"🎬 <b>Title:</b> <code>{display_name}</code>\n"
            f"📦 <b>Files Published:</b> <code>{count} file(s)</code>\n"
            f"🌐 <b>Web Catalog:</b> <a href=\"{web_url}/browse\">{web_url}/browse</a>\n\n"
            "<i>💡 Files remain 100% searchable in Telegram bot!</i>"
        )

    # Case 2: Title / Query provided: /addstream Inception
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "• <code>/streamadd [Movie or Series Name]</code> — Publish all matching files to streaming site\n"
            "• Reply to any video/file with <code>/streamadd</code> — Publish that file/series to site\n\n"
            "<i>Example:</i> <code>/streamadd Inception</code>"
        )

    query = args[1].strip()
    count = await set_web_stream_status_by_query(query, True)
    clear_catalog_cache()

    if count == 0:
        return await message.reply_text(
            f"⚠️ <b>No files found matching:</b> <code>{query}</code>\n"
            "Make sure the title is indexed in the bot first."
        )

    await message.reply_text(
        f"✅ <b>Published to Streaming Website!</b>\n\n"
        f"🎬 <b>Title/Query:</b> <code>{query}</code>\n"
        f"📦 <b>Files Published:</b> <code>{count} file(s)</code>\n"
        f"🌐 <b>Web Catalog:</b> <a href=\"{web_url}/browse\">{web_url}/browse</a>\n\n"
        "<i>💡 Files remain 100% searchable in Telegram bot!</i>"
    )


@Client.on_message(filters.command(["streamremove", "removestream", "delstream", "streamdel"]) & filters.private)
async def del_stream_cmd(client: Client, message: Message):
    """Hide a specific movie, series, or replied file from the Web Streaming Website."""
    if not Config.is_admin(message.from_user.id):
        return

    from database.files import set_web_stream_status_by_query, set_web_stream_status_by_id
    from utils.web_server import clear_catalog_cache
    from utils.helpers import parse_media_metadata

    # Case 1: Reply to a file message
    reply = message.reply_to_message
    if reply and (reply.document or reply.video or reply.audio):
        media = reply.document or reply.video or reply.audio
        file_name = getattr(media, "file_name", "") or ""
        meta = parse_media_metadata(file_name)
        base_title = meta.get("base_title") if meta else ""

        args = message.text.split(maxsplit=1)
        target_title = args[1].strip() if len(args) > 1 else base_title

        if target_title:
            count = await set_web_stream_status_by_query(target_title, False)
        else:
            count = await set_web_stream_status_by_id(media.file_unique_id, False)

        clear_catalog_cache()
        display_name = target_title or file_name or "Selected File"
        return await message.reply_text(
            f"🚫 <b>Hidden from Streaming Website!</b>\n\n"
            f"🎬 <b>Title:</b> <code>{display_name}</code>\n"
            f"📦 <b>Files Removed from Web:</b> <code>{count} file(s)</code>\n\n"
            "<i>💡 Files remain 100% indexed and searchable in Telegram bot!</i>"
        )

    # Case 2: Title / Query provided: /delstream Inception
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "• <code>/streamremove [Movie or Series Name]</code> — Hide all matching files from streaming site\n"
            "• Reply to any video/file with <code>/streamremove</code> — Hide that file/series from site\n\n"
            "<i>Example:</i> <code>/streamremove Inception</code>"
        )

    query = args[1].strip()
    count = await set_web_stream_status_by_query(query, False)
    clear_catalog_cache()

    if count == 0:
        return await message.reply_text(f"⚠️ <b>No files found matching:</b> <code>{query}</code>")

    await message.reply_text(
        f"🚫 <b>Hidden from Streaming Website!</b>\n\n"
        f"🎬 <b>Title/Query:</b> <code>{query}</code>\n"
        f"📦 <b>Files Removed from Web:</b> <code>{count} file(s)</code>\n\n"
        "<i>💡 Files remain 100% indexed and searchable in Telegram bot!</i>"
    )


async def _build_stream_settings_panel():
    """Construct unified dashboard text and inline buttons for stream control center."""
    from database.mongo import get_bot_setting, mongo
    cutoff = await get_bot_setting("stream_catalog_cutoff_id", None)
    mode = await get_bot_setting("stream_catalog_mode", "auto")
    chans = await get_bot_setting("stream_catalog_channels", [])
    is_paused = await get_bot_setting("stream_catalog_paused", False)

    total_bot_files = 0
    try:
        total_bot_files = await mongo.files.count_documents({})
        if mongo.has_secondary:
            total_bot_files += await mongo.files_secondary.count_documents({})
    except Exception:
        pass

    if is_paused:
        status_desc = "⏸️ PAUSED (Updates frozen)"
    elif mode == "cleared":
        status_desc = "🧹 CLEARED (Showroom empty)"
    else:
        status_desc = "🟢 LIVE & ACTIVE"

    if cutoff:
        start_desc = f"Fresh from now (ID: <code>{cutoff[:10]}...</code>)"
    else:
        start_desc = "Beginning (Full 588k library)"

    mode_labels = {
        "all": "🔵 ALL (Every /index & upload goes to web)",
        "auto": "🟢 AUTO (Live channel uploads only)",
        "channels": f"🟣 CHANNELS ({len(chans)} whitelisted)",
        "cleared": "⚪ CLEARED (Website wiped)"
    }
    mode_desc = mode_labels.get(mode, mode)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Start From NOW", callback_data="stream_panel_set_now"),
            InlineKeyboardButton("♻️ Restore All", callback_data="stream_panel_set_reset")
        ],
        [
            InlineKeyboardButton("⏸️ Pause Stream", callback_data="stream_panel_pause"),
            InlineKeyboardButton("▶️ Resume Stream", callback_data="stream_panel_resume")
        ],
        [
            InlineKeyboardButton("🧹 Clear Website", callback_data="stream_panel_clear_all"),
            InlineKeyboardButton(f"🔀 Mode: {mode.upper()}", callback_data="stream_panel_toggle_mode")
        ],
        [
            InlineKeyboardButton(f"📺 Channels ({len(chans)})", callback_data="stream_panel_channels_list"),
            InlineKeyboardButton("🔄 Refresh", callback_data="stream_panel_refresh")
        ]
    ])

    text = (
        "🎬 <b>STREAMING WEBSITE CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Website Status:</b> {status_desc}\n"
        f"• <b>Showroom Start:</b> {start_desc}\n"
        f"• <b>Publishing Mode:</b> {mode_desc}\n"
        f"• <b>Whitelisted Channels:</b> <code>{len(chans)} Channels</code>\n"
        f"• <b>Bare-Code Junk Guard:</b> 🟢 Active (e.g. S02E33 hidden)\n\n"
        "📊 <b>Database Overview:</b>\n"
        f"• <b>Bot Master Index:</b> <code>{total_bot_files:,} files</code> (100% in TG)\n\n"
        "⚡ <b>Commands:</b>\n"
        "• <code>/streamstart now</code> — Live start from now (All files to web)\n"
        "• <code>/streamclear all</code> — Wipe website (Files safe in Bot)\n"
        "• <code>/streampause</code> | <code>/streamresume</code> — Freeze / Unfreeze site\n"
        "• <code>/streamadd [name]</code> | <code>/streamremove [name]</code>\n"
        "• <code>/addstreamchannel [id]</code> — Whitelist channel\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return text, keyboard


@Client.on_message(filters.command(["streamsettings", "catalogsettings"]) & filters.private)
async def stream_settings_cmd(client: Client, message: Message):
    if not Config.is_admin(message.from_user.id):
        return
    text, keyboard = await _build_stream_settings_panel()
    await message.reply_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^stream_panel_"))
async def stream_settings_callbacks(client: Client, query: CallbackQuery):
    if not Config.is_admin(query.from_user.id):
        await query.answer("⛔ Admin Only!", show_alert=True)
        return

    data = query.data
    from database.mongo import set_bot_setting, get_bot_setting, mongo
    from utils.web_server import clear_catalog_cache

    if data == "stream_panel_set_now":
        latest = await mongo.files.find_one({}, {"_id": 1}, sort=[("_id", -1)])
        if latest:
            cutoff_id = str(latest["_id"])
            await set_bot_setting("stream_catalog_cutoff_id", cutoff_id)
            await set_bot_setting("stream_catalog_mode", "all")
            await set_bot_setting("stream_catalog_paused", False)
            clear_catalog_cache()
            await query.answer("✅ Stream started from NOW! All new files will go to site.", show_alert=True)
        else:
            await query.answer("⚠️ No files found.", show_alert=True)

    elif data == "stream_panel_set_reset":
        await set_bot_setting("stream_catalog_cutoff_id", None)
        await set_bot_setting("stream_catalog_mode", "all")
        await set_bot_setting("stream_catalog_paused", False)
        clear_catalog_cache()
        await query.answer("✅ Entire database restored to website showroom!", show_alert=True)

    elif data == "stream_panel_pause":
        await set_bot_setting("stream_catalog_paused", True)
        clear_catalog_cache()
        await query.answer("⏸️ Website catalog paused! New files stay in Bot only.", show_alert=True)

    elif data == "stream_panel_resume":
        await set_bot_setting("stream_catalog_paused", False)
        mode = await get_bot_setting("stream_catalog_mode", "auto")
        if mode == "cleared":
            await set_bot_setting("stream_catalog_mode", "all")
        clear_catalog_cache()
        await query.answer("▶️ Website catalog resumed! Live publishing is ON.", show_alert=True)

    elif data == "stream_panel_clear_all":
        await set_bot_setting("stream_catalog_mode", "cleared")
        await set_bot_setting("stream_catalog_cutoff_id", None)
        clear_catalog_cache()
        await query.answer("🧹 Website catalog cleared! (All files safe in Bot).", show_alert=True)

    elif data == "stream_panel_toggle_mode":
        curr = await get_bot_setting("stream_catalog_mode", "all")
        modes = ["all", "auto", "channels"]
        next_mode = modes[(modes.index(curr) + 1) % len(modes)] if curr in modes else "all"
        await set_bot_setting("stream_catalog_mode", next_mode)
        clear_catalog_cache()
        await query.answer(f"✅ Mode changed to: {next_mode.upper()}", show_alert=True)

    elif data == "stream_panel_channels_list":
        chans = await get_bot_setting("stream_catalog_channels", [])
        if chans:
            c_text = "\n".join([f"• {c}" for c in chans])
            await query.answer(f"📺 Whitelisted Channels:\n{c_text}", show_alert=True)
        else:
            await query.answer("ℹ️ No specific streaming channels whitelisted. Use /addstreamchannel <id>", show_alert=True)

    elif data == "stream_panel_refresh":
        await query.answer("🔄 Dashboard refreshed!", show_alert=False)

    elif data == "stream_panel_clear_cache":
        clear_catalog_cache()
        await query.answer("🧹 Stream catalog cache cleared!", show_alert=True)

    # Refresh message view
    try:
        text, keyboard = await _build_stream_settings_panel()
        await query.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass


# -------------------------------------------------------------
# 1-Click Telegram Admin Bot Restart & Auto-Update Engine
# -------------------------------------------------------------

@Client.on_message(filters.command(["restart", "reboot"]) & filters.private)
async def restart_bot_cmd(client: Client, message: Message):
    """Seamlessly restart the bot process with detached launcher and zero port/socket conflicts."""
    if not Config.is_admin(message.from_user.id):
        return
    msg = await message.reply_text("♻️ <b>Restarting AutoFilterBot...</b>\nPlease wait 5-10 seconds.")
    import os
    import sys
    import json
    import subprocess

    # 1. Save restart notification locally and in MongoDB
    restart_data = {"chat_id": message.chat.id, "message_id": msg.id}
    try:
        with open("/tmp/autofilterbot_restart.json", "w") as f:
            json.dump(restart_data, f)
    except Exception:
        pass

    try:
        from database.mongo import set_bot_setting
        await set_bot_setting("restart_notification", restart_data)
    except Exception:
        pass

    # 2. Release and remove lock file so new process never conflicts
    try:
        if os.path.exists("/tmp/autofilterbot_master.lock"):
            os.remove("/tmp/autofilterbot_master.lock")
    except Exception:
        pass

    # 3. Locate root directory and python binary
    plugins_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(plugins_dir)
    bot_script = os.path.join(root_dir, "bot.py")
    if not os.path.exists(bot_script):
        bot_script = os.path.abspath("bot.py")
    python_bin = sys.executable

    # 4. Detached launcher with smart systemd service detection
    if sys.platform != "win32":
        service_name = None
        for sname in ["akbot", "autofilterbot"]:
            try:
                res = subprocess.run(["systemctl", "is-active", sname], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and "active" in res.stdout:
                    service_name = sname
                    break
            except Exception:
                pass

        if service_name:
            cmd = f"sleep 1 && systemctl restart {service_name}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
        else:
            cmd = f"sleep 2 && cd '{root_dir}' && '{python_bin}' '{bot_script}'"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
    else:
        cmd = f"timeout /t 2 /nobreak && cd /d \"{root_dir}\" && \"{python_bin}\" \"{bot_script}\""
        subprocess.Popen(cmd, shell=True)

    # 5. Cleanly exit current process
    sys.exit(0)


@Client.on_message(filters.command(["update", "gitpull"]) & filters.private)
async def update_bot_cmd(client: Client, message: Message):
    """Pull latest GitHub commits and seamlessly restart bot without touching SSH terminal."""
    if not Config.is_admin(message.from_user.id):
        return
    msg = await message.reply_text("🔄 <b>Pulling latest updates from GitHub...</b>")
    import os
    import sys
    import json
    import subprocess

    plugins_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(plugins_dir)
    bot_script = os.path.join(root_dir, "bot.py")
    if not os.path.exists(bot_script):
        bot_script = os.path.abspath("bot.py")
    python_bin = sys.executable

    try:
        pull_out = subprocess.check_output(
            ["git", "pull"], cwd=root_dir, stderr=subprocess.STDOUT, text=True, timeout=30
        )
    except Exception as e:
        await msg.edit_text(f"❌ <b>Git pull failed:</b>\n<code>{e}</code>")
        return

    await msg.edit_text(
        f"✅ <b>Git pull complete:</b>\n<code>{pull_out[:200]}</code>\n\n"
        "♻️ <i>Restarting bot in 2 seconds...</i>"
    )

    restart_data = {"chat_id": message.chat.id, "message_id": msg.id}
    try:
        with open("/tmp/autofilterbot_restart.json", "w") as f:
            json.dump(restart_data, f)
    except Exception:
        pass

    try:
        from database.mongo import set_bot_setting
        await set_bot_setting("restart_notification", restart_data)
    except Exception:
        pass

    try:
        if os.path.exists("/tmp/autofilterbot_master.lock"):
            os.remove("/tmp/autofilterbot_master.lock")
    except Exception:
        pass

    if sys.platform != "win32":
        service_name = None
        for sname in ["akbot", "autofilterbot"]:
            try:
                res = subprocess.run(["systemctl", "is-active", sname], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and "active" in res.stdout:
                    service_name = sname
                    break
            except Exception:
                pass

        if service_name:
            cmd = f"sleep 1 && systemctl restart {service_name}"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
        else:
            cmd = f"sleep 2 && cd '{root_dir}' && '{python_bin}' '{bot_script}'"
            subprocess.Popen(cmd, shell=True, start_new_session=True)
    else:
        cmd = f"timeout /t 2 /nobreak && cd /d \"{root_dir}\" && \"{python_bin}\" \"{bot_script}\""
        subprocess.Popen(cmd, shell=True)

    sys.exit(0)
