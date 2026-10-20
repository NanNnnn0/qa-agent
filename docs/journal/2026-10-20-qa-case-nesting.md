# 2026-10-20 qa-case-nesting

- Goal: make the case library legible without building a full hierarchy - nest each project's API cases under its catalog endpoint, in the assets tab.
- Changed: `webui/src/components/qa/QaApiAssets.tsx` (case count column, expandable endpoint rows, nested case list, case drawer), `webui/src/tests/qa-api-assets.test.tsx` (8 tests), `docs/adr/0011-nest-cases-under-endpoints.md`, `docs/STATUS.md`.
- Verified:
  - `./node_modules/.bin/tsc -p tsconfig.build.json --noEmit` -> clean.
  - `./node_modules/.bin/vitest run qa-api-assets` -> 8 passed; `vitest run qa-` -> 39 passed in 8.51s (5 files).
  - Live grouping check against the deployed database: `CHEYICHA-API` (proj_2ff6a80eeb8f) -> `POST /api/auth/register` gets 20 cases; `TRY` (proj_7468e0fb401e) -> `GET /` gets 2; no unmatched cases. That is the data from the operator's screenshot, where every case showed a missing source because `qa_case` created it without a catalog link.
- Deployment: merged `feat/qa-case-nesting` into `main` as `3fd21f9` (4 files, no conflicts). `cd webui && npm run build` -> built in 25.62s; `systemctl restart qa-agent` -> active, `/` 200, `/health` 200; the new view is in `assets/QaWorkbench-DnPotEiU.js`.
- Follow-up (same slice, `7c20a80`): the expanded panel became a table with the case library's columns minus chain and tags (code, title, kind, priority, status), using the shared `QaPriorityBadge` / `QaCaseStatusBadge` so a case reads the same in both places, and the endpoint drawer stopped repeating the case list. Rebuilt (26.23s), restarted, `/` and `/health` 200, view in `assets/QaWorkbench-QgRm2N86.js`. Gate: `tsc` clean, `vitest run qa-` -> 40 passed.
- Not done: cases still carry no `operation_id` when written through `qa_case`, so the nesting is a path heuristic; the case library itself is still one flat table. `main` is ahead of `origin/main` and still not pushed.
- Affects other sessions: the assets tab now also reads `GET /api/qa/cases` (limit 500) on every filter change. Anyone adding a case field to that route changes this view too.
- Next step: write `operation_id` on every API case (including `qa_case` creates) and give the case library its own grouping; that turns the heuristic into a stored link (ADR 0011).
