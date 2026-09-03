from __future__ import annotations

import pytest

from birkin import cli, web


@pytest.mark.parametrize("port", [70000, -1])
def test_web_rejects_out_of_range_port_before_server_start(
    port: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given an out-of-range CLI port and a server boundary that must not run.
    def fail_run(*, port: int | None, open_browser: bool) -> int:
        pytest.fail(f"server started with port={port}, open_browser={open_browser}")

    monkeypatch.setattr(web, "run", fail_run)

    # When the web command parses the port.
    with pytest.raises(SystemExit) as raised:
        _ = cli.main(["web", "--port", str(port), "--no-browser"])

    # Then argparse rejects it with a bounded conventional CLI error.
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.out == ""
    assert captured.err.startswith("usage:")
    assert "port must be between 0 and 65535" in captured.err
    assert "Traceback" not in captured.err
