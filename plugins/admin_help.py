"""
Admin Help & Command Documentation Module
========================================
Interactive categorized command center for bot administrators.
Displays detailed command syntax, operational explanations, and real-world examples.
"""

import logging
try:
    from hydrogram import Client, filters
    from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from config import Config

logger = logging.getLogger(__name__)

# Category definitions and order
CATEGORY_KEYS = [
    "gifts",
    "ads",
    "promos",
    "broadcast",
    "releases",
    "filestore",
    "autoapprove",
    "downloader",
    "indexer",
    "database",
    "poster",
    "streaming",
    "utils",
]

CATEGORY_TITLES = {
    "gifts": "🎁 Gifts & Task Rewards",
    "ads": "📢 Sponsor Ads & Monetization",
    "promos": "🎟️ VIP Plans & Promo Coupons",
    "broadcast": "👑 Broadcasts & Hype Premiere",
    "releases": "📢 Releases & Auto-Post",
    "filestore": "📦 File Store & Batches",
    "autoapprove": "👥 Auto-Approve & Welcome",
    "downloader": "📥 Universal Downloader",
    "indexer": "🗂️ Channel Indexer & Crawler",
    "database": "🗄️ Database, Storage & Cleanup",
    "poster": "🎨 Canvas Poster & TMDB API",
    "streaming": "⚡ Web Streaming & Players",
    "utils": "⚙️ Group Tools & Utilities",
}

