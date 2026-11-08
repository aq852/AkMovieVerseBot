import logging
try:
    from hydrogram import Client
    from hydrogram.types import (
        BotCommand,
        BotCommandScopeDefault,
        BotCommandScopeChat,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeAllChatAdministrators
    )
except ImportError:
    from pyrogram import Client
    from pyrogram.types import (
        BotCommand,
        BotCommandScopeDefault,
        BotCommandScopeChat,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeAllChatAdministrators
    )

from config import Config

logger = logging.getLogger(__name__)

USER_COMMANDS = [
    BotCommand("start", "Start the bot & get main menu"),
    BotCommand("help", "How to search & use the bot"),
    BotCommand("dl", "Download Instagram & Telegram: /dl <url>"),
    BotCommand("watch", "Stream movie/series online: /watch <name>"),
    BotCommand("stream", "Generate fast stream & web player links"),
    BotCommand("imdb", "Search movie rating & details: /imdb <name>"),
    BotCommand("request", "Request movie/series: /request <name>"),
    BotCommand("myrequests", "View your requested movies status"),
    BotCommand("myalerts", "View active movie upload alerts: /myalerts"),
    BotCommand("batch", "Create 1-click batch link: /batch"),
    BotCommand("genlink", "Single file shareable link: reply /genlink"),
    BotCommand("batches", "View your saved batch links"),
    BotCommand("delbatch", "Delete your batch: /delbatch <id>"),
    BotCommand("plans", "View VIP ad-free plans"),
    BotCommand("myplan", "Check your VIP status"),
    BotCommand("refer", "Invite friends & earn free VIP"),
    BotCommand("redeem", "Redeem VIP promo coupon: /redeem <code>"),
    BotCommand("poster", "Design HD poster: /poster <name>"),
    BotCommand("tgm", "Upload media to CDN: reply /tgm"),
    BotCommand("paste", "Publish text to Telegraph: /paste"),
    BotCommand("id", "Get your Telegram ID"),
    BotCommand("info", "Get user profile details"),
    BotCommand("cancel", "Cancel current action")
]

GROUP_ADMIN_COMMANDS = [
    BotCommand("settings", "Open group settings panel"),
    BotCommand("connect", "Connect group to your PM"),
    BotCommand("disconnect", "Disconnect group from PM"),
    BotCommand("shortlink", "Set custom shortener for group"),
    BotCommand("filter", "Add manual filter: /filter <word> <reply>"),
    BotCommand("filters", "List active manual filters in group"),
    BotCommand("stop", "Remove filter: /stop <word>"),
    BotCommand("stopall", "Clear all manual filters in group"),
    BotCommand("plans", "View VIP premium plans"),
    BotCommand("request", "Request movie/series: /request <name>"),
    BotCommand("id", "Get group / message ID"),
    BotCommand("info", "Get user details")
]

