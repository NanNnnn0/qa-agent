# ADR 0001: Record architecture decisions

- Status: accepted
- Date: 2026-10-18

## Context

The project is developed by several agent sessions in parallel, each with a finite context window. Decisions that live only in a conversation are lost when that conversation ends, and the next session re-litigates them, often differently. The fork also has contracts that span several layers (the structured `case.api` payload, the WebSocket mutation channel, dispatch prompts), where a local change has remote consequences.

## Decision

Every decision that crosses a module boundary, changes a public contract, or would be expensive to reverse is recorded as an ADR in `docs/adr/`, numbered sequentially, immutable once accepted.

An ADR states the context, the decision, the consequences, and the alternatives that were rejected. Superseding an ADR means writing a new one that references the old; the old one stays.

## Consequences

- A new session can read the decisions in order and understand why the code looks the way it does.
- Reviewing a change that contradicts an ADR is cheap: the contradiction is visible before the code is written.
- Writing an ADR costs a few minutes and is therefore reserved for decisions that matter; routine implementation choices do not get one.

## Alternatives rejected

- **Decision log in commit messages only.** Cheap, but not discoverable before the change is made.
- **A single architecture document rewritten in place.** Loses the reasoning behind superseded choices and produces merge conflicts when two sessions edit it.
