import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from utils.helpers import is_private_chat
from database.filters import (
    add_manual_filter,
    get_manual_filter,
    get_all_manual_filters,
    delete_manual_filter,
    delete_all_manual_filters
)

logger = logging.getLogger(__name__)

async def is_admin_or_owner(client: Client, message: Message) -> bool:
    """Check if the user is a group administrator or bot owner."""
    if not message.from_user:
        return False
    user_id = message.from_user.id
    if Config.is_admin(user_id):
        return True
    if is_private_chat(message):
        return True
    try:
        member = await client.get_chat_member(message.chat.id, user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False


# 1. /filter <keyword> <reply_text> or reply with /filter <keyword>
@Client.on_message(filters.command("filter") & (filters.group | filters.private))
async def add_filter_command(client: Client, message: Message):
    """Add a custom keyword filter with text or replied media."""
    if not await is_admin_or_owner(client, message):
        await message.reply_text("⛔ **Only group administrators can add custom filters!**")
        return

    chat_id = message.chat.id
    reply = message.reply_to_message
    args = message.text.split(maxsplit=2)

    keyword = None
    reply_text = ""
    file_id = None

    if reply:
        if len(args) < 2:
            await message.reply_text("⚠️ **Usage:** Reply to any message/media with `/filter [keyword]`")
            return
        keyword = args[1].lower().strip()
        reply_text = reply.caption or reply.text or f"Here is your file for {keyword}"
        media = reply.document or reply.video or reply.audio or reply.photo
        if media:
            file_id = media.file_id
    else:
        if len(args) < 3:
            await message.reply_text(
                "⚠️ **Usage:**\n"
                "• `/filter [keyword] [reply_text]`\n"
                "• Or reply to any media/message with `/filter [keyword]`"
            )
            return
        keyword = args[1].lower().strip()
        reply_text = args[2].strip()

    if not keyword:
        await message.reply_text("❌ Invalid filter keyword.")
        return

    success = await add_manual_filter(chat_id, keyword, reply_text, file_id)
    if success:
        await message.reply_text(
            f"✅ **Filter Added Successfully!**\n\n"
            f"• **Keyword:** `{keyword}`\n"
            f"• **Type:** `{'Media File 📁' if file_id else 'Text Message 📝'}`\n\n"
            f"Whenever someone types `{keyword}`, the bot will automatically reply with this response!"
        )
    else:
        await message.reply_text("❌ Failed to save filter to database.")


# 2. /filters (List all active filters in this chat)
@Client.on_message(filters.command("filters") & (filters.group | filters.private))
async def list_filters_command(client: Client, message: Message):
    """List all custom manual filters saved in this chat."""
    chat_id = message.chat.id
    filters_list = await get_all_manual_filters(chat_id)

    if not filters_list:
        await message.reply_text(
            "ℹ️ **No manual filters configured for this chat!**\n\n"
            "To add a filter, send:\n"
            "`/filter [keyword] [reply text]` or reply to any file with `/filter [keyword]`"
        )
        return

    lines = [f"📋 **Active Custom Filters in this Chat ({len(filters_list)} Total):**\n"]
    for i, kw in enumerate(filters_list, 1):
        lines.append(f"{i}. `{kw}`")

    lines.append("\n💡 **Manage:**\n• `/stop [keyword]` — Delete a filter\n• `/stopall` — Clear all filters")
    await message.reply_text("\n".join(lines))


# 3. /stop [keyword] (Delete a specific filter)
@Client.on_message(filters.command("stop") & (filters.group | filters.private))
async def stop_filter_command(client: Client, message: Message):
    """Delete a specific manual keyword filter."""
    if not await is_admin_or_owner(client, message):
        await message.reply_text("⛔ **Only group administrators can remove filters!**")
        return

    chat_id = message.chat.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("⚠️ **Usage:** `/stop [keyword]`")
        return

    keyword = args[1].lower().strip()
    success = await delete_manual_filter(chat_id, keyword)
    if success:
        await message.reply_text(f"✅ Filter for `{keyword}` has been deleted.")
    else:
        await message.reply_text(f"❌ Filter `{keyword}` not found in this chat.")


# 4. /stopall (Clear all filters in this chat)
@Client.on_message(filters.command("stopall") & (filters.group | filters.private))
async def stop_all_filters_command(client: Client, message: Message):
    """Purge all manual keyword filters in this chat."""
    if not await is_admin_or_owner(client, message):
        await message.reply_text("⛔ **Only group administrators can clear all filters!**")
        return

    chat_id = message.chat.id
    deleted_count = await delete_all_manual_filters(chat_id)
    await message.reply_text(f"💥 **Cleared `{deleted_count}` custom filters from this chat!**")
