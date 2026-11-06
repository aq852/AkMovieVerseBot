import random
import string
import datetime
import logging
import urllib.parse

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.promo import (
    create_promo_code,
    redeem_promo_code,
    get_all_promos,
    delete_promo_code
)

logger = logging.getLogger(__name__)


def generate_random_promo_code(days: int) -> str:
    """Generate a clean branded coupon code (e.g. VIP-7D-X49K)."""
    rand_chars = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"VIP-{days}D-{rand_chars}"


# ==============================================================================
# Admin Command: /genpromo <days> <max_uses> [custom_code]
# ==============================================================================

@Client.on_message(filters.command(["genpromo", "createpromo", "addpromo"]))
async def generate_promo_command(client: Client, message: Message):
    """Admin command to generate a promotional VIP coupon code."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text(
            "🎟️ <b>GENERATE PROMO CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b> <code>/genpromo &lt;days&gt; &lt;max_uses&gt; [custom_code]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/genpromo 7 50 WEEKEND7</code> — <i>7 Days VIP for 50 users</i>\n"
            "• <code>/genpromo 30 10 DIWALI2026</code> — <i>30 Days VIP for 10 users</i>\n"
            "• <code>/genpromo 3 100</code> — <i>Auto-generates random 3-Day code</i>"
        )

    try:
        days = int(args[1])
        max_uses = int(args[2])
    except ValueError:
        return await message.reply_text("❌ <b>Error:</b> <code>days</code> and <code>max_uses</code> must be numbers.")

    if len(args) >= 4:
        code = args[3].strip().upper()
    else:
        code = generate_random_promo_code(days)

    success, msg, doc = await create_promo_code(
        code=code,
        days=days,
        max_uses=max_uses,
        expiry_days=30,
        created_by=message.from_user.id
    )

    if not success:
        return await message.reply_text(f"❌ <b>Error:</b> {msg}")

    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    redeem_link = f"https://t.me/{bot_username}?start=redeem_{code}"
    share_text = (
        f"🎁 <b>GIVEAWAY: {days} DAYS FREE VIP ACCESS!</b>\n\n"
        f"Use coupon code: <code>{code}</code>\n"
        f"• 👥 <b>Limited to:</b> First {max_uses} Users!\n"
        f"• ⚡ Instant direct file downloads with Zero Ads!\n\n"
        f"👉 Tap the button below to redeem instantly:"
    )

    share_url = f"https://t.me/share/url?url={urllib.parse.quote(redeem_link)}&text={urllib.parse.quote(share_text)}"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 1-Click Redeem Link", url=redeem_link)],
        [InlineKeyboardButton("📢 Share to Channel / Group", url=share_url)]
    ])

    report = (
        "✅ <b>PROMO CODE GENERATED SUCCESSFULLY!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎟️ <b>Coupon Code:</b> <code>{code}</code>\n"
        f"💎 <b>VIP Duration:</b> <code>{days} Days</code>\n"
        f"👥 <b>Max Redemptions:</b> <code>{max_uses} Users</code>\n"
        f"🔗 <b>1-Click Claim Link:</b>\n<code>{redeem_link}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Post the link or code in your updates channel to reward members!</i>"
    )

    await message.reply_text(report, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /promos (View Active Promo Codes)
# ==============================================================================

@Client.on_message(filters.command(["promos", "listpromos"]))
async def list_promos_command(client: Client, message: Message):
    """Admin command to list and inspect active promotional codes."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    promos = await get_all_promos(limit=25)
    if not promos:
        return await message.reply_text("ℹ️ <b>No promo codes generated yet.</b> Use <code>/genpromo</code> to create one.")

    lines = ["🎟️ <b>ACTIVE PROMO CODES DASHBOARD</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    now = datetime.datetime.utcnow()

    for idx, p in enumerate(promos, 1):
        code = p.get("code")
        days = p.get("days", 1)
        claimed = p.get("claimed_count", 0)
        max_u = p.get("max_uses", 1)
        exp = p.get("expires_at")
        is_expired = exp and exp < now
        status = "🔴 Expired" if is_expired else ("🟡 Full" if claimed >= max_u else "🟢 Active")

        lines.append(
            f"<b>{idx}.</b> <code>{code}</code> — {status}\n"
            f"   💎 <b>{days} Days</b> | 👥 <code>{claimed}/{max_u} Claimed</code>"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <b>Manage:</b> <code>/delpromo &lt;code&gt;</code> to revoke a code.")
    await message.reply_text("\n".join(lines))


# ==============================================================================
# Admin Command: /delpromo <code>
# ==============================================================================

@Client.on_message(filters.command(["delpromo", "deletepromo", "revokepromo"]))
async def delete_promo_command(client: Client, message: Message):
    """Admin command to revoke and delete a promo code."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("⚠️ <b>Usage:</b> <code>/delpromo &lt;code&gt;</code>\nExample: <code>/delpromo WEEKEND7</code>")

    code = args[1].strip()
    success = await delete_promo_code(code)
    if success:
        await message.reply_text(f"🗑️ <b>Promo code <code>{code.upper()}</code> has been permanently revoked!</b>")
    else:
        await message.reply_text(f"❌ Promo code <code>{code.upper()}</code> was not found.")


# ==============================================================================
# User Command: /redeem <code>
# ==============================================================================

@Client.on_message(filters.command(["redeem", "claim"]))
async def redeem_promo_command(client: Client, message: Message):
    """User command to redeem a promotional VIP coupon code."""
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text(
            "🎟️ <b>REDEEM PROMO CODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Got a special coupon code from our updates channel?\n\n"
            "<b>Usage:</b> <code>/redeem &lt;coupon_code&gt;</code>\n"
            "<b>Example:</b> <code>/redeem WEEKEND7</code>\n\n"
            "💎 <i>Redeeming gives instant VIP Premium access without ads or shorteners!</i>"
        )

    code = args[1].strip()
    user_id = message.from_user.id
    success, msg, days = await redeem_promo_code(code, user_id)

    if not success:
        return await message.reply_text(msg)

    u_mention = message.from_user.mention(message.from_user.first_name)
    congrats_text = (
        "🎉 <b>PROMO CODE REDEEMED SUCCESSFULLY!</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 👤 <b>Member:</b> {u_mention}\n"
        f"• 🎟️ <b>Coupon Code:</b> <code>{code.upper()}</code>\n"
        f"• 💎 <b>VIP Unlocked:</b> <code>{days} Day(s) Premium Pass</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌟 <b>Your Active VIP Perks:</b>\n"
        "• 🚫 No shorteners or verification ads\n"
        "• ⚡ Instant 1-second file delivery\n"
        "• 📦 Unlimited batch downloads\n\n"
        "<i>Enjoy your premium experience! Type any movie title to start searching.</i>"
    )

    await message.reply_text(congrats_text)

    # Optional audit log to Log Channel
    if Config.LOG_CHANNEL:
        try:
            await client.send_message(
                Config.LOG_CHANNEL,
                f"🎟️ <b>#PromoCodeRedeemed</b>\n\n"
                f"• <b>User:</b> {u_mention} (<code>{user_id}</code>)\n"
                f"• <b>Code:</b> <code>{code.upper()}</code>\n"
                f"• <b>Duration:</b> <code>+{days} Days VIP</code>"
            )
        except Exception:
            pass
