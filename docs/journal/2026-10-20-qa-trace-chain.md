# 2026-10-20 qa-trace-chain

- Goal: make the trace chain writable from the agent and require it for an executable case, so the chain badges stop reading "no source / no test point".
- Changed: `nanobot/qa/testpoints.py` (new service), `nanobot/agent/tools/qa_testpoint.py` (new tool), `nanobot/agent/tools/qa.py` (`testpoints`/`sources`/`direct_reason`/`risk` + the ready rule), `nanobot/qa/http.py` (`GET /api/qa/testpoints`, the ready rule on create/update), both QA skills, `webui/src/components/qa/QaTestpoints.tsx` (new tab), `webui/src/lib/qa-api.ts`, `QaWorkbench.tsx`, `tests/qa/test_trace_chain.py` (7 tests), `tests/qa/conftest.py` (`qa_chain` fixture), ADR 0012, STATUS.
- Verified:
  - `pytest tests/qa -q` -> 255 passed in 52.54s; `ruff check` clean.
  - `vitest run qa-` -> 44 passed; `tsc -p tsconfig.build.json --noEmit` clean.
  - Chain semantics pinned by tests: a source draft lands in `draft/agent`; a test point refuses a draft source ("still a draft"); an approved chain accepts a ready case; a ready case without a link is refused with the exact next step; a draft case may stay unlinked and be `attach`ed later; a direct source link needs `direct_reason`; `list` reports drafts and unlinked cases.
  - Deployment: merged as `690ec35`, 255 passed on the checkout, ruff clean, `npm run build` 26.02s, restart -> active, `/` 200, `/health` 200, startup registers **32 tools** (was 31) including `qa_testpoint`.
- Migration (run on the live database, read-only on SQLite):
  - `python -m qa_trace trace migrate-sqlite --db /root/.nanobot/qa/qa.sqlite3 --root /opt/qa-agent/qa-workbench/projects --project CHEYICHA-API` -> 20 cases -> 20 drafts, 0 formal, 0 skipped, 0 errors.
  - After reindex the library still lists 20 cases (no duplicates), each now YAML-backed at `draft/sqlite-migration/cases/TC-CHEYICHA_API-0NN.yaml`.
  - `qa_testpoint` view of that project: 0 sources, 0 test points, 20 drafts, 20 unlinked cases.
  - Undo: `rm -rf /opt/qa-agent/qa-workbench/projects/cheyicha-api` (the SQLite rows are untouched; the migration never writes the database).
- Not done: no source or test point has been approved for CHEYICHA-API yet, so the chain is still empty; the case library badge shows a case's direct `sources` only, so a case linked through a test point still reads "no source" until the badge computes it transitively; the `api` role prompt still names tools a subagent does not have (ADR 0010); `main` is still ahead of `origin/main`.
- Affects other sessions: the ready-link rule changes the contract of `qa.case.create`/`qa.case.update` and of the `qa_case` tool - an unlinked `status=ready` write now fails. `tests/qa/conftest.py` gained the `qa_chain` fixture for tests that need an executable case.
- Next step: approve a source and a test point for CHEYICHA-API (workbench test points tab or `qa trace review approve`), attach the migrated cases with `qa_testpoint action=attach`, then compute the chain badges transitively.
