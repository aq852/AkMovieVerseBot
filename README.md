# 🎬 AkMovieVerse — Ultimate Auto-Filter Telegram Bot

<p align="center">
  <img src="https://images.unsplash.com/photo-1536440136628-849c177e76a1?auto=format&fit=crop&w=1200&q=80" alt="AkMovieVerse Banner" width="100%" />
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python" alt="Python" /></a>
  <a href="https://github.com/hydrogram/hydrogram"><img src="https://img.shields.io/badge/Hydrogram-MTProto%202.0-blueviolet?style=for-the-badge&logo=telegram" alt="Hydrogram" /></a>
  <a href="https://www.mongodb.com/"><img src="https://img.shields.io/badge/MongoDB-Motor%20Async-green?style=for-the-badge&logo=mongodb" alt="MongoDB" /></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker" alt="Docker" /></a>
  <a href="https://github.com/aq852/AkMovieVerseBot/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-orange?style=for-the-badge" alt="License" /></a>
</p>

---

## 📖 Overview

**AkMovieVerse** is an ultra-modern, high-performance Telegram Auto-Filter and Content Delivery framework designed for massive entertainment communities. Built on **Python 3.11**, **Hydrogram MTProto 2.0**, and asynchronous **MongoDB (Motor)**, it delivers sub-second search responses, dual-cluster storage sharding, task-locked reward drops, time-based sponsor ads, web cinema streaming, and a full-featured admin command center.

Designed for zero-downtime 24/7 cloud hosting on **Koyeb, Heroku, Render, VPS, and Docker**.