# Detailed guide per category
CATEGORY_CONTENT = {
    "gifts": (
        "🎁 <b>Gifts & Task-Locked Rewards Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Create exclusive reward drops for any file or batch, locked behind channel joins or shortener bypass.</i>\n\n"
        "• <code>/gift [claims] [duration] [@channels] [flags]</code>\n"
        "<b>Aliases:</b> <code>/creategift</code>, <code>/reward</code>\n"
        "<b>Usage:</b> Reply to any file, video, APK, or document to create an instant task-locked reward link.\n"
        "<b>Supported Flags:</b>\n"
        "  • <code>-viponly</code> : Reserved strictly for VIP subscribers\n"
        "  • <code>-shortener</code> : Require 1-time shortener/ad bypass\n"
        "  • <code>-protect</code> : Content protected (Forward & Save blocked)\n"
        "  • <code>-del 3m</code> : Auto-deletes delivered file in 3 minutes\n"
        "  • <code>-unlimited</code> : No user limit & No time limit (Permanent)\n"
        "  • <code>-draft</code> : Create draft gift without posting to channel (alias: <code>-nopost</code>)\n"
        "  • <code>-img &lt;url&gt;</code> : Custom gift card banner picture\n"
        "<b>Examples:</b>\n"
        "  • <code>/gift 50 48h @AkMoviesOfficial</code>\n"
        "  • <code>/gift 0 0 @AkMoviesOfficial -shortener</code> (Permanent/Unlimited)\n"
        "  • <code>/gift 100 24h @AkMoviesOfficial -del 3m -viponly</code>\n"
        "  • <code>/gift 0 0 -draft</code> (Test in PM without auto-posting to channel)\n\n"
        "• <code>/giftbatch &lt;batch_id&gt; [claims] [duration] ...</code>\n"
        "<b>Usage:</b> Creates a gift drop for an entire multi-file season pack.\n"
        "<b>Example:</b> <code>/giftbatch b_abc123 50 48h @AkMoviesOfficial</code>\n\n"
        "• <code>/setgiftchannel &lt;@channel|-100id|off&gt;</code> (alias: <code>/giftchannel</code>)\n"
        "<b>Usage:</b> Set dedicated channel for auto-publishing gift drops. Pass <code>off</code> to disable.\n"
        "<b>Example:</b> <code>/setgiftchannel @AkMovieVerse</code> or <code>/setgiftchannel off</code>\n\n"
        "• <code>/gifts</code> | <code>/giftstats [gift_id]</code>\n"
        "<b>Usage:</b> Live dashboard of active gifts, claimed counts, views, and remaining stock.\n\n"
        "• <code>/delgift &lt;gift_id&gt;</code> (alias: <code>/revokegift</code>)\n"
        "<b>Usage:</b> Immediately cancels and revokes an active gift campaign.\n\n"
        "• <code>/giftban &lt;user_id&gt; [reason]</code>\n"
        "<b>Usage:</b> Globally blacklists a user from claiming any gifts (e.g. for leaving sponsor channels).\n\n"
        "• <code>/giftunban &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Removes user from gift blacklist."
    ),

    "ads": (
        "📢 <b>Sponsor Ads & Monetization Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Launch time-based sponsor campaigns across search results, /start, and web cinema players.</i>\n\n"
        "• <code>/setad &lt;duration&gt; [Ad Title | Target URL]</code>\n"
        "<b>Aliases:</b> <code>/addad</code>, <code>/createad</code>\n"
        "<b>Usage:</b> Activates a dynamic time-based sponsor advertisement.\n"
        "<b>Duration Formats:</b> <code>24h</code>, <code>3d</code>, <code>7d</code>, <code>30d</code>\n"
        "<b>Placements:</b>\n"
        "  • Search Results: Bottom clickable text link (Zero keyboard bloat)\n"
        "  • /start Menu: Eye-catching bottom button (Row 2)\n"
        "  • Web Players: Glowing cinema player banner\n"
        "  • <b>VIP Immunity:</b> VIP members never see ads anywhere!\n"
        "<b>Example:</b> <code>/setad 7d [🔥 1XBet 100% Bonus | https://1xbet.com]</code>\n\n"
        "• <code>/ads</code> | <code>/adstats</code> (alias: <code>/activead</code>)\n"
        "<b>Usage:</b> Live sponsor ad dashboard: remaining time, total impressions (views), and test link.\n\n"
        "• <code>/delad</code> (alias: <code>/removead</code>, <code>/clearad</code>)\n"
        "<b>Usage:</b> Immediately cancels current sponsor ad.\n\n"
        "• <code>/shortener [on|off|status]</code>\n"
        "<b>Usage:</b> Global shortener toggle. When <code>off</code>, all files are delivered 100% free and direct without ads.\n\n"
        "• <code>/shorteners</code>\n"
        "<b>Usage:</b> Lists active shorteners in rotation and traffic splits.\n\n"
        "• <code>/shortenerstats</code>\n"
        "<b>Usage:</b> Live clicks per shortener domain and VIP bypass stats.\n\n"
        "• <code>/add_shortener &lt;domain&gt; &lt;api_key&gt;</code>\n"
        "<b>Usage:</b> Adds a new shortener to rotation pool.\n"
        "<b>Example:</b> <code>/add_shortener shareus.io 83bf92...</code>\n\n"
        "• <code>/del_shortener &lt;domain&gt;</code>\n"
        "<b>Usage:</b> Removes shortener from rotation.\n\n"
        "• <code>/set_web_url &lt;url&gt;</code>\n"
        "<b>Usage:</b> Sets the 3-second intermediate web gateway URL."
    ),

    "promos": (
        "🎟️ <b>VIP Plans & Promo Codes Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Manage paid VIP subscriptions, referral bonuses, and promotional coupon codes.</i>\n\n"
        "• <code>/genpromo &lt;days&gt; &lt;max_users&gt; [code]</code>\n"
        "<b>Aliases:</b> <code>/createpromo</code>, <code>/addpromo</code>\n"
        "<b>Usage:</b> Generates a VIP coupon code with 1-click deep-link.\n"
        "<b>Example:</b> <code>/genpromo 7 50 AKVIP7</code> (7 days VIP for first 50 users)\n\n"
        "• <code>/promos</code> (alias: <code>/listpromos</code>)\n"
        "<b>Usage:</b> Dashboard of active coupons, claims count, and remaining quota.\n\n"
        "• <code>/delpromo &lt;code&gt;</code> (alias: <code>/deletepromo</code>, <code>/revokepromo</code>)\n"
        "<b>Usage:</b> Revokes an active promo code.\n\n"
        "• <code>/redeem &lt;code&gt;</code> (alias: <code>/claim</code>)\n"
        "<b>Usage:</b> Redeem a VIP coupon code (or via <code>/start redeem_&lt;code&gt;</code>).\n\n"
        "• <code>/add_premium &lt;user_id&gt; &lt;days&gt;</code>\n"
        "<b>Usage:</b> Manually grant VIP access to a user.\n"
        "<b>Example:</b> <code>/add_premium 1049173662 30</code>\n\n"
        "• <code>/remove_premium &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Revokes VIP access from a user.\n\n"
        "• <code>/premium_users</code> (alias: <code>/premium_list</code>)\n"
        "<b>Usage:</b> Lists active VIP subscribers, remaining days, and expiry dates.\n\n"
        "• <code>/plans</code> (alias: <code>/vip</code>) | <code>/myplan</code>\n"
        "<b>Usage:</b> View subscription pricing or check personal VIP status.\n\n"
        "• <code>/refer</code>\n"
        "<b>Usage:</b> Referral link generator: Earn free VIP days by inviting friends!"
    ),

    "broadcast": (
        "👑 <b>Broadcast & Premiere Alerts</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Mass messaging, advanced custom button announcements, and automated daily drops.</i>\n\n"
        "• <code>/abroadcast [-pin] [-silent]</code>\n"
        "<b>Aliases:</b> <code>/advbroadcast</code>, <code>/broadcast_btn</code>\n"
        "<b>Usage:</b> Advanced user broadcast with custom buttons and optional pin!\n"
        "<b>Syntax:</b> Reply to message with:\n"
        "<code>/abroadcast -pin\n[Button 1 | https://link1.com][Button 2 | https://link2.com]</code>\n\n"
        "• <code>/preview_broadcast</code> (alias: <code>/test_abroadcast</code>)\n"
        "<b>Usage:</b> Previews your advanced broadcast with buttons in your private chat first.\n\n"
        "• <code>/agrp_broadcast</code> (alias: <code>/adv_grp_broadcast</code>)\n"
        "<b>Usage:</b> Advanced broadcast with custom buttons to all connected groups.\n\n"
        "• <code>/broadcast</code>\n"
        "<b>Usage:</b> Reply to any message to broadcast directly to all bot users. Auto-purges blocked users in real-time.\n\n"
        "• <code>/grp_broadcast</code>\n"
        "<b>Usage:</b> Reply to any message to broadcast to all groups.\n\n"
        "• <code>/hypedrop &lt;Movie Name&gt;</code> (alias: <code>/specialdrop</code>)\n"
        "<b>Usage:</b> Blockbuster premiere card ('THE WAIT IS OVER') with HD poster, IMDb rating, and 1-click broadcast button.\n\n"
        "• <code>/demands</code> (alias: <code>/topdemands</code>)\n"
        "<b>Usage:</b> Top 15 most searched unfulfilled titles by users.\n\n"
        "• <code>/dailybroadcast [on|off|status]</code>\n"
        "<b>Usage:</b> Toggle automated evening broadcast engine.\n\n"
        "• <code>/test_broadcast [fresh|gem]</code> | <code>/send_broadcast [fresh|gem]</code>\n"
        "<b>Usage:</b> Preview or manually trigger daily broadcast right now.\n\n"
        "• <code>/set_broadcast_time &lt;HH:MM&gt;</code>\n"
        "<b>Usage:</b> Set daily broadcast trigger time in IST (e.g. <code>20:00</code>).\n\n"
        "• <code>/addgem &lt;Title&gt; | &lt;type&gt; | &lt;rating&gt; | &lt;hook&gt; [| poster]</code>\n"
        "<b>Usage:</b> Adds a hidden gem movie/anime to the rotation pool.\n\n"
        "• <code>/listgems</code>\n"
        "<b>Usage:</b> Lists active curated hidden gems.\n\n"
        "• <code>/send &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Reply to file/media to deliver directly into user's PM.\n\n"
        "• <code>/ban &lt;user_id&gt; [reason]</code> | <code>/unban &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Blacklist or unban user from bot.\n\n"
        "• <code>/set_pic &lt;url&gt;</code> (alias: <code>/setpic</code>)\n"
        "<b>Usage:</b> Update primary /start welcome banner photo/GIF."
    ),

    "releases": (
        "📢 <b>Channel Releases & Auto-Post Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Automated and manual publishing of rich movie/series cards to your updates channel.</i>\n\n"
        "• <code>/post &lt;title&gt;</code> (aliases: <code>/cpost</code>, <code>/publish</code>)\n"
        "<b>Usage:</b> Creates release card with 12-photo cycling gallery, rating, OTT tags, and 1-click publish button.\n\n"
        "• <code>/autopost [on|off|status]</code>\n"
        "<b>Usage:</b> Background auto-post engine. Auto-detects forwarded files and publishes release cards after 2-minute debounce buffer.\n\n"
        "• <code>/poststyle [1|2|3]</code> (alias: <code>/set_post_style</code>)\n"
        "<b>Usage:</b> Layout selector (1: Cinematic 16:9, 2: Vertical 2:3 Portrait, 3: Clean Compact Text).\n\n"
        "• <code>/postbutton &lt;text&gt; | &lt;url&gt;</code> (alias: <code>/postbtn</code>)\n"
        "<b>Usage:</b> Custom promotional button on Row 2 of all channel posts.\n\n"
        "• <code>/setupdateschannel &lt;chat_id&gt;</code>\n"
        "<b>Usage:</b> Sets the target channel ID where releases are published."
    ),

    "filestore": (
        "📦 <b>File Store & Batch Link Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Package multiple files or series into 1-Click shareable deep-links.</i>\n\n"
        "• <code>/batch &lt;link1&gt; &lt;link2&gt; [Title]</code>\n"
        "<b>Usage:</b> Crawl a range of channel messages and pack into a single batch deep-link.\n\n"
        "• <code>/batch</code> (Interactive PM Builder)\n"
        "<b>Usage:</b> Send <code>/batch</code> in PM, forward any files, then send <code>/done [Title]</code>.\n\n"
        "• <code>/done [Title]</code> | <code>/cancel</code>\n"
        "<b>Usage:</b> Complete or abort active interactive batch creation.\n\n"
        "• <code>/genlink [Title]</code> (alias: <code>/link</code>)\n"
        "<b>Usage:</b> Reply to any file/video to get an instant shareable link.\n\n"
        "• <code>/batches</code> (alias: <code>/batchlist</code>)\n"
        "<b>Usage:</b> Dashboard of recent batches with views and download counts.\n\n"
        "• <code>/delbatch &lt;batch_id&gt;</code>\n"
        "<b>Usage:</b> Permanently delete a batch from MongoDB.\n\n"
        "• <code>/share [duration] [uses]</code> (alias: <code>/sharefile</code>)\n"
        "<b>Usage:</b> Reply to file to create a time-limited or view-limited secret share link.\n\n"
        "• <code>/tgm</code> (aliases: <code>/img</code>, <code>/cdn</code>)\n"
        "<b>Usage:</b> Reply to photo/GIF/video to upload to Multi-CDN (Graph.org + Catbox + ImgBB fallback).\n\n"
        "• <code>/paste [Title]</code> (aliases: <code>/tgraph</code>, <code>/telegraph</code>)\n"
        "<b>Usage:</b> Reply to text or .txt file to publish a Telegraph Instant View Webpage.\n\n"
        "• <code>/editpaste &lt;url&gt; [Title]</code> (alias: <code>/epaste</code>)\n"
        "<b>Usage:</b> Update an existing Telegraph article keeping the URL unchanged.\n\n"
        "• <code>/delpaste &lt;url&gt;</code> (alias: <code>/wipepaste</code>)\n"
        "<b>Usage:</b> Wipe content from a Telegraph page created by this bot."
    ),

    "autoapprove": (
        "👥 <b>Auto-Approve & Gatekeeper Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Instant 1-second join request auto-approval across multiple channels with personalized welcome DMs.</i>\n\n"
        "• <code>/autoapprove [on|off]</code>\n"
        "<b>Usage:</b> Toggle automatic join request approval globally.\n\n"
        "• <code>/autoapprove_channels</code> (alias: <code>/autoapprovechannels</code>)\n"
        "<b>Usage:</b> Lists channels whitelisted for auto-approval.\n\n"
        "• <code>/add_autoapprove &lt;chat_id&gt;</code> | <code>/del_autoapprove &lt;chat_id&gt;</code>\n"
        "<b>Usage:</b> Add or remove channel from auto-approval whitelist.\n\n"
        "• <code>/test_welcome</code> (alias: <code>/testwelcome</code>)\n"
        "<b>Usage:</b> Live preview of auto-approval welcome card in your PM.\n\n"
        "• <code>/set_welcome_pic &lt;url&gt;</code> | <code>/del_welcome_pic</code>\n"
        "<b>Usage:</b> Set or reset welcome banner photo/GIF.\n\n"
        "• <code>/set_welcome &lt;text&gt;</code> | <code>/get_welcome</code>\n"
        "<b>Usage:</b> Set custom welcome DM template (supports <code>{mention}</code>, <code>{title}</code>, <code>{first_name}</code>).\n\n"
        "• <code>/acceptall [chat_id]</code> | <code>/declineall [chat_id]</code>\n"
        "<b>Usage:</b> Instantly approve or decline all backlog join requests.\n\n"
        "• <code>/sharelink [chat_id]</code> (alias: <code>/createlink</code>)\n"
        "<b>Usage:</b> Generates an admin join-request invite link."
    ),

    "downloader": (
        "📥 <b>Universal Downloader Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>High-speed remote file downloader + Zero-Load Telegram Cloud Forwarder.</i>\n\n"
        "• <code>/dl &lt;url&gt; [| filename]</code> (alias: <code>/download</code>)\n"
        "<b>Usage:</b> Downloads from external URLs (YouTube, Instagram, TeraBox, direct links) or forwards Telegram posts with 0 server load!\n"
        "  • Single Post: <code>/dl https://t.me/channel/123</code>\n"
        "  • Range: <code>/dl https://t.me/channel/100-110</code> (Max 10 files)\n\n"
        "• <code>/dlstats</code> (alias: <code>/downloaderstats</code>)\n"
        "<b>Usage:</b> Downloader performance: active tasks, bandwidth, RAM, disk.\n\n"
        "• <code>/setthumb</code> | <code>/showthumb</code> | <code>/delthumb</code>\n"
        "<b>Usage:</b> Set, view, or delete permanent custom thumbnail for downloads."
    ),

    "indexer": (
        "🗂️ <b>Channel Indexer & Media Crawler</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Batch crawl channels to index all video and document files into MongoDB.</i>\n\n"
        "• <code>/index &lt;channel_or_link&gt;</code>\n"
        "<b>Usage:</b> Starts indexing all media from a channel into MongoDB.\n"
        "<b>Example:</b> <code>/index -1002001671856</code> or <code>/index https://t.me/c/2001671856/10</code>\n\n"
        "• <code>/index resume</code>\n"
        "<b>Usage:</b> Resumes an interrupted channel crawl from exact bookmark.\n\n"
        "• <code>/indexall &lt;id1&gt; &lt;id2&gt; ...</code> (alias: <code>/crawlall</code>)\n"
        "<b>Usage:</b> Multi-channel sequential crawl.\n\n"
        "• <code>/checkpoints</code> (alias: <code>/indexcheckpoints</code>)\n"
        "<b>Usage:</b> Lists interrupted indexing bookmarks (clear via <code>/checkpoints clear</code>).\n\n"
        "• <code>/setskip &lt;number&gt;</code>\n"
        "<b>Usage:</b> Skip specified number of messages before indexing starts.\n\n"
        "• <code>/stopindex</code> (alias: <code>/cancelindex</code>)\n"
        "<b>Usage:</b> Immediately aborts active indexing crawl."
    ),

    "database": (
        "🗄️ <b>Database, Storage & Cleanup</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Monitor MongoDB metrics, purge junk files, watermark cleaner, and disaster recovery.</i>\n\n"
        "• <code>/stats</code>\n"
        "<b>Usage:</b> Total indexed files, registered users, connected groups, uptime, and RAM.\n\n"
        "• <code>/targetdb [1|2|auto]</code> (alias: <code>/setwritedb</code>)\n"
        "<b>Usage:</b> Multi-cluster write routing (auto-switches to Secondary DB at 440MB).\n\n"
        "• <code>/autoclean</code> (aliases: <code>/housekeeping</code>, <code>/cleanhouse</code>)\n"
        "<b>Usage:</b> Full database housekeeping: Purges dead groups, expired batches, share links, expired verifications, and expired ads/gifts!\n\n"
        "• <code>/deletecam</code> (aliases: <code>/purgecam</code>, <code>/deletefiles</code>)\n"
        "<b>Usage:</b> Purges low-quality CamRip / PreDVD / HDTS files.\n\n"
        "• <code>/cleanduplicates</code> (aliases: <code>/purgeduplicates</code>, <code>/del_duplicates</code>)\n"
        "<b>Usage:</b> Purges 100% duplicate files while preserving primary copy.\n\n"
        "• <code>/cleanfiles</code> (aliases: <code>/cleanfilenames</code>, <code>/fixfilenames</code>)\n"
        "<b>Usage:</b> Watermark Cleaner: Cleans website watermarks (1TamilMV, HDHub4u) from filenames in MongoDB!\n\n"
        "• <code>/delbyname &lt;movie_name&gt;</code> (aliases: <code>/deletebyname</code>, <code>/purgebyname</code>)\n"
        "<b>Usage:</b> Copyright Quick-Purge: Deletes all resolutions of a movie.\n\n"
        "• <code>/addjunk &lt;tag&gt;</code> | <code>/deljunk &lt;tag&gt;</code> | <code>/junkwords</code>\n"
        "<b>Usage:</b> Manage custom pirated site tags cleaner blacklist.\n\n"
        "• <code>/deleteall confirm</code> (aliases: <code>/wipedb</code>, <code>/cleandb</code>)\n"
        "<b>Usage:</b> ⚠️ Wipes all indexed files from MongoDB.\n\n"
        "• <code>/backup</code> (alias: <code>/dbbackup</code>) | <code>/restore</code> (alias: <code>/dbrestore</code>)\n"
        "<b>Usage:</b> Backup MongoDB collections to zip or restore.\n\n"
        "• <code>/autobackup [on|off]</code>\n"
        "<b>Usage:</b> Automated Sunday Disaster Recovery backup scheduler.\n\n"
        "• <code>/clonechannel &lt;source_id&gt; &lt;target_id&gt; [limit]</code>\n"
        "<b>Usage:</b> Clones files between storage channels for disaster recovery.\n\n"
        "• <code>/autodelete [seconds|off]</code> (aliases: <code>/set_autodelete</code>, <code>/deltime</code>)\n"
        "<b>Usage:</b> Set auto-delete timer for delivered search files."
    ),

    "poster": (
        "🎨 <b>Canvas Poster Studio & TMDB API</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Automated 1080p promotional poster generator with TMDB metadata & custom branding.</i>\n\n"
        "• <code>/poster &lt;title or TMDB link&gt;</code> (aliases: <code>/thumbnail</code>, <code>/art</code>)\n"
        "<b>Usage:</b> Designs an HD 1080p canvas promotional poster card.\n\n"
        "• <code>/styles</code> (alias: <code>/posterstyles</code>)\n"
        "<b>Usage:</b> Interactive preview of all 6 poster rendering themes.\n\n"
        "• <code>/set_poster_brand &lt;brand&gt;</code> (aliases: <code>/setposterbrand</code>, <code>/setbrand</code>)\n"
        "<b>Usage:</b> Sets custom watermark text on canvas posters.\n\n"
        "• <code>/set_poster_channel &lt;channel_id&gt;</code> (alias: <code>/setposterchannel</code>)\n"
        "<b>Usage:</b> Sets default channel for publishing canvas posters.\n\n"
        "• <code>/set_tmdb_key &lt;api_key&gt;</code> | <code>/set_tmdb_token &lt;token&gt;</code>\n"
        "<b>Usage:</b> Update TMDB v3 API Key or v4 Bearer Token.\n\n"
        "• <code>/tmdb_status</code> (aliases: <code>/tmdbstatus</code>, <code>/tmdb</code>)\n"
        "<b>Usage:</b> Tests TMDB API connectivity, key validation, and ping."
    ),

    "streaming": (
        "⚡ <b>Web Streaming & Player Controls</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>High-speed web video streaming, 7-server online cinema player, and download toggles.</i>\n\n"
        "• <code>/streaming [on|off|status]</code> (aliases: <code>/streamtoggle</code>, <code>/togglestream</code>)\n"
        "<b>Usage:</b> Toggle fast video streaming & web player globally.\n\n"
        "• <code>/stream_download [on|off|status]</code> (alias: <code>/player_download</code>)\n"
        "<b>Usage:</b> Toggle direct fast download inside web streaming player. When off, download redirects to bot while stream stays 100% free.\n\n"
        "• <code>/watch &lt;movie_name&gt;</code> (alias: <code>/streamonline</code>)\n"
        "<b>Usage:</b> Search and stream directly with multi-server online cinema player.\n\n"
        "• <code>/stream</code> (alias: <code>/streamlink</code>)\n"
        "<b>Usage:</b> Reply to video/file to generate web streaming and direct player links."
    ),

    "utils": (
        "⚙️ <b>Group Automation & General Utilities</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Manage group settings, manual keyword auto-replies, and utilities.</i>\n\n"
        "• <code>/adminhelp</code> (aliases: <code>/ahelp</code>, <code>/admincommands</code>)\n"
        "<b>Usage:</b> Open interactive Master Admin Command Center or jump directly: <code>/ahelp gifts</code>.\n\n"
        "• <code>/start</code> | <code>/help</code>\n"
        "<b>Usage:</b> Main bot menu and end-user interactive help guide.\n\n"
        "• <code>/settings</code>\n"
        "<b>Usage:</b> Group control panel (Single/Double buttons, spell check, IMDb poster, auto-delete).\n\n"
        "• <code>/connect [group_id]</code> | <code>/disconnect [group_id]</code>\n"
        "<b>Usage:</b> Connect or disconnect group to manage settings remotely via PM.\n\n"
        "• <code>/shortlink &lt;domain&gt; &lt;api_key&gt;</code>\n"
        "<b>Usage:</b> Configure custom group shortener so group owners earn revenue.\n\n"
        "• <code>/filter &lt;trigger&gt; &lt;reply&gt;</code> | <code>/filters</code>\n"
        "<b>Usage:</b> Create or list manual keyword auto-reply filters in group.\n\n"
        "• <code>/stop &lt;trigger&gt;</code> | <code>/stopall</code>\n"
        "<b>Usage:</b> Delete specific or all manual keyword filters.\n\n"
        "• <code>/id</code> | <code>/info [user_id]</code>\n"
        "<b>Usage:</b> Returns Telegram ID or profile info.\n\n"
        "• <code>/imdb &lt;movie_name&gt;</code>\n"
        "<b>Usage:</b> Fetches IMDb synopsis, rating, genres, and cast.\n\n"
        "• <code>/request &lt;movie_name&gt;</code> (alias: <code>/req</code>) | <code>/myrequests</code>\n"
        "<b>Usage:</b> Submit or view movie/series requests with voting buttons.\n\n"
        "• <code>/myalerts</code>\n"
        "<b>Usage:</b> View your active movie upload notifications.\n\n"
        "• <code>/commands</code>\n"
        "<b>Usage:</b> Syncs and registers all bot commands with Telegram autocomplete menu."
    ),
}

