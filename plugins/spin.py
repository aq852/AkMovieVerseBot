import time
import random
import asyncio
import datetime
import logging
import hmac
import hashlib

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        CallbackQuery,
        WebAppInfo
    )
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        CallbackQuery,
        WebAppInfo
    )

from config import Config
from database.loyalty import (
    get_loyalty_profile,
    record_daily_activity,
    can_spin_today,
    consume_spin,
    add_coins
)
from database.users import add_premium_user
from database.mongo import get_bot_setting, set_bot_setting

logger = logging.getLogger("flixify.spin")


def generate_spin_token(user_id: int) -> str:
    """Generate secure HMAC-SHA256 signature for Telegram WebApp wheel authentication."""
    secret = (getattr(Config, "BOT_TOKEN", None) or "flixify_spin_secret_2026").encode()
    return hmac.new(secret, f"spin_{user_id}".encode(), hashlib.sha256).hexdigest()[:16]


def verify_spin_token(user_id: int, token: str) -> bool:
    """Verify HMAC signature to prevent unauthorized or spoofed spins."""
    expected = generate_spin_token(user_id)
    return hmac.compare_digest(expected, str(token).strip())


def get_current_iso_week() -> str:
    """Return string representing current year and ISO week number (e.g. '2026-W46')."""
    return datetime.datetime.utcnow().strftime("%Y-W%W")


