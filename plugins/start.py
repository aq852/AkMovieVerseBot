import asyncio
import datetime
import html
import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from database.users import add_user, is_banned, record_referral, is_premium, get_user_info, get_total_users_count
from database.files import get_file_by_id
from database.verify import is_user_verified, create_verify_token, verify_user_token
from utils.fsub import check_fsub, build_fsub_markup
from utils.shortener import get_shortlink
from utils.helpers import format_clean_title, get_readable_size, get_random_start_pic, is_private_chat, resolve_channel_display_and_url

logger = logging.getLogger(__name__)

async def auto_delete_messages(
    messages: list,
    delay: int = 300,
    file_unique_id: str | None = None,
    clean_name: str | None = None,
    bot_username: str | None = None
):
    """Background task to delete delivered media and convert warning to a re-download tombstone."""
    await asyncio.sleep(delay)
    file_msg = messages[0] if len(messages) > 0 else None
    warn_msg = messages[1] if len(messages) > 1 else None

    # Delete the media file message to comply with Telegram copyright policy
    if file_msg:
        try:
            await file_msg.delete()
        except Exception:
            pass

    # If we have file details and a warning message, replace warning with a clean re-download tombstone!
    if warn_msg and file_unique_id and bot_username:
        try:
            import html
            disp_title = html.escape(clean_name or "Movie / Series File")
            tombstone_text = (
                "⚠️ <b>This file has been auto-deleted due to copyright policy!</b>\n\n"
                f"📁 <b>File:</b> <code>{disp_title}</code>\n\n"
                "<i>Don't worry! Tap below to instantly re-download this file anytime:</i>"
            )
            re_dl_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Re-download File ↗️", url=f"https://t.me/{bot_username}?start=file_{file_unique_id}")]
            ])
            await warn_msg.edit_text(tombstone_text, reply_markup=re_dl_markup)
            return
        except Exception:
            pass

    # Fallback delete warning message if tombstone couldn't be edited
    if warn_msg:
        try:
            await warn_msg.delete()
        except Exception:
            pass

