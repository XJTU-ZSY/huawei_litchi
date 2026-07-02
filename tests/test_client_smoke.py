from __future__ import annotations

import socket
import threading
import unittest
from typing import Any
import logging

from litchi_bot.client import ClientConfig, LitchiClient
from litchi_bot.protocol.framing import FrameDecoder, encode_frame
from litchi_bot.strategy.base import BaseStrategy


class BrokenStrategy(BaseStrategy):
    def decide(self, inquire_data: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("boom")


class FakeServer(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.ready = threading.Event()
        self.port: int | None = None
        self.messages: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", 0))
                server.listen(1)
                self.port = int(server.getsockname()[1])
                self.ready.set()

                conn, _ = server.accept()
                with conn:
                    conn.settimeout(3)
                    self.messages.append(_recv_one(conn))
                    _send_one(
                        conn,
                        {
                            "msg_name": "start",
                            "msg_data": {
                                "matchId": "match_smoke",
                                "round": 1,
                                "players": [{"playerId": 1001, "teamId": "RED"}],
                            },
                        },
                    )
                    self.messages.append(_recv_one(conn))

                    for round_number in (1, 2, 3):
                        _send_one(
                            conn,
                            {
                                "msg_name": "inquire",
                                "msg_data": {"matchId": "match_smoke", "round": round_number},
                            },
                        )
                        self.messages.append(_recv_one(conn))

                    _send_one(conn, {"msg_name": "over", "msg_data": {"matchId": "match_smoke"}})
        except BaseException as exc:  # pragma: no cover - reported in test thread
            self.error = exc
            self.ready.set()


def _send_one(conn: socket.socket, message: dict[str, Any]) -> None:
    conn.sendall(encode_frame(message))


def _recv_one(conn: socket.socket) -> dict[str, Any]:
    decoder = FrameDecoder()
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            raise AssertionError("client closed connection before sending a message")
        messages = decoder.feed(chunk)
        if messages:
            return messages[0]


class ClientSmokeTests(unittest.TestCase):
    def test_client_handshake_and_empty_actions_survive_strategy_error(self) -> None:
        server = FakeServer()
        server.start()
        self.assertTrue(server.ready.wait(3), "fake server did not start")
        self.assertIsNotNone(server.port)

        client = LitchiClient(
            ClientConfig(player_id="1001", host="127.0.0.1", port=server.port, timeout_seconds=3),
            strategy=BrokenStrategy(),
            logger=_quiet_logger(),
        )
        self.assertEqual(client.run(), 0)
        server.join(3)

        if server.error is not None:
            raise server.error
        self.assertFalse(server.is_alive(), "fake server thread did not exit")

        registration = server.messages[0]
        self.assertEqual(registration["msg_name"], "registration")
        self.assertEqual(registration["msg_data"]["playerId"], 1001)

        ready = server.messages[1]
        self.assertEqual(ready["msg_name"], "ready")
        self.assertEqual(ready["msg_data"]["matchId"], "match_smoke")
        self.assertEqual(ready["msg_data"]["round"], 1)

        actions = server.messages[2:]
        self.assertEqual([msg["msg_data"]["round"] for msg in actions], [1, 2, 3])
        self.assertTrue(all(msg["msg_name"] == "action" for msg in actions))
        self.assertTrue(all(msg["msg_data"]["actions"] == [] for msg in actions))


def _quiet_logger() -> logging.Logger:
    logger = logging.getLogger("litchi_bot.tests.quiet")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


if __name__ == "__main__":
    unittest.main()
