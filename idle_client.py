#!/usr/bin/env python3
"""
Minimal idle client for local testing.

Behavior:
1. Connect to the server.
2. Send registration.
3. On start, send ready.
4. On every inquire, send action with actions: [].
5. On over, print the result and exit.
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Optional


MAX_FRAME_LEN = 99_999


class ProtocolError(Exception):
    pass


def setup_logging(log_dir: Optional[Path], player_id: int, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("idle_client")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"idle_client_{player_id}.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    return logger


def pack_message(msg_name: str, msg_data: Dict[str, Any]) -> bytes:
    body = json.dumps(
        {"msg_name": msg_name, "msg_data": msg_data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > MAX_FRAME_LEN:
        raise ProtocolError(f"message body too large: {len(body)} bytes")
    return f"{len(body):05d}".encode("ascii") + body


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("server closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(sock: socket.socket) -> Dict[str, Any]:
    prefix = recv_exact(sock, 5)
    if not prefix.isdigit():
        raise ProtocolError(f"invalid length prefix: {prefix!r}")
    size = int(prefix)
    if size <= 0 or size > MAX_FRAME_LEN:
        raise ProtocolError(f"invalid message size: {size}")
    body = recv_exact(sock, size)
    try:
        msg = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"message body is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"message body is not JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise ProtocolError("message body must be a JSON object")
    return msg


def send_message(sock: socket.socket, msg_name: str, msg_data: Dict[str, Any], logger: logging.Logger) -> None:
    sock.sendall(pack_message(msg_name, msg_data))
    logger.debug("sent %s %s", msg_name, msg_data)


def run_client(args: argparse.Namespace) -> int:
    player_id = int(args.player_id)
    player_name = args.name or f"idle-{player_id}"
    logger = setup_logging(Path(args.log_dir) if args.log_dir else None, player_id, args.verbose)

    match_id: Optional[str] = None
    ready_sent = False
    action_count = 0

    logger.info("connecting host=%s port=%s playerId=%s", args.host, args.port, player_id)
    with socket.create_connection((args.host, args.port), timeout=args.connect_timeout) as sock:
        sock.settimeout(args.socket_timeout)
        send_message(
            sock,
            "registration",
            {"playerId": player_id, "playerName": player_name, "version": args.version},
            logger,
        )
        logger.info("registration sent playerName=%s version=%s", player_name, args.version)

        while True:
            msg = read_message(sock)
            msg_name = msg.get("msg_name")
            msg_data = msg.get("msg_data", {})
            logger.debug("received %s %s", msg_name, msg_data)

            if msg_name == "start":
                match_id = msg_data["matchId"]
                start_round = int(msg_data.get("round", 1))
                my_info = next(
                    (p for p in msg_data.get("players", []) if int(p.get("playerId", -1)) == player_id),
                    {},
                )
                logger.info(
                    "start received matchId=%s round=%s team=%s",
                    match_id,
                    start_round,
                    my_info.get("teamId", "UNKNOWN"),
                )
                send_message(
                    sock,
                    "ready",
                    {"matchId": match_id, "round": start_round, "playerId": player_id},
                    logger,
                )
                ready_sent = True
                logger.info("ready sent round=%s", start_round)

            elif msg_name == "inquire":
                if not ready_sent or not match_id:
                    logger.warning("inquire received before start/ready; ignored")
                    continue
                round_no = int(msg_data["round"])
                send_message(
                    sock,
                    "action",
                    {"matchId": match_id, "round": round_no, "playerId": player_id, "actions": []},
                    logger,
                )
                action_count += 1
                logger.info("empty action sent round=%s total=%s", round_no, action_count)

            elif msg_name == "error":
                logger.warning(
                    "server error round=%s playerId=%s code=%s message=%s",
                    msg_data.get("round"),
                    msg_data.get("playerId"),
                    msg_data.get("errorCode"),
                    msg_data.get("message"),
                )

            elif msg_name == "over":
                logger.info(
                    "match over result=%s winner=%s overRound=%s actionsSent=%s",
                    msg_data.get("resultType"),
                    msg_data.get("winnerPlayerId"),
                    msg_data.get("overRound"),
                    action_count,
                )
                return 0

            else:
                logger.warning("unknown server message: %s", msg_name)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Idle client that sends empty actions every round.")
    parser.add_argument("player_id", help="playerId assigned by the platform/server")
    parser.add_argument("host", help="server host")
    parser.add_argument("port", type=int, help="server port")
    parser.add_argument("--name", default="", help="playerName sent in registration")
    parser.add_argument("--version", default="idle-client-1.0", help="client version sent in registration")
    parser.add_argument("--log-dir", default="client_logs", help="write client log files to this directory; empty disables file logs")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="connection timeout in seconds")
    parser.add_argument("--socket-timeout", type=float, default=None, help="socket read timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="print debug logs")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return run_client(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"idle client failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
