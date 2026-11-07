import re
import html
import logging
import datetime
from typing import Optional

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from utils.helpers import get_readable_size, format_clean_title
from database.ads import parse_duration_string
from database.gifts import (
    create_gift,
    get_gift,
    delete_gift,
    get_all_gifts,
    gift_ban_user,
    gift_unban_user,
    is_gift_banned
)
from database.batches import get_batch
from database.mongo import mongo

logger = logging.getLogger(__name__)

_GIFT_CHANNEL_CACHE = {"channel": None, "loaded": False}


async def get_gift_channel():
    """Retrieve target channel for auto-publishing gift drops."""
    if _GIFT_CHANNEL_CACHE["loaded"]:
        return _GIFT_CHANNEL_CACHE["channel"]
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "gift_channel"})
        if doc and "channel" in doc:
            val = doc["channel"]
            _GIFT_CHANNEL_CACHE["channel"] = val
            _GIFT_CHANNEL_CACHE["loaded"] = True
            return val
    except Exception:
        pass
    default_ch = getattr(Config, "GIFT_CHANNEL", None)
    _GIFT_CHANNEL_CACHE["channel"] = default_ch if default_ch and default_ch != 0 else None
    _GIFT_CHANNEL_CACHE["loaded"] = True
    return _GIFT_CHANNEL_CACHE["channel"]