async def deliver_file_with_copyright_warning(
    client: Client,
    user_id: int,
    file_doc: dict,
    custom_protect: bool | None = None,
    is_protected_viewing: bool = False
):
    """Deliver file with AkVerseXBot-style clean title, backup channel button, and auto-delete warning."""
    clean_name = format_clean_title(file_doc.get("file_name", "Movie File"))

    # Resolve backup/updates channel link (safe against raw channel IDs like -100...)
    backup_name, backup_url = await resolve_channel_display_and_url(client)

    import html
    escaped_title = html.escape(clean_name)
    escaped_backup = html.escape(backup_name)

    caption = (
        f"🎬 <b>{escaped_title}</b>\n\n"
        f"⚜️ <b>Join Backup</b> 🤝: <a href=\"{backup_url}\">{escaped_backup}</a>"
    )

    btn_rows = [
        [InlineKeyboardButton("📌 JOIN UPDATES CHANNEL 📌 ↗️", url=backup_url)]
    ]
    if Config.ENABLE_STREAMING and file_doc.get("file_unique_id"):
        btn_rows.append([
            InlineKeyboardButton("⚡ Stream & Watch Online ↗️", callback_data=f"stream_{file_doc['file_unique_id']}")
        ])

    btn = InlineKeyboardMarkup(btn_rows)

    protect_flag = custom_protect if custom_protect is not None else Config.PROTECT_CONTENT

    file_msg = None
    try:
        file_msg = await client.send_cached_media(
            chat_id=user_id,
            file_id=file_doc["file_id"],
            caption=caption,
            reply_markup=btn,
            protect_content=protect_flag
        )
    except Exception as e:
        logger.warning(f"send_cached_media failed for {file_doc.get('file_name')} ({e}). Attempting copy_message fallback...")
        channel_id = file_doc.get("channel_id")
        message_id = file_doc.get("message_id")
        if channel_id and message_id:
            file_msg = await client.copy_message(
                chat_id=user_id,
                from_chat_id=channel_id,
                message_id=message_id,
                caption=caption,
                reply_markup=btn,
                protect_content=protect_flag
            )
            # Auto-heal: update new bot's file_id in MongoDB so future sends are cached and instant
            try:
                new_fid = None
                if file_msg.document:
                    new_fid = file_msg.document.file_id
                elif file_msg.video:
                    new_fid = file_msg.video.file_id
                elif file_msg.audio:
                    new_fid = file_msg.audio.file_id
                elif file_msg.photo:
                    new_fid = file_msg.photo.file_id
                elif file_msg.animation:
                    new_fid = file_msg.animation.file_id
                elif file_msg.voice:
                    new_fid = file_msg.voice.file_id
                if new_fid and new_fid != file_doc.get("file_id") and "_id" in file_doc:
                    from database.mongo import mongo
                    await mongo.files.update_one({"_id": file_doc["_id"]}, {"$set": {"file_id": new_fid}})
                    logger.info(f"Auto-healed file_id for '{file_doc.get('file_name')}' on current bot.")
            except Exception as update_err:
                logger.debug(f"Could not auto-update file_id: {update_err}")
        else:
            raise e

    # Resolve file auto-delete duration (Free users = 5 mins, VIP members = 30 mins)
    from database.mongo import get_bot_setting
    from database.users import is_premium
    is_vip = await is_premium(user_id) or Config.is_admin(user_id)

    if is_protected_viewing:
        # Protected content viewing mode: Give 30 Minutes so users have time to watch
        del_seconds = 1800
        del_label = "30 MINUTES"
        warning_text = (
            "🛡️ <b><u>CONTENT PROTECTION ACTIVE</u></b> 🛡️\n\n"
            f"⏳ <b>THIS MEDIA WILL AUTO-DELETE IN {del_label}</b>\n\n"
            "• 🔒 <i>Forwarding and downloads to device storage are restricted by creator.</i>\n"
            "• 🍿 <i>You have 30 Minutes to stream and watch directly inside Telegram!</i>"
        )
    else:
        if is_vip:
            del_seconds = await get_bot_setting("vip_file_auto_delete_time", getattr(Config, "VIP_FILE_AUTO_DELETE_TIME", 1800))
        else:
            del_seconds = await get_bot_setting("file_auto_delete_time", getattr(Config, "FILE_AUTO_DELETE_TIME", 300))

        if del_seconds >= 60:
            mins = del_seconds // 60
            del_label = f"{mins} MINUTE" if mins == 1 else f"{mins} MINUTES"
        else:
            del_label = f"{del_seconds} SECONDS"

        if is_vip:
            warning_text = (
                "👑 <b><u>VIP EXCLUSIVE BENEFIT</u></b> 👑\n\n"
                f"⏳ <b>THIS FILE WILL AUTO-DELETE IN {del_label}</b> (Due to Telegram copyright policies).\n\n"
                "• <i>As a VIP Member, you enjoy 6x extended time (30 Mins) compared to free users (5 Mins)!</i>\n"
                "• <i>Please forward this file to your <b>Saved Messages</b> or private storage to keep it permanently.</i>"
            )
        else:
            warning_text = (
                "❗️❗️❗️ <b><u>IMPORTANT</u></b> ❗️❗️❗️\n\n"
                f"<b>THIS MOVIE FILE/VIDEO WILL BE DELETED IN {del_label} 😐 (DUE TO COPYRIGHT ISSUES).</b>\n\n"
                "• <i>PLEASE FORWARD THIS FILE TO SAVED MESSAGES AND START DOWNLOADING THERE</i>\n"
                "• <i>Want 30-Minute extended time? Upgrade to VIP via /plans!</i>"
            )

    if del_seconds > 0 and file_msg:
        warn_msg = await client.send_message(chat_id=user_id, text=warning_text)
        bot_uname = client.me.username if client.me else Config.BOT_USERNAME
        asyncio.create_task(
            auto_delete_messages(
                [file_msg, warn_msg],
                delay=del_seconds,
                file_unique_id=file_doc.get("file_unique_id"),
                clean_name=clean_name,
                bot_username=bot_uname
            )
        )

def get_time_greeting() -> str:
    """Return greeting based on current time of day."""
    hour = datetime.datetime.utcnow().hour + 5.5 # Approx IST offset
    if 5 <= hour < 12:
        return "🌅 Good Morning"
    elif 12 <= hour < 17:
        return "☀️ Good Afternoon"
    elif 17 <= hour < 21:
        return "🌆 Good Evening"
    else:
        return "🌙 Good Night"


