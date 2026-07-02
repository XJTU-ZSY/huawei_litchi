---
name: litchi-coach
description: Coach workflow for the Litchi transport contest. Use when planning an iteration, prioritizing strategy work, reviewing replay findings, deciding the next requirement card, or coordinating protocol, architecture, implementation, and testing roles for this Python contest client.
---

# Litchi Coach

## Overview

Act as the owner of win rate and delivery quality. Keep the team focused on the smallest verified improvement that raises score, reduces illegal actions, or fixes replay-proven failures.

## Workflow

1. Read `docs/backlog.md`, `docs/strategy_notes.md`, and any replay report involved in the request.
2. Classify the request as one of:
   - P0 reliability: disconnects, missing actions, illegal actions, stuck states, failed delivery.
   - P1 scoring: task score, route choice, resources, endgame timing.
   - P2 opponent learning: window cards, guards, blocking, route prediction.
3. Write or update one requirement card before coding.
4. Route the card through these roles:
   - `$litchi-protocol-expert` for fields, legality, errors, and server feedback.
   - `$litchi-architect` for module boundaries and interfaces.
   - `$litchi-implementer` for a scoped code change.
   - `$litchi-tester` for unit, mock, or replay regression checks.
   - `$litchi-replay-analyst` when the input is a match replay.
5. Accept the iteration only after tests or a replay regression can explain the outcome.

## Replay Handoff Intake

When `$litchi-replay-analyst` or `.replay_watch/ai_tasks/*.prompt.md` provides a replay handoff:

1. Verify the evidence path: raw replay, machine report, and player ID.
2. Convert findings into at most three requirement cards.
3. Prefer one high-confidence P0 card over multiple speculative strategy cards.
4. If there are no P0 failures, pick the highest expected win-rate or score improvement.
5. Keep implementation out of the intake response unless the user explicitly asks to proceed.

## Requirement Card

Use this format:

```text
Title:
Priority: P0/P1/P2
Evidence: document section, test failure, or replay file
Expected behavior:
Forbidden behavior:
Implementation owner:
Validation:
Status:
```

## Coaching Rules

- Protect P0 reliability before optimizing score.
- Do not request broad rewrites when a small, testable change fixes the current card.
- Convert every replay lesson into either a bug fix, strategy heuristic, or explicit rejection.
- Prefer measurable claims: score delta, illegal action count, delivery round, missed tasks, rejected actions.
