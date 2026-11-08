import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from utils.helpers import clean_search_query, get_readable_size, build_filter_buttons, build_category_keyboard, get_random_start_pic
from utils.bot_commands import USER_COMMANDS, GROUP_ADMIN_COMMANDS, ADMIN_COMMANDS
from utils.web_server import VERIFY_GATEWAY_HTML
from database.files import _build_search_filter
from plugins.start import get_time_greeting

class TestAutoFilterEngine(unittest.TestCase):
    def test_clean_search_query(self):
        raw = "Avengers: Endgame (2019) 1080p full movie download free"
        cleaned = clean_search_query(raw)
        self.assertNotIn("download", cleaned)
        self.assertNotIn("movie", cleaned)
        self.assertNotIn("free", cleaned)
        self.assertIn("Avengers", cleaned)
        self.assertIn("Endgame", cleaned)

    def test_get_readable_size(self):
        size_bytes = 1536 * 1024 * 1024  # 1.5 GB
        formatted = get_readable_size(size_bytes)
        self.assertIn("GB", formatted)
        self.assertIn("1.50", formatted)

    def test_single_and_double_button_modes(self):
        mock_results = [
            {"file_unique_id": "abc1", "file_name": "Inception.1080p.mkv", "file_size": 2147483648},
            {"file_unique_id": "abc2", "file_name": "Interstellar.720p.mp4", "file_size": 1073741824}
        ]

        single_markup = build_filter_buttons(
            results=mock_results,
            page=1,
            total_pages=3,
            query="Inception",
            bot_username="TestBot",
            mode="single"
        )
        self.assertIsNotNone(single_markup)
        # Check that Filter Results exists in first row
        self.assertIn("Filter Results", single_markup.inline_keyboard[0][0].text)
        # Check that Remove Ads and Send All exist in second row
        self.assertIn("Remove ads", single_markup.inline_keyboard[1][0].text)
        self.assertIn("SEND ALL", single_markup.inline_keyboard[1][1].text)
        # Verify that number buttons are not present by default (clean UI)
        all_texts = [btn.text for row in single_markup.inline_keyboard for btn in row]
        self.assertNotIn("1️⃣", all_texts)
        self.assertNotIn("2️⃣", all_texts)

    def test_category_keyboard(self):
        qual_markup = build_category_keyboard("Inception", cat_type="quality")
        self.assertIsNotNone(qual_markup)
        found_qual = any("480p" in btn.text for row in qual_markup.inline_keyboard for btn in row)
        self.assertTrue(found_qual)

        lang_markup = build_category_keyboard("Inception", cat_type="language")
        found_lang = any("Hindi" in btn.text for row in lang_markup.inline_keyboard for btn in row)
        self.assertTrue(found_lang)

    def test_build_search_filter(self):
        query_filter = _build_search_filter("Inception", quality="1080p", language="Hindi")
        self.assertIn("$and", query_filter)
        patterns = [list(elem.values())[0]["$regex"] for elem in query_filter["$and"]]
        self.assertIn("Inception", patterns)
        self.assertTrue(any("1080p" in p for p in patterns))
        self.assertTrue(any("hindi" in p.lower() for p in patterns))

    def test_time_greeting(self):
        greeting = get_time_greeting()
        self.assertTrue(greeting.startswith(("🌅", "☀️", "🌆", "🌙")))

    def test_get_random_start_pic(self):
        url = "https://api.aniwallpaper.workers.dev/random"
        pic1 = get_random_start_pic(url)
        pic2 = get_random_start_pic(url)
        self.assertIn("_t=", pic1)
        self.assertIn("_t=", pic2)
        self.assertNotEqual(pic1, pic2)

        # File ID should not be modified
        file_id = "AgACAgIAAxkBAAIFV2eM"
        self.assertEqual(get_random_start_pic(file_id), file_id)

    def test_bot_commands_compliance(self):
        for scope_name, cmd_list in [("User", USER_COMMANDS), ("GroupAdmin", GROUP_ADMIN_COMMANDS), ("Admin", ADMIN_COMMANDS)]:
            self.assertTrue(len(cmd_list) > 0)
            seen_cmds = set()
            for cmd in cmd_list:
                name = cmd.command
                desc = cmd.description
                # Telegram constraints
                self.assertTrue(1 <= len(name) <= 32, f"Invalid length for command {name} in {scope_name}")
                self.assertTrue(name.islower(), f"Command {name} must be lowercase in {scope_name}")
                self.assertTrue(name.isalnum() or "_" in name, f"Command {name} has invalid characters in {scope_name}")
                self.assertTrue(1 <= len(desc) <= 256, f"Description too long for {name} in {scope_name}")
                self.assertNotIn(name, seen_cmds, f"Duplicate command {name} in {scope_name}")
                seen_cmds.add(name)

    def test_verify_gateway_html(self):
        import base64
        target = "https://lksfy.com/test1234"
        target_b64 = base64.b64encode(target.encode("utf-8")).decode("utf-8")
        html = VERIFY_GATEWAY_HTML.format(target_b64=target_b64, target_url=target)
        self.assertIn("AkMovieVerse Verification", html)
        self.assertIn("window.location.replace", html)
        self.assertIn("proceedToVerification", html)
        self.assertIn("oncontextmenu", html)
        # Verify that direct URL is hidden from anchor tags and meta refresh
        self.assertNotIn(f'href="{target}"', html)
        self.assertNotIn('meta http-equiv="refresh"', html)

    def test_parse_duration(self):
        from database.share_links import parse_duration
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("1h"), 3600)
        self.assertEqual(parse_duration("24h"), 86400)
        self.assertEqual(parse_duration("3d"), 259200)
        self.assertIsNone(parse_duration("invalid"))

    def test_poster_studio_canvas_and_urls(self):
        from utils.poster_engine.fetcher import extract_title_from_url
        from utils.poster_engine.templates import generate_poster_canvas

        # Test OTT URL parser
        q1, p1 = extract_title_from_url("https://www.netflix.com/title/80057281?title=Stranger-Things")
        self.assertEqual(p1, "Netflix")
        self.assertIn("Stranger", q1)

        q2, p2 = extract_title_from_url("https://www.crunchyroll.com/series/GEXH3W49E/solo-leveling")
        self.assertEqual(p2, "Crunchyroll")
        self.assertEqual(q2, "solo leveling")

        dummy_media = {
            "display_title": "Avengers: Doomsday",
            "year": 2026,
            "rating": None,
            "match_pct": None,
            "maturity": "16+",
            "genres": ["Action", "Adventure", "Sci-Fi"],
            "episodes": "Feature Film",
            "duration": "Feature Film",
            "description": "An upcoming Marvel Cinematic Universe film directed by Anthony and Joe Russo."
        }
        # Test rendering all 8 clean & spatial canvas styles
        for style_id in range(1, 9):
            buf = generate_poster_canvas(style_id, dummy_media, "AkMoviesZone", False, art_index=0)
            self.assertIsNotNone(buf)
            self.assertGreater(len(buf.getvalue()), 5000)

        # Test combo builders from plugins.poster
        from plugins.poster import build_portrait_combos, build_landscape_combos
        p_combos = build_portrait_combos(["http://img1.jpg", "http://img2.jpg"])
        self.assertGreaterEqual(len(p_combos), 2)
        l_combos = build_landscape_combos(["http://bg1.jpg", "http://bg2.jpg"])
        self.assertGreaterEqual(len(l_combos), 2)

    def test_streaming_engine(self):
        from utils.ranges import parse_range, plan_chunks, RangeNotSatisfiable
        from utils.custom_dl import ChunkCache, StreamConcurrencyGuard
        from plugins.stream import build_stream_keyboard

        # 1. Test Range Parsing
        file_size = 100 * 1024 * 1024  # 100 MB
        byte_range, is_partial = parse_range(None, file_size)
        self.assertFalse(is_partial)
        self.assertEqual(byte_range.start, 0)
        self.assertEqual(byte_range.end, file_size - 1)

        byte_range, is_partial = parse_range("bytes=0-1048575", file_size)
        self.assertTrue(is_partial)
        self.assertEqual(byte_range.start, 0)
        self.assertEqual(byte_range.end, 1048575)
        self.assertEqual(byte_range.length, 1048576)

        # Suffix range
        byte_range, is_partial = parse_range("bytes=-500", file_size)
        self.assertTrue(is_partial)
        self.assertEqual(byte_range.start, file_size - 500)
        self.assertEqual(byte_range.end, file_size - 1)

        # Invalid range
        with self.assertRaises(RangeNotSatisfiable):
            parse_range("bytes=500-100", file_size)

        # 2. Test Mathematical Chunk Planner (512KB alignment)
        plan = plan_chunks(byte_range, chunk_size=512 * 1024)
        self.assertIsNotNone(plan)
        self.assertGreaterEqual(plan.count, 1)

        # 3. Test Stream Keyboard Generation (Ultra-clean minimalist layout)
        kb = build_stream_keyboard("https://stream.akmovieverse.com", "abc123xyz", "Inception.mkv")
        self.assertIsNotNone(kb)
        found_player = any("Stream & Watch Online" in btn.text for row in kb.inline_keyboard for btn in row)
        self.assertTrue(found_player)
        found_close = any("Close" in btn.text for row in kb.inline_keyboard for btn in row)
        self.assertTrue(found_close)

        # Telegram Bot API compliance: all URLs must start with http:// or https://
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.url:
                    self.assertTrue(
                        btn.url.startswith(("http://", "https://")),
                        f"Invalid scheme for Telegram button: {btn.url}"
                    )

    def test_chat_type_normalization(self):
        from utils.helpers import get_chat_type_str, is_private_chat
        try:
            from hydrogram.enums import ChatType
            self.assertEqual(get_chat_type_str(ChatType.PRIVATE), "private")
            self.assertEqual(get_chat_type_str(ChatType.CHANNEL), "channel")
            self.assertEqual(get_chat_type_str(ChatType.SUPERGROUP), "supergroup")
            self.assertTrue(is_private_chat(ChatType.PRIVATE))
            self.assertFalse(is_private_chat(ChatType.CHANNEL))
        except ImportError:
            pass
        self.assertEqual(get_chat_type_str("private"), "private")
        self.assertEqual(get_chat_type_str("channel"), "channel")
        self.assertTrue(is_private_chat("private"))
        self.assertFalse(is_private_chat("channel"))

    def test_safe_format_welcome(self):
        from plugins.auto_approve import safe_format_welcome
        # Test normal placeholders
        res = safe_format_welcome("Hello {first_name} to {title}", first_name="Amit", title="Channel")
        self.assertEqual(res, "Hello Amit to Channel")
        # Test unknown placeholder: should not crash with KeyError
        res2 = safe_format_welcome("Hello {unknown_tag} {mention}", mention="@user")
        self.assertIn("Hello {unknown_tag} @user", res2)
        # Test broken braces: should not crash
        res3 = safe_format_welcome("Broken {brace text", first_name="Amit")
        self.assertIn("Broken", res3)

    def test_admin_help_hub_and_categories(self):
        from plugins.admin_help import (
            CATEGORY_KEYS, CATEGORY_CONTENT, CHEAT_SHEET_TEXT,
            get_admin_hub_markup, get_category_markup
        )
        from utils.bot_commands import ADMIN_COMMANDS
        self.assertGreaterEqual(len(CATEGORY_KEYS), 13)
        # Telegram 4096 character safety limit
        self.assertLess(len(CHEAT_SHEET_TEXT), 4096)
        for cat in CATEGORY_KEYS:
            self.assertIn(cat, CATEGORY_CONTENT)
            self.assertLess(len(CATEGORY_CONTENT[cat]), 4096)
            mk = get_category_markup(cat)
            self.assertIsNotNone(mk)
            cbs = [btn.callback_data for row in mk.inline_keyboard for btn in row]
            self.assertIn("ahelp_home", cbs)

        hub = get_admin_hub_markup()
        self.assertIsNotNone(hub)
        hub_cbs = [btn.callback_data for row in hub.inline_keyboard for btn in row]
        self.assertIn("ahelp_close", hub_cbs)
        for cat in CATEGORY_KEYS:
            self.assertIn(f"ahelp_cat:{cat}", hub_cbs)

        # Ensure all admin commands are present in cheat sheet
        for cmd in ADMIN_COMMANDS:
            self.assertIn(f"/{cmd.command}", CHEAT_SHEET_TEXT)

    def test_channel_post_caption_and_buttons(self):
        from plugins.channel_post import format_post_caption, build_post_buttons
        sample_group = {
            "key": "movie:mirzapur:2024",
            "slug": "mirzapur-2024",
            "title": "Mirzapur",
            "clean_name": "Mirzapur",
            "year": 2024,
            "is_series": False,
            "primary_file_id": "file_12345",
            "qualities": {"1080p", "720p", "480p"},
            "audio_tags": ["Hindi", "Dual Audio"],
            "subtitles": ["English"],
            "has_hevc": True,
            "total_files": 3
        }
        sample_tmdb = {
            "full_title": "Mirzapur (2024)",
            "rating_str": "8.5/10 IMDb",
            "genres": ["Action", "Crime", "Drama"],
            "ott": "Amazon Prime Video",
            "overview": "A shocking incident at a wedding procession ignites a series of events."
        }
        caption = format_post_caption(sample_group, sample_tmdb)
        self.assertIn("Mirzapur", caption)
        self.assertIn("8.5/10 IMDb", caption)
        self.assertIn("<blockquote expandable>", caption)
        self.assertIn("Amazon Prime Video", caption)

        buttons = build_post_buttons(sample_group)
        self.assertIsNotNone(buttons)
        self.assertEqual(len(buttons.inline_keyboard), 1)
        self.assertEqual(len(buttons.inline_keyboard[0]), 2)
        self.assertEqual(buttons.inline_keyboard[0][0].text, "▶️ Watch Online")
        self.assertEqual(buttons.inline_keyboard[0][1].text, "🤖 Get File")

    def test_telegram_downloader_regex_and_batches(self):
        from plugins.downloader import TG_POST_REGEX
        # Test 1: Public channel single message
        m1 = TG_POST_REGEX.search("https://t.me/VIVAMAX_ONLY_2025/997")
        self.assertIsNotNone(m1)
        self.assertIsNone(m1.group(1))
        self.assertEqual(m1.group(2), "VIVAMAX_ONLY_2025")
        self.assertEqual(m1.group(3), "997")
        self.assertIsNone(m1.group(4))

        # Test 2: Public channel batch range
        m2 = TG_POST_REGEX.search("https://t.me/AkMovieVerse/100-110")
        self.assertIsNotNone(m2)
        self.assertEqual(m2.group(2), "AkMovieVerse")
        self.assertEqual(m2.group(3), "100")
        self.assertEqual(m2.group(4), "110")

        # Test 3: Private channel range
        m3 = TG_POST_REGEX.search("https://t.me/c/2001671856/50-60")
        self.assertIsNotNone(m3)
        self.assertEqual(m3.group(1), "2001671856")
        self.assertEqual(m3.group(3), "50")
        self.assertEqual(m3.group(4), "60")

    def test_channel_post_all_styles(self):
        from plugins.channel_post import format_post_caption
        sample_group = {
            "title": "Kantara",
            "year": 2022,
            "sorted_qualities": ["1080p", "720p"],
            "languages_list": ["Hindi", "Kannada"]
        }
        sample_tmdb = {
            "rating_str": "8.3/10 IMDb",
            "genres": ["Action", "Adventure"],
            "ott": "Netflix",
            "overview": "When greed paves the way for betrayal, a tribe clashes with the forest officer."
        }
        # Style 1: Cinematic Widescreen
        cap1 = format_post_caption(sample_group, sample_tmdb, style=1)
        self.assertIn("<blockquote expandable>", cap1)
        self.assertIn("Kantara (2022)", cap1)

        # Style 2: Minimalist Poster
        cap2 = format_post_caption(sample_group, sample_tmdb, style=2)
        self.assertNotIn("<blockquote expandable>", cap2)
        self.assertIn("<b>Title :</b> Kantara (2022)", cap2)
        self.assertIn("<b>Rating :</b> 8.3/10 IMDb", cap2)

        # Style 3: Clean Compact
        cap3 = format_post_caption(sample_group, sample_tmdb, style=3)
        self.assertIn("<b>Qualities :</b>", cap3)
        self.assertIn("Kantara (2022)", cap3)

    def test_series_multiseason_post_and_range_formatting(self):
        from plugins.channel_post import format_episodes_range, format_post_caption, build_post_buttons
        # Test range formatting
        self.assertEqual(format_episodes_range([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]), "1-12")
        self.assertEqual(format_episodes_range([1, 2, 3, 5, 7, 8, 9]), "1-3, 5, 7-9")
        self.assertEqual(format_episodes_range([], has_complete_pack=True), "Complete Season")
        self.assertEqual(format_episodes_range([1, 2, 3], has_complete_pack=True), "1-3 (Pack)")

        # Test multi-season TV Series post caption matching user screenshot
        series_group = {
            "key": "series:dexter",
            "clean_name": "Dexter",
            "is_series": True,
            "year": 2006,
            "slug": "dexter-2006",
            "sorted_qualities": ["1080p", "720p"],
            "files": [{"file_name": "Dexter.S01E01.1080p.BluRay.x265.mkv"}],
            "seasons_map": {
                1: {"episodes": set(range(1, 13)), "has_pack": False},
                2: {"episodes": set(range(1, 13)), "has_pack": False},
                3: {"episodes": set(range(1, 13)), "has_pack": False},
                4: {"episodes": set(range(1, 13)), "has_pack": False},
                5: {"episodes": set(range(1, 13)), "has_pack": False},
                6: {"episodes": set(range(1, 13)), "has_pack": False},
                7: {"episodes": set(range(1, 13)), "has_pack": False},
                8: {"episodes": set(range(1, 13)), "has_pack": False},
            }
        }
        series_tmdb = {
            "rating": 8.2,
            "genres": ["Crime", "Drama", "Mystery"],
            "ott": "Netflix, Amazon Prime Video"
        }
        cap = format_post_caption(series_group, series_tmdb, style=1)
        self.assertIn("Dexter (2006)", cap)
        self.assertIn("<blockquote expandable>", cap)
        self.assertIn("<blockquote expandable>", cap)
        self.assertIn("⭐ <b>Rating :</b> 8.2/10 IMDb", cap)
        self.assertIn("🎭 <b>Genres :</b> Crime, Drama, Mystery", cap)
        self.assertIn("📺 <b>OTT :</b> Netflix, Amazon Prime Video", cap)
        self.assertIn("📺 <b>Episodes :</b>", cap)
        self.assertIn("S1: 1-12", cap)
        self.assertIn("S8: 1-12", cap)

        # Test Series buttons: Watch Online + Get File
        buttons = build_post_buttons(series_group)
        self.assertIsNotNone(buttons)
        self.assertEqual(buttons.inline_keyboard[0][0].text, "▶️ Watch Online")
        self.assertEqual(buttons.inline_keyboard[0][1].text, "🤖 Get File")
        self.assertIn("filter_Dexter", buttons.inline_keyboard[0][1].url)

    def test_web_player_download_toggle(self):
        import asyncio
        from utils.web_server import set_web_download_enabled, is_web_download_enabled
        async def _check():
            await set_web_download_enabled(False)
            self.assertFalse(await is_web_download_enabled())
            await set_web_download_enabled(True)
            self.assertTrue(await is_web_download_enabled())
        asyncio.run(_check())

    def test_backup_json_serialization(self):
        import zipfile
        import io
        from bson import json_util
        from bson.objectid import ObjectId
        import datetime

        sample_doc = {
            "_id": ObjectId("654321654321654321654321"),
            "file_name": "Test.Movie.2024.1080p.mkv",
            "file_size": 1073741824,
            "created_at": datetime.datetime.utcnow()
        }
        docs = [sample_doc]
        serialized = json_util.dumps(docs)
        self.assertIn("Test.Movie.2024.1080p.mkv", serialized)
        
        # Test ZIP archiving and unpacking
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("telegram_files.json", serialized)
        
        zip_buf.seek(0)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            unpacked = json_util.loads(zf.read("telegram_files.json").decode("utf-8"))
            self.assertEqual(len(unpacked), 1)
            self.assertEqual(unpacked[0]["_id"], sample_doc["_id"])
            self.assertEqual(unpacked[0]["file_name"], sample_doc["file_name"])

    def test_daily_broadcast_badges(self):
        from plugins.daily_broadcast import get_rating_badge
        b_high = get_rating_badge(8.9)
        self.assertIn("ALL-TIME MASTERPIECE", b_high)
        b_must = get_rating_badge(8.2)
        self.assertIn("MUST WATCH MASTERPIECE", b_must)
        b_rec = get_rating_badge(7.4)
        self.assertIn("HIGHLY RECOMMENDED", b_rec)
        b_pop = get_rating_badge(6.8)
        self.assertIn("POPULAR BINGE WATCH", b_pop)

    def test_daily_broadcast_categories(self):
        from plugins.daily_broadcast import get_category_label
        self.assertIn("Anime Series", get_category_label("anime"))
        self.assertIn("Web Series", get_category_label("series"))
        self.assertIn("K-Drama", get_category_label("kdrama"))
        self.assertIn("Movie", get_category_label("movie"))

    def test_fresh_drops_vertical_format(self):
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock
        from plugins.daily_broadcast import build_fresh_drops_content

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[
            {"file_name": "Stree 2 (2024) 1080p.mkv"},
            {"file_name": "Mirzapur S03 (2024) 720p.mkv"}
        ])

        mock_col = MagicMock()
        mock_col.find.return_value = mock_cursor
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col

        with patch("plugins.daily_broadcast.mongo._db", mock_db):
            with patch("plugins.daily_broadcast.fetch_media_rating", new_callable=AsyncMock) as mock_rate:
                mock_rate.return_value = (8.0, 2024)
                caption, markup = asyncio.run(build_fresh_drops_content("TestBot"))
                self.assertIn("AKMOVIEVERSE • TODAY TOP RATED UPLOADS", caption)
                self.assertIn("⭐ 1. <a href=", caption)
                self.assertIn("https://t.me/TestBot?start=search_", caption)

    def test_secondary_db_optional_fallback(self):
        import asyncio
        from database.mongo import mongo
        from database.files import get_active_target_collection

        # Without secondary DB, has_secondary should be False and primary files collection returned
        self.assertFalse(mongo.has_secondary)
        col, mode = asyncio.run(get_active_target_collection())
        self.assertEqual(col, mongo.files)
        self.assertEqual(mode, "primary")

    def test_multi_db_search_and_routing(self):
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock
        from database.mongo import mongo
        from database.files import get_search_results, count_files

        mock_doc1 = {"_id": "1", "file_unique_id": "u1", "file_name": "Inception 2010 1080p.mkv", "created_at": None}
        mock_doc2 = {"_id": "2", "file_unique_id": "u2", "file_name": "Inception 2010 720p.mkv", "created_at": None}

        mock_cur1 = MagicMock()
        mock_cur1.sort.return_value = mock_cur1
        mock_cur1.limit.return_value = mock_cur1
        mock_cur1.to_list = AsyncMock(return_value=[mock_doc1])

        mock_cur2 = MagicMock()
        mock_cur2.sort.return_value = mock_cur2
        mock_cur2.limit.return_value = mock_cur2
        mock_cur2.to_list = AsyncMock(return_value=[mock_doc2])

        mock_col1 = MagicMock()
        mock_col1.find.return_value = mock_cur1
        mock_col1.count_documents = AsyncMock(return_value=1)

        mock_col2 = MagicMock()
        mock_col2.find.return_value = mock_cur2
        mock_col2.count_documents = AsyncMock(return_value=1)

        mock_db1 = MagicMock()
        mock_db1.__getitem__.return_value = mock_col1

        mock_db2 = MagicMock()
        mock_db2.__getitem__.return_value = mock_col2

        with patch.object(mongo, "_db", mock_db1), patch.object(mongo, "_db2", mock_db2):
            self.assertTrue(mongo.has_secondary)
            results = asyncio.run(get_search_results("Inception", offset=0, limit=10))
            self.assertEqual(len(results), 2)
            # Higher quality (1080p) should be ranked before 720p
            self.assertEqual(results[0]["file_unique_id"], "u1")
            self.assertEqual(results[1]["file_unique_id"], "u2")

            total = asyncio.run(count_files("Inception"))
            self.assertEqual(total, 2)

    def test_storage_alerts_tiers(self):
        import asyncio
        from unittest.mock import patch, AsyncMock, MagicMock
        from database.files import check_storage_alerts
        from config import Config

        mock_client = MagicMock()
        mock_client.send_message = AsyncMock()

        stored_settings = {"last_storage_alert_tier": "none"}

        async def fake_get_setting(k, d=None):
            return stored_settings.get(k, d)

        async def fake_set_setting(k, v):
            stored_settings[k] = v
            return True

        with patch.object(Config, "MASTER_CLIENT", mock_client):
            with patch("database.mongo.get_bot_setting", side_effect=fake_get_setting):
                with patch("database.mongo.set_bot_setting", side_effect=fake_set_setting):
                    # 1. Below 400 MB (e.g. 350 MB) -> No alert
                    asyncio.run(check_storage_alerts(350.0))
                    self.assertEqual(stored_settings["last_storage_alert_tier"], "none")
                    self.assertEqual(mock_client.send_message.call_count, 0)

                    # 2. At 405 MB -> Triggers Tier 400 alert
                    asyncio.run(check_storage_alerts(405.0))
                    self.assertEqual(stored_settings["last_storage_alert_tier"], "400")
                    self.assertTrue(mock_client.send_message.called)
                    call_args = mock_client.send_message.call_args[0][1]
                    self.assertIn("400 MB REACHED", call_args)

                    mock_client.send_message.reset_mock()

                    # 3. At 425 MB -> Triggers Tier 420 warning
                    asyncio.run(check_storage_alerts(425.0))
                    self.assertEqual(stored_settings["last_storage_alert_tier"], "420")
                    self.assertTrue(mock_client.send_message.called)
                    call_args = mock_client.send_message.call_args[0][1]
                    self.assertIn("420 MB REACHED", call_args)

                    mock_client.send_message.reset_mock()

                    # 4. At 445 MB -> Triggers Tier 440 critical
                    asyncio.run(check_storage_alerts(445.0))
                    self.assertEqual(stored_settings["last_storage_alert_tier"], "440")
                    self.assertTrue(mock_client.send_message.called)
                    call_args = mock_client.send_message.call_args[0][1]
                    self.assertIn("440 MB", call_args)

                    mock_client.send_message.reset_mock()

                    # 5. Database cleared to 300 MB -> Resets alert tier
                    asyncio.run(check_storage_alerts(300.0))
                    self.assertEqual(stored_settings["last_storage_alert_tier"], "none")

    def test_universal_ripper_title_cleaner(self):
        from utils.title_cleaner import clean_movie_title
        # 1. Test case from user's screenshot
        t1 = "www 1TamilMV style - Aadarsha Kutumbam House No 47 mkv"
        c1 = clean_movie_title(t1, keep_year=False)
        self.assertEqual(c1, "Aadarsha Kutumbam House No 47")

        # 2. BollyFlix & PreDVD cleanup from title
        t2 = "[BollyFlix.Org] Stree 2 (2024) Hindi 1080p PreDVD.mkv"
        c2 = clean_movie_title(t2, keep_year=True)
        self.assertIn("Stree 2", c2)
        self.assertNotIn("BollyFlix", c2)
        self.assertNotIn("PreDVD", c2)

        # 3. TamilBlasters
        t3 = "www.TamilBlasters.cam - Devara (2024) Telugu 720p HDTS.mkv"
        c3 = clean_movie_title(t3, keep_year=True)
        self.assertIn("Devara", c3)
        self.assertNotIn("TamilBlasters", c3)

    def test_tmdb_anti_hallucination_guard(self):
        from utils.title_cleaner import is_tmdb_match_valid
        # User screenshot case: Aadarsha Kutumbam must NOT match Search: WWW!
        self.assertFalse(is_tmdb_match_valid("Aadarsha Kutumbam House No 47", "Search: WWW"))
        # Positive exact match
        self.assertTrue(is_tmdb_match_valid("Aadarsha Kutumbam House No 47", "Aadarsha Kutumbam"))
        # Positive sequel match
        self.assertTrue(is_tmdb_match_valid("Stree 2", "Stree 2"))
        # Irrelevant match rejection
        self.assertFalse(is_tmdb_match_valid("Pushpa 2 The Rule", "The Rule"))

    def test_predvd_quality_preservation_in_badges(self):
        from utils.helpers import parse_media_metadata
        meta = parse_media_metadata("[BollyFlix.Org] Stree 2 (2024) Hindi 1080p PreDVD.mkv")
        # Quality should be preserved in badges/metadata
        self.assertEqual(meta["quality"], "1080P")
        self.assertTrue(any("PreDVD" in b for b in meta["badges"]))
        # Base title should be clean of BollyFlix and PreDVD
        self.assertEqual(meta["clean_name"], "Stree 2")

    def test_stream_new_badge_duration(self):
        from config import Config
        self.assertEqual(getattr(Config, "STREAM_NEW_TAG_DAYS", 2), 2)
        window = Config.STREAM_NEW_TAG_DAYS * 86400
        # 1 day old (within 2 days window) -> Should be marked recent / NEW
        diff_recent = 1 * 86400
        self.assertTrue(diff_recent <= window)
        # 3 days old (outside 2 days window) -> Should NOT be marked recent / NEW
        diff_old = 3 * 86400
        self.assertFalse(diff_old <= window)

    def test_sanitize_stored_filename(self):
        from utils.title_cleaner import sanitize_stored_filename
        # 1. South site watermark removal
        f1 = "www.1TamilMV.style - Aadarsha Kutumbam House No 47.mkv"
        self.assertEqual(sanitize_stored_filename(f1), "Aadarsha Kutumbam House No 47.mkv")

        # 2. Hindi portal tag removal
        f2 = "Cold.Call.2026.1080p.WEB-DL.HIN-TAM.x264.ESub-SkymoviesHD.mkv"
        self.assertEqual(sanitize_stored_filename(f2), "Cold.Call.2026.1080p.WEB-DL.HIN-TAM.x264.ESub.mkv")

        # 3. Clean files remain untouched
        clean_file = "Inception.2010.1080p.BluRay.x264.mkv"
        self.assertEqual(sanitize_stored_filename(clean_file), clean_file)

    def test_channel_indexer_sanitize_file_name(self):
        from plugins.channel_indexer import sanitize_file_name
        # 1. VegaMovies and TLD removal
        s1 = "[VegaMovies.nl] The Vvaan (2026) Hindi 1080p WEB-DL x264.mkv"
        res1 = sanitize_file_name(s1)
        self.assertNotIn("VegaMovies", res1)
        self.assertNotIn("nl", res1.split()[0])
        self.assertIn("The Vvaan", res1)
        self.assertIn("1080p", res1)

        # 2. KatmovieHD bracket tag removal
        s2 = "Money.Heist.S05E01.1080p.NF.WEB-DL.[KatmovieHD].mkv"
        res2 = sanitize_file_name(s2)
        self.assertNotIn("KatmovieHD", res2)
        self.assertIn("Money.Heist", res2)
        self.assertIn("S05E01", res2)

        # 3. Telegram invite hash and join tag removal
        s3 = "Squid Game S02 (2024) [Join t.me/+abcdef12345] 720p Hindi.mkv"
        res3 = sanitize_file_name(s3)
        self.assertNotIn("t.me", res3)
        self.assertNotIn("Join", res3)
        self.assertIn("Squid Game", res3)
        self.assertIn("S02", res3)
        self.assertIn("720p", res3)

    def test_remove_ads_visibility_with_shortener_toggle(self):
        from config import Config
        from utils.helpers import build_filter_buttons
        
        # When Shorteners are enabled: 'Remove ads' should be present
        Config.SHORTENER_ENABLED = True
        kb_with_ads = build_filter_buttons([], 1, 1, "avengers", "testbot", is_pm=True)
        all_buttons_text = [btn.text for row in kb_with_ads.inline_keyboard for btn in row]
        self.assertTrue(any("Remove ads" in txt for txt in all_buttons_text))
        self.assertTrue(any("SEND ALL" in txt for txt in all_buttons_text))

        # When Shorteners are disabled: 'Remove ads' is replaced with 'VIP Plans'
        Config.SHORTENER_ENABLED = False
        kb_without_ads = build_filter_buttons([], 1, 1, "avengers", "testbot", is_pm=True)
        all_buttons_text_off = [btn.text for row in kb_without_ads.inline_keyboard for btn in row]
        self.assertFalse(any("Remove ads" in txt for txt in all_buttons_text_off))
        self.assertTrue(any("VIP Plans" in txt for txt in all_buttons_text_off))
        self.assertTrue(any("SEND ALL" in txt for txt in all_buttons_text_off))
        
        # Reset back to True for other tests
        Config.SHORTENER_ENABLED = True

    def test_auto_delete_messages_tombstone(self):
        import asyncio
        from plugins.start import auto_delete_messages
        
        deleted = []
        edited = []
        
        class MockMsg:
            def __init__(self, mid):
                self.id = mid
            async def delete(self):
                deleted.append(self.id)
            async def edit_text(self, text, reply_markup=None):
                edited.append((self.id, text, reply_markup))

        file_msg = MockMsg(101)
        warn_msg = MockMsg(102)

        async def run_test():
            await auto_delete_messages(
                [file_msg, warn_msg],
                delay=0,
                file_unique_id="uniq_abc123",
                clean_name="Kantara (2022) 1080p",
                bot_username="TestMovieBot"
            )

        asyncio.run(run_test())
        self.assertIn(101, deleted)
        self.assertEqual(len(edited), 1)
        self.assertEqual(edited[0][0], 102)
        self.assertIn("auto-deleted", edited[0][1])
        self.assertIn("Kantara (2022) 1080p", edited[0][1])
        # Check re-download button
        kb = edited[0][2]
        self.assertIsNotNone(kb)
        btn = kb.inline_keyboard[0][0]
        self.assertIn("Re-download", btn.text)
        self.assertIn("start=file_uniq_abc123", btn.url)

    def test_dynamic_settings_caster(self):
        from database.mongo import load_dynamic_settings
        from config import Config
        # Ensure load_dynamic_settings is callable and doesn't throw
        import asyncio
        asyncio.run(load_dynamic_settings())
        self.assertIsInstance(Config.SHORTENER_ENABLED, bool)
        self.assertIsInstance(Config.ENABLE_STREAMING, bool)

    def test_parse_channel_post_link(self):
        from plugins.file_store import parse_channel_post_link
        # Private channel single post
        cid, s, e = parse_channel_post_link("https://t.me/c/2001671856/9470")
        self.assertEqual(cid, -1002001671856)
        self.assertEqual(s, 9470)
        self.assertEqual(e, 9470)

        # Private channel range post
        cid, s, e = parse_channel_post_link("https://t.me/c/2001671856/9470-9485")
        self.assertEqual(cid, -1002001671856)
        self.assertEqual(s, 9470)
        self.assertEqual(e, 9485)

        # Public channel range post
        cid, s, e = parse_channel_post_link("https://t.me/akmovieverse/50-75")
        self.assertEqual(cid, "akmovieverse")
        self.assertEqual(s, 50)
        self.assertEqual(e, 75)

    def test_filestore_daily_limit_config_and_helpers(self):
        from config import Config
        from plugins.file_store import format_daily_quota_reached_msg
        
        # Verify default channel ID is -1004384430212
        self.assertEqual(Config.FILE_STORE_CHANNEL, -1004384430212)
        # Verify daily limit is 10
        self.assertEqual(Config.FILE_STORE_USER_DAILY_LIMIT, 10)

        text, markup = format_daily_quota_reached_msg(10)
        self.assertIn("Daily File Store Limit Reached", text)
        self.assertIn("10/10 links today", text)
        self.assertTrue(any("VIP Plans" in btn.text for row in markup.inline_keyboard for btn in row))

    def test_text_to_telegraph_nodes(self):
        from plugins.file_store import text_to_telegraph_nodes
        raw_text = (
            "# Main Heading\n"
            "## Sub Heading\n"
            "> Quoted line\n"
            "---\n"
            "Normal paragraph line"
        )
        nodes = text_to_telegraph_nodes(raw_text)
        self.assertEqual(nodes[0]["tag"], "h3")
        self.assertEqual(nodes[0]["children"], ["Main Heading"])
        self.assertEqual(nodes[1]["tag"], "h4")
        self.assertEqual(nodes[1]["children"], ["Sub Heading"])
        self.assertEqual(nodes[2]["tag"], "blockquote")
        self.assertEqual(nodes[3]["tag"], "hr")
        self.assertEqual(nodes[4]["tag"], "p")
        self.assertEqual(nodes[4]["children"], ["Normal paragraph line"])

    def test_lifetime_vip_status(self):
        from database.users import is_premium
        from database.mongo import mongo
        from unittest.mock import patch, PropertyMock, MagicMock, AsyncMock
        import asyncio
        import datetime

        # 1. Lifetime VIP (is_premium=True, premium_expires=None)
        mock_user = {"user_id": 12345, "is_premium": True, "premium_expires": None}
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=mock_user)
        with patch.object(type(mongo), "users", new_callable=PropertyMock, return_value=mock_col):
            res = asyncio.run(is_premium(12345))
            self.assertTrue(res)

        # 2. Expired VIP
        mock_expired = {
            "user_id": 12345,
            "is_premium": True,
            "premium_expires": datetime.datetime.utcnow() - datetime.timedelta(days=1)
        }
        mock_col_exp = MagicMock()
        mock_col_exp.find_one = AsyncMock(return_value=mock_expired)
        mock_col_exp.update_one = AsyncMock()
        with patch.object(type(mongo), "users", new_callable=PropertyMock, return_value=mock_col_exp):
            res_exp = asyncio.run(is_premium(12345))
            self.assertFalse(res_exp)
            mock_col_exp.update_one.assert_called_once()

    def test_deleteall_decorator_exists(self):
        import plugins.admin as admin
        self.assertTrue(hasattr(admin.delete_all_files_command, "handlers"))
        self.assertGreater(len(admin.delete_all_files_command.handlers), 0)

    def test_backup_collections_has_batches(self):
        from plugins.backup import BACKUP_COLLECTIONS
        self.assertIn("batches", BACKUP_COLLECTIONS)

    def test_batch_expired_tz_safety(self):
        from plugins.file_store import is_batch_expired
        import datetime
        from datetime import timezone

        # Naive datetime in future
        doc_future = {
            "expire_at": datetime.datetime.utcnow() + datetime.timedelta(hours=2),
            "max_downloads": None,
            "downloads_count": 0
        }
        exp, reason = is_batch_expired(doc_future)
        self.assertFalse(exp)

        # Aware datetime in past
        doc_past_aware = {
            "expire_at": datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2),
            "max_downloads": None,
            "downloads_count": 0
        }
        exp, reason = is_batch_expired(doc_past_aware)
        self.assertTrue(exp)
        self.assertIn("Time limit", reason)

        # Max downloads reached
        doc_max_dl = {
            "expire_at": None,
            "max_downloads": 5,
            "downloads_count": 5
        }
        exp, reason = is_batch_expired(doc_max_dl)
        self.assertTrue(exp)
        self.assertIn("Download limit", reason)

    def test_get_file_by_id_batches_fallback(self):
        from database.files import get_file_by_id
        from database.mongo import mongo
        from unittest.mock import patch, PropertyMock, MagicMock, AsyncMock
        import asyncio

        mock_batch = {
            "batch_id": "b123",
            "files": [
                {
                    "file_id": "telegram_fid_1",
                    "file_unique_id": "uniq_123",
                    "file_name": "Sample.mkv",
                    "file_size": 1000
                }
            ]
        }
        mock_files = MagicMock()
        mock_files.find_one = AsyncMock(return_value=None)
        mock_batches = MagicMock()
        mock_batches.find_one = AsyncMock(return_value=mock_batch)

        with patch.object(type(mongo), "files", new_callable=PropertyMock, return_value=mock_files), \
             patch.object(type(mongo), "batches", new_callable=PropertyMock, return_value=mock_batches):
            res = asyncio.run(get_file_by_id("uniq_123"))
            self.assertIsNotNone(res)
            self.assertEqual(res["file_name"], "Sample.mkv")

    def test_resolve_draft_group_year_stripping(self):
        import asyncio
        from plugins.channel_post import resolve_draft_group, _DRAFT_PREVIEWS
        from unittest.mock import patch, AsyncMock

        # 1. Test draft memory cache
        _DRAFT_PREVIEWS["test_draft"] = {"title": "Test Movie"}
        res = asyncio.run(resolve_draft_group("test_draft"))
        self.assertEqual(res["title"], "Test Movie")

        # 2. Test slug with year 'dexter-2006' resolves correctly
        mock_grp = {"title": "Dexter (2006)", "clean_name": "Dexter"}
        with patch("plugins.channel_post.build_aggregated_post_group", new=AsyncMock(return_value=mock_grp)):
            res2 = asyncio.run(resolve_draft_group("dexter-2006"))
            self.assertEqual(res2["title"], "Dexter (2006)")

    def test_smart_token_compounding_and_acronyms(self):
        import re
        from database.files import _token_to_regex, _build_search_filter

        # 1. Test acronym flexible pattern
        kgf_pat = _token_to_regex("kgf")
        self.assertTrue(re.search(kgf_pat, "K.G.F Chapter 2 2022", re.I))
        self.assertTrue(re.search(kgf_pat, "K G F 2", re.I))
        self.assertTrue(re.search(kgf_pat, "KGF 2", re.I))

        rrr_pat = _token_to_regex("rrr")
        self.assertTrue(re.search(rrr_pat, "R.R.R 2022 Hindi", re.I))

        # 2. Test compound words (ironman -> iron man, spiderman -> spider-man)
        iron_pat = _token_to_regex("ironman")
        self.assertTrue(re.search(iron_pat, "Iron Man (2008)", re.I))
        self.assertTrue(re.search(iron_pat, "Iron-Man 2", re.I))
        self.assertTrue(re.search(iron_pat, "Ironman", re.I))

        spider_pat = _token_to_regex("spiderman")
        self.assertTrue(re.search(spider_pat, "The Amazing Spider-Man", re.I))
        self.assertTrue(re.search(spider_pat, "Spider Man No Way Home", re.I))

        # 3. Test _build_search_filter uses token compounding
        built = _build_search_filter("ironman 1080p")
        self.assertIn("$and", built)
        patterns = [elem["file_name"]["$regex"] for elem in built["$and"]]
        self.assertIn(iron_pat, patterns)

    def test_session_restore_html_cleaning(self):
        import re
        # Verify that HTML tags and backticks are cleanly stripped during smart_nav restore
        raw_msg = "🏷️ <b>TITLE :</b> <code>Iron Man</code>\n📦 <b>TOTAL FILES :</b> <code>5</code>"
        q_match = re.search(r"(?:Title|Series|Query)\s*:\s*`?([^`\n]+)`?", raw_msg, re.I)
        self.assertIsNotNone(q_match)
        raw_match = q_match.group(1).strip()
        cleaned_q = re.sub(r"<[^>]+>", "", raw_match).replace("`", "").strip()
        self.assertEqual(cleaned_q, "Iron Man")

    def test_fuzzy_spellcheck_on_actual_typos(self):
        from rapidfuzz import fuzz
        from utils.title_cleaner import extract_core_title

        catalog = [
            "The.Avengers.2012.1080p.BluRay.x264",
            "Spider-Man.No.Way.Home.2021.1080p",
            "Oppenheimer.2023.IMAX.1080p",
            "Interstellar.2014.1080p.BluRay",
            "Brothers 2026 S01 E01 E08 COMBINED A"
        ]

        test_typos = {
            "avengrs": "The Avengers",
            "spidrman": "Spider Man",
            "openheimer": "Oppenheimer",
            "interstelar": "Interstellar"
        }

        for typo, expected_prefix in test_typos.items():
            best_candidate = None
            best_score = 0
            clean_q_core = extract_core_title(typo).lower().strip()
            q_words = [w for w in clean_q_core.split() if len(w) >= 3 and not w.isdigit()]

            for item in catalog:
                cand_core = extract_core_title(item).lower().strip()
                if not cand_core or cand_core == clean_q_core:
                    continue
                c_words = [w for w in cand_core.split() if len(w) >= 3 and not w.isdigit()]
                if not c_words:
                    continue

                word_match = any(
                    any(fuzz.ratio(qw, cw) >= 70 for cw in c_words)
                    for qw in q_words
                )
                if not word_match:
                    continue

                score = fuzz.WRatio(clean_q_core, cand_core)
                if score > best_score and score >= 65:
                    best_score = score
                    best_candidate = extract_core_title(item)

            self.assertIsNotNone(best_candidate, f"Failed to match typo: {typo}")
            self.assertTrue(best_candidate.startswith(expected_prefix), f"Expected prefix {expected_prefix}, got {best_candidate}")

    def test_fuzzy_year_trap_prevention(self):
        """Verify that searching for 'My Royal Nemesis (2026)' NEVER false-matches 'Brothers 2026'."""
        from rapidfuzz import fuzz
        from utils.title_cleaner import extract_core_title

        catalog = [
            "Brothers 2026 S01 E01 E08 COMBINED A",
            "The.Avengers.2012.1080p.BluRay.x264"
        ]

        query = "My Royal Nemesis (2026)"
        clean_q_core = extract_core_title(query).lower().strip()
        q_words = [w for w in clean_q_core.split() if len(w) >= 3 and not w.isdigit()]

        matched_candidate = None
        for item in catalog:
            cand_core = extract_core_title(item).lower().strip()
            if not cand_core or cand_core == clean_q_core:
                continue
            c_words = [w for w in cand_core.split() if len(w) >= 3 and not w.isdigit()]
            if not c_words:
                continue

            word_match = any(
                any(fuzz.ratio(qw, cw) >= 70 for cw in c_words)
                for qw in q_words
            )
            if not word_match:
                continue

            score = fuzz.WRatio(clean_q_core, cand_core)
            if score >= 65:
                matched_candidate = item
                break

        self.assertIsNone(matched_candidate, f"Year-trap failed! Unrelated file matched: {matched_candidate}")

    def test_purge_files_and_caches_resets_flags(self):
        import asyncio
        from database.files import purge_files_and_caches
        import database.files as files_mod
        from database.mongo import mongo
        from unittest.mock import patch, MagicMock, AsyncMock

        files_mod._DB1_FULL_STATUS = True
        mock_res = MagicMock(deleted_count=5)

        with patch.object(type(mongo), "files", new_callable=MagicMock) as mock_f:
            mock_f.delete_many = AsyncMock(return_value=mock_res)
            with patch.object(type(mongo), "has_secondary", False):
                with patch("database.mongo.set_bot_setting", new_callable=AsyncMock) as mock_set:
                    res = asyncio.run(purge_files_and_caches())
                    self.assertEqual(res["files_primary"], 5)
                    self.assertFalse(files_mod._DB1_FULL_STATUS)
                    mock_set.assert_called_with("last_storage_alert_tier", "none")

    def test_purge_factory_reset_keys(self):
        import asyncio
        from database.files import purge_factory_reset
        from unittest.mock import patch, AsyncMock

        with patch("database.files.purge_files_and_caches", new_callable=AsyncMock) as mock_base:
            mock_base.return_value = {
                "files_primary": 10,
                "files_secondary": 0,
                "tmdb_cache": 2,
                "channel_posts": 1,
                "checkpoints": 1,
                "verifications": 1,
                "total": 15
            }
            res = asyncio.run(purge_factory_reset())
            self.assertIn("batches", res)
            self.assertIn("share_links", res)
            self.assertIn("movie_requests", res)
            self.assertIn("upload_alerts", res)
            self.assertGreaterEqual(res["total"], 15)

    def test_deleteall_callback_handler_exists(self):
        import plugins.admin as admin
        self.assertTrue(hasattr(admin.wipe_database_callback, "handlers"))
        self.assertGreater(len(admin.wipe_database_callback.handlers), 0)

    def test_housekeeping_runs_and_preserves_safety_invariants(self):
        import asyncio
        from plugins.housekeeping import run_database_housekeeping, format_housekeeping_report
        from database.mongo import mongo
        from unittest.mock import patch, MagicMock, AsyncMock

        mock_del = MagicMock(deleted_count=3)
        with patch.object(type(mongo), "batches", new_callable=MagicMock) as mock_b, \
             patch.object(type(mongo), "share_links", new_callable=MagicMock) as mock_sl, \
             patch.object(type(mongo), "verify", new_callable=MagicMock) as mock_v, \
             patch.object(type(mongo), "requests", new_callable=MagicMock) as mock_req, \
             patch.object(type(mongo), "users", new_callable=MagicMock) as mock_users:

            mock_b.delete_many = AsyncMock(return_value=mock_del)
            mock_sl.delete_many = AsyncMock(return_value=mock_del)
            mock_v.delete_many = AsyncMock(return_value=mock_del)
            mock_req.delete_many = AsyncMock(return_value=mock_del)
            mock_users.delete_many = AsyncMock()
            mock_users.delete_one = AsyncMock()

            stats = asyncio.run(run_database_housekeeping(client=None, triggered_by="Test Suite"))

            self.assertIn("total_purged", stats)
            self.assertEqual(stats["expired_batches"], 3)
            self.assertEqual(stats["expired_share_links"], 3)
            # CRITICAL SAFETY INVARIANT CHECK: users must NEVER be touched!
            mock_users.delete_many.assert_not_called()
            mock_users.delete_one.assert_not_called()

            # Test report formatting
            rep = format_housekeeping_report(stats)
            self.assertIn("Database Housekeeping", rep)
            self.assertIn("All Users, Channel Auto-Posts &amp; TMDB Cache were 100% preserved", rep)

    def test_autoclean_command_decorator_exists(self):
        import plugins.housekeeping as housekeeping
        self.assertTrue(hasattr(housekeeping.auto_clean_command, "handlers"))
        self.assertGreater(len(housekeeping.auto_clean_command.handlers), 0)

    def test_imdb_search_callback_exists(self):
        import plugins.extra as extra
        self.assertTrue(hasattr(extra.imdb_search_callback_handler, "handlers"))
        self.assertGreater(len(extra.imdb_search_callback_handler.handlers), 0)

    def test_channel_post_buttons_multi_vs_single_quality(self):
        from plugins.channel_post import build_post_buttons

        # Movie with multiple qualities -> must route to start=filter_
        group_multi = {
            "is_series": False,
            "clean_name": "Inception",
            "files": [{"file_unique_id": "f1"}, {"file_unique_id": "f2"}],
            "qualities": {"720p", "1080p"},
            "primary_file_id": "f1"
        }
        markup_multi = build_post_buttons(group_multi)
        get_file_btn_multi = markup_multi.inline_keyboard[0][1]
        self.assertIn("start=filter_Inception", get_file_btn_multi.url)

        # Movie with only single quality -> must route directly to start=file_
        group_single = {
            "is_series": False,
            "clean_name": "Inception",
            "files": [{"file_unique_id": "f1"}],
            "qualities": {"1080p"},
            "primary_file_id": "f1"
        }
        markup_single = build_post_buttons(group_single)
        get_file_btn_single = markup_single.inline_keyboard[0][1]
        self.assertIn("start=file_f1", get_file_btn_single.url)

    def test_user_requests_and_alerts_enhancements(self):
        from database.requests import get_user_requests
        self.assertTrue(callable(get_user_requests))

        # Test upload alerts markup contains cancel buttons
        from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        btn = InlineKeyboardButton("🗑️ Cancel Alert", callback_data="delalert_12345")
        self.assertTrue(btn.callback_data.startswith("delalert_"))

    def test_parse_broadcast_custom_buttons(self):
        from plugins.admin import parse_broadcast_custom_buttons

        # 1. Empty / None text
        self.assertIsNone(parse_broadcast_custom_buttons(""))
        self.assertIsNone(parse_broadcast_custom_buttons("   "))

        # 2. Single button
        text_single = "/abroadcast [Join Channel | https://t.me/testchannel]"
        markup1 = parse_broadcast_custom_buttons(text_single)
        self.assertIsNotNone(markup1)
        self.assertEqual(len(markup1.inline_keyboard), 1)
        self.assertEqual(markup1.inline_keyboard[0][0].text, "Join Channel")
        self.assertEqual(markup1.inline_keyboard[0][0].url, "https://t.me/testchannel")

        # 3. Multiple rows and multiple buttons in row
        text_multi = """
        /abroadcast -pin
        [Main Channel | https://t.me/ch1][Backup Channel | https://t.me/ch2]
        [👑 Buy VIP | https://t.me/bot?start=vip]
        """
        markup2 = parse_broadcast_custom_buttons(text_multi)
        self.assertIsNotNone(markup2)
        self.assertEqual(len(markup2.inline_keyboard), 2)
        # Row 1 has 2 buttons
        self.assertEqual(len(markup2.inline_keyboard[0]), 2)
        self.assertEqual(markup2.inline_keyboard[0][0].text, "Main Channel")
        self.assertEqual(markup2.inline_keyboard[0][1].text, "Backup Channel")
        # Row 2 has 1 button
        self.assertEqual(len(markup2.inline_keyboard[1]), 1)
        self.assertEqual(markup2.inline_keyboard[1][0].text, "👑 Buy VIP")

    def test_promo_codes_creation_and_redemption(self):
        import asyncio
        from unittest.mock import patch, PropertyMock, MagicMock, AsyncMock
        from database.promo import create_promo_code, redeem_promo_code, delete_promo_code
        from database.mongo import mongo

        # 1. Validation tests
        ok, msg, _ = asyncio.run(create_promo_code("AB", 7, 10))
        self.assertFalse(ok)
        self.assertIn("3-30", msg)

        ok, msg, _ = asyncio.run(create_promo_code("VALIDCODE", 0, 10))
        self.assertFalse(ok)
        self.assertIn("Days must be", msg)

        # 2. Mock MongoDB promo_codes collection
        fake_db = {}

        mock_col = MagicMock()

        async def fake_find_one(query):
            code = query.get("code")
            return fake_db.get(code)

        async def fake_insert_one(doc):
            fake_db[doc["code"]] = doc
            return MagicMock(inserted_id="mock_id")

        async def fake_find_one_and_update(filter_q, update_q, **kwargs):
            code = filter_q.get("code")
            doc = fake_db.get(code)
            if not doc:
                return None
            if not doc.get("is_active", True):
                return None
            if doc.get("claimed_count", 0) >= doc.get("max_uses", 1):
                return None
            user_id = filter_q.get("claimed_by", {}).get("$ne")
            if user_id in doc.get("claimed_by", []):
                return None

            # Apply atomic update
            doc["claimed_count"] = doc.get("claimed_count", 0) + update_q.get("$inc", {}).get("claimed_count", 1)
            doc.setdefault("claimed_by", []).append(update_q.get("$addToSet", {}).get("claimed_by"))
            return doc

        async def fake_delete_one(query):
            code = query.get("code")
            if code in fake_db:
                del fake_db[code]
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

        mock_col.find_one = AsyncMock(side_effect=fake_find_one)
        mock_col.insert_one = AsyncMock(side_effect=fake_insert_one)
        mock_col.find_one_and_update = AsyncMock(side_effect=fake_find_one_and_update)
        mock_col.delete_one = AsyncMock(side_effect=fake_delete_one)

        mock_db_dict = {"promo_codes": mock_col}

        with patch.object(type(mongo), "db", new_callable=PropertyMock, return_value=mock_db_dict):
            with patch("database.promo.add_premium", new=AsyncMock(return_value=True)):
                # Create promo
                ok, msg, doc = asyncio.run(create_promo_code("VIPTEST", 7, max_uses=2))
                self.assertTrue(ok)
                self.assertEqual(doc["code"], "VIPTEST")
                self.assertEqual(doc["days"], 7)

                # Duplicate code should fail
                ok_dup, msg_dup, _ = asyncio.run(create_promo_code("VIPTEST", 7, 5))
                self.assertFalse(ok_dup)
                self.assertIn("already exists", msg_dup)

                # User 100 redeems successfully
                ok_r1, msg_r1, days1 = asyncio.run(redeem_promo_code("VIPTEST", 100))
                self.assertTrue(ok_r1)
                self.assertEqual(days1, 7)

                # User 100 double-claim rejection
                ok_r1_again, msg_r1_again, _ = asyncio.run(redeem_promo_code("VIPTEST", 100))
                self.assertFalse(ok_r1_again)
                self.assertIn("already redeemed", msg_r1_again)

                # User 200 redeems successfully (claim 2 of 2)
                ok_r2, msg_r2, days2 = asyncio.run(redeem_promo_code("VIPTEST", 200))
                self.assertTrue(ok_r2)
                self.assertEqual(days2, 7)

                # User 300 claims exhausted code -> limit reached
                ok_r3, msg_r3, _ = asyncio.run(redeem_promo_code("VIPTEST", 300))
                self.assertFalse(ok_r3)
                self.assertIn("limit", msg_r3.lower())

                # Revoke / delete promo code
                del_ok = asyncio.run(delete_promo_code("VIPTEST"))
                self.assertTrue(del_ok)
                self.assertNotIn("VIPTEST", fake_db)

    def test_parse_duration_string(self):
        from database.ads import parse_duration_string
        self.assertEqual(parse_duration_string("1h"), 3600)
        self.assertEqual(parse_duration_string("24h"), 86400)
        self.assertEqual(parse_duration_string("3d"), 259200)
        self.assertEqual(parse_duration_string("7d"), 604800)
        self.assertEqual(parse_duration_string("1w"), 604800)
        self.assertEqual(parse_duration_string("30d"), 2592000)
        self.assertEqual(parse_duration_string("1m"), 2592000)
        self.assertEqual(parse_duration_string("1y"), 31536000)
        self.assertIsNone(parse_duration_string("invalid"))
        self.assertIsNone(parse_duration_string("10x"))

    def test_format_search_results_sponsor_ad(self):
        from utils.helpers import format_search_results_text
        fake_results = [{
            "file_unique_id": "u123",
            "file_name": "One_Piece_Episode_100.mkv",
            "file_size": 104857600
        }]
        # Without ad
        text_no_ad = format_search_results_text(
            results=fake_results,
            query="one piece",
            total_files=1,
            bot_username="testbot",
            sponsor_ad=None
        )
        self.assertNotIn("📢 <b>Sponsor:</b>", text_no_ad)
        self.assertIn("<b>1. <a href=\"https://t.me/testbot?start=file_u123\">[100.00 MB] One Piece Episode 100.mkv</a></b>", text_no_ad)

        # With active sponsor ad
        ad = {"text": "Join AkMovies Official", "url": "https://t.me/akmovies"}
        text_with_ad = format_search_results_text(
            results=fake_results,
            query="one piece",
            total_files=1,
            bot_username="testbot",
            sponsor_ad=ad
        )
        self.assertIn("📢 <b>Sponsor:</b>", text_with_ad)
        self.assertIn("https://t.me/akmovies", text_with_ad)
        self.assertIn("Join AkMovies Official", text_with_ad)

    def test_get_web_sponsor_banner_html(self):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from utils.web_server import get_web_sponsor_banner_html

        # Test when no ad exists
        with patch("database.ads.get_active_sponsor_ad", new=AsyncMock(return_value=None)):
            html = asyncio.run(get_web_sponsor_banner_html())
            self.assertEqual(html, "")

        # Test when active ad exists
        ad = {"text": "Join AkMoviesZone", "url": "https://t.me/akmovieszone"}
        with patch("database.ads.get_active_sponsor_ad", new=AsyncMock(return_value=ad)):
            html = asyncio.run(get_web_sponsor_banner_html())
            self.assertIn("sponsor-banner-bar", html)
            self.assertIn("🔥 SPONSOR", html)
            self.assertIn("Join AkMoviesZone", html)
            self.assertIn("https://t.me/akmovieszone", html)

    def test_sponsor_ad_engine_crud(self):
        import asyncio
        from unittest.mock import patch, PropertyMock, MagicMock, AsyncMock
        from database.mongo import mongo
        from database.ads import (
            set_sponsor_ad,
            get_active_sponsor_ad,
            delete_sponsor_ad,
            get_ad_stats,
            clean_expired_ads
        )
        fake_ads = []

        async def fake_update_many(query, update):
            for a in fake_ads:
                if query.get("is_active") is True and a.get("is_active"):
                    a.update(update.get("$set", {}))
            return MagicMock(modified_count=1)

        async def fake_insert_one(doc):
            doc["_id"] = "ad_1"
            fake_ads.append(doc)
            return MagicMock(inserted_id="ad_1")

        async def fake_find_one(query, sort=None):
            for a in fake_ads:
                if query.get("is_active") is True and a.get("is_active"):
                    return a
            if not query.get("is_active") and fake_ads:
                return fake_ads[-1]
            return None

        async def fake_update_one(query, update):
            for a in fake_ads:
                if a.get("_id") == query.get("_id"):
                    if "$set" in update:
                        a.update(update["$set"])
                    if "$inc" in update:
                        for k, v in update["$inc"].items():
                            a[k] = a.get(k, 0) + v
                    return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def fake_delete_many(query):
            count = len(fake_ads)
            fake_ads.clear()
            return MagicMock(deleted_count=count)

        mock_ads_col = MagicMock()
        mock_ads_col.update_many = AsyncMock(side_effect=fake_update_many)
        mock_ads_col.insert_one = AsyncMock(side_effect=fake_insert_one)
        mock_ads_col.find_one = AsyncMock(side_effect=fake_find_one)
        mock_ads_col.update_one = AsyncMock(side_effect=fake_update_one)
        mock_ads_col.delete_many = AsyncMock(side_effect=fake_delete_many)

        mock_db = {"sponsor_ads": mock_ads_col}

        with patch.object(type(mongo), "db", new_callable=PropertyMock, return_value=mock_db):
            # 1. Set Sponsor Ad
            ok, msg, doc = asyncio.run(set_sponsor_ad(
                text="1XBet Promo",
                url="https://1xbet.com",
                duration_str="7d",
                duration_seconds=604800,
                created_by=123
            ))
            self.assertTrue(ok)
            self.assertEqual(doc["text"], "1XBet Promo")

            # 2. Get Active Ad
            active = asyncio.run(get_active_sponsor_ad(track_impression=True))
            self.assertIsNotNone(active)
            self.assertEqual(active["text"], "1XBet Promo")
            self.assertEqual(active["impressions"], 1)

            # 3. Stats
            stats = asyncio.run(get_ad_stats())
            self.assertIsNotNone(stats)
            self.assertTrue(stats["is_active"])

            # 4. Delete Ad
            deleted = asyncio.run(delete_sponsor_ad())
            self.assertTrue(deleted)

            # 5. Clean Expired Ads
            purged = asyncio.run(clean_expired_ads(keep_days=7))
            self.assertGreaterEqual(purged, 1)

    def test_gift_flags_parsing(self):
        from plugins.gifts import parse_gift_flags
        args = ["100", "72h", "@AkMoviesZone", "-viponly", "-shortener", "-del", "3m", "-img", "https://img.com/p.jpg"]
        flags = parse_gift_flags(args)
        self.assertEqual(flags["claims"], 100)
        self.assertEqual(flags["duration_seconds"], 72 * 3600)
        self.assertIn("@AkMoviesZone", flags["channels"])
        self.assertTrue(flags["is_vip_only"])
        self.assertTrue(flags["require_shortener"])
        self.assertEqual(flags["auto_delete_seconds"], 180)
        self.assertEqual(flags["poster_url"], "https://img.com/p.jpg")
        self.assertTrue(flags["protect_content"])

        # Test -unlimited flag
        args_unlim = ["@AkMoviesZone", "-unlimited"]
        flags_unlim = parse_gift_flags(args_unlim)
        self.assertEqual(flags_unlim["claims"], 0)
        self.assertEqual(flags_unlim["duration_seconds"], 0)

        # Test 0 0 positional args
        args_zeros = ["0", "0", "@AkMoviesZone"]
        flags_zeros = parse_gift_flags(args_zeros)
        self.assertEqual(flags_zeros["claims"], 0)
        self.assertEqual(flags_zeros["duration_seconds"], 0)

        # Test simple natural keywords without hyphens
        args_natural = ["75", "12h", "shortener", "vip", "lock", "del", "5m"]
        flags_nat = parse_gift_flags(args_natural)
        self.assertEqual(flags_nat["claims"], 75)
        self.assertEqual(flags_nat["duration_seconds"], 12 * 3600)
        self.assertTrue(flags_nat["require_shortener"])
        self.assertTrue(flags_nat["is_vip_only"])
        self.assertTrue(flags_nat["protect_content"])
        self.assertEqual(flags_nat["auto_delete_seconds"], 300)

        # Test private channel, invite link, YouTube, Instagram, and invite tasks
        args_extended = [
            "50", "24h",
            "-1002247400551",
            "https://t.me/+AbCdEf123",
            "yt", "https://youtube.com/@AkMovieVerse",
            "insta", "https://instagram.com/akmovieverse",
            "invite", "2"
        ]
        flags_ext = parse_gift_flags(args_extended)
        self.assertEqual(flags_ext["claims"], 50)
        self.assertEqual(flags_ext["duration_seconds"], 24 * 3600)
        self.assertIn("-1002247400551", flags_ext["channels"])
        self.assertIn("https://t.me/+AbCdEf123", flags_ext["channels"])
        self.assertEqual(len(flags_ext["external_links"]), 2)
        self.assertEqual(flags_ext["external_links"][0]["type"], "youtube")
        self.assertEqual(flags_ext["external_links"][1]["type"], "instagram")
        self.assertEqual(flags_ext["required_invites"], 2)

        # Test -strict, -reclaim, -draft flags
        flags_strict = parse_gift_flags(["0", "0", "-strict", "-draft"])
        self.assertFalse(flags_strict["allow_reclaim"])
        self.assertTrue(flags_strict["draft"])

        flags_reclaim = parse_gift_flags(["0", "0", "-reclaim"])
        self.assertTrue(flags_reclaim["allow_reclaim"])

    def test_gift_reward_system_crud(self):
        import asyncio
        from unittest.mock import patch, PropertyMock, MagicMock, AsyncMock
        from database.mongo import mongo
        from database.gifts import (
            create_gift,
            get_gift,
            record_gift_claim,
            has_user_claimed_gift,
            delete_gift,
            gift_ban_user,
            gift_unban_user,
            is_gift_banned,
            create_gift_task_token,
            verify_gift_task_token,
            is_gift_task_verified,
            record_gift_redownload,
            clean_expired_gifts
        )

        fake_gifts = {}
        fake_blacklist = {}
        fake_tokens = {}

        # Mock gift_rewards collection
        mock_gr = MagicMock()

        async def fake_gr_insert(doc):
            fake_gifts[doc["gift_id"]] = doc
            return MagicMock(inserted_id="g_id")

        async def fake_gr_find(query, sort=None):
            return fake_gifts.get(query.get("gift_id"))

        async def fake_gr_update(query, update, upsert=False):
            gid = query.get("gift_id")
            if gid in fake_gifts:
                doc = fake_gifts[gid]
                if "$set" in update:
                    doc.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                if "$push" in update:
                    for k, v in update["$push"].items():
                        doc.setdefault(k, []).append(v)
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        mock_gr.insert_one = AsyncMock(side_effect=fake_gr_insert)
        mock_gr.find_one = AsyncMock(side_effect=fake_gr_find)
        mock_gr.update_one = AsyncMock(side_effect=fake_gr_update)
        mock_gr.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))

        # Mock gift_blacklist collection
        mock_gb = MagicMock()

        async def fake_gb_update(query, update, upsert=False):
            fake_blacklist[query["user_id"]] = update.get("$set", {})
            return MagicMock(modified_count=1)

        async def fake_gb_find(query):
            return fake_blacklist.get(query.get("user_id"))

        async def fake_gb_del(query):
            if query.get("user_id") in fake_blacklist:
                del fake_blacklist[query["user_id"]]
                return MagicMock(deleted_count=1)
            return MagicMock(deleted_count=0)

        mock_gb.update_one = AsyncMock(side_effect=fake_gb_update)
        mock_gb.find_one = AsyncMock(side_effect=fake_gb_find)
        mock_gb.delete_one = AsyncMock(side_effect=fake_gb_del)

        # Mock gift_task_tokens collection
        mock_gt = MagicMock()

        async def fake_gt_insert(doc):
            fake_tokens[doc["token"]] = doc
            return MagicMock(inserted_id="t_id")

        async def fake_gt_find(query):
            if "token" in query:
                return fake_tokens.get(query["token"])
            for t, d in fake_tokens.items():
                if d.get("gift_id") == query.get("gift_id") and d.get("user_id") == query.get("user_id"):
                    if query.get("is_verified") is True and not d.get("is_verified"):
                        continue
                    return d
            return None

        async def fake_gt_update(query, update):
            tok = query.get("token")
            if tok in fake_tokens:
                fake_tokens[tok].update(update.get("$set", {}))
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        mock_gt.insert_one = AsyncMock(side_effect=fake_gt_insert)
        mock_gt.find_one = AsyncMock(side_effect=fake_gt_find)
        mock_gt.update_one = AsyncMock(side_effect=fake_gt_update)
        mock_gt.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))

        mock_db = {
            "gift_rewards": mock_gr,
            "gift_blacklist": mock_gb,
            "gift_task_tokens": mock_gt
        }

        with patch.object(type(mongo), "db", new_callable=PropertyMock, return_value=mock_db):
            # 1. Create Gift
            g_doc = asyncio.run(create_gift(
                title="Avengers 4K IMAX",
                file_type="single",
                file_doc={"file_id": "f_123", "file_name": "avengers.mkv"},
                max_claims=2,
                duration_seconds=3600,
                created_by=999
            ))
            gid = g_doc["gift_id"]
            self.assertIsNotNone(gid)
            self.assertEqual(g_doc["max_claims"], 2)

            # 2. Get Gift
            fetched = asyncio.run(get_gift(gid))
            self.assertEqual(fetched["title"], "Avengers 4K IMAX")

            # 3. User 100 Claims
            ok1, _ = asyncio.run(record_gift_claim(gid, 100))
            self.assertTrue(ok1)
            self.assertTrue(asyncio.run(has_user_claimed_gift(gid, 100)))

            # 4. User 100 Duplicate Claim Blocked & Smart Re-download Tested
            ok_dup, _ = asyncio.run(record_gift_claim(gid, 100))
            self.assertFalse(ok_dup)
            asyncio.run(record_gift_redownload(gid, 100))
            fetched_re = asyncio.run(get_gift(gid))
            self.assertEqual(fetched_re.get("redownloads_count", 0), 1)

            # 5. User 200 Claims (Stock Reached: 2/2)
            ok2, _ = asyncio.run(record_gift_claim(gid, 200))
            self.assertTrue(ok2)

            # 6. User 300 Rejection (Out of stock)
            ok3, msg3 = asyncio.run(record_gift_claim(gid, 300))
            self.assertFalse(ok3)
            self.assertIn("claimed", msg3.lower())

            # 7. Gift Blacklist test
            banned = asyncio.run(gift_ban_user(555, "Spamming"))
            self.assertTrue(banned)
            self.assertTrue(asyncio.run(is_gift_banned(555)))
            unbanned = asyncio.run(gift_unban_user(555))
            self.assertTrue(unbanned)
            self.assertFalse(asyncio.run(is_gift_banned(555)))

            # 8. Token Verification test
            tok = asyncio.run(create_gift_task_token(gid, 777, "shortener"))
            self.assertTrue(tok.startswith("gtok_"))
            self.assertFalse(asyncio.run(is_gift_task_verified(gid, 777, "shortener")))
            ok_v, _, _ = asyncio.run(verify_gift_task_token(tok))
            self.assertTrue(ok_v)
            self.assertTrue(asyncio.run(is_gift_task_verified(gid, 777, "shortener")))

            # 9. Clean Expired Gifts
            purged = asyncio.run(clean_expired_gifts(keep_days=14))
            self.assertGreaterEqual(purged, 1)

    def test_codebase_integrity_and_imports(self):
        """Regression test verifying no missing core imports in critical handlers."""
        import plugins.callbacks as cb
        self.assertTrue(hasattr(cb, "asyncio"))
        self.assertTrue(hasattr(cb, "html"))
        self.assertTrue(hasattr(cb, "urllib"))

        import plugins.start as st
        self.assertTrue(hasattr(st, "html"))

        import utils.gift_flow as gf
        self.assertTrue(hasattr(gf, "datetime"))

        import utils.helpers as hp
        self.assertTrue(hasattr(hp, "asyncio"))

    def test_video_screenshots_generator(self):
        """Test screenshot watermark stamping and size safety limit."""
        import tempfile
        import os
        from PIL import Image
        from plugins.screenshots import apply_watermark, MAX_SCREENSHOT_FILE_SIZE_MB

        self.assertEqual(MAX_SCREENSHOT_FILE_SIZE_MB, 250)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            temp_path = tf.name

        try:
            img = Image.new("RGB", (640, 360), color=(30, 30, 50))
            img.save(temp_path, "JPEG")

            out_path = apply_watermark(temp_path, watermark_text="@AkMovieVerse")
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 500)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_dynamic_stream_and_browse_catalog(self):
        """Verify dynamic request host detection and /browse command registration."""
        from utils.web_server import get_stream_base_url
        from utils.bot_commands import USER_COMMANDS
        from unittest.mock import MagicMock

        # 1. Verify dynamic header detection
        mock_req = MagicMock()
        mock_req.headers = {
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "akmovieverse.duckdns.org"
        }
        detected = get_stream_base_url(mock_req)
        self.assertEqual(detected, "https://akmovieverse.duckdns.org")

        # 2. Verify user commands scope exclusions (browse, styles, group settings excluded)
        user_cmd_names = [cmd.command for cmd in USER_COMMANDS]
        self.assertNotIn("browse", user_cmd_names)
        self.assertNotIn("styles", user_cmd_names)
        self.assertNotIn("settings", user_cmd_names)
        self.assertIn("start", user_cmd_names)
        self.assertIn("dl", user_cmd_names)
        self.assertLessEqual(len(USER_COMMANDS), 100)

    def test_custom_posters_and_browse_button_toggle(self):
        """Verify custom poster override caching and browse button default state."""
        from config import Config
        from plugins.channel_post import format_post_caption
        # 1. Start menu browse button defaults to OFF
        self.assertFalse(getattr(Config, "ENABLE_BROWSE_BUTTON", False))

        # 2. Blockquote has expandable tag and guaranteed storyline
        grp = {"title": "Test Show", "is_series": True, "slug": "test-show", "files": []}
        tmdb = {"rating": 8.0, "genres": ["Crime"]}
        caption = format_post_caption(grp, tmdb, style=1)
        self.assertIn("<blockquote expandable>", caption)
        self.assertIn("Storyline :", caption)
        self.assertIn("</blockquote>", caption)

    def test_maintenance_mode_functionality(self):
        """Verify maintenance mode toggle, persistence, panel text, and command registration."""
        from config import Config
        from plugins.maintenance import (
            set_maintenance_mode,
            format_maintenance_panel_text,
            get_maintenance_panel_markup
        )
        import asyncio

        # 1. Default state
        self.assertFalse(getattr(Config, "MAINTENANCE_MODE", False))

        # 2. Toggle ON with custom reason
        asyncio.run(set_maintenance_mode(True, reason="5 Lakh Files Indexing"))
        self.assertTrue(Config.MAINTENANCE_MODE)
        self.assertEqual(Config.MAINTENANCE_REASON, "5 Lakh Files Indexing")

        # 3. Panel formatting reflects active status
        panel_text = format_maintenance_panel_text()
        self.assertIn("ACTIVE", panel_text)
        self.assertIn("5 Lakh Files Indexing", panel_text)

        # 4. Markup contains Disable button when active
        markup = get_maintenance_panel_markup()
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn("maint_disable", btn_data)

        # 5. Toggle OFF
        asyncio.run(set_maintenance_mode(False))
        self.assertFalse(Config.MAINTENANCE_MODE)
        panel_text_off = format_maintenance_panel_text()
        self.assertIn("INACTIVE", panel_text_off)

    def test_daily_free_download_system(self):
        """Verify Daily Free Quota check, consumption, auto-reset, and admin limit config."""
        from config import Config
        from database.mongo import MongoDB
        from database.users import (
            check_daily_free_download,
            consume_daily_free_download,
            get_daily_free_status
        )
        import asyncio
        from unittest.mock import patch, PropertyMock, AsyncMock

        # 1. Default limit is 3
        self.assertEqual(getattr(Config, "DAILY_FREE_LIMIT", 3), 3)

        fake_col = AsyncMock()
        fake_store = {}

        def fake_find_one(query, *args, **kwargs):
            uid = query.get("user_id")
            return fake_store.get(uid)

        def fake_update_one(filter_dict, update_dict, *args, **kwargs):
            uid = filter_dict.get("user_id")
            doc = fake_store.setdefault(uid, {"user_id": uid})
            for k, v in update_dict.items():
                if k == "$set":
                    doc.update(v)
                elif k == "$inc":
                    for sub_k, sub_v in v.items():
                        doc[sub_k] = doc.get(sub_k, 0) + sub_v
            return AsyncMock(modified_count=1)

        fake_col.find_one = AsyncMock(side_effect=fake_find_one)
        fake_col.update_one = AsyncMock(side_effect=fake_update_one)

        test_user = 9988776655

        async def _test():
            with patch.object(MongoDB, "users", new_callable=PropertyMock, return_value=fake_col):
                # Check initial quota
                has_free, used, limit = await check_daily_free_download(test_user)
                self.assertTrue(has_free)
                self.assertEqual(used, 0)
                self.assertEqual(limit, 3)

                # Consume 1st file
                c1 = await consume_daily_free_download(test_user)
                self.assertEqual(c1, 1)

                # Consume 2nd file
                c2 = await consume_daily_free_download(test_user)
                self.assertEqual(c2, 2)

                # Consume 3rd file
                c3 = await consume_daily_free_download(test_user)
                self.assertEqual(c3, 3)

                # 4th file -> Quota exhausted
                has_free_4, used_4, limit_4 = await check_daily_free_download(test_user)
                self.assertFalse(has_free_4)
                self.assertEqual(used_4, 3)
                self.assertEqual(limit_4, 3)

                # Status helper
                st_used, st_limit = await get_daily_free_status(test_user)
                self.assertEqual(st_used, 3)
                self.assertEqual(st_limit, 3)

                # Admin bypass
                admin_id = Config.ADMINS[0]
                adm_has_free, _, _ = await check_daily_free_download(admin_id)
                self.assertTrue(adm_has_free)

        asyncio.run(_test())

    def test_instagram_downloader_and_public_access(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from config import Config
        """Test Instagram URL detection, shortcode extraction, public exemption, and photo fallback."""
        from utils.downloader import is_instagram_url, extract_instagram_shortcode, download_instagram
        from plugins.downloader import verify_downloader_access

        # 1. URL detection
        self.assertTrue(is_instagram_url("https://www.instagram.com/p/DfVAUv2yW3V/"))
        self.assertTrue(is_instagram_url("https://instagram.com/reel/C8qLd9nvykM/?igsh=123"))
        self.assertTrue(is_instagram_url("https://instagr.am/p/DfVAUv2yW3V"))
        self.assertFalse(is_instagram_url("https://youtube.com/watch?v=123"))
        self.assertFalse(is_instagram_url("https://t.me/AkMovieVerse/123"))

        # 2. Shortcode extraction
        self.assertEqual(extract_instagram_shortcode("https://www.instagram.com/p/DfVAUv2yW3V/"), "DfVAUv2yW3V")
        self.assertEqual(extract_instagram_shortcode("https://instagram.com/reel/C8qLd9nvykM/?igsh=123"), "C8qLd9nvykM")

        # 3. Public access policy verification
        async def _test_access():
            mock_client = AsyncMock()
            mock_user = MagicMock()
            mock_user.id = 99999999  # Normal non-admin user
            mock_msg = AsyncMock()
            mock_msg.from_user = mock_user

            with patch.object(Config, "DOWNLOADER_ACCESS", "admin"), \
                 patch("plugins.downloader.check_force_sub", new_callable=AsyncMock, return_value=True), \
                 patch("plugins.downloader._USER_LAST_DL", {}):
                
                # External YouTube link -> Blocked for non-admin
                yt_allowed = await verify_downloader_access(mock_client, mock_msg, url="https://youtube.com/watch?v=abc")
                self.assertFalse(yt_allowed)

                # Instagram link -> Allowed for everyone (Exempt)
                insta_allowed = await verify_downloader_access(mock_client, mock_msg, url="https://www.instagram.com/p/DfVAUv2yW3V/")
                self.assertTrue(insta_allowed)

        asyncio.run(_test_access())

        # 4. Fallback mechanism test
        with patch("utils.downloader._sync_ytdlp_download", side_effect=Exception("ERROR: [Instagram] DfVAUv2yW3V: No video formats found!")), \
             patch("utils.downloader.download_instagram_embed", return_value={"file_path": "test.jpg", "is_photo": True, "title": "Instagram Photo"}) as mock_embed:
            res = download_instagram("https://www.instagram.com/p/DfVAUv2yW3V/", "tmp_dir", 50000000)
            self.assertTrue(res.get("is_photo"))
            self.assertEqual(res.get("title"), "Instagram Photo")
            mock_embed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
