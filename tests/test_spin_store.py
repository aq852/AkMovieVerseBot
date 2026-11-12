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


if __name__ == "__main__":
    unittest.main()