async def set_gift_channel(channel):
    """Set target channel for auto-publishing gift drops."""
    _GIFT_CHANNEL_CACHE["channel"] = channel
    _GIFT_CHANNEL_CACHE["loaded"] = True
    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "gift_channel"},
            {"$set": {"channel": channel, "updated_at": datetime.datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error persisting gift channel setting: {e}")



def parse_short_duration(dur_str: str) -> Optional[int]:
    """Parse time string supporting seconds (s), minutes (m), hours (h), days (d), weeks (w)."""
    m = re.match(r"^(\d+)\s*(s|sec|m|min|h|hr|d|day|w|week)?$", dur_str.strip().lower())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2) or "m"
    if unit in ("s", "sec"):
        return val
    elif unit in ("m", "min"):
        return val * 60
    elif unit in ("h", "hr"):
        return val * 3600
    elif unit in ("d", "day"):
        return val * 86400
    elif unit in ("w", "week"):
        return val * 7 * 86400
    return None


def parse_gift_flags(arg_list: list[str]) -> dict:
    """Parse command line flags like -viponly, -shortener, -protect, -del 3m, -img <url>, -unlimited."""
    flags = {
        "is_vip_only": False,
        "require_shortener": False,
        "protect_content": True,
        "auto_delete_seconds": 300,  # 5 minutes default
        "poster_url": None,
        "channels": [],
        "external_links": [],
        "required_invites": 0,
        "claims": 50,
        "duration_seconds": 172800,  # 48 hours default
        "draft": False,
        "allow_reclaim": True
    }

    seen_numbers = 0
    skip_next = False
    for i, token in enumerate(arg_list):
        if skip_next:
            skip_next = False
            continue

        tok_low = token.lower()
        if tok_low in ("-draft", "draft", "-nopost", "nopost"):
            flags["draft"] = True
        elif tok_low in ("-strict", "strict", "-nostore", "nostore"):
            flags["allow_reclaim"] = False
        elif tok_low in ("-reclaim", "reclaim", "-hybrid", "hybrid"):
            flags["allow_reclaim"] = True
        elif tok_low in ("-unlimited", "unlimited", "-nolimit", "nolimit", "-forever", "forever", "-inf", "inf"):
            flags["claims"] = 0
            flags["duration_seconds"] = 0
        elif tok_low in ("forever", "lifetime", "never", "0h", "0d", "0s"):
            flags["duration_seconds"] = 0
        elif tok_low in ("-viponly", "viponly", "-vip", "vip"):
            flags["is_vip_only"] = True
        elif tok_low in ("-shortener", "shortener", "-short", "short", "-ad", "ad"):
            flags["require_shortener"] = True
        elif tok_low in ("-noprotect", "noprotect", "unlock"):
            flags["protect_content"] = False
        elif tok_low in ("-protect", "protect", "lock"):
            flags["protect_content"] = True
        elif tok_low in ("-del", "del", "autodel"):
            if i + 1 < len(arg_list):
                dur = parse_short_duration(arg_list[i + 1])
                if dur is not None:
                    flags["auto_delete_seconds"] = dur
                skip_next = True
        elif tok_low in ("-img", "img", "-poster", "poster"):
            if i + 1 < len(arg_list):
                flags["poster_url"] = arg_list[i + 1]
                skip_next = True
        elif tok_low in ("yt", "youtube", "-yt", "-youtube"):
            if i + 1 < len(arg_list):
                flags["external_links"].append({
                    "title": "Subscribe on YouTube",
                    "url": arg_list[i + 1].strip(),
                    "type": "youtube"
                })
                skip_next = True
        elif tok_low in ("insta", "instagram", "-insta", "-instagram"):
            if i + 1 < len(arg_list):
                flags["external_links"].append({
                    "title": "Follow on Instagram",
                    "url": arg_list[i + 1].strip(),
                    "type": "instagram"
                })
                skip_next = True
        elif tok_low in ("link", "web", "site", "sponsor", "-link", "-web"):
            if i + 1 < len(arg_list):
                flags["external_links"].append({
                    "title": "Visit Partner Website",
                    "url": arg_list[i + 1].strip(),
                    "type": "web"
                })
                skip_next = True
        elif tok_low in ("invite", "refer", "-invite", "-refer"):
            if i + 1 < len(arg_list) and arg_list[i + 1].isdigit():
                flags["required_invites"] = int(arg_list[i + 1])
                skip_next = True
        elif token.startswith("@") or token.startswith("-100") or (token.lstrip("-").isdigit() and len(token) > 8) or token.startswith("https://t.me/+") or token.startswith("t.me/+"):
            flags["channels"].append(token)
        elif token.isdigit():
            val = int(token)
            if seen_numbers == 0:
                flags["claims"] = val
            elif seen_numbers == 1:
                # 2nd numeric token without unit: 0 means no time limit, else hours
                flags["duration_seconds"] = 0 if val == 0 else (val * 3600)
            seen_numbers += 1
        elif re.match(r"^\d+\s*([hdwHDW]|days?|hours?|weeks?)$", token):
            dur = parse_short_duration(token)
            if dur is not None:
                flags["duration_seconds"] = dur

    # Default channels fallback if none specified in command
    if not flags["channels"]:
        if Config.FORCE_SUB_CHANNELS:
            flags["channels"] = list(Config.FORCE_SUB_CHANNELS)
        elif Config.CHANNEL_URL and not Config.CHANNEL_URL.startswith("http"):
            flags["channels"] = [Config.CHANNEL_URL]
        elif Config.UPDATES_CHANNEL:
            flags["channels"] = [str(Config.UPDATES_CHANNEL)]

    return flags


# ==============================================================================
# Admin Command: /gift (Reply to any File / Media Message)
# ==============================================================================

@Client.on_message(filters.command(["gift", "creategift", "reward"]) & filters.private)
async def create_single_gift_handler(client: Client, message: Message):
    """Admin tool to create a task-locked gift reward link for any file."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    reply = message.reply_to_message
    if not reply:
        return await message.reply_text(
            "🎁 <b>CREATE TASK-LOCKED REWARD / GIFT LINK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Super Simple Usage:</b> Reply to any file, video, or APK with:\n"
            "• <code>/gift</code> : Instant 50 claims, 48h validity (Fastest 1-word!)\n"
            "• <code>/gift 100 7d</code> : 100 claims, 7 days\n"
            "• <code>/gift 50 24h @MyChannel</code> : Custom channel task\n"
            "• <code>/gift 50 24h -1002247400551</code> : Private channel support\n"
            "• <code>/gift 50 24h yt https://youtube.com/@channel</code> : YouTube Subscribe task\n"
            "• <code>/gift 50 24h insta https://instagram.com/myacc</code> : Instagram Follow task\n"
            "• <code>/gift 50 24h invite 2</code> : Invite 2 friends task\n"
            "• <code>/gift 100 3d shortener protect</code> : Shortener + Protected\n\n"
            "<b>Optional Modifiers (No hyphens needed):</b>\n"
            "• <code>yt &lt;url&gt;</code> : YouTube subscribe task\n"
            "• <code>insta &lt;url&gt;</code> : Instagram follow task\n"
            "• <code>link &lt;url&gt;</code> : Sponsor / website visit task\n"
            "• <code>invite &lt;n&gt;</code> : Require inviting N friends\n"
            "• <code>shortener</code> : Require 1-time shortener task\n"
            "• <code>vip</code> : VIP members only\n"
            "• <code>protect</code> : Content protected (No forward/save)\n"
            "• <code>del 5m</code> : Auto-delete file in 5 minutes\n\n"
            "💡 <i>Works with public, private channels, links, and referral tasks!</i>"
        )

    # Extract media from reply
    media = (
        reply.document or reply.video or reply.audio or
        reply.photo or reply.animation or reply.voice
    )
    if not media:
        return await message.reply_text("❌ <b>No supported file or media found in replied message.</b>")

    raw_name = getattr(media, "file_name", None) or "Exclusive Reward File"
    file_id = media.file_id
    file_unique_id = getattr(media, "file_unique_id", "")
    file_size = getattr(media, "file_size", 0)

    file_doc = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_name": raw_name,
        "file_size": file_size
    }

    # Parse command arguments & flags
    cmd_args = message.text.split()[1:]
    flags = parse_gift_flags(cmd_args)

    clean_title = format_clean_title(raw_name)
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    # Create gift record in database
    doc = await create_gift(
        title=clean_title,
        file_type="single",
        file_doc=file_doc,
        total_files=1,
        total_size=file_size,
        poster_url=flags["poster_url"],
        channels=flags["channels"],
        require_shortener=flags["require_shortener"],
        is_vip_only=flags["is_vip_only"],
        protect_content=flags["protect_content"],
        auto_delete_seconds=flags["auto_delete_seconds"],
        max_claims=flags["claims"],
        duration_seconds=flags["duration_seconds"],
        created_by=message.from_user.id,
        external_links=flags["external_links"],
        required_invites=flags["required_invites"],
        allow_reclaim=flags["allow_reclaim"]
    )

    if not doc:
        return await message.reply_text("❌ <b>Database error:</b> Failed to create gift reward.")

    gift_id = doc["gift_id"]
    gift_link = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

    # Build Ready-to-Forward Channel Post (Ultra-Clean & Compact)
    del_mins = flags["auto_delete_seconds"] // 60
    del_str = f"{del_mins} Mins" if del_mins > 0 else f"{flags['auto_delete_seconds']}s"
    stock_str = f"First {flags['claims']} Users" if flags["claims"] > 0 else "Unlimited"
    validity_str = "Lifetime" if flags["duration_seconds"] == 0 else "Limited Time"
    vip_badge = " • 👑 <b>VIP Only</b>" if flags["is_vip_only"] else ""

    card_text = (
        "🎁 <b>EXCLUSIVE REWARD DROP</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Item:</b> <code>{html.escape(clean_title)}</code>\n"
        f"💾 <b>Size:</b> <code>{get_readable_size(file_size)}</code>  •  👥 <b>Stock:</b> <code>{stock_str}</code>\n"
        f"⏳ <b>Validity:</b> <code>{validity_str}</code>  •  ⏱️ <b>Auto-Delete:</b> <code>{del_str}</code>{vip_badge}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Claim Link:</b>\n"
        f"<a href=\"{gift_link}\"><b>{gift_link}</b></a>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 CLAIM EXCLUSIVE REWARD ↗️", url=gift_link)]
    ])

    # Auto-publish to configured gift drops channel
    gift_channel = await get_gift_channel()
    channel_post_url = None

    if gift_channel and not flags.get("draft"):
        try:
            poster = doc.get("poster_url")
            ch_msg = None
            if poster:
                try:
                    ch_msg = await client.send_photo(
                        chat_id=gift_channel,
                        photo=poster,
                        caption=card_text,
                        reply_markup=markup
                    )
                except Exception as p_err:
                    logger.debug(f"Could not send photo to gift channel: {p_err}")

            if not ch_msg:
                ch_msg = await client.send_message(
                    chat_id=gift_channel,
                    text=card_text,
                    reply_markup=markup,
                    disable_web_page_preview=True
                )

            if ch_msg:
                if str(gift_channel).startswith("-100"):
                    clean_cid = str(gift_channel)[4:]
                    channel_post_url = f"https://t.me/c/{clean_cid}/{ch_msg.id}"
                elif str(gift_channel).startswith("@"):
                    channel_post_url = f"https://t.me/{str(gift_channel).lstrip('@')}/{ch_msg.id}"
        except Exception as pub_err:
            logger.warning(f"Failed to auto-post gift to channel {gift_channel}: {pub_err}")

    if channel_post_url:
        admin_summary = (
            f"✅ <b>GIFT REWARD CREATED & PUBLISHED TO CHANNEL!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
            f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n"
            f"📢 <b>Channel Post:</b> <a href=\"{channel_post_url}\"><b>View Live Post ↗️</b></a>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>The card below was automatically published to your gift channel!</i>"
        )
    else:
        admin_summary = (
            f"✅ <b>GIFT REWARD LINK CREATED SUCCESSFULLY!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
            f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n\n"
            f"📢 <i>You can forward the ready-made card below directly to your channel!</i>"
        )

    await message.reply_text(admin_summary, disable_web_page_preview=True)

    poster = doc.get("poster_url")
    if poster:
        try:
            return await message.reply_photo(photo=poster, caption=card_text, reply_markup=markup)
        except Exception:
            pass

    await message.reply_text(card_text, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /giftbatch <batch_id> [claims] [duration] ...
# ==============================================================================

@Client.on_message(filters.command(["giftbatch", "rewardbatch"]) & filters.private)
async def create_batch_gift_handler(client: Client, message: Message):
    """Admin tool to create a gift reward for an entire batch (multi-file pack)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text(
            "🎁 <b>CREATE MULTI-FILE BATCH GIFT LINK</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Usage:</b>\n"
            "<code>/giftbatch &lt;batch_id&gt; [claims] [duration] [@channel...] [flags]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/giftbatch b_abc123 50 48h @AkMoviesOfficial -protect -del 5m</code>"
        )

    batch_id = parts[1].strip()
    batch = await get_batch(batch_id)
    if not batch:
        return await message.reply_text(f"❌ <b>Batch not found:</b> <code>{html.escape(batch_id)}</code>")

    files = batch.get("files", [])
    total_files = len(files)
    total_size = batch.get("total_size", 0)

    cmd_args = parts[2:]
    flags = parse_gift_flags(cmd_args)

    batch_title = f"{files[0].get('file_name', 'Batch Pack')} (+{total_files - 1} Files)" if total_files > 1 else files[0].get("file_name", "Batch File")
    clean_title = format_clean_title(batch_title)
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    doc = await create_gift(
        title=clean_title,
        file_type="batch",
        batch_id=batch_id,
        total_files=total_files,
        total_size=total_size,
        poster_url=flags["poster_url"],
        channels=flags["channels"],
        require_shortener=flags["require_shortener"],
        is_vip_only=flags["is_vip_only"],
        protect_content=flags["protect_content"],
        auto_delete_seconds=flags["auto_delete_seconds"],
        max_claims=flags["claims"],
        duration_seconds=flags["duration_seconds"],
        created_by=message.from_user.id,
        external_links=flags["external_links"],
        required_invites=flags["required_invites"],
        allow_reclaim=flags["allow_reclaim"]
    )

    if not doc:
        return await message.reply_text("❌ <b>Database error:</b> Failed to create batch gift reward.")

    gift_id = doc["gift_id"]
    gift_link = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

    # Build Ready-to-Forward Batch Channel Post (Ultra-Clean & Compact)
    del_mins = flags["auto_delete_seconds"] // 60
    del_str = f"{del_mins} Mins" if del_mins > 0 else f"{flags['auto_delete_seconds']}s"
    stock_str = f"First {flags['claims']} Users" if flags["claims"] > 0 else "Unlimited"
    validity_str = "Lifetime" if flags["duration_seconds"] == 0 else "Limited Time"

    card_text = (
        "🎁 <b>EXCLUSIVE BATCH REWARD PACK</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Package:</b> <code>{html.escape(clean_title)}</code>\n"
        f"📁 <b>Files:</b> <code>{total_files} Files</code>  •  💾 <b>Size:</b> <code>{get_readable_size(total_size)}</code>\n"
        f"👥 <b>Stock:</b> <code>{stock_str}</code>  •  ⏱️ <b>Auto-Delete:</b> <code>{del_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Claim Link:</b>\n"
        f"<a href=\"{gift_link}\"><b>{gift_link}</b></a>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 CLAIM COMPLETE BATCH PACK ↗️", url=gift_link)]
    ])

    # Auto-publish to configured gift drops channel
    gift_channel = await get_gift_channel()
    channel_post_url = None

    if gift_channel and not flags.get("draft"):
        try:
            poster = doc.get("poster_url")
            ch_msg = None
            if poster:
                try:
                    ch_msg = await client.send_photo(
                        chat_id=gift_channel,
                        photo=poster,
                        caption=card_text,
                        reply_markup=markup
                    )
                except Exception as p_err:
                    logger.debug(f"Could not send photo to gift channel: {p_err}")

            if not ch_msg:
                ch_msg = await client.send_message(
                    chat_id=gift_channel,
                    text=card_text,
                    reply_markup=markup,
                    disable_web_page_preview=True
                )

            if ch_msg:
                if str(gift_channel).startswith("-100"):
                    clean_cid = str(gift_channel)[4:]
                    channel_post_url = f"https://t.me/c/{clean_cid}/{ch_msg.id}"
                elif str(gift_channel).startswith("@"):
                    channel_post_url = f"https://t.me/{str(gift_channel).lstrip('@')}/{ch_msg.id}"
        except Exception as pub_err:
            logger.warning(f"Failed to auto-post batch gift to channel {gift_channel}: {pub_err}")

    if channel_post_url:
        admin_summary = (
            f"✅ <b>BATCH GIFT CREATED & PUBLISHED TO CHANNEL!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
            f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n"
            f"📢 <b>Channel Post:</b> <a href=\"{channel_post_url}\"><b>View Live Post ↗️</b></a>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <i>The pack card below was automatically published to your gift channel!</i>"
        )
    else:
        admin_summary = (
            f"✅ <b>BATCH GIFT REWARD CREATED SUCCESSFULLY!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Gift Link:</b> <code>{gift_link}</code>\n"
            f"🆔 <b>Gift ID:</b> <code>{gift_id}</code>\n\n"
            f"📢 <i>You can forward the ready-made card below directly to your channel!</i>"
        )

    await message.reply_text(admin_summary, disable_web_page_preview=True)
    poster = doc.get("poster_url")
    if poster:
        try:
            return await message.reply_photo(photo=poster, caption=card_text, reply_markup=markup)
        except Exception:
            pass

    await message.reply_text(card_text, reply_markup=markup, disable_web_page_preview=True)


