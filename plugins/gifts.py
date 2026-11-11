import os
import shutil
import tempfile
import asyncio
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
        allow_reclaim=flags["allow_reclaim"],
        ad_link=cfg.get("ad_link"),
        ad_links=cfg.get("ad_links", []),
        ad_wait_seconds=cfg.get("ad_wait_seconds", 3),
        ad_button_text=cfg.get("ad_button_text", "🌐 View Sponsored Offer ↗️")
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

    cfg = await get_auto_gift_config()
    post_hdr = cfg.get("post_header", "🔥 EXCLUSIVE DROP 🔥")
    post_btn = cfg.get("post_button", "⚡ Get Full Video ➔")

    card_text = (
        f"<b>{post_hdr}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Item:</b> <code>{html.escape(clean_title)}</code>\n"
        f"💾 <b>Size:</b> <code>{get_readable_size(file_size)}</code>  •  👥 <b>Stock:</b> <code>{stock_str}</code>\n"
        f"⏳ <b>Validity:</b> <code>{validity_str}</code>  •  ⏱️ <b>Auto-Delete:</b> <code>{del_str}</code>{vip_badge}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Download / Watch Online:</b>\n"
        f"👉 <a href=\"{gift_link}\"><b>⚡ CLICK HERE TO GET FULL VIDEO ⚡</b></a>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(post_btn, url=gift_link)]
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
                try:
                    await mongo.db["gift_rewards"].update_one(
                        {"gift_id": gift_id},
                        {"$set": {"post_chat_id": gift_channel, "post_msg_id": ch_msg.id}}
                    )
                except Exception:
                    pass
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

    cfg = await get_auto_gift_config()
    post_hdr = cfg.get("post_header", "🔥 EXCLUSIVE DROP 🔥")
    post_btn = cfg.get("post_button", "⚡ Get Full Video ➔")

    card_text = (
        f"<b>{post_hdr}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Package:</b> <code>{html.escape(clean_title)}</code>\n"
        f"📁 <b>Files:</b> <code>{total_files} Files</code>  •  💾 <b>Size:</b> <code>{get_readable_size(total_size)}</code>\n"
        f"👥 <b>Stock:</b> <code>{stock_str}</code>  •  ⏱️ <b>Auto-Delete:</b> <code>{del_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Download / Watch Online:</b>\n"
        f"👉 <a href=\"{gift_link}\"><b>⚡ CLICK HERE TO GET COMPLETE PACK ⚡</b></a>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(post_btn, url=gift_link)]
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
                try:
                    await mongo.db["gift_rewards"].update_one(
                        {"gift_id": gift_id},
                        {"$set": {"post_chat_id": gift_channel, "post_msg_id": ch_msg.id}}
                    )
                except Exception:
                    pass
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
    """Admin tool to immediately revoke and stop a gift reward link, and remove its channel post."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied</b>: Admin privileges required.")

    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("<b>Usage:</b> <code>/delgift &lt;gift_id&gt;</code>")

    gid = parts[1].strip()
    gift_doc = await mongo.db["gift_rewards"].find_one({"gift_id": gid})
    post_deleted = False
    if gift_doc:
        post_cid = gift_doc.get("post_chat_id")
        post_mid = gift_doc.get("post_msg_id")
        if post_cid and post_mid:
            try:
                await client.delete_messages(chat_id=post_cid, message_ids=post_mid)
                post_deleted = True
            except Exception as e_del:
                logger.debug(f"Could not delete gift channel post: {e_del}")

    ok = await delete_gift(gid)
    if ok:
        note = " (and its channel post was removed)" if post_deleted else ""
        await message.reply_text(f"🗑️ <b>Gift campaign <code>{html.escape(gid)}</code> has been revoked successfully!</b>{note}")
    else:
        await message.reply_text("❌ Gift not found or already inactive.")


@Client.on_message(filters.command(["delallgifts", "deleteallgifts", "clearallgifts", "revokeallgifts"]) & filters.private)
async def delete_all_gifts_command(client: Client, message: Message):
    """Admin tool to purge all gifts and delete their channel posts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin privileges required.")

    total_count = await mongo.db["gift_rewards"].count_documents({})
    if total_count == 0:
        return await message.reply_text("ℹ️ <b>No gifts found:</b> Database currently has 0 gifts.")

    confirm_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, Delete All Gifts & Posts", callback_data="confirm_delallgifts"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_delallgifts")
        ]
    ])

    await message.reply_text(
        "⚠️ <b>CONFIRM BULK DELETE ALL GIFTS?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Total Gifts Found: <b>{total_count}</b>\n"
        "• This will <b>delete all gift cards/posts</b> from your gift channel!\n"
        "• All active gift links will immediately be revoked.\n\n"
        "<i>Are you sure you want to proceed?</i>",
        reply_markup=confirm_markup
    )


