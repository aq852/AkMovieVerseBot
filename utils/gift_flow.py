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
    """Check if user has joined a required public or private channel.
    Supports @username, numeric ID (-100...), invite links (t.me/+...), and ID | invite_link syntax.
    Returns (is_member, channel_display_title, channel_invite_url).
    """
    raw_str = str(channel_identifier).strip().strip("<>\"\'[]() ")
    custom_invite = ""
    clean_ch = raw_str
    if "|" in raw_str:
        parts = raw_str.split("|", 1)
        clean_ch = parts[0].strip().strip("<>\"\'[]() ")
        custom_invite = parts[1].strip().strip("<>\"\'[]() ")

    # Determine chat target (int for numeric IDs, str for @username or invite link)
    if clean_ch.lstrip("-").isdigit():
        chat_target = int(clean_ch)
    else:
        chat_target = clean_ch

    invite_url = custom_invite
    if not invite_url:
        if str(clean_ch).startswith("@"):
            invite_url = f"https://t.me/{clean_ch[1:]}"
        elif str(clean_ch).startswith("http://") or str(clean_ch).startswith("https://") or str(clean_ch).startswith("t.me/"):
            invite_url = str(clean_ch) if str(clean_ch).startswith("http") else f"https://{clean_ch}"
        else:
            invite_url = str(clean_ch)

    display_title = str(clean_ch)
    real_chat_id = chat_target

    try:
        chat = await client.get_chat(chat_target)
        if chat:
            real_chat_id = chat.id  # CRITICAL: Always use the resolved integer chat.id for membership lookup
            if chat.title:
                display_title = chat.title
            if not custom_invite:
                if chat.username:
                    invite_url = f"https://t.me/{chat.username}"
                elif getattr(chat, "invite_link", None):
                    invite_url = chat.invite_link
                else:
                    try:
                        invite_obj = await client.create_chat_invite_link(real_chat_id)
                        if invite_obj and invite_obj.invite_link:
                            invite_url = invite_obj.invite_link
                    except Exception as e_inv:
                        logger.debug(f"Could not create invite link for {real_chat_id}: {e_inv}")
    except Exception as e_chat:
        logger.debug(f"Could not fetch chat info for {chat_target}: {e_chat}")

    # Ensure invite_url is a valid web link if target was numeric
    if not invite_url.startswith("http://") and not invite_url.startswith("https://"):
        if str(real_chat_id).startswith("-100"):
            invite_url = f"https://t.me/c/{str(real_chat_id).replace('-100', '')}"
        elif str(clean_ch).startswith("@"):
            invite_url = f"https://t.me/{clean_ch[1:]}"

    # Check member status using real_chat_id
    try:
        member = await client.get_chat_member(real_chat_id, user_id)
        status_val = str(getattr(member, "status", "")).lower()
        if "left" in status_val or "banned" in status_val or "kicked" in status_val:
            return False, display_title, invite_url
        return True, display_title, invite_url
    except Exception as e_mem:
        logger.warning(f"check_channel_membership check failed for user {user_id} in {real_chat_id} ({display_title}): {e_mem}")
        return False, display_title, invite_url


