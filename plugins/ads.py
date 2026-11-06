import re
import datetime
import logging
import html

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.ads import (
    set_sponsor_ad,
    get_ad_stats,
    delete_sponsor_ad,
    parse_duration_string
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Admin Command: /setad <duration> [Ad Text | URL]
# ==============================================================================

@Client.on_message(filters.command(["setad", "addad", "createad"]))
async def set_ad_command(client: Client, message: Message):
    """Admin tool to activate a time-based dynamic sponsor advertisement."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    text = message.text or ""
    body = re.sub(r"^/(?:setad|addad|createad)(?:@\w+)?\s*", "", text.strip(), flags=re.I).strip()
    if not body:
        return await message.reply_text(
            "📢 <b>SET TIME-BASED SPONSOR AD</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage (With or without brackets):</b>\n"
            "• <code>/setad 1h Ad Title | Target URL</code>\n"
            "• <code>/setad &lt;duration&gt; [Ad Title | Target URL]</code>\n\n"
            "<b>Duration Formats:</b>\n"
            "• <code>1h</code> : 1 Hour (Flash Ad)\n"
            "• <code>24h</code> : 24 Hours (1 Day)\n"
            "• <code>3d</code> : 3 Days\n"
            "• <code>7d</code> : 7 Days (1 Week)\n"
            "• <code>30d</code> : 30 Days (1 Month)\n\n"
            "<b>Examples:</b>\n"
            "• <code>/setad 1h Join AkMovieVerse | https://t.me/AkMovieVerse</code>\n"
            "• <code>/setad 24h [🔥 1XBet 100% Bonus | https://1xbet.com]</code>\n\n"
            "💡 <i>Active ads auto-expire on the exact second. VIP members never see ads!</i>"
        )

    # 1. Extract duration (supports <1h>, 1h, 1hr, 24h, 3d, etc.)
    dur_match = re.match(r"^(?:<)?([0-9]+\s*[a-zA-Z]*)(?:>)?\s+", body)
    if not dur_match:
        return await message.reply_text("❌ <b>Missing duration.</b> Example: <code>/setad 1h Title | https://url</code>")

    dur_str = dur_match.group(1).strip()
    rest = body[dur_match.end():].strip()

    # 2. Extract title and URL (with or without [ ... ])
    if rest.startswith("[") and rest.endswith("]"):
        rest = rest[1:-1].strip()

    if "|" not in rest:
        return await message.reply_text(
            "❌ <b>Invalid format.</b> Title and URL must be separated by a <code>|</code> pipe.\n"
            "<b>Example:</b> <code>/setad 1h Ad Title | https://t.me/mychannel</code>"
        )

    parts = rest.split("|", 1)
    ad_title = parts[0].strip()
    ad_url = parts[1].strip()

    dur_seconds = parse_duration_string(dur_str)
    if not dur_seconds:
        return await message.reply_text("❌ <b>Invalid duration format.</b> Use <code>1h</code>, <code>24h</code>, <code>3d</code>, <code>7d</code>, <code>30d</code>.")

    success, msg, doc = await set_sponsor_ad(
        text=ad_title,
        url=ad_url,
        duration_str=dur_str,
        duration_seconds=dur_seconds,
        created_by=message.from_user.id
    )

    if not success:
        return await message.reply_text(f"❌ <b>Error:</b> {msg}")

    expires_at = doc.get("expires_at")
    exp_str = expires_at.strftime("%d %b %Y, %H:%M UTC") if expires_at else "Auto"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 Test Ad: {ad_title}", url=ad_url)]
    ])

    report = (
        "✅ <b>SPONSOR AD ACTIVATED SUCCESSFULLY!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Ad Text:</b> <code>{html.escape(ad_title)}</code>\n"
        f"🔗 <b>Destination:</b> <code>{html.escape(ad_url)}</code>\n"
        f"⏳ <b>Campaign Duration:</b> <code>{dur_str.upper()}</code>\n"
        f"📅 <b>Expires At:</b> <code>{exp_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📍 <b>Active Placements:</b>\n"
        "• <b>Search Results:</b> Clickable sponsor text link (Zero clutter)\n"
        "• <b>/start Welcome:</b> Eye-catching bottom sponsor button\n"
        "• <b>Web Streaming:</b> Glowing cinema player sponsor banner\n\n"
        "👑 <i>VIP Members will automatically skip all ads!</i>"
    )

    await message.reply_text(report, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /ads or /adstats (Active Campaign Dashboard)
# ==============================================================================

@Client.on_message(filters.command(["ads", "adstats", "activead"]))
async def ad_stats_command(client: Client, message: Message):
    """Admin dashboard to inspect active ad campaign, remaining validity, and views."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    ad = await get_ad_stats()
    if not ad:
        return await message.reply_text(
            "ℹ️ <b>No active sponsor ad found.</b>\n"
            "Use <code>/setad &lt;duration&gt; [Ad Title | URL]</code> to launch a campaign."
        )

    now = datetime.datetime.utcnow()
    expires_at = ad.get("expires_at")
    is_active = ad.get("is_active", False) and (expires_at and expires_at > now)

    status_badge = "🟢 Active" if is_active else "🔴 Expired / Inactive"

    rem_str = "Expired"
    if is_active and expires_at:
        rem_delta = expires_at - now
        days = rem_delta.days
        hours = int(rem_delta.seconds / 3600)
        minutes = int((rem_delta.seconds % 3600) / 60)
        if days > 0:
            rem_str = f"{days} Day(s), {hours} Hour(s)"
        else:
            rem_str = f"{hours} Hour(s), {minutes} Minute(s)"

    ad_text = ad.get("text", "Sponsor")
    ad_url = ad.get("url", "")
    impressions = ad.get("impressions", 0)
    dur_str = ad.get("duration_str", "7d")

    report = (
        "📢 <b>SPONSOR AD DASHBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Status:</b> {status_badge}\n"
        f"• <b>Ad Title:</b> <code>{html.escape(ad_text)}</code>\n"
        f"• <b>Target Link:</b> <code>{html.escape(ad_url)}</code>\n"
        f"• <b>Duration:</b> <code>{dur_str.upper()}</code>\n"
        f"• <b>Time Remaining:</b> <code>{rem_str}</code>\n"
        f"• <b>Impressions (Views):</b> <code>{impressions:,} Views</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Use <code>/delad</code> to immediately revoke this ad campaign.</i>"
    )

    markup = None
    if ad_url:
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔗 Test Link: {ad_text}", url=ad_url)]
        ])

    await message.reply_text(report, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /delad (Revoke Active Ad)
# ==============================================================================

@Client.on_message(filters.command(["delad", "removead", "clearad"]))
async def delete_ad_command(client: Client, message: Message):
    """Admin tool to immediately revoke and stop current sponsor ad."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    deleted = await delete_sponsor_ad()
    if deleted:
        await message.reply_text("🗑️ <b>Active sponsor ad has been successfully revoked and removed!</b>")
    else:
        await message.reply_text("ℹ️ No active sponsor ad was running.")
