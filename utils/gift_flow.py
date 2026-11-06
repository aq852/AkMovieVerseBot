import asyncio
import datetime
import html
import logging
from typing import Optional

try:
    from hydrogram import Client
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from utils.helpers import get_readable_size, format_clean_title
from utils.shortener import get_shortlink
from database.users import is_premium
from database.gifts import (
    get_gift,
    record_gift_claim,
    has_user_claimed_gift,
    is_gift_banned,
    increment_gift_views,
    create_gift_task_token,
    is_gift_task_verified
)
from database.batches import get_batch
from database.files import get_file_by_id

logger = logging.getLogger(__name__)


async def check_channel_membership(client: Client, user_id: int, channel_identifier: str) -> tuple[bool, str, str]:
    """Check if user has joined a required channel.
    Returns (is_member, channel_display_title, channel_invite_url).
    """
    clean_ch = channel_identifier.strip()
    invite_url = f"https://t.me/{clean_ch[1:]}" if clean_ch.startswith("@") else clean_ch

    display_title = clean_ch
    try:
        chat = await client.get_chat(clean_ch)
        if chat.title:
            display_title = chat.title
        if chat.username:
            invite_url = f"https://t.me/{chat.username}"
        elif getattr(chat, "invite_link", None):
            invite_url = chat.invite_link
    except Exception as e:
        logger.debug(f"Could not fetch chat info for {clean_ch}: {e}")

    # Check member status
    try:
        member = await client.get_chat_member(clean_ch, user_id)
        status_val = str(getattr(member, "status", "")).lower()
        if "left" in status_val or "banned" in status_val or "kicked" in status_val:
            return False, display_title, invite_url
        return True, display_title, invite_url
    except Exception as e:
        logger.debug(f"User {user_id} not in channel {clean_ch}: {e}")
        return False, display_title, invite_url


async def deliver_gift_content(client: Client, user_id: int, gift: dict) -> None:
    """Deliver single file or batch files with custom protection and self-destruct timer."""
    from plugins.start import deliver_file_with_copyright_warning, auto_delete_messages

    file_type = gift.get("file_type", "single")
    protect_flag = gift.get("protect_content", True)
    auto_del_sec = gift.get("auto_delete_seconds", 300)
    del_mins = auto_del_sec // 60
    del_label = f"{del_mins} MINUTE" if del_mins == 1 else f"{del_mins} MINUTES"
    if del_mins == 0:
        del_label = f"{auto_del_sec} SECONDS"

    title = gift.get("title", "Exclusive Reward")
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    # 1. Delivery header banner
    celebration_msg = await client.send_message(
        chat_id=user_id,
        text=(
            "🎉 <b>CONGRATULATIONS! REWARD UNLOCKED!</b> 🎁\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Package:</b> <code>{html.escape(title)}</code>\n"
            f"⏳ <b>Self-Destruct:</b> <code>Auto-Deletes in {del_label}</code>\n"
            f"🔒 <b>Content Protection:</b> <code>{'Active (No Forward)' if protect_flag else 'Disabled'}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>Delivering your files below. Enjoy your exclusive reward!</i>"
        )
    )

    delivered_msgs = [celebration_msg]

    if file_type == "single":
        file_doc = gift.get("file_doc") or {}
        fid = file_doc.get("file_id")
        if not fid and file_doc.get("file_unique_id"):
            db_doc = await get_file_by_id(file_doc["file_unique_id"])
            if db_doc:
                file_doc = db_doc
                fid = db_doc.get("file_id")

        if fid:
            try:
                caption = (
                    f"🎁 <b>{html.escape(format_clean_title(file_doc.get('file_name', title)))}</b>\n\n"
                    f"⏳ <i>Auto-Deletes in {del_label} for copyright protection.</i>"
                )
                msg = await client.send_cached_media(
                    chat_id=user_id,
                    file_id=fid,
                    caption=caption,
                    protect_content=protect_flag
                )
                delivered_msgs.append(msg)
            except Exception as e:
                logger.warning(f"Failed to send cached gift media: {e}. Falling back to deliver_file...")
                await deliver_file_with_copyright_warning(
                    client=client,
                    user_id=user_id,
                    file_doc=file_doc,
                    custom_protect=protect_flag,
                    is_protected_viewing=False
                )

    elif file_type == "batch":
        batch_id = gift.get("batch_id")
        batch = await get_batch(batch_id) if batch_id else None
        files = batch.get("files", []) if batch else []

        for f_item in files:
            fid = f_item.get("file_id")
            if fid:
                try:
                    f_name = html.escape(format_clean_title(f_item.get("file_name", "Reward File")))
                    msg = await client.send_cached_media(
                        chat_id=user_id,
                        file_id=fid,
                        caption=f"🎁 <b>{f_name}</b>\n\n⏳ <i>Auto-deletes in {del_label}</i>",
                        protect_content=protect_flag
                    )
                    delivered_msgs.append(msg)
                    await asyncio.sleep(0.4)
                except Exception as send_err:
                    logger.debug(f"Error sending batch gift file {f_item.get('file_name')}: {send_err}")

    # Schedule gift auto-deletion
    if auto_del_sec > 0:
        asyncio.create_task(
            auto_delete_messages(
                messages=delivered_msgs,
                delay=auto_del_sec,
                clean_name=title,
                bot_username=bot_uname
            )
        )


