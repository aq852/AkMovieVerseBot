import logging
import datetime
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
    add_coins,
    deduct_coins,
    get_top_leaderboard,
    get_seconds_until_midnight_ist
)
from database.store import (
    get_all_store_items,
    get_store_item_by_id,
    add_or_update_store_item,
    delete_store_item,
    purchase_store_item
)

logger = logging.getLogger("flixify.store_plugin")


def build_store_text_and_markup(profile: dict, items: list[dict], bot_username: str) -> tuple[str, InlineKeyboardMarkup]:
    """Render the main coin store catalog interface."""
    coins = profile.get("coins", 0)
    streak = profile.get("current_streak", 1)
    rank = profile.get("lifetime_rank", "🌟 Newbie Watcher")
    passes = profile.get("bonus_direct_passes", 0)

    text = (
        f"🛒 <b>FLIXIFY REWARDS STORE</b> 🪙\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Aapka Wallet:</b>\n"
        f"• 💰 <b>Balance:</b> <code>{coins:,} Coins</code>\n"
        f"• 🏅 <b>Rank Badge:</b> <code>{rank}</code>\n"
        f"• 🔥 <b>Daily Streak:</b> <code>{streak} Days</code>\n"
        f"• ⚡ <b>Direct Passes:</b> <code>{passes} Available</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛍️ <b>Available Rewards & Upgrades:</b>\n\n"
    )

    if not items:
        text += "<i>Store mein filhaal koi items uplabdh nahi hain. Kripya baad mein check karein!</i>\n"
    else:
        for idx, it in enumerate(items, 1):
            title = it.get("title", "Item")
            price = it.get("price_coins", 0)
            desc = it.get("description", "")
            text += f"{idx}. <b>{title}</b> — 🪙 <code>{price} Coins</code>\n"
            if desc:
                text += f"   <i>{desc}</i>\n"
            text += "\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Neeche diye gaye buttons se kisi bhi item par tap karke khareedein! Coins kam hain toh <b>/spin</b> ghumayein.</i>"
    )

    buttons = []
    # 2 buttons per row for catalog items
    row = []
    for it in items:
        iid = it.get("item_id")
        price = it.get("price_coins", 0)
        btn_text = f"{it.get('title', 'Item')} ({price}c)"
        row.append(InlineKeyboardButton(btn_text, callback_data=f"store_view:{iid}"))
        if len(row) == 1:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Navigation buttons
    buttons.append([
        InlineKeyboardButton("🎲 Lucky Spin", callback_data="spin_nav:spin"),
        InlineKeyboardButton("👤 My Profile", callback_data="spin_nav:profile"),
        InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
    ])
    ref_link = f"https://t.me/{bot_username}?start=spin_{profile.get('user_id', '')}"
    share_url = f"https://t.me/share/url?url={ref_link}&text=Join%20AkMovieVerse%20Bot%20for%20Fast%20Movies%20%26%20Daily%20Lucky%20Spin!"
    buttons.append([InlineKeyboardButton("👥 Earn Coins & Spins (Invite Friends) ↗️", url=share_url)])

    return text, InlineKeyboardMarkup(buttons)


# =========================================================================
# USER COMMANDS: /store & /coins
# =========================================================================

@Client.on_message(filters.command(["store", "coins", "shop"]) & filters.private)
async def store_command_handler(client: Client, message: Message):
    """Display user wallet balance and Flixify Coin Store catalog."""
    user_id = message.from_user.id
    profile = await record_daily_activity(user_id)
    items = await get_all_store_items(active_only=True)
    bot_uname = client.me.username if client.me else (Config.BOT_USERNAME or "TheFlixifyBot")

    text, markup = build_store_text_and_markup(profile, items, bot_uname)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


# =========================================================================
# USER COMMANDS: /profile & /rank
# =========================================================================

