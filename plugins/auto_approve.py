import asyncio
import time
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton, Message
    from hydrogram.errors import FloodWait
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton, Message
    from pyrogram.errors import FloodWait

from config import Config
from database.users import add_user
from utils.helpers import get_chat_type_str

logger = logging.getLogger(__name__)

CUSTOM_WELCOME_TEXT = None
CUSTOM_WELCOME_PIC = None

DEFAULT_WELCOME_TEXT = (
    "🎉 **Hello {mention},**\n\n"
    "<blockquote>**YOUR REQUEST TO JOIN {title} HAS BEEN APPROVED! ✅**</blockquote>\n\n"
    "🍿 **Welcome to AkMovieVerse!**\n"
    "Search, find and download your favourite movies & web series directly here."
)

AUTO_APPROVE_CHANNELS_CACHE = None

async def get_auto_approve_channels() -> list[int]:
    """Fetch the list of channel IDs where auto-approve is active."""
    global AUTO_APPROVE_CHANNELS_CACHE
    if AUTO_APPROVE_CHANNELS_CACHE is not None:
        return AUTO_APPROVE_CHANNELS_CACHE

    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"setting": "auto_approve_channels"})
        if doc and "channels" in doc and isinstance(doc["channels"], list):
            AUTO_APPROVE_CHANNELS_CACHE = [int(c) for c in doc["channels"] if str(c).lstrip("-").isdigit()]
            return AUTO_APPROVE_CHANNELS_CACHE
    except Exception:
        pass

    # Fallback to Config
    if getattr(Config, "AUTO_APPROVE_CHANNELS", None):
        AUTO_APPROVE_CHANNELS_CACHE = list(Config.AUTO_APPROVE_CHANNELS)
    else:
        defaults = set()
        if Config.CHANNELS:
            defaults.update(Config.CHANNELS)
        if getattr(Config, "UPDATES_CHANNEL", None):
            defaults.add(Config.UPDATES_CHANNEL)
        AUTO_APPROVE_CHANNELS_CACHE = list(defaults)

    return AUTO_APPROVE_CHANNELS_CACHE


async def add_auto_approve_channel(channel_id: int):
    channels = await get_auto_approve_channels()
    if channel_id not in channels:
        channels.append(channel_id)
        from database.mongo import mongo
        await mongo.db["bot_settings"].update_one(
            {"setting": "auto_approve_channels"},
            {"$set": {"channels": channels}},
            upsert=True
        )
        global AUTO_APPROVE_CHANNELS_CACHE
        AUTO_APPROVE_CHANNELS_CACHE = channels


async def del_auto_approve_channel(channel_id: int):
    channels = await get_auto_approve_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        from database.mongo import mongo
        await mongo.db["bot_settings"].update_one(
            {"setting": "auto_approve_channels"},
            {"$set": {"channels": channels}},
            upsert=True
        )
        global AUTO_APPROVE_CHANNELS_CACHE
        AUTO_APPROVE_CHANNELS_CACHE = channels

async def get_welcome_text() -> str:
    """Fetch custom or default welcome message template."""
    global CUSTOM_WELCOME_TEXT
    if CUSTOM_WELCOME_TEXT is not None:
        return CUSTOM_WELCOME_TEXT
    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"setting": "auto_approve_welcome"})
        if doc and doc.get("text"):
            CUSTOM_WELCOME_TEXT = doc["text"]
            return CUSTOM_WELCOME_TEXT
    except Exception:
        pass
    return DEFAULT_WELCOME_TEXT


def safe_format_welcome(template: str, **kwargs) -> str:
    """Format template safely without crashing on missing keys or stray braces."""
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    try:
        return template.format_map(SafeDict(**kwargs))
    except Exception:
        res = template
        for k, v in kwargs.items():
            res = res.replace("{" + k + "}", str(v))
        return res


async def get_welcome_pic() -> str:
    """Fetch custom photo URL or dynamic random anime wallpaper."""
    global CUSTOM_WELCOME_PIC
    if CUSTOM_WELCOME_PIC is not None:
        return CUSTOM_WELCOME_PIC
    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"setting": "auto_approve_pic"})
        if doc and doc.get("pic"):
            CUSTOM_WELCOME_PIC = doc["pic"]
            return CUSTOM_WELCOME_PIC
    except Exception:
        pass
    # Dynamic anime artwork with millisecond cache-buster
    return f"https://api.aniwallpaper.workers.dev/random?_t={int(time.time() * 1000)}"


