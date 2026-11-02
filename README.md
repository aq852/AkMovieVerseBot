# 🎬 Ultimate Auto Filter Telegram Bot (Python + MongoDB)

An advanced, high-performance, and modular Telegram Auto-Filter Bot built with **Python 3.11**, **Hydrogram (MTProto 2.0)**, and **MongoDB (Motor)**. Designed for lightning-fast media search, group auto-filtering, monetization, and zero-downtime multi-cloud deployment on **Koyeb, Heroku, Render, VPS, and Docker**.

---

## ✨ Features Overview

- ⚡ **Auto-Filter Engine**: Automatically searches and delivers indexed files in groups and PM.
- 🔲 **Single vs Double Button Rows**: Switch between wide detailed buttons and compact 2-column buttons via `/settings`.
- 🏷️ **Multi-Dimension Sub-Filters**: Filter search results on the fly by **Quality** (`480p`, `720p`, `1080p`, `4K`) or **Language** (`Hindi`, `English`, `Tamil`, `Telugu`).
- 💡 **AI Spell-Check**: Suggests the nearest correct title ("Did you mean: ...?") when users misspell a movie name.
- 🖼️ **IMDb Metadata & Posters**: Fetches movie/series posters, IMDb ratings, genres, and cast details automatically.
- 🔎 **Inline Search Mode**: Search the database directly from any chat using `@YourBot movie_name`.
- 💰 **24-Hour Token Monetization**: Universal shortener integration with a 24-hour verification window (users verify once for 24 hours of unlimited downloads).
- 📢 **Multi-Channel Force-Subscribe (FSub)**: Multi-channel support with **Auto-Approval** for Telegram Request-to-Join channels.
- 🧹 **Chat Hygiene & Anti-Piracy**: Auto-delete timer in groups and PreDVD/CamRip cleaners (`/deletefiles`).
- 🤖 **Clone Bot Engine (`/clone`)**: Allows users to spawn their own personal bot instance running on your master framework.
- ⚙️ **PM Group Connections**: Admins can run `/connect` in their group and manage settings privately in bot PM.
- 🌐 **Zero-Downtime Health Check**: Built-in background `aiohttp` web server on dynamic `$PORT` ensuring seamless hosting on Koyeb, Heroku, and Render.

---

