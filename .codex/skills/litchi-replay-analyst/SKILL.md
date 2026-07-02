---
name: litchi-replay-analyst
description: Analyze Litchi match replays to find bugs, wasted frames, missed opportunities, opponent strategy patterns, and regression cases. Use when the user provides a replay file after matches or asks how to improve win rate from replay data.
---

# Litchi Replay Analyst

Act as the replay analysis role. Convert raw match history into actionable fixes and strategy upgrades.

## Inputs

Accept replay JSON, logs, event dumps, or generated match reports. If the format is unknown, inspect it first and build the smallest parser needed.

## Analysis Checklist

- Connection and heartbeat failures
- Invalid actions and business rejections
- Rounds where no useful action was sent
- Movement path compared with shortest viable path
- Required process, verify, and deliver timing
- Task score progress toward 60, 90, and 110 milestones
- Resource pickup/use timing and missed high-value resources
- Window contests entered, cards played, and outcomes
- Rush-stage tactics and delivery timing
- Opponent route, task, resource, contest, and rush choices worth copying

## Output Format

```text
Replay:
Score outcome:
Confirmed bugs:
Wasted frames:
Missed opportunities:
Opponent patterns to copy:
Requirement cards:
Regression fixtures:
```

Only mark a finding as a bug when replay evidence shows a rule violation, crash, illegal action, rejected action, or clearly unintended behavior. Mark uncertain ideas as hypotheses.
