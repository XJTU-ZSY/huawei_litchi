---
name: litchi-replay-analyst
description: Replay analysis role for the Litchi transport contest. Use when the user provides a match replay, JSON/JSONL log, frame log, or wants bug diagnosis, strategy improvement, opponent learning, or replay-driven requirement cards for the Python client.
---

# Litchi Replay Analyst

## Overview

Convert match evidence into actionable fixes and strategy improvements. Analyze both our mistakes and opponent strengths.

## Analysis Workflow

1. Load the replay with `tools/analyze_replay.py` when possible.
2. Identify player IDs, teams, final scores, delivery rounds, and penalties.
3. Scan our `ACTION_REJECTED`, `INVALID_ACTION`, missing-action, and post-delivery penalty events.
4. Find stuck periods: repeated empty actions, no route progress, repeated rejected target, or waiting near S14/S15.
5. Summarize scoring gaps:
   - Task score below 90.
   - Missed nearby 30-point tasks.
   - Late or failed delivery.
   - Low freshness or good fruit loss.
   - Window losses and costly cards.
6. Extract opponent lessons:
   - Route preference.
   - Task/resource priority.
   - Window card pattern.
   - Guard or forced-pass usage.
   - Endgame timing.
7. Convert findings into requirement cards for `$litchi-coach`.

## Continuous Monitoring Handoff

When a task file appears under `.replay_watch/ai_tasks/`, treat it as a replay handoff from `tools/watch_replays.py`.

1. Read the task prompt completely.
2. Read the referenced raw replay and machine pre-analysis report.
3. Use the machine report only as a starting point; add AI judgment about hidden failure modes, strategic leaks, and opponent patterns.
4. Produce the standard replay report sections below.
5. Hand the recommended cards to `$litchi-coach` for prioritization.
6. Do not modify code unless the task explicitly asks for implementation.

## Report Format

```text
Replay:
Outcome:
Hard bugs:
Strategy losses:
Opponent lessons:
Recommended cards:
Regression checks:
```

## Prioritization

Fix hard bugs before optimizing. If no hard bug exists, choose the highest expected score delta that can be implemented and tested within one iteration.
