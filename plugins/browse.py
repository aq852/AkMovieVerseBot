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
    escaped_ch_name = html.escape(channel_name)

    caption = (
        "🍿 <b>AkMovieVerse — Web Cinema & Catalog</b>\n\n"
        "Browse thousands of high-definition movies, web series, dual-audio releases, and complete seasons directly in your browser!\n\n"
        "✨ <b>Web Cinema Features:</b>\n"
        "• 🎬 <b>In-Browser Cinema Player:</b> Instant 1-click playback\n"
        "• 📺 <b>External Players:</b> MX Player, VLC & M3U Playlist support\n"
        "• 🚀 <b>Lightning Fast Downloads:</b> High-speed web file transfers\n"
        "• 🔍 <b>Smart Live Search:</b> Filter by Movies, Series, Qualities & Audio\n\n"
        f"📢 <b>Official Channel:</b> <a href=\"{channel_url}\">{escaped_ch_name}</a>"
    )

    buttons = [
        [
            InlineKeyboardButton("🌐 OPEN WEB CINEMA CATALOG ↗️", url=browse_url)
        ],
        [
            InlineKeyboardButton("📌 Join Updates Channel ↗️", url=channel_url)
        ]
    ]

    await message.reply_text(
        caption,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True
    )


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
