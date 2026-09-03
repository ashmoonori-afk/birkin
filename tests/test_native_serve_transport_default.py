"""Platform-aware transport selection for the native bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.native import serve


def test_default_transport_is_loopback_on_windows(tmp_path: Path) -> None:
    """Given Windows, When no transport is requested, Then loopback is used."""
    options = serve.NativeServeOptions.resolve(
        root=tmp_path,
        platform_name="nt",
    )

    assert options.transport == "loopback"


def test_default_transport_is_uds_on_posix(tmp_path: Path) -> None:
    """Given POSIX, When no transport is requested, Then UDS remains the default."""
    options = serve.NativeServeOptions.resolve(
        root=tmp_path,
        platform_name="posix",
    )

    assert options.transport == "uds"


def test_explicit_uds_is_honoured_on_posix(tmp_path: Path) -> None:
    """Given POSIX, When UDS is requested, Then it is retained verbatim."""
    options = serve.NativeServeOptions.resolve(
        transport="uds",
        root=tmp_path,
        platform_name="posix",
    )

    assert options.transport == "uds"


@pytest.mark.parametrize("transport", ("uds", "loopback"))
def test_explicit_transport_is_not_rewritten_on_windows(
    tmp_path: Path,
    transport: str,
) -> None:
    """Given Windows, When a transport is requested, Then it is retained verbatim."""
    options = serve.NativeServeOptions.resolve(
        transport=transport,
        root=tmp_path,
        platform_name="nt",
    )

    assert options.transport == transport