async def execute_spin_roll(client: Client, user_id: int, user_first_name: str = "Player") -> tuple[bool, str, dict]:
    """Core spin resolution engine with silent probability gate and weekly jackpot throttle.
    Returns (success: bool, result_message: str, details_dict: dict).
    """
    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)
    if not allowed:
        return False, "cooldown", {"cooldown_seconds": cooldown_secs}

    consumed = await consume_spin(user_id, spin_type)
    if not consumed:
        return False, "failed_to_consume", {}

    profile = await get_loyalty_profile(user_id)
    streak = profile.get("longest_streak", 1)
    roll = random.random() * 100.0  # 0.00 to 100.00

    prize_type = "coins"
    prize_val = 5

    # Tier 3: Loyal Legend (15+ Days Streak)
    if streak >= 15:
        current_week = get_current_iso_week()
        last_mega_winner_week = await get_bot_setting("last_mega_jackpot_week", "")
        can_win_mega = (last_mega_winner_week != current_week)

        if roll < 0.1 and can_win_mega:
            prize_type = "vip_3d"
            prize_val = 3
            await set_bot_setting("last_mega_jackpot_week", current_week)
        elif roll < 3.5:
            prize_type = "vip_1d"
            prize_val = 1
        elif roll < 18.0:
            prize_type = "coins"
            prize_val = 20
        elif roll < 48.0:
            prize_type = "coins"
            prize_val = 10
        else:
            prize_type = "coins"
            prize_val = 5

    # Tier 2: Silver Cinephile (7 - 14 Days Streak)
    elif streak >= 7:
        if roll < 2.5:
            prize_type = "vip_1d"
            prize_val = 1
        elif roll < 18.0:
            prize_type = "coins"
            prize_val = 20
        elif roll < 48.0:
            prize_type = "coins"
            prize_val = 10
        else:
            prize_type = "coins"
            prize_val = 5

    # Tier 1: Newbie (Day 1 - 6) -> 100% Coins Only
    else:
        if roll < 15.0:
            prize_type = "coins"
            prize_val = 20
        elif roll < 45.0:
            prize_type = "coins"
            prize_val = 10
        else:
            prize_type = "coins"
            prize_val = 5

    # Map prize to wheel slice target segment (0 through 7)
    # Segments:
    # 0: 5 Coins, 1: 1-Day VIP, 2: 10 Coins, 3: Direct Pass, 4: 20 Coins, 5: 5 Coins, 6: 3-Day VIP, 7: 10 Coins
    if prize_type == "coins":
        if prize_val == 20:
            target_segment = 4
        elif prize_val == 10:
            target_segment = random.choice([2, 7])
        else:
            target_segment = random.choice([0, 5])
    elif prize_type == "vip_1d":
        target_segment = 1
    elif prize_type == "vip_3d":
        target_segment = 6
    else:
        target_segment = 3

    is_jackpot = False
    new_balance = profile.get("coins", 0)

    if prize_type == "coins":
        new_balance = await add_coins(user_id, prize_val, reason="spin_wheel_win")
        won_title = f"+{prize_val} Flixify Coins"
        result_text = (
            f"🎉 <b>MUBARAK HO!</b> 🥳\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Aapne jeete hain: 🪙 <b>+{prize_val} Flixify Coins!</b>\n\n"
            f"💰 <b>Naya Balance:</b> <code>{new_balance} Coins</code>\n"
            f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank', '🌟 Newbie')}</code>\n"
            f"🔥 <b>Active Streak:</b> <code>{profile.get('current_streak', 1)} Days</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>In coins ko jama karke aap <b>/store</b> se Direct Passes aur VIP khareed sakte hain!</i>"
        )
    elif prize_type == "vip_1d":
        is_jackpot = True
        await add_premium_user(user_id, days=1)
        won_title = "👑 1-Day Full VIP Pass"
        result_text = (
            f"👑 <b>JACKPOT WINNER! VIP UNLOCKED!</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Aapne jeeta hai: 👑 <b>24-Hour Full VIP Access!</b>\n\n"
            f"⚡ <b>Fayde:</b> Unlimited ad-free streaming & instant downloads activated!\n"
            f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Enjoy your VIP day! Movies search karke maze lijiye."
        )
    elif prize_type == "vip_3d":
        is_jackpot = True
        await add_premium_user(user_id, days=3)
        won_title = "💎 3-Day Mega VIP Pass (Rare 🌟)"
        result_text = (
            f"💎 <b>ULTIMATE MEGA JACKPOT WINNER!</b> 🌟🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Bhai aapki kismat aag hai! Aapne jeeta hai:\n"
            f"💎 <b>3-Day Full Mega VIP Pass! (72 Hours)</b>\n\n"
            f"⚡ <b>Perks:</b> Zero ads, ultra-fast streaming & unlimited direct downloads!\n"
            f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank')}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Congratulations on your ultimate win!"
        )

    # Social Proof Card to LOG_CHANNEL for Admin Broadcast
    if is_jackpot and Config.LOG_CHANNEL and client:
        try:
            now_ist_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%d %b %Y, %I:%M %p IST")
            log_text = (
                f"🎰 <b>FLIXIFY LUCKY SPIN • JACKPOT ALERT!</b> 🌟\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Winner:</b> <a href='tg://user?id={user_id}'>{user_first_name}</a> (<code>{user_id}</code>)\n"
                f"🏅 <b>Streak Rank:</b> <code>{profile.get('lifetime_rank')}</code> (<b>{profile.get('current_streak', 1)} Days</b>)\n"
                f"🎁 <b>Won Prize:</b> <b>{won_title}</b>\n"
                f"⏰ <b>Time:</b> <code>{now_ist_str}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Real user jackpot win! Tap below to publish social proof into your Updates Channel.</i>"
            )
            pub_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Publish to Updates Channel ↗️", callback_data=f"spin_pub:{user_id}:{prize_type}")]
            ])
            await client.send_message(Config.LOG_CHANNEL, log_text, reply_markup=pub_markup)
        except Exception as e_log:
            logger.debug(f"Could not send jackpot alert to log channel: {e_log}")

    details = {
        "prize_type": prize_type,
        "prize_val": prize_val,
        "target_segment": target_segment,
        "item_title": won_title,
        "new_balance": new_balance,
        "streak": profile.get("current_streak", 1),
        "rank": profile.get("lifetime_rank", "🌟 Newbie")
    }
    return True, result_text, details


