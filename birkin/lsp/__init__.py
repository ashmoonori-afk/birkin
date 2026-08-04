"""Language-server diagnostics for the file tools.

``protocol`` is the wire format and the delta rule; ``client`` is one server
process driven synchronously. Nothing here imports an event loop -- see
``client``'s docstring for why that is a requirement rather than a preference.
"""

from __future__ import annotations

from . import diagnostics
from .client import DEFAULT_TIMEOUT, LspClient
from .protocol import LspError, encode, new_since, read_message

__all__ = ["DEFAULT_TIMEOUT", "LspClient", "LspError", "diagnostics",
           "encode", "new_since", "read_message"]