@Client.on_message(filters.command(["profile", "rank", "badge", "streak"]) & filters.private)
async def profile_command_handler(client: Client, message: Message):
    """Display user's loyalty profile card, streak history, and rank badge."""
    user_id = message.from_user.id
    profile = await record_daily_activity(user_id)
    bot_uname = client.me.username if client.me else (Config.BOT_USERNAME or "TheFlixifyBot")

    coins = profile.get("coins", 0)
    current_streak = profile.get("current_streak", 1)
    longest_streak = profile.get("longest_streak", 1)
    rank = profile.get("lifetime_rank", "🌟 Newbie Watcher")
    passes = profile.get("bonus_direct_passes", 0)
    total_spins = profile.get("total_spins_count", 0)
    ref_spins = profile.get("referral_spins", 0)
    secs = get_seconds_until_midnight_ist()
    hours = secs // 3600
    minutes = (secs % 3600) // 60

    text = (
        f"🎖️ <b>FLIXIFY LOYALTY PROFILE</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Member:</b> {message.from_user.first_name}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"🏅 <b>Lifetime Rank:</b> <code>{rank}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 <b>Active Streak:</b> <code>{current_streak} Days</code>\n"
        f"🏆 <b>Highest Streak:</b> <code>{longest_streak} Days</code>\n"
        f"🪙 <b>Coin Balance:</b> <code>{coins:,} Coins</code>\n"
        f"⚡ <b>Direct Download Passes:</b> <code>{passes}</code>\n"
        f"🎰 <b>Total Spins Used:</b> <code>{total_spins}</code>\n"
        f"🎁 <b>Extra Referral Spins:</b> <code>{ref_spins} Available</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Next Daily Reset:</b> <code>{hours}h {minutes}m</code> (12:00 AM IST)\n\n"
        f"💡 <i>Tip: Streak tootne par bhi aapka highest rank badge hamesha bacha rehta hai!</i>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Lucky Spin", callback_data="spin_nav:spin"),
            InlineKeyboardButton("🛒 Coin Store", callback_data="spin_nav:store")
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
        ]
    ])
    await message.reply_text(text, reply_markup=markup)


# =========================================================================
# USER COMMANDS: /leaderboard
# =========================================================================

@Client.on_message(filters.command(["leaderboard", "topstreaks", "topcoins"]) & filters.private)
async def leaderboard_command_handler(client: Client, message: Message):
    """Display the top 10 users ranked by longest streak and coin wealth."""
    leaders = await get_top_leaderboard(limit=10)
    text = (
        f"🏆 <b>FLIXIFY TOP LEGENDS LEADERBOARD</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if not leaders:
        text += "<i>Abhi leaderboard par koi data nahi hai. Aap pehle ban sakte hain!</i>\n"
    else:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for idx, u in enumerate(leaders):
            medal = medals[idx] if idx < len(medals) else f"{idx+1}."
            uid = u.get("user_id")
            streak = u.get("longest_streak", 1)
            coins = u.get("coins", 0)
            rank = u.get("lifetime_rank", "🌟 Newbie")
            text += f"{medal} <code>{uid}</code> • <b>{streak} Days</b> | 🪙 <b>{coins:,}c</b>\n   └ <i>{rank}</i>\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Apna rank badhane ke liye roz bot use karein aur /spin se coins jeetein!</i>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Lucky Spin", callback_data="spin_nav:spin"),
            InlineKeyboardButton("🛒 Coin Store", callback_data="spin_nav:store")
        ]
    ])
    await message.reply_text(text, reply_markup=markup)


# =========================================================================
# CALLBACK HANDLERS: Navigation & Store Item View / Buy
# =========================================================================

