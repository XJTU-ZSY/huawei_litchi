from __future__ import annotations

import json
from typing import Any

PREFIX_SIZE = 5
MAX_BODY_BYTES = 99999


class FrameDecodeError(ValueError):
    """Raised when a TCP frame cannot be decoded as protocol JSON."""


def encode_frame(message: dict[str, Any] | str | bytes) -> bytes:
    if isinstance(message, bytes):
        body = message
    elif isinstance(message, str):
        body = message.encode("utf-8")
    else:
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    if len(body) > MAX_BODY_BYTES:
        raise ValueError(f"message body exceeds {MAX_BODY_BYTES} bytes")

    return f"{len(body):05d}".encode("ascii") + body


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if data:
            self._buffer.extend(data)

        messages: list[dict[str, Any]] = []
        while True:
            if len(self._buffer) < PREFIX_SIZE:
                return messages

            prefix = bytes(self._buffer[:PREFIX_SIZE])
            if not prefix.isdigit():
                raise FrameDecodeError(f"invalid frame length prefix: {prefix!r}")

            body_len = int(prefix.decode("ascii"))
            if body_len > MAX_BODY_BYTES:
                raise FrameDecodeError(f"frame body too large: {body_len}")

            frame_len = PREFIX_SIZE + body_len
            if len(self._buffer) < frame_len:
                return messages

            body = bytes(self._buffer[PREFIX_SIZE:frame_len])
            del self._buffer[:frame_len]

            try:
                decoded = body.decode("utf-8")
                message = json.loads(decoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise FrameDecodeError("invalid JSON frame body") from exc

            if not isinstance(message, dict):
                raise FrameDecodeError("JSON frame body must be an object")
            messages.append(message)