ADMIN_COMMANDS = [
    BotCommand("start", "Start bot & main menu"),
    BotCommand("help", "Help guide & command center"),
    BotCommand("adminhelp", "Admin command center & detailed guide"),
    BotCommand("batch", "Create batch link: /batch [link1] [link2]"),
    BotCommand("genlink", "Single file shareable link: reply /genlink"),
    BotCommand("batches", "Admin batch dashboard & analytics"),
    BotCommand("delbatch", "Delete any batch link: /delbatch <id>"),
    BotCommand("tgm", "Upload media to Multi-CDN: reply /tgm"),
    BotCommand("paste", "Publish article to Telegraph: /paste"),
    BotCommand("post", "Interactive channel release draft: /post <title>"),
    BotCommand("poststyle", "Select auto-post style: /poststyle [1|2|3]"),
    BotCommand("postbutton", "Custom auto-post button: /postbutton <text> | <url>"),
    BotCommand("autopost", "Toggle auto-post engine: /autopost [on|off|status]"),
    BotCommand("setupdateschannel", "Set updates channel: /setupdateschannel <id>"),
    BotCommand("streaming", "Toggle streaming engine: /streaming [on|off]"),
    BotCommand("stream_download", "Toggle web fast download: /stream_download [on|off]"),
    BotCommand("stats", "System metrics, total files & users"),
    BotCommand("targetdb", "MongoDB multi-cluster write routing: /targetdb [1|2|auto]"),
    BotCommand("index", "Batch crawl channel: /index <channel_or_link>"),
    BotCommand("checkpoints", "Indexing resume bookmarks: /checkpoints"),
    BotCommand("setskip", "Set message skip offset: /setskip <number>"),
    BotCommand("stopindex", "Stop active indexing crawl"),
    BotCommand("broadcast", "Broadcast replied message to all users"),
    BotCommand("grp_broadcast", "Broadcast replied message to all groups"),
    BotCommand("add_premium", "Grant VIP access: /add_premium <id> <days>"),
    BotCommand("remove_premium", "Revoke VIP access: /remove_premium <id>"),
    BotCommand("premium_users", "List active VIP members & validity"),
    BotCommand("deletecam", "Purge CamRip / PreDVD files: /deletecam"),
    BotCommand("cleanduplicates", "Purge duplicate files: /cleanduplicates"),
    BotCommand("cleanfiles", "Clean website watermarks from files: /cleanfiles"),
    BotCommand("delbyname", "Purge movie files by name: /delbyname <name>"),
    BotCommand("addjunk", "Blacklist site tag: /addjunk <tag>"),
    BotCommand("deljunk", "Remove site tag: /deljunk <tag>"),
    BotCommand("junkwords", "View blacklisted site tags: /junkwords"),
    BotCommand("deleteall", "Wipe files & clear MongoDB storage: /deleteall"),
    BotCommand("cleandb", "Storage wipe menu with auto-backup: /cleandb"),
    BotCommand("autodelete", "Configure file auto-deletion timer"),
    BotCommand("ban", "Blacklist user from bot: /ban <user_id>"),
    BotCommand("unban", "Unban user: /unban <user_id>"),
    BotCommand("send", "Send replied file to user: /send <user_id>"),
    BotCommand("poster", "Design HD 1080p poster: /poster <name/link>"),
    BotCommand("set_poster_brand", "Set watermark: /set_poster_brand <brand>"),
    BotCommand("set_poster_channel", "Set channel: /set_poster_channel <id>"),
    BotCommand("set_tmdb_token", "Set TMDB Bearer Token: /set_tmdb_token <tok>"),
    BotCommand("set_tmdb_key", "Set TMDB API Key: /set_tmdb_key <key>"),
    BotCommand("tmdb_status", "Check TMDB API connection: /tmdb_status"),
    BotCommand("styles", "Preview all 6 poster templates"),
    BotCommand("set_pic", "Update /start welcome photo: /set_pic <url>"),
    BotCommand("shorteners", "Toggle / view shorteners: /shortener [on|off]"),
    BotCommand("shortenerstats", "Shortener analytics: /shortenerstats"),
    BotCommand("add_shortener", "Add shortener: /add_shortener <dom> <api>"),
    BotCommand("del_shortener", "Remove shortener: /del_shortener <dom>"),
    BotCommand("set_web_url", "Set 3s gateway URL: /set_web_url <url>"),
    BotCommand("acceptall", "Approve pending requests: /acceptall [id]"),
    BotCommand("declineall", "Decline pending requests: /declineall [id]"),
    BotCommand("autoapprove", "Toggle auto-approver: /autoapprove [on|off]"),
    BotCommand("autoapprove_channels", "List whitelisted auto-approve channels"),
    BotCommand("add_autoapprove", "Add channel to auto-approve: /add_autoapprove <id>"),
    BotCommand("del_autoapprove", "Remove channel: /del_autoapprove <id>"),
    BotCommand("sharelink", "Generate protected link: /sharelink [chat_id]"),
    BotCommand("share", "Secret file share link: reply /share [time] [limit]"),
    BotCommand("test_welcome", "Preview auto-accept card: /test_welcome"),
    BotCommand("set_welcome_pic", "Set welcome photo: /set_welcome_pic"),
    BotCommand("set_welcome", "Custom auto-accept welcome: /set_welcome"),
    BotCommand("commands", "Refresh Telegram command autocomplete menu"),
    BotCommand("dl", "Universal Downloader: /dl <url> [| name]"),
    BotCommand("dlstats", "Downloader live stats & bandwidth"),
    BotCommand("setthumb", "Set custom thumbnail for downloads"),
    BotCommand("backup", "Backup MongoDB database to zip: /backup"),
    BotCommand("autobackup", "Weekly backup toggle: /autobackup [on|off]"),
    BotCommand("autoclean", "Weekly cleanup & dead groups purge: /autoclean"),
    BotCommand("restore", "Restore MongoDB backup: reply /restore"),
    BotCommand("clonechannel", "Clone files between channels: /clonechannel"),
    BotCommand("hypedrop", "Blockbuster Hype Premiere: /hypedrop <title>"),
    BotCommand("demands", "Top searched unfulfilled movies: /demands"),
    BotCommand("dailybroadcast", "Toggle daily broadcast: /dailybroadcast [on|off]"),
    BotCommand("test_broadcast", "Test broadcast preview: /test_broadcast [fresh|gem]"),
    BotCommand("send_broadcast", "Manual user broadcast: /send_broadcast [fresh|gem]"),
    BotCommand("set_broadcast_time", "Set daily broadcast time: /set_broadcast_time <HH:MM>"),
    BotCommand("addgem", "Add hidden gem: /addgem <title> | <type> | <rate> | <hook>"),
    BotCommand("listgems", "List all active gems: /listgems"),
    BotCommand("genpromo", "Generate VIP promo code: /genpromo <days> <users>"),
    BotCommand("promos", "Active promo coupons dashboard"),
    BotCommand("delpromo", "Revoke promo code: /delpromo <code>"),
    BotCommand("abroadcast", "Advanced broadcast with buttons: /abroadcast"),
    BotCommand("preview_broadcast", "Test & preview broadcast in PM"),
    BotCommand("agrp_broadcast", "Advanced broadcast to all groups"),
    BotCommand("setad", "Set time-based sponsor ad: /setad <time> [Text | Link]"),
    BotCommand("ads", "Sponsor ad campaign status & stats: /ads"),
    BotCommand("delad", "Delete active sponsor ad: /delad"),
    BotCommand("gift", "Create task-locked gift: reply /gift [claims] [time]"),
    BotCommand("giftbatch", "Create batch gift: /giftbatch <batch_id> [claims]"),
    BotCommand("setgiftchannel", "Set gift drop channel: /setgiftchannel <id|off>"),
    BotCommand("gifts", "Active gift reward campaigns dashboard"),
    BotCommand("giftstats", "Live gift reward analytics: /giftstats [id]"),
    BotCommand("delgift", "Revoke gift campaign: /delgift <gift_id>"),
    BotCommand("giftban", "Blacklist user from gifts: /giftban <user_id>"),
    BotCommand("giftunban", "Unban user from gifts: /giftunban <user_id>"),
    BotCommand("ss", "Capture video screenshots: reply /ss [count]"),
    BotCommand("maintenance", "Toggle maintenance mode: /maintenance [on|off]"),
    BotCommand("setfreelimit", "Set daily free file limit: /setfreelimit <num>")
]

