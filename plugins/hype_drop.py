import os
import re
import time
import uuid
import datetime
import logging
import urllib.parse
import asyncio
import aiohttp

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.mongo import mongo
from plugins.daily_broadcast import execute_broadcast_with_dead_user_purging

logger = logging.getLogger(__name__)

# In-memory store for pending hype broadcast cards: hype_id -> dict
PENDING_HYPE_PAYLOADS: dict[str, dict] = {}


async def record_search_demand(clean_q: str, user_id: int):
    """Record zero-result search query in MongoDB to track audience demand."""
    if not clean_q or len(clean_q) < 3 or clean_q.isdigit():
        return
    norm_q = clean_q.lower().strip()
    try:
        await mongo.db["search_demand"].update_one(
            {"query": norm_q},
            {
                "$inc": {"count": 1},
                "$set": {
                    "title": clean_q,
                    "last_searched": datetime.datetime.utcnow(),
                    "notified": False
                },
                "$addToSet": {"users": user_id}
            },
            upsert=True
        )
    except Exception as e:
        logger.debug(f"Error recording search demand for {clean_q}: {e}")


async def build_hype_card(bot_username: str, query: str) -> tuple[str, InlineKeyboardMarkup, str, dict]:
    """Fetch TMDB details and scan local channel DB for qualities/audio to construct the Hype Premiere Alert."""
    api_key = getattr(Config, "TMDB_API_KEY", "") or "56b50689afe7438a51aab0d653679865"
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    clean_q = re.sub(r"\s*\((?:19|20)\d{2}\).*", "", query).strip()
    clean_q = re.sub(r"[\-_:\[\]\(\)]", " ", clean_q).strip()
    clean_q = re.sub(r"\s+", " ", clean_q)

    encoded = urllib.parse.quote(clean_q)
    endpoints = [
        f"https://tmdbapi.the-zake.workers.dev/3/search/multi?api_key={api_key}&query={encoded}",
        f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={encoded}"
    ]

    meta = {
        "title": query,
        "year": "N/A",
        "rating": 7.5,
        "genres": "Action • Thriller",
        "overview": "The most anticipated release is finally available! Stream and download in top quality.",
        "poster": "",
        "audio": "Hindi Original [5.1 Audio]",
        "qualities": "1080p • 720p • 480p"
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.0)) as session:
            data = None
            for ep in endpoints:
                try:
                    async with session.get(ep, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("results"):
                                break
                except Exception:
                    continue

            if data and data.get("results"):
                results = data.get("results", [])
                if results:
                    chosen = results[0]
                    m_id = chosen.get("id")
                    m_type = chosen.get("media_type", "movie")
                    meta["title"] = chosen.get("title") or chosen.get("name") or query
                    rel_date = chosen.get("release_date") or chosen.get("first_air_date") or ""
                    if rel_date and len(rel_date) >= 4:
                        meta["year"] = rel_date[:4]

                    vote = chosen.get("vote_average") or 0.0
                    if vote > 0:
                        meta["rating"] = round(float(vote), 1)

                    if chosen.get("overview"):
                        meta["overview"] = chosen["overview"]

                    if chosen.get("poster_path"):
                        meta["poster"] = f"https://image.tmdb.org/t/p/w780{chosen['poster_path']}"
                    elif chosen.get("backdrop_path"):
                        meta["poster"] = f"https://image.tmdb.org/t/p/w1280{chosen['backdrop_path']}"

                    # Fetch detail for official genre names
                    if m_id:
                        for d_base in ["https://tmdbapi.the-zake.workers.dev/3", "https://api.themoviedb.org/3"]:
                            detail_url = f"{d_base}/{m_type}/{m_id}?api_key={api_key}"
                            try:
                                async with session.get(detail_url, headers=headers, timeout=3.0) as d_resp:
                                    if d_resp.status == 200:
                                        d_data = await d_resp.json()
                                        g_names = [g.get("name") for g in d_data.get("genres", []) if g.get("name")]
                                        if g_names:
                                            meta["genres"] = " • ".join(g_names[:3])
                                            break
                            except Exception:
                                pass
    except Exception as e:
        logger.debug(f"TMDB fetch error in hype card: {e}")

    # Fallback poster if none found
    if not meta["poster"]:
        meta["poster"] = Config.START_PIC or "https://telegra.ph/file/0c9a5180f1338d388915b.jpg"

    # Scan local database for matching files to detect true audio & qualities
    try:
        escaped_q = re.escape(clean_q)
        cursor = mongo.files.find(
            {"file_name": {"$regex": escaped_q, "$options": "i"}},
            {"file_name": 1}
        ).limit(30)
        matching_docs = await cursor.to_list(length=30)

        if matching_docs:
            detected_qualities = set()
            detected_audio = set()
            for doc in matching_docs:
                fn = doc.get("file_name", "").lower()
                if re.search(r"\b(2160p|4k|uhd)\b", fn):
                    detected_qualities.add("4K UHD")
                if re.search(r"\b(1080p|fhd)\b", fn):
                    detected_qualities.add("1080p")
                if re.search(r"\b(720p|hd)\b", fn):
                    detected_qualities.add("720p")
                if re.search(r"\b(480p|sd)\b", fn):
                    detected_qualities.add("480p")
                if re.search(r"\b(hevc|x265|10bit)\b", fn):
                    detected_qualities.add("10bit HEVC")

                if re.search(r"\b(dual|multi)\b", fn):
                    detected_audio.add("Dual Audio")
                elif re.search(r"\b(hin|hindi)\b", fn):
                    detected_audio.add("Hindi Original")
                if re.search(r"\b(atmos|5\.1|ddp)\b", fn):
                    detected_audio.add("Dolby Atmos 5.1")

            if detected_qualities:
                order = ["4K UHD", "1080p", "720p", "480p", "10bit HEVC"]
                sorted_q = [q for q in order if q in detected_qualities]
                if sorted_q:
                    meta["qualities"] = " • ".join(sorted_q)
            if detected_audio:
                meta["audio"] = " + ".join(list(detected_audio)[:2])
    except Exception as e:
        logger.debug(f"Error scanning local files for hype metadata: {e}")

    # Build clean storyline hook (first 250 chars)
    overview_text = meta["overview"]
    if len(overview_text) > 280:
        overview_text = overview_text[:275].rstrip() + "..."

    caption = (
        "🚨 <b>SPECIAL PREMIERE • THE WAIT IS OVER!</b> 🚨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 <b>{meta['title']}</b> ({meta['year']})\n"
        f"⭐ <b>IMDb:</b> <code>{meta['rating']}/10</code> | 🎭 <b>Genre:</b> {meta['genres']}\n"
        f"🔊 <b>Audio:</b> {meta['audio']}\n"
        f"📺 <b>Quality:</b> {meta['qualities']}\n\n"
        f"💬 <i>\"{overview_text}\"</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👆 <i>Click to download</i>"
    )

    clean_param = re.sub(r"[^a-zA-Z0-9]+", "_", meta["title"]).strip("_")[:55]
    deep_link = f"https://t.me/{bot_username}?start=search_{clean_param}"
    channel_url = Config.CHANNEL_URL or f"https://t.me/{bot_username}"

    btn_rows = [
        [
            InlineKeyboardButton("⚡ Download / Stream Now", url=deep_link)
        ],
        [
            InlineKeyboardButton("📢 Updates Channel", url=channel_url)
        ],
        [
            InlineKeyboardButton("💎 Get Ad-Free VIP", url=f"https://t.me/{bot_username}?start=plans")
        ]
    ]

    return caption, InlineKeyboardMarkup(btn_rows), meta["poster"], meta


async def check_and_notify_high_demand(client: Client, media_info: dict):
    """When a file is uploaded, check if it satisfies unfulfilled audience search demand."""
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
        cursor = mongo.db["search_demand"].find({
            "notified": False,
            "$or": [
                {"query": norm_base},
                {"query": {"$regex": f"^{re.escape(norm_base)}", "$options": "i"}}
            ]
        })

        demands = await cursor.to_list(length=10)
        for doc in demands:
            users_list = doc.get("users", [])
            total_searches = doc.get("count", 0)
            user_count = len(users_list)

            # Trigger alert if demanded by >= 2 unique users or >= 3 total searches
            if user_count >= 2 or total_searches >= 3:
                await mongo.db["search_demand"].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"notified": True, "fulfilled_at": datetime.datetime.utcnow()}}
                )

                q_term = doc.get("title", base_name)
                alert_text = (
                    "🔥 <b>HIGH-DEMAND MOVIE UPLOADED!</b>\n\n"
                    f"🎬 <b>Title:</b> <code>{q_term}</code>\n"
                    f"👥 <b>Demanded By:</b> <code>{user_count} unique users</code> ({total_searches} total searches)\n"
                    f"📁 <b>New File:</b> <code>{raw_name[:50]}</code>\n\n"
                    "👇 <i>Aap niche click karke turant iska Hype Premiere Alert bana sakte hain:</i>"
                )

                clean_slug = re.sub(r"[^a-zA-Z0-9]+", "_", q_term).strip("_")[:30]
                action_markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🚀 Preview & Send Hype Alert", callback_data=f"makehype_{clean_slug}")
                    ]
                ])

                if Config.LOG_CHANNEL:
                    try:
                        await client.send_message(Config.LOG_CHANNEL, alert_text, reply_markup=action_markup)
                    except Exception as le:
                        logger.debug(f"Could not log high demand alert: {le}")

                for admin_id in Config.ADMINS:
                    try:
                        await client.send_message(admin_id, alert_text, reply_markup=action_markup)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"Error checking high demand on upload: {e}")


