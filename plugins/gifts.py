import os
import time
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
    """Retrieve target channel for auto-publishing gift drops with dual-cluster resilience."""
    if _GIFT_CHANNEL_CACHE.get("loaded") and _GIFT_CHANNEL_CACHE.get("channel"):
        return _GIFT_CHANNEL_CACHE["channel"]
    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"key": "gift_channel"})
        if doc and "channel" in doc and doc["channel"]:
            val = doc["channel"]
            _GIFT_CHANNEL_CACHE["channel"] = val
            _GIFT_CHANNEL_CACHE["loaded"] = True
            return val
        if mongo.has_secondary:
            doc2 = await mongo.db2["bot_settings"].find_one({"key": "gift_channel"})
            if doc2 and "channel" in doc2 and doc2["channel"]:
                val = doc2["channel"]
                _GIFT_CHANNEL_CACHE["channel"] = val
                _GIFT_CHANNEL_CACHE["loaded"] = True
                return val
    except Exception as e:
        logger.debug(f"Error loading gift channel setting: {e}")

    default_ch = getattr(Config, "GIFT_CHANNEL", None)
    return default_ch if default_ch and default_ch != 0 else None


async def set_gift_channel(channel):
    """Set target channel for auto-publishing gift drops synced to primary and secondary DB."""
    _GIFT_CHANNEL_CACHE["channel"] = channel
    _GIFT_CHANNEL_CACHE["loaded"] = True
    from database.mongo import mongo
    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "gift_channel"},
            {"$set": {"channel": channel, "updated_at": datetime.datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error persisting gift channel setting: {e}")

    if mongo.has_secondary:
        try:
            await mongo.db2["bot_settings"].update_one(
                {"key": "gift_channel"},
                {"$set": {"channel": channel, "updated_at": datetime.datetime.utcnow()}},
                upsert=True
            )
        except Exception as e2:
            logger.debug(f"Error syncing gift channel to secondary DB: {e2}")



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
        f"🚀 <i>Every new gift created with /gift or /giftbatch will now be automatically published directly to this channel!</i>\n\n"
        f"💡 <b>Channel Migration Tip:</b> If this is a new channel and you want to restore previous gift drops, send <code>/repostgifts</code> to auto-post all active gifts here!"
    )


# ==============================================================================
# Admin Command: /repostgifts [limit] (1-Click Channel Migration Tool)
# ==============================================================================

@Client.on_message(filters.command(["repostgifts", "migrategifts", "repost_gifts"]) & filters.private)
async def repost_gifts_command(client: Client, message: Message):
    """Admin command to automatically re-publish active gifts from MongoDB into a new channel."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin only.")

    target_channel = await get_gift_channel()
    cfg = await get_auto_gift_config()
    if not target_channel:
        target_channel = cfg.get("post_channel")

    if not target_channel:
        return await message.reply_text(
            "⚠️ <b>Target Channel Not Configured!</b>\n\n"
            "Please first set your new channel using:\n"
            "• <code>/setgiftchannel &lt;channel_id&gt;</code>\n"
            "• or <code>/setgiftpost &lt;channel_id&gt;</code>\n\n"
            "<i>Once set, run /repostgifts again to migrate all gifts!</i>"
        )

    # Check bot permissions in target channel
    ch_title = str(target_channel)
    try:
        chat = await client.get_chat(target_channel)
        if chat and chat.title:
            ch_title = chat.title
    except Exception as e:
        return await message.reply_text(
            f"❌ <b>Cannot access target channel:</b> <code>{target_channel}</code>\n"
            f"Error: <code>{e}</code>\n\n"
            "⚠️ Please ensure the bot is added to the channel as an Admin with <b>Post Messages</b> permission."
        )

    # Parse limit (default 100, max 500)
    args = message.text.split()
    limit = 100
    if len(args) > 1 and args[1].isdigit():
        limit = max(1, min(500, int(args[1])))

    from database.gifts import DEFAULT_GIFT_POSTER

    cursor = mongo.db["gift_rewards"].find({"is_active": True}).sort("created_at", 1).limit(limit)
    gifts_list = await cursor.to_list(length=limit)

    if not gifts_list:
        return await message.reply_text("ℹ️ <b>No active gifts found in database to repost.</b>")

    status_msg = await message.reply_text(
        f"🔄 <b>Starting Gift Channel Migration...</b>\n\n"
        f"📢 <b>Target Channel:</b> <code>{ch_title}</code>\n"
        f"🎁 <b>Active Gifts to Repost:</b> <code>{len(gifts_list)}</code>\n"
        f"⏱️ <b>Pacing:</b> Safe 2.5s delay per post (avoids floodwait)\n\n"
        f"⏳ <i>Please wait while posts are being published...</i>"
    )

    bot_uname = client.me.username if client.me else Config.BOT_USERNAME
    post_hdr = cfg.get("post_header", "🔥 EXCLUSIVE DROP 🔥")
    post_btn = cfg.get("post_button", "⚡ Get Full Video ➔")

    reposted_count = 0
    failed_count = 0

    for idx, gift in enumerate(gifts_list, start=1):
        gift_id = gift.get("gift_id")
        title = gift.get("title", "Exclusive Reward")
        file_size = gift.get("total_size", 0)
        auto_del_sec = gift.get("auto_delete_seconds", 300)
        del_mins = auto_del_sec // 60
        del_str = f"{del_mins} Mins" if del_mins > 0 else f"{auto_del_sec}s"
        max_c = gift.get("max_claims", 0)
        stock_str = f"First {max_c} Users" if max_c > 0 else "Unlimited"
        validity_str = "Lifetime" if not gift.get("expires_at") else "Limited Time"
        vip_badge = " • 👑 <b>VIP Only</b>" if gift.get("is_vip_only") else ""
        gift_link = f"https://t.me/{bot_uname}?start=gift_{gift_id}"

        clean_t = format_clean_title(title)
        card_text = (
            f"<b>{post_hdr}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Item:</b> <code>{html.escape(clean_t)}</code>\n"
            f"💾 <b>Size:</b> <code>{get_readable_size(file_size)}</code>  •  👥 <b>Stock:</b> <code>{stock_str}</code>\n"
            f"⏳ <b>Validity:</b> <code>{validity_str}</code>  •  ⏱️ <b>Auto-Delete:</b> <code>{del_str}</code>{vip_badge}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔗 <b>Download / Watch Online:</b>\n"
            f"👉 <a href=\"{gift_link}\"><b>⚡ CLICK HERE TO GET FULL VIDEO ⚡</b></a>"
        )

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(post_btn, url=gift_link)]
        ])

        poster = gift.get("poster_url") or DEFAULT_GIFT_POSTER
        sent_msg = None
        try:
            sent_msg = await client.send_photo(
                chat_id=target_channel,
                photo=poster,
                caption=card_text,
                reply_markup=markup
            )
        except Exception:
            try:
                sent_msg = await client.send_message(
                    chat_id=target_channel,
                    text=card_text,
                    reply_markup=markup,
                    disable_web_page_preview=False
                )
            except Exception as e_send:
                logger.warning(f"Error reposting gift {gift_id} to {target_channel}: {e_send}")

        if sent_msg:
            reposted_count += 1
            try:
                await mongo.db["gift_rewards"].update_one(
                    {"gift_id": gift_id},
                    {"$set": {"post_chat_id": target_channel, "post_msg_id": sent_msg.id}}
                )
            except Exception:
                pass
        else:
            failed_count += 1

        if idx % 5 == 0 or idx == len(gifts_list):
            try:
                await status_msg.edit_text(
                    f"🔄 <b>Migrating Gifts to Channel:</b> <code>{ch_title}</code>\n\n"
                    f"• <b>Progress:</b> <code>{idx}/{len(gifts_list)}</code>\n"
                    f"• <b>Successfully Reposted:</b> <code>{reposted_count}</code>\n"
                    f"• <b>Failed:</b> <code>{failed_count}</code>"
                )
            except Exception:
                pass

        await asyncio.sleep(2.5)

    await status_msg.edit_text(
        f"✅ <b>GIFT CHANNEL MIGRATION COMPLETED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Channel:</b> <code>{ch_title}</code>\n"
        f"🎁 <b>Total Reposted:</b> <code>{reposted_count}</code> gifts\n"
        f"⚠️ <b>Failed / Skipped:</b> <code>{failed_count}</code>\n\n"
        f"🎉 <i>All old gifts have been published live into your new channel with active claim buttons!</i>"
    )


# ==============================================================================
# Admin Command: /giftcatalog (Master Catalog / Pinned Index of All Gifts)
# ==============================================================================

@Client.on_message(filters.command(["giftcatalog", "giftindex"]) & filters.private)
async def gift_catalog_command(client: Client, message: Message):
    """Generate a master clickable catalog list of all active gifts."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin only.")

    cursor = mongo.db["gift_rewards"].find({"is_active": True}).sort("created_at", -1).limit(100)
    gifts_list = await cursor.to_list(length=100)

    if not gifts_list:
        return await message.reply_text("ℹ️ <b>No active gifts found in database.</b>")

    bot_uname = client.me.username if client.me else Config.BOT_USERNAME
    lines = [
        "📚 <b>MASTER GIFTS & REWARDS CATALOG</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔥 <i>Total Active Drops: {len(gifts_list)}</i>\n"
    ]

    for idx, gift in enumerate(gifts_list, start=1):
        gid = gift.get("gift_id")
        title = format_clean_title(gift.get("title", "Reward"))
        size_str = get_readable_size(gift.get("total_size", 0))
        link = f"https://t.me/{bot_uname}?start=gift_{gid}"
        lines.append(f"{idx}. <a href=\"{link}\"><b>{html.escape(title[:38])}</b></a> ({size_str})")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Click any title to instantly open and claim it in the bot!</i>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>...and more!</i>"

    await message.reply_text(text, disable_web_page_preview=True)