> 📚 **Official Bot Documentation & Command Manual:**  
> Complete interactive guide with copy-paste examples for every feature:  
> 👉 [**https://graph.org/AkMovieVerse-Bot-Guide-11-07**](https://graph.org/AkMovieVerse-Bot-Guide-11-07)

---

## 🌟 Key Features

### ⚡ 1. Intelligent Auto-Filter & Search Engine
- **Instant Media Discovery:** Automatically listens in connected groups or PM and indexes Telegram files with zero latency.
- **Single vs. Double Row Layouts:** Toggle between detailed full-width buttons and compact 2-column buttons via `/settings`.
- **Dynamic Sub-Filtering:** Narrow down results on the fly by **Quality** (`480p`, `720p`, `1080p`, `4K`, `HEVC`), **Language** (`Hindi`, `English`, `Tamil`, `Telugu`, `Dual Audio`), or **Season** (`S01`, `S02`, `Complete Pack`).
- **AI Spell-Check:** Automatically catches misspelled titles and suggests nearest matches (*"Did you mean: ...?"*).
- **Inline Search Mode:** Query database files directly from any chat with `@YourBot <movie_name>`.

### 🎁 2. Task-Locked Gift & Rewards Engine
- **Exclusive Reward Drops:** Create task-locked reward campaigns for single files or complete season packs (`/gift`, `/giftbatch`).
- **Interactive 3D Gold Box Card:** Sleek luxury gift poster with live countdown and progress indicators.
- **Verification Checklist:** Real-time requirements checklist (`[✅ Channel 1]` vs `[❌ Channel 2]` vs `[❌ 1-Time Ad Bypass]`).
- **DRM Content Protection:** Enforce `protect_content=True` so users cannot forward or save the received file.
- **Custom Auto-Delete:** Set a dedicated self-destruct timer (e.g. `-del 3m`, `-del 5m`) for delivered reward files.
- **Lifetime & Limited Gifts:** Support for stock claim limits, time expiry, or `-unlimited` permanent drops.
- **Gift Blacklist:** One-click global blacklisting (`/giftban`, `/giftunban`) to restrict abusers.

### 📢 3. Time-Based Sponsor Ads Engine
- **Triple Placement Architecture:**
  - **Search Results:** Clean hyperlinked sponsor text right after file #10 (zero button clutter).
  - **Start Menu (`/start`):** Eye-catching Row 2 button and branded sponsored caption link.
  - **Web Cinema Players:** Glowing glass banner at the top of `/watch` and `/watch_online`.
- **Automatic Time Expiry:** Launch campaigns for `24h`, `3d`, `7d`, or `30d` (`/setad`). Expired ads are automatically deactivated and purged.
- **VIP Immunity:** VIP subscribers never see ads anywhere in the bot or web players!

### 🎟️ 4. VIP Subscription, Promo Coupons & Referral Engine
- **Promo Coupon Codes:** Generate multi-use or single-use promo codes (`/genpromo <code> <days> <users>`). Users redeem with `/redeem`.
- **Refer & Earn:** Every user gets a personal referral link (`/refer`) to invite friends and earn free VIP days automatically.
- **VIP Perks:** Bypass all shorteners, unlock VIP-only gifts, stream ad-free, and enjoy high-speed direct downloads.

### ⚡ 5. Web Streaming & Online Cinema Player
- **Embedded Web Players:** Stream movies and series directly in modern web browsers via Artplayer and multi-server Cinema mode (`/watch`, `/stream`).
- **Fast Download Gateway:** Toggle direct player download button (`/stream_download [on|off]`). When disabled, downloads redirect safely to the bot while streaming remains free.

### 🎨 6. Canvas Poster Engine & TMDb API
- **HD 1080p Canvas Posters:** Design professional movie cards on the fly (`/poster <title>`).
- **6 Designer Styles:** Netflix Red, Glassmorphism, Neon Cyberpunk, Minimalist, Cinematic, and Anime Vibrant (`/styles`).
- **Custom Branding & Watermark:** Set channel branding watermark and direct publish channel (`/set_poster_brand`, `/set_poster_channel`).

### 📥 7. Universal Downloader
- **Multi-Platform Support:** Download videos, audio, and media from YouTube, Instagram, Facebook, TikTok, Twitter/X, LuLuStream, StreamTape, direct URLs, or Telegram media files (`/dl <url>`).
- **Live Progress & Speed:** Real-time progress percentage, ETA, and download speed updates.
- **Custom Thumbnails:** Upload and manage custom thumbnails for downloaded files (`/setthumb`, `/showthumb`, `/delthumb`).

### 👑 8. Master Admin Command Center (`/ahelp`, `/adminhelp`)
- **13 Interactive Categories:** Structured navigation covering all 100+ commands with syntax, parameters, flags, and copy-paste examples.
- **Smart Navigation:** `[ ❌ Close Menu ]` on the main hub and `[ 🔙 Back to Hub ]` on all sub-screens.
- **Direct Keyword Jumps:** Jump directly to any module (e.g. `/ahelp gifts`, `/ahelp ads`, `/ahelp broadcast`).
- **Master Cheat Sheet:** Expandable compact cheat sheet listing 100% of the bot commands within Telegram's single-message limit.
- **Telegram Menu Sync:** Sync commands directly to Telegram autocomplete menu with 1 click (`/commands`).

### 👥 9. Auto-Approve & Channel Gatekeeper
- **Instant Join Request Approval:** Automatically approves pending Telegram channel join requests (`/autoapprove on`).
- **Personalized Welcome DM:** Sends dynamic DM to joining users with random anime wallpapers and placeholders (`{mention}`, `{title}`, `{first_name}`).
- **Batch Processing:** One-click `/acceptall` and `/declineall` for backlogged join queues.

### 🗄️ 10. Multi-Cluster Database & Housekeeping
- **Dual MongoDB Sharding:** Route write operations between Primary and Secondary clusters (`/targetdb 1|2|auto`).
- **Automated Housekeeping:** Weekly automated cleanup purging dead groups, unverified tokens, duplicate files, and site watermarks (`/autoclean`).
- **Backup & Restore:** Full database export to encrypted zip backup and instant restore via PM (`/backup`, `/restore`).

---

## 🛠️ Environment Variables Configuration

Configure these environment variables in your `.env` file or cloud dashboard:

### 🔑 Essential Credentials
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `API_ID` | **Yes** | — | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | **Yes** | — | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | **Yes** | — | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `BOT_USERNAME` | **Yes** | — | Bot username without `@` (e.g. `AkMovieVerseBot`) |
| `ADMINS` | **Yes** | — | Space-separated Telegram User IDs of administrators |
| `DATABASE_URI` | **Yes** | — | Primary MongoDB Atlas connection string (`mongodb+srv://...`) |
| `DATABASE_NAME` | No | `AutoFilterBot` | Primary database name |

### 🗄️ Secondary MongoDB (Multi-Cluster Storage)
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `SECONDARY_DATABASE_URI` | No | — | Secondary MongoDB connection string for storage overflow |
| `SECONDARY_DATABASE_NAME`| No | `AutoFilterBot` | Secondary database name |
| `PRIMARY_DB_MAX_SIZE_MB` | No | `440` | Threshold (MB) to trigger automatic secondary cluster routing |

### 📢 Channels & Force-Subscribe
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `CHANNELS` | No | — | Source storage channel IDs to index (space-separated) |
| `LOG_CHANNEL` | No | `0` | Private channel ID for error logs and search demand alerts |
| `UPDATES_CHANNEL` | No | `0` | Official updates channel for auto-post releases |
| `GIFT_CHANNEL` | No | `0` | Dedicated channel for auto-publishing gift drops (`@channel` or `-100...`) |
| `FORCE_SUB_CHANNELS` | No | — | Channels users must join to access search files |
| `AUTO_APPROVE` | No | `True` | Automatically approve channel join requests |
| `AUTO_APPROVE_CHANNELS`| No | — | Channels enabled for auto-approval |
| `CHANNEL_URL` | No | `https://t.me/AkMovieVerse` | Main channel link shown on buttons |

### 💰 Monetization & Shorteners
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `SHORTENER_ENABLED` | No | `True` | Enable/Disable URL shortener token verification |
| `SHORTENER_URL` | No | `linkshortify.com` | Primary shortener domain |
| `SHORTENER_API` | No | — | Primary shortener API key |
| `SHORTENER_URL2` | No | — | Secondary shortener domain (for rotation) |
| `SHORTENER_API2` | No | — | Secondary shortener API key |
| `SHORTENER_ROTATION` | No | `round_robin` | Multi-shortener strategy (`round_robin` or `random`) |
| `VERIFY_EXPIRE` | No | `86400` | Duration of 1-time verification in seconds (86400s = 24h) |
| `TUTORIAL_URL` | No | — | Video link explaining how to bypass shortener |

### ⚡ Web Server & Streaming
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `PORT` | No | `8080` | Web server port (Koyeb / Heroku / Render) |
| `WEB_URL` | No | — | Public URL of web server (e.g. `https://mybot.koyeb.app`) |
| `STREAM_URL` | No | — | Custom streaming domain (defaults to `WEB_URL`) |
| `ENABLE_STREAMING` | No | `True` | Global online streaming toggle |
| `ENABLE_WEB_DOWNLOAD` | No | `True` | Allow direct file download inside web player |

### 🎨 Poster & Downloader
| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `TMDB_API_KEY` | No | — | TMDb API Key for poster and synopsis metadata |
| `TMDB_READ_ACCESS_TOKEN` | No | — | TMDb v4 Bearer Read Access Token |
| `DEFAULT_POSTER_BRAND` | No | `AkMovieVerse` | Default watermark text on generated posters |
| `DOWNLOADER_ACCESS` | No | `admin` | Downloader permission (`admin` or `all`) |
| `DOWNLOADER_MAX_SIZE` | No | `100` | Maximum file download size (in MB) |

---

## 🚀 Deployment Instructions

### Option 1: Koyeb (Recommended)
1. Fork or push this repository to your GitHub account.
2. Sign in to [Koyeb](https://app.koyeb.com/).
3. Click **Create App**, choose **GitHub**, and select your repository.
4. Set the builder to **Dockerfile** (or buildpack).
5. Add all required environment variables under **Environment Variables**.
6. Set the exposed port to `8080` (HTTP).
7. Click **Deploy**. The bot and internal health-check server will start automatically!

### Option 2: Heroku
1. Install [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) and authenticate:
   ```bash
   heroku login
   ```
2. Create an app:
   ```bash
   heroku create akmovieverse-bot
   ```
3. Set your environment variables in App Settings or via CLI:
   ```bash
   heroku config:set API_ID=12345 API_HASH=your_hash BOT_TOKEN=your_token ...
   ```
4. Deploy the code:
   ```bash
   git push heroku main
   heroku ps:scale web=1
   ```

### Option 3: VPS / Docker Compose
1. Clone this repository on your Linux server:
   ```bash
   git clone https://github.com/aq852/AkMovieVerseBot.git
   cd AkMovieVerseBot
   ```
2. Create your `.env` configuration file:
   ```bash
   cp .env.sample .env
   nano .env
   ```
3. Start the bot with Docker Compose:
   ```bash
   docker-compose up -d --build
   ```
4. Inspect live logs:
   ```bash
   docker-compose logs -f
   ```

---

## 🤖 Command Reference Hub

Use `/ahelp` or `/admincommands` to access the interactive categorized command center in bot PM.

> 📖 **Full Command Manual & Examples:**  
> Check the official [**Telegraph Command Guide**](https://graph.org/AkMovieVerse-Bot-Guide-11-07) for full syntax and copy-paste examples.

### 🎁 Gifts & Task Rewards (Smart Hybrid Engine)
- `/gift [claims] [duration] [@channels] [flags]` — Create task-locked reward drop from replied file (Supports `-unlimited`, `0 0`, `-del 5m`, `-viponly`, `-shortener`, `-draft`, `-strict`)
- `/giftbatch <batch_id> [claims] [duration] ...` — Create gift drop for full season pack
- `/setgiftchannel <@channel|-100id|off>` — Set dedicated channel for auto-publishing gift drops
- `/gifts` | `/giftstats [id]` — Active gifts dashboard, unique claims & re-download analytics
- `/delgift <gift_id>` — Revoke and cancel active gift campaign
- `/giftban <user_id> [reason]` — Blacklist user from claiming gifts
- `/giftunban <user_id>` — Remove user from gift blacklist

### 📢 Sponsor Ads & Monetization
- `/setad <duration> [Title | URL]` — Activate time-based sponsor ad (`24h`, `3d`, `7d`, `30d`)
- `/ads` — View active sponsor ad status, clicks, and remaining time
- `/delad` — Immediately remove active sponsor ad
- `/shorteners` | `/shortenerstats` — View shortener domains, API keys, and rotation stats
- `/add_shortener <domain> <api>` — Add secondary shortener for round-robin rotation
- `/del_shortener <domain>` — Remove shortener from rotation
- `/set_web_url <url>` — Update public web server URL

### 🎟️ VIP Plans & Promo Coupons
- `/genpromo <days> <users> [code]` — Generate VIP promo coupon code
- `/promos` | `/delpromo <code>` — List and revoke promo codes
- `/redeem <code>` — Redeem promo coupon for free VIP access
- `/add_premium <user_id> <days>` — Manually grant VIP access to a user
- `/remove_premium <user_id>` — Revoke VIP status from a user
- `/premium_users` — List all active VIP subscribers
- `/plans` | `/myplan` | `/refer` — View VIP tiers, check status, or invite friends

### 👑 Broadcasts & Hype Premiere
- `/abroadcast` — Advanced broadcast with custom inline URL buttons
- `/preview_broadcast` — Test broadcast card in your PM before sending
- `/agrp_broadcast` — Advanced broadcast to all connected groups
- `/broadcast` | `/grp_broadcast` — Direct fast broadcast to users or groups
- `/hypedrop <title>` — Blockbuster Premiere card with countdown timer
- `/demands` — Top searched movies that returned zero results
- `/dailybroadcast [on|off]` — Toggle daily automated movie recommendations
- `/addgem <title> | <type> | <rate> | <hook>` — Add hidden gem to curation pool

### 📢 Releases & Auto-Post
- `/post <title>` — Interactive channel release card draft generator
- `/autopost [on|off|status]` — Toggle automatic channel release posting
- `/poststyle [1|2|3]` — Choose auto-post release layout style
- `/postbutton <text> | <url>` — Set custom channel release button
- `/setupdateschannel <id>` — Set destination channel for releases

### 📦 File Store & Batches
- `/batch` — Create multi-file shareable batch pack link
- `/genlink` — Reply to any file to generate a single-file share link
- `/batches` | `/delbatch <id>` — View or delete your batch links
- `/share [time] [limit]` — Secret file share link with self-destruct and download limit
- `/tgm` — Upload replied media to Multi-CDN hosting
- `/paste` | `/editpaste` | `/delpaste` — Publish text or code to Telegraph

### 👥 Auto-Approve & Gatekeeper
- `/autoapprove [on|off]` — Toggle automatic approval of join requests
- `/autoapprove_channels` — List channels enabled for auto-approval
- `/add_autoapprove <id>` | `/del_autoapprove <id>` — Whitelist channel for auto-approval
- `/acceptall [chat_id]` | `/declineall [chat_id]` — Accept or decline all pending requests
- `/set_welcome` | `/get_welcome` — Customize welcome DM sent to accepted members
- `/test_welcome` | `/set_welcome_pic` — Preview welcome card or set photo URL
- `/sharelink [chat_id]` — Generate protected Request-to-Join invite link

### 📥 Universal Downloader
- `/dl <url> [| filename]` — Universal video and audio downloader
- `/dlstats` — Live download server status, bandwidth, and queues
- `/setthumb` | `/showthumb` | `/delthumb` — Manage custom download thumbnails

### 🗂️ Channel Indexer & Crawler
- `/index <channel_or_link>` — Crawl and index media from channel
- `/indexall <id1> <id2> ...` — Sequential multi-channel crawl
- `/checkpoints` — View indexing progress bookmarks
- `/setskip <num>` — Set message offset for indexing
- `/stopindex` — Abort active channel indexing crawl

### 🗄️ Database, Storage & Cleanup
- `/stats` — Real-time metrics: files, users, chats, and MongoDB cluster size
- `/targetdb [1|2|auto]` — Multi-cluster write routing
- `/backup` | `/restore` — Full MongoDB backup to encrypted zip and restore
- `/autobackup [on|off]` — Automated weekly MongoDB backups
- `/autoclean` — Purge dead groups, expired tokens, and stale records
- `/deletecam` — Purge low-quality CamRip and PreDVD files
- `/cleanduplicates` — Scan and remove duplicate files across clusters
- `/cleanfiles` — Clean website advertisements and watermarks from file titles
- `/delbyname <query>` — Delete all files matching a specific keyword
- `/addjunk <tag>` | `/deljunk <tag>` | `/junkwords` — Blacklist website promo tags
- `/deleteall confirm` — Wipe all indexed files from database
- `/cleandb` — Storage cleanup menu with automatic backup safeguard
- `/autodelete [seconds]` — Configure auto-delete timer for search results

### 🎨 Canvas Poster & TMDb API
- `/poster <movie_name>` — Generate HD 1080p canvas poster card
- `/styles` — Preview all 6 designer poster templates
- `/set_poster_brand <brand>` — Set custom watermark branding text
- `/set_poster_channel <id>` — Set channel for publishing generated posters
- `/set_tmdb_key <key>` | `/set_tmdb_token <token>` — Configure TMDb API credentials
- `/tmdb_status` — Test TMDb API connection health

### ⚡ Web Streaming & Players
- `/streaming [on|off]` — Global streaming engine toggle
- `/stream_download [on|off]` — Toggle player download button
- `/watch <movie_name>` — Stream movie or series with multi-server web cinema player
- `/stream` — Reply to video/file to generate direct web streaming links

### ⚙️ Group Tools & Utilities
- `/settings` — Group control panel (Single/Double buttons, spell check, IMDb poster)
- `/connect [group_id]` | `/disconnect [group_id]` — Connect group settings to PM
- `/shortlink <domain> <api>` — Configure custom group shortener for group owner revenue
- `/filter <trigger> <reply>` | `/filters` — Create or list manual keyword auto-replies
- `/stop <trigger>` | `/stopall` — Remove specific or all manual keyword filters
- `/id` | `/info` — Get Telegram ID or detailed file technical specs
- `/imdb <movie_name>` — Search IMDb synopsis, rating, genres, and cast
- `/request <movie_name>` | `/myrequests` — Submit or track movie requests with voting
- `/myalerts` — Manage upload notification alerts
- `/commands` — Sync all 100+ commands with Telegram autocomplete menu

---

## 👨‍💻 Developer Credits & Community

<p align="center">
  <b>Developed & Maintained with ❤️ by:</b><br />
  <h3>👑 AMIT</h3>
</p>

- 📢 **Official Channel:** [AKMOVIEVERSE](https://t.me/AkMovieVerse) (`@AkMovieVerse`)
- 💬 **Updates & Drops:** [@AkMovies](https://t.me/Akmovieverse)
- 🆘 **Direct Support & Inquiries:** [@AK_ownerbot](https://t.me/AK_ownerbot)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
