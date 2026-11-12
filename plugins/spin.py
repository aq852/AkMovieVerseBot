import time
import random
import asyncio
import datetime
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

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


def get_current_iso_week() -> str:
    """Return string representing current year and ISO week number (e.g. '2026-W46')."""
    return datetime.datetime.utcnow().strftime("%Y-W%W")


@Client.on_message(filters.command(["spin", "luckyspin"]) & filters.private)
async def spin_command_handler(client: Client, message: Message):
    """Entry point for the Daily Lucky Spin wheel."""
    user_id = message.from_user.id
    # Record daily active interaction to advance streak
    profile = await record_daily_activity(user_id)
    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)

    bot_username = Config.BOT_USERNAME or "TheFlixifyBot"
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
        f"Neeche diye gaye button par tap karke wheel ghumayein aur jeetein <b>Coins & VIP Rewards</b>!"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 SPIN THE WHEEL! 🎲", callback_data="spin_roll:do")]
    ])
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^spin_roll:do$"))
async def spin_roll_callback_handler(client: Client, query: CallbackQuery):
    """Execute spinning animation and determine prize using silent probability gates."""
    user_id = query.from_user.id
    allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)

    if not allowed:
        return await query.answer("⏰ Aaj ka spin use ho chuka hai!", show_alert=True)

    # 1. Consume spin
    consumed = await consume_spin(user_id, spin_type)
    if not consumed:
        return await query.answer("Spin execute nahi ho saka. Kripya dubara koshish karein.", show_alert=True)

    await query.answer("🎲 Wheel ghoom raha hai...")

    # 2. Animated visual frames in Telegram
    frames = [
        "🎰 <b>[ 🪙 5 COINS | 👑 VIP | 🪙 10 COINS ]</b>\n🎲 <i>Wheel tezi se ghoom raha hai...</i>",
        "🎰 <b>[ 💎 3-DAY VIP | 🪙 20 COINS | 🪙 5 COINS ]</b>\n🎲 <i>Slow ho raha hai...</i>",
        "🎰 <b>[ 🪙 10 COINS | 👑 1-DAY VIP | 🪙 5 COINS ]</b>\n🎲 <i>Nateeja aane wala hai...!</i>"
    ]
    for frame in frames:
        try:
            await query.message.edit_text(frame)
            await asyncio.sleep(0.7)
        except Exception:
            pass

    # 3. Silent Probability Gate
    profile = await get_loyalty_profile(user_id)
    streak = profile.get("longest_streak", 1)
    roll = random.random() * 100.0  # 0.00 to 100.00

    prize_type = "coins"
    prize_val = 5

    # Tier 3: Loyal Legend (15+ Days Streak)
    if streak >= 15:
        # Check weekly global cap for 3-day VIP
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

    # 4. Award Prize & Build Announcement
    is_jackpot = False
    if prize_type == "coins":
        new_balance = await add_coins(user_id, prize_val, reason="spin_wheel_win")
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

    # 5. Send Social Proof Card to LOG_CHANNEL for Admin Broadcast
    if is_jackpot and Config.LOG_CHANNEL:
        try:
            winner_name = query.from_user.first_name or "Flixify User"
            won_title = "👑 1-Day VIP Pass" if prize_type == "vip_1d" else "💎 3-Day Mega VIP Pass (Rare 🌟)"
            now_ist_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%d %b %Y, %I:%M %p IST")

            log_text = (
                f"🎰 <b>FLIXIFY LUCKY SPIN • JACKPOT ALERT!</b> 🌟\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Winner:</b> <a href='tg://user?id={user_id}'>{winner_name}</a> (<code>{user_id}</code>)\n"
                f"🏅 <b>Streak Rank:</b> <code>{profile.get('lifetime_rank')}</code> (<b>{profile.get('current_streak', 1)} Days</b>)\n"
                f"🎁 <b>Won Prize:</b> <b>{won_title}</b>\n"
                f"⏰ <b>Time:</b> <code>{now_ist_str}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Proof of real user reward drop from @TheFlixifyBot. Tap below to showcase in your Updates Channel!</i>"
            )
            pub_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Publish to Updates Channel ↗️", callback_data=f"spin_pub:{user_id}:{prize_type}")]
            ])
            await client.send_message(Config.LOG_CHANNEL, log_text, reply_markup=pub_markup)
        except Exception as e_log:
            logger.debug(f"Could not send jackpot alert to log channel: {e_log}")


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
        # Edit log button to indicate published
        await query.message.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("✅ Published to Channel", callback_data="none")]])
        )
    except Exception as e:
        await query.answer(f"Failed to publish: {e}", show_alert=True)
