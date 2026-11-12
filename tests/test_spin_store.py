import unittest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock

from database.loyalty import (
    calculate_rank,
    get_ist_now,
    get_ist_date_str,
    get_seconds_until_midnight_ist,
    add_coins,
    deduct_coins,
    use_direct_pass,
    can_spin_today,
    credit_referral_spin,
    consume_spin
)
from database.store import (
    get_all_store_items,
    get_store_item_by_id,
    add_or_update_store_item,
    delete_store_item,
    purchase_store_item
)
from database.channel_access import (
    grant_temporary_channel_access,
    check_and_evict_expired_channel_members
)


class TestLoyaltyRankAndCalculations(unittest.TestCase):
    def test_rank_progression(self):
        self.assertEqual(calculate_rank(0), "🌟 Newbie Watcher")
        self.assertEqual(calculate_rank(1), "🌟 Newbie Watcher")
        self.assertEqual(calculate_rank(6), "🌟 Newbie Watcher")
        self.assertEqual(calculate_rank(7), "🥈 Silver Cinephile")
        self.assertEqual(calculate_rank(14), "🥈 Silver Cinephile")
        self.assertEqual(calculate_rank(15), "🥇 Gold Cinema Master")
        self.assertEqual(calculate_rank(29), "🥇 Gold Cinema Master")
        self.assertEqual(calculate_rank(30), "💎 Diamond Elite")
        self.assertEqual(calculate_rank(59), "💎 Diamond Elite")
        self.assertEqual(calculate_rank(60), "👑 Flixify Immortal")
        self.assertEqual(calculate_rank(100), "👑 Flixify Immortal")

    def test_ist_timing(self):
        ist_now = get_ist_now()
        date_str = get_ist_date_str(ist_now)
        self.assertTrue(len(date_str) == 10)
        self.assertIn("-", date_str)
        secs = get_seconds_until_midnight_ist()
        self.assertGreater(secs, 0)
        self.assertLessEqual(secs, 86400)


class TestLoyaltyWalletAndSpins(unittest.IsolatedAsyncioTestCase):
    @patch("database.loyalty.mongo")
    async def test_add_and_deduct_coins(self, mock_mongo):
        mock_col = MagicMock()
        mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_col.insert_one = AsyncMock()
        mock_mongo.db = {"loyalty_users": mock_col}

        # Test add_coins
        mock_col.find_one_and_update = AsyncMock(return_value={"coins": 150})
        new_bal = await add_coins(12345, 50, "test")
        self.assertEqual(new_bal, 150)

        # Test deduct_coins success
        mock_col.find_one_and_update = AsyncMock(return_value={"coins": 100})
        ok, rem = await deduct_coins(12345, 50, "test_spend")
        self.assertTrue(ok)
        self.assertEqual(rem, 100)

        # Test deduct_coins failure (insufficient balance)
        mock_col.find_one_and_update = AsyncMock(return_value=None)
        mock_col.find_one = AsyncMock(return_value={"coins": 30, "_id": "uid", "last_ref_spin_date": get_ist_date_str()})
        ok, rem = await deduct_coins(12345, 50, "test_fail")
        self.assertFalse(ok)
        self.assertEqual(rem, 30)

    @patch("database.loyalty.mongo")
    async def test_use_direct_pass(self, mock_mongo):
        mock_col = MagicMock()
        mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_col.insert_one = AsyncMock()
        mock_mongo.db = {"loyalty_users": mock_col}

        # Success case: had passes
        mock_col.find_one_and_update = AsyncMock(return_value={"bonus_direct_passes": 2})
        used, rem = await use_direct_pass(12345)
        self.assertTrue(used)
        self.assertEqual(rem, 2)

        # Failure case: 0 passes left
        mock_col.find_one_and_update = AsyncMock(return_value=None)
        mock_col.find_one = AsyncMock(return_value={"bonus_direct_passes": 0, "_id": "uid", "last_ref_spin_date": get_ist_date_str()})
        used, rem = await use_direct_pass(12345)
        self.assertFalse(used)
        self.assertEqual(rem, 0)


