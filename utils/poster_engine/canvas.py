import io
import math
import os
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICONS_DIR = ASSETS_DIR / "icons"

_FONTS_CACHE = {}


def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Retrieve TrueType font from assets/fonts or return default fallback."""
    key = (name.lower(), size)
    if key in _FONTS_CACHE:
        return _FONTS_CACHE[key]

    target_path = None
    if FONTS_DIR.exists():
        # Exact match or prefix match
        for f in FONTS_DIR.iterdir():
            if f.is_file() and name.lower() in f.stem.lower():
                target_path = f
                break

    font = None
    if target_path and target_path.exists():
        try:
            font = ImageFont.truetype(str(target_path), size)
        except Exception:
            pass

    if not font:
        # Fallback to system fonts or default
        for fb in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(fb, size)
                break
            except Exception:
                pass

    if not font:
        font = ImageFont.load_default()

    _FONTS_CACHE[key] = font
    return font


def get_icon(name: str, size: tuple = None) -> Image.Image | None:
    """Load PNG icon with transparency from assets/icons/."""
    icon_path = ICONS_DIR / name
    if not icon_path.exists():
        return None

    try:
        img = Image.open(icon_path).convert("RGBA")
        if size:
            img = img.resize(size, Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def colorize_icon(icon: Image.Image, color: tuple) -> Image.Image:
    """Tint or colorize an RGBA icon."""
    if not icon:
        return None
    r, g, b = color[:3]
    colored = Image.new("RGBA", icon.size, (r, g, b, 255))
    mask = icon.split()[3]
    colored.putalpha(mask)
    return colored


def load_image_from_url(url: str, timeout: int = 10) -> Image.Image | None:
    """Download external image from URL and return as RGBA Image."""
    if not url or not url.startswith("http"):
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        pass
    return None


def create_gradient_overlay(width: int, height: int, mode: str = "v") -> Image.Image:
    """Create smooth RGBA linear gradient overlay."""
    w, h = max(1, width), max(1, height)
    ramp = Image.linear_gradient("L")
    tv = ramp.resize((w, h), Image.Resampling.BILINEAR)
    if mode == "h":
        tv = tv.transpose(Image.Transpose.ROTATE_90)
    overlay = Image.new("RGBA", (w, h), (10, 10, 15, 255))
    overlay.putalpha(tv)
    return overlay


def create_cinematic_vignette(width: int, height: int) -> Image.Image:
    """Generate subtle dark cinematic vignette shadow around the borders."""
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vignette)
    
    # Outer dark frame with smooth radial falloff
    steps = 15
    for i in range(steps):
        alpha = int(180 * (1 - (i / steps) ** 1.5))
        margin_x = int((width / 2) * (i / steps))
        margin_y = int((height / 2) * (i / steps))
        draw.rectangle(
            [margin_x, margin_y, width - margin_x, height - margin_y],
            outline=(10, 10, 15, alpha),
            width=int(width / steps)
        )
    return vignette.filter(ImageFilter.GaussianBlur(30))


def apply_watermark(canvas: Image.Image, brand_text: str, is_premium: bool = False):
    """Draw stylish professional channel branding at top right unless user is premium VIP."""
    if is_premium or not brand_text or not brand_text.strip():
        return

    clean_brand = brand_text.strip().upper()
    display_brand = clean_brand if clean_brand.startswith("@") else f"@{clean_brand}"
    font = get_font("Poppins-SemiBold", 24)
    draw = ImageDraw.Draw(canvas)

    padding_x = 20
    padding_y = 10
    text_bbox = draw.textbbox((0, 0), display_brand, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    w, h = canvas.size
    box_w = text_w + (padding_x * 2)
    box_h = text_h + (padding_y * 2)
    pos_x = w - box_w - 45
    pos_y = 45

    # Draw pill badge with glass effect
    badge = Image.new("RGBA", (box_w, box_h), (15, 23, 42, 210))
    b_draw = ImageDraw.Draw(badge)
    b_draw.rounded_rectangle([0, 0, box_w, box_h], radius=14, outline=(56, 189, 248, 140), width=2)
    b_draw.text((padding_x, padding_y - 2), display_brand, font=font, fill=(241, 245, 249, 240))

    canvas.paste(badge, (pos_x, pos_y), badge)


def draw_liquid_glass_pill(canvas: Image.Image, text: str, cx: int, cy: int, font=None, text_color=(241, 245, 249), border_color=(56, 189, 248, 140), bg_color=(15, 23, 42, 215)):
    """Draw a centered translucent liquid-glass pill badge."""
    if not text:
        return
    if font is None:
        font = get_font("Poppins-SemiBold", 24)

    draw = ImageDraw.Draw(canvas)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]

    pad_x = 26
    pad_y = 12
    pw = tw + pad_x * 2
    ph = th + pad_y * 2

    px = int(cx - (pw / 2))
    py = int(cy)

    pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill)
    p_draw.rounded_rectangle([0, 0, pw, ph], radius=ph // 2, fill=bg_color, outline=border_color, width=1)
    p_draw.text((pad_x, pad_y - 2), text, font=font, fill=text_color)
    canvas.paste(pill, (px, py), pill)


def draw_quality_badge(canvas: Image.Image, label: str = "4K UHD", pos_x: int = 50, pos_y: int = 50):
    """Draw sleek top-left media quality tag (e.g. 4K UHD, 1080p)."""
    font = get_font("Poppins-Bold", 18)
    draw = ImageDraw.Draw(canvas)
    text_bbox = draw.textbbox((0, 0), label, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]

    pad_x = 14
    pad_y = 6
    bw = tw + pad_x * 2
    bh = th + pad_y * 2

    badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(badge)
    b_draw.rounded_rectangle([0, 0, bw, bh], radius=8, fill=(10, 10, 15, 200), outline=(255, 255, 255, 60), width=1)
    b_draw.text((pad_x, pad_y - 2), label, font=font, fill=(245, 158, 11))  # Amber/gold 4K text
    canvas.paste(badge, (pos_x, pos_y), badge)