# ==============================================================================
# Admin Command: /gifts or /giftstats (Active Gifts Dashboard)
# ==============================================================================

@Client.on_message(filters.command(["gifts", "giftstats"]) & filters.private)
async def list_gifts_dashboard(client: Client, message: Message):
    """Admin dashboard to inspect live gift campaigns, claim progress, and revoke."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) > 1:
        # Specific gift details
        gid = parts[1].strip()
        gift = await get_gift(gid)
        if not gift:
            return await message.reply_text(f"❌ <b>Gift not found:</b> <code>{html.escape(gid)}</code>")

        claimed = gift.get("claimed_count", 0)
        max_c = gift.get("max_claims", 0)
        views = gift.get("views_count", 0)
        active = gift.get("is_active", False)
        status_str = "🟢 Active" if active else "🔴 Inactive / Expired"

        exp = gift.get("expires_at")
        exp_str = exp.strftime("%d %b %Y, %H:%M UTC") if exp else "Never"

        bot_uname = client.me.username if client.me else Config.BOT_USERNAME
        link = f"https://t.me/{bot_uname}?start=gift_{gid}"

        text = (
            f"🎁 <b>GIFT REWARD CAMPAIGN #{gid}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Title:</b> <code>{html.escape(gift.get('title', 'Gift'))}</code>\n"
            f"• <b>Status:</b> {status_str}\n"
            f"• <b>Claimed:</b> <code>{claimed} / {max_c if max_c else '∞'} Users</code>\n"
            f"• <b>Re-Downloads:</b> <code>{gift.get('redownloads_count', 0):,} Times</code>\n"
            f"• <b>Views / Clicks:</b> <code>{views:,} Views</code>\n"
            f"• <b>Mode:</b> <code>{'Hybrid (Re-download Allowed)' if gift.get('allow_reclaim', True) else 'Strict (1-Claim Only)'}</code>\n"
            f"• <b>VIP Only:</b> <code>{'Yes' if gift.get('is_vip_only') else 'No'}</code>\n"
            f"• <b>Shortener Task:</b> <code>{'Yes' if gift.get('require_shortener') else 'No'}</code>\n"
            f"• <b>Required Channels:</b> <code>{', '.join(gift.get('channels', [])) or 'None'}</code>\n"
            f"• <b>Expires At:</b> <code>{exp_str}</code>\n"
            f"• <b>Link:</b> <code>{link}</code>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Revoke / Delete Gift", callback_data=f"delgift_cb_{gid}")]
        ])
        return await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)

    # General list
    gifts = await get_all_gifts(limit=15, only_active=True)
    if not gifts:
        return await message.reply_text(
            "ℹ️ <b>No active gift campaigns found.</b>\n"
            "Use <code>/gift</code> (by replying to any file) or <code>/giftbatch &lt;id&gt;</code> to create one."
        )

    text_lines = [
        "🎁 <b>ACTIVE GIFT CAMPAIGNS DASHBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    buttons = []
    for g in gifts:
        gid = g["gift_id"]
        title = g.get("title", "Gift")[:25]
        claimed = g.get("claimed_count", 0)
        max_c = g.get("max_claims", 0)
        text_lines.append(f"• <code>{gid}</code> : <b>{html.escape(title)}</b> ({claimed}/{max_c})")
        buttons.append([
            InlineKeyboardButton(f"🔍 {title} ({claimed}/{max_c})", callback_data=f"gift_info_{gid}")
        ])

    text_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    text_lines.append("💡 <i>Tap any gift below to inspect or revoke it.</i>")

    await message.reply_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(buttons))


# ==============================================================================
# Admin Command: /delgift <gift_id>
# ==============================================================================

@Client.on_message(filters.command(["delgift", "revokegift"]) & filters.private)
async def delete_gift_handler(client: Client, message: Message):
    """Admin tool to immediately revoke and stop a gift reward link."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("<b>Usage:</b> <code>/delgift &lt;gift_id&gt;</code>")

    gid = parts[1].strip()
    ok = await delete_gift(gid)
    if ok:
        await message.reply_text(f"🗑️ <b>Gift campaign <code>{html.escape(gid)}</code> has been revoked successfully!</b>")
    else:
        await message.reply_text("❌ Gift not found or already inactive.")


