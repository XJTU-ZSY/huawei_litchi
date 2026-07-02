from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litchi_bot.replay import analyze_messages, format_report, load_messages
from litchi_bot.protocol import parse_player_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a Litchi replay or JSONL log")
    parser.add_argument("path")
    parser.add_argument("--player-id")
    args = parser.parse_args()
    player_id = parse_player_id(args.player_id) if args.player_id else None
    messages = load_messages(args.path)
    print(format_report(analyze_messages(messages, player_id)))


if __name__ == "__main__":
    main()
