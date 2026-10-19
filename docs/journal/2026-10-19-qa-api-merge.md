# 2026-10-19 qa-merge

- Goal: land the API testing branch on `main` and measure what merging the parallel schedule branch would cost.
- Changed: this note only; the branch carries merge commit `7326e96` (main + `feat/qa-api-testing`).
- Verified: `.venv/bin/python -m pytest tests/qa -q -p no:qa_trace` -> 160 passed in 38.38s on `merge/qa-api-testing`; `.venv/bin/python -m ruff check nanobot/qa tests/qa` -> All checks passed. Union probe (main + api testing + schedules) -> 226 passed in 42.64s after resolving the conflicts listed below; the probe branch was discarded, not committed.
- Not done: deploying. `/opt/qa-agent` is detached at `d7714fd` on `feat/qa-workbench-polish`, the service is running from there, and nothing was restarted.
- Affects other sessions: the schedule branch must fix two things before it can merge cleanly, and one of them is its own hygiene.
- Next step: the schedule session restores line endings and resolves the two WebUI test files, then merges.

## Merge 1: `feat/qa-api-testing` into `main`

Clean, no conflicts. `git worktree add /opt/worktrees/qa-merge -b merge/qa-api-testing main` then `git merge --no-ff feat/qa-api-testing`. The gate above ran on that tree.

## Merge 2: `feat/qa-workbench-polish` (schedule branch)

Measured with `git merge --no-commit --no-ff feat/qa-workbench-polish`. Three conflicts:

- `nanobot/qa/store.py`
- `webui/src/tests/app-layout.test.tsx`
- `webui/src/tests/temporary-chat-navigation.test.tsx`

The schedule branch also converts about 1850 files from CRLF to LF. `git diff --ignore-cr-at-eol --stat edd907b feat/qa-workbench-polish` shrinks from 2082 files / 595970 insertions to 230 files / 30075 insertions, and a sample file shows 2273 CR characters on `main` and 0 after the merge. Per `docs/COLLABORATION.md`, that whole-file churn must be fixed on the schedule branch before merging (`git checkout main -- <paths that only differ in endings>`), otherwise the merge commit rewrites endings for most of the tree.

### store.py resolution that passed the gate

Four hunks, all additive, resolved as a union:

1. Imports: `collections.abc Iterable, Mapping`, `contextlib contextmanager`, `pathlib`, `typing Any, Iterator`, `nanobot.qa.catalog`, `nanobot.qa.schedule_time`, `sha256_json`.
2. The v3 comment: keep the schedule branch's note and add that the `api_*` tables come from the same `SCHEMA` script and need no data rewrite.
3. Module constants: keep the `_JSON_OPERATION_FIELDS` / `_CASE_COLUMNS` / `_INSERT_CASE_SQL` / `_UPDATE_CASE_SQL` block and `_SCHEDULE_UPDATE_FIELDS`.
4. `_migrate`: keep the `if version < 3:` branch that adds `derived`, `legacy_id`, `yaml_path` and calls `_drop_case_code_constraint()`, then note that the API asset tables come from `SCHEMA`.

Both sides' tests passed on the union, including `test_schedules`, `test_case_files`, `test_trace_api` and the whole API testing suite, so the two feature sets coexist in one store. The two WebUI test conflicts were resolved by taking the schedule branch's content in the probe; that is not the right final resolution, because `main` also changed `app-layout.test.tsx` to retarget the blank-start assertions, so the WebUI owner must merge both intents.

### Why this is not a version bump

Both branches call their additive change version 3. Neither `_migrate` needs DDL for the API tables, and the schedule branch's v3 branch only adds columns, so a database already at 3 gains whichever structures it lacks on open. ADR 0007 records this; the merge needs a gate run, not a renumber.
