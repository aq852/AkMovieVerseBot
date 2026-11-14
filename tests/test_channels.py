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

    async def test_settings_resilience_and_memory_cache(self):
        from database.mongo import get_bot_setting, set_bot_setting, _SETTINGS_CACHE
        # Setting a key updates memory cache even if DB fails
        await set_bot_setting("custom_test_key", "active_val")
        self.assertEqual(_SETTINGS_CACHE.get("custom_test_key"), "active_val")
        val = await get_bot_setting("custom_test_key")
        self.assertEqual(val, "active_val")

    def test_smart_protected_channel_link_encoding_and_decoding(self):
        import base64
        channel_id = -1002331917822
        # Encode
        raw_bytes = str(channel_id).encode("utf-8")
        b64_code = base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")
        self.assertEqual(b64_code, "LTEwMDIzMzE5MTc4MjI")

        # Decode (with padding restoration as done in start.py)
        raw_b64 = b64_code
        padding = len(raw_b64) % 4
        if padding:
            raw_b64 += "=" * (4 - padding)
        decoded_cid = int(base64.urlsafe_b64decode(raw_b64.encode("utf-8")).decode("utf-8"))
        self.assertEqual(decoded_cid, channel_id)

    async def test_sharelink_command_execution(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from plugins.auto_approve import create_share_link_command

        # Test 1: Empty args in PM sends usage message
        mock_msg_empty = MagicMock()
        mock_msg_empty.from_user.id = 12345
        mock_msg_empty.text = "/sharelink"
        mock_msg_empty.chat.type.name = "PRIVATE"
        mock_msg_empty.chat.type.value = "private"
        mock_msg_empty.reply_text = AsyncMock()

        mock_client = MagicMock()
        mock_client.me.username = "TheFlixifyBot"

        with patch("config.Config.is_admin", return_value=True):
            await create_share_link_command(mock_client, mock_msg_empty)
            self.assertTrue(mock_msg_empty.reply_text.called)
            sent_text = mock_msg_empty.reply_text.call_args[0][0]
            self.assertIn("Smart Protected Channel Link Generator", sent_text)

        # Test 2: Passing channel ID generates smart link without NameError
        mock_msg_cid = MagicMock()
        mock_msg_cid.from_user.id = 12345
        mock_msg_cid.text = "/sharelink -1003843941702"
        mock_msg_cid.chat.type.name = "PRIVATE"
        mock_msg_cid.chat.type.value = "private"
        mock_msg_cid.reply_text = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -1003843941702
        mock_chat.title = "Test Vault Channel"
        mock_client.get_chat = AsyncMock(return_value=mock_chat)
        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+AbCdEfGh"
        mock_client.create_chat_invite_link = AsyncMock(return_value=mock_invite)

        with patch("config.Config.is_admin", return_value=True), \
             patch("plugins.auto_approve.add_auto_approve_channel", new=AsyncMock()):
            await create_share_link_command(mock_client, mock_msg_cid)
            self.assertTrue(mock_msg_cid.reply_text.called)
            sent_text_2 = mock_msg_cid.reply_text.call_args[0][0]
            self.assertIn("SMART PROTECTED CHANNEL LINK GENERATED", sent_text_2)
            self.assertIn("https://t.me/TheFlixifyBot?start=req_", sent_text_2)
            self.assertIn("https://t.me/+AbCdEfGh", sent_text_2)

    async def test_gatekeeper_start_command_execution(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from plugins.start import start_command_handler

        mock_client = MagicMock()
        mock_client.me.username = "TheFlixifyBot"

        mock_msg = MagicMock()
        mock_msg.from_user.id = 99999
        mock_msg.from_user.first_name = "Alex"
        mock_msg.from_user.username = "alex"
        mock_msg.text = "/start req_LTEwMDM4NDM5NDE3MDI"
        mock_msg.command = ["start", "req_LTEwMDM4NDM5NDE3MDI"]
        mock_msg.chat.type.name = "PRIVATE"
        mock_msg.chat.type.value = "private"
        mock_msg.reply_text = AsyncMock()
        mock_msg.reply_photo = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -1003843941702
        mock_chat.title = "Xclusive Vault"
        mock_chat.username = None
        mock_client.get_chat = AsyncMock(return_value=mock_chat)

        mock_invite = MagicMock()
        mock_invite.invite_link = "https://t.me/+TestGatekeeperLink"
        mock_client.create_chat_invite_link = AsyncMock(return_value=mock_invite)
        mock_client.get_chat_member = AsyncMock(side_effect=Exception("UserNotParticipant"))

        with patch("database.users.add_user", new=AsyncMock()), \
             patch("database.users.is_banned", new=AsyncMock(return_value=False)), \
             patch("utils.fsub.check_fsub", new=AsyncMock(return_value=True)):
            await start_command_handler(mock_client, mock_msg)
            # Must reply with either photo or text containing the invite link
            sent_url = None
            if mock_msg.reply_photo.called:
                markup = mock_msg.reply_photo.call_args[1].get("reply_markup")
                sent_url = markup.inline_keyboard[0][0].url
            elif mock_msg.reply_text.called:
                markup = mock_msg.reply_text.call_args[1].get("reply_markup")
                if markup:
                    sent_url = markup.inline_keyboard[0][0].url

            self.assertEqual(sent_url, "https://t.me/+TestGatekeeperLink")


if __name__ == "__main__":
    unittest.main()
