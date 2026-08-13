"""WebUI contract: Python owns state semantics; the page consumes, never copies.

Contracts: /api/contract exports the uistate JSON Schema plus the token
registry; the shipped page fetches that contract instead of hand-copying
state names; accessibility affordances (lang, aria labels, reduced motion,
focus-visible) ship in the page source.
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

from birkin import ui_tokens, uistate
from birkin.web import server as web_server


def _request(port: int, method: str, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(method, path, headers={"Host": "127.0.0.1"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


@pytest.fixture
def srv():
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_contract_endpoint_exports_schema_and_tokens(srv):
    code, body = _request(srv, "GET", "/api/contract")
    assert code == 200
    obj = json.loads(body)
    assert tuple(obj["uistate"]["properties"]["state"]["enum"]) == \
        uistate.UI_STATES
    enc = obj["uistate"]["x-birkin-encoding"]
    for state in uistate.UI_STATES:
        assert enc[state]["label"] == uistate.label(state)
        assert enc[state]["attention"] == uistate.attention_rank(state)
    assert set(obj["tokens"]["tokens"]) == set(ui_tokens.TOKENS)


def test_page_consumes_contract_instead_of_copying_it(srv):
    code, body = _request(srv, "GET", "/")
    assert code == 200
    html = body.decode("utf-8")
    assert "/api/contract" in html
    # state names must come from the generated contract, never be hardcoded
    for state in uistate.UI_STATES:
        assert f'"{state}"' not in html, state
    # palette hexes likewise stay in Python
    for token, value in ui_tokens.PALETTES[ui_tokens.DEFAULT_PALETTE].items():
        assert value not in html, token


def test_page_ships_accessibility_affordances(srv):
    _, body = _request(srv, "GET", "/")
    html = body.decode("utf-8")
    assert 'lang="ko"' in html
    assert "aria-label" in html
    assert "prefers-reduced-motion" in html
    assert "focus-visible" in html
    assert "aria-live" in html          # authority responses are announced
