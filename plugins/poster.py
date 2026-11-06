import uuid
import time
import asyncio
import logging
from io import BytesIO

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
    )
    from hydrogram.errors import MessageNotModified
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
    )
    from pyrogram.errors import MessageNotModified

from config import Config
from database.users import is_premium
from database.poster import (
    get_poster_brand, set_poster_brand, get_poster_channel, set_poster_channel
)
from utils.poster_engine.fetcher import resolve_media_metadata
from utils.poster_engine.templates import generate_poster_canvas, STYLE_NAMES
from utils.poster_engine.uploader import upload_to_imgbb

logger = logging.getLogger(__name__)

# In-memory poster session store with 1-hour TTL
POSTER_SESSIONS: dict[str, dict] = {}


def _clean_sessions():
    """Prune expired sessions older than 3600 seconds."""
    now = time.time()
    expired = [sid for sid, s in POSTER_SESSIONS.items() if now - s.get("created_at", 0) > 3600]
    for sid in expired:
        POSTER_SESSIONS.pop(sid, None)


def build_portrait_combos(all_posters: list) -> list:
    """Build a rich sequence of (style_id, art_index) for vertical 2:3 posters."""
    combos = []
    total = max(1, len(all_posters))

    # Primary art in Style 1 (Spatial Leech Poster)
    combos.append((1, 0))
    if total > 1:
        combos.append((1, 1))
    # Style 5 (Multi-Ratings) & Style 8 (Pure Clean Poster)
    combos.append((5, 0))
    combos.append((8, 0))

    # Walk through remaining artworks with rotating styles
    styles_pool = [1, 5, 8]
    for idx in range(2 if total > 2 else total, total):
        s = styles_pool[idx % len(styles_pool)]
        combos.append((s, idx))
        if s != 1:
            combos.append((1, idx))

    seen = set()
    unique = []
    for c in combos:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def build_landscape_combos(all_backdrops: list) -> list:
    """Build a rich, mixed sequence of (style_id, art_index) for widescreen 16:9 banners."""
    combos = []
    total = max(1, len(all_backdrops))

    # Style 2 (Spatial Cinema Banner)
    combos.append((2, 0))
    # Style 4 (Frosted Glass Card)
    combos.append((4, 0))
    if total > 1:
        combos.append((2, 1))
        combos.append((4, 1))
    # Style 3 (Minimalist Letterbox)
    combos.append((3, 0))
    # Style 7 (Pure Clean Backdrop)
    combos.append((7, 0))

    # Walk through remaining backdrops with rotating landscape styles
    styles_pool = [2, 4, 3, 7]
    for idx in range(2 if total > 2 else total, total):
        s = styles_pool[idx % len(styles_pool)]
        combos.append((s, idx))

    seen = set()
    unique = []
    for c in combos:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def build_poster_keyboard(
    session_id: str,
    mode: str,
    p_idx: int,
    total_p: int,
    l_idx: int,
    total_l: int,
    num_posters: int = 0,
    num_backdrops: int = 0
) -> InlineKeyboardMarkup:
    """Build ultra-compact, sleek 3-row keyboard for Poster Studio."""
    p_label = f"📱 Poster ({p_idx + 1}/{total_p}) ↻" if mode == "poster" else f"📱 Poster ({p_idx + 1}/{total_p})"
    l_label = f"🖥️ Landscape ({l_idx + 1}/{total_l}) ↻" if mode == "landscape" else f"🖥️ Landscape ({l_idx + 1}/{total_l})"

    posters_count = f" ({num_posters})" if num_posters > 0 else ""
    backdrops_count = f" ({num_backdrops})" if num_backdrops > 0 else ""

    keyboard = [
        # Row 1: The 2 Core Mode Switchers
        [
            InlineKeyboardButton(p_label, callback_data=f"pmix_p_{session_id}"),
            InlineKeyboardButton(l_label, callback_data=f"pmix_l_{session_id}")
        ],
        # Row 2: Full Albums & HD Download
        [
            InlineKeyboardButton(f"📸 Posters{posters_count}", callback_data=f"palbum_posters_{session_id}"),
            InlineKeyboardButton(f"🌄 Wallpapers{backdrops_count}", callback_data=f"palbum_backdrops_{session_id}"),
            InlineKeyboardButton("📁 HD File", callback_data=f"pdoc_{session_id}")
        ],
        # Row 3: Channel Publisher & Web Link
        [
            InlineKeyboardButton("📣 Post to Channel ↗️", callback_data=f"ppublish_{session_id}"),
            InlineKeyboardButton("🌐 ImgBB", callback_data=f"pimgbb_{session_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_poster_caption(
    media_data: dict,
    mode: str,
    combo_idx: int,
    total_combos: int,
    style_id: int,
    brand: str = "",
    is_premium: bool = False
) -> str:
    """Format minimal, cinematic 2-line poster caption."""
    title = (media_data.get("display_title") or "Movie").strip()
    year = media_data.get("year", "")
    year_str = f" ({year})" if year else ""

    rating = media_data.get("rating")
    rating_str = f" • ⭐ <b>{rating}/10</b>" if rating and float(rating) > 0 else ""

    mode_label = "📱 <b>Poster (2:3)</b>" if mode == "poster" else "🖥️ <b>Landscape (16:9)</b>"
    style_name = STYLE_NAMES.get(style_id, f"Style {style_id}")

    brand_tag = f" • 🏷️ @{brand}" if brand and not is_premium else ""

    return f"🎬 <b>{title}{year_str}</b>{rating_str}\n{mode_label} • 🎨 <i>{style_name}</i> (<code>{combo_idx + 1}/{total_combos}</code>){brand_tag}"


# ======================================================================
# 1. /poster <query or link>
# ======================================================================
@Client.on_message(filters.command(["poster", "thumbnail", "art"]))
async def poster_studio_command(client: Client, message: Message):
    """Entry point for the Poster Studio: parses search query or OTT link and renders 1080p canvas."""
    _clean_sessions()
    user_id = message.from_user.id if message.from_user else message.chat.id

    query = None
    if len(message.command) > 1:
        query = message.text.split(maxsplit=1)[1].strip()
    elif message.reply_to_message:
        replied = message.reply_to_message
        query = replied.text or replied.caption

    if not query:
        await message.reply_text(
            "🎨 <b>Poster &amp; Leech Studio</b>\n\n"
            "Generate stunning studio posters with official logos, liquid glass badges, and multiple artworks!\n\n"
            "<b>Usage:</b>\n"
            "• <code>/poster [Movie, Anime or Series Name]</code>\n"
            "• <code>/poster [OTT or IMDb URL]</code>\n"
            "• Reply to any message or file with <code>/poster</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/poster Avengers Doomsday</code>\n"
            "• <code>/poster Inception</code>\n"
            "• <code>/poster Solo Leveling</code>\n\n"
            "💡 Use <code>/styles</code> to preview all styles!"
        )
        return

    status_msg = await message.reply_text(f"🎨 <b>Designing Poster Studio canvas for:</b> <code>{query[:40]}</code>...")

    try:
        media_data, detected_platform = await resolve_media_metadata(query)
        if not media_data:
            await status_msg.edit_text(
                f"❌ <b>Content Not Found.</b>\n\n"
                f"Could not retrieve media metadata for: <code>{query}</code>.\n"
                f"Please check the spelling or send a direct OTT/IMDb link."
            )
            return

        # Check premium VIP status and custom branding
        user_is_vip = await is_premium(user_id)
        brand = await get_poster_brand(user_id)

        # Candidate artworks list
        images = media_data.get("images", {})
        all_posters = images.get("all_posters") or ([images.get("portrait_poster")] if images.get("portrait_poster") else [])
        all_backdrops = images.get("all_backdrops") or ([images.get("banner_backdrop")] if images.get("banner_backdrop") else [])

        portrait_combos = build_portrait_combos(all_posters)
        landscape_combos = build_landscape_combos(all_backdrops)

        mode = "poster"
        p_idx = 0
        l_idx = 0

        initial_style, initial_art_idx = portrait_combos[p_idx]

        # Generate Poster Canvas
        canvas_io = generate_poster_canvas(initial_style, media_data, brand, user_is_vip, initial_art_idx)
        canvas_io.name = f"poster_{initial_style}_{initial_art_idx}.jpg"

        # Create session
        session_id = uuid.uuid4().hex[:12]
        POSTER_SESSIONS[session_id] = {
            "user_id": user_id,
            "media_data": media_data,
            "mode": mode,
            "p_idx": p_idx,
            "l_idx": l_idx,
            "portrait_combos": portrait_combos,
            "landscape_combos": landscape_combos,
            "current_style": initial_style,
            "art_index": initial_art_idx,
            "brand": brand,
            "is_premium": user_is_vip,
            "created_at": time.time(),
            "rendered_io": canvas_io
        }

        caption = format_poster_caption(media_data, mode, p_idx, len(portrait_combos), initial_style, brand, user_is_vip)
        markup = build_poster_keyboard(
            session_id, mode, p_idx, len(portrait_combos), l_idx, len(landscape_combos),
            len(all_posters), len(all_backdrops)
        )

        canvas_io.seek(0)
        await message.reply_photo(
            photo=canvas_io,
            caption=caption,
            reply_markup=markup
        )
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Error in poster studio: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Error generating poster:</b> <code>{e}</code>")


# ======================================================================
# 2. Unified Switcher Callbacks (Poster 2:3 & Landscape 16:9 Mix)
# ======================================================================
@Client.on_callback_query(filters.regex(r"^pmix_(p|l)_([a-f0-9]+)$"))
async def switch_poster_mix_callback(client: Client, query: CallbackQuery):
    """Switch or advance between Poster (Portrait 2:3) and Landscape (16:9) mixed combos."""
    target_mode_code = query.data.split("_")[1]
    session_id = query.data.split("_")[2]

    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired! Please run /poster again.", show_alert=True)
        except Exception:
            pass
        return

    target_mode = "poster" if target_mode_code == "p" else "landscape"
    current_mode = session.get("mode", "poster")

    portrait_combos = session.get("portrait_combos") or [(1, 0)]
    landscape_combos = session.get("landscape_combos") or [(2, 0)]

    p_idx = session.get("p_idx", 0)
    l_idx = session.get("l_idx", 0)

    if target_mode == "poster":
        if current_mode == "poster":
            p_idx = (p_idx + 1) % len(portrait_combos)
            session["p_idx"] = p_idx
        else:
            session["mode"] = "poster"
        style_id, art_idx = portrait_combos[p_idx]
        active_idx = p_idx
        total_active = len(portrait_combos)
        alert_text = f"📱 Rendering Poster ({active_idx + 1}/{total_active})..."
    else:
        if current_mode == "landscape":
            l_idx = (l_idx + 1) % len(landscape_combos)
            session["l_idx"] = l_idx
        else:
            session["mode"] = "landscape"
        style_id, art_idx = landscape_combos[l_idx]
        active_idx = l_idx
        total_active = len(landscape_combos)
        alert_text = f"🖥️ Rendering Landscape ({active_idx + 1}/{total_active})..."

    try:
        await query.answer(alert_text)
    except Exception:
        pass

    try:
        media_data = session["media_data"]
        brand = session["brand"]
        is_premium = session["is_premium"]

        canvas_io = generate_poster_canvas(style_id, media_data, brand, is_premium, art_idx)
        canvas_io.seek(0)
        canvas_io.name = f"poster_{style_id}_{art_idx}.jpg"
        session["current_style"] = style_id
        session["art_index"] = art_idx
        session["rendered_io"] = canvas_io

        all_posters = media_data.get("images", {}).get("all_posters", [])
        all_backdrops = media_data.get("images", {}).get("all_backdrops", [])

        caption = format_poster_caption(media_data, session["mode"], active_idx, total_active, style_id, brand, is_premium)
        markup = build_poster_keyboard(
            session_id, session["mode"], p_idx, len(portrait_combos), l_idx, len(landscape_combos),
            len(all_posters), len(all_backdrops)
        )

        canvas_io.seek(0)
        await query.message.edit_media(
            media=InputMediaPhoto(media=canvas_io, caption=caption),
            reply_markup=markup
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Error switching poster mix: {e}", exc_info=True)
        try:
            await query.answer("❌ Error rendering combo!", show_alert=True)
        except Exception:
            pass


# ======================================================================
# 3. Album Sender Callbacks (Send All Posters / All Wallpapers Album)
# ======================================================================
@Client.on_callback_query(filters.regex(r"^palbum_posters_([a-f0-9]+)$"))
async def send_posters_album_callback(client: Client, query: CallbackQuery):
    """Send ALL official vertical posters in Telegram media groups (up to 10 per group)."""
    session_id = query.data.split("_")[2]
    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired!", show_alert=True)
        except Exception:
            pass
        return

    all_posters = session["media_data"].get("images", {}).get("all_posters", [])
    if not all_posters:
        try:
            await query.answer("❌ No alternative posters found for this title.", show_alert=True)
        except Exception:
            pass
        return

    total = len(all_posters)
    try:
        await query.answer(f"📸 Sending all {total} posters...")
    except Exception:
        pass

    try:
        title = session["media_data"].get("display_title", "Movie")
        year = session["media_data"].get("year", "")
        year_str = f" ({year})" if year else ""

        # Send in chunks of 10
        for chunk_idx in range(0, total, 10):
            chunk = all_posters[chunk_idx:chunk_idx + 10]
            media_group = []
            for j, url in enumerate(chunk):
                item_num = chunk_idx + j + 1
                caption = f"🎬 <b>{title}{year_str}</b> — Official Posters Album ({item_num}/{total})" if j == 0 else ""
                media_group.append(InputMediaPhoto(media=url, caption=caption))
            await query.message.reply_media_group(media=media_group)
    except Exception as e:
        logger.error(f"Error sending posters album: {e}")
        try:
            await query.message.reply_text(f"❌ <b>Failed to send album:</b> <code>{e}</code>")
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^palbum_backdrops_([a-f0-9]+)$"))
async def send_backdrops_album_callback(client: Client, query: CallbackQuery):
    """Send ALL alternative 16:9 4K wallpapers in Telegram media groups (up to 10 per group)."""
    session_id = query.data.split("_")[2]
    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired!", show_alert=True)
        except Exception:
            pass
        return

    all_backdrops = session["media_data"].get("images", {}).get("all_backdrops", [])
    if not all_backdrops:
        try:
            await query.answer("❌ No alternative wallpapers found for this title.", show_alert=True)
        except Exception:
            pass
        return

    total = len(all_backdrops)
    try:
        await query.answer(f"🌄 Sending all {total} wallpapers...")
    except Exception:
        pass

    try:
        title = session["media_data"].get("display_title", "Movie")
        year = session["media_data"].get("year", "")
        year_str = f" ({year})" if year else ""

        # Send in chunks of 10
        for chunk_idx in range(0, total, 10):
            chunk = all_backdrops[chunk_idx:chunk_idx + 10]
            media_group = []
            for j, url in enumerate(chunk):
                item_num = chunk_idx + j + 1
                caption = f"🌄 <b>{title}{year_str}</b> — Official 16:9 Wallpapers ({item_num}/{total})" if j == 0 else ""
                media_group.append(InputMediaPhoto(media=url, caption=caption))
            await query.message.reply_media_group(media=media_group)
    except Exception as e:
        logger.error(f"Error sending backdrops album: {e}")
        try:
            await query.message.reply_text(f"❌ <b>Failed to send album:</b> <code>{e}</code>")
        except Exception:
            pass


# ======================================================================
# 5. Download Buttons (Portrait, Backdrop, Uncompressed)
# ======================================================================
@Client.on_callback_query(filters.regex(r"^pdoc_([a-f0-9]+)$"))
async def send_uncompressed_callback(client: Client, query: CallbackQuery):
    session_id = query.data.split("_")[1]
    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired!", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer("📁 Sending full quality uncompressed file...")
    except Exception:
        pass

    canvas_io = session.get("rendered_io")
    if not canvas_io:
        canvas_io = generate_poster_canvas(session["current_style"], session["media_data"], session["brand"], session["is_premium"], session.get("art_index", 0))

    canvas_io.seek(0)
    title_slug = session["media_data"].get("display_title", "poster").replace(" ", "_")[:20]
    canvas_io.name = f"{title_slug}_style{session['current_style']}.jpg"

    await query.message.reply_document(
        document=canvas_io,
        caption=f"📁 <b>Full HD Uncompressed File</b>\n🎨 Template: <code>{STYLE_NAMES.get(session['current_style'])}</code>"
    )


# ======================================================================
# 6. ImgBB Cloud Uploader
# ======================================================================
@Client.on_callback_query(filters.regex(r"^pimgbb_([a-f0-9]+)$"))
async def upload_imgbb_callback(client: Client, query: CallbackQuery):
    session_id = query.data.split("_")[1]
    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired!", show_alert=True)
        except Exception:
            pass
        return

    try:
        await query.answer("🌐 Uploading to ImgBB CDN...")
    except Exception:
        pass

    canvas_io = session.get("rendered_io")
    if not canvas_io:
        canvas_io = generate_poster_canvas(session["current_style"], session["media_data"], session["brand"], session["is_premium"], session.get("art_index", 0))

    canvas_io.seek(0)
    img_url = await upload_to_imgbb(canvas_io)
    if img_url:
        await query.message.reply_text(
            f"🌐 <b>ImgBB Direct CDN Image Link:</b>\n\n"
            f"🔗 <code>{img_url}</code>\n\n"
            f"💡 <i>You can use this direct link anywhere on websites or web players!</i>",
            disable_web_page_preview=False
        )
    else:
        try:
            await query.answer("❌ ImgBB upload failed. Please try again later.", show_alert=True)
        except Exception:
            pass


# ======================================================================
# 7. Direct Channel Publishing (Post to Channel)
# ======================================================================
@Client.on_callback_query(filters.regex(r"^ppublish_([a-f0-9]+)$"))
async def post_to_channel_callback(client: Client, query: CallbackQuery):
    session_id = query.data.split("_")[1]
    session = POSTER_SESSIONS.get(session_id)
    if not session:
        try:
            await query.answer("⚠️ Session expired!", show_alert=True)
        except Exception:
            pass
        return

    user_id = query.from_user.id
    target_channel = await get_poster_channel(user_id)

    if not target_channel:
        try:
            await query.answer(
                "⚠️ No channel configured!\n\nUse /set_poster_channel [channel_id] to connect your channel first.",
                show_alert=True
            )
        except Exception:
            pass
        return

    try:
        await query.answer("📣 Publishing to channel...")
    except Exception:
        pass

    try:
        canvas_io = session.get("rendered_io")
        if not canvas_io:
            canvas_io = generate_poster_canvas(session["current_style"], session["media_data"], session["brand"], session["is_premium"], session.get("art_index", 0))
        canvas_io.seek(0)
        canvas_io.name = "release_poster.jpg"

        bot_username = client.me.username if client.me else Config.BOT_USERNAME
        title = session["media_data"].get("display_title", "Movie")
        year = session["media_data"].get("year", "2024")

        year_str = f" ({year})" if year else ""
        genres = ", ".join(session["media_data"].get("genres", [])[:3])
        genres_line = f"\n🏷️ <i>{genres}</i>" if genres else ""
        rating = session["media_data"].get("rating")
        rating_line = f"\n⭐ <b>Rating:</b> <code>{rating}/10</code>" if rating and float(rating) > 0 else ""

        channel_caption = f"🎬 <b>{title}{year_str}</b>{genres_line}{rating_line}"

        clean_slug = title.replace(" ", "_")[:25]
        channel_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download & Watch Online ↗️", url=f"https://t.me/{bot_username}?start=search_{clean_slug}")]
        ])

        sent = await client.send_photo(
            chat_id=target_channel,
            photo=canvas_io,
            caption=channel_caption,
            reply_markup=channel_markup
        )
        await query.message.reply_text(
            f"✅ <b>Successfully Published to Channel!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{target_channel}</code>\n"
            f"🔗 <b>Message ID:</b> <code>{sent.id}</code>"
        )
    except Exception as e:
        logger.error(f"Failed to publish poster to channel {target_channel}: {e}")
        try:
            await query.message.reply_text(f"❌ <b>Failed to publish to channel:</b> <code>{e}</code>\n\n<i>Make sure the bot is an admin in the channel with Post Messages permission!</i>")
        except Exception:
            pass


# ======================================================================
# 8. Admin / User Branding & Channel Setup Commands
# ======================================================================
@Client.on_message(filters.command(["set_poster_brand", "setposterbrand", "setbrand"]))
async def set_poster_brand_command(client: Client, message: Message):
    """Set custom channel branding/watermark rendered on posters."""
    user_id = message.from_user.id if message.from_user else message.chat.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        current = await get_poster_brand(user_id)
        await message.reply_text(
            f"🏷️ <b>Current Poster Branding:</b> <code>{current}</code>\n\n"
            f"<b>Usage:</b> <code>/set_poster_brand [brand_name]</code>\n"
            f"<b>Example:</b> <code>/set_poster_brand AkMoviesZone</code>\n\n"
            f"💡 When set, all your generated posters will feature this watermark at the top-right!"
        )
        return

    new_brand = args[1].strip()
    success = await set_poster_brand(user_id, new_brand)
    if success:
        await message.reply_text(
            f"✅ <b>Poster Branding Updated!</b>\n\n"
            f"🏷️ <b>New Watermark:</b> <code>{new_brand}</code>\n"
            f"All future posters generated will render this brand badge."
        )
    else:
        await message.reply_text("❌ Failed to update poster branding.")


@Client.on_message(filters.command(["set_poster_channel", "setposterchannel"]))
async def set_poster_channel_command(client: Client, message: Message):
    """Set destination channel for 1-click 'Post to Channel' publishing."""
    user_id = message.from_user.id if message.from_user else message.chat.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        current = await get_poster_channel(user_id)
        current_str = f"<code>{current}</code>" if current else "<code>None (Not set)</code>"
        await message.reply_text(
            f"📢 <b>Current Poster Publish Channel:</b> {current_str}\n\n"
            f"<b>Usage:</b> <code>/set_poster_channel [channel_id]</code>\n"
            f"<b>Example:</b> <code>/set_poster_channel -1002001671856</code>\n\n"
            f"💡 Once set, clicking 📣 Post to Channel on any poster will broadcast it immediately!"
        )
        return

    try:
        ch_id = int(args[1].strip())
        success = await set_poster_channel(user_id, ch_id)
        if success:
            await message.reply_text(
                f"✅ <b>Publish Channel Configured!</b>\n\n"
                f"📢 <b>Channel ID:</b> <code>{ch_id}</code>\n"
                f"Make sure this bot is added as an <b>Admin</b> in the channel with 'Post Messages' permission."
            )
        else:
            await message.reply_text("❌ Failed to save channel ID in database.")
    except ValueError:
        await message.reply_text("⚠️ Invalid channel ID! It should be a number (e.g. <code>-1002001671856</code>).")


@Client.on_message(filters.command(["styles", "posterstyles"]))
async def list_styles_command(client: Client, message: Message):
    """Display all 7 available Spatial & Clean poster styles and descriptions."""
    text = (
        "🎨 <b>Poster Studio — 7 Clean &amp; Spatial Styles:</b>\n\n"
        "1. 📱 <b>Spatial Leech Poster (Portrait 2:3 - 1000×1500):</b>\n"
        "   Clean textless artwork, official transparent title logo, liquid glass pill badge, 4K UHD tag. Ideal for <b>Leech bots, torrent releases, and movie files</b>!\n\n"
        "2. 🌄 <b>Spatial Cinema Banner (Landscape 16:9 - 1920×1080):</b>\n"
        "   Full 16:9 widescreen backdrop, official title logo, liquid glass pill badge. Ideal for <b>channel header posts &amp; web players</b>!\n\n"
        "3. 🖤 <b>Minimalist Letterbox (16:9):</b>\n"
        "   Centered cinema typography layout with movie title and release year.\n\n"
        "4. 💎 <b>Frosted Glass Floating Card (16:9):</b>\n"
        "   Ambient blurred background with floating vertical portrait card and metadata pill.\n\n"
        "5. ⭐ <b>Multi-Ratings Studio Card (Portrait 2:3):</b>\n"
        "   Clean vertical poster with official logo and multi-source ratings pill.\n\n"
        "6. 🌸 <b>Anime Studio Edition (16:9):</b>\n"
        "   Japanese romaji/native subtitle + English title + studio tag.\n\n"
        "7. 🖼️ <b>Pure Clean Artwork:</b>\n"
        "   Untouched high-res original backdrop artwork with subtle branding watermark only.\n\n"
        "💡 <b>Generate any poster using:</b> <code>/poster [Movie / Anime / Series]</code>\n"
        "Then use <b>⏪ Prev Style | Next Style ⏩</b> and <b>◀️ Prev Art | Next Art ▶️</b> to explore!"
    )
    await message.reply_text(text)


@Client.on_callback_query(filters.regex(r"^pinfo_"))
async def poster_info_callback(client: Client, query: CallbackQuery):
    try:
        await query.answer("💡 Use ⏪ Prev Style and Next Style ⏩ to change the design template!", show_alert=True)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^partinfo_"))
async def poster_artinfo_callback(client: Client, query: CallbackQuery):
    try:
        await query.answer("💡 Use ◀️ Prev Art and Next Art ▶️ to switch between different official movie posters!", show_alert=True)
    except Exception:
        pass