async def render_gift_page(
    client: Client,
    user_id: int,
    gift_id: str,
    target_message: Optional[Message] = None,
    callback_query: Optional[CallbackQuery] = None
) -> None:
    """Evaluate gift eligibility, check tasks live, and deliver reward or present checklist card."""
    # 1. Blacklist Check
    if await is_gift_banned(user_id):
        alert_text = (
            "⛔ <b>Access Restricted</b>\n\n"
            "You have been blacklisted from claiming gift rewards due to rule violations (leaving sponsor channels).\n\n"
            "If you believe this is an error, please contact bot support."
        )
        if callback_query:
            return await callback_query.answer("⛔ You are blacklisted from claiming gifts.", show_alert=True)
        if target_message:
            return await target_message.reply_text(alert_text)
        return

    # 2. Fetch Gift Campaign
    gift = await get_gift(gift_id)
    if not gift:
        not_found = "❌ <b>Gift reward not found or link is invalid.</b>"
        if callback_query:
            return await callback_query.answer("❌ Gift not found.", show_alert=True)
        if target_message:
            return await target_message.reply_text(not_found)
        return

    # 3. Active / Expiry Check
    now = datetime.datetime.utcnow()
    expires_at = gift.get("expires_at")
    if not gift.get("is_active") or (expires_at and expires_at < now):
        exp_text = (
            "⏳ <b>THIS GIFT REWARD HAS EXPIRED!</b>\n\n"
            "This limited promotional drop has already ended.\n"
            "Keep notifications ON in our updates channel for future exclusive drops!"
        )
        if callback_query:
            return await callback_query.answer("⏳ This gift has expired.", show_alert=True)
        if target_message:
            return await target_message.reply_text(exp_text)
        return

    # 4. VIP Only Check
    user_is_vip = await is_premium(user_id) or Config.is_admin(user_id)
    if gift.get("is_vip_only") and not user_is_vip:
        bot_uname = client.me.username if client.me else Config.BOT_USERNAME
        vip_locked_text = (
            "👑 <b>VIP EXCLUSIVE REWARD BOX</b> 👑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 <b>Access Locked:</b> This gift drop is strictly reserved for <b>AkMovieVerse VIP Members</b>!\n\n"
            "💎 <i>Upgrade your account to VIP today to claim this reward and enjoy 100% ad-free instant downloads across the bot!</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎟️ UPGRADE TO VIP NOW ↗️", url=f"https://t.me/{bot_uname}?start=plans")]
        ])
        if callback_query:
            return await callback_query.answer("👑 VIP Exclusive Reward! Upgrade to claim.", show_alert=True)
        if target_message:
            return await target_message.reply_text(vip_locked_text, reply_markup=markup)
        return

    # 5. One-Claim Per User Check
    if await has_user_claimed_gift(gift_id, user_id):
        already_claimed = (
            "⚠️ <b>REWARD ALREADY CLAIMED!</b>\n\n"
            "You have already claimed this gift reward once.\n"
            "In accordance with our anti-abuse policy, only 1 claim per account is permitted."
        )
        if callback_query:
            return await callback_query.answer("⚠️ You have already claimed this gift reward!", show_alert=True)
        if target_message:
            return await target_message.reply_text(already_claimed)
        return

    # 6. Max Stock Exhaustion Check
    max_c = gift.get("max_claims", 0)
    claimed = gift.get("claimed_count", 0)
    if max_c > 0 and claimed >= max_c:
        exhausted = (
            "🚫 <b>GIFT REWARD EXHAUSTED!</b>\n\n"
            f"All <b>{max_c}</b> gifts in this drop have already been claimed by lucky users! 🔥\n\n"
            "Stay tuned in our updates channel for the next exclusive drop."
        )
        if callback_query:
            return await callback_query.answer("🚫 All gifts have been claimed!", show_alert=True)
        if target_message:
            return await target_message.reply_text(exhausted)
        return

    # Increment view counter
    await increment_gift_views(gift_id)

    # 7. Evaluate Tasks
    channels = gift.get("channels", [])
    channel_status = []  # list of (is_member, title, url)
    all_channels_done = True

    for ch in channels:
        is_mem, title, url = await check_channel_membership(client, user_id, ch)
        channel_status.append((is_mem, title, url))
        if not is_mem:
            all_channels_done = False

    # Shortener Task
    require_shortener = gift.get("require_shortener", False)
    shortener_done = True
    if require_shortener:
        shortener_done = await is_gift_task_verified(gift_id, user_id, "shortener")

    # If VIP user, tasks are automatically waived (VIP Perk)
    if user_is_vip:
        all_channels_done = True
        shortener_done = True

    # ==========================================================================
    # CASE A: ALL TASKS COMPLETED -> DELIVER REWARD!
    # ==========================================================================
    if all_channels_done and shortener_done:
        success, reason = await record_gift_claim(gift_id, user_id)
        if not success:
            if callback_query:
                return await callback_query.answer(f"❌ {reason}", show_alert=True)
            if target_message:
                return await target_message.reply_text(f"❌ <b>Error:</b> {reason}")
            return

        if callback_query:
            await callback_query.answer("🎉 Tasks verified! Unlocking your reward now...", show_alert=False)
            try:
                await callback_query.message.delete()
            except Exception:
                pass

        await deliver_gift_content(client, user_id, gift)
        return

    # ==========================================================================
    # CASE B: INCOMPLETE TASKS -> SHOW INTERACTIVE CHECKLIST CARD
    # ==========================================================================
    if callback_query:
        await callback_query.answer("❌ Please complete all tasks above first!", show_alert=True)

    if max_c > 0:
        pct = int((claimed / max_c * 100))
        stock_line = f"👥 <b>Stock:</b> <code>{claimed}/{max_c} Claimed ({pct}%)</code>"
        rem_line = f"🔥 <b>Remaining:</b> <code>{max(0, max_c - claimed)} Left!</code>"
    else:
        stock_line = f"👥 <b>Stock:</b> <code>{claimed} Claimed (Unlimited Stock)</code>"
        rem_line = "🔥 <b>Remaining:</b> <code>Unlimited (Open for Everyone!)</code>"

    auto_del_sec = gift.get("auto_delete_seconds", 300)
    del_mins = auto_del_sec // 60
    del_str = f"{del_mins} Minute(s)" if del_mins > 0 else f"{auto_del_sec}s"

    card_lines = [
        "🎁 <b>EXCLUSIVE REWARD BOX UNLOCKED!</b> 🎁",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>Reward:</b> <code>{html.escape(gift.get('title', 'Exclusive Reward'))}</code>",
        stock_line,
        rem_line,
        f"⏳ <b>Self-Destruct:</b> <code>Auto-Deletes in {del_str}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "👉 <b>Complete the quick tasks below to unlock your reward:</b>\n"
    ]

    button_rows = []

    # Channel rows
    for idx, (is_mem, title, url) in enumerate(channel_status, start=1):
        tick = "✅" if is_mem else "❌"
        status_txt = "Joined" if is_mem else "Not Joined"
        card_lines.append(f"{tick} <b>Task {idx}:</b> Join <code>{html.escape(title)}</code> ({status_txt})")

        if not is_mem:
            button_rows.append([
                InlineKeyboardButton(f"📢 Join {title[:20]} ↗️", url=url)
            ])

    # Shortener row
    if require_shortener:
        idx = len(channel_status) + 1
        tick = "✅" if shortener_done else "❌"
        status_txt = "Verified" if shortener_done else "Incomplete"
        card_lines.append(f"{tick} <b>Task {idx}:</b> Complete 1-Time Ad Bypass ({status_txt})")

        if not shortener_done:
            bot_uname = client.me.username if client.me else Config.BOT_USERNAME
            token = await create_gift_task_token(gift_id, user_id, "shortener")
            target_url = f"https://t.me/{bot_uname}?start=vgtok_{token}"
            short_link = await get_shortlink(target_url)
            button_rows.append([
                InlineKeyboardButton("🔑 Complete Ad/Shortener Task ↗️", url=short_link)
            ])

    card_lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    card_lines.append("💡 <i>After completing tasks, tap the button below to claim!</i>")

    # Claim verification button
    button_rows.append([
        InlineKeyboardButton("🔄 Verify & Claim Reward 🎁", callback_data=f"claimgift_{gift_id}")
    ])

    markup = InlineKeyboardMarkup(button_rows)
    card_text = "\n".join(card_lines)

    poster = gift.get("poster_url")
    if target_message:
        if poster:
            try:
                return await target_message.reply_photo(photo=poster, caption=card_text, reply_markup=markup)
            except Exception:
                pass
        await target_message.reply_text(card_text, reply_markup=markup, disable_web_page_preview=True)
    elif callback_query:
        try:
            if callback_query.message.photo:
                await callback_query.message.edit_caption(caption=card_text, reply_markup=markup)
            else:
                await callback_query.message.edit_text(card_text, reply_markup=markup, disable_web_page_preview=True)
        except Exception as edit_err:
            logger.debug(f"Could not edit gift message: {edit_err}")
