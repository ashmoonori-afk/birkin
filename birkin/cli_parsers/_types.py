"""Shared parser registration types."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping

CommandHandler = Callable[[argparse.Namespace], int]
Handlers = Mapping[str, CommandHandler]