class TestStoreAndFulfillment(unittest.IsolatedAsyncioTestCase):
    @patch("database.store.mongo")
    async def test_store_catalog_crud(self, mock_mongo):
        mock_col = MagicMock()
        mock_mongo.db = {"store_items": mock_col}

        mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        ok = await add_or_update_store_item(
            item_id="test_pass",
            title="⚡ Test Pass",
            price_coins=50,
            item_type="pass",
            item_value=1
        )
        self.assertTrue(ok)

        mock_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        del_ok = await delete_store_item("test_pass")
        self.assertTrue(del_ok)

    @patch("database.store.add_premium_user", new_callable=AsyncMock)
    @patch("database.store.deduct_coins", new_callable=AsyncMock)
    @patch("database.store.get_store_item_by_id", new_callable=AsyncMock)
    @patch("database.store.mongo")
    async def test_purchase_vip_item(self, mock_mongo, mock_get_item, mock_deduct, mock_add_premium):
        mock_client = MagicMock()
        mock_get_item.return_value = {
            "item_id": "vip_1d",
            "title": "👑 1-Day Full VIP Pass",
            "price_coins": 150,
            "item_type": "vip",
            "item_value": 1,
            "is_active": True
        }
        mock_deduct.return_value = (True, 50)
        mock_add_premium.return_value = True

        ok, msg, payload = await purchase_store_item(mock_client, 12345, "vip_1d")
        self.assertTrue(ok)
        self.assertIn("VIP ACTIVATED", msg)
        self.assertEqual(payload.get("vip_days_added"), 1)

    @patch("database.channel_access.mongo")
    async def test_temporary_channel_access_generation(self, mock_mongo):
        mock_col = MagicMock()
        mock_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="xyz"))
        mock_mongo.db = {"channel_access_ledger": mock_col}

        mock_client = MagicMock()
        invite_mock = MagicMock()
        invite_mock.invite_link = "https://t.me/+joinPrivateTestLink"
        mock_client.create_chat_invite_link = AsyncMock(return_value=invite_mock)

        ok, link, exp = await grant_temporary_channel_access(
            client=mock_client,
            user_id=12345,
            chat_id=-1001234567890,
            duration_hours=24,
            channel_name="Private VIP Channel"
        )
        self.assertTrue(ok)
        self.assertEqual(link, "https://t.me/+joinPrivateTestLink")

    @patch("database.channel_access.mongo")
    async def test_expired_channel_member_eviction(self, mock_mongo):
        mock_col = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{
            "_id": "doc123",
            "user_id": 999,
            "chat_id": -1001234567890,
            "channel_name": "VIP Channel",
            "expires_at": time.time() - 100,
            "status": "active"
        }])
        mock_col.find = MagicMock(return_value=mock_cursor)
        mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_mongo.db = {"channel_access_ledger": mock_col}

        mock_client = MagicMock()
        mock_client.ban_chat_member = AsyncMock(return_value=True)
        mock_client.unban_chat_member = AsyncMock(return_value=True)
        mock_client.send_message = AsyncMock(return_value=True)

        evicted = await check_and_evict_expired_channel_members(mock_client)
        self.assertEqual(evicted, 1)
        mock_client.ban_chat_member.assert_awaited_once_with(chat_id=-1001234567890, user_id=999)
        mock_client.unban_chat_member.assert_awaited_once_with(chat_id=-1001234567890, user_id=999)


