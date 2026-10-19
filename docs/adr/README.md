# Architecture decision records

One file per decision: `NNNN-kebab-title.md`, numbered sequentially from 0001, never renumbered and never edited after acceptance. A decision that changes course gets a new ADR that supersedes the old one; the old file stays in place with `Status: superseded by ADR-NNNN`.

Write an ADR when a change does any of the following:

- touches a public contract (`case.api`, `qa.*` WebSocket actions, dispatch prompts in `roles.py`);
- crosses a module boundary that `AGENTS.md` assigns to a different area;
- picks a dependency, a storage format, or a compatibility stance;
- would be expensive to reverse after another session builds on it.

Do not write one for routine implementation choices.

## Template

```markdown
# ADR NNNN: Title in the imperative

- Status: proposed | accepted | superseded by ADR-NNNN
- Date: YYYY-MM-DD

## Context

What forces are at play, in two or three sentences. State the constraint that makes this a decision rather than a preference.

## Decision

What we will do, stated so that a reviewer can disagree with it.

## Consequences

What becomes easier, what becomes harder, and what a future session must know to avoid undoing it.

## Alternatives rejected

Each alternative with the reason it lost. This is the part that saves the next session from re-proposing it.
```

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-api-asset-workflow.md) | Store API reference assets as catalog rows, revisions and batches | accepted |
| [0003](0003-api-asset-tools.md) | Expose the API asset workflow as MCP tools and move the role protocol onto it | accepted |
