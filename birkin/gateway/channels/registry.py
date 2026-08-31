"""Registry for send-only gateway delivery adapters.

The registry is deliberately separate from :func:`build_channels`: legacy
HTTP and Telegram channels own long-running inbound loops, while entries here
are lightweight outbound targets created only when a delivery names them.
"""

from __future__ import annotations

from collections.abc import Callable

from .registry_types import ChannelEntry, Config, DeliveryTarget


class Registry:
    """Named adapter entries, resolved before a caller's legacy fallback."""

    def __init__(self) -> None:
        self._entries: dict[str, ChannelEntry] = {}

    @staticmethod
    def _name(name: str) -> str:
        return str(name or "").strip().lower()

    def register(self, entry: ChannelEntry) -> None:
        name = self._name(entry.name)
        if not name:
            raise ValueError("channel entry name must not be empty")
        if name in self._entries:
            raise ValueError(f"channel entry already registered: {name}")
        if entry.max_message_len <= 0:
            raise ValueError("channel max_message_len must be positive")
        self._entries[name] = entry

    def get(self, name: str) -> ChannelEntry | None:
        return self._entries.get(self._name(name))

    def names(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def labels(self) -> tuple[str, ...]:
        """Human-facing names that make channel direction explicit."""
        return tuple(
            f"{entry.name} ({entry.direction})" for entry in self._entries.values()
        )

    def resolve(
        self,
        name: str,
        cfg: Config,
        *,
        fallback: Callable[[str], DeliveryTarget | None] | None = None,
    ) -> DeliveryTarget | None:
        """Create a registered, enabled target or use ``fallback``.

        A known but disabled/invalid channel does not fall through: treating a
        misspelled Slack or Discord configuration as a legacy target would hide
        the configuration error and could route a message to the wrong place.
        """
        normalized = self._name(name)
        entry = self.get(normalized)
        if entry is None:
            return fallback(normalized) if fallback is not None else None
        configured_channels = cfg.get("channels")
        channel_cfg = (
            configured_channels.get(normalized)
            if isinstance(configured_channels, dict)
            else None
        )
        if isinstance(channel_cfg, dict) and not bool(
            channel_cfg.get("enabled", False)
        ):
            return None
        if entry.validate_cfg(cfg):
            return None
        return entry.factory(cfg)


# Imports happen only after the contract exists, avoiding adapter/registry
# initialization cycles while keeping built-ins available from one registry.
def _builtins() -> Registry:
    from .discord_webhook import entry as discord_entry
    from .slack_webhook import entry as slack_entry

    registry = Registry()
    registry.register(slack_entry())
    registry.register(discord_entry())
    return registry


default_registry = _builtins()


def register(entry: ChannelEntry) -> None:
    default_registry.register(entry)


def get(name: str) -> ChannelEntry | None:
    return default_registry.get(name)


def names() -> tuple[str, ...]:
    return default_registry.names()


def labels() -> tuple[str, ...]:
    return default_registry.labels()


def resolve_delivery_target(
    name: str,
    cfg: Config,
    *,
    fallback: Callable[[str], DeliveryTarget | None] | None = None,
    registry: Registry = default_registry,
) -> DeliveryTarget | None:
    """Resolve an outbound channel, preserving legacy behavior as fallback."""
    return registry.resolve(name, cfg, fallback=fallback)


__all__ = [
    "ChannelEntry",
    "Registry",
    "default_registry",
    "get",
    "labels",
    "names",
    "register",
    "resolve_delivery_target",
]
