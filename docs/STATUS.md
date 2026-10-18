# Status

Verified on 2026-10-18 against the deployment host. This page answers "what works right now"; it is not a plan (see `ROADMAP.md`) and not a changelog (see `CHANGELOG.md`). Update it in the same commit that makes a fact here stop being true.

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
| QA tests | `.venv/bin/python -m pytest tests/qa -q` | 83 passed in 8.59s (2026-10-18) |
| Lint | `.venv/bin/python -m ruff check nanobot/qa` | All checks passed |
| QA workbench tests | `cd webui && npx vitest run qa-` | 8 passed (2026-10-18) |
| Full WebUI suite | `cd webui && npm test` | 2792 passed, 5 failed; known, see Known gaps |
| Full suite | `.venv/bin/python -m pytest -q` | never run on this host |

`pytest-asyncio` and `ruff` were missing from `.venv` and were installed on 2026-10-18. Before that, 26 async tests failed with `async def functions are not natively supported` and `ruff` did not exist. Both were missing dev dependencies, not product defects. A new checkout needs them before the gate means anything.

## What exists

- QA domain: `nanobot/qa/` (about 3.0k lines: `store`, `validation`, `runner`, `service`, `http`, `roles`, `seed`, `mcp_server`, `demo_server`).
- HTTP and WebSocket surface: `/api/qa/*` routes plus `qa.*` mutation actions on the WebSocket channel.
- Model-facing tools and skills: `nanobot/agent/tools/qa.py`, `spawn_task` in `nanobot/agent/subagent.py`, five `qa-*` skills.
- QA workbench: `webui/src/components/qa/` and `webui/src/lib/qa-api.ts` (71 TS/TSX files including the API client).
- Tests: `tests/qa/` (11 files) and `webui/src/tests/qa-*.test.tsx`.
- Docs: `docs/qa-agent.md`, `docs/design/qa-platform.md`, `docs/design/qa-webui-brief.md`, `docs/research/` (4 files), plus the inherited upstream pages under `docs/`.

## Known gaps

- CI runs `.github/workflows/fork-gate.yml` on pushes to `main` and on pull requests, with the same documentation-only filter on both events: the Python gate (`ruff check nanobot/qa`, `pytest tests/qa`) and the QA workbench WebUI suite, both on `ubuntu-24.04`. The inherited upstream `ci.yml` is disabled manually; re-enable it only for changes that touch Docker, the TUI or the whole WebUI.
- The full WebUI suite has seven failures unrelated to QA and is not gated. They are test/UI drift, not flakes: `app-layout.test.tsx` asserts the hero greeting on the blank start page, while the current composition renders `PaneWorkbench` (`data-testid="pane-grid"`, `workbench-pane-new-topic`). One of those assertions already waits ten seconds and still fails, so more waiting cannot close the gap.
- A separate race does exist in the same file: `App.tsx` returns `StartupShell` while `state.status === "loading"`, and a test that queries right after `waitFor(() => expect(connectSpy).toHaveBeenCalled())` can run against the shell. It was observed once in the toggle-theme assertion; it is not the cause of the recurring seven.
- Reproduce: `cd webui && DEBUG_PRINT_LIMIT=200000 npx vitest run src/tests/app-layout.test.tsx -t "opens a blank start page without creating an empty chat"`.
- Fix direction: decide whether the blank-start composition is intended, then either update those assertions to the workbench contract or fix the composition; only after that should the full suite enter the gate.
- WebUI tests have never run on this host, so their state is unknown rather than green.
- `nanobot/web/dist` and `.venv` are not tracked by git; a fresh clone is not a working deployment until both are rebuilt (see `deploy.md`).
- There is no history before 2026-10-18: the tree was deployed as a tarball and captured as a single baseline commit.
- The checkout is mode 777, so any local process can write it.

## Environment dependencies

- Python 3.12.3, `nanobot_ai` 0.3.5 installed editable in `/opt/qa-agent/.venv`.
- Config `/root/.nanobot/config.json`; QA database `/root/.nanobot/qa/qa.sqlite3`, overridable with `NANOBOT_QA_DB`.
- Host `206.187.213.212` (Ubuntu 24.04, 6 vCPU / 8 GB), SSH alias `hk-206`.