## 🛠️ Environment Variables Configuration

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `API_ID` | **Yes** | — | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | **Yes** | — | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | **Yes** | — | Telegram Bot Token from [@BotFather](https://t.me/BotFather) |
| `BOT_USERNAME` | **Yes** | — | Bot username without `@` (e.g. `MyAutoFilterBot`) |
| `DATABASE_URI` | **Yes** | — | MongoDB Atlas Connection URI (`mongodb+srv://...`) |
| `DATABASE_NAME` | No | `AutoFilterBot` | MongoDB Database name |
| `ADMINS` | **Yes** | — | Telegram User IDs of administrators (space separated) |
| `CHANNELS` | No | — | Source storage channel IDs for media indexing (space separated) |
| `LOG_CHANNEL` | No | `0` | Private channel ID for bot event logs and errors |
| `FORCE_SUB_CHANNELS` | No | — | Usernames or channel IDs users must join before accessing files |
| `AUTO_APPROVE` | No | `True` | Automatically approve Request-to-Join channel requests |
| `SHORTENER_ENABLED` | No | `True` | Enable/Disable URL shortener token verification |
| `SHORTENER_URL` | No | `shareus.io` | Shortener domain / API website |
| `SHORTENER_API` | No | — | Shortener API secret key |
| `VERIFY_EXPIRE` | No | `86400` | Duration of verified access in seconds (86400s = 24 hours) |
| `TUTORIAL_URL` | No | — | URL/Video showing how users can bypass the shortener |
| `ENABLE_IMDB` | No | `True` | Fetch movie posters and IMDb ratings in search cards |
| `SINGLE_BUTTON` | No | `True` | Single wide button row vs double compact buttons |
| `AUTO_DELETE_TIME` | No | `300` | Auto-delete countdown in groups (in seconds) |
| `PROTECT_CONTENT` | No | `False` | Prevent users from forwarding or saving delivered files |
| `ALLOW_CLONE` | No | `True` | Allow users to create cloned bots via `/clone` |
| `PORT` | No | `8080` | Web server port for Koyeb / Heroku / Render |

---

## 🚀 Deployment Instructions

### 1. Deploy on Koyeb (Recommended)
1. Fork or push this repository to GitHub.
2. Sign in to [Koyeb](https://app.koyeb.com/).
3. Click **Create App** and select **GitHub**.
4. Choose this repository.
5. In **Environment Variables**, add all required keys (`API_ID`, `API_HASH`, `BOT_TOKEN`, `DATABASE_URI`, `ADMINS`, etc.).
6. Set **Port** to `8080` (HTTP).
7. Click **Deploy**. The built-in web server will keep your health checks green!

### 2. Deploy on Heroku
1. Install [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) and log in.
2. Create an app:
   ```bash
   heroku create my-autofilter-bot
   ```
3. Set your environment variables in Heroku App Settings (Config Vars).
4. Deploy the code:
   ```bash
   git push heroku main
   ```
5. Ensure the worker/web dyno is active:
   ```bash
   heroku ps:scale web=1
   ```

### 3. Deploy on VPS (Docker & Docker Compose)
1. Clone this repository onto your server:
   ```bash
   git clone <your_repo_url> autofilterbot
   cd autofilterbot
   ```
2. Copy `.env.sample` to `.env` and fill in your credentials:
   ```bash
   cp .env.sample .env
   nano .env
   ```
3. Launch with Docker Compose:
   ```bash
   docker-compose up -d --build
   ```
4. View real-time logs:
   ```bash
   docker-compose logs -f
   ```

---

## 🤖 Full Command List

### Public / User Commands
- `/start` — Start bot, view time greetings, unlock deep-linked files, or complete verification.
- `/plans`, `/myplan` — View VIP subscription tiers and active plan status.
- `/refer` — Get personal invite link to earn free VIP access.
- `/id` — Get Telegram User ID, Group ID, or media IDs.
- `/info` — Inspect technical metadata (DC ID, file mime-type, resolution, duration).
- `/imdb <movie_name>` — Search and fetch movie poster and IMDb ratings.
- `/top` — View top trending searches.
- `@YourBot query` — Inline search across any chat.

### Group Admin Commands
- `/connect` — Connect group settings to your PM.
- `/disconnect` — Unlink group from PM settings.
- `/settings` — Open interactive toggle panel (auto-delete, IMDb, shortener, button layouts).
- `/shortlink <website> <api_key>` — Set custom shortener for your group.
- `/filter <word> <reply>` — Set custom manual keyword trigger.
- `/filters` — List active group filters.
- `/stop <word>` — Delete manual filter.

### Bot Administrator Commands
- `/stats` — Comprehensive database, storage, and user metrics.
- `/broadcast` — Fast broadcast to all bot users in PM (reply to message).
- `/grp_broadcast` — Broadcast message to all connected groups.
- `/master_broadcast` — Global broadcast across the Main Bot AND all Cloned Bots simultaneously!
- `/clones` — View all running clone bots, their owners, and configurations.
- `/delclone <username_or_token>` — Force-stop and delete any abusive clone bot.
- `/index` — Batch crawl and index channel files (`/index <channel>`).
- `/setskip <num>` — Skip $N$ messages during batch indexing.
- `/deletefiles` — Purge all low-quality CamRip and PreDVD files.
- `/delete <file_id>` — Delete a single file from database.
- `/deleteall confirm` — Wipe all indexed files.
- `/ban <user_id>` / `/unban <user_id>` — Blacklist management.
- `/add_premium <user_id> <days>` — Grant VIP access.
- `/send <user_id>` — Dispatch replied file directly to a user in PM.
- `/commands` — Auto-register command autocomplete menu in Telegram.
- `/clone <bot_token>` — Spawn a new cloned bot instance.
- `/set_shortener <website> <api_key>` — Set custom shortener for your cloned bot.
- `/set_fsub <channel>` — Add custom FSub channel for your cloned bot.
- `/deleteclone` — Delete your active cloned bot instance.
