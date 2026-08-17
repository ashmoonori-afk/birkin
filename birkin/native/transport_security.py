"""Platform-specific peer identity and socket-path checks."""

from __future__ import annotations

import os
import socket
import stat
import struct
from pathlib import Path
from typing import cast

from birkin.native.protocol import NativeProtocolError


def peer_uid(connection: socket.socket) -> int | None:
    getpeereid = getattr(connection, "getpeereid", None)
    if callable(getpeereid):
        peer = cast(tuple[int, int], getpeereid())
        return peer[0]
    so_peercred = getattr(socket, "SO_PEERCRED", None)
    if isinstance(so_peercred, int):
        raw = connection.getsockopt(
            socket.SOL_SOCKET,
            so_peercred,
            struct.calcsize("3i"),
        )
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid
    local_peercred = getattr(socket, "LOCAL_PEERCRED", None)
    if isinstance(local_peercred, int):
        xucred_format = "@IIh2x16I"
        raw = connection.getsockopt(
            0,
            local_peercred,
            struct.calcsize(xucred_format),
        )
        _version, uid, _group_count, *_groups = struct.unpack(
            xucred_format,
            raw,
        )
        return uid
    return None


def reject_symlinks(socket_path: Path) -> None:
    for candidate in (socket_path, *socket_path.parents):
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise NativeProtocolError(
                "E_SOCKET_PATH",
                "Unix socket path must not traverse symbolic links",
            )
