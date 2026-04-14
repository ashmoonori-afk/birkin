"""
Shared platform registry for Birkin.

Single source of truth for platform metadata consumed by both
skills_config (label display) and tools_config (default toolset
resolution).  Import ``PLATFORMS`` from here instead of maintaining
duplicate dicts in each module.
"""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="birkin-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="birkin-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="birkin-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="birkin-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="birkin-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="birkin-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="birkin-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="birkin-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="birkin-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="birkin-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="birkin-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="birkin-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="birkin-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="birkin-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="birkin-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="birkin-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="birkin-qqbot")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="birkin-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="birkin-api-server")),
])


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key, or *default*."""
    info = PLATFORMS.get(key)
    return info.label if info is not None else default
