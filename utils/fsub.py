import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
    from hydrogram.errors import UserNotParticipant
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
    from pyrogram.errors import UserNotParticipant
from config import Config

logger = logging.getLogger(__name__)

async def check_fsub(client: Client, user_id: int) -> tuple[bool, list[dict]]:
    """Verify user membership across all configured Force-Subscribe channels."""
    if Config.is_admin(user_id):
        return True, []

    channels_to_check = list(Config.FORCE_SUB_CHANNELS)
    if not channels_to_check:
        return True, []

    unjoined = []

    for channel in channels_to_check:
        try:
            # Handle username or ID
            chat_identifier = int(channel) if str(channel).lstrip("-").isdigit() else channel
            member = await client.get_chat_member(chat_identifier, user_id)
            if member.status in ["kicked", "left"]:
                chat = await client.get_chat(chat_identifier)
                invite_link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else await client.export_chat_invite_link(chat_identifier))
                unjoined.append({"title": chat.title, "link": invite_link})
        except UserNotParticipant:
            try:
                chat = await client.get_chat(chat_identifier)
                invite_link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else await client.export_chat_invite_link(chat_identifier))
                unjoined.append({"title": chat.title, "link": invite_link})
            except Exception as e:
                logger.error(f"Error resolving invite link for FSub channel {channel}: {e}")
        except Exception as e:
            logger.debug(f"FSub check exception for channel {channel}: {e}")

    return len(unjoined) == 0, unjoined


def build_fsub_markup(unjoined_channels: list[dict], file_unique_id: str = "") -> InlineKeyboardMarkup:
    """Build inline buttons for unjoined channels and a Try Again retry button."""
    buttons = []

    for idx, chan in enumerate(unjoined_channels, start=1):
        title = chan.get("title") or f"Channel {idx}"
        link = chan.get("link", "https://t.me/")
        buttons.append([InlineKeyboardButton(f"📢 Join {title[:25]}", url=link)])

    # Retry button
    if file_unique_id:
        if file_unique_id.startswith("batch_") or file_unique_id.startswith("file_"):
            retry_url = f"https://t.me/{Config.BOT_USERNAME}?start={file_unique_id}"
        else:
            retry_url = f"https://t.me/{Config.BOT_USERNAME}?start=file_{file_unique_id}"
        buttons.append([InlineKeyboardButton("🔄 Try Again", url=retry_url)])

    return InlineKeyboardMarkup(buttons)