@Client.on_chat_join_request()
async def auto_approve_join_request(client: Client, request: ChatJoinRequest):
    """Automatically approve channel and group join requests in under 1 second with Link-Share gatekeeper styling."""
    if not Config.AUTO_APPROVE:
        return

    chat = request.chat
    user = request.from_user

    # Verify if chat is in the allowed Auto-Approve Channels list
    allowed_channels = await get_auto_approve_channels()
    if allowed_channels and chat.id not in allowed_channels:
        logger.info(f"Join request for chat {chat.id} skipped (not in auto-approve channels list).")
        return

    try:
        # 1. Approve join request (handles FloodWait safely)
        try:
            await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
            await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)

        logger.info(f"Approved join request from {user.id} ({user.first_name}) for {chat.title} ({chat.id})")

        # 2. Register user in database if new (Enables them for /broadcast)
        try:
            await add_user(user.id, user.first_name, user.username or "")
        except Exception as e:
            logger.debug(f"DB registration note: {e}")

        # 3. Log to Log Channel
        if Config.LOG_CHANNEL:
            try:
                user_mention = f"[{user.first_name}](tg://user?id={user.id})"
                uname_str = f"@{user.username}" if user.username else "No username"
                await client.send_message(
                    chat_id=Config.LOG_CHANNEL,
                    text=(
                        "👥 **#JoinRequestApproved (1s Auto-Accept)**\n\n"
                        f"• **User:** {user_mention} ({uname_str})\n"
                        f"• **User ID:** `{user.id}`\n"
                        f"• **Channel / Group:** `{chat.title}`\n"
                        f"• **Status:** Approved instantly"
                    )
                )
            except Exception:
                pass

        # 4. Build Link-Share styled interactive buttons
        channel_link = None
        if getattr(request, "invite_link", None) and request.invite_link.invite_link:
            channel_link = request.invite_link.invite_link
        elif chat.username:
            channel_link = f"https://t.me/{chat.username}"

        buttons = []
        bot_uname = client.me.username if client.me else Config.BOT_USERNAME
        if bot_uname:
            buttons.append([InlineKeyboardButton("• 🍿 SEARCH MOVIES IN BOT •", url=f"https://t.me/{bot_uname}?start=help")])
        if channel_link:
            c_label = chat.title[:20] if chat.title else "CHANNEL"
            buttons.append([InlineKeyboardButton(f"• 📢 OPEN {c_label} • ↗️", url=channel_link)])

        markup = InlineKeyboardMarkup(buttons) if buttons else None

        # 5. Format caption
        template = await get_welcome_text()
        uname_val = f"@{user.username}" if user.username else user.first_name
        user_mention = f"[{user.first_name}](tg://user?id={user.id})"
        welcome_text = safe_format_welcome(
            template,
            mention=user_mention,
            name=user.first_name or "User",
            first_name=user.first_name or "User",
            title=chat.title or "Channel",
            id=user.id,
            username=uname_val,
            bot=f"@{bot_uname}" if bot_uname else "Bot"
        )

        pic_url = await get_welcome_pic()

        # 6. Deliver Photo DM (falls back gracefully to text message if photo fails)
        try:
            await client.send_photo(
                chat_id=user.id,
                photo=pic_url,
                caption=welcome_text,
                reply_markup=markup
            )
        except Exception:
            try:
                await client.send_message(
                    chat_id=user.id,
                    text=welcome_text,
                    reply_markup=markup
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Failed to auto-approve join request for {user.id} in {chat.id}: {e}")


# --- Admin Commands for Auto-Approve & Link-Share Management ---

# 1. /sharelink [chat_id] [duration] [limit]
@Client.on_message(filters.command(["sharelink", "createlink"]))
async def create_share_link_command(client: Client, message: Message):
    """Generate copyright-protected, time-based, or single-use invite links for any channel."""
    if not Config.is_admin(message.from_user.id):
        return

    import datetime
    from database.share_links import parse_duration

    args = message.text.split()
    target_chat = None
    duration_str = None
    limit_val = None

    idx = 1
    # Check if first arg is chat_id
    if len(args) > idx and (args[idx].startswith("-") or args[idx].startswith("@") or (args[idx].isdigit() and len(args[idx]) > 8)):
        target_str = args[idx].strip()
        try:
            target_chat = int(target_str) if (target_str.startswith("-") and target_str[1:].isdigit()) or target_str.isdigit() else target_str
        except Exception:
            target_chat = target_str
        idx += 1
    elif get_chat_type_str(message.chat.type) in ["group", "supergroup", "channel"]:
        target_chat = message.chat.id
    elif Config.CHANNELS:
        target_chat = Config.CHANNELS[0]

    # Parse remaining arguments (time and/or limit)
    while idx < len(args):
        val = args[idx].lower().strip()
        parsed_sec = parse_duration(val)
        if parsed_sec is not None:
            duration_str = val
        elif val in ["onetime", "single", "once"]:
            limit_val = 1
        elif val.isdigit():
            limit_val = int(val)
        idx += 1

    if not target_chat:
        await message.reply_text(
            "🛡️ **Time-Based & Single-Use Channel Link Generator:**\n\n"
            "**Usage:**\n"
            "• `/sharelink [chat_id]` — Unlimited Join-Request link\n"
            "• `/sharelink [chat_id] [time]` — Time-limited (e.g. `1h`, `24h`, `3d`)\n"
            "• `/sharelink [chat_id] onetime` — 1-Person Single-Use link\n"
            "• `/sharelink [chat_id] 1h 1` — 1 Hour + 1 Person limit\n\n"
            "**Examples:**\n"
            "`/sharelink -1002001671856 1h 1`\n"
            "`/sharelink -1002001671856 24h`\n"
            "`/sharelink -1002001671856 onetime`"
        )
        return

    expire_dt = None
    duration_label = "Permanent (No Expiry)"
    if duration_str:
        sec = parse_duration(duration_str)
        if sec:
            expire_dt = datetime.datetime.utcnow() + datetime.timedelta(seconds=sec)
            duration_label = f"Expires in {duration_str} ({expire_dt.strftime('%d %b, %H:%M UTC')})"

    creates_req = True
    limit_label = "Unlimited Users (Auto-Approved in <1s)"
    if limit_val is not None:
        creates_req = False
        limit_label = "Single-Use (1 Person Only 🔥)" if limit_val == 1 else f"Max {limit_val} Users"

    try:
        kwargs = {"chat_id": target_chat, "name": f"LinkShare ({duration_str or 'perm'})"}
        if expire_dt:
            kwargs["expire_date"] = expire_dt
        if limit_val:
            kwargs["member_limit"] = limit_val
        else:
            kwargs["creates_join_request"] = True

        invite_link = await client.create_chat_invite_link(**kwargs)

        await message.reply_text(
            "🛡️ **Protected Channel Link Generated!**\n\n"
            f"🔗 **Link:** `{invite_link.invite_link}`\n\n"
            f"⏱️ **Validity:** `{duration_label}`\n"
            f"👤 **Usage Limit:** `{limit_label}`\n"
            f"🔒 **Mode:** `{'One-Time / Member-Limited' if limit_val else 'Auto-Approve Gatekeeper'}`\n\n"
            "💡 **Why this is powerful:**\n"
            "• Protects main channel from copyright strikes.\n"
            "• Automatically expires or self-destructs after set time/usage.\n"
            "• Auto-registers users into database for broadcast!"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Failed to generate link:** `{e}`\n\n💡 Ensure the bot is Administrator in the channel with 'Invite Users via Links' permission.")


# 2. /test_welcome (Preview what users see when accepted)
@Client.on_message(filters.command(["test_welcome", "testwelcome"]))
async def test_welcome_command(client: Client, message: Message):
    """Preview the exact auto-accept card in Admin PM."""
    if not Config.is_admin(message.from_user.id):
        return

    bot_uname = client.me.username if client.me else ""
    user = message.from_user
    user_mention = f"[{user.first_name}](tg://user?id={user.id})"
    uname_val = f"@{user.username}" if user.username else user.first_name

    template = await get_welcome_text()
    welcome_text = safe_format_welcome(
        template,
        mention=user_mention,
        name=user.first_name or "User",
        first_name=user.first_name or "User",
        title="Sample VIP Channel",
        id=user.id,
        username=uname_val,
        bot=f"@{bot_uname}" if bot_uname else "Bot"
    )

    buttons = [
        [InlineKeyboardButton("• 🍿 SEARCH MOVIES IN BOT •", url=f"https://t.me/{bot_uname}?start=help")],
        [InlineKeyboardButton("• 📢 OPEN CHANNEL • ↗️", url=f"https://t.me/{bot_uname}")]
    ]
    markup = InlineKeyboardMarkup(buttons)
    pic_url = await get_welcome_pic()

    try:
        await client.send_photo(
            chat_id=user.id,
            photo=pic_url,
            caption=welcome_text,
            reply_markup=markup
        )
    except Exception as e:
        await message.reply_text(f"❌ Preview Error: `{e}`")


# 3. /set_welcome_pic [photo_url] or reply to photo
@Client.on_message(filters.command(["set_welcome_pic", "setwelcomepic"]))
async def set_welcome_pic_command(client: Client, message: Message):
    """Set custom photo for auto-approve welcome message."""
    if not Config.is_admin(message.from_user.id):
        return

    pic_url = None
    reply = message.reply_to_message
    if reply and reply.photo:
        pic_url = reply.photo.file_id
    elif len(message.text.split()) > 1:
        pic_url = message.text.split(maxsplit=1)[1].strip()

    if not pic_url:
        await message.reply_text(
            "⚠️ **Usage:**\n"
            "• Reply to any photo with `/set_welcome_pic`\n"
            "• Or send `/set_welcome_pic [image_direct_url]`"
        )
        return

    try:
        from database.mongo import mongo
        await mongo.db["bot_settings"].update_one(
            {"setting": "auto_approve_pic"},
            {"$set": {"pic": pic_url}},
            upsert=True
        )
        global CUSTOM_WELCOME_PIC
        CUSTOM_WELCOME_PIC = pic_url
        await message.reply_text("✅ **Custom Auto-Approve Welcome Photo Saved!**\nUse `/test_welcome` to preview it.")
    except Exception as e:
        await message.reply_text(f"❌ Failed to save photo: `{e}`")


@Client.on_message(filters.command(["del_welcome_pic", "delwelcomepic", "reset_welcome_pic"]))
async def del_welcome_pic_command(client: Client, message: Message):
    """Reset welcome photo back to dynamic anime artwork."""
    if not Config.is_admin(message.from_user.id):
        return

    from database.mongo import mongo
    await mongo.db["bot_settings"].delete_one({"setting": "auto_approve_pic"})
    global CUSTOM_WELCOME_PIC
    CUSTOM_WELCOME_PIC = None
    await message.reply_text("🔄 **Auto-Approve photo reset to dynamic anime art!**\nEach approved user will receive a fresh poster.")


# 4. /acceptall (Bulk Accept)
@Client.on_message(filters.command(["acceptall", "approveall", "accept", "approve"]))
async def approve_all_pending_command(client: Client, message: Message):
    """Approve all pending join requests in a channel or group in bulk."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    target_chat = None
    if len(args) > 1:
        target_str = args[1].strip()
        try:
            target_chat = int(target_str) if (target_str.startswith("-") and target_str[1:].isdigit()) or target_str.isdigit() else target_str
        except Exception:
            target_chat = target_str
    elif get_chat_type_str(message.chat.type) in ["group", "supergroup", "channel"]:
        target_chat = message.chat.id
    else:
        await message.reply_text(
            "⚠️ **Usage:**\n"
            "• Send `/acceptall` inside your group/channel\n"
            "• Or send `/acceptall [chat_id_or_username]` in PM\n\n"
            "Example: `/acceptall -1002247400551`"
        )
        return

    wait_msg = await message.reply_text(f"⏳ **Approving all pending requests for** `{target_chat}`...")
    try:
        success = await client.approve_all_chat_join_requests(chat_id=target_chat)
        if success:
            await wait_msg.edit_text(f"✅ **All pending join requests for `{target_chat}` have been APPROVED!**")
        else:
            await wait_msg.edit_text("ℹ️ No pending join requests found or already approved.")
    except Exception as e:
        await wait_msg.edit_text(f"❌ **Error:** `{e}`\n\n💡 Ensure the bot is added as **Administrator** in that channel with 'Add Users' / 'Invite via Link' permission.")


# 5. /declineall (Bulk Decline)
@Client.on_message(filters.command(["declineall", "rejectall", "decline", "reject"]))
async def decline_all_pending_command(client: Client, message: Message):
    """Decline/reject all pending join requests in a channel or group."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    target_chat = None
    if len(args) > 1:
        target_str = args[1].strip()
        try:
            target_chat = int(target_str) if (target_str.startswith("-") and target_str[1:].isdigit()) or target_str.isdigit() else target_str
        except Exception:
            target_chat = target_str
    elif get_chat_type_str(message.chat.type) in ["group", "supergroup", "channel"]:
        target_chat = message.chat.id
    else:
        await message.reply_text(
            "⚠️ **Usage:**\n"
            "• Send `/declineall` inside your group/channel\n"
            "• Or send `/declineall [chat_id]` in PM"
        )
        return

    wait_msg = await message.reply_text(f"⏳ **Declining pending requests for** `{target_chat}`...")
    try:
        success = await client.decline_all_chat_join_requests(chat_id=target_chat)
        if success:
            await wait_msg.edit_text(f"🚫 **All pending join requests for `{target_chat}` have been DECLINED.**")
        else:
            await wait_msg.edit_text("ℹ️ No pending join requests found or already processed.")
    except Exception as e:
        await wait_msg.edit_text(f"❌ **Error:** `{e}`")


# 6. /autoapprove [on|off]
@Client.on_message(filters.command("autoapprove"))
async def toggle_auto_approve_command(client: Client, message: Message):
    """Toggle Auto-Approve system on or off."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2 or args[1].lower() not in ["on", "off", "status"]:
        status_str = "ENABLED ✅" if Config.AUTO_APPROVE else "DISABLED ❌"
        await message.reply_text(
            f"🤖 **Auto Join Request Approver:** `{status_str}`\n\n"
            "**Commands:**\n"
            "• `/autoapprove on|off` — Toggle 1-sec auto-approval\n"
            "• `/sharelink [chat_id]` — Create protected invite link\n"
            "• `/acceptall [chat_id]` — Approve all pending requests\n"
            "• `/declineall [chat_id]` — Decline all pending requests\n"
            "• `/set_welcome_pic` — Set custom welcome photo\n"
            "• `/set_welcome [text]` — Set custom welcome text\n"
            "• `/test_welcome` — Preview welcome message card"
        )
        return

    sub = args[1].lower()
    if sub == "on":
        Config.AUTO_APPROVE = True
        await message.reply_text("✅ **Auto-Approve Enabled!** Join requests in all admin channels will be accepted in <1s.")
    elif sub == "off":
        Config.AUTO_APPROVE = False
        await message.reply_text("⛔ **Auto-Approve Disabled.** Join requests will not be accepted automatically.")


# 7. /set_welcome [message]
@Client.on_message(filters.command(["set_welcome", "setwelcome"]))
async def set_welcome_command(client: Client, message: Message):
    """Set custom welcome message sent to auto-approved users."""
    if not Config.is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text(
            "⚠️ **Usage:** `/set_welcome [your message]`\n\n"
            "**Supported Placeholders:**\n"
            "• `{mention}` — Clickable user mention\n"
            "• `{name}` — User First Name\n"
            "• `{title}` — Channel Title\n"
            "• `{id}` — User ID\n"
            "• `{username}` — @Username\n"
            "• `<blockquote>...</blockquote>` — Blockquote styling\n\n"
            "**Example:**\n"
            "`/set_welcome ⁉️ **Hey {name},**\\n\\n<blockquote>**YOUR REQUEST TO JOIN {title} IS APPROVED!**</blockquote>`"
        )
        return

    new_text = args[1].strip()
    try:
        from database.mongo import mongo
        await mongo.db["bot_settings"].update_one(
            {"setting": "auto_approve_welcome"},
            {"$set": {"text": new_text}},
            upsert=True
        )
        global CUSTOM_WELCOME_TEXT
        CUSTOM_WELCOME_TEXT = new_text
        await message.reply_text("✅ **Custom Welcome Caption Saved!**\nUse `/test_welcome` to preview it.")
    except Exception as e:
        await message.reply_text(f"❌ Failed to save custom welcome message: `{e}`")


# 8. /get_welcome & /reset_welcome
@Client.on_message(filters.command(["get_welcome", "getwelcome", "reset_welcome", "resetwelcome"]))
async def get_welcome_command(client: Client, message: Message):
    """View or reset the auto-approve welcome message."""
    if not Config.is_admin(message.from_user.id):
        return

    cmd = message.command[0].lower()
    from database.mongo import mongo
    if "reset" in cmd:
        await mongo.db["bot_settings"].delete_one({"setting": "auto_approve_welcome"})
        global CUSTOM_WELCOME_TEXT
        CUSTOM_WELCOME_TEXT = None
        await message.reply_text("🔄 **Auto-Approve Welcome Message reset to SinGate default!**")
        return

    current = await get_welcome_text()
    await message.reply_text(
        f"📝 **Current Auto-Approve Welcome Message:**\n\n{current}\n\n"
        "💡 To change: `/set_welcome [text]`\n"
        "💡 To reset: `/reset_welcome`"
    )


# 9. Channel List Management: /add_autoapprove, /del_autoapprove, /autoapprove_channels
@Client.on_message(filters.command(["add_autoapprove", "addautoapprove"]))
async def add_auto_approve_command(client: Client, message: Message):
    """Add a channel to the Auto-Approve whitelist."""
    if not Config.is_admin(message.from_user.id):
        return

    target_chat = None
    args = message.text.split()
    if len(args) > 1:
        target_str = args[1].strip()
        if (target_str.startswith("-") and target_str[1:].isdigit()) or target_str.isdigit():
            target_chat = int(target_str)
    elif get_chat_type_str(message.chat.type) in ["group", "supergroup", "channel"]:
        target_chat = message.chat.id

    if not target_chat:
        await message.reply_text("⚠️ **Usage:** `/add_autoapprove <chat_id>`\nExample: `/add_autoapprove -1003537939374`")
        return

    await add_auto_approve_channel(target_chat)
    chat_title = ""
    try:
        c_info = await client.get_chat(target_chat)
        chat_title = f" ({c_info.title})"
    except Exception:
        pass

    await message.reply_text(f"✅ **Channel Added to Auto-Approve List!**\n• Chat ID: `{target_chat}`{chat_title}")


@Client.on_message(filters.command(["del_autoapprove", "delautoapprove", "remove_autoapprove"]))
async def del_auto_approve_command(client: Client, message: Message):
    """Remove a channel from the Auto-Approve whitelist."""
    if not Config.is_admin(message.from_user.id):
        return

    target_chat = None
    args = message.text.split()
    if len(args) > 1:
        target_str = args[1].strip()
        if (target_str.startswith("-") and target_str[1:].isdigit()) or target_str.isdigit():
            target_chat = int(target_str)
    elif get_chat_type_str(message.chat.type) in ["group", "supergroup", "channel"]:
        target_chat = message.chat.id

    if not target_chat:
        await message.reply_text("⚠️ **Usage:** `/del_autoapprove <chat_id>`\nExample: `/del_autoapprove -1003537939374`")
        return

    await del_auto_approve_channel(target_chat)
    await message.reply_text(f"🗑️ **Channel Removed from Auto-Approve List!**\n• Chat ID: `{target_chat}`")


@Client.on_message(filters.command(["autoapprove_channels", "autoapprovechannels"]))
async def list_auto_approve_channels_command(client: Client, message: Message):
    """List all channels currently enabled for Auto-Approve."""
    if not Config.is_admin(message.from_user.id):
        return

    channels = await get_auto_approve_channels()
    if not channels:
        await message.reply_text("ℹ️ **No channels configured for Auto-Approve.**\nAdd one using `/add_autoapprove <chat_id>`.")
        return

    lines = []
    for idx, ch_id in enumerate(channels, 1):
        title = ""
        try:
            c_info = await client.get_chat(ch_id)
            title = f" — **{c_info.title}**"
        except Exception:
            pass
        lines.append(f"{idx}. `{ch_id}`{title}")

    channels_txt = "\n".join(lines)
    await message.reply_text(
        f"📋 **Auto-Approve Enabled Channels ({len(channels)}):**\n\n"
        f"{channels_txt}\n\n"
        "💡 **Commands:**\n"
        "• `/add_autoapprove <chat_id>` — Add channel\n"
        "• `/del_autoapprove <chat_id>` — Remove channel"
    )



