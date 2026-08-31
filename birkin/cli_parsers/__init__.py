"""Composition root for the Birkin argparse command surface."""

from __future__ import annotations

import argparse

from . import automation, core, integrations, memory, native, workers
from ._types import Handlers


def build_parser(*, version: str, handlers: Handlers) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="birkin",
        description="Lightweight self-improving CLI agent workspace",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
    )
    subparsers = parser.add_subparsers(dest="command")
    core.register(subparsers, handlers)
    native.register_web_and_bridge(subparsers, handlers)
    native.register_services_and_voice(subparsers, handlers)
    automation.register_tools_models_and_scheduler(subparsers, handlers)
    workers.register(subparsers, handlers)
    memory.register(subparsers, handlers)
    automation.register_operations(subparsers, handlers)
    integrations.register(subparsers, handlers)
    return parser
