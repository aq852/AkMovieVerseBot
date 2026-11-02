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
    "releases",
    "filestore",
    "autoapprove",
    "downloader",
    "indexer",
    "monetization",
    "database",
    "broadcast",
    "poster",
    "utils",
]

CATEGORY_TITLES = {
    "releases": "📢 Channel Releases & Auto-Post",
    "filestore": "📦 File Store & Batch Generator",
    "autoapprove": "👥 Auto-Approve & Welcome",
    "downloader": "📥 Universal Downloader",
    "indexer": "🗂️ Channel Indexer & Crawler",
    "monetization": "💎 VIP, Plans & Shorteners",
    "database": "🗄️ File Management & Database",
    "broadcast": "👑 Broadcast & User Control",
    "poster": "🎨 Canvas Poster & TMDB API",
    "utils": "⚙️ Group Tools & Utilities",
}

# Detailed guide per category
CATEGORY_CONTENT = {
    "releases": (
        "📢 <b>Channel Releases & Auto-Post Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Automated and manual publishing of rich movie/series cards to your updates channel.</i>\n\n"
        "• <code>/post &lt;movie or series title&gt;</code>\n"
        "<b>Usage:</b> Searches indexed files + TMDB to create an interactive release preview with a 12-photo cycling gallery, expandable blockquote (IMDb rating, genres, OTT tag, audio, qualities), and a 1-click <code>[🚀 Publish to Channel]</code> button.\n"
        "<b>Example:</b> <code>/post Mirzapur</code> or <code>/post Gajab Raat</code>\n\n"
        "• <code>/autopost [on|off|status]</code>\n"
        "<b>Usage:</b> Toggles the automatic background release engine. When enabled, new files forwarded to storage channels enter a 2-minute debounce buffer, fetch TMDB metadata, and auto-publish or edit/upgrade channel posts.\n"
        "<b>Example:</b> <code>/autopost on</code> | <code>/autopost status</code>\n\n"
        "• <code>/poststyle [1|2|3]</code>\n"
        "<b>Usage:</b> Select active channel post layout design:\n"
        "  • <b>Style 1:</b> Cinematic Widescreen (16:9 Backdrop + Expandable Storyline)\n"
        "  • <b>Style 2:</b> Minimalist Single-Poster (2:3 Vertical Portrait Poster + Crisp 5-Line Info)\n"
        "  • <b>Style 3:</b> Clean Compact Text (Ultra-fast & lightweight release)\n"
        "<b>Example:</b> <code>/poststyle 2</code> (or run <code>/poststyle</code> for interactive selector)\n\n"
        "• <code>/postbutton &lt;text&gt; | &lt;url&gt;</code>\n"
        "<b>Usage:</b> Sets a custom promotional button on Row 2 of all channel release posts (e.g. Backup Channel, Discussion Group).\n"
        "<b>Example:</b> <code>/postbutton 📢 Join Backup Channel | https://t.me/AkMovieVerse</code>\n"
        "<b>Disable:</b> <code>/postbutton off</code> | <b>Status:</b> <code>/postbutton status</code>\n\n"
        "• <code>/setupdateschannel &lt;chat_id&gt;</code>\n"
        "<b>Usage:</b> Sets the target updates channel ID where release cards and auto-posts are published.\n"
        "<b>Example:</b> <code>/setupdateschannel -1003537939374</code>"
    ),

    "filestore": (
        "📦 <b>File Store & Batch Link Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Package multiple files or series into 1-Click shareable deep-links.</i>\n\n"
        "• <code>/batch &lt;link1&gt; &lt;link2&gt; [Title]</code>\n"
        "<b>Usage:</b> Crawl a range of channel messages and pack all media files into a single batch deep-link.\n"
        "<b>Example:</b> <code>/batch https://t.me/c/123/10 https://t.me/c/123/20 Mirzapur S03 Pack</code>\n\n"
        "• <code>/batch</code> (Interactive PM Builder)\n"
        "<b>Usage:</b> Send <code>/batch</code> in PM without arguments. Forward any number of files, then send <code>/done [Title]</code> when finished!\n\n"
        "• <code>/genlink</code> (alias: <code>/link</code>)\n"
        "<b>Usage:</b> Reply to any file/video with <code>/genlink [Title]</code> to get an instant shareable link.\n\n"
        "• <code>/batches</code> (alias: <code>/batchlist</code>)\n"
        "<b>Usage:</b> Displays dashboard of recent batches with views, downloads, and 1-click delete buttons.\n\n"
        "• <code>/delbatch &lt;batch_id&gt;</code>\n"
        "<b>Usage:</b> Permanently delete a batch link from MongoDB.\n\n"
        "• <code>/tgm</code> (alias: <code>/img</code>, <code>/cdn</code>)\n"
        "<b>Usage:</b> Reply to any photo, sticker, GIF, or video with <code>/tgm</code> to upload to Telegraph / Multi-CDN (Graph.org + Catbox + ImgBB auto-fallback) and get a permanent direct link.\n\n"
        "• <code>/paste [Title]</code> (alias: <code>/tgraph</code>, <code>/telegraph</code>)\n"
        "<b>Usage:</b> Reply to any text message, collection list, or .txt file to publish a beautiful Telegraph Instant View Webpage.\n\n"
        "• <code>/editpaste &lt;url&gt; [New Title]</code> (alias: <code>/epaste</code>)\n"
        "<b>Usage:</b> Reply to updated text or send <code>/editpaste &lt;link&gt; | New content</code> to update an existing Telegraph article. The URL remains unchanged!\n\n"
        "• <code>/delpaste &lt;url&gt;</code> (alias: <code>/wipepaste</code>)\n"
        "<b>Usage:</b> Wipe all content from a Telegraph page created by this bot."
    ),

    "autoapprove": (
        "👥 <b>Auto-Approve & Gatekeeper Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Instant 1-second join request auto-approval across multiple channels with personalized welcome DMs.</i>\n\n"
        "• <code>/autoapprove [on|off]</code>\n"
        "<b>Usage:</b> Toggles automatic join request approval globally on or off.\n\n"
        "• <code>/autoapprove_channels</code>\n"
        "<b>Usage:</b> Lists all active channels currently whitelisted for instant join approval.\n\n"
        "• <code>/add_autoapprove &lt;chat_id&gt;</code>\n"
        "<b>Usage:</b> Whitelists a new channel for instant join request auto-approval.\n"
        "<b>Example:</b> <code>/add_autoapprove -1003537939374</code>\n\n"
        "• <code>/del_autoapprove &lt;chat_id&gt;</code>\n"
        "<b>Usage:</b> Removes a channel from the auto-approval whitelist.\n"
        "<b>Example:</b> <code>/del_autoapprove -1003537939374</code>\n\n"
        "• <code>/test_welcome</code>\n"
        "<b>Usage:</b> Sends a live test preview of the auto-approval welcome card to your private chat with action buttons.\n\n"
        "• <code>/set_welcome_pic &lt;url&gt;</code>\n"
        "<b>Usage:</b> Sets a custom banner photo/GIF for the welcome DM (or reply to any photo with this command).\n\n"
        "• <code>/set_welcome &lt;text&gt;</code>\n"
        "<b>Usage:</b> Customizes the text template of the welcome DM. Supports <code>{mention}</code>, <code>{title}</code>, <code>{first_name}</code> tags.\n\n"
        "• <code>/get_welcome</code>\n"
        "<b>Usage:</b> Displays the current auto-approval welcome DM text and photo status.\n\n"
        "• <code>/del_welcome</code>\n"
        "<b>Usage:</b> Resets the welcome DM text back to default.\n\n"
        "• <code>/acceptall [chat_id]</code>\n"
        "<b>Usage:</b> Instantly approves all pending backlog join requests in target channel.\n"
        "<b>Example:</b> <code>/acceptall -1003537939374</code>\n\n"
        "• <code>/declineall [chat_id]</code>\n"
        "<b>Usage:</b> Declines all pending backlog join requests in target channel.\n\n"
        "• <code>/sharelink [chat_id]</code>\n"
        "<b>Usage:</b> Generates an admin-approved join request invite link (<code>creates_join_request=True</code>) for your channel."
    ),

    "downloader": (
        "📥 <b>Universal Downloader Engine</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>High-speed remote file & media downloader + Zero-Load Telegram Cloud Forwarder.</i>\n\n"
        "• <code>/dl &lt;url&gt; [| filename]</code>\n"
        "<b>Usage:</b> Downloads video/file from external sites (YouTube, Instagram, TeraBox, Direct URLs) or forwards directly from Telegram posts with 0 server load!\n"
        "<b>Telegram Cloud Forwarding:</b>\n"
        "  • Single Post: <code>/dl https://t.me/channel/123</code>\n"
        "  • Batch Range: <code>/dl https://t.me/channel/100-110</code> (Capped to max 10 for safety)\n"
        "  • <b>Zero Server Load:</b> Instant Telegram cloud transfer without consuming server bandwidth or disk space.\n"
        "  • <b>Public Access:</b> Open to all users with 15s cooldown & force-sub check.\n"
        "  • <b>Auto-Delete in PM:</b> Delivered files + copyright notice are automatically deleted after 15 minutes.\n"
        "  • <b>Dump Backup:</b> Copied files are silently forwarded to dump channel for admin backup without polluting the search database.\n\n"
        "• <code>/dlstats</code>\n"
        "<b>Usage:</b> Displays live downloader performance: active download tasks, download/upload bandwidth, RAM, and disk space.\n\n"
        "• <code>/setthumb</code>\n"
        "<b>Usage:</b> Reply to any photo to save it as the permanent custom thumbnail for all future downloaded video uploads.\n\n"
        "• <code>/showthumb</code>\n"
        "<b>Usage:</b> Displays the currently active custom download thumbnail.\n\n"
        "• <code>/delthumb</code>\n"
        "<b>Usage:</b> Deletes the custom thumbnail and restores automatic video frame extraction."
    ),

    "indexer": (
        "🗂️ <b>Channel Indexer & Media Crawler</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Batch crawl public and private channels to index all video and document files into MongoDB.</i>\n\n"
        "• <code>/index &lt;channel_or_link&gt;</code>\n"
        "<b>Usage:</b> Starts indexing all media from a channel username, channel ID, or message link into MongoDB.\n"
        "<b>Example:</b> <code>/index -1002001671856</code> or <code>/index https://t.me/c/2001671856/10</code>\n\n"
        "• <code>/index resume</code>\n"
        "<b>Usage:</b> Resumes an interrupted channel crawl from its exact saved checkpoint bookmark.\n\n"
        "• <code>/checkpoints</code>\n"
        "<b>Usage:</b> Lists any interrupted indexing bookmarks (or clear them with <code>/checkpoints clear</code>).\n\n"
        "• <code>/setskip &lt;number&gt;</code>\n"
        "<b>Usage:</b> Sets a message offset number. The crawler will skip messages up to this count before indexing starts.\n"
        "<b>Example:</b> <code>/setskip 2500</code>\n\n"
        "• <code>/stopindex</code>\n"
        "<b>Usage:</b> Immediately aborts and cancels the active channel indexing crawl."
    ),

    "monetization": (
        "💎 <b>VIP, Monetization & Shorteners</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Manage paid VIP subscribers, multi-shortener rotation pools, and intermediate web gateways.</i>\n\n"
        "• <code>/add_premium &lt;user_id&gt; &lt;days&gt;</code>\n"
        "<b>Usage:</b> Grants VIP ad-free access to a user for specified days. VIP members bypass shorteners, token verifications, and cooldowns.\n"
        "<b>Example:</b> <code>/add_premium 1049173662 30</code>\n\n"
        "• <code>/remove_premium &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Immediately revokes VIP access from a user.\n"
        "<b>Example:</b> <code>/remove_premium 1049173662</code>\n\n"
        "• <code>/premium_users</code>\n"
        "<b>Usage:</b> Lists all active VIP subscribers with user ID, name, remaining days, and expiry dates.\n\n"
        "• <code>/shortener [on|off|status]</code>\n"
        "<b>Usage:</b> Enable or disable URL shorteners globally. When <code>off</code>, all files are delivered 100% free and direct without any ads, and 'Remove ads' buttons are hidden. Persists across restarts in MongoDB.\n"
        "<b>Example:</b> <code>/shortener off</code> | <code>/shortener on</code>\n\n"
        "• <code>/streaming [on|off|status]</code> (alias: <code>/stream on|off</code>)\n"
        "<b>Usage:</b> Toggle fast video streaming & web player globally. Persists across restarts in MongoDB.\n"
        "<b>Example:</b> <code>/streaming off</code> | <code>/streaming on</code>\n\n"
        "• <code>/shorteners</code>\n"
        "<b>Usage:</b> Lists all active shortener domains in rotation, API keys, and traffic split percentages.\n\n"
        "• <code>/shortenerstats</code>\n"
        "<b>Usage:</b> Displays live daily clicks per shortener domain, VIP bypass counts, and all-time traffic statistics.\n\n"
        "• <code>/add_shortener &lt;domain&gt; &lt;api_key&gt;</code>\n"
        "<b>Usage:</b> Adds a new URL shortener to the dynamic multi-shortener rotation pool.\n"
        "<b>Example:</b> <code>/add_shortener shareus.io 83bf92...</code>\n\n"
        "• <code>/del_shortener &lt;domain&gt;</code>\n"
        "<b>Usage:</b> Removes a shortener domain from the rotation pool.\n\n"
        "• <code>/set_web_url &lt;url&gt;</code>\n"
        "<b>Usage:</b> Sets the 5-second intermediate web gateway URL (e.g. Cloudflare Worker) for secure link verification.\n\n"
        "• <code>/stream_download [on|off|status]</code>\n"
        "<b>Usage:</b> Toggle direct fast download inside the web streaming player. When turned <code>off</code>, the web player download button redirects users to the bot for verification/VIP, while streaming remains 100% free.\n"
        "<b>Example:</b> <code>/stream_download off</code> | <code>/stream_download on</code>\n\n"
        "• <code>/plans</code> (alias: <code>/vip</code>)\n"
        "<b>Usage:</b> Displays the VIP pricing menu and payment QR/UPI instructions for users.\n\n"
        "• <code>/myplan</code>\n"
        "<b>Usage:</b> Check your personal VIP status, active plan, and validity."
    ),

    "database": (
        "🗄️ <b>File Management & Database</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Monitor MongoDB index metrics, clean low-quality files, and configure auto-deletion.</i>\n\n"
        "• <code>/stats</code>\n"
        "<b>Usage:</b> Displays total indexed files in MongoDB, registered users, connected groups, bot uptime, and system RAM.\n\n"
        "• <code>/targetdb [1|2|auto]</code> (alias: <code>/setwritedb</code>)\n"
        "<b>Usage:</b> Multi-Cluster Storage Routing: View or switch active MongoDB write target. In <code>auto</code> mode, automatically routes new uploads to Secondary DB when Primary DB hits 440MB (Alerts dispatched at 400MB, 420MB, 440MB).\n"
        "<b>Example:</b> <code>/targetdb auto</code> | <code>/targetdb 2</code>\n\n"
        "• <code>/deletecam</code> (alias: <code>/purgecam</code>, <code>/deletefiles</code>)\n"
        "<b>Usage:</b> Scans the database for low-quality / pre-release titles (CamRip, PreDVD, HDTS) and purges them to maintain library quality.\n\n"
        "• <code>/cleanduplicates</code>\n"
        "<b>Usage:</b> Scans MongoDB for 100% exact duplicate files (matching Unique ID or exact file size & name) and purges redundant copies while preserving the primary file.\n\n"
        "• <code>/cleanfiles</code> (alias: <code>/cleanfilenames</code>)\n"
        "<b>Usage:</b> Watermark Cleaner: Scans all stored files in MongoDB and cleans competitor website URLs (e.g. 1TamilMV, HDHub4u, SkymoviesHD) from stored filenames while keeping movie names, print quality, and extensions 100% intact!\n\n"
        "• <code>/delbyname &lt;movie_name&gt;</code> (alias: <code>/deletebyname</code>)\n"
        "<b>Usage:</b> Copyright Quick-Purge: Instantly deletes all resolutions (480p, 720p, 1080p, 4K) of a movie or series matching the name from MongoDB search index.\n"
        "<b>Example:</b> <code>/delbyname Stree 2</code>\n\n"
        "• <code>/addjunk &lt;word_or_domain&gt;</code>\n"
        "<b>Usage:</b> Add custom pirated site tag or clutter word to the universal title cleaner. Bot automatically strips it from all filenames and TMDB queries.\n"
        "<b>Example:</b> <code>/addjunk 1TamilMV</code> or <code>/addjunk BollyFlix.Org</code>\n\n"
        "• <code>/deljunk &lt;word&gt;</code>\n"
        "<b>Usage:</b> Remove a word from the custom junk blacklist.\n\n"
        "• <code>/junkwords</code> (alias: <code>/listjunk</code>)\n"
        "<b>Usage:</b> View all active custom blacklisted junk words and built-in site cleaners.\n\n"
        "• <code>/deleteall confirm</code>\n"
        "<b>Usage:</b> ⚠️ <b>DANGER:</b> Completely wipes all indexed files from MongoDB. Requires confirmation.\n\n"
        "• <code>/backup</code> (alias: <code>/dbbackup</code>)\n"
        "<b>Usage:</b> Generates a full compressed ZIP backup of all MongoDB collections and delivers it to Admin PM and Log Channel.\n\n"
        "• <code>/autobackup [on|off]</code>\n"
        "<b>Usage:</b> Automated Sunday Disaster Recovery: Automatically dispatches a full DB backup to Log Channel & Admins every Sunday at 23:00 IST.\n\n"
        "• <code>/restore</code> (alias: <code>/dbrestore</code>)\n"
        "<b>Usage:</b> Reply to any backup ZIP file with <code>/restore</code> to restore all collections to MongoDB using idempotent upsert.\n\n"
        "• <code>/clonechannel &lt;source_id&gt; &lt;target_id&gt; [limit]</code>\n"
        "<b>Usage:</b> Clones files from primary storage channel to a backup storage channel for channel disaster recovery.\n\n"
        "• <code>/autodelete [on|off|seconds]</code>\n"
        "<b>Usage:</b> Configures auto-deletion timer for delivered files to protect users' PMs from copyright flags.\n"
        "<b>Example:</b> <code>/autodelete 600</code> (sets 10 minutes timer)"
    ),

    "broadcast": (
        "👑 <b>Broadcast & User Management</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Mass announcements, blockbuster hype alerts, user messaging, and moderation.</i>\n\n"
        "• <code>/hypedrop &lt;Movie Name&gt;</code> (alias: <code>/specialdrop</code>)\n"
        "<b>Usage:</b> Builds a high-converting blockbuster premiere alert ('THE WAIT IS OVER') with HD poster, IMDb rating, audio & 4K quality badges. Sends an interactive admin preview to your PM with a 1-click broadcast button.\n"
        "<b>Example:</b> <code>/hypedrop Stree 2</code> or <code>/hypedrop Mirzapur</code>\n\n"
        "• <code>/demands</code> (alias: <code>/topdemands</code>)\n"
        "<b>Usage:</b> Displays the Top 15 most searched movies by users that returned 0 results. Shows exact audience demand so you know what to upload next!\n\n"
        "• <code>/broadcast</code>\n"
        "<b>Usage:</b> Reply to any text, photo, video, or document with <code>/broadcast</code> to send to all private bot users. Automatically auto-purges blocked/deactivated users from MongoDB in real-time.\n"
        "<b>Example:</b> Reply to message with <code>/broadcast</code>\n\n"
        "• <code>/dailybroadcast [on|off|status]</code>\n"
        "<b>Usage:</b> View or toggle the automated daily evening broadcast engine (Fresh Drops & Hidden Gems).\n\n"
        "• <code>/test_broadcast [fresh|gem]</code>\n"
        "<b>Usage:</b> Previews today's automated broadcast card (Fresh Drops or Hidden Gem) directly in your PM without sending to users.\n\n"
        "• <code>/send_broadcast [fresh|gem]</code>\n"
        "<b>Usage:</b> Manually launches the Fresh Drops or Hidden Gem broadcast to all users right now.\n\n"
        "• <code>/set_broadcast_time &lt;HH:MM&gt;</code>\n"
        "<b>Usage:</b> Sets daily automated broadcast trigger time in 24-hour IST format (e.g. <code>/set_broadcast_time 20:00</code>).\n\n"
        "• <code>/addgem &lt;Title&gt; | &lt;type&gt; | &lt;rating&gt; | &lt;hook&gt; [| poster]</code>\n"
        "<b>Usage:</b> Adds a new Movie, Anime, Web Series, or K-Drama to the curated Hidden Gems rotation.\n\n"
        "• <code>/listgems</code>\n"
        "<b>Usage:</b> Lists all active curated hidden gems in the rotation pool.\n\n"
        "• <code>/grp_broadcast</code>\n"
        "<b>Usage:</b> Reply to any message to broadcast it to all connected groups.\n\n"
        "• <code>/ban &lt;user_id&gt; [reason]</code>\n"
        "<b>Usage:</b> Blacklists a user from interacting with the bot.\n"
        "<b>Example:</b> <code>/ban 123456789 Spammer</code>\n\n"
        "• <code>/unban &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Unbans a previously blacklisted user.\n"
        "<b>Example:</b> <code>/unban 123456789</code>\n\n"
        "• <code>/send &lt;user_id&gt;</code>\n"
        "<b>Usage:</b> Reply to any media or message with <code>/send &lt;user_id&gt;</code> to dispatch a direct copy into the user's PM from the bot.\n"
        "<b>Example:</b> Reply to file with <code>/send 1049173662</code>\n\n"
        "• <code>/set_pic &lt;url&gt;</code> (alias: <code>/setpic</code>)\n"
        "<b>Usage:</b> Updates the primary banner photo/GIF displayed when users send <code>/start</code>."
    ),

    "poster": (
        "🎨 <b>Canvas Poster Studio & TMDB API</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Automated 1080p promotional poster generator with TMDB metadata & custom branding.</i>\n\n"
        "• <code>/poster &lt;movie/series name or TMDB link&gt;</code>\n"
        "<b>Usage:</b> Designs an HD 1080p canvas promotional poster card with rating, genres, plot summary, and branding banner.\n"
        "<b>Example:</b> <code>/poster Inception</code> or <code>/poster https://www.themoviedb.org/movie/27205</code>\n\n"
        "• <code>/styles</code>\n"
        "<b>Usage:</b> Interactive gallery preview of all 6 poster rendering themes (Neon, Glassmorphism, Cinematic, Minimal, etc.).\n\n"
        "• <code>/set_poster_brand &lt;brand_name&gt;</code>\n"
        "<b>Usage:</b> Sets custom branding/watermark text embedded on canvas posters.\n"
        "<b>Example:</b> <code>/set_poster_brand AkMovieVerse</code>\n\n"
        "• <code>/set_poster_channel &lt;channel_id&gt;</code>\n"
        "<b>Usage:</b> Sets the default channel for publishing generated canvas posters.\n\n"
        "• <code>/set_tmdb_key &lt;api_key&gt;</code>\n"
        "<b>Usage:</b> Updates the TMDB v3 API Key in database settings.\n\n"
        "• <code>/set_tmdb_token &lt;token&gt;</code>\n"
        "<b>Usage:</b> Updates the TMDB v4 Bearer Token in database settings.\n\n"
        "• <code>/tmdb_status</code>\n"
        "<b>Usage:</b> Tests TMDB API connectivity, key validation, and ping response."
    ),

    "utils": (
        "⚙️ <b>Group Automation & General Utilities</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Manage group settings, manual keyword auto-replies, and media utilities.</i>\n\n"
        "• <code>/settings</code>\n"
        "<b>Usage:</b> Opens group settings control panel (Single/Double button view, spell check, IMDb poster toggle, auto-delete, welcome greeting).\n\n"
        "• <code>/connect [group_id]</code>\n"
        "<b>Usage:</b> Connects a group to your PM so you can manage group settings remotely via private chat.\n\n"
        "• <code>/disconnect [group_id]</code>\n"
        "<b>Usage:</b> Disconnects the group from PM management.\n\n"
        "• <code>/shortlink &lt;domain&gt; &lt;api_key&gt;</code>\n"
        "<b>Usage:</b> Configures a custom group-specific shortener so group owners earn revenue from searches in their group.\n\n"
        "• <code>/filter &lt;trigger&gt; &lt;reply&gt;</code>\n"
        "<b>Usage:</b> Creates a custom keyword auto-reply trigger in a group (supports media replies).\n\n"
        "• <code>/filters</code>\n"
        "<b>Usage:</b> Lists all active manual filters in the group.\n\n"
        "• <code>/stop &lt;trigger&gt;</code>\n"
        "<b>Usage:</b> Deletes a specific manual keyword filter.\n\n"
        "• <code>/stopall</code>\n"
        "<b>Usage:</b> Clears all manual filters in the group.\n\n"
        "• <code>/id</code>\n"
        "<b>Usage:</b> Returns Telegram ID of the user, chat, or replied message.\n\n"
        "• <code>/info [user_id]</code>\n"
        "<b>Usage:</b> Displays user profile details: ID, DC ID, first name, username, and profile link.\n\n"
        "• <code>/imdb &lt;movie_name&gt;</code>\n"
        "<b>Usage:</b> Fetches IMDb rating, synopsis, genres, cast, and poster.\n\n"
        "• <code>/watch &lt;movie_name&gt;</code>\n"
        "<b>Usage:</b> Searches and streams movie/series directly in high-speed web player.\n\n"
        "• <code>/stream</code>\n"
        "<b>Usage:</b> Reply to any video/file to generate fast web streaming and direct download player links.\n\n"
        "• <code>/share [duration] [uses]</code>\n"
        "<b>Usage:</b> Reply to any file to create a secure time-limited or view-limited private share link.\n\n"
        "• <code>/request &lt;movie_name&gt;</code>\n"
        "<b>Usage:</b> Sends a movie/series request to the admin channel with interactive voting buttons.\n\n"
        "• <code>/commands</code>\n"
        "<b>Usage:</b> Syncs and registers all commands with Telegram servers for autocomplete menu across all scopes."
    ),
}

