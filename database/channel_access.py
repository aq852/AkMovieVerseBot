import time
import datetime
import logging
from database.mongo import mongo

logger = logging.getLogger("flixify.channel_access")


async def grant_temporary_channel_access(
    client,
    user_id: int,
    chat_id: int,
    duration_hours: int,
    channel_name: str = "Private VIP Channel"
) -> tuple[bool, str, str]:
    """Create a single-use, auto-expiring invite link (member_limit=1) and track access ledger.
    Returns (success: bool, invite_link: str, error_or_expiry: str).
    """
    try:
        now = time.time()
        # Invite link itself expires in 24 hours if not clicked
        link_expire_timestamp = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        
        # 1. Generate Telegram Single-Use Invite Link (member_limit=1)
        invite = await client.create_chat_invite_link(
            chat_id=int(chat_id),
            name=f"Flixify_User_{user_id}",
            member_limit=1,
            expire_date=link_expire_timestamp
        )
        invite_link = invite.invite_link

        # 2. Compute user access expiry timestamp
        access_expires_at = now + (int(duration_hours) * 3600)

        # 3. Record in channel_access_ledger
        col = mongo.db["channel_access_ledger"]
        doc = {
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "channel_name": channel_name,
            "invite_link": invite_link,
            "duration_hours": int(duration_hours),
            "granted_at": now,
            "expires_at": access_expires_at,
            "status": "active"
        }
        await col.insert_one(doc)

        logger.info(f"Granted {duration_hours}h channel access for user {user_id} to channel {chat_id}")
        return True, invite_link, str(access_expires_at)
    except Exception as e:
        logger.error(f"Failed to generate single-use invite link for chat {chat_id}: {e}")
        return False, "", str(e)


async def check_and_evict_expired_channel_members(client) -> int:
    """Background worker: Automatically kicks expired members (ban + unban) and notifies them in PM."""
    now = time.time()
    col = mongo.db["channel_access_ledger"]
    cursor = col.find({"status": "active", "expires_at": {"$lte": now}})
    expired_docs = await cursor.to_list(length=100)

    evicted_count = 0
    for doc in expired_docs:
        uid = doc.get("user_id")
        cid = doc.get("chat_id")
        ch_name = doc.get("channel_name", "Private VIP Channel")
        doc_id = doc.get("_id")

        try:
            # Kick user out of channel cleanly via Ban + Unban
            await client.ban_chat_member(chat_id=cid, user_id=uid)
            try:
                await client.unban_chat_member(chat_id=cid, user_id=uid)
            except Exception:
                pass

            # Update ledger status
            await col.update_one({"_id": doc_id}, {"$set": {"status": "expired", "evicted_at": now}})
            evicted_count += 1
            logger.info(f"Evicted expired user {uid} from channel {cid}")

            # Notify user in PM
            try:
                msg_text = (
                    f"⏰ <b>Private Channel Access Expired</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Aapka <b>{ch_name}</b> ka time poora ho chuka hai.\n\n"
                    f"💡 <i>Agar aap dobara join karna chahte hain, toh naya pass lene ke liye <b>/store</b> ya <b>/spin</b> use karein!</i>"
                )
                await client.send_message(uid, msg_text)
            except Exception:
                pass
        except Exception as e_evict:
            logger.debug(f"Could not evict user {uid} from chat {cid}: {e_evict}")
            # Mark as closed so it doesn't loop
            await col.update_one({"_id": doc_id}, {"$set": {"status": "eviction_failed", "error": str(e_evict)}})

    return evicted_count