# ==============================================================================
# 🎁 Automated Gift Drops Engine & Interactive Settings Dashboard
# ==============================================================================

_AUTO_GIFT_CONFIG_CACHE = {
    "loaded": False,
    "enabled": True,
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
    "poster_mode": "sample",
    "post_header": "🔥 EXCLUSIVE DROP 🔥",
    "post_button": "⚡ Get Full Video ➔",
    "ad_link": None,
    "ad_links": [],
    "ad_wait_seconds": 3,
    "ad_button_text": "🌐 View Sponsored Offer ↗️",
    "interval_seconds": 0,
    "queue_paused": False,
    "quiet_hours_enabled": False,
    "quiet_start_hour": 0,
    "quiet_end_hour": 8,
    "jitter_enabled": True,
    "clean_previous_post": False,
    "last_posted_msg_id": None
}

_GIFT_QUEUE_WORKER_TASK: asyncio.Task | None = None
_LAST_GIFT_POST_TIMESTAMP: float = 0.0

# Pending queue of videos waiting for custom poster in GIFT_DB_CHANNEL
# key: message_id -> dict: {"event": asyncio.Event, "photo_id": Optional[str], "chat_id": int, "file_name": str, "status_msg": Optional[Message]}
_PENDING_GIFT_VIDEOS: dict[int, dict] = {}
_GIFT_PROCESS_LOCK = asyncio.Lock()


async def get_auto_gift_config() -> dict:
    """Retrieve auto-gift publisher configuration from MongoDB with dual-cluster resilience."""
    global _AUTO_GIFT_CONFIG_CACHE
    if _AUTO_GIFT_CONFIG_CACHE.get("loaded"):
        return _AUTO_GIFT_CONFIG_CACHE
    try:
        from database.mongo import mongo
        doc = await mongo.db["bot_settings"].find_one({"key": "auto_gift_config"})
        if doc and "config" in doc:
            _AUTO_GIFT_CONFIG_CACHE.update(doc["config"])
            _AUTO_GIFT_CONFIG_CACHE["loaded"] = True
            return _AUTO_GIFT_CONFIG_CACHE
        if mongo.has_secondary:
            doc2 = await mongo.db2["bot_settings"].find_one({"key": "auto_gift_config"})
            if doc2 and "config" in doc2:
                _AUTO_GIFT_CONFIG_CACHE.update(doc2["config"])
                _AUTO_GIFT_CONFIG_CACHE["loaded"] = True
                return _AUTO_GIFT_CONFIG_CACHE
    except Exception as e:
        logger.warning(f"Error loading auto gift config from MongoDB: {e}")
        # Return in-memory cache without setting loaded=True so future calls can retry loading
        return _AUTO_GIFT_CONFIG_CACHE

    _AUTO_GIFT_CONFIG_CACHE["loaded"] = True
    return _AUTO_GIFT_CONFIG_CACHE