@Client.on_message(filters.command("start") & filters.private)
async def start_command_handler(client: Client, message: Message):
    """Handle /start command with greeting, deep-linking, FSub, and token verification."""
    user_id = message.from_user.id
    name = message.from_user.first_name
    username = message.from_user.username or ""

    # Check blacklist
    if await is_banned(user_id):
        await message.reply_text("🚫 <b>You have been blacklisted from using this bot.</b>")
        return

    user_doc, is_new = await add_user(user_id, name, username)

    if is_new and Config.LOG_CHANNEL:
        try:
            total_u = await get_total_users_count()
            uname_str = f"@{username}" if username else "No username"
            user_mention = message.from_user.mention(name)
            args_text = message.text.split()[1] if len(message.text.split()) > 1 else ""
            ref_txt = f"\n• <b>Referred By:</b> <code>{args_text.split('refer_')[1]}</code>" if args_text.startswith("refer_") else ""
            log_txt = (
                "👤 <b>#NewUser Started Bot!</b>\n\n"
                f"• <b>Name:</b> {user_mention}\n"
                f"• <b>User ID:</b> <code>{user_id}</code>\n"
                f"• <b>Username:</b> {uname_str}\n"
                f"• <b>Total Users:</b> <code>{total_u:,}</code>"
                f"{ref_txt}"
            )
            await client.send_message(Config.LOG_CHANNEL, log_txt)
        except Exception as e:
            logger.debug(f"Error sending new user log: {e}")

    bot_username = client.me.username if client.me else Config.BOT_USERNAME
    parts = message.text.split(None, 1)
    args = parts[1].strip() if len(parts) > 1 else ""

    # 1. Referral Deep-link: /start refer_<id> or /start spin_<id>
    if args.startswith("spin_"):
        referrer_str = args.split("spin_")[1]
        if referrer_str.isdigit() and is_new:
            referrer_id = int(referrer_str)
            if referrer_id != user_id:
                try:
                    from database.loyalty import credit_referral_spin
                    ok_spin, reason = await credit_referral_spin(referrer_id)
                    if ok_spin:
                        await client.send_message(
                            referrer_id,
                            "🎰 🎉 <b>CONGRATULATIONS! EXTRA SPIN UNLOCKED!</b> 🌟\n\n"
                            "Aapke dost ne aapke invite link se bot join kiya hai!\n"
                            "🎁 Aapko mila hai <b>+1 Instant Lucky Spin</b>!\n\n"
                            "👉 Wheel ghumane ke liye <b>/spin</b> dabayein!"
                        )
                except Exception as e_spin:
                    logger.debug(f"Spin referral credit error: {e_spin}")
        from plugins.spin import spin_command_handler
        return await spin_command_handler(client, message)

    elif args == "spin":
        from plugins.spin import spin_command_handler
        return await spin_command_handler(client, message)

    elif args in ["coins", "store", "shop"]:
        from plugins.store import store_command_handler
        return await store_command_handler(client, message)

    elif args in ["profile", "rank"]:
        from plugins.store import profile_command_handler
        return await profile_command_handler(client, message)

    elif args in ["leaderboard", "top"]:
        from plugins.store import leaderboard_command_handler
        return await leaderboard_command_handler(client, message)

    elif args.startswith("refer_"):
        referrer_str = args.split("refer_")[1]
        if referrer_str.isdigit():
            referrer_id = int(referrer_str)
            success, msg = await record_referral(referrer_id, user_id)
            if success and msg == "awarded_first_referral":
                try:
                    await client.send_message(
                        referrer_id,
                        "🎉 <b>CONGRATULATIONS! FIRST REFERRAL BONUS UNLOCKED!</b> 👑\n\n"
                        "Your friend just joined using your personal invite link!\n"
                        "🎁 You have been awarded <b>1 Day of Free VIP Premium Access</b> as a welcome starter bonus!\n\n"
                        "💡 <i>Keep inviting! For every 5 friends, you unlock another 1 Day of Free VIP!</i>"
                    )
                except Exception:
                    pass
            elif success and msg == "awarded_premium":
                try:
                    await client.send_message(
                        referrer_id,
                        "🎉 <b>CONGRATULATIONS! REFERRAL MILESTONE REACHED!</b> 👑\n\n"
                        "You reached another referral tier and unlocked <b>1 Day of Free VIP Premium Access</b>!\n\n"
                        "Enjoy unlimited, instant file downloads without any shorteners."
                    )
                except Exception:
                    pass

    # 1.1 Promo Code Deep-link: /start redeem_<code>
    elif args.startswith("redeem_"):
        promo_code = args.split("redeem_", 1)[1].strip()
        from database.promo import redeem_promo_code
        success, msg, days = await redeem_promo_code(promo_code, user_id)
        if success:
            u_mention = message.from_user.mention(message.from_user.first_name)
            congrats_text = (
                "🎉 <b>PROMO CODE REDEEMED SUCCESSFULLY!</b> 👑\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• 👤 <b>Member:</b> {u_mention}\n"
                f"• 🎟️ <b>Coupon Code:</b> <code>{promo_code.upper()}</code>\n"
                f"• 💎 <b>VIP Unlocked:</b> <code>{days} Day(s) Premium Pass</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌟 <b>Your Active VIP Perks:</b>\n"
                "• 🚫 No shorteners or verification ads\n"
                "• ⚡ Instant 1-second file delivery\n"
                "• 📦 Unlimited batch downloads\n\n"
                "<i>Enjoy your premium experience! Type any movie title to start searching.</i>"
            )
            await message.reply_text(congrats_text)
            if Config.LOG_CHANNEL:
                try:
                    await client.send_message(
                        Config.LOG_CHANNEL,
                        f"🎟️ <b>#PromoCodeRedeemed</b>\n\n"
                        f"• <b>User:</b> {u_mention} (<code>{user_id}</code>)\n"
                        f"• <b>Code:</b> <code>{promo_code.upper()}</code>\n"
                        f"• <b>Duration:</b> <code>+{days} Days VIP</code>"
                    )
                except Exception:
                    pass
        else:
            await message.reply_text(msg)
        return

    # 2. File Retrieval or Batch Deep-link: /start file_<id> or /start batch_<id>
    elif args.startswith("file_") or args.startswith("batch_"):
        raw_id = args.split("_", 1)[1]

        # Check if it's a batch collection or filestore link
        from database.batches import get_batch
        batch_doc = await get_batch(raw_id)
        if batch_doc:
            from plugins.file_store import handle_start_batch
            await handle_start_batch(client, message, raw_id)
            return

        file_unique_id = raw_id
        file_doc = await get_file_by_id(file_unique_id)

        if not file_doc:
            await message.reply_text("❌ <b>Sorry, this file is no longer available in our database.</b>")
            return

        # FSub Verification
        is_member, unjoined = await check_fsub(client, user_id)
        if not is_member:
            markup = build_fsub_markup(unjoined, file_unique_id)
            await message.reply_text(
                "📢 <b>Channel Membership Required!</b>\n\n"
                "To access this file, you must first join our official updates channel(s).\n"
                "Join using the button(s) below, then click <b>'Try Again'</b>:",
                reply_markup=markup
            )
            return

        # 24-Hour Session Verification OR Daily Free Quota OR Direct Pass
        user_is_verified = await is_user_verified(user_id)
        delivered_under_free = False
        used_pass_flag = False
        passes_left = 0
        used_free_count = 0
        free_quota_limit = getattr(Config, "DAILY_FREE_LIMIT", 3)

        if not user_is_verified:
            # 1. First check bonus direct download pass from /store or rewards
            try:
                from database.loyalty import use_direct_pass
                used_pass, passes_left = await use_direct_pass(user_id)
                if used_pass:
                    used_pass_flag = True
            except Exception:
                used_pass_flag = False

            if not used_pass_flag:
                from database.users import check_daily_free_download, consume_daily_free_download
                has_free, used_today, limit = await check_daily_free_download(user_id)
                if has_free:
                    used_free_count = await consume_daily_free_download(user_id)
                    free_quota_limit = limit
                    delivered_under_free = True
                else:
                    token = await create_verify_token(user_id, file_unique_id)
                    redirect_url = f"https://t.me/{bot_username}?start=verify_{token}"

                    final_verify_url = None
                    verify_markup = None
                    verify_text = None

                    if Config.SHORTENER_ENABLED:
                        from utils.shortener import get_rotated_shortlink
                        from database.verify import update_token_shortlink

                        short_link, shortener_used = await get_rotated_shortlink(redirect_url)
                        await update_token_shortlink(token, short_link, shortener_used)

                        if Config.WEB_URL:
                            final_verify_url = f"{Config.WEB_URL}/verify/{token}"
                        else:
                            final_verify_url = short_link

                        verify_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔓 Verify Access (24h Pass)", url=final_verify_url)],
                            [InlineKeyboardButton("📖 How to Bypass / Tutorial", url=Config.TUTORIAL_URL)],
                            [InlineKeyboardButton("👑 Buy VIP (Skip Verification)", callback_data="view_plans")]
                        ])
                        verify_text = (
                            f"⏳ <b>Daily Free Limit Reached ({used_today}/{limit} Used)!</b>\n\n"
                            f"You have used your <b>{limit} Daily Free Downloads</b> for today.\n\n"
                            "To unlock <b>24 Hours of UNLIMITED, Instant Downloads</b>:\n"
                            "👉 Complete a quick 1-minute verification below, or buy VIP!\n\n"
                            "<i>💡 Tip: Your daily free quota resets every midnight automatically!</i>"
                        )
                    elif getattr(Config, "WEB_URL", ""):
                        from database.verify import update_token_shortlink
                        await update_token_shortlink(token, redirect_url, "clean_gateway")
                        final_verify_url = f"{Config.WEB_URL}/verify/{token}"

                        verify_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🛡️ 1-Click Verification (24h Pass)", url=final_verify_url)],
                            [InlineKeyboardButton("👑 VIP Members Skip All Checks", callback_data="view_plans")]
                        ])
                        verify_text = (
                            f"⏳ <b>Daily Free Limit Reached ({used_today}/{limit} Used)!</b>\n\n"
                            "Please complete a quick 5-second check to unlock <b>24 Hours of Unlimited Downloads</b>!\n\n"
                            "• <i>No external spam ads • Just a quick safety check.</i>\n"
                            "• <i>Your daily free quota resets every midnight!</i>"
                        )

                    if final_verify_url and verify_markup:
                        await message.reply_text(verify_text, reply_markup=verify_markup)
                        return

        # Deliver File Directly
        try:
            await deliver_file_with_copyright_warning(client, user_id, file_doc)
            if used_pass_flag:
                try:
                    await message.reply_text(
                        f"⚡ <b>Direct Download Pass Used!</b> <code>({passes_left} remaining)</code>\n"
                        "<i>Enjoy your instant, ad-free download! Get more passes via /store.</i>"
                    )
                except Exception:
                    pass
            elif delivered_under_free:
                rem = max(0, free_quota_limit - used_free_count)
                try:
                    await message.reply_text(
                        f"🎁 <b>Daily Free Download:</b> <code>{used_free_count}/{free_quota_limit} used</code> "
                        f"<i>({rem} remaining for today)</i>\n"
                        "💡 <i>Tip: Want unlimited downloads without daily caps? Tap /plans to get VIP!</i>",
                        disable_web_page_preview=True
                    )
                except Exception:
                    pass
            return
        except Exception as e:
            logger.error(f"Error dispatching file to {user_id}: {e}")
            await message.reply_text(f"❌ <b>Error sending file:</b> <code>{e}</code>")
            return

    # 3. Token Verification Completion: /start verify_<token>
    elif args.startswith("verify_"):
        token = args.split("verify_")[1]
        success, pending_file_id, verified_user_id = await verify_user_token(token)

        if not success or verified_user_id != user_id:
            await message.reply_text("❌ <b>Invalid or expired verification token.</b> Please request the file again.")
            return

        await message.reply_text(
            "🎉 <b>Verification Successful!</b>\n\n"
            "You now have <b>24 Hours of Unlimited Access</b> to all files without any shorteners!\n"
            "Sending your requested file now..."
        )

        if Config.LOG_CHANNEL:
            try:
                u_mention = message.from_user.mention(message.from_user.first_name)
                await client.send_message(
                    Config.LOG_CHANNEL,
                    f"🔓 <b>#TokenVerified (24h Pass Active)</b>\n\n"
                    f"• <b>User:</b> {u_mention} (<code>{user_id}</code>)\n"
                    f"• <b>Shortener:</b> <code>{Config.SHORTENER_URL}</code>\n"
                    f"• <b>Status:</b> Active for next 24 Hours"
                )
            except Exception:
                pass

        if pending_file_id:
            if pending_file_id.startswith("batch_"):
                b_id = pending_file_id.split("_", 1)[1]
                from plugins.file_store import handle_start_batch
                await handle_start_batch(client, message, b_id)
                return
            else:
                raw_fid = pending_file_id.split("_", 1)[1] if pending_file_id.startswith("file_") else pending_file_id
                file_doc = await get_file_by_id(raw_fid)
                if file_doc:
                    try:
                        await deliver_file_with_copyright_warning(client, user_id, file_doc)
                        return
                    except Exception as e:
                        logger.error(f"Error delivering verified file: {e}")
                else:
                    await message.reply_text("❌ <b>Sorry, requested file could not be found.</b>")
        return

    # 4. VIP Plans / Remove Ads: /start plans
    elif args == "plans" or args.startswith("plans"):
        from plugins.extra import get_plans_text, get_plans_markup
        plans_text = get_plans_text()
        markup = get_plans_markup()

        sent = False
        if Config.UPI_QR_URL:
            try:
                await message.reply_photo(photo=Config.UPI_QR_URL, caption=plans_text, reply_markup=markup)
                sent = True
            except Exception:
                pass
        if not sent:
            await message.reply_text(plans_text, reply_markup=markup)
        return

    # 5. Search Deep-link: /start search_<query>
    elif args.startswith("search_"):
        import urllib.parse
        raw_param = args.split("search_", 1)[1]
        raw_query = urllib.parse.unquote_plus(raw_param).replace("+", " ").replace("_", " ").strip()
        # Attempt smart navigator session first so user gets quality / season buttons if available!
        try:
            from utils.smart_nav import create_nav_session, build_navigator_root_view
            sid = create_nav_session(
                query=raw_query,
                user_id=user_id,
                chat_id=message.chat.id,
                is_pm=True,
                bot_username=bot_username
            )
            text, markup = await build_navigator_root_view(sid)
            if "❌" not in text and "⚠️ No" not in text and not re.search(r"\b0 Files\b", text):
                await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
                return
        except Exception as nav_err:
            logger.debug(f"Smart Nav fallback to filter handler: {nav_err}")

        message.text = raw_query
        from plugins.autofilter import group_auto_filter_handler
        await group_auto_filter_handler(client, message)
        return

    # 6. Filter Deep-link: /start filter_<query> (Direct Filter Trigger from Channel Post or Top Link)
    elif args.startswith("filter_"):
        import urllib.parse
        raw_param = args.split("filter_", 1)[1]
        raw_filter_q = urllib.parse.unquote_plus(raw_param).replace("+", " ").replace("_", " ").strip()
        try:
            from utils.smart_nav import create_nav_session, build_navigator_root_view
            sid = create_nav_session(
                query=raw_filter_q,
                user_id=user_id,
                chat_id=message.chat.id,
                is_pm=True,
                bot_username=bot_username
            )
            text, markup = await build_navigator_root_view(sid)
            if "❌" not in text and "⚠️ No" not in text and not re.search(r"\b0 Files\b", text):
                await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)
                return
        except Exception as nav_err:
            logger.debug(f"Smart Nav fallback to autofilter: {nav_err}")

        # Seamless fallback: Run standard group_auto_filter_handler so files, spell-check & sponsor ad are sent
        message.text = raw_filter_q
        from plugins.autofilter import group_auto_filter_handler
        await group_auto_filter_handler(client, message)
        return

    # 6b. MovieVerse 3D Deep-link: /start galaxy_<query> or /start movieverse
    elif args.startswith("galaxy_") or args in ("galaxy", "movieverse", "3d"):
        import urllib.parse
        raw_galaxy_q = urllib.parse.unquote_plus(args.split("galaxy_", 1)[1]).strip() if args.startswith("galaxy_") else ""
        from utils.web_server import get_effective_stream_base_url
        stream_base = get_effective_stream_base_url()
        if not stream_base or any(h in stream_base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
            stream_base = "https://akmovieverse.duckdns.org"

        g_param = f"?q={urllib.parse.quote_plus(raw_galaxy_q)}" if raw_galaxy_q else ""
        galaxy_target_url = f"{stream_base}/galaxy{g_param}"

        try:
            from hydrogram.types import WebAppInfo
        except ImportError:
            from pyrogram.types import WebAppInfo

        q_label = f" for '<b>{html.escape(raw_galaxy_q)}</b>'" if raw_galaxy_q else ""
        g_text = (
            f"🪐 <b>MOVIEVERSE 3D SEARCH</b> 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <i>Explore files in an interactive 3D WebGL orbit{q_label}!</i>\n\n"
            f"• <b>3D Interactive Cards:</b> Swipe to spin solar orbit\n"
            f"• <b>Instant Quality Selection:</b> 480p, 720p, 1080p, 4K\n"
            f"• <b>Direct Bot Delivery:</b> 1-tap download straight to this chat\n\n"
            f"👇 <i>Tap below to launch MovieVerse 3D:</i>"
        )
        g_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪐 OPEN MOVIEVERSE 3D 🚀", web_app=WebAppInfo(url=galaxy_target_url))],
            [InlineKeyboardButton("🌐 Open in Web Browser ↗️", url=galaxy_target_url)]
        ])
        await message.reply_text(g_text, reply_markup=g_markup, disable_web_page_preview=True)
        return

    # 7. Time-based & Single-Use Secret Share Deep-link: /start share_<token>
    elif args.startswith("share_"):
        token = args.split("share_")[1]
        from database.share_links import claim_share_link
        success, reason, share_doc = await claim_share_link(token, user_id)

        if not success:
            if reason == "expired":
                exp_dt = share_doc.get("expire_at")
                exp_str = exp_dt.strftime("%d %b %Y, %H:%M UTC") if exp_dt else "Passed"
                await message.reply_text(
                    "⏳ <b>This Secret Share Link Has Expired!</b>\n\n"
                    f"• <b>Expired At:</b> <code>{exp_str}</code>\n\n"
                    "💡 The sender configured this link with a time limit that has already passed."
                )
            elif reason == "limit_reached":
                max_u = share_doc.get("max_uses", 1)
                limit_text = "Single-Use (1 Person Only)" if max_u == 1 else f"{max_u}-Person Limit"
                await message.reply_text(
                    "🔒 <b>Access Limit Reached!</b>\n\n"
                    f"• <b>Restriction:</b> <code>{limit_text}</code>\n\n"
                    "This secret link has already been claimed by someone else and has self-destructed! 🔥"
                )
            else:
                await message.reply_text("❌ <b>Invalid or Deleted Share Link!</b>")
            return

        # Fetch and deliver the file
        file_unique_id = share_doc["file_unique_id"]
        file_doc = await get_file_by_id(file_unique_id)
        if not file_doc:
            await message.reply_text("❌ <b>The file associated with this link is no longer available.</b>")
            return

        max_u = share_doc.get("max_uses")
        claimed = share_doc.get("claimed_count", 1)
        rem_label = f"{max_u - claimed} remaining" if max_u else "Unlimited"

        await message.reply_text(
            "🔓 <b>Access Granted via Secret Share Link!</b>\n\n"
            f"• <b>File:</b> <code>{file_doc.get('file_name', 'Movie')}</code>\n"
            f"• <b>Usage:</b> <code>{claimed}/{max_u if max_u else '∞'}</code> ({rem_label})\n\n"
            "Delivering your file now..."
        )
        await deliver_file_with_copyright_warning(client, user_id, file_doc)
        return

    elif args.startswith("gift_"):
        gift_id = args.split("gift_")[1]
        from utils.gift_flow import render_gift_page
        await render_gift_page(client=client, user_id=user_id, gift_id=gift_id, target_message=message)
        return

    elif args.startswith("vgtok_"):
        token = args.split("vgtok_")[1]
        from database.gifts import verify_gift_task_token
        ok, msg, token_doc = await verify_gift_task_token(token)
        if not ok or not token_doc:
            await message.reply_text(f"❌ <b>Verification Failed:</b> {msg}")
            return

        gift_id = token_doc.get("gift_id", "")
        target_url = token_doc.get("target_url", "")
        bot_uname = client.me.username if client.me else Config.BOT_USERNAME

        buttons = []
        if target_url:
            buttons.append([InlineKeyboardButton("🌐 Open Target Link ↗️", url=target_url)])
        buttons.append([InlineKeyboardButton("🎁 Continue to Claim Reward ↗️", url=f"https://t.me/{bot_uname}?start=gift_{gift_id}")])

        success_text = (
            "✅ <b>TASK COMPLETED &amp; VERIFIED!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your task has been confirmed in our database!\n\n"
            "👉 Tap the button below to return and claim your gift reward:"
        )
        markup = InlineKeyboardMarkup(buttons)
        await message.reply_text(success_text, reply_markup=markup, disable_web_page_preview=True)
        return

    # 7. Standard /start Greeting
    hour = datetime.datetime.utcnow().hour + 5.5
    if 5 <= hour < 12:
        greeting_time = "GOOD MORNING 🌅"
    elif 12 <= hour < 17:
        greeting_time = "GOOD AFTERNOON 🌔"
    elif 17 <= hour < 21:
        greeting_time = "GOOD EVENING 🌆"
    else:
        greeting_time = "GOOD NIGHT 🌙"

    welcome_text = (
        f"🚩<i>JAI SHRI RAM</i>🚩\n\n"
        f"HEY <b>{name}</b>, {greeting_time}\n\n"
        f"🤖 I AM <b>{bot_username}</b>, THE MOST POWERFUL AUTO FILTER BOT WITH PREMIUM FEATURES."
    )

    markup_rows = [
        [InlineKeyboardButton("🔰 ADD ME TO YOUR GROUP 🔰", url=f"https://t.me/{bot_username}?startgroup=true")],
        [
            InlineKeyboardButton("HELP 📢", callback_data="help_menu"),
            InlineKeyboardButton("ABOUT 📖", callback_data="about_menu")
        ]
    ]

    from plugins.stream import get_effective_stream_base_url
    stream_base = get_effective_stream_base_url()
    if getattr(Config, "ENABLE_BROWSE_BUTTON", False) and Config.ENABLE_STREAMING and stream_base and not any(h in stream_base for h in ("127.0.0.1", "localhost", "0.0.0.0")):
        markup_rows.insert(1, [
            InlineKeyboardButton("🌐 BROWSE WEB CINEMA ↗️", url=f"{stream_base}/browse")
        ])

    # Time-based sponsor ad for non-VIP users (Bottom button + caption link)
    if not await is_premium(user_id):
        try:
            from database.ads import get_active_sponsor_ad
            ad = await get_active_sponsor_ad()
            if ad and ad.get("text") and ad.get("url"):
                ad_title = ad["text"]
                ad_url = ad["url"]
                markup_rows.append([
                    InlineKeyboardButton(f"🔥 {ad_title} ↗️", url=ad_url)
                ])
                welcome_text += f"\n\n📢 <i>Sponsored:</i> <a href=\"{ad_url}\">{html.escape(ad_title)}</a>"
        except Exception as e:
            logger.debug(f"Could not load sponsor ad for start: {e}")

    markup = InlineKeyboardMarkup(markup_rows)

    sent = False
    start_pic = get_random_start_pic()
    if start_pic:
        try:
            await message.reply_photo(photo=start_pic, caption=welcome_text, reply_markup=markup)
            sent = True
        except Exception as e:
            logger.debug(f"Could not send start photo: {e}")

    if not sent:
        await message.reply_text(welcome_text, reply_markup=markup)