async def deliver_gift_content(client: Client, user_id: int, gift: dict, is_redownload: bool = False) -> None:
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

    # Direct Media Delivery (No redundant header text spam)
    delivered_msgs = []

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

    # 5. One-Claim vs Smart Hybrid Re-Download Check
    if await has_user_claimed_gift(gift_id, user_id):
        allow_reclaim = gift.get("allow_reclaim", True)
        if not allow_reclaim:
            already_claimed = (
                "⚠️ <b>REWARD ALREADY CLAIMED!</b>\n\n"
                "You have already claimed this gift reward once.\n"
                "In accordance with strict campaign rules, only 1 claim per account is permitted."
            )
            if callback_query:
                return await callback_query.answer("⚠️ You have already claimed this gift reward!", show_alert=True)
            if target_message:
                return await target_message.reply_text(already_claimed)
            return

        # Smart Hybrid Re-Download: Live Anti-Leave Shield Check
        channels = gift.get("channels", [])
        missing_channels = []
        user_is_vip = await is_premium(user_id) or Config.is_admin(user_id)

        if not user_is_vip:
            for ch in channels:
                is_mem, title, url = await check_channel_membership(client, user_id, ch)
                if not is_mem:
                    missing_channels.append((title, url))

        if missing_channels:
            # User left sponsor channels! Block re-download until they re-join!
            bot_uname = client.me.username if client.me else Config.BOT_USERNAME
            buttons = []
            for ch_title, ch_url in missing_channels:
                buttons.append([InlineKeyboardButton(f"📢 Re-Join: {ch_title} ↗️", url=ch_url)])
            buttons.append([
                InlineKeyboardButton("🔄 Verify Membership & Re-Download ↗️", url=f"https://t.me/{bot_uname}?start=gift_{gift_id}")
            ])
            rejoin_text = (
                "⚠️ <b>RE-DOWNLOAD LOCKED • CHANNEL MEMBERSHIP REQUIRED</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>You previously unlocked this reward, but you have left one or more required sponsor channels!</i>\n\n"
                "🔒 <b>Active channel membership is required</b> to re-access and stream/download this drop.\n\n"
                "👉 <i>Please re-join the channel(s) below and click Verify to receive your file again:</i>"
            )
            markup = InlineKeyboardMarkup(buttons)
            if callback_query:
                return await callback_query.message.edit_text(rejoin_text, reply_markup=markup, disable_web_page_preview=True)
            if target_message:
                return await target_message.reply_text(rejoin_text, reply_markup=markup, disable_web_page_preview=True)
            return

        # Verified! Deliver re-download with counter increment
        from database.gifts import record_gift_redownload
        await record_gift_redownload(gift_id, user_id)

        if callback_query:
            await callback_query.answer("♻️ Active membership verified! Re-delivering file...", show_alert=False)
            try:
                await callback_query.message.delete()
            except Exception:
                pass

        await deliver_gift_content(client, user_id, gift, is_redownload=True)
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
    from database.mongo import mongo
    from database.gifts import get_or_set_gift_initial_invites

    # A. Channels Task (Public & Private)
    channels = gift.get("channels", [])
    channel_status = []  # list of (is_member, title, url)
    all_channels_done = True

    for ch in channels:
        is_mem, title, url = await check_channel_membership(client, user_id, ch)
        channel_status.append((is_mem, title, url))
        if not is_mem:
            all_channels_done = False

    # B. Shortener Task
    require_shortener = gift.get("require_shortener", False)
    shortener_done = True
    if require_shortener:
        shortener_done = await is_gift_task_verified(gift_id, user_id, "shortener")

    # C. External Link Tasks (YouTube, Instagram, Website)
    external_links = gift.get("external_links", [])
    ext_status = []  # list of (is_done, title, url, type, token)
    all_ext_done = True
    for idx, ext in enumerate(external_links, start=1):
        is_done = await is_gift_task_verified(gift_id, user_id, f"extlink_{idx}")
        token = ""
        if not is_done:
            all_ext_done = False
            token = await create_gift_task_token(gift_id, user_id, task_type=f"extlink_{idx}", target_url=ext.get("url", ""))
        ext_status.append((is_done, ext.get("title", "Visit Link"), ext.get("url", ""), ext.get("type", "web"), token))

    # D. Referral Invite Task
    required_invites = gift.get("required_invites", 0)
    invites_done = True
    new_invites = 0
    if required_invites > 0:
        user_doc = await mongo.users.find_one({"user_id": user_id}) or {}
        curr_refer_count = user_doc.get("refer_count", 0)
        initial_invites = await get_or_set_gift_initial_invites(gift_id, user_id, curr_refer_count)
        new_invites = max(0, curr_refer_count - initial_invites)
        if new_invites < required_invites:
            invites_done = False

    # E. Sponsored Ad Tasks (Multi-Ad Support with Anti-Cheat Wait Timer)
    raw_ad_links = gift.get("ad_links") or ([gift["ad_link"]] if gift.get("ad_link") else [])
    ad_links = [str(u).strip() for u in raw_ad_links if str(u).strip().startswith("http")]
    ad_wait_sec = gift.get("ad_wait_seconds", 3)
    ad_tasks_status = []  # list of (idx, is_done, token, ad_url)
    all_ads_done = True

    for a_idx, a_url in enumerate(ad_links, start=1):
        a_task_type = f"ad_task_{a_idx}" if len(ad_links) > 1 else "ad_task"
        is_a_done = await is_gift_task_verified(gift_id, user_id, a_task_type)
        a_token = ""
        if not is_a_done:
            all_ads_done = False
            tok_doc = await mongo.db["gift_task_tokens"].find_one({
                "gift_id": gift_id,
                "user_id": user_id,
                "task_type": a_task_type
            })
            if not tok_doc:
                a_token = await create_gift_task_token(
                    gift_id, user_id, task_type=a_task_type, target_url=a_url, ad_wait_seconds=ad_wait_sec
                )
            else:
                a_token = tok_doc["token"]
                if callback_query:
                    clicked_at = tok_doc.get("clicked_at")
                    if not clicked_at:
                        label = f"Sponsor Offer #{a_idx}" if len(ad_links) > 1 else "the Sponsor Offer"
                        return await callback_query.answer(
                            f"❌ Please tap '{label}' first!",
                            show_alert=True
                        )
                    elapsed = (datetime.datetime.utcnow() - clicked_at).total_seconds()
                    if elapsed < ad_wait_sec:
                        rem = int(ad_wait_sec - elapsed) + 1
                        label = f"Sponsor Offer #{a_idx}" if len(ad_links) > 1 else "the sponsor page"
                        return await callback_query.answer(
                            f"⏳ Please stay on {label} for at least {ad_wait_sec}s!\n(Wait {rem}s more before verifying)",
                            show_alert=True
                        )
                    else:
                        await mongo.db["gift_task_tokens"].update_one(
                            {"_id": tok_doc["_id"]},
                            {"$set": {"is_verified": True, "verified_at": datetime.datetime.utcnow()}}
                        )
                        is_a_done = True
        ad_tasks_status.append((a_idx, is_a_done, a_token, a_url))

    if len(ad_tasks_status) > 0 and all(st[1] for st in ad_tasks_status):
        all_ads_done = True

    # If VIP user, all tasks are automatically waived (VIP Perk)
    if user_is_vip:
        all_channels_done = True
        shortener_done = True
        all_ext_done = True
        invites_done = True
        all_ads_done = True

    # ==========================================================================
    # CASE A: ALL TASKS COMPLETED -> DELIVER REWARD!
    # ==========================================================================
    if all_channels_done and shortener_done and all_ext_done and invites_done and all_ads_done:
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
    task_num = 1
    bot_uname = client.me.username if client.me else Config.BOT_USERNAME

    # 1. Channel rows (Public & Private)
    for idx, (is_mem, title, url) in enumerate(channel_status, start=1):
        tick = "✅" if is_mem else "❌"
        status_txt = "Joined" if is_mem else "Not Joined"
        card_lines.append(f"{tick} <b>Task {task_num}:</b> Join <code>{html.escape(title)}</code> ({status_txt})")
        task_num += 1

        if not is_mem:
            button_rows.append([
                InlineKeyboardButton(f"📢 Join {title[:22]} ↗️", url=url)
            ])

    # 2. External Link Tasks (YouTube, Instagram, Website)
    for is_done, ext_title, ext_url, ext_type, token in ext_status:
        tick = "✅" if is_done else "❌"
        status_txt = "Verified" if is_done else "Pending"
        card_lines.append(f"{tick} <b>Task {task_num}:</b> {ext_title} ({status_txt})")
        task_num += 1

        if not is_done:
            icon = "🔴" if ext_type == "youtube" else ("📸" if ext_type == "instagram" else "🌐")
            visit_url = f"https://t.me/{bot_uname}?start=vgtok_{token}" if token else ext_url
            button_rows.append([
                InlineKeyboardButton(f"{icon} {ext_title[:24]} ↗️", url=visit_url)
            ])

    # 3. Referral Invite Task
    if required_invites > 0:
        tick = "✅" if invites_done else "❌"
        status_txt = f"{new_invites}/{required_invites} Invited"
        card_lines.append(f"{tick} <b>Task {task_num}:</b> Invite {required_invites} Friend(s) to Bot ({status_txt})")
        task_num += 1

        if not invites_done:
            import urllib.parse
            refer_link = f"https://t.me/{bot_uname}?start=refer_{user_id}"
            share_text = f"🔥 Claim exclusive movies and web series gifts on @{bot_uname}!"
            share_url = f"https://t.me/share/url?url={urllib.parse.quote(refer_link)}&text={urllib.parse.quote(share_text)}"
            button_rows.append([
                InlineKeyboardButton(f"👥 Invite Friends ({new_invites}/{required_invites}) ↗️", url=share_url)
            ])

    # 4. Shortener row
    if require_shortener:
        tick = "✅" if shortener_done else "❌"
        status_txt = "Verified" if shortener_done else "Incomplete"
        card_lines.append(f"{tick} <b>Task {task_num}:</b> Complete 1-Time Ad Bypass ({status_txt})")
        task_num += 1

        if not shortener_done:
            token = await create_gift_task_token(gift_id, user_id, "shortener")
            target_url = f"https://t.me/{bot_uname}?start=vgtok_{token}"
            short_link = await get_shortlink(target_url)

            # Save shortlink in token document for web gateway masking
            try:
                await mongo.db["gift_task_tokens"].update_one(
                    {"token": token},
                    {"$set": {"short_link": short_link}}
                )
            except Exception as e_tok:
                logger.debug(f"Error saving short_link in gift_task_tokens: {e_tok}")

            # Mask shortener link through clean branded gateway domain
            web_gateway = Config.WEB_URL or Config.STREAM_URL
            if web_gateway and str(web_gateway).startswith("http"):
                masked_url = f"{str(web_gateway).rstrip('/')}/verify/{token}"
            else:
                masked_url = short_link

            button_rows.append([
                InlineKeyboardButton("🔑 Complete 1-Time Ad Bypass ↗️", url=masked_url)
            ])

    # 5. Sponsored Ad Tasks rows (Multi-Ad Support)
    web_gateway = Config.WEB_URL or Config.STREAM_URL
    for a_idx, is_a_done, a_token, a_url in ad_tasks_status:
        tick = "✅" if is_a_done else "❌"
        status_txt = "Verified" if is_a_done else f"Pending ({ad_wait_sec}s visit)"
        label = f"View Sponsor Offer #{a_idx}" if len(ad_tasks_status) > 1 else "View Sponsored Partner Offer"
        card_lines.append(f"{tick} <b>Task {task_num}:</b> {label} ({status_txt})")
        task_num += 1

        if not is_a_done:
            if web_gateway and str(web_gateway).startswith("http"):
                masked_url = f"{str(web_gateway).rstrip('/')}/verify/{a_token}"
            else:
                masked_url = a_url

            btn_label = f"🌐 View Sponsor Offer #{a_idx} ↗️" if len(ad_tasks_status) > 1 else (gift.get("ad_button_text") or "🌐 View Sponsored Offer ↗️")
            button_rows.append([
                InlineKeyboardButton(btn_label, url=masked_url)
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