async def register_all_bot_commands(client: Client) -> dict:
    """Register all bot commands in Telegram autocomplete menu across all scopes."""
    results = {
        "user_commands": 0,
        "group_admin_commands": 0,
        "admin_scoped": 0,
        "errors": []
    }

    # 1. Global / Private Chats Scope (Regular Users)
    try:
        await client.set_bot_commands(USER_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        try:
            await client.set_bot_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
        except Exception:
            pass
        results["user_commands"] = len(USER_COMMANDS)
        logger.info(f"Registered {len(USER_COMMANDS)} user commands for AllPrivateChats & Default")
    except Exception as e:
        logger.warning(f"Failed to set user commands: {e}")
        results["errors"].append(f"PrivateChats: {e}")

    # 2. Group Administrators Scope
    try:
        await client.set_bot_commands(GROUP_ADMIN_COMMANDS, scope=BotCommandScopeAllChatAdministrators())
        results["group_admin_commands"] = len(GROUP_ADMIN_COMMANDS)
        logger.info(f"Registered {len(GROUP_ADMIN_COMMANDS)} group admin commands")
    except Exception as e:
        logger.warning(f"Failed to set group admin commands: {e}")
        results["errors"].append(f"GroupAdmins: {e}")

    # 3. Dedicated Admin Scope for each Bot Admin
    for admin_id in Config.ADMINS:
        try:
            await client.set_bot_commands(ADMIN_COMMANDS[:100], scope=BotCommandScopeChat(chat_id=admin_id))
            results["admin_scoped"] += 1
            logger.info(f"Registered {len(ADMIN_COMMANDS[:100])} full admin commands for chat {admin_id}")
        except Exception as e:
            logger.warning(f"Failed to set admin commands for {admin_id}: {e}")
            results["errors"].append(f"Admin {admin_id}: {e}")

    return results