# Condensed Full Cheat Sheet
CHEAT_SHEET_TEXT = (
    "📜 <b>Admin Commands Quick Reference</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "<blockquote expandable>"
    "<b>📢 RELEASES & AUTO-POST:</b>\n"
    "• <code>/post &lt;title&gt;</code> — Channel release with 12 photos\n"
    "• <code>/poststyle [1-3]</code> — Switch layout (1:Cinema, 2:Poster, 3:Text)\n"
    "• <code>/postbutton &lt;txt&gt; | &lt;url&gt;</code> — Custom promotional button\n"
    "• <code>/autopost [on|off]</code> | <code>/setupdateschannel &lt;id&gt;</code>\n\n"
    "<b>👥 AUTO-APPROVE & WELCOME:</b>\n"
    "• <code>/autoapprove [on|off]</code> — Toggle auto-approver\n"
    "• <code>/autoapprove_channels</code> | <code>/add_autoapprove &lt;id&gt;</code>\n"
    "• <code>/del_autoapprove &lt;id&gt;</code> | <code>/test_welcome</code>\n"
    "• <code>/set_welcome_pic &lt;url&gt;</code> | <code>/set_welcome &lt;txt&gt;</code>\n"
    "• <code>/acceptall [id]</code> | <code>/declineall [id]</code>\n"
    "• <code>/sharelink [id]</code> — Join-request invite link\n\n"
    "<b>📥 DOWNLOADER ENGINE:</b>\n"
    "• <code>/dl &lt;url&gt; [| name]</code> — Download web/TG link\n"
    "• <code>/dlstats</code> — Downloader RAM, disk & bandwidth\n"
    "• <code>/setthumb</code> | <code>/showthumb</code> | <code>/delthumb</code>\n\n"
    "<b>🗂️ CHANNEL INDEXER:</b>\n"
    "• <code>/index &lt;channel&gt;</code> — Index channel to MongoDB\n"
    "• <code>/index resume</code> | <code>/checkpoints</code> — Resume crawl\n"
    "• <code>/setskip &lt;num&gt;</code> | <code>/stopindex</code>\n\n"
    "<b>💎 VIP & SHORTENERS:</b>\n"
    "• <code>/shortener [on|off]</code> — Global shortener verification toggle\n"
    "• <code>/streaming [on|off]</code> — Global video streaming engine toggle\n"
    "• <code>/stream_download [on|off]</code> — Web player download toggle\n"
    "• <code>/add_premium &lt;id&gt; &lt;days&gt;</code> | <code>/remove_premium &lt;id&gt;</code>\n"
    "• <code>/premium_users</code> — List active VIP users\n"
    "• <code>/shortenerstats</code> — Live click & traffic analytics\n"
    "• <code>/shorteners</code> | <code>/add_shortener</code> | <code>/del_shortener</code>\n"
    "• <code>/set_web_url &lt;url&gt;</code> | <code>/plans</code> | <code>/myplan</code>\n\n"
    "<b>🗄️ DATABASE & STORAGE:</b>\n"
    "• <code>/stats</code> — MongoDB metrics, users & server stats\n"
    "• <code>/deletefiles</code> — Purge CamRip/PreDVD files\n"
    "• <code>/cleanduplicates</code> — Purge 100% duplicate files\n"
    "• <code>/delete &lt;id&gt;</code> | <code>/deleteall confirm</code>\n"
    "• <code>/autodelete [sec]</code> — File auto-delete timer\n\n"
    "<b>👑 BROADCAST & USERS:</b>\n"
    "• <code>/hypedrop &lt;name&gt;</code> — Blockbuster Premiere Alert\n"
    "• <code>/demands</code> — Top unfulfilled movie searches\n"
    "• <code>/dailybroadcast [on|off]</code> | <code>/test_broadcast</code>\n"
    "• <code>/broadcast [-pin|-silent]</code> — Broadcast to users\n"
    "• <code>/grp_broadcast</code> — Broadcast to all groups\n"
    "• <code>/ban &lt;id&gt;</code> | <code>/unban &lt;id&gt;</code> | <code>/send &lt;id&gt;</code>\n"
    "• <code>/set_pic &lt;url&gt;</code> — Update /start welcome photo\n\n"
    "<b>🎨 POSTER & TMDB:</b>\n"
    "• <code>/poster &lt;title&gt;</code> — Generate 1080p canvas poster\n"
    "• <code>/styles</code> — Preview all 6 poster rendering themes\n"
    "• <code>/set_poster_brand &lt;brand&gt;</code> | <code>/set_poster_channel &lt;id&gt;</code>\n"
    "• <code>/set_tmdb_key &lt;k&gt;</code> | <code>/set_tmdb_token &lt;t&gt;</code> | <code>/tmdb_status</code>\n\n"
    "<b>⚙️ GROUP & UTILITIES:</b>\n"
    "• <code>/settings</code> | <code>/connect [id]</code> | <code>/disconnect [id]</code>\n"
    "• <code>/shortlink &lt;dom&gt; &lt;api&gt;</code> — Custom group shortener\n"
    "• <code>/filter &lt;word&gt; &lt;reply&gt;</code> | <code>/filters</code> | <code>/stop</code> | <code>/stopall</code>\n"
    "• <code>/id</code> | <code>/info</code> | <code>/imdb &lt;name&gt;</code>\n"
    "• <code>/watch &lt;name&gt;</code> | <code>/stream</code> | <code>/share [sec] [uses]</code>\n"
    "• <code>/request &lt;name&gt;</code> | <code>/commands</code>"
    "</blockquote>\n\n"
    "💡 <i>Tap any category button below for full syntax & operational examples!</i>"
)


