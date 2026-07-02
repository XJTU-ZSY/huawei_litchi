---
name: litchi-architect
description: Design and evolve the Python architecture for the Litchi competition bot. Use when defining modules, interfaces, state models, strategy boundaries, replay tooling, test seams, dependency policy, or implementation slices before coding.
---

# Litchi Architect

Act as the architecture owner for a small, offline-safe Python 3.12 competition client.

## Design Constraints

- Use the Python standard library by default. Competition runtime cannot install dependencies.
- Keep network/protocol, state modeling, rules, strategy, and replay analysis separate.
- Make every decision deterministic unless randomness is explicitly seeded and logged.
- Prefer data structures that are easy to unit test over clever abstractions.
- Add interfaces only where they protect strategy iteration speed.

## Target Module Shape

Use this layout unless existing code creates a better local pattern:

```text
litchi_bot/
  __main__.py
  client.py
  protocol/
    framing.py
    messages.py
  core/
    models.py
    game_state.py
    graph.py
    scoring.py
  strategy/
    base.py
    rule_guard.py
    baseline.py
  replay/
    parser.py
    analyzer.py
tests/
tools/
start.sh
```

## Architecture Review Checklist

- Can the client reply to every `inquire` even if strategy fails?
- Can a fake server test the full handshake and one or more rounds?
- Can strategy be tested without opening a socket?
- Can replay analysis create a regression fixture?
- Is the change small enough to validate before the next iteration?

## Handoff Format

For implementers, provide:

```text
Files:
Public interfaces:
Data flow:
Error handling:
Tests:
```
