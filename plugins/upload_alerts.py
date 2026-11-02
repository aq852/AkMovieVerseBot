import os
import re
import datetime
import logging
import asyncio

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
    from hydrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
    from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid

from config import Config
from database.mongo import mongo

logger = logging.getLogger(__name__)


async def add_upload_alert(user_id: int, user_name: str, query_term: str) -> bool:
    """Register a user's request to be notified when a missing movie/series is uploaded."""
    if not query_term or len(query_term) < 2:
        return False
    norm_q = query_term.lower().strip()
    try:
        await mongo.db["upload_alerts"].update_one(
            {"query": norm_q, "user_id": user_id},
            {
                "$set": {
                    "title": query_term.strip(),
                    "user_id": user_id,
                    "user_name": user_name or "User",
                    "created_at": datetime.datetime.utcnow(),
                    "status": "pending"
                }
            },
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error saving upload alert for {user_id} - {query_term}: {e}")
        return False


async def auto_notify_alert_subscribers(client: Client, media_info: dict):
    """When a file is indexed, automatically dispatch direct PM notifications to users who set an alert."""
    raw_name = media_info.get("file_name", "")
    if not raw_name:
        return

    from plugins.daily_broadcast import clean_media_title
    clean_title = clean_media_title(raw_name)
    base_name = re.sub(r"\s*\((?:19|20)\d{2}\).*", "", clean_title).strip()
    base_name = re.sub(r"[\-_:\[\]\(\)]", " ", base_name).strip()
    norm_base = base_name.lower()

    if len(norm_base) < 3:
        return

    try:
        # Find all pending alert subscriptions matching this title
        cursor = mongo.db["upload_alerts"].find({
            "status": "pending",
            "$or": [
                {"query": norm_base},
                {"query": {"$regex": f"^{re.escape(norm_base)}", "$options": "i"}}
            ]
        })

        subscribers = await cursor.to_list(length=100)
        if not subscribers:
            return

        bot_username = client.me.username if client.me else Config.BOT_USERNAME
        clean_slug = re.sub(r"[^a-zA-Z0-9]+", "_", base_name).strip("_")[:55]
        deep_link = f"https://t.me/{bot_username}?start=search_{clean_slug}"
        channel_url = Config.CHANNEL_URL or f"https://t.me/{bot_username}"

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download Now (1-Click)", url=deep_link)],
            [InlineKeyboardButton("📢 Updates Channel", url=channel_url)]
        ])

        notified_ids = []
        for sub in subscribers:
            uid = sub.get("user_id")
            u_name = sub.get("user_name", "Friend")
            alert_id = sub.get("_id")

            text = (
                f"🎉 <b>Good News {u_name}!</b>\n\n"
                f"🔔 <b>Aapki mangi hui movie bot me add ho chuki hai!</b>\n"
                f"🎬 <b>Title:</b> <code>{base_name}</code>\n"
                f"📁 <b>File:</b> <code>{raw_name[:55]}</code>\n\n"
                "👇 <i>Niche diye button par click karke turant download ya stream karein!</i>"
            )

            try:
                await client.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=markup,
                    disable_web_page_preview=True
                )
                notified_ids.append(alert_id)
                await asyncio.sleep(0.05)
            except (UserIsBlocked, InputUserDeactivated, UserDeactivated, PeerIdInvalid):
                # User blocked bot or account deleted - mark fulfilled & remove
                notified_ids.append(alert_id)
                try:
                    await mongo.users.delete_one({"user_id": uid})
                except Exception:
                    pass
            except FloodWait as fw:
                await asyncio.sleep(fw.value + 1)
            except Exception as e:
                logger.debug(f"Could not deliver upload alert to user {uid}: {e}")

        if notified_ids:
            await mongo.db["upload_alerts"].update_many(
                {"_id": {"$in": notified_ids}},
                {"$set": {"status": "fulfilled", "fulfilled_at": datetime.datetime.utcnow()}}
            )
            logger.info(f"Dispatched {len(notified_ids)} upload alert notifications for '{base_name}'.")

    except Exception as e:
        logger.error(f"Error in auto_notify_alert_subscribers: {e}", exc_info=True)


# ==============================================================================
# Callback Query Handler for [🔔 Notify Me When Uploaded]
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^notifme_"))
async def notify_me_callback_handler(client: Client, query: CallbackQuery):
    """Handle click on 'Notify Me When Uploaded' button from zero-result search."""
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "User"
    query_term = query.data.split("_", 1)[1].strip()

    if not query_term:
        return await query.answer("⚠️ Invalid movie query.", show_alert=True)

    success = await add_upload_alert(user_id, user_name, query_term)
    if success:
        await query.answer(
            f"🔔 Alert Set for '{query_term}'!\n\nJaise hi yeh movie upload hogi, bot aapko turant PM me notify karega.",
            show_alert=True
        )

        # Update button text to give instant visual feedback
        try:
            old_markup = query.message.reply_markup
            if old_markup:
                new_keyboard = []
                for row in old_markup.inline_keyboard:
                    new_row = []
                    for btn in row:
                        if btn.callback_data and btn.callback_data.startswith("notifme_"):
                            new_row.append(InlineKeyboardButton("✅ Alert Active (We will notify you)", callback_data="alert_active_info"))
                        else:
                            new_row.append(btn)
                    new_keyboard.append(new_row)
                await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(new_keyboard))
        except Exception:
            pass
    else:
        await query.answer("❌ Could not register alert. Please try again later.", show_alert=True)


@Client.on_callback_query(filters.regex(r"^alert_active_info$"))
async def alert_active_info_callback(client: Client, query: CallbackQuery):
    await query.answer("✅ Aapka alert active hai! Upload hote hi message aayega.", show_alert=True)


# ==============================================================================
# User Command: /myalerts (View & Manage Active Alerts)
# ==============================================================================

@Client.on_message(filters.command("myalerts") & filters.private)
async def my_alerts_command(client: Client, message: Message):
    """User command to view their pending movie upload notifications."""
    user_id = message.from_user.id
    cursor = mongo.db["upload_alerts"].find({"user_id": user_id, "status": "pending"}).sort("created_at", -1).limit(10)
    alerts = await cursor.to_list(length=10)

    if not alerts:
        return await message.reply_text(
            "🔔 **Aapke paas abhi koi active upload alert nahi hai.**\n\n"
            "Jab aap koi aisi movie search karte hain jo bot me nahi hoti, to aap **'Notify Me When Uploaded'** par click karke alert set kar sakte hain!"
        )

    lines = ["🔔 <b>Aapke Active Movie Alerts:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for idx, a in enumerate(alerts, 1):
        dt_str = a.get("created_at", datetime.datetime.utcnow()).strftime("%d %b")
        lines.append(f"<b>{idx}. {a.get('title')}</b> <i>(Set on {dt_str})</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Jaise hi ye upload hongi, bot aapko turant PM me download link bhej dega!</i>")
    await message.reply_text("\n".join(lines))
