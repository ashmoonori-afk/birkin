"""RED-first Browser Aside network-policy and action-security proofs.

Grounded in `.omo/design/native-browser-aside/SECURITY_PRIVACY.md` and `ACTION_SECURITY.md`:
assertions consume typed policy decisions and denial codes only, never wall-clock timing,
real DNS, or a live browser.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import pytest

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.sandbox import NetworkPolicy, SandboxPolicy

SECRET = "BIRKIN-SENTINEL-SECRET-7F3A"
Rule = tuple[str, str, int]
Fields = tuple[tuple[str, str], ...]


class _Destination(Protocol):
    scheme: str
    host: str
    port: int
    display_url: str

class _Egress(Protocol):
    def evaluate(self, url: str) -> _Destination: ...
    def connect(self, url: str, peer: str = "") -> str: ...
    def follow_redirects(self, chain: Sequence[str]) -> _Destination: ...

class _Decision(Protocol):
    kind: str
    result: str
    code: str
    approval: str
    digest: str
    receipt: Mapping[str, object]

class _Authority(Protocol):
    def decide(
        self, *, kind: str, source: str, url: str = "", method: str = "GET",
        fields: Fields = (), path: str = "", gesture: str = "",
    ) -> _Decision: ...
    def replay(self, approval: str, *, fields: Fields = ()) -> _Decision: ...

class _PolicyModule(Protocol):
    def browser_egress_policy(
        self, policy: SandboxPolicy, *, private_network: tuple[Rule, ...] = (),
        resolver: Callable[[str], tuple[str, ...]] | None = None,
        control_addresses: tuple[str, ...] = (),
    ) -> _Egress: ...
    def browser_action_authority(
        self, *, egress: _Egress, secrets: tuple[str, ...], jail_root: str
    ) -> _Authority: ...

def _module() -> _PolicyModule:
    return cast(_PolicyModule, cast(object, importlib.import_module("birkin.browser_aside_policy")))

def _policy(*hosts: str) -> SandboxPolicy:
    if not hosts:
        return SandboxPolicy()
    return SandboxPolicy(network=NetworkPolicy.ALLOWLIST, network_allowlist=hosts)

def _denied(call: Callable[[], object]) -> str:
    with pytest.raises(BrowserAsideError) as caught:
        _ = call()
    return caught.value.code

def _auth(
    root: Path, *, hosts: tuple[str, ...] = ("example.com",), private: tuple[Rule, ...] = ()
) -> _Authority:
    module = _module()
    egress = module.browser_egress_policy(_policy(*hosts), private_network=private)
    return module.browser_action_authority(egress=egress, secrets=(SECRET,), jail_root=str(root))

def _decide(
    auth: _Authority, kind: str, source: str, url: str = "", *, method: str = "GET",
    fields: Fields = (), path: str = "", gesture: str = "",
) -> _Decision:
    return auth.decide(
        kind=kind, source=source, url=url, method=method, fields=fields, path=path, gesture=gesture
    )

def test_network_egress_policy_denies_off_and_unlisted_hosts() -> None:
    module = _module()
    off = module.browser_egress_policy(_policy())
    assert _denied(lambda: off.evaluate("https://example.com/")) == "network_policy_denied"

    gate = module.browser_egress_policy(_policy("example.com"))
    allowed = gate.evaluate("https://EXAMPLE.com:443/a?token=1#frag")
    assert (allowed.scheme, allowed.host, allowed.port) == ("https", "example.com", 443)
    assert allowed.display_url == "https://example.com/a"
    assert _denied(lambda: gate.evaluate("https://evil.example.net/")) == "network_policy_denied"

def test_privileged_scheme_denial_is_not_overridable() -> None:
    gate = _module().browser_egress_policy(_policy("example.com"))
    urls = (
        "file:///etc/passwd", "javascript:fetch('/')", "data:text/html,<h1>x</h1>", "about:blank",
        "blob:https://example.com/9f", "filesystem:https://example.com/tmp/x", "chrome://settings",
        "devtools://devtools/bundled/x.html", "view-source:https://example.com/", "ftp://ex.com/x",
        "ws://example.com/s", "wss://example.com/s",
    )
    for url in urls:
        assert _denied(lambda u=url: gate.evaluate(u)) == "unsupported_scheme"

def test_private_network_ssrf_requires_an_exact_trusted_rule() -> None:
    hosts = ("localhost", "169.254.169.254", "10.0.0.5", "metadata.google.internal", "2130706433",
             "::1", "dev.localhost")
    blocked = ("http://localhost/", "http://169.254.169.254/latest/meta-data/",
               "http://10.0.0.5/admin", "http://metadata.google.internal/", "http://2130706433/",
               "http://[::1]:8080/")
    module = _module()
    addresses = {
        "localhost": ("127.0.0.1",),
        "169.254.169.254": ("169.254.169.254",),
        "10.0.0.5": ("10.0.0.5",),
        "metadata.google.internal": ("169.254.169.254",),
        "2130706433": ("127.0.0.1",),
        "::1": ("::1",),
        "dev.localhost": ("127.0.0.1",),
    }
    resolver = lambda host: addresses[host]
    wide = module.browser_egress_policy(
        _policy(*hosts),
        resolver=resolver,
    )
    for url in blocked:
        assert _denied(lambda u=url: wide.evaluate(u)) == "private_network_denied"

    scoped = module.browser_egress_policy(
        _policy(*hosts),
        private_network=(
            ("dev.localhost", "127.0.0.1/32", 8080),
        ),
        resolver=resolver,
    )
    allowed = scoped.evaluate("http://dev.localhost:8080/fixture")
    assert (allowed.host, allowed.port) == ("dev.localhost", 8080)
    for url in ("http://dev.localhost:9000/", "http://localhost:8080/"):
        assert _denied(lambda u=url: scoped.evaluate(u)) == "private_network_denied"

def test_cgnat_is_private_network_for_ssrf_policy() -> None:
    gate = _module().browser_egress_policy(
        _policy("carrier.example"),
        resolver=lambda _host: ("100.64.0.1",),
    )
    assert (
        _denied(lambda: gate.evaluate("https://carrier.example/"))
        == "private_network_denied"
    )

def test_dns_rebinding_mixed_answers_fail_before_page_bytes() -> None:
    public = ("93.184.216.34",)
    answers = (public, public, ("93.184.216.34", "127.0.0.1"), ("10.0.0.5",))
    asked: list[str] = []

    def resolver(host: str) -> tuple[str, ...]:
        asked.append(host)
        return answers[min(len(asked) - 1, len(answers) - 1)]

    site = "https://example.com/"
    gate = _module().browser_egress_policy(_policy("example.com"), resolver=resolver)
    assert gate.connect(site) == "93.184.216.34"
    assert _denied(
        lambda: gate.connect(site, peer="127.0.0.1")
    ) == "dns_rebinding_denied"
    for _answer_set in ("mixed", "rebound"):
        assert _denied(lambda: gate.connect(site)) == "dns_rebinding_denied"
    assert asked == ["example.com"] * 5

def test_redirect_chain_policy_rechecks_every_hop() -> None:
    gate = _module().browser_egress_policy(_policy("example.com", "10.0.0.5"))
    final = gate.follow_redirects(("https://example.com/a", "/b", "https://example.com/c"))
    assert final.display_url == "https://example.com/c"

    chains = {
        "private_network_denied": ("https://example.com/a", "http://10.0.0.5/x"),
        "unsupported_scheme": ("https://example.com/a", "file:///etc/passwd"),
        "browser_redirect_policy": tuple(f"https://example.com/{n}" for n in range(22)),
    }
    for code, chain in chains.items():
        assert _denied(lambda c=chain: gate.follow_redirects(c)) == code

def test_shared_authority_denials_have_no_bypass_path() -> None:
    gate = _module().browser_egress_policy(
        _policy("example.com", "127.0.0.1"),
        private_network=(("127.0.0.1", "127.0.0.1/32", 8787),),
        control_addresses=("127.0.0.1:8787",),
    )
    assert _denied(lambda: gate.evaluate("http://127.0.0.1:8787/api")) == "control_address_denied"

    shipped = BrowserEgressPolicy(
        policy=_policy("example.com", "127.0.0.1")
    )
    for url in ("file:///etc/passwd", "https://user:pw@example.com/", "http://127.0.0.1/"):
        shared = _denied(lambda u=url: gate.evaluate(u))
        assert _denied(lambda u=url: shipped.check_navigation(u)) == shared != ""

def test_navigation_and_form_actions_require_typed_human_authority(tmp_path: Path) -> None:
    auth = _auth(
        tmp_path, hosts=("example.com", "dev.localhost", "10.0.0.5"),
        private=(("dev.localhost", "127.0.0.1/32", 8080),),
    )
    url = "https://example.com/a"
    human = _decide(auth, "navigate", "web_human", url, gesture="g1")
    assert (human.kind, human.result, human.approval) == ("navigation", "allow", "")

    agent = _decide(auth, "navigate", "agent", "http://dev.localhost:8080/x")
    assert (agent.kind, agent.result) == ("navigation", "approval_required")
    assert agent.approval != ""
    denied = _decide(auth, "navigate", "agent", "http://10.0.0.5/admin")
    assert (denied.result, denied.code, denied.approval) == ("denied", "private_network_denied", "")

    values: Fields = (("q", "hello"),)
    safe = _decide(auth, "form_submit", "web_human", url, fields=values, gesture="g2")
    assert (safe.kind, safe.result) == ("form_submit", "allow")
    posted = _decide(auth, "form_submit", "web_human", url, method="POST", fields=values,
                     gesture="g3")
    assert (posted.kind, posted.result) == ("form_submit", "approval_required")

def test_navigation_url_uses_shared_secret_scanner(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    decision = _decide(
        auth,
        "navigate",
        "web_human",
        f"https://example.com/?token={SECRET}",
        gesture="omnibox",
    )
    assert (decision.result, decision.code) == (
        "denied",
        "secret_detected",
    )

def test_download_export_and_upload_stay_inside_the_file_jail(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    local = tmp_path / "picked.txt"
    _ = local.write_text("hello", encoding="utf-8")
    url = "https://example.com/u"
    upload = _decide(auth, "upload", "web_human", url, method="POST", path=str(local), gesture="g1")
    assert (upload.kind, upload.result) == ("upload", "approval_required")

    outside = _decide(auth, "upload", "web_human", url, method="POST", path="/etc/x", gesture="g2")
    assert (outside.result, outside.code, outside.approval) == ("denied", "upload_jail_denied", "")
    scripted = _decide(auth, "upload", "agent", url, method="POST", path=str(local))
    assert (scripted.result, scripted.code) == ("denied", "upload_jail_denied")

    export = _decide(auth, "download_export", "agent", path=str(tmp_path / "out.bin"))
    assert (export.kind, export.result) == ("download_export", "approval_required")
    escape = _decide(auth, "download_export", "web_human", path="/tmp/x/o.bin", gesture="g3")
    assert (escape.result, escape.code) == ("denied", "export_jail_denied")

def test_secret_scan_blocks_and_binds_an_immutable_approval_digest(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    url = "https://example.com/f"
    leak: Fields = (("note", f"token={SECRET}"),)
    leaking = _decide(auth, "form_submit", "agent", url, method="POST", fields=leak)
    assert (leaking.result, leaking.code, leaking.approval) == ("denied", "secret_scan_denied", "")
    assert SECRET not in "".join(str(value) for value in leaking.receipt.values())

    clean: Fields = (("note", "clean"),)
    pending = _decide(auth, "form_submit", "agent", url, method="POST", fields=clean)
    assert (pending.result, pending.digest != "") == ("approval_required", True)
    replay = auth.replay(pending.approval, fields=clean)
    assert (replay.result, replay.digest) == ("allow", pending.digest)

    tampered = auth.replay(pending.approval, fields=(("note", "changed"),))
    assert (tampered.result, tampered.code) == ("denied", "approval_stale")
    reused = auth.replay(pending.approval, fields=clean)
    assert (reused.result, reused.code) == ("denied", "approval_stale")

def test_clipboard_and_sensitive_permissions_have_no_approval_route(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    for kind in ("clipboard", "permission"):
        for source in ("web_human", "agent"):
            d = _decide(auth, kind, source, "https://example.com/", gesture="g1")
            assert (d.kind, d.result, d.code) == (kind, "denied", "unsupported_capability")
            assert d.approval == ""

def test_popup_and_external_protocol_dispatch_fail_closed(tmp_path: Path) -> None:
    auth = _auth(tmp_path)
    scripted = _decide(auth, "popup", "page", "https://example.com/p")
    assert (scripted.kind, scripted.result, scripted.code) == ("popup", "denied", "popup_blocked")
    human = _decide(auth, "popup", "web_human", "https://example.com/p", gesture="g1")
    assert (human.kind, human.result) == ("popup", "allow")
    external = ("external_protocol", "denied", "external_protocol_denied")
    for url in ("mailto:ops@example.com", "tel:+15550100", "ssh://example.com", "app://open"):
        d = _decide(auth, "navigate", "web_human", url, gesture="g2")
        assert (d.kind, d.result, d.code) == external
