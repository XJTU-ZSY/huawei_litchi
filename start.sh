#!/bin/bash
set -e

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>" >&2
  exit 1
fi

PLAYER_ID="$1"
HOST="$2"
PORT="$3"

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}."
exec python3 -m litchi_bot.main "${PLAYER_ID}" "${HOST}" "${PORT}"