@Client.on_message(filters.command(["spin", "luckyspin"]) & filters.private)
async def spin_command_handler(client: Client, message: Message):
    """Entry point for the Daily Lucky Spin wheel with interactive WebApp & In-Chat options."""
    user_id = message.from_user.id
    # Record daily active interaction to advance streak
    profile = await record_daily_activity(user_id)
    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)

    bot_username = client.me.username if client.me else (Config.BOT_USERNAME or "TheFlixifyBot")
    ref_link = f"https://t.me/{bot_username}?start=spin_{user_id}"

    if not allowed:
        hours = cooldown_secs // 3600
        minutes = (cooldown_secs % 3600) // 60
        timer_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

        text = (
            f"⏰ <b>Aaj Ka Free Spin Use Ho Chuka Hai!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User:</b> {message.from_user.first_name}\n"
            f"🪙 <b>Wallet Balance:</b> <code>{profile.get('coins', 0)} Coins</code>\n"
            f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank', '🌟 Newbie')}</code>\n"
            f"🔥 <b>Current Streak:</b> <code>{profile.get('current_streak', 1)} Days</code>\n\n"
            f"⏳ <b>Agla Free Spin Available:</b> <code>{timer_str}</code> (Raat 12:00 AM IST)\n\n"
            f"🚀 <b>Intazar Nahi Karna?</b>\n"
            f"Apne dost ko bot share karein! Har 1 naye dost ke aane par aapko <b>+1 Instant Spin</b> milega!"
        )
        share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20AkMovieVerse%20Bot%20for%20Fast%20Movies%20%26%20Daily%20Lucky%20Spin!"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Invite Friend (+1 Spin) ↗️", url=share_url)],
            [
                InlineKeyboardButton("👛 Wallet / Store", callback_data="spin_nav:store"),
                InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
            ]
        ])
        return await message.reply_text(text, reply_markup=markup)

    # User is authorized to spin
    label = "🎁 Free Daily Spin" if spin_type == "free" else f"⚡ Extra Referral Spin ({ref_spins} Left)"
    text = (
        f"🎰 <b>FLIXIFY LUCKY SPIN WHEEL</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Player:</b> {message.from_user.first_name}\n"
        f"🪙 <b>Balance:</b> <code>{profile.get('coins', 0)} Coins</code>\n"
        f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank', '🌟 Newbie')}</code>\n"
        f"🔥 <b>Streak:</b> <code>{profile.get('current_streak', 1)} Days</code>\n\n"
        f"🎯 <b>Spin Status:</b> <code>{label} Available!</code>\n\n"
        f"✨ <i>Real 3D interactive spinning wheel dekhne ke liye neeche button dabayein!</i>"
    )

    base_web = (Config.STREAM_URL or Config.WEB_URL or "https://akmovieverse.duckdns.org").rstrip("/")
    token = generate_spin_token(user_id)
    webapp_url = f"{base_web}/spin?uid={user_id}&tok={token}"

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎡 OPEN 3D LUCKY WHEEL (Visual) 🎰", web_app=WebAppInfo(url=webapp_url))
        ],
        [
            InlineKeyboardButton("🎲 Quick Spin In-Chat ⚡", callback_data="spin_roll:do")
        ],
        [
            InlineKeyboardButton("👛 Wallet / Store", callback_data="spin_nav:store"),
            InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
        ]
    ])
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^spin_roll:do$"))
async def spin_roll_callback_handler(client: Client, query: CallbackQuery):
    """Execute dynamic multi-frame mechanical casino slot reel in chat."""
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "Player"

    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)
    if not allowed:
        return await query.answer("⏰ Aaj ka spin use ho chuka hai!", show_alert=True)

    await query.answer("🎲 Casino reels ghoom rahe hain...")

    # Multi-frame mechanical slot animation
    frames = [
        (
            "🎰 <b>FLIXIFY WHEEL OF FORTUNE</b> 🌟\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "╔═════════════════════════════╗\n"
            "║  🪙 5c  │  👑 VIP │  🪙 10c ║\n"
            "╠═════════════════════════════╣\n"
            "▶ ⟦  ⚡ PASS │  🪙 20c │  👑 VIP  ⟧ ◀\n"
            "╠═════════════════════════════╣\n"
            "║  💎 3D  │  🪙 5c  │  ⚡ PASS║\n"
            "╚═════════════════════════════╝\n"
            "🎲 <i>Reels tezi se ghoom rahe hain... [ ⚡░░░░░░░ ] 15%</i>"
        ),
        (
            "🎰 <b>FLIXIFY WHEEL OF FORTUNE</b> 🌟\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "╔═════════════════════════════╗\n"
            "║  👑 VIP │  ⚡ PASS│  💎 3D  ║\n"
            "╠═════════════════════════════╣\n"
            "▶ ⟦  🪙 10c │  👑 VIP │  🪙 5c   ⟧ ◀\n"
            "╠═════════════════════════════╣\n"
            "║  🪙 20c │  🪙 10c │  👑 VIP ║\n"
            "╚═════════════════════════════╝\n"
            "🎲 <i>Wheel top speed par hai... [ ⚡⚡⚡⚡░░░ ] 55%</i>"
        ),
        (
            "🎰 <b>FLIXIFY WHEEL OF FORTUNE</b> 🌟\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "╔═════════════════════════════╗\n"
            "║  ⚡ PASS│  💎 3D  │  🪙 20c ║\n"
            "╠═════════════════════════════╣\n"
            "▶ ⟦  🪙 5c  │  🪙 10c │  ⚡ PASS ⟧ ◀\n"
            "╠═════════════════════════════╣\n"
            "║  👑 VIP │  🪙 20c │  🪙 5c  ║\n"
            "╚═════════════════════════════╝\n"
            "🎲 <i>Brakes lag rahe hain... [ ⚡⚡⚡⚡⚡⚡░ ] 85%</i>"
        )
    ]

    for frame in frames:
        try:
            await query.message.edit_text(frame)
            await asyncio.sleep(0.7)
        except Exception:
            pass

    # Execute backend prize roll
    success, result_text, details = await execute_spin_roll(client, user_id, user_name)
    if not success:
        return await query.message.edit_text("❌ Spin execute nahi ho saka. Kripya thodi der baad dubara koshish karein.")

    won_icon = "🪙" if details["prize_type"] == "coins" else ("👑" if details["prize_type"] == "vip_1d" else "💎")
    won_label = details["item_title"]

    # Final stopped and locked frame
    locked_frame = (
        "🎰 <b>FLIXIFY WHEEL OF FORTUNE</b> 🌟\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "╔═════════════════════════════╗\n"
        "║  💎 3D  │  ⚡ PASS│  👑 VIP ║\n"
        "╠═════════════════════════════╣\n"
        f"▶ ⟦  {won_icon} {won_label}  ⟧ ◀\n"
        "╠═════════════════════════════╣\n"
        "║  🪙 5c  │  🪙 20c │  🪙 5c  ║\n"
        "╚═════════════════════════════╝\n"
        "🎯 <b>STOPPED & LOCKED!</b>"
    )
    try:
        await query.message.edit_text(locked_frame)
        await asyncio.sleep(0.8)
    except Exception:
        pass

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👛 Wallet / Store", callback_data="spin_nav:store"),
            InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
        ]
    ])
    try:
        await query.message.edit_text(result_text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^spin_pub:(\d+):(vip_1d|vip_3d)$"))
async def spin_publish_jackpot_callback(client: Client, query: CallbackQuery):
    """Admin callback to publish jackpot social proof card to UPDATES_CHANNEL."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("Sirf bot admins is post ko broadcast kar sakte hain.", show_alert=True)

    if not Config.UPDATES_CHANNEL:
        return await query.answer("Config.UPDATES_CHANNEL configure nahi hai!", show_alert=True)

    data = query.data.split(":")
    winner_id = int(data[1])
    prize_type = data[2]

    won_title = "👑 1-Day Full VIP Pass" if prize_type == "vip_1d" else "💎 3-Day Mega VIP Access!"
    bot_username = Config.BOT_USERNAME or "TheFlixifyBot"

    pub_text = (
        f"🎉 <b>LUCKY SPIN JACKPOT WINNER!</b> 🎰🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Congratulations to our loyal member for hitting the jackpot on @{bot_username}!\n\n"
        f"👤 <b>Winner ID:</b> <code>{winner_id}</code>\n"
        f"🎁 <b>Won Prize:</b> <b>{won_title}</b>\n\n"
        f"✨ <i>Roz subah bot mein aakar Lucky Spin ghumayein aur paayein Coins, VIP Passes aur Direct Downloads bilkul FREE!</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    pub_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 Try Your Luck (Free Spin) ↗️", url=f"https://t.me/{bot_username}?start=spin")]
    ])

    try:
        await client.send_message(Config.UPDATES_CHANNEL, pub_text, reply_markup=pub_markup)
        await query.answer("✅ Social proof successfully published to Updates Channel!", show_alert=True)
        await query.message.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("✅ Published to Channel", callback_data="none")]])
        )
    except Exception as e:
        await query.answer(f"Failed to publish: {e}", show_alert=True)