@Client.on_callback_query(filters.regex(r"^spin_nav:(store|leaderboard|profile|spin)$"))
async def store_navigation_callback(client: Client, query: CallbackQuery):
    """Handle cross-navigation between Spin, Store, Profile, and Leaderboard."""
    action = query.data.split(":")[1]
    user_id = query.from_user.id
    bot_uname = client.me.username if client.me else (Config.BOT_USERNAME or "TheFlixifyBot")

    if action == "store":
        profile = await get_loyalty_profile(user_id)
        items = await get_all_store_items(active_only=True)
        text, markup = build_store_text_and_markup(profile, items, bot_uname)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass

    elif action == "profile":
        profile = await get_loyalty_profile(user_id)
        coins = profile.get("coins", 0)
        current_streak = profile.get("current_streak", 1)
        longest_streak = profile.get("longest_streak", 1)
        rank = profile.get("lifetime_rank", "🌟 Newbie Watcher")
        passes = profile.get("bonus_direct_passes", 0)
        total_spins = profile.get("total_spins_count", 0)
        ref_spins = profile.get("referral_spins", 0)
        secs = get_seconds_until_midnight_ist()
        hours = secs // 3600
        minutes = (secs % 3600) // 60

        text = (
            f"🎖️ <b>FLIXIFY LOYALTY PROFILE</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Member:</b> {query.from_user.first_name}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🏅 <b>Lifetime Rank:</b> <code>{rank}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 <b>Active Streak:</b> <code>{current_streak} Days</code>\n"
            f"🏆 <b>Highest Streak:</b> <code>{longest_streak} Days</code>\n"
            f"🪙 <b>Coin Balance:</b> <code>{coins:,} Coins</code>\n"
            f"⚡ <b>Direct Download Passes:</b> <code>{passes}</code>\n"
            f"🎰 <b>Total Spins Used:</b> <code>{total_spins}</code>\n"
            f"🎁 <b>Extra Referral Spins:</b> <code>{ref_spins} Available</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ <b>Next Daily Reset:</b> <code>{hours}h {minutes}m</code> (12:00 AM IST)\n\n"
            f"💡 <i>Tip: Streak tootne par bhi aapka highest rank badge hamesha bacha rehta hai!</i>"
        )
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 Lucky Spin", callback_data="spin_nav:spin"),
                InlineKeyboardButton("🛒 Coin Store", callback_data="spin_nav:store")
            ],
            [
                InlineKeyboardButton("🏆 Leaderboard", callback_data="spin_nav:leaderboard")
            ]
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass

    elif action == "leaderboard":
        leaders = await get_top_leaderboard(limit=10)
        text = (
            f"🏆 <b>FLIXIFY TOP LEGENDS LEADERBOARD</b> 🌟\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if not leaders:
            text += "<i>Abhi leaderboard par koi data nahi hai. Aap pehle ban sakte hain!</i>\n"
        else:
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            for idx, u in enumerate(leaders):
                medal = medals[idx] if idx < len(medals) else f"{idx+1}."
                uid = u.get("user_id")
                streak = u.get("longest_streak", 1)
                coins = u.get("coins", 0)
                rank = u.get("lifetime_rank", "🌟 Newbie")
                text += f"{medal} <code>{uid}</code> • <b>{streak} Days</b> | 🪙 <b>{coins:,}c</b>\n   └ <i>{rank}</i>\n"

        text += (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Apna rank badhane ke liye roz bot use karein aur /spin se coins jeetein!</i>"
        )
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎲 Lucky Spin", callback_data="spin_nav:spin"),
                InlineKeyboardButton("🛒 Coin Store", callback_data="spin_nav:store")
            ]
        ])
        try:
            await query.message.edit_text(text, reply_markup=markup)
        except Exception:
            pass

    elif action == "spin":
        # Redirect to spin handler flow
        from plugins.spin import can_spin_today
        profile = await get_loyalty_profile(user_id)
        allowed, spin_type, ref_spins, cooldown_secs = await can_spin_today(user_id)
        ref_link = f"https://t.me/{bot_uname}?start=spin_{user_id}"

        if not allowed:
            hours = cooldown_secs // 3600
            minutes = (cooldown_secs % 3600) // 60
            timer_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            text = (
                f"⏰ <b>Aaj Ka Free Spin Use Ho Chuka Hai!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>User:</b> {query.from_user.first_name}\n"
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
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception:
                pass
        else:
            label = "🎁 Free Daily Spin" if spin_type == "free" else f"⚡ Extra Referral Spin ({ref_spins} Left)"
            text = (
                f"🎰 <b>FLIXIFY LUCKY SPIN WHEEL</b> 🌟\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Player:</b> {query.from_user.first_name}\n"
                f"🪙 <b>Balance:</b> <code>{profile.get('coins', 0)} Coins</code>\n"
                f"🏅 <b>Rank:</b> <code>{profile.get('lifetime_rank', '🌟 Newbie')}</code>\n"
                f"🔥 <b>Streak:</b> <code>{profile.get('current_streak', 1)} Days</code>\n\n"
                f"🎯 <b>Spin Status:</b> <code>{label} Available!</code>\n\n"
                f"Neeche diye gaye button par tap karke wheel ghumayein aur jeetein <b>Coins & VIP Rewards</b>!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 SPIN THE WHEEL! 🎲", callback_data="spin_roll:do")]
            ])
            try:
                await query.message.edit_text(text, reply_markup=markup)
            except Exception:
                pass