# ==============================================================================
# Admin Commands: /giftban & /giftunban
# ==============================================================================

@Client.on_message(filters.command(["giftban"]) & filters.private)
async def gift_ban_handler(client: Client, message: Message):
    """Globally blacklist a user from claiming any gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/giftban &lt;user_id&gt; [reason]</code>")

    target_id = int(parts[1])
    reason = " ".join(parts[2:]) if len(parts) > 2 else "Left sponsor channel / Rule violation"

    ok = await gift_ban_user(user_id=target_id, reason=reason, banned_by=message.from_user.id)
    if ok:
        await message.reply_text(
            f"🚫 <b>User <code>{target_id}</code> has been blacklisted from gifts!</b>\n"
            f"<b>Reason:</b> <code>{html.escape(reason)}</code>"
        )
        try:
            await client.send_message(
                chat_id=target_id,
                text=f"⚠️ <b>Notice:</b> You have been restricted from claiming reward gifts on @{client.me.username}.\n<b>Reason:</b> {html.escape(reason)}"
            )
        except Exception:
            pass
    else:
        await message.reply_text("❌ Error blacklisting user.")


@Client.on_message(filters.command(["giftunban"]) & filters.private)
async def gift_unban_handler(client: Client, message: Message):
    """Unban user from claiming gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.reply_text("<b>Usage:</b> <code>/giftunban &lt;user_id&gt;</code>")

    target_id = int(parts[1])
    ok = await gift_unban_user(target_id)
    if ok:
        await message.reply_text(f"✅ <b>User <code>{target_id}</code> is now unbanned and can claim gifts.</b>")
    else:
        await message.reply_text("ℹ️ User was not in gift blacklist.")