async def save_auto_gift_config(updates: dict):
    """Persist updated auto-gift publisher configuration to MongoDB with atomic field updates and cluster replication."""
    global _AUTO_GIFT_CONFIG_CACHE
    if not _AUTO_GIFT_CONFIG_CACHE.get("loaded"):
        await get_auto_gift_config()

    _AUTO_GIFT_CONFIG_CACHE.update(updates)
    _AUTO_GIFT_CONFIG_CACHE["loaded"] = True

    # Use atomic dot-notation ($set: {"config.key": val}) so other settings are NEVER wiped out
    set_fields = {f"config.{k}": v for k, v in updates.items()}
    set_fields["updated_at"] = datetime.datetime.utcnow()

    from database.mongo import mongo
    try:
        await mongo.db["bot_settings"].update_one(
            {"key": "auto_gift_config"},
            {"$set": set_fields},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving auto gift config to primary DB: {e}")

    if mongo.has_secondary:
        try:
            await mongo.db2["bot_settings"].update_one(
                {"key": "auto_gift_config"},
                {"$set": set_fields},
                upsert=True
            )
        except Exception as e2:
            logger.debug(f"Error syncing auto gift config to secondary DB: {e2}")


async def extract_sample_clip_ffmpeg(video_path: str, start_sec: float, duration_sec: int, output_path: str) -> bool:
    """Extract a 2-4 second preview clip using ffmpeg with safe fallback and strict timeout."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y",
            "-ss", f"{start_sec:.2f}",
            "-i", video_path,
            "-t", str(duration_sec),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-an",  # Strip audio for ultra-fast sample generation and avoid audio sync hangs
            "-movflags", "+faststart",
            "-loglevel", "error",
            output_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=20.0)
        except asyncio.TimeoutError:
            logger.warning(f"ffmpeg sample clip extraction timed out after 20s for {video_path}")
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            return True
    except Exception as e:
        logger.warning(f"ffmpeg sample clip extraction error: {e}")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
    return False


def format_gift_settings_dashboard(cfg: dict, q_count: int = 0) -> tuple[str, InlineKeyboardMarkup]:
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

    int_val = cfg.get("interval_seconds", 0)
    if int_val == 0:
        int_str = "OFF (Instant Drops)"
    elif int_val >= 3600:
        int_str = f"{int_val // 3600} Hour(s)"
    else:
        int_str = f"{int_val // 60} Minutes"

    quiet_str = "🌙 ON (12 AM - 8 AM Pause)" if cfg.get("quiet_hours_enabled") else "☀️ OFF (24/7 Drip)"
    clean_str = "🧹 ON (Single Active Post)" if cfg.get("clean_previous_post") else "📜 OFF (Keep All)"

    mode_val = cfg.get("poster_mode", "sample")
    if mode_val == "sample":
        mode_str = "🎬 2-4s Sample ➔ 📸 SS ➔ 🃏 Card (Auto-Cascade)"
    elif mode_val == "thumb":
        mode_str = "📹 Video Thumbnail ➔ 🃏 Card"
    else:
        mode_str = "📸 Auto Screenshot (SS) ➔ 🃏 Card"

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
        f"• <b>Pacing Interval:</b> <code>{int_str}</code>",
        f"• <b>Drip-Feed Queue:</b> <code>{q_count:,} Pending</code>",
        f"• <b>Night Sleep Mode:</b> {quiet_str}",
        f"• <b>Channel Clean Mode:</b> {clean_str}",
        f"• <b>Post Header:</b> <code>{html.escape(cfg.get('post_header', '🔥 EXCLUSIVE DROP 🔥'))}</code>",
        f"• <b>Post Button:</b> <code>{html.escape(cfg.get('post_button', '⚡ Get Full Video ➔'))}</code>",
        "• <b>Poster Hierarchy:</b> 🎬 Sample (2-4s) ➔ 📸 HD Screenshot ➔ 📹 Native Thumb ➔ 🃏 3D Card",
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
        "• <code>/setgiftinterval <15m|30m|1h|off></code> — Drip-feed pacing delay",
        "• <code>/setgiftquiet <on|off></code> — 12 AM - 8 AM night sleep mode",
        "• <code>/setgiftclean <on|off></code> — Single active drop clean mode",
        "• <code>/giftqueue</code> — View scheduled queue & controls",
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
            InlineKeyboardButton(f"⏱️ Pace: {int_str}", callback_data="agift_interval"),
            InlineKeyboardButton(f"📋 Queue ({q_count})", callback_data="agift_view_q")
        ],
        [
            InlineKeyboardButton(f"🌙 Night: {'ON' if cfg.get('quiet_hours_enabled') else 'OFF'}", callback_data="agift_quiet"),
            InlineKeyboardButton(f"🧹 Clean: {'ON' if cfg.get('clean_previous_post') else 'OFF'}", callback_data="agift_clean_prev")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="agift_refresh")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)


async def format_gift_queue_dashboard(cfg: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Build detailed visual status of queued drip-feed gift drops."""
    try:
        queued_cursor = mongo.db["gift_post_queue"].find({"status": "queued"}).sort("queued_at", 1)
        queued_items = await queued_cursor.to_list(length=10)
        total_count = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
        failed_count = await mongo.db["gift_post_queue"].count_documents({"status": "failed"})
    except Exception:
        queued_items = []
        total_count = 0
        failed_count = 0

    int_sec = cfg.get("interval_seconds", 0)
    if int_sec == 0:
        int_str = "OFF (Instant Posting)"
    elif int_sec >= 3600:
        int_str = f"{int_sec // 3600} Hour(s)"
    else:
        int_str = f"{int_sec // 60} Minutes"

    is_paused = cfg.get("queue_paused", False)
    status_emoji = "⏸️ PAUSED" if is_paused else ("🟢 DRIP-FEED ACTIVE" if int_sec > 0 else "⚡ INSTANT MODE")

    # Accurate IST Quiet Hours Status
    now_utc = datetime.datetime.utcnow()
    ist_hour = (now_utc.hour + 5 + (now_utc.minute + 30) // 60) % 24
    q_start = int(cfg.get("quiet_start_hour", 0))
    q_end = int(cfg.get("quiet_end_hour", 8))
    quiet_on = cfg.get("quiet_hours_enabled", False)
    in_quiet = False
    if quiet_on:
        if q_start < q_end:
            in_quiet = (q_start <= ist_hour < q_end)
        elif q_start > q_end:
            in_quiet = (ist_hour >= q_start or ist_hour < q_end)

    if in_quiet:
        quiet_str = f"🌙 Active & Sleeping ({q_start} to {q_end} IST)"
    elif quiet_on:
        quiet_str = f"🌙 Armed ({q_start} to {q_end} IST)"
    else:
        quiet_str = "☀️ Disabled (24/7 Drops)"

    clean_on = cfg.get("clean_previous_post", False)
    clean_str = "🧹 Clean (Single active post)" if clean_on else "📜 Archive (Keep all)"

    now = time.time()
    time_since_last = now - _LAST_GIFT_POST_TIMESTAMP
    if _LAST_GIFT_POST_TIMESTAMP <= 0:
        next_in_str = "Immediately on trigger"
    elif in_quiet:
        next_in_str = f"⏸️ Sleeping until {q_end}:00 IST"
    elif time_since_last >= int_sec:
        next_in_str = "⚡ Ready now (on next tick)"
    else:
        rem_sec = int(int_sec - time_since_last)
        next_in_str = f"~{rem_sec // 60}m {rem_sec % 60}s"

    est_total_mins = (total_count * int_sec) // 60 if int_sec > 0 else 0
    est_str = f"~{est_total_mins // 60}h {est_total_mins % 60}m" if est_total_mins >= 60 else f"~{est_total_mins} mins"

    lines = [
        "📦 <b>AUTO-GIFT DRIP-FEED QUEUE DASHBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Queue Status:</b> {status_emoji}",
        f"• <b>Pending in Queue:</b> <code>{total_count:,} posts</code>",
    ]
    if failed_count > 0:
        lines.append(f"• <b>⚠️ Failed / Stuck Drops:</b> <code>{failed_count} posts</code> (Tap Retry below)")

    lines.extend([
        f"• <b>Pacing Interval:</b> <code>{int_str}</code>",
        f"• <b>Next Drop In:</b> <code>{next_in_str}</code>",
        f"• <b>Est. Completion:</b> <code>{est_str}</code>",
        f"• <b>Night Mode:</b> {quiet_str}",
        f"• <b>Channel Mode:</b> {clean_str}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ])

    if queued_items:
        lines.append("📋 <b>Upcoming Next In Line:</b>")
        for idx, itm in enumerate(queued_items[:5], 1):
            title = itm.get("title", "Untitled Video")
            lines.append(f"<b>#{idx}.</b> <code>{html.escape(title[:40])}</code>")
        if total_count > 5:
            lines.append(f"<i>... and {total_count - 5} more posts waiting in queue</i>")
    else:
        lines.append("ℹ️ <i>Queue is currently empty. Drop videos in DB channel to queue them up!</i>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Tip: Use /setgiftinterval &lt;15m|30m|1h&gt; to customize pacing!</i>")

    pause_btn_text = "▶️ Resume Queue" if is_paused else "⏸️ Pause Queue"
    pause_cb = "agift_q_resume" if is_paused else "agift_q_pause"

    keyboard = [
        [
            InlineKeyboardButton("⚡ Post Next Now", callback_data="agift_q_next"),
            InlineKeyboardButton(pause_btn_text, callback_data=pause_cb)
        ]
    ]

    if failed_count > 0:
        keyboard.append([
            InlineKeyboardButton(f"🔄 Retry {failed_count} Failed Drops", callback_data="agift_q_retry_failed"),
            InlineKeyboardButton("🗑️ Clear Failed", callback_data="agift_q_clear_failed")
        ])

    keyboard.extend([
        [
            InlineKeyboardButton("🧹 Clear All Queue", callback_data="agift_q_clear"),
            InlineKeyboardButton("🔄 Refresh Queue", callback_data="agift_q_refresh")
        ],
        [
            InlineKeyboardButton("🌙 Toggle Night Sleep", callback_data="agift_q_toggle_quiet"),
            InlineKeyboardButton("⚙️ Back to Gift Settings", callback_data="agift_back_settings")
        ]
    ])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def _dispatch_queued_gift(client: Client, item: dict, cfg: dict) -> bool:
    """Publish a single queued gift drop to the target public channel with 4-tier resilient delivery."""
    try:
        post_ch = item["post_ch"]
        caption_text = item["caption_text"]
        claim_url = item["claim_url"]
        post_btn = item.get("post_btn", "⚡ Get Full Video ➔")
        poster_photo = item.get("poster_photo")
        sample_video_path = item.get("sample_video_path")
        gift_id = item.get("gift_id")

        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(post_btn, url=claim_url)]
        ])

        sent_pub_msg = None

        # Tier 1: Try sending extracted 3s sample preview video if available
        if sample_video_path and os.path.exists(sample_video_path):
            try:
                sent_pub_msg = await client.send_video(
                    chat_id=post_ch,
                    video=sample_video_path,
                    caption=caption_text,
                    reply_markup=markup,
                    supports_streaming=True
                )
            except Exception as e_vid:
                logger.warning(f"Sending queued sample video failed: {e_vid}, falling back to poster photo")

        # Tier 2: Try custom / local / cached poster photo
        if not sent_pub_msg and poster_photo:
            try:
                sent_pub_msg = await client.send_photo(
                    chat_id=post_ch,
                    photo=poster_photo,
                    caption=caption_text,
                    reply_markup=markup
                )
            except Exception as e_photo:
                logger.warning(f"Sending queued poster photo ({poster_photo}) failed: {e_photo}, trying default poster URL")

        # Tier 3: Try official high-resolution fallback poster URL
        if not sent_pub_msg:
            from database.gifts import DEFAULT_GIFT_POSTER
            try:
                sent_pub_msg = await client.send_photo(
                    chat_id=post_ch,
                    photo=DEFAULT_GIFT_POSTER,
                    caption=caption_text,
                    reply_markup=markup
                )
            except Exception as e_def:
                logger.warning(f"Sending default gift poster failed: {e_def}, falling back to text-only drop")

        # Tier 4: Text message with inline claim button (100% resilient if photo permissions are restricted)
        if not sent_pub_msg:
            try:
                sent_pub_msg = await client.send_message(
                    chat_id=post_ch,
                    text=caption_text,
                    reply_markup=markup,
                    disable_web_page_preview=False
                )
            except Exception as e_msg:
                logger.error(f"Cannot dispatch queued gift to {post_ch} even via text message: {e_msg}")
                return False

        if sent_pub_msg:
            try:
                await mongo.db["gift_rewards"].update_one(
                    {"gift_id": gift_id},
                    {"$set": {"post_chat_id": post_ch, "post_msg_id": sent_pub_msg.id}}
                )
            except Exception:
                pass

            # Channel Clean Mode: Auto-delete previous active gift post
            if cfg.get("clean_previous_post", False):
                prev_id = cfg.get("last_posted_msg_id")
                if prev_id and prev_id != sent_pub_msg.id:
                    try:
                        await client.delete_messages(chat_id=post_ch, message_ids=[prev_id])
                        logger.info(f"Cleaned previous gift post msg {prev_id} from {post_ch}")
                    except Exception as e_del:
                        logger.debug(f"Could not delete previous gift post {prev_id}: {e_del}")

            await save_auto_gift_config({"last_posted_msg_id": sent_pub_msg.id})
            logger.info(f"Successfully dispatched queued gift '{item.get('title')}' (ID: {gift_id}) to {post_ch}")
            return True
    except Exception as e:
        logger.error(f"Failed to dispatch queued gift: {e}")
        return False
    return False


async def _gift_queue_worker(client: Client):
    """Background engine that continuously pops scheduled gifts and drops them at the set interval."""
    global _LAST_GIFT_POST_TIMESTAMP
    logger.info("Auto-Gift Scheduled Drip Feed Queue Worker started.")
    import random
    while True:
        try:
            await asyncio.sleep(10)
            cfg = await get_auto_gift_config()
            if not cfg.get("enabled"):
                continue
            if cfg.get("queue_paused", False):
                continue

            count = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
            if count == 0:
                continue

            interval_sec = int(cfg.get("interval_seconds", 0))

            # Quiet Hours check (e.g. 12 AM to 8 AM IST)
            if cfg.get("quiet_hours_enabled", False):
                now_utc = datetime.datetime.utcnow()
                ist_hour = (now_utc.hour + 5 + (now_utc.minute + 30) // 60) % 24
                q_start = int(cfg.get("quiet_start_hour", 0))
                q_end = int(cfg.get("quiet_end_hour", 8))
                in_quiet = False
                if q_start < q_end:
                    in_quiet = (q_start <= ist_hour < q_end)
                elif q_start > q_end:
                    in_quiet = (ist_hour >= q_start or ist_hour < q_end)

                if in_quiet:
                    continue

            # Pacing interval check
            now = time.time()
            if interval_sec > 0:
                jitter = 0
                if cfg.get("jitter_enabled", True) and interval_sec >= 120:
                    jitter = random.randint(-min(60, interval_sec // 10), min(60, interval_sec // 10))
                effective_interval = max(30, interval_sec + jitter)

                if _LAST_GIFT_POST_TIMESTAMP > 0 and (now - _LAST_GIFT_POST_TIMESTAMP < effective_interval):
                    continue

            # Pop the oldest queued item
            next_item = await mongo.db["gift_post_queue"].find_one(
                {"status": "queued"},
                sort=[("queued_at", 1)]
            )
            if not next_item:
                continue

            success = await _dispatch_queued_gift(client, next_item, cfg)
            if success:
                _LAST_GIFT_POST_TIMESTAMP = time.time()
                await mongo.db["gift_post_queue"].delete_one({"_id": next_item["_id"]})
            else:
                attempts = next_item.get("attempts", 0) + 1
                if attempts >= 3:
                    await mongo.db["gift_post_queue"].update_one(
                        {"_id": next_item["_id"]},
                        {"$set": {"status": "failed", "attempts": attempts}}
                    )
                else:
                    await mongo.db["gift_post_queue"].update_one(
                        {"_id": next_item["_id"]},
                        {"$set": {"attempts": attempts}}
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in _gift_queue_worker: {e}", exc_info=True)
            await asyncio.sleep(15)


def start_gift_queue_worker(client: Client):
    """Launch the background scheduled drip-feed queue dispatcher."""
    global _GIFT_QUEUE_WORKER_TASK
    if _GIFT_QUEUE_WORKER_TASK and not _GIFT_QUEUE_WORKER_TASK.done():
        return _GIFT_QUEUE_WORKER_TASK
    _GIFT_QUEUE_WORKER_TASK = asyncio.create_task(_gift_queue_worker(client))
    return _GIFT_QUEUE_WORKER_TASK


@Client.on_message(filters.command(["giftsettings", "autogift", "giftconfig"]) & filters.private)
async def gift_settings_command(client: Client, message: Message):
    """Admin interactive dashboard to inspect and configure automated gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ <b>Access Denied:</b> Admin only.")

    start_gift_queue_worker(client)
    cfg = await get_auto_gift_config()
    q_count = 0
    try:
        q_count = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
    except Exception:
        pass
    text, markup = format_gift_settings_dashboard(cfg, q_count=q_count)
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
        curr = cfg.get("poster_mode", "sample")
        modes = ["sample", "ss", "thumb"]
        try:
            next_idx = (modes.index(curr) + 1) % len(modes)
        except ValueError:
            next_idx = 0
        new_mode = modes[next_idx]
        await save_auto_gift_config({"poster_mode": new_mode})
        mode_labels = {
            "sample": "SAMPLE (Cascade to SS/Card)",
            "ss": "SCREENSHOT (Cascade to Card)",
            "thumb": "THUMBNAIL (Direct)"
        }
        await query.answer(f"Mode set to {mode_labels.get(new_mode, new_mode.upper())}!")

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

    elif data == "agift_interval":
        curr = cfg.get("interval_seconds", 0)
        cycles = [0, 600, 900, 1800, 3600, 7200]
        try:
            next_idx = (cycles.index(curr) + 1) % len(cycles)
        except ValueError:
            next_idx = 0
        new_sec = cycles[next_idx]
        await save_auto_gift_config({"interval_seconds": new_sec})
        lbl = "Instant (0s)" if new_sec == 0 else (f"{new_sec // 3600} Hour(s)" if new_sec >= 3600 else f"{new_sec // 60}m")
        await query.answer(f"Pacing Interval set to {lbl}!")

    elif data == "agift_quiet":
        new_val = not cfg.get("quiet_hours_enabled", False)
        await save_auto_gift_config({"quiet_hours_enabled": new_val})
        await query.answer(f"Night Sleep Mode {'Enabled (12AM-8AM)' if new_val else 'Disabled (24/7)'}!")

    elif data == "agift_clean_prev":
        new_val = not cfg.get("clean_previous_post", False)
        await save_auto_gift_config({"clean_previous_post": new_val})
        await query.answer(f"Channel Clean Mode {'Enabled (Single Post)' if new_val else 'Disabled (Keep All)'}!")

    elif data == "agift_view_q":
        text, markup = await format_gift_queue_dashboard(cfg)
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_back_settings":
        q_count = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
        text, markup = format_gift_settings_dashboard(cfg, q_count=q_count)
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_next":
        next_item = await mongo.db["gift_post_queue"].find_one({"status": "queued"}, sort=[("queued_at", 1)])
        if not next_item:
            # Fallback to oldest failed item if admin manually triggers Post Next
            next_item = await mongo.db["gift_post_queue"].find_one({"status": "failed"}, sort=[("queued_at", 1)])

        if next_item:
            ok = await _dispatch_queued_gift(client, next_item, cfg)
            if ok:
                await mongo.db["gift_post_queue"].delete_one({"_id": next_item["_id"]})
                _LAST_GIFT_POST_TIMESTAMP = time.time()
                await query.answer(f"⚡ Dropped '{next_item.get('title')}' now!", show_alert=True)
            else:
                attempts = next_item.get("attempts", 0) + 1
                await mongo.db["gift_post_queue"].update_one(
                    {"_id": next_item["_id"]},
                    {"$set": {"status": "failed", "attempts": attempts}}
                )
                await query.answer("⚠️ Failed to post item. Check bot permissions in target channel.", show_alert=True)
        else:
            await query.answer("ℹ️ Queue is empty!", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_retry_failed":
        res = await mongo.db["gift_post_queue"].update_many(
            {"status": "failed"},
            {"$set": {"status": "queued", "attempts": 0}}
        )
        await query.answer(f"🔄 Reset {res.modified_count} failed drops to active queue!", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_clear_failed":
        res = await mongo.db["gift_post_queue"].delete_many({"status": "failed"})
        await query.answer(f"🗑️ Removed {res.deleted_count} failed drops!", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_toggle_quiet":
        curr_q = cfg.get("quiet_hours_enabled", False)
        await save_auto_gift_config({"quiet_hours_enabled": not curr_q})
        state_str = "Disabled (24/7 Drops)" if curr_q else "Enabled (Night Pause 12AM-8AM)"
        await query.answer(f"🌙 Night Sleep: {state_str}!", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_pause":
        await save_auto_gift_config({"queue_paused": True})
        await query.answer("⏸️ Queue Paused! Drip feed frozen.", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_resume":
        await save_auto_gift_config({"queue_paused": False})
        await query.answer("▶️ Queue Resumed! Drip feed active.", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_clear":
        res = await mongo.db["gift_post_queue"].delete_many({"status": "queued"})
        await query.answer(f"🧹 Cleared {res.deleted_count} queued posts!", show_alert=True)
        text, markup = await format_gift_queue_dashboard(await get_auto_gift_config())
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_q_refresh":
        await query.answer("🔄 Queue Refreshed!")
        text, markup = await format_gift_queue_dashboard(cfg)
        return await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)

    elif data == "agift_refresh":
        await query.answer("Dashboard Refreshed!")

    cfg = await get_auto_gift_config()
    q_count = 0
    try:
        q_count = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
    except Exception:
        pass
    text, markup = format_gift_settings_dashboard(cfg, q_count=q_count)
    try:
        await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


@Client.on_message(filters.command(["giftqueue", "agiftq", "giftq"]) & filters.private)
async def gift_queue_command(client: Client, message: Message):
    """Admin command to inspect and control the scheduled drip-feed gift queue."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")
    start_gift_queue_worker(client)
    cfg = await get_auto_gift_config()
    text, markup = await format_gift_queue_dashboard(cfg)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_message(filters.command(["giftretry", "retrygifts", "agiftretry"]) & filters.private)
async def gift_retry_command(client: Client, message: Message):
    """Admin command to recover any failed gift drops back to the active queue."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")
    res = await mongo.db["gift_post_queue"].update_many(
        {"status": "failed"},
        {"$set": {"status": "queued", "attempts": 0}}
    )
    start_gift_queue_worker(client)
    await message.reply_text(
        f"✅ <b>Queue Recovered:</b> <code>{res.modified_count}</code> failed gift drops have been reset back to <code>queued</code>!\n"
        f"⚡ <i>They will now be posted automatically according to the pacing interval.</i>",
        quote=True
    )


@Client.on_message(filters.command(["setgiftinterval", "setgiftbreak", "setgiftpace"]) & filters.private)
async def set_gift_interval_command(client: Client, message: Message):
    """Admin command to set time pacing interval for auto-gift drops (e.g. 15m, 30m, 1h, 0/off)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        cfg = await get_auto_gift_config()
        sec = cfg.get("interval_seconds", 0)
        cur = "OFF (Instant Drops)" if sec == 0 else (f"{sec // 3600} Hour(s)" if sec >= 3600 else f"{sec // 60} Minutes")
        return await message.reply_text(
            f"⏱️ <b>Auto-Gift Time Post / Interval Settings</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Current Interval:</b> <code>{cur}</code>\n\n"
            f"<b>Usage:</b>\n"
            f"• <code>/setgiftinterval 15m</code> — Post 1 gift every 15 minutes\n"
            f"• <code>/setgiftinterval 30m</code> — Post 1 gift every 30 minutes\n"
            f"• <code>/setgiftinterval 1h</code> — Post 1 gift every 1 hour\n"
            f"• <code>/setgiftinterval 0</code> or <code>off</code> — Instant posting (no delay)\n\n"
            f"💡 <i>When enabled, you can dump 500 videos into your DB channel. The bot will queue them and post one-by-one smoothly!</i>"
        )

    val = args[1].strip().lower()
    if val in ["0", "off", "disable", "instant"]:
        await save_auto_gift_config({"interval_seconds": 0})
        return await message.reply_text("✅ <b>Interval Disabled!</b> Gifts will now be posted immediately upon upload.")

    sec = 0
    if val.endswith("h"):
        h_str = val[:-1].strip()
        if h_str.isdigit():
            sec = int(h_str) * 3600
    elif val.endswith("m"):
        m_str = val[:-1].strip()
        if m_str.isdigit():
            sec = int(m_str) * 60
    elif val.endswith("s"):
        s_str = val[:-1].strip()
        if s_str.isdigit():
            sec = int(s_str)
    elif val.isdigit():
        v_num = int(val)
        sec = v_num * 60 if v_num < 100 else v_num

    if sec < 60:
        return await message.reply_text("❌ Please enter a valid interval of at least 1 minute (e.g. <code>15m</code>, <code>30m</code>, <code>1h</code>, or <code>off</code>).")

    await save_auto_gift_config({"interval_seconds": sec})
    label = f"{sec // 3600} Hour(s)" if sec >= 3600 else f"{sec // 60} Minutes"
    await message.reply_text(
        f"✅ <b>Auto-Gift Pacing Interval Updated!</b>\n\n"
        f"• <b>New Interval:</b> <code>{label}</code>\n"
        f"• You can now dump bulk videos into your DB channel.\n"
        f"• Bot will buffer them in queue and publish 1 drop every <b>{label}</b>.\n"
        f"• Check queue status anytime with <code>/giftqueue</code>!"
    )


@Client.on_message(filters.command(["setgiftquiet", "setgiftnight"]) & filters.private)
async def set_gift_quiet_command(client: Client, message: Message):
    """Admin command to toggle night quiet hours (12 AM to 8 AM IST) for gift drops."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        cfg = await get_auto_gift_config()
        cur = "ON (12 AM - 8 AM Pause)" if cfg.get("quiet_hours_enabled") else "OFF (24/7 Drip Feed)"
        return await message.reply_text(
            f"🌙 <b>Auto-Gift Night Sleep Mode</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Current Status:</b> <code>{cur}</code>\n\n"
            f"<b>Usage:</b>\n"
            f"• <code>/setgiftquiet on</code> — Pause posting between 12 AM and 8 AM IST\n"
            f"• <code>/setgiftquiet off</code> — Allow posting 24/7\n\n"
            f"💡 <i>Prevents disturbing sleeping subscribers at night. Posts queue up and resume in morning!</i>"
        )

    val = args[1].strip().lower()
    enable = val in ["on", "enable", "true", "yes", "1"]
    await save_auto_gift_config({"quiet_hours_enabled": enable})
    await message.reply_text(
        f"✅ <b>Night Sleep Mode {'Enabled' if enable else 'Disabled'}!</b>\n"
        f"• Status: <code>{'🌙 ON (12 AM - 8 AM IST Pause)' if enable else '☀️ OFF (24/7 Drip Feed)'}</code>"
    )


@Client.on_message(filters.command(["setgiftclean", "setgiftcleanpost"]) & filters.private)
async def set_gift_clean_command(client: Client, message: Message):
    """Admin command to toggle channel clean mode (auto-deleting previous gift post in channel)."""
    if not Config.is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admin only.")

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        cfg = await get_auto_gift_config()
        cur = "ON (Single active drop)" if cfg.get("clean_previous_post") else "OFF (Keep all posts)"
        return await message.reply_text(
            f"🧹 <b>Auto-Gift Clean Channel Mode</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Current Status:</b> <code>{cur}</code>\n\n"
            f"<b>Usage:</b>\n"
            f"• <code>/setgiftclean on</code> — Auto-delete previous gift post when new one drops\n"
            f"• <code>/setgiftclean off</code> — Keep all gift posts in channel history\n\n"
            f"💡 <i>Keep your channel clean so subscribers only see the latest active drops!</i>"
        )

    val = args[1].strip().lower()
    enable = val in ["on", "enable", "true", "yes", "1"]
    await save_auto_gift_config({"clean_previous_post": enable})
    await message.reply_text(
        f"✅ <b>Clean Channel Mode {'Enabled' if enable else 'Disabled'}!</b>\n"
        f"• Status: <code>{'🧹 ON (Single active drop)' if enable else '📜 OFF (Keep all posts)'}</code>"
    )


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
    sec = max(0, min(60, sec))
    await save_auto_gift_config({"ad_wait_seconds": sec})
    wait_note = "Instant Verification (No wait)" if sec == 0 else f"{sec} Seconds"
    await message.reply_text(f"✅ <b>Sponsor Ad Anti-Cheat Timer Set to:</b> <code>{wait_note}</code>")




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

    # Safety Guard: Never trigger auto-gift in main movie storage channels!
    try:
        from database.channels import is_storage_channel
        if await is_storage_channel(chat_id):
            logger.warning(f"Channel {chat_id} is registered as a Main Movie Storage channel! Skipping auto-gift to prevent mixing.")
            return
    except Exception:
        pass

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

    from utils.helpers import parse_media_metadata, get_readable_size
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

    temp_dir = tempfile.mkdtemp(prefix="autogift_")
    try:
        photo_id = pending_info.get("photo_id")

        # Step 2: Poster & Sample Video Resolution Hierarchy
        # Priority 1: Sample Video (2-4s preview clip)
        # Priority 2: HD Screenshot (Frame extracted from video)
        # Priority 3: Native Thumbnail / Card Poster
        poster_photo = None
        sample_video_path = None
        mode = cfg.get("poster_mode", "sample")

        if photo_id:
            # Priority 0: Admin explicitly replied with a custom photo
            poster_photo = photo_id
        else:
            async with _GIFT_PROCESS_LOCK:
                # Baseline: Download native media thumbnail first
                thumb_local = None
                if hasattr(media, "thumbs") and media.thumbs:
                    try:
                        t_path = os.path.join(temp_dir, f"thumb_{message.id}.jpg")
                        target_thumb = media.thumbs[0]
                        downloaded_t = None
                        try:
                            downloaded_t = await asyncio.wait_for(
                                client.download_media(target_thumb, file_name=t_path),
                                timeout=15.0
                            )
                        except Exception:
                            pass
                        if not downloaded_t and hasattr(target_thumb, "file_id"):
                            try:
                                downloaded_t = await asyncio.wait_for(
                                    client.download_media(target_thumb.file_id, file_name=t_path),
                                    timeout=15.0
                                )
                            except Exception:
                                pass
                        if downloaded_t and os.path.exists(downloaded_t):
                            from plugins.screenshots import apply_watermark
                            watermark = getattr(Config, "DEFAULT_POSTER_BRAND", "@AkMovieVerse") or "@AkMovieVerse"
                            apply_watermark(downloaded_t, watermark_text=watermark)
                            thumb_local = downloaded_t
                    except Exception as e_th:
                        logger.debug(f"Media thumbnail download skipped: {e_th}")

                # Support videos up to 350 MB for local sample & screenshot generation
                max_media_bytes = 350 * 1024 * 1024
                video_local = None

                async def _download_video_once():
                    nonlocal video_local
                    if video_local and os.path.exists(video_local):
                        return video_local
                    if file_size <= max_media_bytes:
                        v_path = os.path.join(temp_dir, file_name)
                        # Adaptive timeout: 150s to 360s based on file size (~1MB/s MTProto rate)
                        dl_timeout = max(150.0, min(360.0, (file_size / (1024 * 1024)) * 2.0))
                        video_local = await asyncio.wait_for(
                            client.download_media(message, file_name=v_path),
                            timeout=dl_timeout
                        )
                        return video_local
                    return None

                # Priority 1: Try sample video if mode is 'sample' (default)
                if mode == "sample":
                    try:
                        if file_size <= max_media_bytes:
                            if pending_info.get("status_msg"):
                                try:
                                    await pending_info["status_msg"].edit_text("⚙️ 🎬 <b>Extracting 3s sample video preview...</b>")
                                except Exception:
                                    pass

                            v_file = await _download_video_once()
                            if v_file and os.path.exists(v_file):
                                from plugins.screenshots import get_video_duration
                                duration = getattr(media, "duration", 0) or await get_video_duration(v_file)
                                if duration <= 2:
                                    duration = 10.0
                                start_sec = max(0.5, min(duration * 0.2, max(0.5, duration - 3.5))) if duration > 3.0 else 0.0

                                s_path = os.path.join(temp_dir, "sample_preview.mp4")
                                if await extract_sample_clip_ffmpeg(v_file, start_sec, 3, s_path):
                                    sample_video_path = s_path
                                    logger.info(f"Sample video clip generated successfully for {file_name}")
                    except Exception as e_proc:
                        logger.warning(f"Auto-gift sample video extraction failed: {e_proc}")

                # Priority 2: Try HD Screenshot (SS) if no sample generated (or if mode is 'ss')
                if not sample_video_path and mode in ("sample", "ss"):
                    try:
                        if pending_info.get("status_msg"):
                            try:
                                await pending_info["status_msg"].edit_text("⚙️ 📸 <b>Extracting HD screenshot frame...</b>")
                            except Exception:
                                pass

                        v_file = await _download_video_once()
                        if v_file and os.path.exists(v_file):
                            from plugins.screenshots import extract_frame_ffmpeg, apply_watermark, get_video_duration
                            duration = getattr(media, "duration", 0) or await get_video_duration(v_file)
                            if duration <= 2:
                                duration = 10.0
                            start_sec = max(0.5, min(duration * 0.2, max(0.5, duration - 3.5))) if duration > 3.0 else 0.0
                            f_path = os.path.join(temp_dir, "screenshot.jpg")
                            if await extract_frame_ffmpeg(v_file, start_sec, f_path):
                                watermark = getattr(Config, "DEFAULT_POSTER_BRAND", "@AkMovieVerse") or "@AkMovieVerse"
                                apply_watermark(f_path, watermark_text=watermark)
                                poster_photo = f_path
                                logger.info(f"HD screenshot extracted successfully for {file_name}")
                    except Exception as e_proc:
                        logger.warning(f"Auto-gift frame extraction failed: {e_proc}")

                # Priority 3: Fallback Card / Native Thumbnail (NEVER TMDB for auto-gift drops)
                if not sample_video_path and not poster_photo:
                    if thumb_local:
                        poster_photo = thumb_local
                        if pending_info.get("status_msg"):
                            try:
                                await pending_info["status_msg"].edit_text("⚙️ 📸 <b>Applying high-definition poster...</b>")
                            except Exception:
                                pass
                    else:
                        from database.gifts import DEFAULT_GIFT_POSTER
                        poster_photo = DEFAULT_GIFT_POSTER

        # Step 3: Package file metadata for Gift Reward Engine (strictly isolated from search index)
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

        # Step 5: Route to Drip-Feed Queue or Post Immediately
        interval_sec = int(cfg.get("interval_seconds", 0))
        q_pending = 0
        try:
            q_pending = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
        except Exception:
            pass

        if interval_sec > 0 or q_pending > 0:
            queue_poster = poster_photo
            queue_sample = sample_video_path
            if isinstance(poster_photo, str) and os.path.exists(poster_photo):
                queue_asset_dir = os.path.join(os.getcwd(), "cache", "gift_queue")
                os.makedirs(queue_asset_dir, exist_ok=True)
                new_p = os.path.join(queue_asset_dir, f"{gift_id}_poster.jpg")
                try:
                    shutil.copy2(poster_photo, new_p)
                    queue_poster = new_p
                except Exception:
                    pass
            elif not (isinstance(poster_photo, str) and (poster_photo.startswith("http://") or poster_photo.startswith("https://"))):
                from database.gifts import DEFAULT_GIFT_POSTER
                queue_poster = DEFAULT_GIFT_POSTER

            if sample_video_path and os.path.exists(sample_video_path):
                queue_asset_dir = os.path.join(os.getcwd(), "cache", "gift_queue")
                os.makedirs(queue_asset_dir, exist_ok=True)
                new_v = os.path.join(queue_asset_dir, f"{gift_id}_sample.mp4")
                try:
                    shutil.copy2(sample_video_path, new_v)
                    queue_sample = new_v
                except Exception:
                    pass

            from database.gifts import DEFAULT_GIFT_POSTER
            queue_doc = {
                "gift_id": gift_id,
                "title": clean_title,
                "quality": quality,
                "file_size": file_size,
                "post_ch": post_ch,
                "poster_photo": queue_poster if queue_poster else DEFAULT_GIFT_POSTER,
                "sample_video_path": queue_sample,
                "caption_text": caption_text,
                "claim_url": claim_url,
                "post_btn": post_btn,
                "status": "queued",
                "queued_at": time.time(),
                "attempts": 0
            }
            await mongo.db["gift_post_queue"].insert_one(queue_doc)
            total_q = await mongo.db["gift_post_queue"].count_documents({"status": "queued"})
            est_mins = (total_q * interval_sec) // 60 if interval_sec > 0 else 0
            est_str = f"~{est_mins // 60}h {est_mins % 60}m" if est_mins >= 60 else f"~{est_mins} mins"

            int_lbl = f"{interval_sec // 3600}h" if interval_sec >= 3600 else f"{interval_sec // 60}m"
            final_text = (
                f"📥 <b>Added to Scheduled Auto-Gift Queue!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ <b>Title:</b> <code>{html.escape(clean_title)}</code>\n"
                f"📊 <b>Queue Position:</b> <code>#{total_q}</code>\n"
                f"⏱️ <b>Post Interval:</b> <code>{int_lbl}</code>\n"
                f"⏳ <b>Est. Drop Time:</b> <code>In {est_str}</code>\n"
                f"🎁 <b>Gift ID:</b> <code>{gift_id}</code>\n"
                f"🔗 <b>Claim Link:</b> {claim_url}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Will drop automatically to public channel in its turn!</i>"
            )

            try:
                if pending_info.get("status_msg"):
                    await pending_info["status_msg"].edit_text(final_text)
                else:
                    await message.reply_text(final_text, quote=True)
            except Exception:
                pass

            start_gift_queue_worker(client)
            return

        # Instant Drop Execution (when interval is 0 and queue is empty)
        sent_pub_msg = None
        # Tier 1: Try sample video if present
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

        # Tier 2: Try custom / local / cached poster
        if not sent_pub_msg and poster_photo:
            try:
                sent_pub_msg = await client.send_photo(
                    chat_id=post_ch,
                    photo=poster_photo,
                    caption=caption_text,
                    reply_markup=markup
                )
                logger.info(f"Auto-gift successfully published to {post_ch} (Gift ID: {gift_id})")
            except Exception as e_p:
                logger.warning(f"Sending poster photo failed: {e_p}, trying default poster")

        # Tier 3: Try official default high-resolution poster URL
        if not sent_pub_msg:
            from database.gifts import DEFAULT_GIFT_POSTER
            try:
                sent_pub_msg = await client.send_photo(
                    chat_id=post_ch,
                    photo=DEFAULT_GIFT_POSTER,
                    caption=caption_text,
                    reply_markup=markup
                )
            except Exception as e_def:
                logger.warning(f"Sending default poster failed: {e_def}, falling back to text")

        # Tier 4: Text-only drop with inline claim button
        if not sent_pub_msg:
            try:
                sent_pub_msg = await client.send_message(
                    chat_id=post_ch,
                    text=caption_text,
                    reply_markup=markup,
                    disable_web_page_preview=False
                )
            except Exception as e_txt:
                logger.error(f"Failed to publish auto-gift text drop to {post_ch}: {e_txt}")

        if sent_pub_msg:
            try:
                await mongo.db["gift_rewards"].update_one(
                    {"gift_id": gift_id},
                    {"$set": {"post_chat_id": post_ch, "post_msg_id": sent_pub_msg.id}}
                )
            except Exception:
                pass

            # Channel Clean Mode: Auto-delete previous active gift post
            if cfg.get("clean_previous_post", False):
                prev_id = cfg.get("last_posted_msg_id")
                if prev_id and prev_id != sent_pub_msg.id:
                    try:
                        await client.delete_messages(chat_id=post_ch, message_ids=[prev_id])
                        logger.info(f"Cleaned previous gift post msg {prev_id} from {post_ch}")
                    except Exception as e_del:
                        logger.debug(f"Could not delete previous gift post {prev_id}: {e_del}")

            await save_auto_gift_config({"last_posted_msg_id": sent_pub_msg.id})

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
    except Exception as e_worker:
        logger.error(f"Error in auto gift video worker: {e_worker}", exc_info=True)
        try:
            if pending_info.get("status_msg"):
                await pending_info["status_msg"].edit_text(
                    f"⚠️ <b>Auto-Gift Error:</b> <code>{html.escape(str(e_worker)[:120])}</code>"
                )
        except Exception:
            pass
    finally:
        _PENDING_GIFT_VIDEOS.pop(message.id, None)
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
