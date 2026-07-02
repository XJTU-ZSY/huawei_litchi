---
name: litchi-architect
description: Architecture role for the Litchi transport contest Python client. Use when splitting requirements into modules, defining interfaces between protocol, state, graph, strategy, replay analysis, and tests, or deciding how to keep an AI-written contest client maintainable under a short deadline.
---

# Litchi Architect

## Overview

Keep code modular enough for rapid AI iteration. Favor small interfaces, deterministic logic, and replayable decisions over clever but opaque strategy code.

## Module Boundaries

- `framing.py`: byte-level TCP frame encoding and decoding only.
- `protocol.py`: outbound message and action packet construction only.
- `game_state.py`: normalize `start` and `inquire` messages into context and snapshots.
- `graph.py`: route graph, adjacency, and shortest path logic.
- `decision.py`: top-level safe decision orchestration.
- `strategy/`: independent strategy components with no socket code.
- `replay.py`: offline parsing and reports; never affect live TCP logic directly.
- `client.py`: socket loop, logging, and role handoff.

## Design Rules

- Keep protocol and strategy independent.
- Make every decision return plain JSON-compatible action dictionaries.
- Preserve raw server data for fields not yet modeled.
- Avoid hardcoding fixed maps; derive from `start` and current `inquire`.
- Put risky heuristics behind small functions that can be unit tested.
- Log decision reasons in live play and replay analysis.

## Requirement Handoff

For each requirement card, provide:

1. Target module and function names.
2. Data inputs and outputs.
3. State that must be persisted across frames.
4. Tests to add or update.
5. Failure mode if the heuristic is wrong.
