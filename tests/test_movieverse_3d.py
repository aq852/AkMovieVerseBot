"""Unit tests for MovieVerse 3D search and file delivery mini app."""

import unittest
from unittest.mock import MagicMock
from utils.galaxy_movieverse import render_galaxy_movieverse
from utils.web_server import format_galaxy_item
from utils.helpers import build_filter_buttons


class TestMovieVerse3D(unittest.TestCase):
    def test_render_galaxy_movieverse_no_watch_links(self):
        items = [
            {
                "title": "Jailer 2 (2026)",
                "clean_name": "Jailer 2",
                "is_series": False,
                "poster_url": "https://example.com/poster.jpg",
                "year": 2026,
                "rating": "8.5",
                "total_size": "2.4 GB",
                "qualities": ["1080p", "720p"],
                "languages": ["Hindi", "Tamil"],
                "bot_url": "https://t.me/testbot?start=filter_Jailer+2",
                "quality_files": [
                    {"quality": "1080p", "size": "1.8 GB", "bot_url": "https://t.me/testbot?start=file_1080"},
                    {"quality": "720p", "size": "950 MB", "bot_url": "https://t.me/testbot?start=file_720"}
                ]
            }
        ]

        html = render_galaxy_movieverse(items, "https://akmovieverse.duckdns.org", "testbot", initial_query="Jailer")

        # Must contain MovieVerse 3D branding
        self.assertIn("MovieVerse 3D", html)
        self.assertIn("galaxySearchInput", html)
        self.assertIn("cinemaModal", html)

        # Must have initial query
        self.assertIn('value="Jailer"', html)

        # Must NOT contain old streaming buttons
        self.assertNotIn("WATCH / STREAM NOW", html)
        self.assertNotIn("sheetStreamBtn", html)

        # Must have bot file delivery actions
        self.assertIn("Get All Files / Episodes in Bot", html)
        self.assertIn("downloadQualityFile", html)

    def test_format_galaxy_item(self):
        raw_group = {
            "title": "Leo (2023)",
            "clean_name": "Leo",
            "is_series": False,
            "total_size": 3500000000,
            "sorted_qualities": ["1080p", "720p"],
            "languages_list": ["Tamil", "Hindi"],
            "files": [
                {
                    "file_name": "Leo.2023.1080p.HDRip.mkv",
                    "file_size": 2500000000,
                    "file_unique_id": "uid_1080"
                },
                {
                    "file_name": "Leo.2023.720p.HDRip.mkv",
                    "file_size": 1000000000,
                    "file_unique_id": "uid_720"
                }
            ]
        }

        formatted = format_galaxy_item(raw_group, "testbot", "https://img.com/leo.jpg")
        self.assertEqual(formatted["title"], "Leo (2023)")
        self.assertEqual(formatted["clean_name"], "Leo")
        self.assertEqual(formatted["poster_url"], "https://img.com/leo.jpg")
        self.assertIn("filter_Leo", formatted["bot_url"])

        # Check quality files
        self.assertEqual(len(formatted["quality_files"]), 2)
        q_names = [q["quality"].lower() for q in formatted["quality_files"]]
        self.assertIn("1080p", q_names)
        self.assertIn("720p", q_names)
        self.assertTrue(all("https://t.me/testbot?start=file_" in q["bot_url"] for q in formatted["quality_files"]))

    def test_build_filter_buttons_has_3d_explore_button(self):
        results = [{"file_name": "Test.Movie.2024.mkv", "file_unique_id": "t1"}]

        # Test PM buttons (should have web_app WebAppInfo)
        markup_pm = build_filter_buttons(
            results=results,
            page=1,
            total_pages=1,
            query="Jawan",
            bot_username="testbot",
            is_pm=True
        )

        top_btn_pm = markup_pm.inline_keyboard[0][0]
        self.assertIn("MovieVerse 3D", top_btn_pm.text)
        self.assertIsNotNone(top_btn_pm.web_app)
        self.assertIn("galaxy?q=Jawan", top_btn_pm.web_app.url)

        # Test Group buttons (should have deep-link to PM start)
        markup_group = build_filter_buttons(
            results=results,
            page=1,
            total_pages=1,
            query="Jawan",
            bot_username="testbot",
            is_pm=False
        )

        top_btn_group = markup_group.inline_keyboard[0][0]
        self.assertIn("MovieVerse 3D", top_btn_group.text)
        self.assertIn("start=galaxy_Jawan", top_btn_group.url)

    def test_channel_post_buttons_watch_toggle(self):
        from plugins.channel_post import build_post_buttons

        group = {
            "clean_name": "Jailer 2",
            "is_series": False,
            "primary_file_id": "file_123",
            "files": [{"file_name": "Jailer.2.mkv"}],
            "qualities": {"1080p"}
        }

        # 1. By default, Watch Online is NOT included (only Get File)
        markup_default = build_post_buttons(group, enable_watch=False)
        self.assertEqual(len(markup_default.inline_keyboard), 1)
        self.assertEqual(len(markup_default.inline_keyboard[0]), 1)
        self.assertEqual(markup_default.inline_keyboard[0][0].text, "🤖 Get File")

        # 2. When enable_watch=True, both Watch Online and Get File are present
        markup_watch = build_post_buttons(group, enable_watch=True)
        self.assertEqual(len(markup_watch.inline_keyboard[0]), 2)
        btn_texts = [btn.text for btn in markup_watch.inline_keyboard[0]]
        self.assertIn("▶️ Watch Online", btn_texts)
        self.assertIn("🤖 Get File", btn_texts)

        # 3. Custom button in row 2
        custom_btn = {"text": "📌 Join Backup", "url": "https://t.me/backup"}
        markup_custom = build_post_buttons(group, custom_btn=custom_btn, enable_watch=False)
        self.assertEqual(len(markup_custom.inline_keyboard), 2)
        self.assertEqual(markup_custom.inline_keyboard[1][0].text, "📌 Join Backup")


if __name__ == "__main__":
    unittest.main()
