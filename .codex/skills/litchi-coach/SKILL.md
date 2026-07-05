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
   - P0 reliability: disconnects, missing actions, server `error`, rejected/illegal actions, stuck states, failed delivery.
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
6. When server feedback includes `msg_name:error`, `ACTION_REJECTED`, `INVALID_ACTION`, or `actionResults.accepted=false`, require root-cause analysis before accepting any card as complete.

## Replay Handoff Intake

When `$litchi-replay-analyst` or `.replay_watch/ai_tasks/*.prompt.md` provides a replay handoff:

1. Verify the evidence path: raw replay, machine report, AI replay analysis document path, process log, and player ID.
2. Ensure the final replay analysis is saved as its own Markdown document for this replay before the handoff is considered complete.
3. Convert findings into at most three requirement cards.
4. Prefer one high-confidence P0 card over multiple speculative strategy cards.
5. If any server error or rejected/illegal action appears, the top card must identify the triggering frame, action, error code, root cause, algorithm/code change, and replay regression check.
6. If there are no P0 failures, pick the highest expected win-rate or score improvement.
7. Keep implementation out of the intake response unless the user explicitly asks to proceed.
8. Append prioritization rationale, final requirement cards, and replay analysis document path to the referenced process log file.

## Process Logging

When a process log path is provided, append each major stage to it:

- Replay analysis summary and assumptions.
- Replay analysis document path.
- Server error root cause and anti-repeat decision, when any server feedback rejects an action.
- Coach prioritization rationale.
- Requirement cards.
- Architecture decisions before implementation.
- Code changes made.
- Tests and quality gate results.
- Git commit hash.

Use `python -B tools/process_log.py <log-path> --stage "<stage>" --message "<summary>"` when a deterministic append is useful.

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
- Treat every server-returned error as evidence until explained; improve code, strategy, tests, or protocol handling so the same cause is less likely to recur.
- Keep every round's AI replay analysis in a separate user-readable Markdown document, not only inside chat or the process log.
- Prefer measurable claims: score delta, illegal action count, delivery round, missed tasks, rejected actions.