# Condensed Full Cheat Sheet (Guaranteed < 4096 Telegram char limit)
CHEAT_SHEET_TEXT = (
    "📜 <b>Master Admin Commands Quick Reference (A-Z)</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote expandable>"
    "<b>🎁 GIFTS &amp; REWARDS:</b>\n"
    "• <code>/gift</code> | <code>/giftbatch</code> — Create task-locked reward\n"
    "• <code>/setgiftchannel</code> — Auto-post gift channel\n"
    "• <code>/gifts</code> | <code>/giftstats</code> | <code>/delgift</code> | <code>/giftban</code> | <code>/giftunban</code>\n\n"
    "<b>📢 SPONSOR ADS &amp; SHORTENERS:</b>\n"
    "• <code>/setad</code> | <code>/ads</code> | <code>/delad</code> — Time-based sponsor ads\n"
    "• <code>/shorteners</code> | <code>/shortenerstats</code> | <code>/set_web_url</code>\n"
    "• <code>/add_shortener</code> | <code>/del_shortener</code>\n\n"
    "<b>🎟️ VIP &amp; PROMO CODES:</b>\n"
    "• <code>/genpromo</code> | <code>/promos</code> | <code>/delpromo</code> | <code>/redeem</code>\n"
    "• <code>/add_premium</code> | <code>/remove_premium</code> | <code>/premium_users</code>\n"
    "• <code>/plans</code> | <code>/myplan</code> | <code>/refer</code>\n\n"
    "<b>👑 BROADCAST &amp; HYPE PREMIERE:</b>\n"
    "• <code>/broadcast</code> | <code>/grp_broadcast</code> | <code>/send</code>\n"
    "• <code>/abroadcast</code> | <code>/agrp_broadcast</code> | <code>/preview_broadcast</code>\n"
    "• <code>/hypedrop</code> | <code>/specialdrop</code> | <code>/demands</code>\n"
    "• <code>/dailybroadcast</code> | <code>/send_broadcast</code> | <code>/test_broadcast</code>\n"
    "• <code>/set_broadcast_time</code> | <code>/addgem</code> | <code>/listgems</code>\n"
    "• <code>/ban</code> | <code>/unban</code> | <code>/set_pic</code>\n\n"
    "<b>📢 RELEASES &amp; AUTO-POST:</b>\n"
    "• <code>/post</code> | <code>/autopost</code> — Release card &amp; auto-publish\n"
    "• <code>/poststyle</code> | <code>/postbutton</code> | <code>/setupdateschannel</code>\n\n"
    "<b>📦 FILE STORE &amp; BATCHES:</b>\n"
    "• <code>/batch</code> | <code>/genlink</code> | <code>/batches</code> | <code>/delbatch</code> | <code>/share</code>\n"
    "• <code>/tgm</code> | <code>/paste</code> | <code>/editpaste</code> | <code>/delpaste</code>\n\n"
    "<b>👥 AUTO-APPROVE &amp; GATEKEEPER:</b>\n"
    "• <code>/autoapprove</code> | <code>/autoapprove_channels</code>\n"
    "• <code>/add_autoapprove</code> | <code>/del_autoapprove</code> | <code>/sharelink</code>\n"
    "• <code>/test_welcome</code> | <code>/set_welcome_pic</code> | <code>/set_welcome</code>\n"
    "• <code>/get_welcome</code> | <code>/acceptall</code> | <code>/declineall</code>\n\n"
    "<b>📥 DOWNLOADER &amp; THUMBNAILS:</b>\n"
    "• <code>/dl</code> | <code>/dlstats</code> — Downloader engine\n"
    "• <code>/setthumb</code> | <code>/showthumb</code> | <code>/delthumb</code>\n\n"
    "<b>🗂️ CHANNEL INDEXER &amp; CRAWLER:</b>\n"
    "• <code>/index</code> | <code>/indexall</code> | <code>/stopindex</code>\n"
    "• <code>/checkpoints</code> | <code>/setskip</code>\n\n"
    "<b>🗄️ DATABASE &amp; STORAGE CLEANUP:</b>\n"
    "• <code>/stats</code> | <code>/targetdb</code> | <code>/backup</code> | <code>/autobackup</code>\n"
    "• <code>/autoclean</code> | <code>/restore</code> | <code>/clonechannel</code>\n"
    "• <code>/deletecam</code> | <code>/cleanduplicates</code> | <code>/cleanfiles</code>\n"
    "• <code>/delbyname</code> | <code>/addjunk</code> | <code>/deljunk</code> | <code>/junkwords</code>\n"
    "• <code>/deleteall</code> | <code>/cleandb</code> | <code>/autodelete</code>\n\n"
    "<b>🎨 CANVAS POSTER &amp; TMDB API:</b>\n"
    "• <code>/poster</code> | <code>/styles</code> | <code>/tmdb_status</code>\n"
    "• <code>/set_poster_brand</code> | <code>/set_poster_channel</code>\n"
    "• <code>/set_tmdb_key</code> | <code>/set_tmdb_token</code>\n\n"
    "<b>⚡ WEB STREAMING &amp; PLAYERS:</b>\n"
    "• <code>/streaming</code> | <code>/stream_download</code>\n"
    "• <code>/watch</code> | <code>/stream</code>\n\n"
    "<b>⚙️ GROUP TOOLS &amp; UTILITIES:</b>\n"
    "• <code>/settings</code> | <code>/connect</code> | <code>/disconnect</code> | <code>/shortlink</code>\n"
    "• <code>/filter</code> | <code>/filters</code> | <code>/stop</code> | <code>/stopall</code>\n"
    "• <code>/id</code> | <code>/info</code> | <code>/imdb</code> | <code>/request</code> | <code>/myrequests</code>\n"
    "• <code>/myalerts</code> | <code>/start</code> | <code>/help</code> | <code>/commands</code> | <code>/adminhelp</code>\n"
    "</blockquote>\n\n"
    "💡 <i>Tap any category below for full parameters &amp; examples!</i>"
)


