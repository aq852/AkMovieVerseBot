import unittest
import asyncio
from unittest.mock import patch, MagicMock
from database.channels import (
    get_storage_channels,
    add_storage_channel,
    remove_storage_channel,
    is_storage_channel,
    _STORAGE_CHANNELS_CACHE
)
from config import Config


class TestStorageChannels(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Config.CHANNELS = [-1002001671856]

    @patch("database.channels.set_bot_setting")
    @patch("database.channels.get_bot_setting")
    async def test_get_and_add_storage_channel(self, mock_get_setting, mock_set_setting):
        mock_get_setting.return_value = []
        mock_set_setting.return_value = True

        channels = await get_storage_channels(force_refresh=True)
        self.assertIn(-1002001671856, channels)

        # Add DB 2 (-1002370960281)
        ok = await add_storage_channel(-1002370960281)
        self.assertTrue(ok)
        self.assertTrue(await is_storage_channel(-1002370960281))
        self.assertTrue(await is_storage_channel(-1002001671856))

        # Check in Config.CHANNELS
        self.assertIn(-1002370960281, Config.CHANNELS)

    @patch("database.channels.set_bot_setting")
    @patch("database.channels.get_bot_setting")
    async def test_remove_storage_channel(self, mock_get_setting, mock_set_setting):
        mock_get_setting.return_value = [-1002370960281]
        mock_set_setting.return_value = True

        ok = await remove_storage_channel(-1002370960281)
        self.assertTrue(ok)
        self.assertFalse(await is_storage_channel(-1002370960281))


if __name__ == "__main__":
    unittest.main()
