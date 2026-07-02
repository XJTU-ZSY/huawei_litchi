from __future__ import annotations

import logging
import os
import sys

from .client import ClientConfig, LitchiClient


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("Usage: python -m litchi_bot <playerId> <host> <port>", file=sys.stderr)
        return 2

    player_id, host, port_text = args
    try:
        port = int(port_text)
    except ValueError:
        print(f"Invalid port: {port_text}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=os.environ.get("LITCHI_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return LitchiClient(ClientConfig(player_id=player_id, host=host, port=port)).run()


if __name__ == "__main__":
    raise SystemExit(main())
