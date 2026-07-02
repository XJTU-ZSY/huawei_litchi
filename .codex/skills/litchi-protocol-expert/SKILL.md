---
name: litchi-protocol-expert
description: Protocol expert for the Litchi transport contest. Use when implementing or reviewing TCP framing, registration/start/ready/inquire/action/over flows, action field legality, state field parsing, error handling, actionResults/events interpretation, and replay messages derived from the official communication protocol.
---

# Litchi Protocol Expert

## Overview

Guard the client against protocol mistakes. Treat the communication document as the source of truth and prefer empty actions over malformed or illegal action packets.

## Required Checks

For every protocol change, verify:

1. TCP frames use `5 ASCII decimal digits + UTF-8 JSON body`.
2. The decoder buffers bytes, not strings, and supports half packets, sticky packets, and Chinese UTF-8 content.
3. The client follows `registration -> start -> ready -> inquire/action -> over`.
4. `action.round` always equals the just received `inquire.round`.
5. The client sends `actions: []` when no active action is safe.
6. Action objects contain only fields relevant to their action type.
7. At most one main action, one squad action, and one window action are submitted per frame.
8. `error` messages are treated as packet-level failures.
9. `events[]`, `actionResults[]`, and the next state are used together to judge whether an action truly worked.

## Action Categories

Main actions include `WAIT`, `MOVE`, `PROCESS`, `DOCK`, `CLAIM_RESOURCE`, `USE_RESOURCE`, `CLAIM_TASK`, `CLEAR`, `SET_GUARD`, `BREAK_GUARD`, `FORCED_PASS`, `VERIFY_GATE`, `DELIVER`, `RUSH_SPEED`, and `RUSH_PROTECT`.

Squad actions include `SQUAD_SCOUT`, `SQUAD_CLEAR`, `SQUAD_REINFORCE`, and `SQUAD_WEAKEN`.

Window action is `WINDOW_CARD`.

`BREAK_ORDER` is never sent as an independent action; it is a `rushTactic` value bound to `BREAK_GUARD` or `VERIFY_GATE`.

## Review Output

When reviewing a change, list protocol risks first. Include exact action fields, expected server feedback path, and tests that should cover it.
