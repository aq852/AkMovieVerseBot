import time
import logging
from html import escape as html_escape

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message, CallbackQuery, InlineQuery,
        InlineKeyboardMarkup, InlineKeyboardButton,
        InlineQueryResultArticle, InputTextMessageContent
    )
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message, CallbackQuery, InlineQuery,
        InlineKeyboardMarkup, InlineKeyboardButton,
        InlineQueryResultArticle, InputTextMessageContent
    )

from config import Config
from database.mongo import set_bot_setting

logger = logging.getLogger(__name__)

# In-memory per-user cooldown tracker for maintenance notifications (seconds)
_USER_NOTICE_COOLDOWN: dict[int, float] = {}


async def set_maintenance_mode(enabled: bool, reason: str = "") -> bool:
    """Toggle maintenance mode state and update MongoDB persistence."""
    Config.MAINTENANCE_MODE = enabled
    await set_bot_setting("maintenance_mode", enabled)
    if reason:
        clean_reason = reason.strip()
        Config.MAINTENANCE_REASON = clean_reason
        await set_bot_setting("maintenance_reason", clean_reason)
    logger.info(f"Maintenance Mode updated: enabled={enabled}, reason='{Config.MAINTENANCE_REASON}'")
    return True


def get_maintenance_panel_markup() -> InlineKeyboardMarkup:
    """Build interactive control buttons for /maintenance dashboard."""
    is_active = getattr(Config, "MAINTENANCE_MODE", False)
    if is_active:
        toggle_btn = InlineKeyboardButton("🟢 Disable Maintenance (Go Live)", callback_data="maint_disable")
    else:
        toggle_btn = InlineKeyboardButton("🔴 Enable Maintenance (Lock Bot)", callback_data="maint_enable")

    buttons = [
        [toggle_btn],
        [
            InlineKeyboardButton("🔄 Refresh Status", callback_data="maint_refresh"),
            InlineKeyboardButton("❌ Close", callback_data="maint_close")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def format_maintenance_panel_text() -> str:
    """Format the admin maintenance control panel text."""
    is_active = getattr(Config, "MAINTENANCE_MODE", False)
    status_tag = "🔴 <b>ACTIVE</b> <i>(Users Blocked, Admins Allowed)</i>" if is_active else "🟢 <b>INACTIVE</b> <i>(Bot Live for All Users)</i>"
    reason = getattr(Config, "MAINTENANCE_REASON", "Database indexing & system upgrade in progress.")

    return (
        "🛠️ <b>AkMovieVerse — Maintenance Mode Manager</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Current Status:</b> {status_tag}\n"
        f"📌 <b>Active Reason:</b> <code>{html_escape(reason)}</code>\n\n"
        "<b>📖 Quick Commands:</b>\n"
        "• <code>/maintenance on [reason]</code> — Activate maintenance\n"
        "• <code>/maintenance off</code> — Deactivate & resume normal operations\n"
        "• <i>Alias:</i> <code>/maint on</code> | <code>/maint off</code>\n\n"
        "💡 <i>Admins bypass maintenance automatically and can run /index, /post, and all tools without restrictions.</i>"
    )


# =========================================================================
# 1. High-Priority Global Interceptors (group = -1)
# =========================================================================

@Client.on_message(group=-1)
async def maintenance_message_interceptor(client: Client, message: Message):
    """Intercept normal user messages and prevent downstream execution during maintenance."""
    if not getattr(Config, "MAINTENANCE_MODE", False):
        return

    # Never block channel posts (e.g. database channel media listener)
    if message.chat and getattr(message.chat, "type", None) and getattr(message.chat.type, "value", str(message.chat.type)) in ("channel", "enums.ChatType.CHANNEL"):
        return

    user = message.from_user
    if not user:
        return

    # Admins always bypass maintenance mode
    if Config.is_admin(user.id):
        return

    # Rate limit notification to once per 15s per user to prevent bot FloodWait
    now = time.time()
    last_notice = _USER_NOTICE_COOLDOWN.get(user.id, 0)
    if now - last_notice > 15.0:
        _USER_NOTICE_COOLDOWN[user.id] = now
        reason = getattr(Config, "MAINTENANCE_REASON", "Database indexing & system upgrade in progress.")
        channel_url = getattr(Config, "CHANNEL_URL", None) or "https://t.me/AkMovieVerse"
        support_url = getattr(Config, "SUPPORT_URL", None)

        buttons = []
        if channel_url:
            buttons.append(InlineKeyboardButton("📢 Updates Channel", url=channel_url))
        if support_url:
            buttons.append(InlineKeyboardButton("💬 Support", url=support_url))

        markup = InlineKeyboardMarkup([buttons]) if buttons else None

        notice_text = (
            "🛠️ <b>AkMovieVerse — Scheduled Maintenance</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Our systems are currently undergoing scheduled maintenance.\n\n"
            f"📌 <b>Reason:</b> <i>{html_escape(reason)}</i>\n\n"
            "⏳ <b>Status:</b> We are working on database upgrades and will be back shortly.\n"
            "<i>All file downloads, searches, and streaming will resume automatically!</i>"
        )
        try:
            await message.reply_text(notice_text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass

    # Stop propagation so no downstream handlers (/start, filters, downloader, etc.) execute
    message.stop_propagation()


@Client.on_callback_query(group=-1)
async def maintenance_callback_interceptor(client: Client, query: CallbackQuery):
    """Intercept user inline button clicks during maintenance."""
    if not getattr(Config, "MAINTENANCE_MODE", False):
        return

    user = query.from_user
    if not user or Config.is_admin(user.id):
        return

    reason = getattr(Config, "MAINTENANCE_REASON", "Scheduled maintenance in progress.")
    try:
        await query.answer(
            f"🛠️ System Maintenance Active!\n\n{reason[:120]}\n\nPlease check back shortly.",
            show_alert=True
        )
    except Exception:
        pass

    query.stop_propagation()


@Client.on_inline_query(group=-1)
async def maintenance_inline_interceptor(client: Client, inline_query: InlineQuery):
    """Intercept inline searches during maintenance."""
    if not getattr(Config, "MAINTENANCE_MODE", False):
        return

    user = inline_query.from_user
    if not user or Config.is_admin(user.id):
        return

    reason = getattr(Config, "MAINTENANCE_REASON", "Scheduled maintenance in progress.")
    try:
        results = [
            InlineQueryResultArticle(
                title="🛠️ AkMovieVerse Under Maintenance",
                description=f"Reason: {reason[:60]}",
                input_message_content=InputTextMessageContent(
                    f"🛠️ <b>AkMovieVerse is currently under maintenance:</b>\n<i>{html_escape(reason)}</i>"
                )
            )
        ]
        await inline_query.answer(results, cache_time=5)
    except Exception:
        pass

    inline_query.stop_propagation()


# =========================================================================
# 2. Admin Command & Interactive Controls
# =========================================================================

@Client.on_message(filters.command(["maintenance", "maint"]) & filters.private)
async def maintenance_command_handler(client: Client, message: Message):
    """Admin command to view status or toggle maintenance mode."""
    if not Config.is_admin(message.from_user.id):
        return

    text = message.text or ""
    parts = text.split(maxsplit=2)

    # 1. Sub-command: /maintenance on [optional reason]
    if len(parts) > 1 and parts[1].lower() in ("on", "enable", "1", "true"):
        reason = parts[2].strip() if len(parts) > 2 else ""
        await set_maintenance_mode(True, reason=reason)
        panel_text = format_maintenance_panel_text()
        panel_markup = get_maintenance_panel_markup()
        return await message.reply_text(
            f"🔴 <b>Maintenance Mode Activated!</b>\n\n"
            f"Normal users are now blocked with maintenance notices.\n"
            f"📌 <b>Reason:</b> <code>{html_escape(Config.MAINTENANCE_REASON)}</code>\n\n"
            f"💡 <i>You can now safely run heavy indexing, backups, or database updates!</i>",
            reply_markup=panel_markup
        )

    # 2. Sub-command: /maintenance off
    elif len(parts) > 1 and parts[1].lower() in ("off", "disable", "0", "false"):
        await set_maintenance_mode(False)
        panel_markup = get_maintenance_panel_markup()
        return await message.reply_text(
            "🟢 <b>Maintenance Mode Deactivated!</b>\n\n"
            "The bot is now fully LIVE and accessible to all users for search & downloads.",
            reply_markup=panel_markup
        )

    # 3. Default: Display interactive control dashboard
    panel_text = format_maintenance_panel_text()
    panel_markup = get_maintenance_panel_markup()
    await message.reply_text(panel_text, reply_markup=panel_markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^maint_"))
async def maintenance_callback_handler(client: Client, query: CallbackQuery):
    """Handle maintenance control panel callbacks."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied! Admins only.", show_alert=True)

    data = query.data

    if data == "maint_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer("Panel closed.")

    elif data == "maint_enable":
        await set_maintenance_mode(True)
        await query.answer("🔴 Maintenance Mode Enabled! Normal users are blocked.", show_alert=True)

    elif data == "maint_disable":
        await set_maintenance_mode(False)
        await query.answer("🟢 Maintenance Mode Disabled! Bot is now LIVE.", show_alert=True)

    elif data == "maint_refresh":
        await query.answer("Refreshed.")

    # Refresh panel display
    try:
        panel_text = format_maintenance_panel_text()
        panel_markup = get_maintenance_panel_markup()
        await query.message.edit_text(panel_text, reply_markup=panel_markup, disable_web_page_preview=True)
    except Exception:
        pass