# ==============================================================================
# Commands: /hypedrop, /specialdrop, /demands
# ==============================================================================

@Client.on_message(filters.command(["hypedrop", "specialdrop"]) & filters.private)
async def hype_drop_command(client: Client, message: Message):
    """Admin command: /hypedrop <Movie Name> - Preview and broadcast a high-hype blockbuster alert."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**: Admin privileges required.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.reply_text(
            "⚠️ **Usage:** `/hypedrop <Movie / Series Name>`\n\n"
            "**Examples:**\n"
            "• `/hypedrop Stree 2`\n"
            "• `/hypedrop Mirzapur`\n"
            "• `/hypedrop Pushpa 2`\n\n"
            "💡 _Bot will fetch HD poster, IMDb rating, audio & quality badges, and show you an instant preview before broadcasting!_"
        )

    query = args[1].strip()
    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    status = await message.reply_text(f"⏳ **Building Hype Alert for:** `{query}`...")

    try:
        caption, public_markup, photo_url, meta = await build_hype_card(bot_username, query)

        # Store pending payload
        hype_id = uuid.uuid4().hex[:8]
        PENDING_HYPE_PAYLOADS[hype_id] = {
            "caption": caption,
            "markup": public_markup,
            "photo_url": photo_url,
            "title": meta["title"],
            "created_at": time.time()
        }

        # Admin control buttons: Confirm broadcast or cancel
        admin_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Broadcast to All Users", callback_data=f"hypebc_{hype_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"hypecnl_{hype_id}")
            ]
        ])

        await status.delete()
        if photo_url:
            await message.reply_photo(
                photo=photo_url,
                caption=f"👁️ <b>[ADMIN PREVIEW]</b>\n\n{caption}",
                reply_markup=admin_markup
            )
        else:
            await message.reply_text(
                f"👁️ <b>[ADMIN PREVIEW]</b>\n\n{caption}",
                reply_markup=admin_markup,
                disable_web_page_preview=True
            )

    except Exception as e:
        logger.error(f"Error in hypedrop command: {e}", exc_info=True)
        await status.edit_text(f"❌ **Error creating hype alert:** `{e}`")


@Client.on_message(filters.command(["demands", "topdemands"]) & filters.private)
async def top_demands_command(client: Client, message: Message):
    """Admin command: View top unfulfilled movie searches by users."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ **Access Denied**.")

    status = await message.reply_text("⏳ **Analyzing user search demand...**")
    try:
        cursor = mongo.db["search_demand"].find({}).sort("count", -1).limit(15)
        docs = await cursor.to_list(length=15)

        if not docs:
            return await status.edit_text("ℹ️ **Abhi tak koi unfulfilled search record nahi hui hai.**")

        lines = ["📊 <b>TOP DEMANDED MOVIES (USER SEARCHES)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        for idx, doc in enumerate(docs, 1):
            title = doc.get("title", doc.get("query", "Unknown"))
            cnt = doc.get("count", 0)
            u_cnt = len(doc.get("users", []))
            notified = "✅ (Uploaded)" if doc.get("notified") else "🟡 (Pending)"
            lines.append(f"<b>{idx}. {title}</b> — <code>{cnt} searches</code> ({u_cnt} users) {notified}")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Upload these movies to storage channel to satisfy audience demand!</i>")
        await status.edit_text("\n".join(lines))
    except Exception as e:
        logger.error(f"Error listing demands: {e}")
        await status.edit_text(f"❌ **Error:** `{e}`")


# ==============================================================================
# Callback Query Handlers
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^hypebc_"))
async def execute_hype_broadcast_callback(client: Client, query: CallbackQuery):
    """Admin clicked 'Broadcast to All Users' on Hype Alert preview."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied.", show_alert=True)

    hype_id = query.data.split("_")[1]
    payload = PENDING_HYPE_PAYLOADS.get(hype_id)

    if not payload:
        return await query.answer("⚠️ Hype alert session expired. Please run /hypedrop again.", show_alert=True)

    await query.answer("🚀 Starting Hype Broadcast...")
    await query.message.edit_reply_markup(reply_markup=None)

    progress_msg = await query.message.reply_text(
        f"📢 <b>Launching Hype Broadcast for:</b> <code>{payload['title']}</code>\n"
        "⚡ <i>Delivering with real-time dead user purging...</i>"
    )

    try:
        stats = await execute_broadcast_with_dead_user_purging(
            client=client,
            text=payload["caption"],
            markup=payload["markup"],
            photo_url=payload["photo_url"]
        )

        report = (
            f"🎉 <b>Hype Broadcast Completed!</b>\n\n"
            f"🎬 <b>Movie:</b> <code>{payload['title']}</code>\n"
            f"👥 <b>Total Target Users:</b> <code>{stats['total']:,}</code>\n"
            f"✅ <b>Delivered:</b> <code>{stats['sent']:,}</code>\n"
            f"🧹 <b>Dead Users Purged:</b> <code>{stats['purged']:,}</code>\n"
            f"⚠️ <b>Failed / Network:</b> <code>{stats['failed']:,}</code>"
        )
        await progress_msg.edit_text(report)

        if Config.LOG_CHANNEL:
            try:
                await client.send_message(Config.LOG_CHANNEL, report)
            except Exception:
                pass

        PENDING_HYPE_PAYLOADS.pop(hype_id, None)

    except Exception as e:
        logger.error(f"Hype broadcast execution error: {e}", exc_info=True)
        await progress_msg.edit_text(f"❌ **Broadcast Failed:** `{e}`")


@Client.on_callback_query(filters.regex(r"^hypecnl_"))
async def cancel_hype_broadcast_callback(client: Client, query: CallbackQuery):
    """Admin cancelled the hype alert."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied.", show_alert=True)

    hype_id = query.data.split("_")[1]
    PENDING_HYPE_PAYLOADS.pop(hype_id, None)
    await query.answer("Cancelled.")
    await query.message.delete()