@Client.on_callback_query(filters.regex(r"^store_view:([\w\-]+)$"))
async def store_view_item_callback(client: Client, query: CallbackQuery):
    """Show details card for a specific store item with Buy confirmation."""
    item_id = query.data.split(":")[1]
    item = await get_store_item_by_id(item_id)

    if not item or not item.get("is_active", True):
        return await query.answer("❌ Yeh item uplabdh nahi hai.", show_alert=True)

    user_id = query.from_user.id
    profile = await get_loyalty_profile(user_id)
    user_coins = profile.get("coins", 0)
    price = item.get("price_coins", 0)
    title = item.get("title", "Item")
    desc = item.get("description", "No description")

    afford_text = f"✅ Aapke paas kaafi coins hain! ({user_coins} Coins)" if user_coins >= price else f"⚠️ Coins kam hain ({user_coins}/{price} Coins)"

    text = (
        f"🛍️ <b>ITEM DETAILS:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Item:</b> {title}\n"
        f"🪙 <b>Price:</b> <code>{price} Coins</code>\n"
        f"📝 <b>Description:</b>\n<i>{desc}</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Aapka Balance:</b> <code>{user_coins} Coins</code>\n"
        f"📊 <b>Status:</b> {afford_text}\n\n"
        f"Kya aap ise khareedna chahte hain?"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Confirm Purchase ({price}c)", callback_data=f"store_buy:{item_id}")
        ],
        [
            InlineKeyboardButton("« Back to Store", callback_data="spin_nav:store")
        ]
    ])
    try:
        await query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^store_buy:([\w\-]+)$"))
