import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from utils.helpers import is_private_chat
from database.chats import (
    get_chat_settings,
    update_chat_setting,
    connect_user_to_chat,
    disconnect_user_from_chat,
    get_user_connected_chats,
    add_chat
)

logger = logging.getLogger(__name__)

def build_settings_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    """Build interactive toggle keyboard for chat preferences."""
    auto_del = "✅ ON" if settings.get("auto_delete", True) else "❌ OFF"
    del_time = settings.get("auto_delete_time", 300)
    del_label = f"{del_time // 60}m" if del_time >= 60 else f"{del_time}s"
    shortener_status = "✅ ON" if settings.get("shortener_enabled", True) else "❌ OFF"
    btn_mode = "Single (Wide)" if settings.get("single_button", True) else "Double (Compact)"

    keyboard = [
        [
            InlineKeyboardButton(f"Auto-Delete: {auto_del}", callback_data=f"set_autodel_{chat_id}"),
            InlineKeyboardButton(f"Timer: {del_label}", callback_data=f"set_timer_{chat_id}")
        ],
        [
            InlineKeyboardButton(f"Shortener: {shortener_status}", callback_data=f"set_shortener_{chat_id}"),
            InlineKeyboardButton(f"Buttons: {btn_mode}", callback_data=f"set_btnmode_{chat_id}")
        ],
        [
            InlineKeyboardButton("❌ Close Settings", callback_data="close_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


@Client.on_message(filters.group & filters.new_chat_members)
async def new_chat_member_listener(client: Client, message: Message):
    """Listen for when the bot is added to a new group and log it."""
    for member in message.new_chat_members:
        if member.id == client.me.id:
            await add_chat(message.chat.id, message.chat.title)
            if Config.LOG_CHANNEL:
                try:
                    from database.chats import get_total_chats_count
                    total_groups = await get_total_chats_count()
                    added_by = message.from_user.mention if message.from_user else "Unknown"
                    log_text = (
                        "👥 <b>#NewGroup Added!</b>\n\n"
                        f"• <b>Group Title:</b> <code>{message.chat.title}</code>\n"
                        f"• <b>Group ID:</b> <code>{message.chat.id}</code>\n"
                        f"• <b>Added By:</b> {added_by}\n"
                        f"• <b>Total Groups Now:</b> <code>{total_groups:,}</code>"
                    )
                    await client.send_message(Config.LOG_CHANNEL, log_text)
                except Exception as e:
                    logger.debug(f"Error sending new group log: {e}")


# /settings Command
@Client.on_message(filters.command("settings"))
async def chat_settings_command(client: Client, message: Message):
    """Open interactive settings panel for group preferences."""
    if not message.from_user:
        await message.reply_text("⚠️ Please send this command as a user, not an anonymous channel.")
        return

    is_pm = is_private_chat(message)
    user_id = message.from_user.id

    if is_pm:
        # Show connected groups in PM
        connected_chats = await get_user_connected_chats(user_id)
        if not connected_chats:
            await message.reply_text(
                "ℹ️ <b>No Connected Groups Found!</b>\n\n"
                "To manage a group's settings from your PM:\n"
                "1. Add me as an Admin in your group.\n"
                "2. Send <code>/connect</code> inside your group.\n"
                "3. Then use <code>/settings</code> here in PM to manage it privately!"
            )
            return

        buttons = []
        for chat in connected_chats:
            title = chat.get("title", f"Group {chat['chat_id']}")
            buttons.append([InlineKeyboardButton(f"⚙️ {title[:30]}", callback_data=f"openset_{chat['chat_id']}")])

        await message.reply_text("👉 <b>Select a connected group to configure:</b>", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # In Group: Verify user is group admin
    chat_id = message.chat.id
    try:
        member = await client.get_chat_member(chat_id, user_id)
        if member.status not in ["creator", "administrator"] and not Config.is_admin(user_id):
            await message.reply_text("⛔ <b>Only group administrators can modify bot settings!</b>")
            return
    except Exception:
        return

    await add_chat(chat_id, message.chat.title or "")
    settings = await get_chat_settings(chat_id)
    markup = build_settings_keyboard(chat_id, settings)

    await message.reply_text(
        f"⚙️ <b>Settings for:</b> <code>{message.chat.title}</code>\n"
        f"Configure auto-delete, button layouts, and monetization below:",
        reply_markup=markup
    )


# Group Connection Commands: /connect & /disconnect
@Client.on_message(filters.command("connect") & filters.group)
async def connect_group_command(client: Client, message: Message):
    """Connect group to admin's PM for private settings management."""
    if not message.from_user:
        await message.reply_text("⚠️ Please send this command as a user, not an anonymous channel.")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    member = await client.get_chat_member(chat_id, user_id)
    if member.status not in ["creator", "administrator"] and not Config.is_admin(user_id):
        await message.reply_text("⛔ You must be a group administrator to connect this group!")
        return

    await add_chat(chat_id, message.chat.title or "")
    await connect_user_to_chat(user_id, chat_id)

    await message.reply_text(
        f"✅ <b>Successfully Connected!</b>\n\n"
        f"You can now manage <code>{message.chat.title}</code> settings privately by sending <code>/settings</code> in my PM!"
    )


@Client.on_message(filters.command("disconnect") & filters.group)
async def disconnect_group_command(client: Client, message: Message):
    """Unlink group from admin PM."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = message.chat.id

    await disconnect_user_from_chat(user_id, chat_id)
    await message.reply_text("✅ <b>Group disconnected from your PM settings list.</b>")


# Group Admin Custom Shortener: /shortlink <domain> <api_key>
@Client.on_message(filters.command("shortlink"))
async def set_group_shortener_command(client: Client, message: Message):
    """Configure custom shortener credentials for a group."""
    if not message.from_user:
        return
    if is_private_chat(message):
        await message.reply_text("⚠️ <b>Usage:</b> Please send <code>/shortlink [domain] [api_key]</code> inside the group you want to configure.")
        return

    user_id = message.from_user.id
    args = message.text.split()

    if len(args) < 3:
        await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/shortlink [shortener_website] [api_key]</code>\n"
            "Example: <code>/shortlink shareus.io my_secret_api_key_123</code>"
        )
        return

    chat_id = message.chat.id
    member = await client.get_chat_member(chat_id, user_id)
    if member.status not in ["creator", "administrator"] and not Config.is_admin(user_id):
        await message.reply_text("⛔ Only group administrators can configure shortener links.")
        return

    domain = args[1].strip()
    api_key = args[2].strip()

    await update_chat_setting(chat_id, "custom_shortener_url", domain)
    await update_chat_setting(chat_id, "custom_shortener_api", api_key)

    await message.reply_text(f"✅ <b>Custom Shortener Configured!</b>\n\n<b>Website:</b> <code>{domain}</code>\n<b>API Key:</b> <code>{api_key[:6]}******</code>")


# Settings Callbacks
@Client.on_callback_query(filters.regex(r"^openset_"))
async def open_settings_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("openset_")[1])
    settings = await get_chat_settings(chat_id)
    markup = build_settings_keyboard(chat_id, settings)
    await query.message.edit_text(f"⚙️ <b>Configuring Group:</b> <code>{chat_id}</code>", reply_markup=markup)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^set_autodel_"))
async def toggle_autodel_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("set_autodel_")[1])
    settings = await get_chat_settings(chat_id)
    new_val = not settings.get("auto_delete", True)
    await update_chat_setting(chat_id, "auto_delete", new_val)
    settings["auto_delete"] = new_val
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(chat_id, settings))
    await query.answer("Auto-Delete updated!")


@Client.on_callback_query(filters.regex(r"^set_timer_"))
async def cycle_timer_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("set_timer_")[1])
    settings = await get_chat_settings(chat_id)
    timers = [60, 180, 300, 600]
    current = settings.get("auto_delete_time", 300)
    new_timer = timers[(timers.index(current) + 1) % len(timers)] if current in timers else 300
    await update_chat_setting(chat_id, "auto_delete_time", new_timer)
    settings["auto_delete_time"] = new_timer
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(chat_id, settings))
    await query.answer(f"Timer set to {new_timer}s!")


@Client.on_callback_query(filters.regex(r"^set_imdb_"))
async def toggle_imdb_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("set_imdb_")[1])
    settings = await get_chat_settings(chat_id)
    new_val = not settings.get("imdb_enabled", True)
    await update_chat_setting(chat_id, "imdb_enabled", new_val)
    settings["imdb_enabled"] = new_val
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(chat_id, settings))
    await query.answer("IMDb setting updated!")


@Client.on_callback_query(filters.regex(r"^set_shortener_"))
async def toggle_shortener_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("set_shortener_")[1])
    settings = await get_chat_settings(chat_id)
    new_val = not settings.get("shortener_enabled", True)
    await update_chat_setting(chat_id, "shortener_enabled", new_val)
    settings["shortener_enabled"] = new_val
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(chat_id, settings))
    await query.answer("Shortener setting updated!")


@Client.on_callback_query(filters.regex(r"^set_btnmode_"))
async def toggle_btnmode_callback(client: Client, query: CallbackQuery):
    chat_id = int(query.data.split("set_btnmode_")[1])
    settings = await get_chat_settings(chat_id)
    new_val = not settings.get("single_button", True)
    await update_chat_setting(chat_id, "single_button", new_val)
    settings["single_button"] = new_val
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(chat_id, settings))
    await query.answer(f"Switched to {'Single' if new_val else 'Double'} button mode!")


@Client.on_callback_query(filters.regex(r"^close_settings"))
async def close_settings_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
    except Exception:
        pass
