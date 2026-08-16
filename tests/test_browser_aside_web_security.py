from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

CAPABILITY = "CAPABILITY-SENTINEL-44CC"
BOOTSTRAP = "BOOTSTRAP-SENTINEL-7F3A"


class _SecurityError(Protocol):
    code: str
    safe_message: str


class _Guard(Protocol):
    def consume_bootstrap(self, nonce: str, *, host: str) -> str: ...

    def authorize(
        self,
        *,
        method: str,
        path: str,
        host: str,
        origin: str | None,
        fetch_site: str | None,
        content_type: str | None,
        cookie_capability: str | None,
        header_capability: str | None,
    ) -> None: ...


class _PrivacyFilter(Protocol):
    def display_url(self, raw_url: str) -> str: ...

    def observability(
        self,
        record: dict[str, object],
    ) -> dict[str, object]: ...

    def frame_headers(
        self,
        headers: dict[str, str],
    ) -> dict[str, str]: ...

    def text(self, value: str, *, max_length: int) -> str: ...


class _SecurityModule(Protocol):
    BrowserRequestDenied: type[Exception]

    def browser_request_guard(
        self,
        *,
        port: int,
        capability: str,
        bootstrap_nonce: str,
        clock: Callable[[], float] = ...,
        bootstrap_ttl_seconds: float = 60.0,
    ) -> _Guard: ...

    def browser_privacy_filter(self) -> _PrivacyFilter: ...


def _module() -> _SecurityModule:
    module: ModuleType = importlib.import_module(
        "birkin.web.browser_security"
    )
    return cast(_SecurityModule, cast(object, module))


def _guard() -> tuple[_SecurityModule, _Guard]:
    module = _module()
    return module, module.browser_request_guard(
        port=8797,
        capability=CAPABILITY,
        bootstrap_nonce=BOOTSTRAP,
    )


def _error(value: BaseException) -> _SecurityError:
    return cast(_SecurityError, cast(object, value))


def _authorize(
    guard: _Guard,
    *,
    method: str = "POST",
    host: str = "127.0.0.1:8797",
    origin: str | None = "http://127.0.0.1:8797",
    fetch_site: str | None = "same-origin",
    content_type: str | None = "application/json",
    cookie: str | None = CAPABILITY,
    header: str | None = None,
) -> None:
    guard.authorize(
        method=method,
        path="/api/browser-aside/session",
        host=host,
        origin=origin,
        fetch_site=fetch_site,
        content_type=content_type,
        cookie_capability=cookie,
        header_capability=header,
    )


def test_host_origin_and_capability_are_all_required() -> None:
    module, guard = _guard()
    _authorize(guard)
    for host in (
        "evil.test:8797",
        "127.0.0.1.evil.test:8797",
        "127.0.0.1:8798",
        "",
    ):
        with pytest.raises(module.BrowserRequestDenied) as captured:
            _authorize(guard, host=host)
        assert _error(captured.value).code == "host_denied"
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, origin="https://evil.test")
    assert _error(captured.value).code == "origin_denied"
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, cookie="wrong")
    assert _error(captured.value).code == "capability_denied"


def test_exact_localhost_origin_is_allowed_without_wildcard_cors() -> None:
    module, guard = _guard()
    _authorize(
        guard,
        host="localhost:8797",
        origin="http://localhost:8797",
    )
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, method="OPTIONS")
    assert _error(captured.value).code == "cors_preflight_denied"


def test_bootstrap_nonce_is_one_time_and_separate_from_capability() -> None:
    module, guard = _guard()
    assert guard.consume_bootstrap(
        BOOTSTRAP,
        host="127.0.0.1:8797",
    ) == CAPABILITY
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _ = guard.consume_bootstrap(
            BOOTSTRAP,
            host="127.0.0.1:8797",
        )
    assert _error(captured.value).code == "bootstrap_denied"
    with pytest.raises(module.BrowserRequestDenied):
        _ = guard.consume_bootstrap(
            CAPABILITY,
            host="127.0.0.1:8797",
        )