async def store_buy_callback(client: Client, query: CallbackQuery):
    """Execute purchase of a store item and fulfill reward."""
    item_id = query.data.split(":")[1]
    user_id = query.from_user.id

    success, msg, details = await purchase_store_item(client, user_id, item_id)
    if not success:
        return await query.answer(msg, show_alert=True)

    await query.answer("🎉 Purchase Successful!", show_alert=False)

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 Back to Store", callback_data="spin_nav:store"),
            InlineKeyboardButton("👤 My Profile", callback_data="spin_nav:profile")
        ]
    ])
    try:
        await query.message.edit_text(msg, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


# =========================================================================
# ADMIN COMMANDS: /additem, /delitem, /storeitems, /givecoins, /takecoins
# =========================================================================

@Client.on_message(filters.command("additem") & filters.private)
async def admin_add_store_item_cmd(client: Client, message: Message):
    """Admin command to add or update an item in Flixify Store.
    Usage:
    /additem <item_id> <price_coins> <type> <value> <Title> [| Description]
    Types: pass, vip, coupon, channel, text
    Examples:
    /additem pass_5x 200 pass 5 ⚡ 5x Direct Passes | Bypass shorteners for 5 movies
    /additem vip_30d 1500 vip 30 👑 1-Month VIP Master | 30 days unlimited access
    /additem vip_channel 800 channel -1001234567890:48 🔒 Secret VIP Channel | 48 Hours access
    /additem gift_14d 450 coupon 14 🎟️ 14-Day VIP Coupon | Giftable coupon code
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("❌ Sirf bot admins is command ko use kar sakte hain.")

    args = message.text.split(None, 5)
    if len(args) < 6:
        usage = (
            "⚠️ <b>Usage:</b>\n"
            "<code>/additem &lt;item_id&gt; &lt;price_coins&gt; &lt;type&gt; &lt;value&gt; &lt;Title&gt; [| Description]</code>\n\n"
            "<b>Allowed Types:</b> <code>pass</code>, <code>vip</code>, <code>coupon</code>, <code>channel</code>, <code>text</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/additem pass_5x 200 pass 5 ⚡ 5x Direct Passes | Bypass shortener for 5 movies</code>\n"
            "• <code>/additem vip_7d 600 vip 7 👑 7-Day VIP Access | Full week VIP</code>\n"
            "• <code>/additem secret_ch 500 channel -1001234567890:48 🔒 VIP Channel | 48 Hours access</code>\n"
            "• <code>/additem gift_14d 450 coupon 14 🎟️ 14-Day VIP Code | Giftable promo coupon</code>"
        )
        return await message.reply_text(usage)

    item_id = args[1].strip()
    try:
        price = int(args[2].strip())
    except ValueError:
        return await message.reply_text("❌ Price coins integer hona chahiye (e.g. 150).")

    item_type = args[3].strip().lower()
    raw_val = args[4].strip()
    rest = args[5].strip()

    title = rest
    desc = ""
    if "|" in rest:
        t, d = rest.split("|", 1)
        title = t.strip()
        desc = d.strip()

    item_val = raw_val
    if item_type in ["pass", "vip", "coupon"]:
        try:
            item_val = int(raw_val)
        except ValueError:
            return await message.reply_text(f"❌ {item_type} ke liye value integer (days/count) honi chahiye.")

    await add_or_update_store_item(
        item_id=item_id,
        title=title,
        price_coins=price,
        item_type=item_type,
        item_value=item_val,
        description=desc,
        is_active=True
    )

    await message.reply_text(
        f"✅ <b>STORE ITEM SAVED!</b>\n\n"
        f"• <b>ID:</b> <code>{item_id}</code>\n"
        f"• <b>Title:</b> {title}\n"
        f"• <b>Price:</b> <code>{price} Coins</code>\n"
        f"• <b>Type:</b> <code>{item_type}</code>\n"
        f"• <b>Value:</b> <code>{item_val}</code>\n"
        f"• <b>Description:</b> <i>{desc or 'None'}</i>\n\n"
        f"Yeh item ab <b>/store</b> mein live dikhai dega!"
    )


@Client.on_message(filters.command("delitem") & filters.private)
async def admin_del_store_item_cmd(client: Client, message: Message):
    """Admin command to remove an item from Flixify Store.
    Usage: /delitem <item_id>
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("❌ Sirf bot admins is command ko use kar sakte hain.")

    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("⚠️ Usage: <code>/delitem &lt;item_id&gt;</code>")

    item_id = args[1].strip()
    deleted = await delete_store_item(item_id)
    if deleted:
        await message.reply_text(f"✅ Item <code>{item_id}</code> store se hata diya gaya hai.")
    else:
        await message.reply_text(f"❌ Item <code>{item_id}</code> store mein nahi mila.")


@Client.on_message(filters.command("storeitems") & filters.private)
async def admin_list_store_items_cmd(client: Client, message: Message):
    """Admin command to view all configured items in Store."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("❌ Sirf bot admins is command ko use kar sakte hain.")

    items = await get_all_store_items(active_only=False)
    if not items:
        return await message.reply_text("Store mein koi items configured nahi hain.")

    out = "🛒 <b>ALL FLIXIFY STORE ITEMS:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for it in items:
        out += (
            f"• <b>ID:</b> <code>{it.get('item_id')}</code>\n"
            f"  <b>Title:</b> {it.get('title')}\n"
            f"  <b>Price:</b> <code>{it.get('price_coins')}c</code> | <b>Type:</b> <code>{it.get('item_type')}</code>\n"
            f"  <b>Value:</b> <code>{it.get('item_value')}</code> | <b>Active:</b> <code>{it.get('is_active')}</code>\n\n"
        )
    await message.reply_text(out)


@Client.on_message(filters.command("givecoins") & filters.private)
async def admin_give_coins_cmd(client: Client, message: Message):
    """Admin command to credit coins to a user.
    Usage: /givecoins <user_id> <amount>
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("❌ Sirf bot admins is command ko use kar sakte hain.")

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("⚠️ Usage: <code>/givecoins &lt;user_id&gt; &lt;amount&gt;</code>")

    try:
        target_uid = int(args[1].strip())
        amount = int(args[2].strip())
    except ValueError:
        return await message.reply_text("❌ user_id aur amount integer hone chahiye.")

    if amount <= 0:
        return await message.reply_text("❌ Amount positive hona chahiye.")

    new_bal = await add_coins(target_uid, amount, reason=f"admin_gift:{message.from_user.id}")
    await message.reply_text(
        f"✅ <b>COINS CREDITED!</b>\n\n"
        f"• <b>User ID:</b> <code>{target_uid}</code>\n"
        f"• <b>Added:</b> 🪙 <code>+{amount} Coins</code>\n"
        f"• <b>New Balance:</b> <code>{new_bal} Coins</code>"
    )
    try:
        await client.send_message(
            target_uid,
            f"🎁 <b>ADMIN BONUS RECEIVED!</b>\n\n"
            f"Admin ne aapke wallet mein 🪙 <b>+{amount} Flixify Coins</b> add kiye hain!\n"
            f"💰 <b>Total Balance:</b> <code>{new_bal} Coins</code>\n\n"
            f"🛍️ In coins ko <b>/store</b> mein use karein!"
        )
    except Exception:
        pass


@Client.on_message(filters.command("takecoins") & filters.private)
async def admin_take_coins_cmd(client: Client, message: Message):
    """Admin command to deduct coins from a user.
    Usage: /takecoins <user_id> <amount>
    """
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("❌ Sirf bot admins is command ko use kar sakte hain.")

    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("⚠️ Usage: <code>/takecoins &lt;user_id&gt; &lt;amount&gt;</code>")

    try:
        target_uid = int(args[1].strip())
        amount = int(args[2].strip())
    except ValueError:
        return await message.reply_text("❌ user_id aur amount integer hone chahiye.")

    if amount <= 0:
        return await message.reply_text("❌ Amount positive hona chahiye.")

    ok, rem_bal = await deduct_coins(target_uid, amount, reason=f"admin_deduct:{message.from_user.id}")
    if ok:
        await message.reply_text(
            f"✅ <b>COINS DEDUCTED!</b>\n\n"
            f"• <b>User ID:</b> <code>{target_uid}</code>\n"
            f"• <b>Deducted:</b> 🪙 <code>-{amount} Coins</code>\n"
            f"• <b>Remaining Balance:</b> <code>{rem_bal} Coins</code>"
        )
    else:
        await message.reply_text(
            f"⚠️ User ke paas itne coins nahi the. Current Balance: <code>{rem_bal} Coins</code>."
        )
