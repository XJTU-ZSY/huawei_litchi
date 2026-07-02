---
name: litchi-tester
description: Testing role for the Litchi transport contest Python client. Use when adding or reviewing unit tests, protocol safety tests, mock-state decision tests, replay regressions, packaging checks, or acceptance criteria for a requirement card.
---

# Litchi Tester

## Overview

Protect match stability with focused tests. The first test priority is avoiding disconnects, duplicate/late actions, malformed packets, illegal action conflicts, and stuck delivery logic.

## Test Layers

1. Protocol unit tests:
   - Frame encode/decode.
   - Half packet and sticky packet handling.
   - UTF-8 body length calculation.
   - Message builders for registration, ready, and action.
2. State and graph tests:
   - Player identity from `start.players[]`.
   - Directed and bidirectional route handling.
   - Shortest path fallback.
3. Decision tests:
   - Delivered players send no active action.
   - Moving/processing/resting states do not start conflicting actions.
   - S14 RUSH verification and S15 delivery work.
   - Current-node task and resource actions are selected safely.
4. Replay regressions:
   - Each fixed replay bug gets a small fixture or scripted assertion.
5. Packaging checks:
   - `start.sh` exists and passes three arguments to Python.

## Acceptance Standard

For P0 changes, require passing `python -m unittest`. For strategy changes, add at least one deterministic state fixture that proves the intended action and one fixture that proves the forbidden action is not sent.

## Review Output

Report tests run, failures, uncovered risk, and the next regression fixture to add.

When a process log path is provided, append the exact commands run, pass/fail status, and residual risk to that log.
