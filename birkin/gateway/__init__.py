"""birkin gateway — run the agent as a persistent service across channels.

Like hermes' gateway, this is the control plane: it keeps a session per
conversation, shares one memory vault + skill catalog across every channel
(so birkin "remembers you" no matter where you talk to it), and routes
messages to/from pluggable channels (local HTTP by default, Telegram optional).
"""

from .core import Gateway, run

__all__ = ["Gateway", "run"]
