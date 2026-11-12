import time
import logging
from database.mongo import mongo
from database.loyalty import deduct_coins, get_loyalty_profile
from database.users import add_premium_user

logger = logging.getLogger("flixify.store")

DEFAULT_STORE_ITEMS = [
    {
        "item_id": "pass_1x",
        "title": "⚡ 1x Direct Download Pass",
        "description": "Bypass shorteners & ads to download 1 movie instantly.",
        "price_coins": 50,
        "item_type": "pass",
        "item_value": 1,
        "is_active": True,
        "created_at": 1794380000
    },
    {
        "item_id": "vip_1d",
        "title": "👑 1-Day Full VIP Pass",
        "description": "24 Hours unlimited ad-free streaming & downloads.",
        "price_coins": 150,
        "item_type": "vip",
        "item_value": 1,
        "is_active": True,
        "created_at": 1794380000
    },
    {
        "item_id": "vip_3d",
        "title": "💎 3-Day Mega VIP Pass",
        "description": "72 Hours unlimited ad-free streaming & downloads.",
        "price_coins": 350,
        "item_type": "vip",
        "item_value": 3,
        "is_active": True,
        "created_at": 1794380000
    },
    {
        "item_id": "gift_7d",
        "title": "🎟️ 7-Day Giftable VIP Voucher",
        "description": "1-Click VIP coupon code to gift to a friend or yourself.",
        "price_coins": 250,
        "item_type": "coupon",
        "item_value": 7,
        "is_active": True,
        "created_at": 1794380000
    }
]


async def init_default_store_items():
    """Seed initial store items if collection is empty."""
    col = mongo.db["store_items"]
    count = await col.count_documents({})
    if count == 0:
        try:
            await col.insert_many(DEFAULT_STORE_ITEMS)
            logger.info("Initialized default Flixify Store catalog.")
        except Exception as e:
            logger.debug(f"init_default_store_items note: {e}")


async def get_all_store_items(active_only: bool = True) -> list[dict]:
    """Retrieve list of store items sorted by coin price ascending."""
    await init_default_store_items()
    col = mongo.db["store_items"]
    q = {"is_active": True} if active_only else {}
    cursor = col.find(q).sort("price_coins", 1)
    return await cursor.to_list(length=100)


async def get_store_item_by_id(item_id: str) -> dict | None:
    """Fetch a specific store item by unique item_id."""
    col = mongo.db["store_items"]
    return await col.find_one({"item_id": str(item_id).strip()})


async def add_or_update_store_item(
    item_id: str,
    title: str,
    price_coins: int,
    item_type: str,
    item_value,
    description: str = "",
    is_active: bool = True
) -> bool:
    """Admin: Add a new custom item or update existing item in Store."""
    col = mongo.db["store_items"]
    clean_id = str(item_id).strip().lower().replace(" ", "_")
    doc = {
        "item_id": clean_id,
        "title": str(title).strip(),
        "description": str(description).strip(),
        "price_coins": int(price_coins),
        "item_type": str(item_type).strip().lower(),
        "item_value": item_value,
        "is_active": bool(is_active),
        "updated_at": time.time()
    }
    await col.update_one(
        {"item_id": clean_id},
        {"$set": doc, "$setOnInsert": {"created_at": time.time()}},
        upsert=True
    )
    logger.info(f"Store item '{clean_id}' saved with price {price_coins} coins.")
    return True


async def delete_store_item(item_id: str) -> bool:
    """Admin: Delete a store item permanently."""
    col = mongo.db["store_items"]
    res = await col.delete_one({"item_id": str(item_id).strip().lower()})
    return res.deleted_count > 0


