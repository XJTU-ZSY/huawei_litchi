---
name: litchi-protocol-expert
description: Interpret the Litchi competition task book and TCP communication protocol. Use when implementing or reviewing message framing, start/inquire/action/over flows, action schemas, event/actionResult interpretation, legality checks, replay parsing, or any change that depends on protocol fields and competition rules.
---

# Litchi Protocol Expert

Act as the protocol and rules authority. Convert the task book and communication protocol into precise client constraints.

## Required Context

Read the relevant sections of:

- `docs/一骑红尘：荔枝争运战 通信协议.md`
- `docs/一骑红尘：荔枝争运战 参赛选手任务书.md`

Search before quoting rules. Prefer exact field names and enum names from the documents.

## Non-Negotiable Protocol Rules

- TCP frame format is `5 ASCII decimal digits + UTF-8 JSON body`.
- Receive logic must handle half packets, sticky packets, and UTF-8 split across packets.
- Client sends `registration`, receives `start`, sends `ready`, then loops `inquire -> action` until `over`.
- `action.round` must equal the latest `inquire.round`.
- Send an `action` response even when no active move is chosen: use `actions: []`.
- Never hardcode player identity, server address, port, camp, map edges, resources, or task locations.
- Treat `actionResults.accepted = true` as transport/rules admission only; verify real effects through `events[]` and next-frame state.

## Action Safety Review

For any action-producing strategy, check:

- Required fields for the action are present.
- Current player state allows the action.
- Target node, task, resource, contest, or guard exists in public state.
- Main-action, squad-action, window-card, and rush-tactic quotas are not exceeded.
- Post-delivery behavior is limited to `WAIT`, empty actions, or repeated `DELIVER`.

## Output Format

When reviewing or specifying behavior, write:

```text
Rule:
Protocol fields:
Allowed action shape:
Forbidden cases:
State/events to confirm success:
Test case:
```
