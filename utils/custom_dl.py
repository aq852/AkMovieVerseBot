"""
High-Performance MTProto Video Chunk Streaming Engine with In-Memory LRU Cache,
Mathematical Chunk Alignment (RFC 7233), and Active Concurrency Limiting.
Adopted from AkMovieVerse, TeleStream, and NoxMedia streaming architectures.
"""

import asyncio
import logging
import math
from collections import OrderedDict
from typing import AsyncGenerator, Optional, Dict, Tuple, Any

try:
    from hydrogram import Client, raw, utils
    from hydrogram.session import Session, Auth
    from hydrogram.file_id import FileId, FileType, ThumbnailSource
    from hydrogram.errors import AuthBytesInvalid
except ImportError:
    from pyrogram import Client, raw, utils
    from pyrogram.session import Session, Auth
    from pyrogram.file_id import FileId, FileType, ThumbnailSource
    from pyrogram.errors import AuthBytesInvalid

from config import Config
from utils.ranges import ByteRange, ChunkPlan, plan_chunks

logger = logging.getLogger("autofilter.stream")


class ServerBusyError(Exception):
    """Raised when server streaming capacity is at maximum concurrency."""
    pass


class StreamConcurrencyGuard:
    """Limits the number of simultaneous active streams to prevent bandwidth exhaustion."""

    def __init__(self, max_concurrency: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_concurrency = max_concurrency
        self.active_count = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        try:
            # Wait up to 3 seconds for a free stream slot
            await asyncio.wait_for(self.semaphore.acquire(), timeout=3.0)
            async with self._lock:
                self.active_count += 1
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self):
        async with self._lock:
            self.active_count = max(0, self.active_count - 1)
        self.semaphore.release()


# 48 chunks x 512KB = ~24MB In-Memory LRU Cache
# Caches header metadata (MOOV atom), audio codecs, and recent seeks
class ChunkCache:
    def __init__(self, max_entries: int = 48):
        self.max_entries = max_entries
        self.cache: OrderedDict[Tuple[int, int, int], bytes] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: Tuple[int, int, int]) -> Optional[bytes]:
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    async def put(self, key: Tuple[int, int, int], value: bytes):
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                self.cache[key] = value
                return
            self.cache[key] = value
            if len(self.cache) > self.max_entries:
                self.cache.popitem(last=False)


# Global singletons
concurrency_guard = StreamConcurrencyGuard(max_concurrency=Config.MAX_CONCURRENT_STREAMS)
chunk_lru_cache = ChunkCache(max_entries=48)
_media_session_lock = asyncio.Lock()
_resolved_messages: Dict[str, Any] = {}