# ==============================================================================
# Admin Command: /setgiftchannel <channel> (Configure Auto-Publishing Gift Channel)
# ==============================================================================

@Client.on_message(filters.command(["setgiftchannel", "giftchannel"]) & filters.private)
async def set_gift_channel_command(client: Client, message: Message):
    """Admin command to configure dedicated channel for auto-posting gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        current = await get_gift_channel()
        status_str = f"<code>{current}</code>" if current else "<i>Disabled (Manual Forward Mode)</i>"
        return await message.reply_text(
            f"🎁 <b>GIFT AUTO-POST CHANNEL SETTINGS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <b>Current Channel:</b> {status_str}\n\n"
            f"<b>Usage:</b>\n"
            f"• <code>/setgiftchannel @MyChannel</code> (Public Channel)\n"
            f"• <code>/setgiftchannel -1001234567890</code> (Private Channel ID)\n"
            f"• <code>/setgiftchannel off</code> (Disable Auto-Post)\n\n"
            f"💡 <i>When enabled, any gift created via /gift or /giftbatch will automatically post directly to this channel!</i>"
        )

    arg = parts[1].strip()
    if arg.lower() in ("off", "clear", "disable", "none", "0"):
        await set_gift_channel(None)
        return await message.reply_text("✅ <b>Gift Auto-Post Channel Disabled!</b>\nGift cards will now only be sent to admin PM for manual forwarding.")

    # Validate channel
    target = None
    if arg.startswith("-100") or (arg.lstrip("-").isdigit() and len(arg) > 8):
        target = int(arg)
    elif arg.startswith("@"):
        target = arg
    else:
        if not arg.startswith("http"):
            target = f"@{arg}"
        else:
            return await message.reply_text("⚠️ <b>Invalid format!</b> Use <code>@channel_username</code> or <code>-100...</code> channel ID.")

    title = str(target)
    try:
        chat = await client.get_chat(target)
        if chat and chat.title:
            title = chat.title
    except Exception as e:
        logger.warning(f"Could not fetch chat info for {target}: {e}")

    await set_gift_channel(target)
    await message.reply_text(
        f"✅ <b>GIFT AUTO-POST CHANNEL CONFIGURED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Target Channel:</b> <code>{title}</code> (<code>{target}</code>)\n\n"
        f"🚀 <i>Every new gift created with /gift or /giftbatch will now be automatically published directly to this channel!</i>"
    )
