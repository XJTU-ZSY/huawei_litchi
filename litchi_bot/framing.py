from __future__ import annotations

import json
from typing import Any


MAX_FRAME_LENGTH = 99999
PREFIX_LENGTH = 5


class ProtocolError(ValueError):
    """Raised when a TCP frame cannot be parsed safely."""


def encode_frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_LENGTH:
        raise ProtocolError(f"frame body too large: {len(body)}")
    return f"{len(body):05d}".encode("ascii") + body


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        if not data:
            return []
        self._buffer.extend(data)
        messages: list[dict[str, Any]] = []
        while True:
            if len(self._buffer) < PREFIX_LENGTH:
                break
            prefix = bytes(self._buffer[:PREFIX_LENGTH])
            if not prefix.isdigit():
                raise ProtocolError(f"invalid length prefix: {prefix!r}")
            body_length = int(prefix)
            if body_length > MAX_FRAME_LENGTH:
                raise ProtocolError(f"frame length exceeds maximum: {body_length}")
            frame_length = PREFIX_LENGTH + body_length
            if len(self._buffer) < frame_length:
                break
            body = bytes(self._buffer[PREFIX_LENGTH:frame_length])
            del self._buffer[:frame_length]
            try:
                messages.append(json.loads(body.decode("utf-8")))
            except UnicodeDecodeError as exc:
                raise ProtocolError("invalid UTF-8 body") from exc
            except json.JSONDecodeError as exc:
                raise ProtocolError("invalid JSON body") from exc
        return messages
