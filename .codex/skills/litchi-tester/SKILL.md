---
name: litchi-tester
description: Design and run validation for the Litchi competition bot. Use when creating unit tests, fake-server tests, replay regressions, legality tests, packaging checks, or when reviewing whether a strategy/protocol change is safe to submit.
---

# Litchi Tester

Act as the validation owner. Catch disconnects, illegal actions, protocol mistakes, and replay regressions before matches.

## Test Priorities

1. Framing handles half packets, sticky packets, and multiple frames.
2. Handshake follows `registration -> start -> ready -> inquire/action -> over`.
3. Every `inquire` receives an `action` with matching round.
4. Strategy exceptions degrade to `actions: []`, not a crash.
5. Action guard blocks illegal or duplicate category actions.
6. Replay-derived bugs get permanent regression tests.
7. `start.sh` accepts exactly `playerId host port` and launches the Python client.

## Preferred Test Types

- Pure unit tests for framing, graph, scoring, state parsing, and rule guard.
- Fake socket or fake server smoke tests for protocol loop.
- Replay fixtures for known bugs and opponent-learning cases.
- Packaging self-check before submission.

## Report Format

```text
Tests run:
Result:
Coverage of requirement:
Gaps:
Next recommended test:
```
