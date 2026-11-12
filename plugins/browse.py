"""
AkMovieVerse Web Cinema Catalog & Dynamic Stream URL Manager
============================================================
Provides:
1. /browse, /catalog, /webcinema - 1-Click interactive Telegram card for the Netflix-style Web Catalog
2. /setstream, /set_stream - Admin command to view or update the live Stream/Browse domain in MongoDB
"""

import logging
import html
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.mongo import set_bot_setting
from plugins.stream import get_effective_stream_base_url
from utils.helpers import resolve_channel_display_and_url

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["browse", "catalog", "webcinema"]))
async def browse_catalog_command(client: Client, message: Message):
    """Deliver interactive Telegram card linking to the responsive Web Cinema Catalog."""
    stream_base = get_effective_stream_base_url()
    channel_name, channel_url = await resolve_channel_display_and_url(client)

    if not stream_base or any(h in stream_base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
        await message.reply_text(
            "⚠️ <b>Web Cinema Catalog Offline</b>\n\n"
            "The streaming and catalog domain has not been configured yet.\n"
            "<i>Admins can set it using:</i> <code>/setstream https://yourdomain.com/</code>"
        )
        return

    browse_url = f"{stream_base}/browse"
    galaxy_url = f"{stream_base}/galaxy"
    escaped_ch_name = html.escape(channel_name)

    caption = (
        "🍿 <b>AkMovieVerse — Web Cinema & Catalog</b>\n\n"
        "Browse thousands of high-definition movies, web series, dual-audio releases, and complete seasons directly in your browser!\n\n"
        "✨ <b>Web Cinema Features:</b>\n"
        "• 🎬 <b>In-Browser Cinema Player:</b> Instant 1-click playback\n"
        "• 🪐 <b>3D Galaxy Movieverse:</b> Interactive floating 3D universe\n"
        "• 📺 <b>External Players:</b> MX Player, VLC & M3U Playlist support\n"
        "• 🚀 <b>Lightning Fast Downloads:</b> High-speed web file transfers\n"
        "• 🔍 <b>Smart Live Search:</b> Filter by Movies, Series, Qualities & Audio\n\n"
        f"📢 <b>Official Channel:</b> <a href=\"{channel_url}\">{escaped_ch_name}</a>"
    )

    try:
        from hydrogram.types import WebAppInfo
    except ImportError:
        from pyrogram.types import WebAppInfo

    buttons = [
        [
            InlineKeyboardButton("🪐 OPEN MOVIEVERSE 3D 🚀", web_app=WebAppInfo(url=galaxy_url))
        ],
        [
            InlineKeyboardButton("🌐 Open Web Catalog ↗️", url=browse_url),
            InlineKeyboardButton("📌 Channel ↗️", url=channel_url)
        ]
    ]

    await message.reply_text(
        caption,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True
    )


@Client.on_message(filters.command(["galaxy", "3d", "movieverse"]))
async def galaxy_movieverse_command(client: Client, message: Message):
    """Deliver interactive Telegram Mini App card for the 3D MovieVerse Search & File Delivery."""
    stream_base = get_effective_stream_base_url()
    channel_name, channel_url = await resolve_channel_display_and_url(client)

    if not stream_base or any(h in stream_base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
        stream_base = "https://akmovieverse.duckdns.org"

    # Support optional search query in command: e.g. /movieverse jailer
    args = message.text.split(None, 1)
    q = args[1].strip() if len(args) > 1 else ""
    import urllib.parse
    g_param = f"?q={urllib.parse.quote_plus(q)}" if q else ""
    galaxy_url = f"{stream_base}/galaxy{g_param}"
    escaped_ch_name = html.escape(channel_name)

    q_label = f" for '<b>{html.escape(q)}</b>'" if q else ""
    text = (
        f"🪐 <b>MOVIEVERSE 3D SEARCH & EXPLORER</b> 🚀\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <i>Step into the future of 3D search and file delivery{q_label}!</i>\n\n"
        f"🌌 <b>Features:</b>\n"
        f"• <b>3D Interactive Solar Orbit:</b> Swipe to rotate floating movie & series cards\n"
        f"• <b>Live Cosmic Search:</b> Search any title & see cards rearrange in real-time\n"
        f"• <b>Direct Quality Delivery:</b> 480p, 720p, 1080p, 4K files delivered straight to bot PM\n\n"
        f"👇 <i>Neeche button par tap karke MovieVerse 3D launch karein:</i>"
    )

    try:
        from hydrogram.types import WebAppInfo
    except ImportError:
        from pyrogram.types import WebAppInfo

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🪐 OPEN MOVIEVERSE 3D 🚀", web_app=WebAppInfo(url=galaxy_url))
        ],
        [
            InlineKeyboardButton("🌐 Open in Web Browser ↗️", url=galaxy_url),
            InlineKeyboardButton(f"📢 {escaped_ch_name}", url=channel_url)
        ]
    ])

    await message.reply_text(text, reply_markup=markup)


