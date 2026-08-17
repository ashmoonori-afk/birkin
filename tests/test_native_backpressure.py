from __future__ import annotations

from birkin.native.stream import BoundedEventBuffer


def _event(cursor: int) -> dict[str, object]:
    return {"cursor": cursor, "type": "message.assistant.delta"}


def test_overflow_replaces_queue_with_single_desync_marker() -> None:
    buffer = BoundedEventBuffer(capacity=2)
    assert buffer.push(_event(1)) is True
    assert buffer.push(_event(2)) is True

    assert buffer.push(_event(3)) is False
    assert buffer.push(_event(4)) is False

    assert buffer.drain() == (
        {
            "kind": "stream.desynchronized",
            "body": {"resume_after": 0},
        },
    )
    assert buffer.drain() == ()


def test_overflow_reports_last_delivered_cursor() -> None:
    buffer = BoundedEventBuffer(capacity=1)
    assert buffer.push(_event(1)) is True
    assert buffer.drain() == (_event(1),)
    assert buffer.push(_event(2)) is True

    assert buffer.push(_event(3)) is False

    assert buffer.drain()[0]["body"] == {"resume_after": 1}


def test_resubscribe_resets_desynchronized_buffer() -> None:
    buffer = BoundedEventBuffer(capacity=1)
    assert buffer.push(_event(1)) is True
    assert buffer.push(_event(2)) is False
    _ = buffer.drain()

    buffer.resubscribe(after_cursor=2)

    assert buffer.push(_event(3)) is True
    assert buffer.drain() == (_event(3),)
