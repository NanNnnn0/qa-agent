# ADR 0008: One execution pipeline for every run entry point

- Status: accepted
- Date: 2026-10-19

## Context

`qa_run` (the WebUI `/api/qa/runs/start` route, the agent tool, the CLI and scheduled runs) called `service.execute_cases`, an in-process loop with its own rules: no preflight, no record of which case revision ran, a 200-case cap that raised instead of batching, no credential masking and no failure classification. `execution.execute_pinned` added all of that for `qa_api_run`.

Two implementations of "run the cases" drift. The plan already requires the old entry to stop silently truncating at 200 cases and to report the full scope, and a WebUI run that skips preflight can execute a draft case whose assertions were never reviewed.

## Decision

1. **`service.execute_cases` becomes an adapter.** It keeps its signature (`case_ids`, `kind`, `task_id`, `name`, `environment`, `trigger`) and the task-artifact behavior, and delegates to `execution.execute_pinned`.
2. **Ready-only applies to every entry point.** A draft case now fails the call with the case codes and the reasons instead of running a subset. Callers set the status to `ready`; nothing auto-promotes.
3. **The 200-case cap is gone.** Batches cover up to 2000 cases, and above that the selection is refused rather than narrowed.
4. **`trigger` and `environment` pass through**, so scheduled runs still record `trigger=schedule` and the run history keeps its meaning.
5. **The old loop is deleted, not kept behind a flag.** Its environment-error helper and cap go with it; a second orchestration path is exactly how the two behaviors would diverge again. `CaseRunner` remains the single implementation of requests and assertions, and the fixed template remains the only executor.

## Consequences

- The WebUI run button on a draft case now shows a refusal that names the cases; that is a behavior change for the workbench and belongs in its release notes.
- A scheduled run that targets draft cases fails loudly instead of producing a run that looks green.
- Every case run now costs one template subprocess (about a second), which the legacy in-process path did not.
- Tests that created draft cases only to exercise run mechanics now set `status="ready"`, because the mechanics are what they test.
- Masking, snapshots and classification now cover WebUI, CLI, tool and scheduled runs without any caller opting in.

## Alternatives rejected

- **Keep a permissive legacy flag.** Two behaviors behind one entry point is the drift this ADR exists to remove, and the plan forbids the truncating variant.
- **Auto-promote drafts to ready on run.** It would silently approve an unreviewed case body, which is what `ready` means.
- **Share only `CaseRunner` and keep both orchestrations.** Requests and assertions were already shared; the divergence was in preflight, snapshot, batching and masking.
