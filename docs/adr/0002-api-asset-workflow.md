# ADR 0002: Store API reference assets as catalog rows, revisions and batches

- Status: accepted
- Date: 2026-10-19

## Context

The QA store keeps a case as its result: a request, assertions and steps. It cannot answer which reference material a case came from, what its body looked like before an edit, or which batch created it, and `export_cases` silently returned at most 500 cases because it reused the paged listing.

Three constraints make this a decision rather than a preference. The structured `case.api` contract is public, so the case editors, the runner and the WebUI already depend on its shape. Existing deployments hold version-2 databases that must keep working without a rewrite. Reference material is re-read repeatedly, so ingesting the same document twice must not duplicate work while a document dropping an endpoint must not delete the cases built on it.

## Decision

1. **Identity.** An endpoint is `method + normalize_api_path`, where path parameter names collapse to `{}`: `/orders/{id}` and `/orders/{orderId}` are one operation. `UNIQUE(project_id, method, path)` enforces it and `path_template` keeps the original spelling for display and evidence.
2. **Catalog.** `api_operations` stores the normalized spec, its evidence (JSON pointer plus material version) and a content hash. Ingest parses OpenAPI 3.0/3.1 JSON or YAML, compares before writing, writes nothing when the hash is unchanged, and marks operations missing from the material `status = 'missing'` instead of deleting them.
3. **Revisions.** `api_case_revisions` holds one immutable snapshot per change, written inside the store so the WebUI and the tools get the same history as a batch. `update_case(base_revision=...)` refuses a stale base with `QaConflictError`; an update that changes no recorded field adds no revision.
4. **Batches.** `api_workflows` stages candidates and a checkpoint. Validation runs before any write; the apply then inserts cases, metadata and revisions in one `BEGIN IMMEDIATE` transaction and rolls the whole batch back on the first failure, recording `status = 'failed'` with the error. An `idempotency_key` returns the same workflow, and applying an already applied workflow returns its stored result unchanged.
5. **Export.** `export_cases` reads every case in scope and returns `total`; the paged listing keeps its 500-row cap because that is a page size, not an export.

Version 3 adds tables only, so `_migrate` bumps `PRAGMA user_version` and a version-2 database keeps its rows; new tables arrive through `SCHEMA`, which runs before `_migrate`.

## Consequences

- A case can be traced to an operation, a scenario key and the batch that wrote it, and an edit made anywhere leaves a revision.
- Re-ingesting unchanged material is free, and a material update reports added, changed and missing operations before touching anything.
- Cases without a reference material still work: metadata and evidence are optional, so manual and imported cases keep their current behaviour.
- The WebUI does not read the new tables yet; the export payload only gained `total`, which existing clients ignore.
- Every case write is now transactional, so a failed revision insert no longer leaves a case body without its history.
- A future schema change that alters existing columns must write a real migration step; version 3 relies on SCHEMA having created its tables first.

## Alternatives rejected

- **Store provenance as columns on `cases`.** The `case.api` contract is public, and a Json column per concern would still need its own history and uniqueness rules; the tables keep the case body untouched.
- **Keep the 500 cap and flag truncation.** It tells the caller data is missing without providing the data, so a migrate-and-verify workflow could not rely on an export.
- **Delete operations that vanished from the material.** Existing cases and runs reference them; `missing` preserves the trail, and a later ingest that restores the endpoint reactivates it.
- **One transaction per candidate.** Two failures then leave a half-applied batch that must be undone by hand, which is exactly the state the workflow checkpoint exists to avoid.
- **Sync the batch result back into Markdown.** Markdown stays a presentation layer; the store is the source of truth, and a reverse parse would create a second execution input.
