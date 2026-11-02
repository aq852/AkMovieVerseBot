import io
import uuid
import base64
import aiohttp
import logging
from config import Config

logger = logging.getLogger(__name__)

PROXY_UPLOAD_URL = "https://api-integretion-unblocked.vercel.app/imgbb"
OFFICIAL_IMGBB_URL = "https://api.imgbb.com/1/upload"


async def upload_to_imgbb(image_io: io.BytesIO) -> str | None:
    """Upload poster image to ImgBB or cloud CDN asynchronously and return direct image URL."""
    try:
        image_io.seek(0)
        img_bytes = image_io.read()
        image_io.seek(0)

        # 1. If user configured official IMGBB_API_KEY
        if Config.IMGBB_API_KEY:
            try:
                b64_data = base64.b64encode(img_bytes).decode("utf-8")
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    payload = {"key": Config.IMGBB_API_KEY, "image": b64_data}
                    async with session.post(OFFICIAL_IMGBB_URL, data=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            url = data.get("data", {}).get("url") or data.get("data", {}).get("display_url")
                            if url:
                                return url
            except Exception as e:
                logger.warning(f"Official ImgBB upload failed: {e}")

        # 2. Proxy Upload Fallback
        try:
            filename = f"poster_{uuid.uuid4().hex[:10]}.jpg"
            data = aiohttp.FormData()
            data.add_field("file", img_bytes, filename=filename, content_type="image/jpeg")

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                async with session.post(PROXY_UPLOAD_URL, data=data) as resp:
                    if resp.status == 200:
                        res = await resp.json(content_type=None)
                        if isinstance(res, dict) and "url" in res:
                            return res["url"]
        except Exception as e:
            logger.debug(f"Proxy upload failed: {e}")

    except Exception as e:
        logger.error(f"Image upload failed: {e}")

    return None
