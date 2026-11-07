import os
import re
import time
import asyncio
import logging
import shutil
import urllib.parse
from html import escape as html_escape

import aiohttp
import aiofiles
from curl_cffi import requests as cffi_requests
import yt_dlp
from PIL import Image

from config import Config
from utils.helpers import get_readable_size

logger = logging.getLogger("autofilter.downloader")

DIRECT_MEDIA_EXTENSIONS = (
    ".mp4", ".mkv", ".webm", ".avi", ".flv", ".mov",
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg",
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".apk", ".iso", ".jpg", ".jpeg", ".png", ".webp"
)


class DownloadProgress:
    """Thread-safe progress tracking and cancellation container for downloads."""
    def __init__(self):
        self.current: int = 0
        self.total: int = 0
        self.speed: float = 0.0
        self.eta: int = 0
        self.is_done: bool = False
        self.is_cancelled: bool = False
        self.status_text: str = ""


def make_progress_bar(current: int, total: int, length: int = 10) -> str:
    """Generate a clean visual text progress bar: [■■■■■□□□□□] 50%"""
    if total <= 0 or current <= 0:
        return "[□□□□□□□□□□] 0%"
    pct = min(1.0, max(0.0, current / total))
    filled = int(round(length * pct))
    bar = "■" * filled + "□" * (length - filled)
    return f"[{bar}] {int(pct * 100)}%"


def format_progress_caption(action: str, platform: str, current: int, total: int, speed: float = 0, eta: int = 0) -> str:
    """Format standard progress message for Telegram."""
    bar = make_progress_bar(current, total)
    curr_str = get_readable_size(current)
    tot_str = get_readable_size(total) if total > 0 else "Calculating..."
    speed_str = f"{get_readable_size(speed)}/s" if speed > 0 else "--/s"
    eta_str = f"{eta}s" if eta > 0 else "--"
    
    header = f"{action} from {platform}" if platform else action
    return (
        f"<b>{header}...</b>\n\n"
        f"<code>{bar}</code>\n"
        f"📦 <b>Size:</b> {curr_str} / {tot_str}\n"
        f"⚡ <b>Speed:</b> {speed_str} | ⏱️ <b>ETA:</b> {eta_str}"
    )