def test_bootstrap_expires_and_requires_exact_host() -> None:
    module = _module()
    now = [10.0]
    guard = module.browser_request_guard(
        port=8797,
        capability=CAPABILITY,
        bootstrap_nonce=BOOTSTRAP,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=5.0,
    )
    with pytest.raises(module.BrowserRequestDenied):
        _ = guard.consume_bootstrap(
            BOOTSTRAP,
            host="127.0.0.1",
        )
    guard = module.browser_request_guard(
        port=8797,
        capability=CAPABILITY,
        bootstrap_nonce=BOOTSTRAP,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=5.0,
    )
    now[0] = 15.0
    with pytest.raises(module.BrowserRequestDenied):
        _ = guard.consume_bootstrap(
            BOOTSTRAP,
            host="127.0.0.1:8797",
        )


def test_csrf_cookie_flow_and_cli_header_flow_are_distinct() -> None:
    module, guard = _guard()
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, origin=None, fetch_site=None)
    assert _error(captured.value).code == "csrf_denied"
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, content_type="text/plain")
    assert _error(captured.value).code == "content_type_denied"
    _authorize(
        guard,
        origin=None,
        fetch_site=None,
        cookie=None,
        header=CAPABILITY,
    )


def test_security_errors_never_echo_credentials() -> None:
    module, guard = _guard()
    with pytest.raises(module.BrowserRequestDenied) as captured:
        _authorize(guard, cookie=CAPABILITY + "-tampered")
    error = _error(captured.value)
    rendered = f"{error.code}:{error.safe_message}"
    assert CAPABILITY not in rendered
    assert BOOTSTRAP not in rendered


def test_private_browser_values_are_redacted_at_boundary() -> None:
    privacy = _module().browser_privacy_filter()
    secret = "PRIVATE-SENTINEL-9911"
    raw_url = (
        f"https://user:{secret}@example.com/path?token={secret}#{secret}"
    )
    assert privacy.display_url(raw_url) == "https://example.com/"
    record = privacy.observability(
        {
            "authorization": f"Bearer {secret}",
            "cookie": f"session={secret}",
            "url": raw_url,
            "nested": {"message": f"failed with {secret}"},
        }
    )
    encoded = repr(record)
    assert secret not in encoded
    assert "user:" not in encoded


def test_frame_metadata_uses_a_closed_safe_allowlist() -> None:
    privacy = _module().browser_privacy_filter()
    safe = privacy.frame_headers(
        {
            "X-Birkin-Frame-Digest": "hmac-sha256:" + "a" * 64,
            "X-Birkin-Frame-Ref": "birkin-frame:v1:opaque",
            "X-Birkin-Frame-Revision": "7",
            "X-Page-URL": "https://secret.test/?token=bad",
            "X-Page-Title": "private title",
            "X-Artifact-Path": "/Users/private/frame.jpg",
        }
    )
    assert set(safe) == {
        "X-Birkin-Frame-Digest",
        "X-Birkin-Frame-Ref",
        "X-Birkin-Frame-Revision",
    }


def test_untrusted_browser_metadata_is_inert_and_bounded() -> None:
    privacy = _module().browser_privacy_filter()
    raw = "<img src=x onerror=alert(1)>\x1b]8;;bad\x07\u202eSECRET"
    safe = privacy.text(raw, max_length=24)
    assert len(safe) <= 24
    assert "<" not in safe and ">" not in safe
    assert "\x1b" not in safe and "\x07" not in safe
    assert "\u202e" not in safe
    source = (
        Path(__file__).parents[1]
        / "birkin"
        / "web"
        / "static"
        / "index.html"
    ).read_text(encoding="utf-8")
    browser_script = source[source.index("function setBrowserStatus") :]
    assert "browser-aside-status\").innerHTML" not in browser_script
