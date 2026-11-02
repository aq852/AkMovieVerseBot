import urllib.parse
import logging
import asyncio
from io import BytesIO

try:
    from hydrogram import Client, filters
    from hydrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
    )
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
    )

from config import Config
from database.mongo import mongo
from utils.helpers import get_readable_size, parse_media_metadata
from utils.web_server import resolve_file_from_param

logger = logging.getLogger("autofilter.stream")

# In-memory registry to delete previous stream cards and prevent chat clutter
_active_stream_cards: dict[tuple[int, str], Message] = {}


async def auto_delete_stream_card(msg: Message, delay: int = 300):
    """Auto-delete stream card message after delay (default 5 minutes)."""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass


def get_effective_stream_base_url() -> str:
    """Return effective streaming base URL for Telegram buttons.
    Guarantees the hostname is never 'localhost' because Telegram MTProto API strictly
    rejects 'localhost' with [400 BUTTON_URL_INVALID].
    """
    url = Config.STREAM_URL or Config.WEB_URL
    if url and url.strip():
        url = url.strip().rstrip("/")
        if "localhost" in url:
            url = url.replace("localhost", "127.0.0.1")
        return url
    return f"http://127.0.0.1:{Config.PORT}"


def build_stream_keyboard(base_url: str, file_unique_id: str, file_name: str, token: str = "") -> InlineKeyboardMarkup:
    """Build minimalist, ultra-clean streaming keyboard for Telegram PM."""
    if "localhost" in base_url:
        base_url = base_url.replace("localhost", "127.0.0.1")

    watch_url = f"{base_url}/watch/{file_unique_id}"
    if token:
        watch_url += f"?token={token}"

    buttons = [
        # Row 1: Direct Web Player Hub (All features: Any Player, MX, VLC, Download, Copy Link & M3U live inside)
        [
            InlineKeyboardButton("⚡ Stream & Watch Online ↗️", url=watch_url)
        ],
        # Row 2: Instant Dismiss / Close
        [
            InlineKeyboardButton("❌ Close", callback_data="close_stream_hub")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


@Client.on_callback_query(filters.regex(r"^stream_([a-zA-Z0-9_\-]+)$"))
async def stream_options_callback(client: Client, query: CallbackQuery):
    """Present streaming and web player hub for a delivered file with auto-delete & zero clutter."""
    try:
        file_unique_id = query.data.split("_", 1)[1]

        file_doc = await resolve_file_from_param(file_unique_id)
        if not file_doc:
            await query.answer("❌ File not found in database.", show_alert=True)
            return

        await query.answer("⚡ Generating streaming link...")

        base_url = get_effective_stream_base_url()

        file_name = file_doc.get("file_name", "Movie Video.mp4")
        file_size = int(file_doc.get("file_size", 0))
        size_str = get_readable_size(file_size)

        meta = parse_media_metadata(file_name)
        clean_title = meta["title"]
        qual_badge = f" | <code>{meta['quality']}</code>" if meta["quality"] else ""
        dual_badge = "\n🎧 <b>Audio:</b> <code>Multi-Audio / Dual Audio</code>" if meta["is_dual_audio"] else ""

        user_id = query.from_user.id if query.from_user else 0
        from database.users import is_premium
        is_vip = await is_premium(user_id) or Config.is_admin(user_id)
        token = ""
        if is_vip:
            from utils.web_server import generate_vip_stream_token
            token = generate_vip_stream_token(user_id)

        markup = build_stream_keyboard(base_url, file_unique_id, file_name, token=token)

        text = (
            f"🎬 <b>{clean_title}</b>\n\n"
            f"📦 <b>File Size:</b> <code>{size_str}</code>{qual_badge}{dual_badge}\n"
            f"⚡ <b>Playback:</b> <code>High-Speed Stream Ready</code>\n\n"
            f"⏳ <i>Note: This link will auto-delete in 5 minutes to protect copyright.</i>"
        )

        chat_id = query.message.chat.id
        cache_key = (chat_id, file_unique_id)

        # Remove previous active stream card for this file to avoid clutter
        prev_msg = _active_stream_cards.get(cache_key)
        if prev_msg:
            try:
                await prev_msg.delete()
            except Exception:
                pass

        sent_msg = await query.message.reply_text(
            text=text,
            reply_markup=markup,
            disable_web_page_preview=True
        )
        _active_stream_cards[cache_key] = sent_msg

        # Auto-delete stream card after AUTO_DELETE_TIME (default 5 minutes)
        del_time = getattr(Config, "AUTO_DELETE_TIME", 300)
        asyncio.create_task(auto_delete_stream_card(sent_msg, delay=del_time))

    except Exception as e:
        logger.error(f"Error handling stream options callback: {e}", exc_info=True)
        try:
            await query.answer(f"❌ Error: {e}", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^close_stream_hub$"))
async def close_stream_hub_callback(client: Client, query: CallbackQuery):
    """Delete stream hub message on close button."""
    try:
        await query.message.delete()
    except Exception:
        pass


@Client.on_message(filters.command(["stream", "streamlink"]))
async def stream_command_handler(client: Client, message: Message):
    """Generate instant streaming hub by replying to any media file with /stream."""
    try:
        replied = message.reply_to_message
        target_msg = replied if replied else message

        media = (
            target_msg.video or
            target_msg.document or
            target_msg.audio or
            target_msg.animation
        )

        if not media:
            args = message.text.split()
            if len(args) > 1 and Config.is_admin(message.from_user.id):
                action = args[1].lower()
                from database.mongo import set_bot_setting
                if action in ("on", "enable", "true", "yes"):
                    Config.ENABLE_STREAMING = True
                    await set_bot_setting("enable_streaming", True)
                    await message.reply_text(
                        "🟢 <b>Fast Video Streaming & Web Player Enabled!</b>\n\n"
                        "• Users can now stream media directly in-browser and players.\n"
                        "💾 <i>Saved permanently to database (persists across restarts).</i>"
                    )
                    return
                elif action in ("off", "disable", "false", "no"):
                    Config.ENABLE_STREAMING = False
                    await set_bot_setting("enable_streaming", False)
                    await message.reply_text(
                        "🔴 <b>Fast Video Streaming & Web Player Disabled!</b>\n\n"
                        "• Fast streaming engine is now turned OFF.\n"
                        "💾 <i>Saved permanently to database (persists across restarts).</i>"
                    )
                    return
                elif action in ("status", "info"):
                    st = "🟢 <b>ENABLED</b>" if Config.ENABLE_STREAMING else "🔴 <b>DISABLED</b>"
                    await message.reply_text(
                        f"⚡ <b>Fast Streaming Engine:</b> {st}\n\n"
                        f"• <code>/stream on</code> — Turn streaming ON\n"
                        f"• <code>/stream off</code> — Turn streaming OFF"
                    )
                    return

            await message.reply_text(
                "⚡ <b>Fast Stream & Web Player Hub</b>\n\n"
                "Generate instant direct streaming and high-speed download links for any Telegram video!\n\n"
                "<b>Usage:</b>\n"
                "• Reply to any video, document, or audio file with <code>/stream</code>\n\n"
                "💡 <i>Features: In-browser Cinema Player, MX Player, VLC, and M3U playlist export!</i>"
            )
            return

        file_unique_id = media.file_unique_id
        file_doc = await resolve_file_from_param(file_unique_id)

        # If file was not yet indexed in database, store in temp stream cache and forward to LOG_CHANNEL
        if not file_doc:
            status_msg = await message.reply_text("⚡ <i>Preparing streaming engine...</i>")
            fwd = None
            if Config.LOG_CHANNEL:
                try:
                    fwd = await target_msg.forward(Config.LOG_CHANNEL)
                except Exception as e:
                    logger.debug(f"Could not forward to LOG_CHANNEL for streaming: {e}")

            media_dict = {
                "file_id": media.file_id,
                "file_unique_id": file_unique_id,
                "file_name": getattr(media, "file_name", None) or f"video_{target_msg.id}.mp4",
                "file_size": getattr(media, "file_size", 0),
                "file_type": "video" if target_msg.video else "document",
                "mime_type": getattr(media, "mime_type", "video/mp4"),
                "caption": target_msg.caption or "",
                "channel_id": fwd.chat.id if fwd else target_msg.chat.id,
                "message_id": fwd.id if fwd else target_msg.id
            }
            # Save into temp_stream_files (isolated from search index so personal stream files never get auto-indexed!)
            try:
                await mongo.db["temp_stream_files"].replace_one(
                    {"file_unique_id": file_unique_id},
                    media_dict,
                    upsert=True
                )
            except Exception as e:
                logger.error(f"Error saving temp stream file: {e}")
            file_doc = media_dict
            try:
                await status_msg.delete()
            except Exception:
                pass

        base_url = get_effective_stream_base_url()

        file_name = file_doc.get("file_name", "Movie Video.mp4")
        file_size = int(file_doc.get("file_size", 0))
        size_str = get_readable_size(file_size)

        meta = parse_media_metadata(file_name)
        clean_title = meta["title"]
        qual_badge = f" | <code>{meta['quality']}</code>" if meta["quality"] else ""
        dual_badge = "\n🎧 <b>Audio:</b> <code>Multi-Audio / Dual Audio</code>" if meta["is_dual_audio"] else ""

        user_id = message.from_user.id if message.from_user else 0
        from database.users import is_premium
        is_vip = await is_premium(user_id) or Config.is_admin(user_id)
        token = ""
        if is_vip:
            from utils.web_server import generate_vip_stream_token
            token = generate_vip_stream_token(user_id)

        markup = build_stream_keyboard(base_url, file_unique_id, file_name, token=token)

        text = (
            f"🎬 <b>{clean_title}</b>\n\n"
            f"📦 <b>File Size:</b> <code>{size_str}</code>{qual_badge}{dual_badge}\n"
            f"⚡ <b>Playback:</b> <code>High-Speed Stream Ready</code>\n\n"
            f"⏳ <i>Note: This link will auto-delete in 5 minutes to protect copyright.</i>"
        )

        sent_msg = await message.reply_text(
            text=text,
            reply_markup=markup,
            disable_web_page_preview=True
        )

        del_time = getattr(Config, "AUTO_DELETE_TIME", 300)
        asyncio.create_task(auto_delete_stream_card(sent_msg, delay=del_time))

    except Exception as e:
        logger.error(f"Error in stream_command_handler: {e}", exc_info=True)
        await message.reply_text(f"❌ <b>Stream Error:</b> <code>{e}</code>")