def extract_video_metadata(video_path: str, output_thumb_path: str | None = None) -> dict:
    """Extract metadata (duration, width, height) and generate high-quality frame thumbnail using PyAV."""
    result = {
        "thumb_path": None,
        "duration": None,
        "width": None,
        "height": None
    }
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
        return result

    try:
        import av
        with av.open(video_path) as container:
            if container.duration:
                result["duration"] = int(container.duration / 1_000_000)

            video_streams = container.streams.video
            if not video_streams:
                return result

            stream = video_streams[0]

            # Try seeking past the first 1-2 seconds to skip initial black frames
            try:
                dur = container.duration
                if dur and dur > 3_000_000:
                    seek_pos = min(2_000_000, dur // 3)
                    container.seek(seek_pos)
            except Exception:
                pass

            candidate_frame = None
            for idx, frame in enumerate(container.decode(stream)):
                candidate_frame = frame
                im = frame.to_image()
                # Sample brightness on 16x16 thumbnail to avoid all-black frames
                stat = sum(im.resize((16, 16)).convert("L").getdata()) / 256
                if stat > 15 or idx >= 10:
                    break

            if candidate_frame:
                result["width"] = candidate_frame.width
                result["height"] = candidate_frame.height

                if output_thumb_path:
                    im = candidate_frame.to_image().convert("RGB")
                    im.thumbnail((640, 360), Image.Resampling.LANCZOS)
                    im.save(output_thumb_path, "JPEG", quality=85, optimize=True)
                    result["thumb_path"] = output_thumb_path

    except Exception as e:
        logger.debug(f"PyAV metadata/thumbnail extraction failed: {e}")

    return result


def generate_video_thumbnail(video_path: str, output_thumb_path: str) -> str | None:
    """Generate a high-quality video thumbnail frame using PyAV + Pillow."""
    res = extract_video_metadata(video_path, output_thumb_path)
    return res.get("thumb_path")


def is_lulustream_url(url: str) -> bool:
    """Check if URL belongs to LuLuStream or its mirrors."""
    u = url.lower()
    return any(domain in u for domain in ("lulustream.com", "luluvido.com", "luluvdo.com", "lulu.to"))


def is_vidara_url(url: str) -> bool:
    """Check if URL belongs to Vidara or its embedded media mirrors."""
    u = url.lower()
    return any(domain in u for domain in ("vidara.to", "vidara.org", "g8w90qhngo.com"))


def is_terabox_url(url: str) -> bool:
    """Check if URL belongs to TeraBox cloud storage."""
    u = url.lower()
    return any(domain in u for domain in ("terabox.app", "terabox.com", "1024tera.com", "1024terabox.com", "teraboxlink.com", "freeterabox.com"))


def is_telegram_url(url: str) -> bool:
    """Check if URL points to a Telegram post or channel message."""
    u = url.lower()
    return "t.me/" in u or "telegram.me/" in u


def detect_platform(url: str) -> str:
    """Identify the platform name and icon from a URL."""
    u = url.lower()
    if is_telegram_url(url):
        return "✈️ Telegram"
    elif "instagram.com" in u or "instagr.am" in u:
        return "📸 Instagram"
    elif "youtube.com" in u or "youtu.be" in u:
        return "🔴 YouTube"
    elif "twitter.com" in u or "x.com" in u:
        return "🐦 Twitter / X"
    elif "pinterest.com" in u or "pin.it" in u:
        return "📌 Pinterest"
    elif "facebook.com" in u or "fb.watch" in u or "fb.com" in u:
        return "📘 Facebook"
    elif "tiktok.com" in u:
        return "🎵 TikTok"
    elif "reddit.com" in u or "redd.it" in u:
        return "🤖 Reddit"
    elif "threads.net" in u:
        return "🧵 Threads"
    elif is_lulustream_url(url):
        return "🎬 LuLuStream"
    elif is_vidara_url(url):
        return "🎥 Vidara"
    elif is_terabox_url(url):
        return "📦 TeraBox"
    elif "streamtape.com" in u or "streamtape.to" in u:
        return "📼 Streamtape"
    elif "doodstream.com" in u or "dood." in u:
        return "📺 DoodStream"
    elif "streamwish." in u:
        return "✨ Streamwish"
    elif "vidhide." in u or "vidhidepro." in u:
        return "🎥 VidHide"
    elif "mixdrop." in u:
        return "💧 MixDrop"
    elif is_direct_download_link(url):
        return "🌐 Direct File Link"
    return "🌐 Web Stream / Link"


def is_direct_download_link(url: str) -> bool:
    """Check if URL points directly to a downloadable file extension."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in DIRECT_MEDIA_EXTENSIONS)


def get_cookie_file() -> str | None:
    """Find valid cookie file path if provided by admin, or hydrate from COOKIES_DATA env var."""
    # Hydrate cookies.txt if provided via COOKIES_DATA environment variable (for Koyeb/Cloud)
    env_cookies = os.environ.get("COOKIES_DATA", "").strip()
    if env_cookies and (not os.path.isfile("cookies.txt") or os.path.getsize("cookies.txt") == 0):
        try:
            with open("cookies.txt", "w", encoding="utf-8") as f:
                f.write(env_cookies)
        except Exception as e:
            logger.warning(f"Could not write COOKIES_DATA to cookies.txt: {e}")

    candidates = [
        getattr(Config, "COOKIES_FILE", "cookies.txt"),
        "cookies.txt",
        "instagram_cookies.txt"
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.path.getsize(c) > 0:
            return os.path.abspath(c)
    return None


async def download_direct_file(url: str, output_dir: str, max_size_bytes: int, progress: DownloadProgress | None = None) -> dict:
    """Stream download a direct file link with safety size threshold and live progress."""
    parsed = urllib.parse.urlparse(url)
    raw_filename = os.path.basename(parsed.path) or "downloaded_file.bin"
    clean_filename = re.sub(r'[^\w\-_\. ]', '_', urllib.parse.unquote(raw_filename)).strip()
    if not clean_filename:
        clean_filename = "downloaded_file.bin"

    file_path = os.path.join(output_dir, clean_filename)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url
    }

    start_time = time.time()
    last_time = start_time
    last_bytes = 0

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=600)) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                raise ValueError(f"Server returned HTTP {resp.status}")

            total_size = 0
            content_length = resp.headers.get("Content-Length")
            if content_length:
                total_size = int(content_length)
                if total_size > max_size_bytes:
                    max_mb = max_size_bytes // (1024 * 1024)
                    file_mb = total_size // (1024 * 1024)
                    raise ValueError(f"File size ({file_mb} MB) exceeds maximum allowed limit ({max_mb} MB).")
                if progress:
                    progress.total = total_size

            total_downloaded = 0
            async with aiofiles.open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 256):  # 256 KB chunks
                    if progress and progress.is_cancelled:
                        raise asyncio.CancelledError("Download cancelled by user.")

                    total_downloaded += len(chunk)
                    if total_downloaded > max_size_bytes:
                        max_mb = max_size_bytes // (1024 * 1024)
                        raise ValueError(f"Download aborted: file exceeds maximum allowed limit ({max_mb} MB).")
                    await f.write(chunk)

                    now = time.time()
                    if progress:
                        progress.current = total_downloaded
                        time_diff = now - last_time
                        if time_diff >= 1.0:
                            speed = (total_downloaded - last_bytes) / time_diff
                            progress.speed = speed
                            if total_size > total_downloaded and speed > 0:
                                progress.eta = int((total_size - total_downloaded) / speed)
                            last_time = now
                            last_bytes = total_downloaded

    ext = os.path.splitext(file_path)[1].lower()
    is_video = ext in (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv")
    is_audio = ext in (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg")

    thumb_path = None
    v_dur = None
    v_w = None
    v_h = None
    if is_video:
        v_meta = extract_video_metadata(file_path, os.path.join(output_dir, "direct_thumb.jpg"))
        thumb_path = v_meta.get("thumb_path")
        v_dur = v_meta.get("duration")
        v_w = v_meta.get("width")
        v_h = v_meta.get("height")

    return {
        "file_path": file_path,
        "file_name": clean_filename,
        "file_size": total_downloaded,
        "title": clean_filename,
        "is_video": is_video,
        "is_audio": is_audio,
        "duration": v_dur,
        "width": v_w,
        "height": v_h,
        "thumbnail": thumb_path
    }


def download_lulustream(url: str, output_dir: str, max_size_bytes: int, progress: DownloadProgress | None = None) -> dict:
    """Specialized engine to extract and stream LuLuStream/luluvido.com HLS streams with auto-thumbnail generation."""
    m_code = re.search(r'([a-zA-Z0-9]{10,16})', url)
    if not m_code:
        raise ValueError("Invalid LuLuStream URL format: missing file code.")
    code = m_code.group(1)
    embed_url = f"https://luluvido.com/e/{code}"

    session = cffi_requests.Session()
    r = session.get(embed_url, impersonate="chrome120")
    if r.status_code != 200:
        raise ValueError(f"LuLuStream returned HTTP {r.status_code}. Video might be deleted.")

    # Title extraction
    t_m = re.search(r'<title>(.*?)</title>', r.text, re.I)
    raw_title = "LuLuStream_Video"
    if t_m:
        raw_title = re.sub(r'(?i)watch|online|lulustream|\.mp4|-', '', t_m.group(1)).strip() or "LuLuStream_Video"
    clean_title = re.sub(r'[^\w\-_\. ]', '_', raw_title).strip()
    filename = os.path.join(output_dir, f"{clean_title}.mp4")

    # Unpack Dean Edwards Packed JS
    idx = r.text.find("eval(function(p,a,c,k,e,d)")
    if idx == -1:
        raise ValueError("Could not find video player payload in LuLuStream response.")

    sub = r.text[idx:]
    script_end = sub.find("</script>")
    full_eval = sub[:script_end].strip()

    m = re.search(r"}\s*\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)", full_eval, re.DOTALL)
    if not m:
        raise ValueError("Failed to decode LuLuStream player cipher.")

    p, a_str, c_str, k_str = m.groups()
    a, c, k = int(a_str), int(c_str), k_str.split('|')

    def itob(val, base):
        digits = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if val == 0:
            return "0"
        res = []
        while val > 0:
            res.append(digits[val % base])
            val //= base
        return "".join(reversed(res))

    lookup = {itob(i, a): (k[i] if i < len(k) and k[i] else itob(i, a)) for i in range(c)}
    decoded = re.sub(r'\b[0-9a-zA-Z]+\b', lambda match: lookup.get(match.group(0), match.group(0)), p)

    m3u8s = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', decoded)
    if not m3u8s:
        raise ValueError("No video stream URLs found inside LuLuStream player.")

    master_url = m3u8s[0]
    headers = {"Referer": "https://luluvido.com/", "Origin": "https://luluvido.com"}
    r_master = session.get(master_url, headers=headers, impersonate="chrome120")
    if r_master.status_code != 200:
        raise ValueError("Could not connect to LuLuStream media server.")

    sub_m3u8 = None
    for l in r_master.text.splitlines():
        if l.strip().startswith("http"):
            sub_m3u8 = l.strip()
            break

    if not sub_m3u8:
        sub_m3u8 = master_url

    r_sub = session.get(sub_m3u8, headers=headers, impersonate="chrome120")
    segments = [l.strip() for l in r_sub.text.splitlines() if l.strip().startswith("http") or l.strip().endswith(".ts")]
    if not segments:
        raise ValueError("No video data segments found in playlist.")

    total_segments = len(segments)
    estimated_total = total_segments * 600 * 1024
    if progress:
        progress.total = estimated_total

    total_downloaded = 0
    start_time = time.time()
    last_time = start_time
    last_bytes = 0

    with open(filename, "wb") as f_out:
        for idx, seg in enumerate(segments):
            if progress and progress.is_cancelled:
                raise asyncio.CancelledError("Download cancelled by user.")

            seg_url = seg
            if not seg_url.startswith("http"):
                base = sub_m3u8.rsplit('/', 1)[0]
                seg_url = f"{base}/{seg_url}"

            # Stream segment chunks with retries & generous timeout to survive throttled CDNs
            seg_downloaded = False
            last_seg_err = None
            for attempt in range(3):
                try:
                    r_seg = session.get(seg_url, headers=headers, impersonate="chrome120", stream=True, timeout=120)
                    if r_seg.status_code == 200:
                        for chunk in r_seg.iter_content(chunk_size=1024 * 64):
                            if progress and progress.is_cancelled:
                                raise asyncio.CancelledError("Download cancelled by user.")
                            f_out.write(chunk)
                            total_downloaded += len(chunk)

                            if total_downloaded > max_size_bytes:
                                max_mb = max_size_bytes // (1024 * 1024)
                                raise ValueError(f"Video size exceeds allowed limit ({max_mb} MB).")

                            now = time.time()
                            if progress:
                                progress.current = total_downloaded
                                time_diff = now - last_time
                                if time_diff >= 1.0:
                                    speed = (total_downloaded - last_bytes) / time_diff
                                    progress.speed = speed
                                    rem_segs = total_segments - (idx + 1)
                                    avg_seg_size = total_downloaded / max(1, idx + 1)
                                    rem_bytes = rem_segs * avg_seg_size
                                    if speed > 0:
                                        progress.eta = int(rem_bytes / speed)
                                    last_time = now
                                    last_bytes = total_downloaded

                        seg_downloaded = True
                        break
                    elif r_seg.status_code == 403:
                        session = cffi_requests.Session()
                except Exception as e_s:
                    last_seg_err = e_s
                    time.sleep(1)

            if not seg_downloaded:
                err_text = str(last_seg_err) if last_seg_err else "CDN server non-responsive"
                raise ValueError(f"LuLuStream segment {idx+1}/{total_segments} timed out ({err_text[:80]}).")

    actual_size = os.path.getsize(filename)
    # Auto-generate video thumbnail and extract exact metadata from downloaded MP4
    v_meta = extract_video_metadata(filename, os.path.join(output_dir, "lulu_thumb.jpg"))
    thumb_path = v_meta.get("thumb_path")
    v_dur = v_meta.get("duration") or (total_segments * 3)
    v_w = v_meta.get("width") or 1280
    v_h = v_meta.get("height") or 720

    return {
        "file_path": filename,
        "file_name": os.path.basename(filename),
        "file_size": actual_size,
        "title": clean_title,
        "is_video": True,
        "is_audio": False,
        "duration": v_dur,
        "width": v_w,
        "height": v_h,
        "thumbnail": thumb_path
    }


def download_vidara(url: str, output_dir: str, max_size_bytes: int, progress: DownloadProgress | None = None, quality: str = "best") -> dict:
    """Specialized engine to resolve and download videos from Vidara.to and its embedded gateways."""
    s = cffi_requests.Session()
    r_page = s.get(url, impersonate="chrome120", timeout=15)
    if r_page.status_code != 200:
        raise ValueError(f"Vidara returned HTTP {r_page.status_code}. Video might be removed or unavailable.")

    m_iframe = re.search(r'<iframe[^>]+src=["\']https?://([^/]+)/e/([a-zA-Z0-9]+)', r_page.text)
    if m_iframe:
        domain = m_iframe.group(1)
        filecode = m_iframe.group(2)
    else:
        m_code = re.search(r'([a-zA-Z0-9]{10,24})', url)
        if not m_code:
            raise ValueError("Could not extract Vidara video ID from URL.")
        filecode = m_code.group(1)
        domain = "g8w90qhngo.com"

    api_url = f"https://{domain}/api/stream"
    headers = {
        "Referer": f"https://{domain}/e/{filecode}",
        "Origin": f"https://{domain}",
        "Content-Type": "application/json"
    }
    r_api = s.post(api_url, headers=headers, json={"filecode": filecode, "device": "web", "codecs": ["h264"]}, impersonate="chrome120", timeout=15)
    if r_api.status_code != 200:
        raise ValueError(f"Vidara API returned HTTP {r_api.status_code}. Stream could not be generated.")

    data = r_api.json()
    streaming_url = data.get("streaming_url")
    if not streaming_url:
        raise ValueError("Vidara did not return a valid playable video stream.")

    raw_title = data.get("title") or f"Vidara_{filecode}"
    clean_title = re.sub(r'[^\w\-_\. ]', '_', raw_title).strip() or f"Vidara_{filecode}"
    thumbnail = data.get("thumbnail")

    return _sync_ytdlp_download(
        streaming_url,
        output_dir,
        max_size_bytes,
        progress=progress,
        quality=quality,
        custom_title=clean_title,
        custom_thumb=thumbnail,
        custom_headers={"Referer": f"https://{domain}/"}
    )


def _sync_ytdlp_download(
    url: str,
    output_dir: str,
    max_size_bytes: int,
    progress: DownloadProgress | None = None,
    quality: str = "best",
    custom_title: str | None = None,
    custom_thumb: str | None = None,
    custom_headers: dict | None = None
) -> dict:
    """Synchronous worker to extract and download media via yt-dlp with live progress hook and thumbnail support."""
    out_tmpl = os.path.join(output_dir, "%(title).80B.%(ext)s")
    
    def _progress_hook(d):
        if progress:
            if progress.is_cancelled:
                raise yt_dlp.utils.DownloadCancelled("Download cancelled by user.")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                current = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0.0
                eta = d.get("eta") or 0
                progress.total = total
                progress.current = current
                progress.speed = speed
                progress.eta = eta

    cookie_file = get_cookie_file()
    
    # Configure quality format selector
    if quality == "360":
        fmt = "best[height<=360][ext=mp4]/bestvideo[height<=360]+bestaudio/best[height<=360]/best"
    elif quality == "720":
        fmt = "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    else:
        fmt = "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"

    ydl_opts = {
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "format": fmt,
        "max_filesize": max_size_bytes,
        "noplaylist": True,
        "geo_bypass": True,
        "retries": 5,
        "socket_timeout": 30,
        "progress_hooks": [_progress_hook],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"]
            }
        }
    }

    if custom_headers:
        ydl_opts["http_headers"].update(custom_headers)

    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file
        logger.info(f"Using cookies file: {cookie_file}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("Could not extract media info from this link.")

            filename = None
            if "requested_downloads" in info and info["requested_downloads"]:
                filename = info["requested_downloads"][0].get("filepath")
            
            if not filename or not os.path.exists(filename):
                filename = ydl.prepare_filename(info)

            if not os.path.exists(filename):
                files = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
                if files:
                    filename = max(files, key=os.path.getctime)
                else:
                    raise FileNotFoundError("Downloaded media file could not be located on disk.")

            file_size = os.path.getsize(filename)
            if file_size > max_size_bytes:
                max_mb = max_size_bytes // (1024 * 1024)
                file_mb = file_size // (1024 * 1024)
                raise ValueError(f"Media size ({file_mb} MB) exceeds maximum allowed limit ({max_mb} MB).")

            title = custom_title or info.get("title") or os.path.basename(filename)
            raw_duration = info.get("duration")
            duration = int(raw_duration) if isinstance(raw_duration, (int, float)) and raw_duration > 0 else None

            raw_width = info.get("width")
            width = int(raw_width) if isinstance(raw_width, (int, float)) and raw_width > 0 else None

            raw_height = info.get("height")
            height = int(raw_height) if isinstance(raw_height, (int, float)) and raw_height > 0 else None

            ext = os.path.splitext(filename)[1].lower()
            is_audio = ext in (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg") or bool(info.get("vcodec") == "none")

            # Extract official platform thumbnail image
            thumb_path = None
            raw_thumb_url = custom_thumb or info.get("thumbnail")
            if not raw_thumb_url and info.get("thumbnails"):
                raw_thumb_url = info["thumbnails"][-1].get("url")

            if raw_thumb_url and isinstance(raw_thumb_url, str) and raw_thumb_url.startswith("http"):
                try:
                    web_thumb = os.path.join(output_dir, "web_thumb.jpg")
                    r_th = cffi_requests.get(raw_thumb_url, timeout=10, impersonate="chrome120")
                    if r_th.status_code == 200:
                        with open(web_thumb, "wb") as f_th:
                            f_th.write(r_th.content)
                        with Image.open(web_thumb) as im:
                            im = im.convert("RGB")
                            im.thumbnail((640, 360), Image.Resampling.LANCZOS)
                            im.save(web_thumb, "JPEG", quality=85, optimize=True)
                        thumb_path = web_thumb
                except Exception as e_th:
                    logger.debug(f"Could not download web thumbnail: {e_th}")
                    logger.debug(f"Could not download web thumbnail: {e_th}")

            if not is_audio:
                if not thumb_path or not duration or not width or not height:
                    auto_thumb_file = os.path.join(output_dir, "auto_thumb.jpg") if not thumb_path else None
                    v_meta = extract_video_metadata(filename, auto_thumb_file)
                    if not thumb_path and v_meta.get("thumb_path"):
                        thumb_path = v_meta["thumb_path"]
                    if not duration and v_meta.get("duration"):
                        duration = v_meta["duration"]
                    if not width and v_meta.get("width"):
                        width = v_meta["width"]
                    if not height and v_meta.get("height"):
                        height = v_meta["height"]

            return {
                "file_path": filename,
                "file_name": os.path.basename(filename),
                "file_size": file_size,
                "title": title,
                "is_video": not is_audio,
                "is_audio": is_audio,
                "duration": duration,
                "width": width,
                "height": height,
                "thumbnail": thumb_path
            }

    except yt_dlp.utils.DownloadCancelled:
        raise asyncio.CancelledError("Download cancelled by user.")
    except yt_dlp.utils.DownloadError as de:
        err_str = str(de)
        logger.warning(f"yt-dlp download error for {url}: {err_str}")
        if "login required" in err_str.lower() or "not available to everyone" in err_str.lower() or "rate-limit reached" in err_str.lower():
            if "instagram" in url.lower():
                raise ValueError(
                    "🔒 <b>Instagram Login / Cookies Required:</b>\n\n"
                    "Instagram has restricted this Reel/Post (age-restricted or rate-limited).\n\n"
                    "💡 <b>To fix this:</b>\n"
                    "Place your <code>cookies.txt</code> in the bot directory to download any Instagram post or reel without restrictions!"
                )
            raise ValueError("🔒 This content requires a login session or cookies.")
        elif "403" in err_str or "forbidden" in err_str.lower():
            raise ValueError("❌ Server returned HTTP 403 Forbidden. The host has restricted access to this media stream.")
        elif any(k in err_str.lower() for k in ("timed out", "timeout", "semaphore timeout", "connection refused", "connect timeout")):
            raise ValueError(
                "⏱️ <b>Server Unreachable / Connection Timed Out:</b>\n\n"
                "The media host server is not responding or is blocked by your network/ISP firewall.\n\n"
                "💡 <i>Tip: Adult / pirate sites are frequently blocked by Indian ISPs (Jio, Airtel, Vi) at network level.</i>"
            )
        elif "unavailable" in err_str.lower() or "private" in err_str.lower():
            raise ValueError("❌ This video or link is private or unavailable.")
        raise ValueError(f"Extraction error: {err_str[:120]}")


async def download_media(url: str, output_dir: str, max_size_bytes: int, progress: DownloadProgress | None = None, quality: str = "best") -> dict:
    """High-level async orchestrator for downloading any social media, LuLuStream, Vidara, or direct file URL."""
    os.makedirs(output_dir, exist_ok=True)

    # 1. Specialized LuLuStream and mirror domains handler
    if is_lulustream_url(url):
        return await asyncio.to_thread(download_lulustream, url, output_dir, max_size_bytes, progress)

    # 2. Specialized Vidara and mirror domains handler
    if is_vidara_url(url):
        return await asyncio.to_thread(download_vidara, url, output_dir, max_size_bytes, progress, quality)

    # 3. If direct download link, use fast direct streamer
    if is_direct_download_link(url):
        try:
            return await download_direct_file(url, output_dir, max_size_bytes, progress=progress)
        except Exception as e:
            err_msg = str(e).lower()
            if any(k in err_msg for k in ("timeout", "semaphore", "cannot connect", "connectionrefused", "name or service not known", "getaddrinfo failed")):
                raise ValueError(
                    "⏱️ <b>Server Unreachable / Connection Timed Out:</b>\n\n"
                    "The media host server is not responding or is blocked by your network/ISP firewall.\n\n"
                    "💡 <i>Tip: Adult / pirate sites are frequently blocked by Indian ISPs (Jio, Airtel, Vi) at network level.</i>"
                )
            logger.warning(f"Direct stream download failed for {url}: {e}. Retrying via yt-dlp...")

    # 3. Use yt-dlp in background thread with progress callback, quality selector, and auto-thumbnail
    return await asyncio.to_thread(_sync_ytdlp_download, url, output_dir, max_size_bytes, progress, quality)


def clean_temp_dir(dir_path: str):
    """Safely purge temporary download directory from disk."""
    try:
        if dir_path and os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
    except Exception as e:
        logger.debug(f"Error purging temp dir {dir_path}: {e}")


def purge_stale_temp_downloads(temp_root: str = "temp_downloads"):
    """Purge all leftover temporary directories from previous bot sessions on startup."""
    try:
        if os.path.exists(temp_root):
            count = 0
            for item in os.listdir(temp_root):
                item_path = os.path.join(temp_root, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                        count += 1
                    else:
                        os.remove(item_path)
                        count += 1
                except Exception:
                    pass
            if count > 0:
                logger.info(f"Purged {count} leftover temporary download folder(s) on startup.")
    except Exception as e:
        logger.warning(f"Error purging stale temp downloads: {e}")
