import logging
try:
    from hydrogram import Client
    from hydrogram.types import (
        InlineQuery,
        InlineQueryResultArticle,
        InputTextMessageContent,
        InlineKeyboardMarkup,
        InlineKeyboardButton
    )
except ImportError:
    from pyrogram import Client
    from pyrogram.types import (
        InlineQuery,
        InlineQueryResultArticle,
        InputTextMessageContent,
        InlineKeyboardMarkup,
        InlineKeyboardButton
    )
from config import Config
from database.files import get_search_results
from utils.helpers import get_readable_size, clean_search_query

logger = logging.getLogger(__name__)

@Client.on_inline_query()
async def inline_search_handler(client: Client, query: InlineQuery):
    """Handle inline file searches from any chat using @BotUsername <query>."""
    raw_query = query.query.strip()
    clean_q = clean_search_query(raw_query)

    if not clean_q:
        results = [
            InlineQueryResultArticle(
                title="🔍 Search in Auto Filter Bot",
                description="Type any movie or series name to search indexed files...",
                input_message_content=InputTextMessageContent(
                    "👉 <b>Type any movie, show, or document title to search our library!</b>"
                )
            )
        ]
        await query.answer(results, cache_time=5)
        return

    files = await get_search_results(clean_q, offset=0, limit=25)
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    results = []
    for file_doc in files:
        title = file_doc.get("file_name", "Untitled")
        size_str = get_readable_size(file_doc.get("file_size", 0))
        file_unique_id = file_doc.get("file_unique_id")
        file_type = file_doc.get("file_type", "file").capitalize()

        deep_url = f"https://t.me/{bot_username}?start=file_{file_unique_id}"

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📥 Download ({size_str})", url=deep_url)]
        ])

        message_content = InputTextMessageContent(
            f"🎬 <b>Title:</b> <code>{title}</code>\n"
            f"📁 <b>Type:</b> <code>{file_type}</code> | <b>Size:</b> <code>{size_str}</code>\n\n"
            f"👉 <i>Click the button below to retrieve this file in bot PM:</i>"
        )

        results.append(
            InlineQueryResultArticle(
                title=f"🎬 {title}",
                description=f"Size: {size_str} | Type: {file_type}",
                input_message_content=message_content,
                reply_markup=btn
            )
        )

    if not results:
        results = [
            InlineQueryResultArticle(
                title="⚠️ No files found",
                description=f"No results found for '{clean_q}'. Try a different keyword.",
                input_message_content=InputTextMessageContent(
                    f"⚠️ No files found matching: <code>{clean_q}</code>"
                )
            )
        ]

    await query.answer(results, cache_time=5)