@Client.on_callback_query(filters.regex(r"^(confirm|cancel)_delallgifts$"))
async def del_all_gifts_callback(client: Client, query: CallbackQuery):
    """Callback query handler for bulk gift deletion."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Admin only.", show_alert=True)

    if query.data == "cancel_delallgifts":
        await query.answer("Bulk deletion cancelled.")
        try:
            await query.message.edit_text("❌ <b>Bulk delete cancelled.</b> All gift campaigns remain active.")
        except Exception:
            pass
        return

    await query.answer("Starting bulk deletion...", show_alert=False)
    try:
        await query.message.edit_text("⏳ <b>Deleting channel posts and clearing gift database...</b>")
    except Exception:
        pass

    cursor = mongo.db["gift_rewards"].find({})
    posts_by_channel = {}
    total_gifts = 0

    async for g in cursor:
        total_gifts += 1
        cid = g.get("post_chat_id")
        mid = g.get("post_msg_id")
        if cid and mid:
            posts_by_channel.setdefault(cid, []).append(mid)

    posts_deleted = 0
    for cid, msg_ids in posts_by_channel.items():
        for i in range(0, len(msg_ids), 100):
            batch = msg_ids[i:i+100]
            try:
                await client.delete_messages(chat_id=cid, message_ids=batch)
                posts_deleted += len(batch)
            except Exception as e_del:
                logger.warning(f"Error deleting post batch in {cid}: {e_del}")

    # Wipe gift records and tokens from database
    await mongo.db["gift_rewards"].delete_many({})
    try:
        await mongo.db["gift_task_tokens"].delete_many({})
    except Exception:
        pass

    try:
        await query.message.edit_text(
            "✅ <b>ALL GIFTS SUCCESSFULLY DELETED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗑️ <b>Total Gifts Purged:</b> <code>{total_gifts}</code>\n"
            f"📢 <b>Channel Posts Removed:</b> <code>{posts_deleted}</code>\n\n"
            "🚀 <i>Your drops channel and database are clean!</i>"
        )
    except Exception:
        pass


@Client.on_message(filters.command(["cleargiftchannel", "cleargiftposts"]) & filters.private)
async def clear_gift_channel_posts_command(client: Client, message: Message):
    """Admin tool to delete recent posts directly from the gift drops channel."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    cfg = await get_auto_gift_config()
    post_ch = cfg.get("post_channel") or await get_gift_channel()
    if not post_ch:
        return await message.reply_text("❌ No gift post channel configured yet. Use /setgiftpost first.")

    parts = message.text.split()
    count = 30
    if len(parts) > 1 and parts[1].isdigit():
        count = max(1, min(100, int(parts[1])))

    status = await message.reply_text(f"⏳ <b>Scanning last {count} messages in {post_ch}...</b>")
    msg_ids = []
    try:
        async for m in client.get_chat_history(post_ch, limit=count):
            msg_ids.append(m.id)

        if msg_ids:
            await client.delete_messages(chat_id=post_ch, message_ids=msg_ids)
            await status.edit_text(f"✅ <b>Successfully deleted {len(msg_ids)} recent posts from {post_ch}!</b>")
        else:
            await status.edit_text("ℹ️ No messages found to delete.")
    except Exception as e:
        await status.edit_text(f"❌ <b>Error deleting messages:</b> <code>{html.escape(str(e))}</code>\n<i>Ensure bot is Admin with 'Delete Messages' permission!</i>")


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

# ==============================================================================
# 🎁 Automated Gift Drops Engine & Interactive Settings Dashboard
# ==============================================================================

_AUTO_GIFT_CONFIG_CACHE = {
    "loaded": False,
    "enabled": False,
    "db_channel": None,
    "post_channel": None,
    "claims": 0,
    "duration_seconds": 0,
    "channels": [],
    "require_shortener": False,
    "allow_reclaim": True,
    "auto_delete_seconds": 300,
    "protect_content": True,
    "photo_wait_seconds": 60,
    "poster_mode": "ss",
    "post_header": "🔥 EXCLUSIVE DROP 🔥",
    "post_button": "⚡ Get Full Video ➔",
    "ad_link": None,
    "ad_links": [],
    "ad_wait_seconds": 3,
    "ad_button_text": "🌐 View Sponsored Offer ↗️"
}

# Pending queue of videos waiting for custom poster in GIFT_DB_CHANNEL
# key: message_id -> dict: {"event": asyncio.Event, "photo_id": Optional[str], "chat_id": int, "file_name": str, "status_msg": Optional[Message]}
_PENDING_GIFT_VIDEOS: dict[int, dict] = {}


async def get_auto_gift_config() -> dict:
    """Retrieve auto-gift publisher configuration from MongoDB with in-memory caching."""
    global _AUTO_GIFT_CONFIG_CACHE
    if _AUTO_GIFT_CONFIG_CACHE["loaded"]:
        return _AUTO_GIFT_CONFIG_CACHE
    try:
        doc = await mongo.db["bot_settings"].find_one({"key": "auto_gift_config"})
        if doc and "config" in doc:
            _AUTO_GIFT_CONFIG_CACHE.update(doc["config"])
    except Exception as e:
        logger.debug(f"Error loading auto gift config: {e}")
    _AUTO_GIFT_CONFIG_CACHE["loaded"] = True
    return _AUTO_GIFT_CONFIG_CACHE


