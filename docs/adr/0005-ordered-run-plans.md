# ADR 0005: Order API runs as versioned setup, cases and cleanup phases

- Status: accepted
- Date: 2026-10-19

## Context

A run of independent cases cannot express the shape most API work actually has: create data, verify it, remove it. The plan asks for a versioned ordered structure whose steps reference case ids and revisions, where a dependency failure skips the dependent steps and a cleanup failure is recorded separately from an assertion failure.

A pinned run already records which revision each case executed. An ordered plan adds the question of order and of intent: which step prepares, which verifies, which cleans up.

## Decision

1. **A plan is `{version, setup, cases, cleanup}`.** Each step is `{case_id, revision?}`. `normalize_plan` rejects unknown fields, an empty plan, a duplicate case inside one phase, and a non-positive revision. A plan and `case_ids` are mutually exclusive: a plan states its own selection.
2. **A revision pin is a drift guard, not time travel.** The pinned revision must equal the case's current revision, otherwise preflight blocks with the exact mismatch. Running a historical snapshot body is deliberately not offered: the case row is the execution source, and the pin exists so a stale plan cannot silently run a body nobody reviewed.
3. **Phase semantics are fixed.** Setup runs first. A failed setup step marks the remaining setup steps skipped and the whole cases phase `dependency_blocked`, because those cases depend on data setup was supposed to create. Cleanup always runs, including after a setup failure, since it may need to remove what setup already created. A failed case does not skip later cases; independent cases are independent.
4. **Cleanup failures have their own classification.** A failed cleanup test is `cleanup_failed` and fails the run even when every case passed, because leaked data is a defect in the suite, not a detail.
5. **Extracted values cross phases.** Each phase may be its own template batch, so `execute_pinned` carries `run.*` values from setup into cases and cleanup; within a batch the template does the same.
6. **The snapshot records the plan.** `snapshot.plan.phases` lists each step's case id and resolved revision, so a report answers which order ran against which revision.

## Consequences

- The demo workflow (create an order, read it, cancel it) is now expressible as data, and a test covers it end to end.
- Cleanup running after a setup failure means a cleanup step that depends on a value setup never extracted will fail; it is recorded as `cleanup_failed` rather than hidden, which is the honest outcome.
- Batches are per phase, so a three-phase plan issues up to three template subprocesses even for three cases. That cost buys phase isolation and the skip rules above.
- A plan that pins an old revision is refused rather than executed. The operator must re-read the current case and re-validate the plan.
- Plans live in the run report, not in a table: a plan describes one execution, and `api_workflows` remains the asset batch, not the run.

## Alternatives rejected

- **Execute the historical snapshot body when the pin is old.** The operator would run a body the editor no longer shows, and the case row would stop being the execution source of truth.
- **One flat ordered list without phases.** A setup failure would be indistinguishable from an assertion failure, and cleanup could not be guaranteed to run.
- **Skip cleanup when setup failed.** Partially created data would leak, which is exactly the state cleanup exists to prevent.
- **A new table for plans.** The run row already carries a JSON report; a plan is evidence about one run, and a table would add a version bump for one nested object.