class TestMediaMetadataAndCatalogGrouping(unittest.TestCase):
    def test_movie_parts_and_sequel_parsing(self):
        from utils.helpers import parse_media_metadata
        # Movie sequel numbers like "Jailer 2" must never be parsed as series or episode 2
        m_j2 = parse_media_metadata("Jailer 2 1080p.mkv")
        self.assertFalse(m_j2["is_series"])
        self.assertEqual(m_j2["clean_name"], "Jailer 2")

        # Multi-part movie files must be parsed as parts and NOT series
        m_part1 = parse_media_metadata("Jailer 2 Part 1 1080p.mkv")
        self.assertTrue(m_part1["is_part"])
        self.assertFalse(m_part1["is_series"])
        self.assertEqual(m_part1["part"], 1)
        self.assertEqual(m_part1["clean_name"], "Jailer 2")

        m_part2 = parse_media_metadata("Jailer 2 Part 2 1080p.mkv")
        self.assertTrue(m_part2["is_part"])
        self.assertFalse(m_part2["is_series"])
        self.assertEqual(m_part2["part"], 2)

        m_sf = parse_media_metadata("Street Fighter Part 1.mp4")
        self.assertTrue(m_sf["is_part"])
        self.assertFalse(m_sf["is_series"])
        self.assertEqual(m_sf["clean_name"], "Street Fighter")

        # True TV series must still be parsed correctly
        m_ser = parse_media_metadata("VisionQuest S01E01 720p.mkv")
        self.assertTrue(m_ser["is_series"])
        self.assertEqual(m_ser["season"], 1)
        self.assertEqual(m_ser["episode"], 1)

    def test_catalog_merging_parts_and_qualities(self):
        from utils.web_server import _group_file_docs
        docs = [
            {"_id": "1", "file_name": "Jailer 2 (2026) 1080p.mkv", "file_size": 3000000000},
            {"_id": "2", "file_name": "Jailer 2 (2026) 720p.mkv", "file_size": 1500000000},
            {"_id": "3", "file_name": "Jailer 2 1080p.mkv", "file_size": 3000000000},
            {"_id": "4", "file_name": "Jailer 2 720p.mkv", "file_size": 1500000000},
            {"_id": "5", "file_name": "Jailer 2 Part 1 1080p.mkv", "file_size": 2000000000},
            {"_id": "6", "file_name": "Jailer 2 Part 2 1080p.mkv", "file_size": 2000000000},
            {"_id": "7", "file_name": "Street Fighter Part 1.mp4", "file_size": 1500000000},
            {"_id": "8", "file_name": "Street Fighter Part 2.mp4", "file_size": 1500000000},
            {"_id": "9", "file_name": "VisionQuest S01E01 720p.mkv", "file_size": 800000000},
            {"_id": "10", "file_name": "VisionQuest S01E02 720p.mkv", "file_size": 800000000},
        ]
        groups = _group_file_docs(docs)

        # There should only be 1 Jailer 2 group with all 6 files, NOT split into series!
        j2_groups = [g for g in groups if "jailer" in g["clean_name"].lower()]
        self.assertEqual(len(j2_groups), 1)
        j2 = j2_groups[0]
        self.assertFalse(j2["is_series"])
        self.assertTrue(j2["has_parts"])
        self.assertEqual(len(j2["files"]), 6)
        self.assertIn("1080P", j2["sorted_qualities"])
        self.assertIn("720P", j2["sorted_qualities"])

        # Street Fighter should be 1 movie group with 2 parts
        sf_groups = [g for g in groups if "street" in g["clean_name"].lower()]
        self.assertEqual(len(sf_groups), 1)
        self.assertFalse(sf_groups[0]["is_series"])
        self.assertTrue(sf_groups[0]["has_parts"])
        self.assertEqual(len(sf_groups[0]["files"]), 2)

        # VisionQuest must be a series
        vq_groups = [g for g in groups if "visionquest" in g["clean_name"].lower()]
        self.assertEqual(len(vq_groups), 1)
        self.assertTrue(vq_groups[0]["is_series"])

    def test_spin_token_generation_and_verification(self):
        """Test secure HMAC token generation and tamper verification for WebApp wheel."""
        from plugins.spin import generate_spin_token, verify_spin_token

        user_id = 99887766
        token = generate_spin_token(user_id)
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 16)

        # Valid token must verify
        self.assertTrue(verify_spin_token(user_id, token))

        # Tampered user_id or token must fail
        self.assertFalse(verify_spin_token(user_id + 1, token))
        self.assertFalse(verify_spin_token(user_id, token + "x"))
        self.assertFalse(verify_spin_token(user_id, "invalid_token"))

    def test_render_spin_webapp(self):
        """Test rendering of HTML5 Mini App with user stats and state."""
        from utils.spin_webapp import render_spin_webapp

        profile = {
            "coins": 45,
            "current_streak": 7,
            "lifetime_rank": "🥈 Silver Cinephile"
        }
        html = render_spin_webapp(
            user_id=123456,
            token="testtoken123",
            user_name="Amit",
            profile=profile,
            allowed=True,
            cooldown_secs=0
        )
        self.assertIn("123456", html)
        self.assertIn("testtoken123", html)
        self.assertIn("Amit", html)
        self.assertIn("45", html)
        self.assertIn("Silver Cinephile", html)
        self.assertIn("TAP TO SPIN", html)
        self.assertNotIn("__USER_ID__", html)
        self.assertNotIn("__TOKEN__", html)

    def test_execute_spin_roll_integration(self):
        """Test server-side execute_spin_roll reward granting and segment mapping."""
        from plugins.spin import execute_spin_roll
        from unittest.mock import patch, MagicMock

        mock_profile = {
            "user_id": 112233,
            "coins": 10,
            "current_streak": 3,
            "longest_streak": 3,
            "lifetime_rank": "🌟 Newbie"
        }

        with patch("plugins.spin.can_spin_today", AsyncMock(return_value=(True, "free", 0, 0))), \
             patch("plugins.spin.consume_spin", AsyncMock(return_value=True)), \
             patch("plugins.spin.get_loyalty_profile", AsyncMock(return_value=mock_profile)), \
             patch("plugins.spin.add_coins", AsyncMock(return_value=15)):

            success, msg, details = asyncio.run(execute_spin_roll(None, 112233, "Tester"))
            self.assertTrue(success)
            self.assertIn(details["target_segment"], [0, 2, 4, 5, 7])  # Coins segments
            self.assertEqual(details["prize_type"], "coins")
            self.assertGreater(details["new_balance"], 0)


if __name__ == "__main__":
    unittest.main()
