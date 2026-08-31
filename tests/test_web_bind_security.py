from __future__ import annotations

import socket

from pytest import MonkeyPatch

from birkin.web import server as web_server


class _StoppingServer:
    def __init__(
        self,
        address: tuple[str, int],
        _handler: type[web_server.Handler],
    ) -> None:
        self.server_address: tuple[str, int] = address

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


def test_explicit_remote_mode_supplies_httpserver_wildcard_host(
    monkeypatch: MonkeyPatch,
) -> None:
    # Given: remote mode has an explicit public HTTPS origin.
    cfg = {
        **web_server.config.load_config(),
        "web_remote_access": True,
        "web_external_url": "https://birkin-host.example:8765",
    }
    bound_addresses: list[tuple[str, int]] = []

    def stopping_server(
        address: tuple[str, int],
        handler: type[web_server.Handler],
    ) -> _StoppingServer:
        bound_addresses.append(address)
        return _StoppingServer(address, handler)

    def reject_interface_resolution(_hostname: str) -> str:
        raise AssertionError("remote mode selected one interface")

    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    monkeypatch.setattr(web_server, "HTTPServer", stopping_server)
    monkeypatch.setattr(socket, "getfqdn", lambda: "birkin-host.example")
    monkeypatch.setattr(socket, "gethostbyname", reject_interface_resolution)

    # When: the standalone WebUI starts in explicit remote mode.
    result = web_server.run(port=8765, open_browser=False)

    # Then: HTTPServer receives Python's canonical all-interface host.
    assert result == 0
    assert bound_addresses == [("", 8765)]
