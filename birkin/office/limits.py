from dataclasses import dataclass
@dataclass(frozen=True)
class PackageLimits:
    max_entries:int=10000; max_uncompressed_bytes:int=1_000_000_000; max_entry_ratio:int=1000
DEFAULT_LIMITS=PackageLimits()
