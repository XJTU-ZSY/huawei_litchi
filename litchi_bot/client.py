from __future__ import annotations

from dataclasses import dataclass
import logging
import socket
from typing import Any

from . import __version__
from .protocol.framing import FrameDecodeError, FrameDecoder, encode_frame
from .protocol.messages import action, ready, registration
from .strategy.baseline import BaselineStrategy
from .strategy.base import BaseStrategy


@dataclass(frozen=True)
class ClientConfig:
    player_id: int | str
    host: str
    port: int
    player_name: str = "litchi-bot"
    version: str = __version__
    recv_size: int = 65536
    timeout_seconds: float = 30.0


class LitchiClient:
    def __init__(
        self,
        config: ClientConfig,
        strategy: BaseStrategy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.strategy = strategy or BaselineStrategy(config.player_id)
        self.logger = logger or logging.getLogger(__name__)
        self.match_id: str | None = None
        self.running = True

    def run(self) -> int:
        decoder = FrameDecoder()
        address = (self.config.host, self.config.port)
        with socket.create_connection(address, timeout=self.config.timeout_seconds) as sock:
            sock.settimeout(self.config.timeout_seconds)
            self._send(sock, registration(self.config.player_id, self.config.player_name, self.config.version))

            while self.running:
                try:
                    chunk = sock.recv(self.config.recv_size)
                except socket.timeout:
                    self.logger.warning("Timed out waiting for server data")
                    continue

                if not chunk:
                    self.logger.info("Server closed connection")
                    break

                try:
                    messages = decoder.feed(chunk)
                except FrameDecodeError:
                    self.logger.exception("Failed to decode server frame")
                    return 1

                for message in messages:
                    for response in self.handle_message(message):
                        self._send(sock, response)

        return 0

    def handle_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        msg_name = message.get("msg_name")
        msg_data = message.get("msg_data")
        if not isinstance(msg_data, dict):
            msg_data = {}

        if msg_name == "start":
            return self._handle_start(msg_data)
        if msg_name == "inquire":
            return self._handle_inquire(msg_data)
        if msg_name == "over":
            self.running = False
            return []
        if msg_name == "error":
            self.logger.error("Server error message: %s", msg_data)
            return []

        self.logger.debug("Ignoring unknown message: %s", msg_name)
        return []

    def _handle_start(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        match_id = data.get("matchId")
        if not match_id:
            self.logger.error("start message missing matchId")
            return []

        self.match_id = str(match_id)
        try:
            self.strategy.on_start(data)
        except Exception:
            self.logger.exception("Strategy on_start failed; continuing with protocol loop")

        round_number = _as_int(data.get("round"), default=1)
        return [ready(self.match_id, round_number, self.config.player_id)]

    def _handle_inquire(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        if self.match_id is None:
            self.logger.error("inquire received before start/matchId")
            return []

        round_number = _as_int(data.get("round"), default=None)
        if round_number is None:
            self.logger.error("inquire message missing round")
            return []

        try:
            actions = self.strategy.decide(data)
        except Exception:
            self.logger.exception("Strategy decide failed; sending empty action")
            actions = []

        if actions is None:
            actions = []
        elif not isinstance(actions, list):
            try:
                actions = list(actions)
            except TypeError:
                self.logger.error("Strategy returned non-iterable actions; sending empty action")
                actions = []

        return [action(self.match_id, round_number, self.config.player_id, actions)]

    def _send(self, sock: socket.socket, message: dict[str, Any]) -> None:
        sock.sendall(encode_frame(message))
        self.logger.debug("Sent %s", message.get("msg_name"))


def _as_int(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
