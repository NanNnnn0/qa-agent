# ADR 0007: Reconcile two parallel schema v3 changes and two scheduler modules

- Status: accepted
- Date: 2026-10-19

## Context

While this session built the API asset tables under schema version 3, a parallel session landed a cron schedule feature that also claimed version 3: YAML case-index columns and a `schedules` table, plus `nanobot/qa/scheduler.py`. Their commit `d7714fd` on `feat/qa-workbench-polish` records that the two additive changes share v3 and keeps the number, because `SCHEMA` runs on every open and an existing v3 database still gains the new structures.

This session had independently added `nanobot/qa/scheduler.py` for a per-project run queue, and the deployment checkout `/opt/qa-agent` is currently detached at that other commit.

## Decision

1. **Schema version 3 is shared, not renumbered.** Both sides only add tables and columns through `SCHEMA`, and neither `_migrate` has version-3 DDL, so a database already at 3 gains the missing structures without a data rewrite. Neither branch bumps the marker again.
2. **The run queue module is `nanobot/qa/run_queue.py`.** It was renamed from `scheduler.py` because the cron `QaScheduler` owns that name. The two are independent: the cron scheduler claims due rows, the run queue orders executions of one project.
3. **Table names do not overlap.** The API asset side owns `api_*`; the schedule side owns `schedules` and the YAML case-index columns.
4. **The merge needs a gate run, not a migration.** Whoever merges the two branches must run the full QA gate on the merged tree, because each side's tests exercised a different half of the schema and neither ran against the other's tables.

## Consequences

- Merging costs one gate run and one journal note, not a version bump or a data fix.
- Two modules named for two jobs stay separate; folding the cron claim loop into the run queue is not implied here.
- A future additive change that needs real DDL still writes its own migration branch; sharing v3 is a statement about these two changes only.
- The deployment checkout is on the other branch, so this branch's STATUS page describes a worktree state, not the running service.

## Alternatives rejected

- **Bump the API assets to v4.** The deployed database would skip a version for a change that needs no DDL, and the other session already documented the shared-v3 stance.
- **Rename the cron module instead.** It is already deployed and referenced by its own tests; renaming the undeployed side is the smaller move.
- **Fold both into one scheduler.** They answer different questions (cron claims versus project ordering) and merging them would couple a database-claim loop to an execution queue.