async def save_auto_gift_config(updates: dict):
    """Persist updated auto-gift publisher configuration to MongoDB."""
    global _AUTO_GIFT_CONFIG_CACHE
    cfg = await get_auto_gift_config()
    cfg.update(updates)
    _AUTO_GIFT_CONFIG_CACHE.update(cfg)
    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "auto_gift_config"},
            {"$set": {"config": cfg, "updated_at": datetime.datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving auto gift config: {e}")


async def extract_sample_clip_ffmpeg(video_path: str, start_sec: float, duration_sec: int, output_path: str) -> bool:
    """Extract a 2-4 second preview clip using ffmpeg with safe fallback."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-ss", f"{start_sec:.2f}",
            "-i", video_path,
            "-t", str(duration_sec),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-movflags", "+faststart",
            "-y", output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            return True
    except Exception as e:
        logger.warning(f"ffmpeg sample clip extraction error: {e}")
    return False


def format_gift_settings_dashboard(cfg: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Format stylish interactive dashboard and control keyboard for Auto-Gift publisher."""
    status_str = "🟢 ENABLED (Active)" if cfg.get("enabled") else "🔴 DISABLED (Paused)"
    db_val = cfg.get("db_channel")
    db_str = f"<code>{db_val}</code>" if db_val else "<i>Not Set (Send /setgiftdb)</i>"
    
    post_val = cfg.get("post_channel")
    post_str = f"<code>{post_val}</code>" if post_val else "<i>Not Set (Send /setgiftpost)</i>"
    
    claims_val = cfg.get("claims", 0)
    claims_str = "♾️ Unlimited (No limit)" if claims_val == 0 else f"{claims_val} Claims"

    dur_val = cfg.get("duration_seconds", 0)
    if dur_val == 0:
        dur_str = "♾️ Lifetime (Never expires)"
    elif dur_val >= 86400:
        dur_str = f"{dur_val // 86400} Days"
    else:
        dur_str = f"{dur_val // 3600} Hours"

    chs = cfg.get("channels", [])
    chs_str = ", ".join(chs) if chs else "<i>None (Direct File Delivery)</i>"

    short_str = "🟢 ON (Task Required)" if cfg.get("require_shortener") else "🔴 OFF (Direct Claim)"
    shield_str = "🛡️ Hybrid (Anti-Leave Shield)" if cfg.get("allow_reclaim", True) else "🔒 Strict (1-Claim Only)"

    del_val = cfg.get("auto_delete_seconds", 300)
    del_str = "OFF (No deletion)" if del_val == 0 else f"{del_val // 60} Minutes"

    wait_val = cfg.get("photo_wait_seconds", 60)
    wait_str = "OFF (Instant Drop)" if wait_val == 0 else f"{wait_val}s Wait"

    mode_val = cfg.get("poster_mode", "ss")
    if mode_val == "sample":
        mode_str = "🎬 2-4s Sample Video"
    elif mode_val == "thumb":
        mode_str = "📹 Video Thumbnail"
    else:
        mode_str = "📸 Auto Screenshot (SS)"

    ad_links = cfg.get("ad_links", [])
    if not ad_links and cfg.get("ad_link"):
        ad_links = [cfg["ad_link"]]
    ad_count = len(ad_links)
    ad_wait_val = cfg.get("ad_wait_seconds", 3)
    ad_str = f"<code>{ad_count} Active</code> ({ad_wait_val}s Anti-Cheat each)" if ad_count > 0 else "<i>Disabled (Direct Claim)</i>"

    lines = [
        "🎁 <b>AUTO-GIFT PUBLISHER DASHBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Status:</b> {status_str}",
        f"• <b>Listening DB Channel:</b> {db_str}",
        f"• <b>Public Drops Channel:</b> {post_str}",
        f"• <b>Default Claims:</b> <code>{claims_str}</code>",
        f"• <b>Default Duration:</b> <code>{dur_str}</code>",
        f"• <b>Required Channels:</b> <code>{chs_str}</code>",
        f"• <b>Shortener Verification:</b> {short_str}",
        f"• <b>Sponsor Ad Task:</b> {ad_str} ({ad_wait_val}s Anti-Cheat)",
        f"• <b>Re-Download Shield:</b> {shield_str}",
        f"• <b>Auto-Delete Timer:</b> <code>{del_str}</code>",
        f"• <b>Photo Wait Window:</b> <code>{wait_str}</code>",
        f"• <b>Poster Engine Mode:</b> <code>{mode_str}</code>",
        f"• <b>Post Header:</b> <code>{html.escape(cfg.get('post_header', '🔥 EXCLUSIVE DROP 🔥'))}</code>",
        f"• <b>Post Button:</b> <code>{html.escape(cfg.get('post_button', '⚡ Get Full Video ➔'))}</code>",
        "• <b>Fallback Chain:</b> Photo ➔ SS / Sample ➔ Thumb ➔ TMDB ➔ 3D Box",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Any video dropped into your DB Channel will automatically be converted into a gift reward and published live!</i>\n",
        "<b>Commands to change settings:</b>",
        "• <code>/setgiftdb <channel_id></code> — Set listening DB channel",
        "• <code>/setgiftpost <channel_id></code> — Set public drops channel",
        "• <code>/setgiftchannels <@ch1, -100id...></code> — Set required channels",
        "• <code>/setgiftwait <seconds></code> — 60s, 30s, or 0s for instant",
        "• <code>/setgiftmode <ss|sample|thumb></code> — Screenshot, sample video, or thumb",
        "• <code>/setgiftdel <5m|10m|30m|off></code> — Set auto-delete timer",
        "• <code>/setgiftclaims <0|number></code> — 0 for unlimited",
        "• <code>/setgiftshortener <on|off></code> — Shortener task toggle",
        "• <code>/setgiftheader <text></code> — Customize drop post header",
        "• <code>/setgiftbutton <text></code> — Customize drop claim button",
        "• <code>/setgiftad <url|off></code> — Set Adsterra / sponsor direct link",
        "• <code>/setgiftadwait <seconds></code> — Anti-cheat timer (default 3s)"
    ]
    text = "\n".join(lines)

    toggle_btn_text = "🔴 Turn OFF" if cfg.get("enabled") else "🟢 Turn ON"
    short_btn_text = "🔗 Shortener: OFF" if cfg.get("require_shortener") else "🔗 Shortener: ON"
    shield_btn_text = "🔒 Mode: Strict" if not cfg.get("allow_reclaim", True) else "🛡️ Mode: Hybrid"
    mode_btn_text = f"🎨 Mode: {'SS' if mode_val == 'ss' else ('Sample' if mode_val == 'sample' else 'Thumb')}"
    wait_btn_text = f"⏱️ Wait: {wait_str}"

    keyboard = [
        [
            InlineKeyboardButton(f"⚡ {toggle_btn_text}", callback_data="agift_toggle"),
            InlineKeyboardButton(short_btn_text, callback_data="agift_shortener")
        ],
        [
            InlineKeyboardButton(mode_btn_text, callback_data="agift_mode"),
            InlineKeyboardButton(wait_btn_text, callback_data="agift_wait")
        ],
        [
            InlineKeyboardButton(shield_btn_text, callback_data="agift_shield"),
            InlineKeyboardButton(f"⏳ Delete: {del_str}", callback_data="agift_autodel")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="agift_refresh")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


@Client.on_message(filters.command(["giftsettings", "autogift", "giftconfig"]) & filters.private)
async def gift_settings_command(client: Client, message: Message):
    """Admin interactive dashboard to inspect and configure automated gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin only.")

    cfg = await get_auto_gift_config()
    text, markup = format_gift_settings_dashboard(cfg)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^agift_"))
async def gift_settings_callback_handler(client: Client, query: CallbackQuery):
    """Handle interactive dashboard button clicks."""
    if not Config.is_admin(query.from_user.id):
        return await query.answer("⛔ Admin only.", show_alert=True)

    data = query.data
    cfg = await get_auto_gift_config()

    if data == "agift_toggle":
        new_val = not cfg.get("enabled", False)
        await save_auto_gift_config({"enabled": new_val})
        await query.answer(f"Auto-Gift {'Enabled' if new_val else 'Disabled'}!")

    elif data == "agift_shortener":
        new_val = not cfg.get("require_shortener", False)
        await save_auto_gift_config({"require_shortener": new_val})
        await query.answer(f"Shortener {'Enabled' if new_val else 'Disabled'}!")

    elif data == "agift_mode":
        curr = cfg.get("poster_mode", "ss")
        modes = ["ss", "sample", "thumb"]
        try:
            next_idx = (modes.index(curr) + 1) % len(modes)
        except ValueError:
            next_idx = 0
        new_mode = modes[next_idx]
        await save_auto_gift_config({"poster_mode": new_mode})
        await query.answer(f"Poster Mode set to {new_mode.upper()}!")

    elif data == "agift_wait":
        curr = cfg.get("photo_wait_seconds", 60)
        cycles = [60, 30, 0]
        try:
            next_idx = (cycles.index(curr) + 1) % len(cycles)
        except ValueError:
            next_idx = 0
        new_wait = cycles[next_idx]
        await save_auto_gift_config({"photo_wait_seconds": new_wait})
        w_label = "Instant (0s)" if new_wait == 0 else f"{new_wait}s"
        await query.answer(f"Photo Wait set to {w_label}!")

    elif data == "agift_shield":
        new_val = not cfg.get("allow_reclaim", True)
        await save_auto_gift_config({"allow_reclaim": new_val})
        await query.answer(f"Mode switched to {'Hybrid' if new_val else 'Strict'}!")

    elif data == "agift_autodel":
        curr = cfg.get("auto_delete_seconds", 300)
        cycles = [300, 600, 1800, 0]
        try:
            next_idx = (cycles.index(curr) + 1) % len(cycles)
        except ValueError:
            next_idx = 0
        new_val = cycles[next_idx]
        await save_auto_gift_config({"auto_delete_seconds": new_val})
        del_label = "OFF" if new_val == 0 else f"{new_val // 60}m"
        await query.answer(f"Auto-Delete set to {del_label}!")

    elif data == "agift_refresh":
        await query.answer("Dashboard Refreshed!")

    cfg = await get_auto_gift_config()
    text, markup = format_gift_settings_dashboard(cfg)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_message(filters.command("setgiftdb") & filters.private)
async def set_gift_db_command(client: Client, message: Message):
    """Admin command to configure the private channel where gift files are uploaded."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply_text("Usage: <code>/setgiftdb <channel_id or @username></code>\nExample: <code>/setgiftdb -1001234567890</code>")

    arg = parts[1].strip()
    if arg.lower() in ("off", "none", "disable", "clear", "0"):
        await save_auto_gift_config({"db_channel": None})
        return await message.reply_text(
            "✅ <b>Auto-Gift DB Channel Cleared / Unlinked!</b>\n\n"
            "• Bot will no longer intercept uploads in your movie DB channel.\n"
            "• To re-link a separate gift channel anytime: <code>/setgiftdb &lt;channel_id&gt;</code>"
        )

    target = int(arg) if (arg.startswith("-100") or arg.lstrip("-").isdigit()) else arg
    title = str(target)
    try:
        chat = await client.get_chat(target)
        if chat and chat.title:
            title = chat.title
            target = chat.id
    except Exception as e:
        logger.debug(f"Could not fetch chat info for {target}: {e}")

    await save_auto_gift_config({"db_channel": target})
    await message.reply_text(
        f"✅ <b>GIFT DB CHANNEL CONFIGURED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 <b>Listening Channel:</b> <code>{title}</code> (<code>{target}</code>)\n\n"
        f"🚀 <i>Any video sent or forwarded into this channel will automatically trigger a gift drop!</i>"
    )


@Client.on_message(filters.command("setgiftpost") & filters.private)
async def set_gift_post_command(client: Client, message: Message):
    """Admin command to configure the public channel where gift drop cards are posted."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply_text("Usage: <code>/setgiftpost <channel_id or @username></code>\nExample: <code>/setgiftpost @AkMovieVerse_Gifts</code>")

    arg = parts[1].strip()
    if arg.lower() in ("off", "none", "disable", "clear", "0"):
        await save_auto_gift_config({"post_channel": None})
        return await message.reply_text(
            "✅ <b>Auto-Gift Public Drops Channel Cleared / Unlinked!</b>\n\n"
            "• To re-link a gift drops channel anytime: <code>/setgiftpost &lt;channel_id&gt;</code>"
        )

    target = int(arg) if (arg.startswith("-100") or arg.lstrip("-").isdigit()) else arg
    title = str(target)
    try:
        chat = await client.get_chat(target)
        if chat and chat.title:
            title = chat.title
            target = chat.id
    except Exception as e:
        logger.debug(f"Could not fetch chat info for {target}: {e}")

    await save_auto_gift_config({"post_channel": target})
    await message.reply_text(
        f"✅ <b>GIFT PUBLIC DROPS CHANNEL CONFIGURED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Target Drops Channel:</b> <code>{title}</code> (<code>{target}</code>)\n\n"
        f"🚀 <i>Every new automated gift drop will be published live to this channel!</i>"
    )


@Client.on_message(filters.command("setgiftchannels") & filters.private)
async def set_gift_channels_command(client: Client, message: Message):
    """Admin command to configure required sponsor channels (supports @channel, -100id, and -100id|invite)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply_text(
            "Usage: <code>/setgiftchannels ch1, ch2, ch3...</code>\n\n"
            "<b>Supported Formats:</b>\n"
            "• Public: <code>@AkMovieVerse</code>\n"
            "• Private ID: <code>-1002031749807</code>\n"
            "• Private with Invite Link: <code>-1002031749807 | https://t.me/+goqkqMMq</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/setgiftchannels @AkMovieVerse, -1002031749807 | https://t.me/+goqkqMMq</code>\n\n"
            "<i>To clear:</i> <code>/setgiftchannels off</code>"
        )

    arg = parts[1].strip()
    if arg.lower() in ("off", "none", "clear", "0"):
        await save_auto_gift_config({"channels": []})
        return await message.reply_text("✅ <b>Required Sponsor Channels Cleared!</b> (Gifts will have direct access with no channel tasks)")

    def sanitize_channel_item(item: str) -> str:
        s = item.strip().strip("<>\"\'[]() ")
        if "|" in s:
            p = s.split("|", 1)
            p0 = p[0].strip().strip("<>\"\'[]() ")
            p1 = p[1].strip().strip("<>\"\'[]() ")
            return f"{p0} | {p1}"
        return s

    channel_items = [sanitize_channel_item(c) for c in arg.split(",") if sanitize_channel_item(c)]
    await save_auto_gift_config({"channels": channel_items})
    await message.reply_text(
        f"✅ <b>REQUIRED SPONSOR CHANNELS UPDATED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Channels:</b> <code>{', '.join(channel_items)}</code>\n\n"
        f"🔒 <i>Users must join all these channels before unlocking the gift!</i>\n"
        f"⚠️ <b>Note:</b> Make sure the bot is an <b>ADMIN</b> in private channels with invite link permissions!"
    )


@Client.on_message(filters.command("setgiftshortener") & filters.private)
async def set_gift_shortener_command(client: Client, message: Message):
    """Admin command to toggle shortener verification on automated gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    val = parts[1].strip().lower() if len(parts) > 1 else ""
    if val in ("on", "true", "yes", "enable", "1"):
        await save_auto_gift_config({"require_shortener": True})
        await message.reply_text("✅ <b>Shortener Verification Enabled for Auto-Gifts!</b>")
    elif val in ("off", "false", "no", "disable", "0"):
        await save_auto_gift_config({"require_shortener": False})
        await message.reply_text("✅ <b>Shortener Verification Disabled for Auto-Gifts!</b> (Direct Access)")
    else:
        cfg = await get_auto_gift_config()
        await message.reply_text(f"Current Shortener Setting: <code>{'ON' if cfg.get('require_shortener') else 'OFF'}</code>\nUsage: <code>/setgiftshortener on|off</code>")


@Client.on_message(filters.command("setgiftwait") & filters.private)
async def set_gift_wait_command(client: Client, message: Message):
    """Admin command to configure photo wait buffer in seconds (0 = instant)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return await message.reply_text("Usage: <code>/setgiftwait <seconds></code>\nExample: <code>/setgiftwait 60</code> or <code>/setgiftwait 0</code> (instant)")

    sec = int(parts[1].strip())
    sec = max(0, min(300, sec))
    await save_auto_gift_config({"photo_wait_seconds": sec})
    w_str = "Instant (0s)" if sec == 0 else f"{sec} Seconds"
    await message.reply_text(f"✅ <b>Photo Wait Buffer Set to:</b> <code>{w_str}</code>")


@Client.on_message(filters.command("setgiftmode") & filters.private)
async def set_gift_mode_command(client: Client, message: Message):
    """Admin command to configure poster engine mode (ss | sample | thumb)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    mode = parts[1].strip().lower() if len(parts) > 1 else ""
    if mode not in ("ss", "sample", "thumb"):
        return await message.reply_text(
            "Usage: <code>/setgiftmode <ss | sample | thumb></code>\n\n"
            "• <code>ss</code> : Auto Screenshot Frame with branding watermark (Default)\n"
            "• <code>sample</code> : 2-4s Looping Sample Video Preview\n"
            "• <code>thumb</code> : Native Video Thumbnail"
        )

    await save_auto_gift_config({"poster_mode": mode})
    mode_names = {"ss": "Auto Screenshot Frame", "sample": "2-4s Sample Video", "thumb": "Native Video Thumbnail"}
    await message.reply_text(f"✅ <b>Poster Engine Mode Set to:</b> <code>{mode_names[mode]}</code>")


@Client.on_message(filters.command("setgiftdel") & filters.private)
async def set_gift_del_command(client: Client, message: Message):
    """Admin command to configure auto-delete timer for delivered gift files."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply_text("Usage: <code>/setgiftdel <5m|10m|30m|1h|off></code>")

    arg = parts[1].strip().lower()
    if arg in ("off", "0", "disable", "none"):
        await save_auto_gift_config({"auto_delete_seconds": 0})
        return await message.reply_text("✅ <b>Auto-Delete Disabled!</b> Delivered files will remain in chat permanently.")

    dur_sec = parse_short_duration(arg)
    if dur_sec is None or dur_sec <= 0:
        return await message.reply_text("⚠️ Invalid duration! Use <code>5m</code>, <code>10m</code>, <code>30m</code>, or <code>1h</code>.")

    await save_auto_gift_config({"auto_delete_seconds": dur_sec})
    mins = dur_sec // 60
    await message.reply_text(f"✅ <b>Gift Auto-Delete Timer Set to {mins} Minutes!</b> (Files will self-destruct after {mins}m)")


@Client.on_message(filters.command("setgiftclaims") & filters.private)
async def set_gift_claims_command(client: Client, message: Message):
    """Admin command to configure default maximum claim limits."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return await message.reply_text("Usage: <code>/setgiftclaims <number></code> (Use 0 for unlimited)")

    claims = int(parts[1].strip())
    await save_auto_gift_config({"claims": claims})
    c_str = "Unlimited" if claims == 0 else f"{claims} Claims"
    await message.reply_text(f"✅ <b>Default Claims Set to:</b> <code>{c_str}</code>")


@Client.on_message(filters.command("setgiftduration") & filters.private)
async def set_gift_duration_command(client: Client, message: Message):
    """Admin command to configure default gift drop expiry duration."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        return await message.reply_text("Usage: <code>/setgiftduration <0|24h|48h|7d></code> (Use 0 for lifetime)")

    arg = parts[1].strip().lower()
    if arg in ("0", "lifetime", "forever", "off"):
        await save_auto_gift_config({"duration_seconds": 0})
        return await message.reply_text("✅ <b>Default Duration Set to:</b> <code>Lifetime (Never Expires)</code>")

    dur_sec = parse_short_duration(arg)
    if dur_sec is None or dur_sec <= 0:
        return await message.reply_text("⚠️ Invalid duration format! Use <code>24h</code>, <code>48h</code>, or <code>7d</code>.")

    await save_auto_gift_config({"duration_seconds": dur_sec})
    await message.reply_text(f"✅ <b>Default Duration Set to:</b> <code>{dur_sec // 3600} Hours</code>")

@Client.on_message(filters.command("setgiftheader") & filters.private)
async def set_gift_header_command(client: Client, message: Message):
    """Admin command to configure custom header for automated gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        cfg = await get_auto_gift_config()
        curr = cfg.get("post_header", "🔥 EXCLUSIVE DROP 🔥")
        return await message.reply_text(
            f"Current Header: <code>{html.escape(curr)}</code>\n\n"
            f"Usage: <code>/setgiftheader <text></code>\n"
            f"Example: <code>/setgiftheader 🔥 EXCLUSIVE REWARD DROP 🔥</code>"
        )

    new_hdr = parts[1].strip()
    await save_auto_gift_config({"post_header": new_hdr})
    await message.reply_text(f"✅ <b>Post Header Updated!</b>\n\nNew Header: <b>{html.escape(new_hdr)}</b>")


@Client.on_message(filters.command("setgiftbutton") & filters.private)
async def set_gift_button_command(client: Client, message: Message):
    """Admin command to configure custom button label for automated gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        cfg = await get_auto_gift_config()
        curr = cfg.get("post_button", "⚡ Get Full Video ➔")
        return await message.reply_text(
            f"Current Button: <code>{html.escape(curr)}</code>\n\n"
            f"Usage: <code>/setgiftbutton <text></code>\n"
            f"Example: <code>/setgiftbutton ⚡ Get Full Video ➔</code>"
        )

    new_btn = parts[1].strip()
    await save_auto_gift_config({"post_button": new_btn})
    await message.reply_text(f"✅ <b>Post Button Updated!</b>\n\nNew Button: <code>{html.escape(new_btn)}</code>")

@Client.on_message(filters.command("setgiftad") & filters.private)
async def set_gift_ad_command(client: Client, message: Message):
    """Admin command to configure single or multiple Adsterra / sponsor direct links."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2:
        cfg = await get_auto_gift_config()
        links = cfg.get("ad_links", [])
        if not links and cfg.get("ad_link"):
            links = [cfg["ad_link"]]
        curr_str = "\n".join([f"• <code>{html.escape(l)}</code>" for l in links]) if links else "<i>None (Disabled)</i>"
        return await message.reply_text(
            f"📢 <b>Current Sponsor Ad Links ({len(links)}):</b>\n{curr_str}\n\n"
            f"<b>Usage:</b> <code>/setgiftad <url1, url2, ...></code>\n"
            f"<b>Example (Single):</b> <code>/setgiftad https://auctionr.org/...</code>\n"
            f"<b>Example (Multiple):</b> <code>/setgiftad https://link1.com, https://link2.com</code>\n\n"
            f"<i>To disable:</i> <code>/setgiftad off</code>"
        )

    arg = parts[1].strip()
    if arg.lower() in ("off", "none", "clear", "0", "disable"):
        await save_auto_gift_config({"ad_links": [], "ad_link": None})
        return await message.reply_text("✅ <b>All Sponsor Ad Tasks Disabled!</b> (Direct claim with no ad tasks)")

    raw_urls = [u.strip() for u in arg.split(",") if u.strip()]
    valid_urls = [u for u in raw_urls if u.startswith("http://") or u.startswith("https://")]
    if not valid_urls:
        return await message.reply_text("⚠️ No valid links found! Links must start with <code>https://</code> or <code>http://</code>.")

    await save_auto_gift_config({
        "ad_links": valid_urls,
        "ad_link": valid_urls[0]
    })
    wait_sec = (await get_auto_gift_config()).get("ad_wait_seconds", 3)
    items_str = "\n".join([f"{idx}. <code>{html.escape(u)}</code>" for idx, u in enumerate(valid_urls, start=1)])
    await message.reply_text(
        f"✅ <b>{len(valid_urls)} SPONSOR AD TASKS CONFIGURED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{items_str}\n\n"
        f"⏱️ <b>Anti-Cheat Timer:</b> <code>{wait_sec} Seconds per offer</code>\n"
        f"🛡️ <i>Users must spend at least {wait_sec}s on EACH link to verify!</i>\n"
        f"💰 <i>Multi-ad earnings activated on every gift claim!</i>"
    )


@Client.on_message(filters.command("setgiftadwait") & filters.private)
async def set_gift_ad_wait_command(client: Client, message: Message):
    """Admin command to configure anti-cheat wait timer in seconds for sponsor ads."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    parts = message.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return await message.reply_text(
            "Usage: <code>/setgiftadwait <seconds></code>\n"
            "Example: <code>/setgiftadwait 3</code> or <code>/setgiftadwait 5</code>"
        )

    sec = int(parts[1].strip())
    sec = max(1, min(60, sec))
    await save_auto_gift_config({"ad_wait_seconds": sec})
    await message.reply_text(f"✅ <b>Sponsor Ad Anti-Cheat Timer Set to:</b> <code>{sec} Seconds</code>")




@Client.on_message(filters.command(["postnow", "giftpostnow"]) & ~filters.private)
async def auto_gift_post_now_command(client: Client, message: Message):
    """Immediately publish pending video without waiting for photo timeout."""
    if not message.reply_to_message or message.reply_to_message.id not in _PENDING_GIFT_VIDEOS:
        pending_ids = [mid for mid, item in _PENDING_GIFT_VIDEOS.items() if item["chat_id"] == message.chat.id]
        if not pending_ids:
            return await message.reply_text("ℹ️ No pending gift drop waiting for photo in this channel.")
        target_msg_id = max(pending_ids)
    else:
        target_msg_id = message.reply_to_message.id

    item = _PENDING_GIFT_VIDEOS.get(target_msg_id)
    if item:
        item["event"].set()
        await message.reply_text("⚡ <b>Skipping wait timer!</b> Processing and publishing gift drop now...", quote=True)


# ==============================================================================
# 🚀 Gift DB Channel Photo Listener (Custom Poster Interceptor)
# ==============================================================================

@Client.on_message(filters.photo & ~filters.private)
async def auto_gift_photo_listener(client: Client, message: Message):
    """Intercept custom poster photos sent into GIFT_DB_CHANNEL."""
    cfg = await get_auto_gift_config()
    if not cfg.get("enabled"):
        return

    db_ch = cfg.get("db_channel")
    if not db_ch:
        return

    chat_id = message.chat.id
    if str(chat_id) != str(db_ch) and (not message.chat.username or f"@{message.chat.username}".lower() != str(db_ch).lower()):
        return

    photo_id = message.photo.file_id

    # Check if this photo is replying to a pending video
    target_msg_id = None
    if message.reply_to_message and message.reply_to_message.id in _PENDING_GIFT_VIDEOS:
        target_msg_id = message.reply_to_message.id
    else:
        pending_ids = [mid for mid, item in _PENDING_GIFT_VIDEOS.items() if item["chat_id"] == chat_id]
        if pending_ids:
            target_msg_id = max(pending_ids)

    if target_msg_id and target_msg_id in _PENDING_GIFT_VIDEOS:
        item = _PENDING_GIFT_VIDEOS[target_msg_id]
        item["photo_id"] = photo_id
        item["event"].set()
        try:
            await message.reply_text(
                f"📸 <b>Custom Poster Attached!</b>\n"
                f"Assigned to <code>{html.escape(item['file_name'])}</code>. Publishing gift drop now...",
                quote=True
            )
        except Exception:
            pass


# ==============================================================================
# 🚀 Gift DB Channel Listener (Single-Post Automatic Publisher)
# ==============================================================================

@Client.on_message(filters.channel & (filters.video | filters.document))
async def auto_gift_db_channel_listener(client: Client, message: Message):
    """Automatically convert media dropped into GIFT_DB_CHANNEL into live gift drops."""
    cfg = await get_auto_gift_config()
    if not cfg.get("enabled"):
        return

    db_ch = cfg.get("db_channel")
    post_ch = cfg.get("post_channel")
    if not db_ch or not post_ch:
        return

    chat_id = message.chat.id
    if chat_id != db_ch and str(chat_id) != str(db_ch):
        if message.chat.username and f"@{message.chat.username}".lower() != str(db_ch).lower():
            return

    media = message.video or message.document
    if not media:
        return

    if message.document:
        fn_check = (getattr(message.document, "file_name", "") or "").lower()
        mime_check = (getattr(message.document, "mime_type", "") or "").lower()
        valid_exts = (".mkv", ".mp4", ".avi", ".webm", ".mov", ".flv", ".ts", ".m4v", ".zip", ".rar")
        if not (any(fn_check.endswith(ext) for ext in valid_exts) or mime_check.startswith("video/")):
            return

    file_id = media.file_id
    file_unique_id = media.file_unique_id
    file_name = getattr(media, "file_name", None) or f"Video_{message.id}.mp4"
    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", "")
    caption = message.caption or ""

    from utils.helpers import parse_media_metadata, get_readable_size, get_cached_poster_url
    meta = parse_media_metadata(file_name, caption=caption)
    clean_title = meta.get("clean_name") or file_name
    quality = meta.get("quality")

    # Step 1: Check photo wait buffer (e.g. 60s for admin to send custom poster)
    wait_sec = int(cfg.get("photo_wait_seconds", 60))
    event = asyncio.Event()
    pending_info = {
        "event": event,
        "photo_id": None,
        "chat_id": chat_id,
        "file_name": file_name,
        "status_msg": None
    }
    _PENDING_GIFT_VIDEOS[message.id] = pending_info

    if wait_sec > 0:
        try:
            pending_info["status_msg"] = await message.reply_text(
                f"⏳ <b>Auto-Gift Pending:</b> <code>{html.escape(clean_title)}</code>\n"
                f"⏱️ Waiting <b>{wait_sec}s</b> for custom poster photo (reply with photo or send photo)...\n"
                f"💡 <i>Tip: Send /postnow or reply to skip waiting.</i>",
                quote=True
            )
        except Exception:
            pass

        try:
            await asyncio.wait_for(event.wait(), timeout=wait_sec)
        except asyncio.TimeoutError:
            pass

    photo_id = pending_info.get("photo_id")
    _PENDING_GIFT_VIDEOS.pop(message.id, None)

    # Step 2: Poster & Sample Video Resolution Hierarchy
    poster_photo = None
    sample_video_path = None
    temp_dir = None
    mode = cfg.get("poster_mode", "ss")

    if photo_id:
        poster_photo = photo_id
    else:
        # No custom photo sent: check if we can extract auto-screenshot or 2-4s sample video
        max_extract_bytes = 500 * 1024 * 1024  # 500 MB safeguard limit
        if mode in ("ss", "sample") and file_size <= max_extract_bytes:
            temp_dir = tempfile.mkdtemp(prefix="autogift_")
            try:
                if pending_info["status_msg"]:
                    status_text = "📸 Extracting HD screenshot..." if mode == "ss" else "🎬 Extracting 3s sample video preview..."
                    try:
                        await pending_info["status_msg"].edit_text(f"⚙️ <b>{status_text}</b>")
                    except Exception:
                        pass

                video_local = await asyncio.wait_for(
                    client.download_media(message, file_name=os.path.join(temp_dir, file_name)),
                    timeout=90.0
                )
                if video_local and os.path.exists(video_local):
                    from plugins.screenshots import extract_frame_ffmpeg, apply_watermark, get_video_duration
                    duration = getattr(media, "duration", 0) or await get_video_duration(video_local)
                    if duration <= 2:
                        duration = 10.0
                    start_sec = max(2.0, min(duration * 0.2, duration - 4.0))

                    if mode == "sample":
                        s_path = os.path.join(temp_dir, "sample_preview.mp4")
                        if await extract_sample_clip_ffmpeg(video_local, start_sec, 3, s_path):
                            sample_video_path = s_path

                    if not sample_video_path:
                        f_path = os.path.join(temp_dir, "screenshot.jpg")
                        if await extract_frame_ffmpeg(video_local, start_sec, f_path):
                            watermark = getattr(Config, "DEFAULT_POSTER_BRAND", "@AkMovieVerse") or "@AkMovieVerse"
                            apply_watermark(f_path, watermark_text=watermark)
                            poster_photo = f_path
            except Exception as e_proc:
                logger.warning(f"Auto-gift media extraction failed: {e_proc}")

        # Fallbacks if local media extraction was not performed or failed
        if not poster_photo and not sample_video_path:
            if hasattr(media, "thumbs") and media.thumbs:
                poster_photo = media.thumbs[0].file_id
            else:
                tmdb_poster = await get_cached_poster_url(clean_title)
                if tmdb_poster:
                    poster_photo = tmdb_poster
                else:
                    from database.gifts import DEFAULT_GIFT_POSTER
                    poster_photo = DEFAULT_GIFT_POSTER

    # Step 3: Index file in MongoDB
    from database.files import save_file
    file_doc = {
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_name": file_name,
        "file_size": file_size,
        "file_type": "video" if message.video else "document",
        "mime_type": mime_type,
        "caption": caption,
        "channel_id": message.chat.id,
        "message_id": message.id
    }
    try:
        await save_file(file_doc)
    except Exception as e_save:
        logger.debug(f"Auto-gift save_file note: {e_save}")

    # Step 4: Create Gift in Database
    gift_doc = await create_gift(
        title=clean_title,
        file_type="single",
        file_doc=file_doc,
        total_files=1,
        total_size=file_size,
        poster_url=(
            poster_photo if isinstance(poster_photo, str) and (poster_photo.startswith("http") or not os.path.exists(poster_photo)) else None
        ),
        channels=cfg.get("channels", []),
        require_shortener=cfg.get("require_shortener", False),
        is_vip_only=False,
        protect_content=cfg.get("protect_content", True),
        auto_delete_seconds=cfg.get("auto_delete_seconds", 300),
        max_claims=cfg.get("claims", 0),
        duration_seconds=cfg.get("duration_seconds", 0),
        created_by=0,
        allow_reclaim=cfg.get("allow_reclaim", True),
        ad_link=cfg.get("ad_link"),
        ad_links=cfg.get("ad_links", []),
        ad_wait_seconds=cfg.get("ad_wait_seconds", 3),
        ad_button_text=cfg.get("ad_button_text", "🌐 View Sponsored Offer ↗️")
    )

    gift_id = gift_doc.get("gift_id")
    if not gift_id:
        logger.error("Failed to generate gift_id for auto-gift drop!")
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return

    bot_uname = client.me.username if client.me else Config.BOT_USERNAME
    claim_url = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

    dur_val = cfg.get("duration_seconds", 0)
    validity_str = "♾️ Lifetime Access" if dur_val == 0 else f"⏳ {dur_val // 3600} Hours"
    
    claims_val = cfg.get("claims", 0)
    claims_str = "♾️ Unlimited Claims" if claims_val == 0 else f"🔥 First {claims_val} Users Only"

    post_hdr = cfg.get("post_header", "🔥 EXCLUSIVE DROP 🔥")
    post_btn = cfg.get("post_button", "⚡ Get Full Video ➔")

    caption_text = (
        f"<b>{post_hdr}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ <b>Title:</b> <code>{html.escape(clean_title)}</code>\n"
        f"📦 <b>Details:</b> <code>{quality or 'HD'} • {get_readable_size(file_size)}</code>\n"
        f"⚡ <b>Availability:</b> <code>{claims_str}</code>\n"
        f"⏳ <b>Validity:</b> <code>{validity_str}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 <b>Download / Watch Online:</b>\n"
        f"👉 <a href=\"{claim_url}\"><b>⚡ CLICK HERE TO GET FULL VIDEO ⚡</b></a>"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(post_btn, url=claim_url)]
    ])

    # Step 5: Send Live Card to Public Drops Channel
    sent_pub_msg = None
    try:
        if sample_video_path and os.path.exists(sample_video_path):
            try:
                sent_pub_msg = await client.send_video(
                    chat_id=post_ch,
                    video=sample_video_path,
                    caption=caption_text,
                    reply_markup=markup,
                    supports_streaming=True
                )
                logger.info(f"Auto-gift published with sample video preview to {post_ch} (Gift ID: {gift_id})")
            except Exception as e_vid:
                logger.warning(f"Sending sample video failed: {e_vid}, falling back to photo")
                sent_pub_msg = await client.send_photo(
                    chat_id=post_ch,
                    photo=poster_photo or DEFAULT_GIFT_POSTER,
                    caption=caption_text,
                    reply_markup=markup
                )
        else:
            sent_pub_msg = await client.send_photo(
                chat_id=post_ch,
                photo=poster_photo,
                caption=caption_text,
                reply_markup=markup
            )
            logger.info(f"Auto-gift successfully published to {post_ch} (Gift ID: {gift_id})")
    except Exception as e_post:
        logger.error(f"Failed to publish auto-gift to {post_ch}: {e_post}")
        try:
            sent_pub_msg = await client.send_message(
                chat_id=post_ch,
                text=caption_text,
                reply_markup=markup,
                disable_web_page_preview=True
            )
        except Exception:
            pass
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if sent_pub_msg:
        try:
            await mongo.db["gift_rewards"].update_one(
                {"gift_id": gift_id},
                {"$set": {"post_chat_id": post_ch, "post_msg_id": sent_pub_msg.id}}
            )
        except Exception:
            pass

    # Step 6: Update status message or reply in DB channel
    final_text = (
        f"✅ <b>Gift Drop Published!</b>\n"
        f"🎁 <b>Gift ID:</b> <code>{gift_id}</code>\n"
        f"🔗 <b>Link:</b> {claim_url}"
    )
    try:
        if pending_info.get("status_msg"):
            await pending_info["status_msg"].edit_text(final_text)
        else:
            await message.reply_text(final_text, quote=True)
    except Exception:
        pass
