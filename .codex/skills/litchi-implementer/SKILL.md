---
name: litchi-implementer
description: Implementation role for the Litchi transport contest Python client. Use when writing or modifying code for a scoped requirement card after protocol and architecture decisions are clear, especially for strategy heuristics, state handling, replay tooling, or tests.
---

# Litchi Implementer

## Overview

Implement one requirement at a time with minimal blast radius. Keep all live-client code standard-library only unless the competition package explicitly vendors dependencies.

## Implementation Rules

- Read the requirement card and relevant module before editing.
- Prefer pure functions for strategy and scoring logic.
- Return plain dictionaries for outbound actions.
- Never block the live frame loop with expensive search or file work.
- Keep per-frame decision work comfortably below 500 ms.
- Do not install dependencies at runtime.
- Log enough reason text to reproduce decisions from a replay.

## Coding Pattern

For strategy changes:

1. Add a small scoring or eligibility helper.
2. Add a safety check that converts uncertainty to no-op.
3. Add focused tests for the helper and final action.
4. Run the full unit suite.

## Live Client Constraints

- On any exception inside decision logic, send `actions: []`.
- Do not guess unknown server fields destructively; preserve raw dictionaries.
- Do not hardcode player side. Use `start.players[]`.
- Do not hardcode route list. Use `start.edges[]` and current `inquire.edges[]`.