# User Plan Command
@Client.on_message(filters.command(["plans", "myplan"]))
async def user_plan_command(client: Client, message: Message):
    """View active subscription plan or available upgrades."""
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    if not is_private_chat(message):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎟️ VIEW VIP PREMIUM PLANS ↗️", url=f"https://t.me/{bot_username}?start=plans")]
        ])
        await message.reply_text(
            "💎 <b>AkMovieVerse VIP Premium Plans</b>\n\n"
            "Enjoy 100% ad-free instant downloads, zero shorteners, and unlimited searches!\n"
            "👉 Tap below to view VIP plans in private chat:",
            reply_markup=markup
        )
        return

    user_id = message.from_user.id
    user = await get_user_info(user_id)
    is_vip = await is_premium(user_id)

    if is_vip and user.get("premium_expires"):
        expiry_dt = user["premium_expires"]
        now = datetime.datetime.utcnow()
        remaining = expiry_dt - now
        days = max(0, remaining.days)
        hours = max(0, remaining.seconds // 3600)

        text = (
            "💎 <b>YOUR VIP MEMBERSHIP STATUS</b> 💎\n\n"
            "• <b>Status:</b> <code>ACTIVE VIP 👑</code>\n"
            f"• <b>Remaining Time:</b> <code>{days} Days, {hours} Hours</code>\n"
            f"• <b>Expires On:</b> <code>{expiry_dt.strftime('%d %b %Y, %H:%M UTC')}</code>\n\n"
            "🌟 <b>Your Active Perks:</b>\n"
            "• 📺 Smart TV Stremio Addon access\n"
            "• 🚫 No shorteners or token verification\n"
            "• ⚡ Instant 1-second direct PM delivery\n"
            "• 🔓 Unlimited daily files & searches\n"
            "• 📦 SEND ALL batch season deliveries\n"
            "• ⏳ 30-Minute extended auto-delete buffer\n\n"
            "💡 <i>Want to extend your validity? Choose an upgrade below:</i>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Extend VIP Plan", callback_data="view_plans")],
            [InlineKeyboardButton("👥 Refer & Earn Free Days", callback_data="view_refer")]
        ])
        await message.reply_text(text, reply_markup=markup)
    else:
        from plugins.extra import get_plans_text, get_plans_markup
        plans_text = get_plans_text()
        markup = get_plans_markup()

        sent = False
        if Config.UPI_QR_URL:
            try:
                await message.reply_photo(photo=Config.UPI_QR_URL, caption=plans_text, reply_markup=markup)
                sent = True
            except Exception:
                pass
        if not sent:
            await message.reply_text(plans_text, reply_markup=markup)