@Client.on_message(filters.command(["setstream", "set_stream"]) & filters.private)
async def set_stream_command(client: Client, message: Message):
    """Admin command to view or update the public Stream & Browse URL dynamically in MongoDB."""
    if not Config.is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    current_stream = Config.STREAM_URL or "(Not configured in .env)"
    current_web = Config.WEB_URL or "(Not configured in .env)"
    effective = get_effective_stream_base_url()

    # If called without arguments, display active configuration status
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text(
            "⚡ <b>Stream & Web Catalog Domain Manager:</b>\n\n"
            f"• <b>Active Stream URL:</b> <code>{current_stream}</code>\n"
            f"• <b>Active Web URL:</b> <code>{current_web}</code>\n"
            f"• <b>Effective Base:</b> <code>{effective}</code>\n"
            f"• <b>Catalog Link:</b> <a href=\"{effective}/browse\">{effective}/browse</a>\n\n"
            "<b>How to Change Domain Dynamically:</b>\n"
            "👉 <code>/setstream https://akmovieverse.duckdns.org/</code>\n\n"
            "💡 <i>Changes take effect immediately across all Telegram stream buttons and Web Catalog without restarting the bot!</i>",
            disable_web_page_preview=True
        )
        return

    new_url = parts[1].strip().rstrip("/")
    if not (new_url.startswith("http://") or new_url.startswith("https://")):
        await message.reply_text(
            "❌ <b>Invalid URL Format!</b>\n\n"
            "URL must begin with <code>http://</code> or <code>https://</code>.\n"
            "Example: <code>/setstream https://akmovieverse.duckdns.org/</code>"
        )
        return

    # Normalize trailing slash
    normalized_url = new_url + "/"

    # Update in-memory Config
    Config.STREAM_URL = normalized_url
    Config.WEB_URL = normalized_url

    # Persist in MongoDB bot_settings collection
    await set_bot_setting("stream_url", normalized_url)
    await set_bot_setting("web_url", normalized_url)

    logger.info(f"Admin {message.from_user.id} dynamically updated STREAM_URL to {normalized_url}")

    await message.reply_text(
        "✅ <b>Stream & Web Catalog URL Updated!</b>\n\n"
        f"🌐 <b>New Base Domain:</b> <code>{normalized_url}</code>\n"
        f"🍿 <b>Web Catalog Link:</b> <a href=\"{normalized_url}browse\">{normalized_url}browse</a>\n\n"
        "⚡ <i>Saved permanently to MongoDB! All Telegram stream buttons and web player links will now use this domain automatically.</i>",
        disable_web_page_preview=True
    )


@Client.on_message(filters.command(["browse_btn", "browsebtn", "start_browse"]) & filters.private)
async def toggle_browse_button_command(client: Client, message: Message):
    """Admin command to toggle the '🌐 BROWSE WEB CINEMA' button on /start menu."""
    if not Config.is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    current = getattr(Config, "ENABLE_BROWSE_BUTTON", False)

    if len(parts) < 2 or not parts[1].strip():
        state_str = "🟢 <b>ENABLED (Visible on /start)</b>" if current else "🔴 <b>DISABLED (Hidden from /start)</b>"
        await message.reply_text(
            f"🌐 <b>Start Menu Browse Button Status:</b> {state_str}\n\n"
            "<b>Commands:</b>\n"
            "• <code>/browse_btn on</code> — Show Browse Web Cinema button on /start\n"
            "• <code>/browse_btn off</code> — Hide Browse Web Cinema button from /start"
        )
        return

    action = parts[1].strip().lower()
    if action in ("on", "enable", "true", "yes", "1"):
        Config.ENABLE_BROWSE_BUTTON = True
        await set_bot_setting("enable_browse_button", True)
        await message.reply_text("✅ <b>Browse Web Cinema Button is now ENABLED on /start!</b>")
    elif action in ("off", "disable", "false", "no", "0"):
        Config.ENABLE_BROWSE_BUTTON = False
        await set_bot_setting("enable_browse_button", False)
        await message.reply_text("🔴 <b>Browse Web Cinema Button is now DISABLED and hidden from /start!</b>")
    else:
        await message.reply_text("⚠️ <b>Usage:</b> <code>/browse_btn on</code> or <code>/browse_btn off</code>")
