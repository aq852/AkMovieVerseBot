"""
Video Screenshot Generator Module (Admin Only)
==============================================
Extracts high-definition sample screenshots from videos/clips at evenly spaced intervals,
applies custom branding watermark via Pillow, and delivers them in a compact Telegram photo album.
Safeguards server memory with a 500 MB size cap.
"""

import os
import time
import shutil
import tempfile
import asyncio
import logging
import html
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

try:
    from hydrogram import Client, filters
    from hydrogram.types import Message, InputMediaPhoto
except ImportError:
    from pyrogram import Client, filters
    from pyrogram.types import Message, InputMediaPhoto

from config import Config
from utils.helpers import get_readable_size, format_clean_title

logger = logging.getLogger(__name__)

MAX_SCREENSHOT_FILE_SIZE_MB = 500


def apply_watermark(image_path: str, watermark_text: str = "@AkMovieVerse") -> str:
    """Draw an elegant semi-transparent branding pill badge on the image."""
    try:
        with Image.open(image_path).convert("RGBA") as base:
            overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)

            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

            w, h = base.size
            text = f"  {watermark_text}  "

            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # Bottom-right corner padding
            pad = 20
            box_x0 = w - text_w - pad - 16
            box_y0 = h - text_h - pad - 12
            box_x1 = w - pad
            box_y1 = h - pad

            draw.rounded_rectangle(
                [box_x0, box_y0, box_x1, box_y1],
                radius=8,
                fill=(10, 14, 23, 200),
                outline=(229, 9, 20, 220),
                width=1
            )

            draw.text((box_x0 + 8, box_y0 + 6), text, fill=(255, 255, 255, 240), font=font)

            result = Image.alpha_composite(base, overlay)
            out_rgb = result.convert("RGB")
            out_rgb.save(image_path, "JPEG", quality=90)
    except Exception as e:
        logger.warning(f"Error applying watermark to {image_path}: {e}")
    return image_path


async def get_video_duration(file_path: str) -> float:
    """Get duration of video in seconds using ffprobe with strict timeout and no hang."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return 0.0

        dur_str = stdout.decode().strip()
        if dur_str:
            return float(dur_str)
    except Exception as e:
        logger.debug(f"ffprobe duration check failed: {e}")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
    return 0.0


async def extract_frame_ffmpeg(video_path: str, timestamp_sec: float, output_path: str) -> bool:
    """Extract a single frame at timestamp using ffmpeg with strict timeout and no hang."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-y",
            "-ss", f"{timestamp_sec:.2f}",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            "-loglevel", "error",
            output_path,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning(f"ffmpeg frame extraction timed out at {timestamp_sec}s")
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return False

        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        logger.warning(f"ffmpeg frame extraction failed at {timestamp_sec}s: {e}")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        return False