def build_referral_progress_bar(current_count: int, target: int = 5) -> str:
    """Render sleek visual progress bar for referral tier tracking."""
    rem = current_count % target
    pct = int((rem / target) * 100)
    filled = int(rem / target * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {rem}/{target} ({pct}%)"


# Referral Command
@Client.on_message(filters.command("refer"))
async def refer_command(client: Client, message: Message):
    """Display user's referral stats, visual progress bar, and unique invite link."""
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    if not is_private_chat(message):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 INVITE FRIENDS IN PM ↗️", url=f"https://t.me/{bot_username}?start=refer")]
        ])
        await message.reply_text(
            "👥 <b>Refer & Earn Free VIP Access</b>\n\n"
            "Invite friends to get free days of VIP membership!\n"
            "👉 Tap below to get your personal invite link in PM:",
            reply_markup=markup
        )
        return

    user_id = message.from_user.id
    user = await get_user_info(user_id)
    bot_username = client.me.username if client.me else Config.BOT_USERNAME

    refer_count = user.get("refer_count", 0)
    rewards_earned = user.get("refer_rewards_earned", 0)
    needed = 5 - (refer_count % 5)
    progress_bar = build_referral_progress_bar(refer_count, 5)
    refer_link = f"https://t.me/{bot_username}?start=refer_{user_id}"

    text = (
        "👥 <b><u>REFER & EARN FREE VIP ACCESS</u></b> 👥\n\n"
        "Invite your friends to the bot and unlock <b>Free VIP Membership Days</b>!\n"
        "🎁 <b>Starter Perk:</b> Invite your <b>1st friend</b> to unlock <b>1 Day of Free VIP Premium</b> instantly!\n"
        "🌟 <b>Ongoing Perk:</b> For every <b>5 friends</b> after that, get another <b>1 Day of Free VIP</b> automatically!\n\n"
        f"📊 <b>Your Referral Performance:</b>\n"
        f"• <b>Total Friends Invited:</b> <code>{refer_count}</code>\n"
        f"• <b>Free VIP Days Earned:</b> <code>{rewards_earned} Days 👑</code>\n"
        f"• <b>Current Progress:</b> <code>{progress_bar}</code>\n"
        f"• <b>Next Free VIP Reward:</b> in <code>{needed}</code> more friends!\n\n"
        f"🔗 <b>Your Personal Invite Link:</b>\n"
        f"<code>{refer_link}</code>\n\n"
        "👇 <i>Tap below to share directly with friends or groups:</i>"
    )

    import urllib.parse
    share_caption = "🍿 Search & download unlimited movies and web series in high quality for free!"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(refer_link)}&text={urllib.parse.quote(share_caption)}"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Referral Link", url=share_url)]
    ])

    await message.reply_text(text, reply_markup=markup)
