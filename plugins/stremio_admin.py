import logging
import urllib.parse
from html import escape as html_escape

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.users import is_premium, get_user
from database.stremio import (
    create_or_get_stremio_token,
    reset_stremio_token,
    revoke_stremio_token,
    get_stremio_token,
    get_stremio_stats
)

logger = logging.getLogger("autofilter.stremio_admin")


def _get_stremio_base_url() -> str:
    """Resolve base domain for Stremio manifest links."""
    web_url = getattr(Config, "WEB_URL", None) or getattr(Config, "STREAM_BASE_URL", None)
    if web_url:
        return web_url.rstrip("/")
    fqdn = getattr(Config, "FQDN", None)
    if fqdn:
        proto = "https" if not fqdn.startswith("http") else ""
        return f"{proto}://{fqdn}".rstrip("/") if proto else fqdn.rstrip("/")
    return "https://akmovieverse.duckdns.org"


@Client.on_message(filters.command(["gen_stremio", "setstremio", "stremio"]) & filters.private)
async def generate_stremio_command(client: Client, message: Message):
    """Admin-only command to generate or view secret Stremio VIP Addon link for a user."""
    if not Config.is_admin(message.from_user.id):
        return

    text_parts = message.text.split(None, 1)
    target_user_id = None

    if len(text_parts) > 1 and text_parts[1].strip().lstrip("-").isdigit():
        target_user_id = int(text_parts[1].strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id

    if not target_user_id:
        await message.reply_text(
            "ℹ️ <b>Usage:</b> <code>/gen_stremio &lt;user_id&gt;</code>\n"
            "<i>Or reply to a user's message with</i> <code>/gen_stremio</code>"
        )
        return

    user_is_vip = await is_premium(target_user_id)
    token, is_new = await create_or_get_stremio_token(target_user_id)
    base_url = _get_stremio_base_url()
    
    manifest_url = f"{base_url}/stremio/{token}/manifest.json"
    host_no_scheme = base_url.replace("https://", "").replace("http://", "")
    deep_link = f"stremio://{host_no_scheme}/stremio/{token}/manifest.json"

    vip_badge = "✅ <b>Active VIP Member</b>" if user_is_vip else "⚠️ <b>Not VIP / Inactive</b> (User must be VIP to stream)"
    status_badge = "🆕 <b>Fresh Token Generated</b>" if is_new else "🔑 <b>Existing Active Token</b>"

    reply_text = (
        f"📺 <b>AkMovieVerse — Stremio Smart TV Addon</b>\n\n"
        f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
        f"⭐ <b>VIP Status:</b> {vip_badge}\n"
        f"📊 <b>Token Status:</b> {status_badge}\n\n"
        f"🌐 <b>Manifest HTTPS URL (Copy & paste into Stremio):</b>\n"
        f"<code>{manifest_url}</code>\n\n"
        f"📲 <b>1-Click Install Deep-Link (Android / PC):</b>\n"
        f"<code>{deep_link}</code>\n\n"
        f"🛡️ <b>Security Safeguards:</b>\n"
        f"• 🔒 <b>1-IP Concurrency Lock:</b> Max 1 active TV/device streaming at a time\n"
        f"• 🚫 <b>Sharing Protection:</b> Blocked if friend streams simultaneously\n"
        f"• 🔄 <b>Reset Link:</b> <code>/reset_stremio {target_user_id}</code>\n"
        f"• 🗑️ <b>Revoke Access:</b> <code>/del_stremio {target_user_id}</code>"
    )

    buttons = [
        [InlineKeyboardButton("📲 1-Click Install in Stremio", url=deep_link)],
        [InlineKeyboardButton("🔄 Reset Token", callback_data=f"stremio_reset:{target_user_id}")]
    ]

    await message.reply_text(
        reply_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True
    )


@Client.on_message(filters.command(["reset_stremio", "resetstremio"]) & filters.private)
async def reset_stremio_command(client: Client, message: Message):
    """Admin-only command to destroy old token and issue a fresh un-guessable token."""
    if not Config.is_admin(message.from_user.id):
        return

    text_parts = message.text.split(None, 1)
    target_user_id = None

    if len(text_parts) > 1 and text_parts[1].strip().lstrip("-").isdigit():
        target_user_id = int(text_parts[1].strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id

    if not target_user_id:
        await message.reply_text("ℹ️ <b>Usage:</b> <code>/reset_stremio &lt;user_id&gt;</code>")
        return

    new_token = await reset_stremio_token(target_user_id)
    base_url = _get_stremio_base_url()
    manifest_url = f"{base_url}/stremio/{new_token}/manifest.json"
    host_no_scheme = base_url.replace("https://", "").replace("http://", "")
    deep_link = f"stremio://{host_no_scheme}/stremio/{new_token}/manifest.json"

    reply_text = (
        f"🔄 <b>Stremio Token Reset Successfully!</b>\n\n"
        f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
        f"🚫 <i>All previous addon links have been permanently destroyed!</i>\n\n"
        f"🆕 <b>New Manifest Addon URL:</b>\n"
        f"<code>{manifest_url}</code>\n\n"
        f"📲 <b>New 1-Click Install Link:</b>\n"
        f"<code>{deep_link}</code>"
    )

    await message.reply_text(
        reply_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install", url=deep_link)]]),
        disable_web_page_preview=True
    )


@Client.on_message(filters.command(["del_stremio", "delstremio", "revokestremio"]) & filters.private)
async def revoke_stremio_command(client: Client, message: Message):
    """Admin-only command to deactivate Stremio access for a user."""
    if not Config.is_admin(message.from_user.id):
        return

    text_parts = message.text.split(None, 1)
    target_user_id = None

    if len(text_parts) > 1 and text_parts[1].strip().lstrip("-").isdigit():
        target_user_id = int(text_parts[1].strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id

    if not target_user_id:
        await message.reply_text("ℹ️ <b>Usage:</b> <code>/del_stremio &lt;user_id&gt;</code>")
        return

    success = await revoke_stremio_token(target_user_id)
    if success:
        await message.reply_text(f"🗑️ <b>Stremio VIP access revoked for user</b> <code>{target_user_id}</code>.")
    else:
        await message.reply_text(f"⚠️ No active Stremio token was found for user <code>{target_user_id}</code>.")


@Client.on_message(filters.command(["stremiostats", "stremio_stats"]) & filters.private)
async def stremio_stats_command(client: Client, message: Message):
    """Admin-only live dashboard for Stremio usage."""
    if not Config.is_admin(message.from_user.id):
        return

    stats = await get_stremio_stats()
    text = (
        "📊 <b>AkMovieVerse — Stremio Live Dashboard</b>\n\n"
        f"• 🔑 <b>Total Active VIP Tokens:</b> <code>{stats['total_active_tokens']}</code>\n"
        f"• 📺 <b>Currently Streaming (Last 10m):</b> <code>{stats['currently_streaming']}</code> TV/devices\n"
        f"• 🛡️ <b>Anti-Sharing Policy:</b> <code>1-IP Strict Concurrency Lock</code>\n\n"
        "💡 <i>Tip: Use /gen_stremio &lt;user_id&gt; to issue new VIP TV Addon access.</i>"
    )
    await message.reply_text(text)


@Client.on_callback_query(filters.regex(r"^stremio_reset:(\d+)$"))
async def stremio_reset_callback(client: Client, query):
    """Handle 1-click token reset from inline button."""
    if not Config.is_admin(query.from_user.id):
        await query.answer("❌ Admin permission required.", show_alert=True)
        return

    target_user_id = int(query.data.split(":")[1])
    new_token = await reset_stremio_token(target_user_id)
    base_url = _get_stremio_base_url()
    manifest_url = f"{base_url}/stremio/{new_token}/manifest.json"
    host_no_scheme = base_url.replace("https://", "").replace("http://", "")
    deep_link = f"stremio://{host_no_scheme}/stremio/{new_token}/manifest.json"

    await query.message.edit_text(
        f"🔄 <b>Stremio Token Reset Successfully!</b>\n\n"
        f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
        f"🚫 <i>Previous link destroyed permanently.</i>\n\n"
        f"🆕 <b>New Manifest Addon URL:</b>\n"
        f"<code>{manifest_url}</code>\n\n"
        f"📲 <b>New 1-Click Install:</b>\n"
        f"<code>{deep_link}</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install", url=deep_link)]]),
        disable_web_page_preview=True
    )
    await query.answer("✅ Token reset successfully!")
