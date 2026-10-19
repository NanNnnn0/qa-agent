# 2026-10-18 webui-empty-state

- Goal: settle the seven WebUI failures and get the full suite into the gate.
- Changed: `app-layout.test.tsx` and `temporary-chat-navigation.test.tsx` retargeted from the removed hero greeting to `workbench-pane-new-topic`; `HERO_GREETING_PATTERN` deleted with its last user; the sidebar `Temporary chat` waits now pass an explicit 5s timeout; `.github/workflows/fork-gate.yml` runs `npm test` instead of the QA-only subset; `docs/STATUS.md`, `docs/ROADMAP.md`, `CHANGELOG.md`.
- Verified: `npm test` in `webui/` reports 163 files and 2797 tests passed, twice in a row, in about 170s each run.
- Root cause, for the record: this was test/UI drift, not timing. The blank start page now renders `PaneWorkbench`, and two settings/apps entry points no longer expose `Back to chat` when no chat is mounted. Two hypotheses were disproved on the way: a Testing Library timeout bump (1s to 5s) and a boot-readiness helper; neither changed the failure set, because one assertion already waited ten seconds.
- Not done: nothing outstanding for the gate. `feat/qa-trace` is captured on its own branch by the owner's request and is not merged.
- Affects other sessions: the webui job is now the full suite and takes roughly three to four minutes in CI. A red run there is a real regression, not a known-failure set.
- Next step: merge `feat/qa-trace` when the owner is ready, then let CI gate it.