class TGCustomStreamer:
    """Manages raw MTProto chunk streaming with multi-DC support and caching."""

    @staticmethod
    async def get_media_session(client: Client, dc_id: int) -> Session:
        """Initialize or retrieve authenticated media session for target datacenter."""
        if not hasattr(client, "media_sessions"):
            client.media_sessions = {}

        session = client.media_sessions.get(dc_id)
        if session and getattr(session, "is_started", None) and session.is_started.is_set():
            return session

        async with _media_session_lock:
            session = client.media_sessions.get(dc_id)
            if session and getattr(session, "is_started", None) and session.is_started.is_set():
                return session

            test_mode = await client.storage.test_mode()
            current_dc = await client.storage.dc_id()

            if dc_id != current_dc:
                auth_key = await Auth(client, dc_id, test_mode).create()
                session = Session(client, dc_id, auth_key, test_mode, is_media=True)
                await session.start()

                for _ in range(3):
                    exported = await client.invoke(
                        raw.functions.auth.ExportAuthorization(dc_id=dc_id)
                    )
                    try:
                        await session.invoke(
                            raw.functions.auth.ImportAuthorization(
                                id=exported.id,
                                bytes=exported.bytes
                            )
                        )
                        break
                    except AuthBytesInvalid:
                        continue
                else:
                    await session.stop()
                    raise AuthBytesInvalid(f"Failed to export authorization to DC {dc_id}")
            else:
                auth_key = await client.storage.auth_key()
                session = Session(client, dc_id, auth_key, test_mode, is_media=True)
                await session.start()

            client.media_sessions[dc_id] = session
            return session

    @classmethod
    async def resolve_media_location(cls, client: Client, file_doc: dict) -> Tuple[Any, int, int]:
        """
        Resolve MTProto InputFileLocation, document ID, and DC ID for a database file.
        Returns (location, doc_id, dc_id).
        """
        file_id_str = file_doc.get("file_id")
        file_unique_id = file_doc.get("file_unique_id", "")
        channel_id = file_doc.get("channel_id")
        message_id = file_doc.get("message_id")

        # 1. Try to fetch message from channel to ensure fresh file_reference
        media_obj = None
        if channel_id and message_id:
            try:
                target_chat = int(channel_id) if str(channel_id).lstrip("-").isdigit() else str(channel_id)
                msg = await client.get_messages(target_chat, message_ids=int(message_id))
                if msg and (msg.video or msg.document or msg.audio):
                    media_obj = msg.video or msg.document or msg.audio
            except Exception as e:
                logger.debug(f"Direct channel message lookup notice for {file_unique_id}: {e}")

        # 2. If direct lookup failed, fallback to file_id decoding
        if media_obj:
            file_id_obj = FileId.decode(media_obj.file_id)
        elif file_id_str:
            file_id_obj = FileId.decode(file_id_str)
        else:
            raise ValueError(f"No valid file_id or media found for file {file_unique_id}")

        doc_id = file_id_obj.media_id
        dc_id = file_id_obj.dc_id

        if file_id_obj.file_type in (FileType.VIDEO, FileType.DOCUMENT, FileType.AUDIO):
            location = raw.types.InputDocumentFileLocation(
                id=file_id_obj.media_id,
                access_hash=file_id_obj.access_hash,
                file_reference=file_id_obj.file_reference,
                thumb_size=file_id_obj.thumbnail_size or ""
            )
        elif file_id_obj.file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id_obj.media_id,
                access_hash=file_id_obj.access_hash,
                file_reference=file_id_obj.file_reference,
                thumb_size=file_id_obj.thumbnail_size or ""
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id_obj.media_id,
                access_hash=file_id_obj.access_hash,
                file_reference=file_id_obj.file_reference,
                thumb_size=""
            )

        return location, doc_id, dc_id

    @classmethod
    async def yield_file_range(
        cls,
        client: Client,
        file_doc: dict,
        byte_range: ByteRange,
        chunk_size: int = 512 * 1024
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream a byte range from Telegram MTProto with mathematical chunk alignment,
        in-memory LRU caching, and active concurrency limiting.
        """
        # Concurrency safety check
        acquired = await concurrency_guard.acquire()
        if not acquired:
            logger.warning("Stream rejected: Maximum server streaming concurrency reached.")
            raise ServerBusyError("Server streaming capacity is currently full.")

        try:
            location, doc_id, dc_id = await cls.resolve_media_location(client, file_doc)
            session = await cls.get_media_session(client, dc_id)

            plan: ChunkPlan = plan_chunks(byte_range, chunk_size)
            curr_offset = plan.offset
            part_count = plan.count
            current_part = 1

            while current_part <= part_count:
                cache_key = (doc_id, curr_offset, chunk_size)

                # Check LRU cache first
                chunk_data = await chunk_lru_cache.get(cache_key)

                if chunk_data is None:
                    # Fetch chunk from Telegram MTProto
                    try:
                        res = await session.invoke(
                            raw.functions.upload.GetFile(
                                location=location,
                                offset=curr_offset,
                                limit=chunk_size
                            ),
                            sleep_threshold=30
                        )
                        if isinstance(res, raw.types.upload.File):
                            chunk_data = res.bytes
                            if chunk_data:
                                await chunk_lru_cache.put(cache_key, chunk_data)
                        else:
                            chunk_data = b""
                    except Exception as e:
                        logger.error(f"MTProto GetFile error at offset {curr_offset}: {e}")
                        break

                if not chunk_data:
                    break

                # Precise RFC 7233 slice cutting
                if part_count == 1:
                    yield chunk_data[plan.first_cut:plan.last_cut]
                    break
                elif current_part == 1:
                    yield chunk_data[plan.first_cut:]
                elif current_part == part_count:
                    yield chunk_data[:plan.last_cut]
                else:
                    yield chunk_data

                curr_offset += chunk_size
                current_part += 1

        finally:
            await concurrency_guard.release()
