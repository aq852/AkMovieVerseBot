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
        self.assertGreaterEqual(len(CATEGORY_KEYS), 8)
        # Telegram 4096 character safety limit
        self.assertLess(len(CHEAT_SHEET_TEXT), 4096)
        for cat in CATEGORY_KEYS:
            self.assertIn(cat, CATEGORY_CONTENT)
            self.assertLess(len(CATEGORY_CONTENT[cat]), 4096)
            mk = get_category_markup(cat)
            self.assertIsNotNone(mk)

        hub = get_admin_hub_markup()
        self.assertIsNotNone(hub)

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
        self.assertIn("🎬 <b>Title :</b> Dexter (2006)", cap)
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
        self.assertIn("search_Dexter", buttons.inline_keyboard[0][1].url)

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

if __name__ == "__main__":
    unittest.main()
