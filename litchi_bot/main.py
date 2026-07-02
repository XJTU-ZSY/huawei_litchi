from __future__ import annotations

import argparse

from .client import run_client
from .protocol import parse_player_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Litchi transport contest client")
    parser.add_argument("playerId")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    run_client(parse_player_id(args.playerId), args.host, args.port)


if __name__ == "__main__":
    main()
