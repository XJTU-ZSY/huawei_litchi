#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>" >&2
  exit 1
fi

PLAYER_ID="$1"
HOST="$2"
PORT="$3"

exec python3 idle_client.py "${PLAYER_ID}" "${HOST}" "${PORT}"