def get_admin_hub_markup():
    """Build the main category selection keyboard for admins."""
    buttons = [
        [
            InlineKeyboardButton("🎁 Gifts & Rewards", callback_data="ahelp_cat:gifts"),
            InlineKeyboardButton("📢 Ads & Shorteners", callback_data="ahelp_cat:ads")
        ],
        [
            InlineKeyboardButton("🎟️ VIP & Promo Codes", callback_data="ahelp_cat:promos"),
            InlineKeyboardButton("👑 Broadcasts & Hype", callback_data="ahelp_cat:broadcast")
        ],
        [
            InlineKeyboardButton("📢 Releases & Auto-Post", callback_data="ahelp_cat:releases"),
            InlineKeyboardButton("📦 File Store & Batches", callback_data="ahelp_cat:filestore")
        ],
        [
            InlineKeyboardButton("👥 Auto-Approve & Join", callback_data="ahelp_cat:autoapprove"),
            InlineKeyboardButton("📥 Downloader Engine", callback_data="ahelp_cat:downloader")
        ],
        [
            InlineKeyboardButton("🗂️ Channel Indexer", callback_data="ahelp_cat:indexer"),
            InlineKeyboardButton("🗄️ Database & Cleanup", callback_data="ahelp_cat:database")
        ],
        [
            InlineKeyboardButton("🎨 Poster & TMDB API", callback_data="ahelp_cat:poster"),
            InlineKeyboardButton("⚡ Web Streaming", callback_data="ahelp_cat:streaming")
        ],
        [
            InlineKeyboardButton("⚙️ Group Tools & Utils", callback_data="ahelp_cat:utils"),
            InlineKeyboardButton("👤 User Guide", callback_data="ahelp_user")
        ],
        [
            InlineKeyboardButton("📜 Master Cheat Sheet (A-Z)", callback_data="ahelp_all"),
            InlineKeyboardButton("🔄 Sync TG Menu", callback_data="ahelp_sync")
        ],
        [
            InlineKeyboardButton("❌ Close Menu", callback_data="ahelp_close")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_category_markup(current_key: str):
    """Build navigation buttons for a specific category: Prev, Back to Hub, Next."""
    idx = CATEGORY_KEYS.index(current_key) if current_key in CATEGORY_KEYS else 0
    prev_key = CATEGORY_KEYS[(idx - 1) % len(CATEGORY_KEYS)]
    next_key = CATEGORY_KEYS[(idx + 1) % len(CATEGORY_KEYS)]

    buttons = [
        [
            InlineKeyboardButton("◀️ Prev", callback_data=f"ahelp_cat:{prev_key}"),
            InlineKeyboardButton("🔙 Back to Hub", callback_data="ahelp_home"),
            InlineKeyboardButton("Next ▶️", callback_data=f"ahelp_cat:{next_key}")
        ],
        [
            InlineKeyboardButton("📜 Master Cheat Sheet", callback_data="ahelp_all"),
            InlineKeyboardButton("👤 User Help", callback_data="ahelp_user")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_hub_text():
    return (
        "👑 <b>AkMovieVerse — Master Admin Command Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to your Comprehensive Administrator Documentation Hub.\n"
        "Every single command, parameter, flag, and copy-paste example is documented here.\n\n"
        "📂 <b>Select a category below to explore:</b>"
    )


async def send_admin_help_hub(client: Client, message: Message):
    """Display the primary admin command center hub."""
    text = get_hub_text()
    markup = get_admin_hub_markup()
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


# Direct commands: /adminhelp, /admincommands, /ahelp
@Client.on_message(filters.command(["adminhelp", "admincommands", "ahelp"]))
async def admin_help_command(client: Client, message: Message):
    """Admin-only dedicated command guide with keyword jump support."""
    if not Config.is_admin(message.from_user.id):
        await message.reply_text("⛔ <b>Access Denied:</b> This command is strictly reserved for Bot Administrators.")
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) > 1:
        query_key = parts[1].strip().lower()
        matched_cat = None
        for k in CATEGORY_KEYS:
            if query_key in k or k in query_key:
                matched_cat = k
                break
        if matched_cat:
            cat_text = CATEGORY_CONTENT[matched_cat]
            markup = get_category_markup(matched_cat)
            return await message.reply_text(cat_text, reply_markup=markup, disable_web_page_preview=True)

    await send_admin_help_hub(client, message)


# Callback Query Handler for Admin Help navigation
@Client.on_callback_query(filters.regex(r"^ahelp_"))
async def admin_help_callback(client: Client, query: CallbackQuery):
    """Handle interactive admin help navigation callbacks."""
    if not Config.is_admin(query.from_user.id):
        await query.answer("⛔ Access Denied! Admins only.", show_alert=True)
        return

    data = query.data

    try:
        if data == "ahelp_close":
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.answer("Menu closed.")
            return

        elif data == "ahelp_home":
            text = get_hub_text()
            markup = get_admin_hub_markup()
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            await query.answer()

        elif data.startswith("ahelp_cat:"):
            cat_key = data.split(":", 1)[1]
            if cat_key in CATEGORY_CONTENT:
                text = CATEGORY_CONTENT[cat_key]
                markup = get_category_markup(cat_key)
                await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
                await query.answer()
            else:
                await query.answer("Category not found.", show_alert=True)

        elif data == "ahelp_all":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Hub", callback_data="ahelp_home")],
                [
                    InlineKeyboardButton("👤 User Help", callback_data="ahelp_user"),
                    InlineKeyboardButton("🔄 Sync TG Menu", callback_data="ahelp_sync")
                ]
            ])
            await query.message.edit_text(CHEAT_SHEET_TEXT, reply_markup=markup, disable_web_page_preview=True)
            await query.answer()

        elif data == "ahelp_user":
            user_text = (
                "👤 <b>Auto Filter Bot — User Help & Commands</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "• <b>Search Files:</b> Just type any movie or document title in chat or group!\n"
                "• <b>Single/Double Layout:</b> Use <code>/settings</code> in group to switch button view\n"
                "• <b>Quality, Lang & Season:</b> Use instant sub-filters on search results\n"
                "• <b>Inline Search:</b> Type <code>@Akmovieszone_bot movie_name</code> in any chat\n"
                "• <b>Group Connections:</b> Send <code>/connect</code> in group, manage via PM\n"
                "• <b>VIP Plans:</b> Use <code>/plans</code> to view ad-free download options\n"
                "• <b>Refer & Earn:</b> Use <code>/refer</code> to earn free VIP days!"
            )
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Hub", callback_data="ahelp_home")]
            ])
            await query.message.edit_text(user_text, reply_markup=markup, disable_web_page_preview=True)
            await query.answer()

        elif data == "ahelp_sync":
            await query.answer("🔄 Syncing commands with Telegram servers...", show_alert=False)
            from utils.bot_commands import register_all_bot_commands
            results = await register_all_bot_commands(client)
            await query.answer(
                f"✅ Commands Synced!\n• Users: {results['user_commands']}\n• Admins: {results['admin_scoped']}",
                show_alert=True
            )

    except Exception as e:
        logger.error(f"Error in admin_help_callback: {e}", exc_info=True)
        await query.answer("Notice: Screen refreshed.")
