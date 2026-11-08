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
from database.users import is_premium, get_user_info
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
    web_url = getattr(Config, "WEB_URL", None) or getattr(Config, "STREAM_BASE_URL", None) or getattr(Config, "STREAM_URL", None)
    if web_url:
        return web_url.rstrip("/")
    fqdn = getattr(Config, "FQDN", None)
    if fqdn:
        proto = "https" if not fqdn.startswith("http") else ""
        return f"{proto}://{fqdn}".rstrip("/") if proto else fqdn.rstrip("/")
    return "https://akmovieverse.duckdns.org"


@Client.on_message(filters.command(["gen_stremio", "setstremio", "stremio"]) & filters.private)
async def generate_stremio_command(client: Client, message: Message):
    """Admin command to generate secret Stremio VIP Addon link and notify user directly in DM."""
    # Non-admin self-service: VIP users can fetch their own addon link anytime
    if not Config.is_admin(message.from_user.id):
        target_user_id = message.from_user.id
        user_is_vip = await is_premium(target_user_id)
        if not user_is_vip:
            await message.reply_text(
                "⚠️ <b>AkMovieVerse Stremio Smart TV Addon is an exclusive VIP Perk!</b>\n\n"
                "Upgrade to VIP Premium to stream movies & series directly on your TV/PC without ads.\n"
                "👉 Use /plans to view available subscriptions."
            )
            return

        token, _ = await create_or_get_stremio_token(target_user_id)
        base_url = _get_stremio_base_url()
        manifest_url = f"{base_url}/stremio/{token}/manifest.json"
        install_url = f"{base_url}/stremio/{token}/install"
        user_name = message.from_user.first_name or "VIP Member"

        user_card = (
            f"📺 <b>AkMovieVerse — Your Stremio Smart TV VIP Addon</b> 🎉\n\n"
            f"Hello <b>{html_escape(user_name)}</b>, your VIP Stremio TV Addon is active!\n\n"
            f"🌟 <b>Stream high-speed 4K/1080p Movies & Web Series with Multi-Audio directly inside Stremio on Android TV, Firestick, PC or Mobile.</b>\n\n"
            f"🌐 <b>Addon Manifest URL (Copy & paste into Stremio):</b>\n"
            f"<code>{manifest_url}</code>\n\n"
            f"📲 <b>1-Click Instant Install:</b>\n"
            f"Tap the button below to automatically install into your Stremio app:\n\n"
            f"🛡️ <b>Streaming Policy:</b>\n"
            f"• 🔒 <b>1-Device Active Streaming:</b> Max 1 screen can stream at the same time.\n"
            f"• 🚫 Do not share your addon link with anyone to avoid streaming blocks."
        )
        buttons = [
            [InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)],
            [InlineKeyboardButton("⭐ Check My VIP Plan", callback_data="check_my_plan")]
        ]
        await message.reply_text(user_card, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)
        return

    # Admin mode
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
    install_url = f"{base_url}/stremio/{token}/install"

    vip_badge = "✅ <b>Active VIP Member</b>" if user_is_vip else "⚠️ <b>Not VIP / Inactive</b> (User must be VIP to stream)"
    status_badge = "🆕 <b>Fresh Token Generated</b>" if is_new else "🔑 <b>Existing Active Token</b>"

    # User display name
    user_name = "VIP Member"
    try:
        user_obj = await client.get_users(target_user_id)
        if user_obj and user_obj.first_name:
            user_name = user_obj.first_name
    except Exception:
        pass

    # 1. Send direct DM to the user with 1-Click Install button
    user_stremio_card = (
        f"📺 <b>AkMovieVerse — Your Stremio Smart TV VIP Addon</b> 🎉\n\n"
        f"Hello <b>{html_escape(user_name)}</b>, your VIP Stremio TV Addon has been activated by Admin!\n\n"
        f"🌟 <b>Stream high-speed 4K/1080p Movies & Web Series with Multi-Audio directly inside Stremio on Android TV, Firestick, PC or Mobile.</b>\n\n"
        f"🌐 <b>Addon Manifest URL (Copy & paste into Stremio):</b>\n"
        f"<code>{manifest_url}</code>\n\n"
        f"📲 <b>1-Click Instant Install:</b>\n"
        f"Tap the button below to install directly into your Stremio app:\n\n"
        f"🛡️ <b>Streaming Policy:</b>\n"
        f"• 🔒 <b>1-Device Active Streaming:</b> Max 1 screen can stream at the same time.\n"
        f"• 🚫 Do not share your addon link with anyone to avoid streaming blocks."
    )
    user_buttons = [
        [InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)],
        [InlineKeyboardButton("⭐ Check My VIP Plan", callback_data="check_my_plan")]
    ]
    dm_sent = False
    try:
        await client.send_message(
            target_user_id,
            user_stremio_card,
            reply_markup=InlineKeyboardMarkup(user_buttons),
            disable_web_page_preview=True
        )
        dm_sent = True
    except Exception as e_dm:
        logger.warning(f"Could not deliver Stremio DM to user {target_user_id}: {e_dm}")

    # 2. Reply to Admin
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

    if target_user_id != message.from_user.id:
        if dm_sent:
            reply_text += "\n\n📬 <i>Addon details & 1-Click Install button delivered to user in private chat!</i>"
        else:
            reply_text += "\n\n⚠️ <i>Could not DM user directly (Bot not started in PM or blocked). Please forward them the link above.</i>"

    buttons = [
        [InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)],
        [InlineKeyboardButton("🔄 Reset Token", callback_data=f"stremio_reset:{target_user_id}")]
    ]

    try:
        await message.reply_text(
            reply_text,
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error sending Stremio info: {e}", exc_info=True)
        await message.reply_text(reply_text, disable_web_page_preview=True)


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
    install_url = f"{base_url}/stremio/{new_token}/install"

    reply_text = (
        f"🔄 <b>Stremio Token Reset Successfully!</b>\n\n"
        f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
        f"🚫 <i>All previous addon links have been permanently destroyed!</i>\n\n"
        f"🆕 <b>New Manifest Addon URL:</b>\n"
        f"<code>{manifest_url}</code>\n\n"
        f"📲 <b>New 1-Click Install Link:</b>\n"
        f"<code>{deep_link}</code>"
    )

    try:
        await message.reply_text(
            reply_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install", url=install_url)]]),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error sending reset Stremio message: {e}", exc_info=True)
        await message.reply_text(reply_text, disable_web_page_preview=True)

    if target_user_id != message.from_user.id:
        try:
            await client.send_message(
                target_user_id,
                f"🔄 <b>Your Stremio Smart TV VIP Addon Has Been Refreshed!</b>\n\n"
                f"Previous links have been destroyed. Tap below to install your updated addon:\n\n"
                f"🌐 <b>Manifest URL:</b>\n<code>{manifest_url}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)]]),
                disable_web_page_preview=True
            )
        except Exception:
            pass


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
        if target_user_id != message.from_user.id:
            try:
                await client.send_message(
                    target_user_id,
                    "🗑️ <b>Your Stremio Smart TV VIP Addon access has been revoked or expired.</b>\n\n"
                    "To renew and regain high-speed TV streaming, contact the admin or check /plans."
                )
            except Exception:
                pass
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
    install_url = f"{base_url}/stremio/{new_token}/install"

    try:
        await query.message.edit_text(
            f"🔄 <b>Stremio Token Reset Successfully!</b>\n\n"
            f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
            f"🚫 <i>Previous link destroyed permanently.</i>\n\n"
            f"🆕 <b>New Manifest Addon URL:</b>\n"
            f"<code>{manifest_url}</code>\n\n"
            f"📲 <b>New 1-Click Install:</b>\n"
            f"<code>{deep_link}</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install", url=install_url)]]),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error editing stremio reset message: {e}", exc_info=True)
    await query.answer("✅ Token reset successfully!")

    if target_user_id != query.from_user.id:
        try:
            await client.send_message(
                target_user_id,
                f"🔄 <b>Your Stremio Smart TV VIP Addon Has Been Refreshed!</b>\n\n"
                f"Previous links have been destroyed. Tap below to install your updated addon:\n\n"
                f"🌐 <b>Manifest URL:</b>\n<code>{manifest_url}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 1-Click Install in Stremio", url=install_url)]]),
                disable_web_page_preview=True
            )
        except Exception:
            pass
