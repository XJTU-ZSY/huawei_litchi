from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litchi_bot.process_log import append_process_event, create_process_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or append to an iteration process log")
    parser.add_argument("log")
    parser.add_argument("--title", default="Iteration Process Log")
    parser.add_argument("--stage", default="Note")
    parser.add_argument("--message", default="")
    parser.add_argument("--init", action="store_true", help="Initialize the log if it does not exist")
    args = parser.parse_args()

    path = Path(args.log)
    if args.init:
        create_process_log(path, args.title)
    append_process_event(path, args.stage, args.message)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
