from collections.abc import Mapping, Sequence
from re import Match
from typing import Generic, TextIO, TypeVar

from pexpect.exceptions import EOF

_Text = TypeVar("_Text", str, bytes)

class spawn(Generic[_Text]):
    pid: int | None
    exitstatus: int | None
    logfile_read: TextIO | None
    match: Match[_Text] | None

    def __init__(
        self,
        command: str,
        args: Sequence[str] = ...,
        timeout: float = ...,
        maxread: int = ...,
        searchwindowsize: int | None = ...,
        logfile: TextIO | None = ...,
        cwd: str | None = ...,
        env: Mapping[str, str] | None = ...,
        ignore_sighup: bool = ...,
        echo: bool = ...,
        preexec_fn: None = ...,
        encoding: str | None = ...,
        codec_errors: str = ...,
        dimensions: tuple[int, int] | None = ...,
        use_poll: bool = ...,
    ) -> None: ...

    def send(self, value: _Text) -> int: ...
    def setwinsize(self, rows: int, cols: int) -> None: ...
    def expect_exact(self, pattern: _Text, timeout: float | None = ...) -> int: ...
    def expect(
        self,
        pattern: _Text | type[EOF],
        timeout: float | None = ...,
    ) -> int: ...
    def close(self, force: bool = ...) -> None: ...
    def isalive(self) -> bool: ...
