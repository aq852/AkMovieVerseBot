"""
RFC 7233 single byte-range parsing and Telegram MTProto chunk planning.
Adopted from AkMovieVerse / TeleStream high-precision streaming engine.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple


class RangeNotSatisfiable(ValueError):
    """Raised when an HTTP Range header cannot be satisfied by the file size."""
    pass


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class ChunkPlan:
    offset: int
    first_cut: int
    last_cut: int
    count: int


def parse_range(value: Optional[str], file_size: int) -> Tuple[ByteRange, bool]:
    """
    Parse an RFC 7233 Range header into an inclusive (start, end) ByteRange.
    Returns (ByteRange, is_partial).
    """
    if file_size <= 0:
        raise RangeNotSatisfiable("Empty file")

    if not value or not value.strip():
        return ByteRange(0, file_size - 1, file_size), False

    clean_val = value.strip()
    if not clean_val.startswith("bytes=") or "," in clean_val:
        raise RangeNotSatisfiable("Only single byte ranges are supported")

    spec = clean_val[6:].strip()
    try:
        start_text, end_text = spec.split("-", 1)
        if not start_text:
            # Suffix range: bytes=-500 (last 500 bytes)
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError
            start = max(0, file_size - suffix)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
            if start < 0 or start >= file_size or end < start:
                raise ValueError
            end = min(end, file_size - 1)
    except (TypeError, ValueError) as exc:
        raise RangeNotSatisfiable("Invalid byte range") from exc

    return ByteRange(start, end, file_size), True


def plan_chunks(byte_range: ByteRange, chunk_size: int = 512 * 1024) -> ChunkPlan:
    """
    Calculate the exact aligned Telegram MTProto download offset, slice cuts,
    and total parts count required to serve the requested byte range without
    fetching any unneeded data.
    """
    offset = byte_range.start - (byte_range.start % chunk_size)
    first_cut = byte_range.start - offset
    last_cut = (byte_range.end % chunk_size) + 1
    count = (byte_range.end // chunk_size) - (offset // chunk_size) + 1

    return ChunkPlan(
        offset=offset,
        first_cut=first_cut,
        last_cut=last_cut,
        count=count,
    )
