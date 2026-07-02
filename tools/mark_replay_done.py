from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litchi_bot.replay_watch import create_done_files_from_latest_manifest, find_latest_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Create doneFile marker(s) from the latest replay manifest")
    parser.add_argument("replay_out_dir", help="Replay output directory containing *.manifest.json")
    parser.add_argument("--client", choices=("clientA", "clientB"), help="Only create this client's doneFile; default creates all declared doneFiles")
    args = parser.parse_args()

    replay_out_dir = Path(args.replay_out_dir)
    manifest_path = find_latest_manifest(replay_out_dir)
    if manifest_path is None:
        print(f"no *.manifest.json found in {replay_out_dir}", file=sys.stderr)
        return 1
    try:
        done_paths = create_done_files_from_latest_manifest(replay_out_dir, args.client)
    except Exception as exc:
        print(f"failed to create doneFile marker from {manifest_path}: {exc}", file=sys.stderr)
        return 1
    if not done_paths:
        print(f"no doneFile entry found in {manifest_path}", file=sys.stderr)
        return 1
    for path in done_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
