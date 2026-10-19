# Status

Verified on 2026-10-18 against the deployment host. This page answers "what works right now"; it is not a plan (see `ROADMAP.md`) and not a changelog (see `CHANGELOG.md`). Update it in the same commit that makes a fact here stop being true.

The QA test row and the API asset layer were re-verified on 2026-10-19 in worktree `/opt/worktrees/qa-api-flow` (branch `feat/qa-api-testing`, based on `origin/main`); the deployment checkout itself still runs `feat/qa-trace`.

## Version control

- History lives in the private remote `NanNnnn0/qa-agent`; `main` tracks `origin/main`.
- The host authenticates with a repository-scoped deploy key at `/root/.ssh/github-qa-agent`, registered with write access; `/root/.ssh/config` pins it to `github.com`.
- Sessions work in `/opt/worktrees/<slug>` and merge into `/opt/qa-agent`; see `COLLABORATION.md`.

## Running service

- `qa-agent.service` is `active (running)`, started 2026-10-18 12:17 UTC, about 123 MB RSS.
- The gateway listens on `127.0.0.1:8765` (WebUI and `/api/*`) and `127.0.0.1:18790` (`gateway.port` in `config.json`).
- nginx on 8443 proxies to 8765 with basic auth on `/` (exempt on `/api/`) and a 3600s read timeout.
- The WebUI answers 200; its built assets live in `nanobot/web/dist`, which git ignores.

## Verification status

| Check | Command | Result |
|---|---|---|
| QA tests | `.venv/bin/python -m pytest tests/qa -q` | 160 passed in 37.42s (2026-10-19, `feat/qa-api-testing`) |
| Lint | `.venv/bin/python -m ruff check nanobot/qa` | All checks passed |
| QA workbench tests | `cd webui && npx vitest run qa-` | 8 passed (2026-10-18) |
| Full WebUI suite | `cd webui && npm test` | 2797 passed in 170s, twice in a row (2026-10-18) |

CI wall clock on 2026-10-18 with both jobs running: Python gate 46s, WebUI gate 7m57s. The same WebUI suite takes 170s on this 6-vCPU host, so budget roughly three times the local run for CI; the webui job is capped at 15 minutes.
| Full suite | `.venv/bin/python -m pytest -q` | never run on this host |

`pytest-asyncio` and `ruff` were missing from `.venv` and were installed on 2026-10-18. Before that, 26 async tests failed with `async def functions are not natively supported` and `ruff` did not exist. Both were missing dev dependencies, not product defects. A new checkout needs them before the gate means anything.

## What exists

- QA domain: `nanobot/qa/` (about 3.9k lines: `store`, `catalog`, `validation`, `runner`, `service`, `http`, `roles`, `seed`, `mcp_server`, `demo_server`).
- API asset layer (schema version 3): `api_operations` catalog, `api_case_metadata`, `api_case_revisions` and `api_workflows` in the same SQLite database. Every case write records a revision, catalog re-ingestion is idempotent and marks dropped endpoints `missing` instead of deleting them, and a candidate batch applies in one transaction. `export_cases` returns every case in scope plus `total`; the paged listing keeps its 500-row page cap.
- HTTP and WebSocket surface: `/api/qa/*` routes plus `qa.*` mutation actions on the WebSocket channel.
- Model-facing tools and skills: `nanobot/agent/tools/qa.py`, `spawn_task` in `nanobot/agent/subagent.py`, five `qa-*` skills; `nanobot/skills/qa-api-testing/SKILL.md` now leads with catalog ingestion and a staged batch.
- MCP API asset tools: `qa_api_catalog` (ingest/list/get/diff), `qa_api_workflow` (create/get/validate/submit/apply/resume/export) and `qa_api_run` (preflight/start/get) in `nanobot/qa/api_tools.py`, registered in the stdio MCP server. Local OpenAPI files are only read under `NANOBOT_QA_SPEC_ROOTS`.
- Pinned API runs: `nanobot/qa/execution.py` gates a run with preflight, executes ready cases through the fixed `nanobot/qa/templates/case_template.py` in a subprocess, pins each case revision in the run report, batches above 200 cases, masks credentials (bearer or JSON login, `env:NAME` references) and classifies every failure. `api.extract` plus `{{run.<name>}}` chains values between cases; a failed login persists a run with `classification: auth_failed`.
- Ordered run plans: `plan={version, setup, cases, cleanup}` with `{case_id, revision?}` steps. Setup runs first, a failed setup step marks the cases phase `dependency_blocked`, cleanup always runs, and a cleanup failure is classified `cleanup_failed`. A pinned revision must match the case's current revision, and the run report records the plan with resolved revisions.
- Background runs: `qa_api_run start` returns a `running` row and executes on `nanobot/qa/scheduler.py`, which serializes runs per project and lets different projects proceed in parallel. `get` polls; `wait=true` blocks. A gateway restart leaves a `running` row as evidence instead of rewriting it.
- QA workbench: `webui/src/components/qa/` and `webui/src/lib/qa-api.ts` (71 TS/TSX files including the API client).
- Tests: `tests/qa/` (15 files) and `webui/src/tests/qa-*.test.tsx`.
- Docs: `docs/qa-agent.md`, `docs/design/qa-platform.md`, `docs/design/qa-webui-brief.md`, `docs/research/` (4 files), plus the inherited upstream pages under `docs/`.

## Known gaps

- CI runs `.github/workflows/fork-gate.yml` on pushes to `main` and on pull requests, with the same documentation-only filter on both events: the Python gate (`ruff check nanobot/qa`, `pytest tests/qa`) and the QA workbench WebUI suite, both on `ubuntu-24.04`. The inherited upstream `ci.yml` is disabled manually; re-enable it only for changes that touch Docker, the TUI or the whole WebUI.
- The blank start page no longer renders the hero greeting: it was removed in favour of the workbench pane, and the owner confirmed that is intended. Seven assertions in `app-layout.test.tsx` and `temporary-chat-navigation.test.tsx` still expected the greeting, and two of those expected a `Back to chat` control that settings and apps no longer render when no chat is mounted. They were retargeted to `workbench-pane-new-topic` and a boot wait on 2026-10-18.
- Do not reintroduce greeting assertions. `HERO_GREETING_PATTERN` was deleted with its last user, and the greeting component still exists only for the states that render it.
- `App.tsx` still returns `StartupShell` while `state.status === "loading"`, so a test that queries immediately after `waitFor(() => expect(connectSpy).toHaveBeenCalled())` can run against the shell. Where that matters, wait for boot or pass an explicit timeout instead of relying on the default 1s budget; the sidebar `Temporary chat` wait needed 5s to stop being the last flaky assertion.
- WebUI tests have never run on this host, so their state is unknown rather than green.
- `nanobot/web/dist` and `.venv` are not tracked by git; a fresh clone is not a working deployment until both are rebuilt (see `deploy.md`).
- There is no history before 2026-10-18: the tree was deployed as a tarball and captured as a single baseline commit.
- The checkout is mode 777, so any local process can write it.

## Environment dependencies

- Python 3.12.3, `nanobot_ai` 0.3.5 installed editable in `/opt/qa-agent/.venv`.
- Config `/root/.nanobot/config.json`; QA database `/root/.nanobot/qa/qa.sqlite3`, overridable with `NANOBOT_QA_DB`.
- Host `206.187.213.212` (Ubuntu 24.04, 6 vCPU / 8 GB), SSH alias `hk-206`.