@Client.on_callback_query(filters.regex(r"^makehype_"))
async def trigger_make_hype_callback(client: Client, query: CallbackQuery):
    """Admin clicked 'Preview & Send Hype Alert' from high-demand notification."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Access Denied.", show_alert=True)

    slug = query.data.split("_", 1)[1]
    search_q = slug.replace("_", " ")

    await query.answer(f"Building Hype Alert for {search_q}...")
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    caption, public_markup, photo_url, meta = await build_hype_card(bot_username, search_q)
    hype_id = uuid.uuid4().hex[:8]
    PENDING_HYPE_PAYLOADS[hype_id] = {
        "caption": caption,
        "markup": public_markup,
        "photo_url": photo_url,
        "title": meta["title"],
        "created_at": time.time()
    }

    admin_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Broadcast to All Users", callback_data=f"hypebc_{hype_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"hypecnl_{hype_id}")
        ]
    ])

    if photo_url:
        await query.message.reply_photo(
            photo=photo_url,
            caption=f"👁️ <b>[ADMIN PREVIEW]</b>\n\n{caption}",
            reply_markup=admin_markup
        )
    else:
        await query.message.reply_text(
            f"👁️ <b>[ADMIN PREVIEW]</b>\n\n{caption}",
            reply_markup=admin_markup,
            disable_web_page_preview=True
        )
