# ADR 0004: Pin API runs to a fixed template, gate them with preflight, and mask credentials

- Status: accepted
- Date: 2026-10-19

## Context

The legacy `qa_run` path executes cases inside the caller's process with `CaseRunner`, caps a run at 200 cases, persists no record of which case body it executed, and has no notion of credentials beyond whatever the case interpolates. The API testing plan asks for the opposite: preflight before execution, a pinned snapshot per run, a fixed pytest template as the framework boundary, batching beyond 200, and credentials that never reach a report.

`qa_api_run` is the model-facing entry point for that. Its `start` action has to be honest about what it executed, or a later case edit silently rewrites history.

## Decision

1. **Preflight gates execution.** `execution.preflight` refuses draft cases, non-API cases, cases without `api.request`, cases without assertions, unresolved variables (except `run.*`, which an earlier case produces), cases whose catalog operation is missing, a project without `base_url`, and an invalid auth config. `start` raises with the blocker list instead of running a subset, because a partial run that reports "passed" is worse than no run.
2. **The snapshot lives in the run report.** Each test entry records `case_id`, `code`, revision and content hash, plus `template_version`. Version 3 needs no new table: the run row already carries a JSON report, and a snapshot is evidence about one run, not a new entity.
3. **One fixed template, copied per batch.** `nanobot/qa/templates/case_template.py` parametrizes over the cases, calls `CaseRunner` for requests and assertions, threads `run.*` extracted values between cases, and writes each result to JSON as it goes. The executor copies it to a temporary directory and runs it as a subprocess with `PYTHONPATH` set to this package root, so a worktree run cannot silently execute the deployed checkout's older runner. `CaseRunner` stays the only implementation of requests and assertions.
4. **Batches, not truncation.** More than 200 cases run in sequential batches; the report carries per-batch counts and a summary that covers the whole selection. Above 2000 the selection is refused instead of quietly narrowed.
5. **Credentials are resolved, never stored.** `auth` accepts `none`, `bearer` and `login`. Values may be `env:NAME` references. `preflight` validates the config without contacting the target; `start` obtains at most one token; the report, the log and every test message pass through `mask_payload` before persistence. A failed login persists a run with `classification: auth_failed`, so the failure is visible instead of thrown away.
6. **Failures are classified.** Each test carries `classification`: `passed`, `assertion_failed`, `config_error`, `env_blocked` or `skipped`. A run whose only errors are environment errors keeps the existing `blocked_by_env` status; everything else is `failed`. Assertion failures never become defects automatically.
7. **`extract` joins the case contract.** `api.extract` maps a name to a JSONPath; the value is available to later cases as `{{run.<name>}}`. This is an additive key in `case.api`: `validate_api_spec` normalizes it, the runner fills it, the template threads it. The WebUI case editor does not write `api` at all (it only reads assertion types), so the editor cannot drop the key.

## Consequences

- A run now answers "which case body ran" without a new schema version, and re-running after an edit produces a different snapshot on purpose.
- `start` is synchronous: the MCP call blocks until the run finishes and returns the stored result, then `get` reads it back. There is no job queue, so the plan's asynchronous start plus polling is not what this ships. A long suite therefore needs a client timeout above the batch budget.
- The template subprocess is a real process boundary: a template bug or a pytest import problem surfaces as "the run template did not report this case" per missing case rather than as a silent pass.
- `qa_run` keeps its in-process path for the WebUI and the legacy tool. Two paths exist until the plan's consolidation step, and this ADR records that they differ in preflight, snapshot, batching and masking.
- Extracted values live only in the run context; they are not persisted as variables, so a later run must extract again.

## Alternatives rejected

- **Run in-process and claim a template boundary.** The plan asks the template to own fixtures and parametrization; doing it in the caller's process would make the boundary fictional.
- **Add a schema version for snapshots.** A run is already an append-only record with a JSON report; a fourth version for one nested object buys nothing.
- **Execute the first 200 cases and warn.** The plan explicitly rejects silent truncation, and a summary that does not cover the selection misleads the reviewer.
- **Persist the token so later runs can reuse it.** Credentials would then live in the QA database and its backups; env references plus one login per run cost a request and keep the store clean.
- **Treat an auth failure as a thrown error only.** Without a run row the workbench shows nothing, and the operator cannot tell a bad password from a missing case.
