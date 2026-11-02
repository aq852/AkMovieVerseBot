import io
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .canvas import (
    get_font, load_image_from_url, apply_watermark, draw_liquid_glass_pill, draw_quality_badge
)

# Landscape standard: 1920x1080 (16:9)
W, H = 1920, 1080

# Portrait Leech/Stremio standard: 1000x1500 (2:3)
PW, PH = 1000, 1500

STYLE_NAMES = {
    1: "Spatial Leech Poster",
    2: "Spatial Cinema Banner",
    3: "Minimalist Letterbox",
    4: "Frosted Glass Card",
    5: "Multi-Ratings Studio Card",
    6: "Anime Studio Edition",
    7: "Pure Clean Backdrop",
    8: "Pure Clean Poster"
}


def _get_bg_image(media_data: dict, art_index: int = 0) -> Image.Image:
    """Extract best candidate backdrop or cover and scale to fill 1920x1080."""
    images = media_data.get("images", {})
    all_backdrops = images.get("all_backdrops", [])

    candidates = []
    if all_backdrops and 0 <= art_index < len(all_backdrops):
        candidates.append(all_backdrops[art_index])

    candidates.extend([
        images.get("banner_backdrop"),
        images.get("landscape_poster"),
        media_data.get("bannerImage"),
        media_data.get("backdrop_url"),
        images.get("portrait_poster")
    ])

    for url in candidates:
        if url:
            img = load_image_from_url(url)
            if img:
                iw, ih = img.size
                scale = max(W / iw, H / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                left = (nw - W) // 2
                top = (nh - H) // 2
                return img.crop((left, top, left + W, top + H))

    return Image.new("RGBA", (W, H), (15, 17, 23, 255))


def _get_portrait_image(media_data: dict, art_index: int = 0) -> Image.Image:
    """Extract best candidate vertical portrait or textless cover and scale to 1000x1500."""
    images = media_data.get("images", {})
    all_posters = images.get("all_posters", [])

    candidates = []
    if all_posters and 0 <= art_index < len(all_posters):
        candidates.append(all_posters[art_index])

    candidates.extend([
        images.get("textless_poster"),
        images.get("portrait_poster"),
        (media_data.get("coverImage", {}).get("extraLarge") if isinstance(media_data.get("coverImage"), dict) else None),
        images.get("banner_backdrop"),
        media_data.get("bannerImage")
    ])

    for url in candidates:
        if url:
            img = load_image_from_url(url)
            if img:
                iw, ih = img.size
                scale = max(PW / iw, PH / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                left = (nw - PW) // 2
                top = (nh - PH) // 2
                return img.crop((left, top, left + PW, top + PH))

    return Image.new("RGBA", (PW, PH), (15, 17, 23, 255))


# ----------------------------------------------------------------------
# Style 1: Spatial Leech Poster (Portrait 2:3 - 1000x1500)
# ----------------------------------------------------------------------
def render_spatial_leech_poster(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 1: Flagship Spatial Leech Poster (Portrait 2:3) with Official Logo & Pill Badge."""
    canvas = Image.new("RGBA", (PW, PH), (15, 15, 15, 255))
    bg = _get_portrait_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    # Bottom subtle vignette (lower 35%)
    vignette = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(vignette)
    for y in range(PH):
        if y > 920:
            alpha = int(220 * ((y - 920) / 580) ** 1.3)
            d.line([(0, y), (PW, y)], fill=(8, 10, 15, alpha))
    canvas = Image.alpha_composite(canvas, vignette)

    images = media_data.get("images", {})
    logo_url = images.get("logo")
    logo_img = load_image_from_url(logo_url) if logo_url else None

    pill_y = PH - 140
    if logo_img:
        lw = int(PW * 0.74)
        lh = int(logo_img.height * (lw / logo_img.width))
        if lh > int(PH * 0.20):
            lh = int(PH * 0.20)
            lw = int(logo_img.width * (lh / logo_img.height))
        resized_logo = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
        lx = (PW - lw) // 2
        ly = PH - lh - 170
        canvas.paste(resized_logo, (lx, ly), resized_logo)
        pill_y = ly + lh + 25
    else:
        draw = ImageDraw.Draw(canvas)
        title = (media_data.get("display_title") or "Movie Title").strip().upper()
        t_font = get_font("BebasNeue Bold", 92)
        wrapped = textwrap.wrap(title, width=22)
        ty = PH - 280 - (len(wrapped) * 90)
        for line in wrapped[:2]:
            tw = int(draw.textlength(line, font=t_font))
            tx = (PW - tw) // 2
            draw.text((tx + 3, ty + 3), line, font=t_font, fill=(0, 0, 0, 230))
            draw.text((tx, ty), line, font=t_font, fill=(255, 255, 255))
            ty += 96
        pill_y = ty + 15

    # Liquid Glass Pill Badge
    year = str(media_data.get("year", ""))
    genres_list = [g for g in media_data.get("genres", []) if g.lower() not in ("movie", "series", "feature film")]
    genres_str = "  •  ".join(genres_list[:3]).upper()

    badge_parts = []
    if year:
        badge_parts.append(year)
    if genres_str:
        badge_parts.append(genres_str)
    rating_val = media_data.get("rating")
    if rating_val and float(rating_val) > 0:
        badge_parts.append(f"{rating_val}/10")

    badge_text = "   •   ".join(badge_parts)
    if badge_text:
        draw_liquid_glass_pill(canvas, badge_text, cx=PW // 2, cy=pill_y)

    draw_quality_badge(canvas, "4K UHD", pos_x=45, pos_y=45)
    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 2: Spatial Cinema Banner (Landscape 16:9 - 1920x1080)
# ----------------------------------------------------------------------
def render_spatial_cinema_banner(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 2: Spatial Cinema Banner (Landscape 16:9) with Official Logo & Pill Badge."""
    canvas = Image.new("RGBA", (W, H), (15, 15, 15, 255))
    bg = _get_bg_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grad)
    for y in range(H):
        if y > 680:
            alpha = int(220 * ((y - 680) / 400) ** 1.3)
            d.line([(0, y), (W, y)], fill=(8, 10, 15, alpha))
    canvas = Image.alpha_composite(canvas, grad)

    images = media_data.get("images", {})
    logo_url = images.get("logo")
    logo_img = load_image_from_url(logo_url) if logo_url else None

    pill_y = H - 150
    cx = 280
    if logo_img:
        lw = int(W * 0.42)
        lh = int(logo_img.height * (lw / logo_img.width))
        if lh > int(H * 0.22):
            lh = int(H * 0.22)
            lw = int(logo_img.width * (lh / logo_img.height))
        resized_logo = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
        lx = 90
        ly = H - lh - 160
        canvas.paste(resized_logo, (lx, ly), resized_logo)
        pill_y = ly + lh + 25
        cx = lx + (lw // 2)
    else:
        draw = ImageDraw.Draw(canvas)
        title = (media_data.get("display_title") or "Movie Title").strip().upper()
        t_font = get_font("BebasNeue Bold", 100)
        wrapped = textwrap.wrap(title, width=28)
        ty = 820 - (len(wrapped) * 105)
        for line in wrapped[:2]:
            draw.text((92, ty + 4), line, font=t_font, fill=(0, 0, 0, 220))
            draw.text((90, ty), line, font=t_font, fill=(255, 255, 255))
            ty += 108
        pill_y = ty + 15
        cx = 90 + int(draw.textlength(wrapped[0], font=t_font) // 2)

    year = str(media_data.get("year", ""))
    genres_list = [g for g in media_data.get("genres", []) if g.lower() not in ("movie", "series")]
    genres_str = "  •  ".join(genres_list[:3]).upper()
    badge_parts = []
    if year:
        badge_parts.append(year)
    if genres_str:
        badge_parts.append(genres_str)
    rating_val = media_data.get("rating")
    if rating_val and float(rating_val) > 0:
        badge_parts.append(f"{rating_val}/10")
    badge_text = "   •   ".join(badge_parts)

    if badge_text:
        draw_liquid_glass_pill(canvas, badge_text, cx=max(260, cx), cy=pill_y)

    draw_quality_badge(canvas, "4K UHD", pos_x=50, pos_y=45)
    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 3: Minimalist Letterbox (Landscape 16:9 - 1920x1080)
# ----------------------------------------------------------------------
def render_minimalist_letterbox_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 3: Minimalist Letterbox - Centered widescreen cinema layout with movie title and year."""
    canvas = Image.new("RGBA", (W, H), (10, 10, 12, 255))
    bg = _get_bg_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grad)
    for y in range(H):
        if y > 720:
            alpha = int(230 * ((y - 720) / 360) ** 1.3)
            d.line([(0, y), (W, y)], fill=(5, 5, 8, alpha))
    canvas = Image.alpha_composite(canvas, grad)

    draw = ImageDraw.Draw(canvas)
    title = (media_data.get("display_title") or "Movie Title").strip().upper()
    t_font = get_font("BebasNeue Bold", 110)
    tw = int(draw.textlength(title, font=t_font))
    tx = max(60, (W - tw) // 2)

    ty = 850
    draw.text((tx + 3, ty + 3), title, font=t_font, fill=(0, 0, 0, 230))
    draw.text((tx, ty), title, font=t_font, fill=(255, 255, 255))

    year = str(media_data.get("year", ""))
    if year:
        y_font = get_font("Poppins-Medium", 28)
        y_text = f"•  {year}  •"
        yw = int(draw.textlength(y_text, font=y_font))
        draw.text(((W - yw) // 2, ty + 120), y_text, font=y_font, fill=(203, 213, 225))

    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 4: Frosted Glass Floating Card (Landscape 16:9 - 1920x1080)
# ----------------------------------------------------------------------
def render_frosted_floating_card_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 4: Frosted Glass Card - Ambient blurred background with embedded high-res portrait card."""
    bg = _get_bg_image(media_data, art_index)
    blurred_bg = bg.filter(ImageFilter.GaussianBlur(35))

    dark_mask = Image.new("RGBA", (W, H), (10, 14, 26, 175))
    canvas = Image.alpha_composite(blurred_bg, dark_mask)

    card_x, card_y = 140, 110
    card_w, card_h = 1640, 860

    glass = Image.new("RGBA", (card_w, card_h), (20, 27, 45, 215))
    g_draw = ImageDraw.Draw(glass)
    g_draw.rounded_rectangle([0, 0, card_w, card_h], radius=24, outline=(56, 189, 248, 120), width=2)
    canvas.paste(glass, (card_x, card_y), glass)

    # Embedded Vertical Portrait on Left
    images = media_data.get("images", {})
    all_posters = images.get("all_posters", [])
    p_url = (all_posters[art_index] if all_posters and 0 <= art_index < len(all_posters) else None) or images.get("portrait_poster") or images.get("textless_poster")
    if p_url:
        p_img = load_image_from_url(p_url)
        if p_img:
            pw, ph = 460, 690
            p_img = p_img.resize((pw, ph), Image.Resampling.LANCZOS)
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw, ph], radius=16, fill=255)
            canvas.paste(p_img, (card_x + 80, card_y + 85), mask)

    # Content on Right (Logo or Title + Pills)
    rx = card_x + 590
    ry = card_y + 240
    logo_url = images.get("logo")
    logo_img = load_image_from_url(logo_url) if logo_url else None

    if logo_img:
        lw = int(card_w * 0.50)
        lh = int(logo_img.height * (lw / logo_img.width))
        if lh > 180:
            lh = 180
            lw = int(logo_img.width * (lh / logo_img.height))
        resized_logo = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
        canvas.paste(resized_logo, (rx, ry), resized_logo)
        pill_y = ry + lh + 35
    else:
        draw = ImageDraw.Draw(canvas)
        title = (media_data.get("display_title") or "Movie Title").strip().upper()
        t_font = get_font("BebasNeue Bold", 96)
        wrapped = textwrap.wrap(title, width=22)
        ty = ry
        for line in wrapped[:2]:
            draw.text((rx, ty), line, font=t_font, fill=(255, 255, 255))
            ty += 105
        pill_y = ty + 15

    year = str(media_data.get("year", ""))
    genres_list = [g for g in media_data.get("genres", []) if g.lower() not in ("movie", "series")]
    genres_str = "   •   ".join(genres_list[:3]).upper()
    rating_val = media_data.get("rating")
    rating_str = f"{rating_val}/10" if rating_val and float(rating_val) > 0 else ""

    meta_parts = [p for p in (year, genres_str, rating_str) if p]
    meta_line = "   |   ".join(meta_parts)
    if meta_line:
        draw_liquid_glass_pill(canvas, meta_line, cx=rx + 350, cy=pill_y)

    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 5: Multi-Ratings Studio Card (Portrait 2:3 - 1000x1500)
# ----------------------------------------------------------------------
def render_multi_ratings_card_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 5: Multi-Ratings Studio Card - Clean vertical poster with dual rating badges."""
    canvas = Image.new("RGBA", (PW, PH), (15, 15, 15, 255))
    bg = _get_portrait_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    vignette = Image.new("RGBA", (PW, PH), (0, 0, 0, 0))
    d = ImageDraw.Draw(vignette)
    for y in range(PH):
        if y > 920:
            alpha = int(225 * ((y - 920) / 580) ** 1.3)
            d.line([(0, y), (PW, y)], fill=(8, 10, 15, alpha))
    canvas = Image.alpha_composite(canvas, vignette)

    images = media_data.get("images", {})
    logo_url = images.get("logo")
    logo_img = load_image_from_url(logo_url) if logo_url else None

    pill_y = PH - 140
    if logo_img:
        lw = int(PW * 0.74)
        lh = int(logo_img.height * (lw / logo_img.width))
        if lh > int(PH * 0.20):
            lh = int(PH * 0.20)
            lw = int(logo_img.width * (lh / logo_img.height))
        resized_logo = logo_img.resize((lw, lh), Image.Resampling.LANCZOS)
        lx = (PW - lw) // 2
        ly = PH - lh - 170
        canvas.paste(resized_logo, (lx, ly), resized_logo)
        pill_y = ly + lh + 25
    else:
        draw = ImageDraw.Draw(canvas)
        title = (media_data.get("display_title") or "Movie Title").strip().upper()
        t_font = get_font("BebasNeue Bold", 92)
        wrapped = textwrap.wrap(title, width=22)
        ty = PH - 280 - (len(wrapped) * 90)
        for line in wrapped[:2]:
            tw = int(draw.textlength(line, font=t_font))
            tx = (PW - tw) // 2
            draw.text((tx, ty), line, font=t_font, fill=(255, 255, 255))
            ty += 96
        pill_y = ty + 15

    # Multi Ratings Pill
    rating_val = media_data.get("rating")
    rating_text = f"TMDB {rating_val}/10" if rating_val and float(rating_val) > 0 else "TOP RATED"
    year = str(media_data.get("year", "2024"))
    pill_text = f"{rating_text}   •   {year} CINEMA"
    draw_liquid_glass_pill(canvas, pill_text, cx=PW // 2, cy=pill_y, border_color=(245, 158, 11, 160))

    draw_quality_badge(canvas, "IMAX / 4K", pos_x=45, pos_y=45)
    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 6: Anime Studio Edition (Landscape 16:9 - 1920x1080)
# ----------------------------------------------------------------------
def render_anime_edition_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 6: Anime Studio Edition - Japanese romaji/native subtitle + English title + clean tag."""
    canvas = Image.new("RGBA", (W, H), (15, 15, 15, 255))
    bg = _get_bg_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(grad)
    for y in range(H):
        if y > 680:
            alpha = int(225 * ((y - 680) / 400) ** 1.3)
            d.line([(0, y), (W, y)], fill=(8, 10, 15, alpha))
    canvas = Image.alpha_composite(canvas, grad)

    draw = ImageDraw.Draw(canvas)
    eng_title = (media_data.get("title", {}).get("english") or media_data.get("display_title") or "Anime").strip().upper()
    native_title = (media_data.get("title", {}).get("romaji") or media_data.get("title", {}).get("native") or "").strip()

    t_font = get_font("BebasNeue Bold", 96)
    ty = 830
    draw.text((92, ty + 3), eng_title[:32], font=t_font, fill=(0, 0, 0, 220))
    draw.text((90, ty), eng_title[:32], font=t_font, fill=(255, 255, 255))

    sub_font = get_font("Poppins-Medium", 24)
    if native_title and native_title != eng_title:
        draw.text((90, ty - 38), native_title[:36], font=sub_font, fill=(244, 114, 182))  # Pink anime aesthetic

    studio = media_data.get("studio") or "Studio Release"
    year = str(media_data.get("year", ""))
    pill_text = f"{year}   •   {studio.upper()}   •   OFFICIAL HD"
    draw_liquid_glass_pill(canvas, pill_text, cx=400, cy=ty + 110, border_color=(236, 72, 153, 140))

    draw_quality_badge(canvas, "ANIME HD", pos_x=50, pos_y=45)
    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 7: Pure Clean Artwork (Original 1080p - 1920x1080)
# ----------------------------------------------------------------------
def render_pure_artwork_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 7: Pure Clean Artwork - 100% original unadulterated high-res backdrop with only subtle branding."""
    canvas = Image.new("RGBA", (W, H), (15, 15, 15, 255))
    bg = _get_bg_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Style 8: Pure Clean Poster (Portrait 2:3 - 1000x1500)
# ----------------------------------------------------------------------
def render_pure_portrait_style(media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Style 8: Pure Clean Textless Poster - 1000x1500 original vertical art with subtle branding."""
    canvas = Image.new("RGBA", (PW, PH), (15, 15, 15, 255))
    bg = _get_portrait_image(media_data, art_index)
    canvas.paste(bg, (0, 0))

    apply_watermark(canvas, brand_text, is_premium)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Universal Dispatcher
# ----------------------------------------------------------------------
def generate_poster_canvas(style_id: int, media_data: dict, brand_text: str = "", is_premium: bool = False, art_index: int = 0) -> io.BytesIO:
    """Universal dispatcher for generating any of the 8 Spatial & Clean styles."""
    style_id = int(style_id)
    if style_id == 1:
        return render_spatial_leech_poster(media_data, brand_text, is_premium, art_index)
    elif style_id == 2:
        return render_spatial_cinema_banner(media_data, brand_text, is_premium, art_index)
    elif style_id == 3:
        return render_minimalist_letterbox_style(media_data, brand_text, is_premium, art_index)
    elif style_id == 4:
        return render_frosted_floating_card_style(media_data, brand_text, is_premium, art_index)
    elif style_id == 5:
        return render_multi_ratings_card_style(media_data, brand_text, is_premium, art_index)
    elif style_id == 6:
        return render_anime_edition_style(media_data, brand_text, is_premium, art_index)
    elif style_id == 7:
        return render_pure_artwork_style(media_data, brand_text, is_premium, art_index)
    elif style_id == 8:
        return render_pure_portrait_style(media_data, brand_text, is_premium, art_index)
    else:
        return render_spatial_leech_poster(media_data, brand_text, is_premium, art_index)