@Client.on_message(filters.command(["ss", "screenshot", "screenshots"]))
async def generate_screenshots_command(client: Client, message: Message):
    """Admin-only command to extract high-quality sample screenshots from replied video."""
    user_id = message.from_user.id if message.from_user else 0
    if not Config.is_admin(user_id):
        return await message.reply_text("⛔ <b>Access Denied:</b> This command is restricted to bot administrators.")

    reply = message.reply_to_message
    if not reply:
        return await message.reply_text(
            "ℹ️ <b>Reply to a video file</b> with <code>/ss [count]</code> to generate screenshots.\n\n"
            "<b>Usage:</b>\n"
            "• <code>/ss</code> (Default 5 screenshots)\n"
            "• <code>/ss 8</code> (Custom count: 2-10 frames)\n"
            "• <code>/ss 6 @MyChannel</code> (Custom watermark)"
        )

    # Detect video media
    media = reply.video or reply.animation
    if not media and reply.document:
        mime = getattr(reply.document, "mime_type", "") or ""
        fname = (getattr(reply.document, "file_name", "") or "").lower()
        if mime.startswith("video/") or fname.endswith((".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts")):
            media = reply.document

    if not media:
        return await message.reply_text("⚠️ <b>Invalid Media:</b> Please reply to a valid video file.")

    # File size validation (500MB limit)
    file_size = getattr(media, "file_size", 0)
    max_bytes = MAX_SCREENSHOT_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        size_mb = file_size / (1024 * 1024)
        return await message.reply_text(
            f"⚠️ <b>File Size Exceeds Limit:</b> <code>{size_mb:.1f} MB</code>\n\n"
            f"<i>Maximum supported size for screenshots is <code>{MAX_SCREENSHOT_FILE_SIZE_MB} MB</code> "
            "to safeguard memory on cloud free tier.</i>"
        )

    # Parse arguments: count and custom watermark
    count = 5
    watermark = getattr(Config, "DEFAULT_POSTER_BRAND", "@AkMovieVerse") or "@AkMovieVerse"

    parts = message.text.split()[1:]
    for part in parts:
        if part.isdigit():
            count = max(2, min(10, int(part)))  # Telegram media group limit: 2-10 photos
        elif part.startswith("@"):
            watermark = part

    file_name = getattr(media, "file_name", None) or "Video_Sample.mp4"
    status_msg = await message.reply_text("⏳ <b>Downloading video sample...</b> [0%]")

    temp_dir = tempfile.mkdtemp(prefix="ss_temp_")
    try:
        last_edit = [time.time()]

        async def progress(current, total):
            now = time.time()
            if now - last_edit[0] > 3:
                last_edit[0] = now
                pct = (current / total) * 100
                cur_str = get_readable_size(current)
                tot_str = get_readable_size(total)
                try:
                    await status_msg.edit_text(
                        f"⏳ <b>Downloading video sample:</b> <code>{pct:.1f}%</code>\n"
                        f"📊 <code>{cur_str} / {tot_str}</code>"
                    )
                except Exception:
                    pass

        # Download media file
        video_path = await client.download_media(
            message=reply,
            file_name=os.path.join(temp_dir, file_name),
            progress=progress
        )

        if not video_path or not os.path.exists(video_path):
            return await status_msg.edit_text("❌ <b>Download Error:</b> Failed to download video file.")

        await status_msg.edit_text(f"📸 <b>Extracting {count} screenshot frames via FFmpeg...</b>")

        # Determine video duration
        duration = getattr(media, "duration", 0)
        if duration <= 0:
            duration = await get_video_duration(video_path)

        if duration <= 2:
            duration = 10.0  # Fallback duration for short clips

        # Calculate evenly spaced timestamps avoiding dark intro and outro
        step = duration / (count + 1)
        timestamps = [step * (i + 1) for i in range(count)]

        screenshot_files = []
        for idx, ts in enumerate(timestamps, start=1):
            frame_path = os.path.join(temp_dir, f"screenshot_{idx}.jpg")
            ok = await extract_frame_ffmpeg(video_path, ts, frame_path)
            if ok:
                apply_watermark(frame_path, watermark_text=watermark)
                screenshot_files.append(frame_path)

        if not screenshot_files:
            return await status_msg.edit_text(
                "❌ <b>Extraction Failed:</b> Could not extract frames from this video.\n"
                "<i>Ensure video format is supported and FFmpeg is available.</i>"
            )

        await status_msg.edit_text("🚀 <b>Uploading screenshot album to chat...</b>")

        # Send as InputMediaPhoto Album
        caption = (
            "📸 <b>SAMPLE SCREENSHOTS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎬 <b>File:</b> <code>{html.escape(format_clean_title(file_name))}</code>\n"
            f"💾 <b>Size:</b> <code>{get_readable_size(file_size)}</code>  •  ⏱️ <b>Frames:</b> <code>{len(screenshot_files)} Samples</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <b>Channel:</b> <code>{html.escape(watermark)}</code>"
        )

        media_group = []
        for i, f_path in enumerate(screenshot_files):
            cap = caption if i == 0 else None
            media_group.append(InputMediaPhoto(media=f_path, caption=cap))

        await client.send_media_group(
            chat_id=message.chat.id,
            media=media_group,
            reply_to_message_id=reply.id
        )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in generate_screenshots_command: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>")
        except Exception:
            pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
