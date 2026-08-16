"""Bounded read-only CFB inventory used exclusively for binary HWP identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from .hwp_types import HwpLimits

CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_END = 0xFFFFFFFE
_FREE = 0xFFFFFFFF
_FAT = 0xFFFFFFFD
_SPECIAL = 0xFFFFFFFC


class HwpCfbError(ValueError):
    code: str

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CfbEntry:
    name: str
    entry_type: int
    start_sector: int
    size: int


@final
class HwpCfb:
    """A non-executing CFB parser supporting regular and MiniFAT streams."""

    def __init__(self, data: bytes, limits: HwpLimits) -> None:
        self._data = data
        self._limits = limits
        self._sector_size = 512
        self._sector_count = 0
        self._fat: tuple[int, ...] = ()
        self._mini_fat: tuple[int, ...] = ()
        self._mini_cutoff = 4096
        self._root: CfbEntry | None = None
        self.entries: tuple[CfbEntry, ...] = ()
        self._parse()

    @staticmethod
    def _u16(data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + 2], "little")

    @staticmethod
    def _u32(data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + 4], "little")

    @staticmethod
    def _u64(data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + 8], "little")

    def _fail(self, message: str) -> HwpCfbError:
        return HwpCfbError("hwp_cfb_invalid", message)

    def _sector(self, sector_id: int) -> bytes:
        if sector_id < 0 or sector_id >= self._sector_count:
            raise self._fail("CFB sector index is outside the file")
        start = 512 + sector_id * self._sector_size
        return self._data[start : start + self._sector_size]

    def _chain(self, start: int, table: tuple[int, ...]) -> tuple[int, ...]:
        if start == _END:
            return ()
        chain: list[int] = []
        seen: set[int] = set()
        current = start
        while current != _END:
            if (
                current >= len(table)
                or current in seen
                or len(chain) >= self._limits.max_chain_sectors
            ):
                raise self._fail("invalid or over-limit CFB sector chain")
            seen.add(current)
            chain.append(current)
            current = table[current]
            if current >= _SPECIAL and current != _END:
                raise self._fail("invalid CFB chain terminator")
        return tuple(chain)

    def _regular_stream(self, entry: CfbEntry) -> bytes:
        chain = self._chain(entry.start_sector, self._fat)
        required = (entry.size + self._sector_size - 1) // self._sector_size
        if len(chain) != required:
            raise self._fail(f"stream {entry.name!r} has an inconsistent sector chain")
        return b"".join(self._sector(item) for item in chain)[: entry.size]

    def _parse(self) -> None:
        data = self._data
        if data[:8] != CFB_MAGIC:
            raise HwpCfbError("hwp_cfb_magic_invalid", "binary HWP requires CFB magic")
        if len(data) < 512:
            raise self._fail("truncated CFB header")
        if data[28:30] != b"\xfe\xff" or self._u16(data, 26) != 3:
            raise self._fail("binary HWP requires a CFB v3 little-endian container")
        if self._u16(data, 30) != 9 or self._u16(data, 32) != 6:
            raise self._fail("invalid CFB sector shifts")
        if any(data[34:40]) or self._u32(data, 40) != 0:
            raise self._fail("CFB v3 reserved fields are nonzero")
        if self._u32(data, 68) != _END or self._u32(data, 72) != 0:
            raise self._fail("extended CFB DIFAT is unsupported")
        if (len(data) - 512) % 512:
            raise self._fail("truncated CFB sector")
        self._sector_count = (len(data) - 512) // 512
        if not 0 < self._sector_count <= self._limits.max_cfb_sectors:
            raise self._fail("CFB sector count is outside the configured limit")
        fat_count = self._u32(data, 44)
        if not 0 < fat_count <= min(109, self._sector_count):
            raise self._fail("extended or invalid CFB FAT is unsupported")
        difat = [self._u32(data, offset) for offset in range(76, 512, 4)]
        fat_ids = [item for item in difat if item != _FREE]
        if len(fat_ids) != fat_count or len(set(fat_ids)) != len(fat_ids):
            raise self._fail("CFB DIFAT does not match the FAT count")
        fat: list[int] = []
        for sector_id in fat_ids:
            fat.extend(
                self._u32(self._sector(sector_id), offset)
                for offset in range(0, 512, 4)
            )
        self._fat = tuple(fat)
        if any(item >= len(self._fat) or self._fat[item] != _FAT for item in fat_ids):
            raise self._fail("CFB FAT sectors are not marked as FAT")
        directory = b"".join(
            self._sector(item) for item in self._chain(self._u32(data, 48), self._fat)
        )
        self._parse_directory(directory)
        self._mini_cutoff = self._u32(data, 56)
        if self._mini_cutoff != 4096:
            raise self._fail("nonstandard CFB mini-stream cutoff")
        mini_count = self._u32(data, 64)
        mini_start = self._u32(data, 60)
        if mini_count:
            chain = self._chain(mini_start, self._fat)
            if len(chain) != mini_count:
                raise self._fail("CFB MiniFAT chain count mismatch")
            raw = b"".join(self._sector(item) for item in chain)
            self._mini_fat = tuple(
                self._u32(raw, offset) for offset in range(0, len(raw), 4)
            )
        elif mini_start != _END:
            raise self._fail("CFB declares an unused MiniFAT start sector")

    def _parse_directory(self, directory: bytes) -> None:
        entries: list[CfbEntry] = []
        names: set[str] = set()
        for offset in range(0, len(directory), 128):
            item = directory[offset : offset + 128]
            entry_type = item[66]
            if entry_type == 0:
                continue
            if entry_type not in (1, 2, 5):
                raise self._fail("invalid CFB directory entry type")
            name_size = self._u16(item, 64)
            if not 2 <= name_size <= 64 or name_size % 2:
                raise self._fail("invalid CFB directory name length")
            encoded = item[: name_size - 2]
            try:
                name = encoded.decode("utf-16le", "strict")
            except UnicodeDecodeError as error:
                raise self._fail("invalid CFB directory name encoding") from error
            folded = name.casefold()
            if not name or folded in names:
                raise self._fail("empty or duplicate CFB directory name")
            names.add(folded)
            entries.append(
                CfbEntry(name, entry_type, self._u32(item, 116), self._u64(item, 120))
            )
            if len(entries) > self._limits.max_directory_entries:
                raise self._fail("CFB directory entry limit exceeded")
        roots = [entry for entry in entries if entry.entry_type == 5]
        if len(roots) != 1 or roots[0].name != "Root Entry":
            raise self._fail("CFB must contain one canonical root entry")
        self._root = roots[0]
        self.entries = tuple(entries)

    def entry(self, name: str) -> CfbEntry | None:
        folded = name.casefold()
        return next(
            (item for item in self.entries if item.name.casefold() == folded), None
        )

    def read_stream(self, entry: CfbEntry, *, max_bytes: int) -> bytes:
        if entry.entry_type != 2 or entry.size > max_bytes:
            raise self._fail(
                f"stream {entry.name!r} is invalid or exceeds its byte limit"
            )
        if entry.size == 0:
            return b""
        if entry.size >= self._mini_cutoff:
            return self._regular_stream(entry)
        if self._root is None or not self._mini_fat:
            raise self._fail("small stream has no root mini stream or MiniFAT")
        mini_root = self._regular_stream(self._root)
        chain = self._chain(entry.start_sector, self._mini_fat)
        required = (entry.size + 63) // 64
        if len(chain) != required:
            raise self._fail(f"mini stream {entry.name!r} has an inconsistent chain")
        chunks: list[bytes] = []
        for sector_id in chain:
            start = sector_id * 64
            if start + 64 > len(mini_root):
                raise self._fail("mini-sector index is outside the root mini stream")
            chunks.append(mini_root[start : start + 64])
        return b"".join(chunks)[: entry.size]