async def purchase_store_item(client, user_id: int, item_id: str) -> tuple[bool, str, dict]:
    """Process coin deduction and execute reward fulfillment.
    Returns (success: bool, message: str, details_dict: dict).
    """
    item = await get_store_item_by_id(item_id)
    if not item or not item.get("is_active", True):
        return False, "❌ Yeh item store mein uplabdh nahi hai.", {}

    price = item.get("price_coins", 0)
    ok_deduct, new_bal = await deduct_coins(user_id, price, reason=f"purchase:{item_id}")
    if not ok_deduct:
        return False, f"⚠️ Aapke paas kaafi coins nahi hain! Is item ke liye <b>{price} Coins</b> chahiye (Aapka balance: <b>{new_bal} Coins</b>).", {}

    item_type = item.get("item_type")
    item_val = item.get("item_value")
    title = item.get("title", "Store Item")
    payload = {"new_balance": new_bal, "item_title": title, "item_type": item_type}

    # 1. Direct Download Pass
    if item_type == "pass":
        passes_qty = int(item_val or 1)
        col_loyalty = mongo.db["loyalty_users"]
        await col_loyalty.update_one(
            {"user_id": int(user_id)},
            {"$inc": {"bonus_direct_passes": passes_qty}}
        )
        payload["passes_added"] = passes_qty
        msg = f"🎉 <b>Badhai Ho!</b>\n\nAapko <b>+{passes_qty} Direct Download Pass</b> mil gaya hai! Ab aap bina kisi shortener ke direct high-speed movie le sakte hain."
        return True, msg, payload

    # 2. VIP Access
    elif item_type == "vip":
        vip_days = int(item_val or 1)
        await add_premium_user(user_id, days=vip_days)
        payload["vip_days_added"] = vip_days
        msg = f"👑 <b>VIP ACTIVATED!</b>\n\nAapka <b>{vip_days}-Day Full VIP Pass</b> turant activate ho chuka hai! Enjoy ad-free streaming & instant downloads."
        return True, msg, payload

    # 3. Giftable VIP Coupon (Viral loop)
    elif item_type == "coupon":
        vip_days = int(item_val or 7)
        from database.promo import create_promo_code, generate_random_promo_code
        code_str = generate_random_promo_code(vip_days)
        _, _, _ = await create_promo_code(code_str, days=vip_days, max_uses=1)
        payload["promo_code"] = code_str
        payload["promo_days"] = vip_days
        from config import Config
        bot_uname = Config.BOT_USERNAME or "TheFlixifyBot"
        claim_url = f"https://t.me/{bot_uname}?start=redeem_{code_str}"
        payload["claim_url"] = claim_url

        msg = (
            f"🎟️ <b>VIP GIFT CARD TAIYAR HAI!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Coupon Code:</b> <code>{code_str}</code>\n"
            f"• <b>Benefit:</b> <b>{vip_days} Days VIP Access</b>\n"
            f"• <b>1-Click Claim Link:</b>\n"
            f"👉 <code>{claim_url}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Ise apne dost ko forward karein! Wo 1-click mein link par tap karke VIP activate kar sakta hai.</i>"
        )
        return True, msg, payload

    # 4. Auto-Expiring Private Channel Link
    elif item_type == "channel":
        try:
            # item_val can be 'chat_id:hours' or dict
            if isinstance(item_val, str) and ":" in item_val:
                cid, hrs = item_val.split(":", 1)
                chat_id = int(cid)
                hours = int(hrs)
            else:
                chat_id = int(item_val)
                hours = 72  # default 72 hours

            from database.channel_access import grant_temporary_channel_access
            ok_link, link, exp = await grant_temporary_channel_access(
                client=client,
                user_id=user_id,
                chat_id=chat_id,
                duration_hours=hours,
                channel_name=title
            )
            if ok_link:
                payload["invite_link"] = link
                payload["hours"] = hours
                msg = (
                    f"🎟️ <b>PRIVATE CHANNEL ACCESS GRANTED!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Channel:</b> {title}\n"
                    f"• <b>Valid For:</b> <b>{hours} Hours</b>\n"
                    f"• <b>Single-Use Invite Link:</b>\n"
                    f"👉 <a href='{link}'>Click Here To Join Channel</a>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ <i>Security Notice: Yeh link sirf 1 bande ke liye hai aur {hours} ghante baad access auto-expire ho jayega.</i>"
                )
                return True, msg, payload
            else:
                # Refund coins if invite creation failed
                from database.loyalty import add_coins
                await add_coins(user_id, price, reason="refund_channel_fail")
                return False, f"❌ Link generate karne mein issue aaya: {exp}. Coins refund kar diye gaye hain.", {}
        except Exception as e_ch:
            from database.loyalty import add_coins
            await add_coins(user_id, price, reason="refund_channel_fail")
            return False, f"❌ Channel access issue: {e_ch}. Coins refund kar diye gaye hain.", {}

    # 5. Custom Text / Voucher
    elif item_type == "custom" or item_type == "text":
        custom_txt = str(item_val)
        msg = f"🎁 <b>PURCHASE SUCCESSFUL!</b>\n\n<b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━\n{custom_txt}"
        return True, msg, payload

    return False, "❌ Unknown item type.", {}