def get_admin_hub_markup():
    """Build the main category selection keyboard for admins."""
    buttons = [
        [
            InlineKeyboardButton("📢 Releases & Auto-Post", callback_data="ahelp_cat:releases"),
            InlineKeyboardButton("👥 Auto-Approve & Join", callback_data="ahelp_cat:autoapprove")
        ],
        [
            InlineKeyboardButton("📥 Downloader Engine", callback_data="ahelp_cat:downloader"),
            InlineKeyboardButton("🗂️ Channel Indexer", callback_data="ahelp_cat:indexer")
        ],
        [
            InlineKeyboardButton("💎 VIP & Shorteners", callback_data="ahelp_cat:monetization"),
            InlineKeyboardButton("🗄️ Database & Storage", callback_data="ahelp_cat:database")
        ],
        [
            InlineKeyboardButton("👑 Broadcast & Users", callback_data="ahelp_cat:broadcast"),
            InlineKeyboardButton("🎨 Poster & TMDB", callback_data="ahelp_cat:poster")
        ],
        [
            InlineKeyboardButton("⚙️ Group Tools & Utils", callback_data="ahelp_cat:utils"),
            InlineKeyboardButton("📜 Full Cheat Sheet", callback_data="ahelp_all")
        ],
        [
            InlineKeyboardButton("👤 View User Help", callback_data="ahelp_user"),
            InlineKeyboardButton("🔄 Sync TG Menu", callback_data="ahelp_sync")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_category_markup(current_key: str):
    """Build pagination and navigation buttons for a specific category."""
    idx = CATEGORY_KEYS.index(current_key) if current_key in CATEGORY_KEYS else 0
    prev_key = CATEGORY_KEYS[(idx - 1) % len(CATEGORY_KEYS)]
    next_key = CATEGORY_KEYS[(idx + 1) % len(CATEGORY_KEYS)]

    buttons = [
        [
            InlineKeyboardButton("◀️ Prev", callback_data=f"ahelp_cat:{prev_key}"),
            InlineKeyboardButton("🏠 Categories", callback_data="ahelp_home"),
            InlineKeyboardButton("Next ▶️", callback_data=f"ahelp_cat:{next_key}")
        ],
        [
            InlineKeyboardButton("📜 Full Cheat Sheet", callback_data="ahelp_all"),
            InlineKeyboardButton("👤 User Help", callback_data="ahelp_user")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def get_hub_text():
    return (
        "👑 <b>AkMovieVerse — Admin Command Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to your Master Administrator Documentation Hub.\n"
        "Here you will find full syntax, descriptions, and examples for every command.\n\n"
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
    """Admin-only dedicated command guide."""
    if not Config.is_admin(message.from_user.id):
        await message.reply_text("⛔ <b>Access Denied:</b> This command is strictly reserved for Bot Administrators.")
        return

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
        if data == "ahelp_home":
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
                [InlineKeyboardButton("🏠 Back to Categories", callback_data="ahelp_home")],
                [InlineKeyboardButton("👤 View User Help", callback_data="ahelp_user"), InlineKeyboardButton("🔄 Sync TG Menu", callback_data="ahelp_sync")]
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
                [InlineKeyboardButton("👑 Back to Admin Hub", callback_data="ahelp_home")]
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
