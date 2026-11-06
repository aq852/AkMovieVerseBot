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
        f_uid = media_info.get("file_unique_id")

        buttons = []
        if f_uid:
            buttons.append([InlineKeyboardButton("📥 Download File (1-Click)", callback_data=f"getfile_{f_uid}")])
        buttons.append([InlineKeyboardButton("🔍 View All Prints ↗️", url=f"https://t.me/{bot_username}?start=filter_{clean_slug}")])

        channel_url = Config.CHANNEL_URL or f"https://t.me/{bot_username}"
        if channel_url:
            buttons.append([InlineKeyboardButton("📢 Updates Channel ↗️", url=channel_url)])

        markup = InlineKeyboardMarkup(buttons)

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
            "🔔 <b>Aapke paas abhi koi active upload alert nahi hai.</b>\n\n"
            "Jab aap koi aisi movie search karte hain jo bot me nahi hoti, to aap <b>'Notify Me When Uploaded'</b> par click karke alert set kar sakte hain!"
        )

    lines = ["🔔 <b>Aapke Active Movie Alerts:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    keyboard = []
    for idx, a in enumerate(alerts, 1):
        a_id = str(a.get("_id"))
        title = a.get("title", "Movie")
        dt_str = a.get("created_at", datetime.datetime.utcnow()).strftime("%d %b")
        lines.append(f"<b>{idx}. {title}</b> <i>(Set on {dt_str})</i>")
        keyboard.append([
            InlineKeyboardButton(f"🗑️ Cancel Alert: '{title[:18]}'", callback_data=f"delalert_{a_id}")
        ])

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Jaise hi ye upload hongi, bot aapko turant PM me download link bhej dega!</i>")
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await message.reply_text("\n".join(lines), reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^delalert_(.+)"))
async def delete_alert_callback_handler(client: Client, query: CallbackQuery):
    """Allow user to cancel/delete a pending upload alert."""
    alert_id = query.matches[0].group(1).strip()
    from bson import ObjectId

    try:
        if ObjectId.is_valid(alert_id):
            doc = await mongo.db["upload_alerts"].find_one_and_delete({"_id": ObjectId(alert_id), "user_id": query.from_user.id})
        else:
            doc = await mongo.db["upload_alerts"].find_one_and_delete({"query": alert_id, "user_id": query.from_user.id})

        if doc:
            title = doc.get("title", "Movie")
            await query.answer(f"🗑️ Alert for '{title}' cancelled successfully!", show_alert=True)
            cursor = mongo.db["upload_alerts"].find({"user_id": query.from_user.id, "status": "pending"}).sort("created_at", -1).limit(10)
            remaining = await cursor.to_list(length=10)
            if not remaining:
                await query.message.edit_text(
                    "🔔 <b>Aapke paas abhi koi active upload alert nahi hai.</b>\n\n"
                    "Jab aap koi aisi movie search karte hain jo bot me nahi hoti, to aap <b>'Notify Me When Uploaded'</b> par click karke alert set kar sakte hain!"
                )
            else:
                k = []
                l = ["🔔 <b>Aapke Active Movie Alerts:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
                for idx, a in enumerate(remaining, 1):
                    aid = str(a.get("_id"))
                    t = a.get("title", "Movie")
                    dt_str = a.get("created_at", datetime.datetime.utcnow()).strftime("%d %b")
                    l.append(f"<b>{idx}. {t}</b> <i>(Set on {dt_str})</i>")
                    k.append([
                        InlineKeyboardButton(f"🗑️ Cancel Alert: '{t[:18]}'", callback_data=f"delalert_{aid}")
                    ])
                l.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Jaise hi ye upload hongi, bot aapko turant PM me download link bhej dega!</i>")
                await query.message.edit_text("\n".join(l), reply_markup=InlineKeyboardMarkup(k), disable_web_page_preview=True)
        else:
            await query.answer("Alert already removed or expired.", show_alert=True)
    except Exception as e:
        logger.error(f"Error deleting alert {alert_id}: {e}")
        await query.answer("Error deleting alert.", show_alert=True)
