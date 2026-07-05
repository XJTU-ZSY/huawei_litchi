from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any

from .decision import DecisionEngine
from .framing import FrameDecoder, ProtocolError, encode_frame
from .game_state import GameMemory
from .protocol import action, error_recovery_policy, ready, registration


class GameClient:
    def __init__(self, player_id: int | str, host: str, port: int, log_dir: str = "logs") -> None:
        self.player_id = player_id
        self.host = host
        self.port = int(port)
        self.memory = GameMemory(player_id)
        self.decision = DecisionEngine(self.memory)
        self.decoder = FrameDecoder()
        self.log_dir = Path(log_dir)
        self.log_file = None

    def run(self) -> None:
        with socket.create_connection((self.host, self.port), timeout=10) as sock:
            sock.settimeout(None)
            self._send(sock, registration(self.player_id))
            while True:
                data = sock.recv(65536)
                if not data:
                    self._log({"kind": "disconnect"})
                    return
                for message in self.decoder.feed(data):
                    if self._handle_message(sock, message):
                        return

    def _handle_message(self, sock: socket.socket, message: dict[str, Any]) -> bool:
        name = message.get("msg_name")
        data = message.get("msg_data") or {}
        self._log({"kind": "recv", "msg_name": name, "round": data.get("round")})
        if name == "start":
            context = self.memory.apply_start(data)
            self._open_match_log(context.match_id)
            self._send(sock, ready(context.match_id, context.start_round, self.player_id))
        elif name == "inquire":
            if self.memory.context is None:
                self._log({"kind": "warning", "message": "inquire before start"})
                return False
            snapshot = self.memory.apply_inquire(data)
            actions = self.decision.decide(self.memory.context, snapshot)
            payload = action(self.memory.context.match_id, snapshot.round_no, self.player_id, actions)
            self._log(
                {
                    "kind": "decision",
                    "round": snapshot.round_no,
                    "actions": actions,
                    "reason": self.decision.last_reason,
                }
            )
            self._send(sock, payload)
        elif name == "error":
            error_code = data.get("errorCode")
            self._log(
                {
                    "kind": "server_error",
                    "errorCode": error_code,
                    "policy": error_recovery_policy(error_code),
                    "data": data,
                }
            )
        elif name == "over":
            self._log({"kind": "over", "data": data})
            return True
        else:
            self._log({"kind": "unknown_message", "message": message})
        return False

    def _send(self, sock: socket.socket, message: dict[str, Any]) -> None:
        sock.sendall(encode_frame(message))
        data = message.get("msg_data") or {}
        self._log({"kind": "send", "msg_name": message.get("msg_name"), "round": data.get("round")})

    def _open_match_log(self, match_id: str) -> None:
        try:
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = (self.log_dir / f"{match_id}.jsonl").open("a", encoding="utf-8")
        except OSError as exc:
            print(f"log disabled: {exc}", file=sys.stderr)
            self.log_file = None

    def _log(self, row: dict[str, Any]) -> None:
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        print(line, file=sys.stderr, flush=True)
        if self.log_file is not None:
            self.log_file.write(line + "\n")
            self.log_file.flush()


def run_client(player_id: int | str, host: str, port: int) -> None:
    try:
        GameClient(player_id, host, port).run()
    except ProtocolError as exc:
        print(f"protocol error: {exc}", file=sys.stderr)
        raise
