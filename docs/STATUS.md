# Status

Verified on 2026-10-18 against the deployment host. This page answers "what works right now"; it is not a plan (see `ROADMAP.md`) and not a changelog (see `CHANGELOG.md`). Update it in the same commit that makes a fact here stop being true.

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
| WebUI tests | `cd webui && npm test` | never run on this host |
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

- No CI on this fork's remote yet. `.github/workflows/ci.yml` is inherited from upstream and has never run against this tree.
- WebUI tests have never run on this host, so their state is unknown rather than green.
- `nanobot/web/dist` and `.venv` are not tracked by git; a fresh clone is not a working deployment until both are rebuilt (see `deploy.md`).
- There is no history before 2026-10-18: the tree was deployed as a tarball and captured as a single baseline commit.
- The checkout is mode 777, so any local process can write it.

## Environment dependencies

- Python 3.12.3, `nanobot_ai` 0.3.5 installed editable in `/opt/qa-agent/.venv`.
- Config `/root/.nanobot/config.json`; QA database `/root/.nanobot/qa/qa.sqlite3`, overridable with `NANOBOT_QA_DB`.
- Host `206.187.213.212` (Ubuntu 24.04, 6 vCPU / 8 GB), SSH alias `hk-206`.
