# Roadmap

Milestones are ordered, not dated. A milestone ships when its exit condition is true, not when the calendar says so. Anything not listed here is not planned, and a session should not start unlisted work without adding it first.

## M0 - Collaboration baseline

Exit condition: two sessions can work at the same time without overwriting each other, and a bad change can be rolled back.

- [x] Git repository with a baseline commit of the deployed tree (2026-10-18)
- [x] `docs/COLLABORATION.md`: worktree, ownership, handoff and merge rules
- [x] `docs/deploy.md`: how code reaches the running service, and how to roll back
- [x] `docs/STATUS.md`: what actually works today
- [x] Private remote repository, so history survives the host (`NanNnnn0/qa-agent`, pushed 2026-10-18)
- [x] One rehearsal: two worktrees, two branches, one merge, one restart (2026-10-18, `docs/m0-rehearsal` and `docs/m0-rehearsal-b`)

## M1 - Make the merge gate runnable

Exit condition: the commands in `COLLABORATION.md` run green on a clean checkout, and CI runs them on every push.

- [x] Install the test tooling the gate needs into `.venv` (`pytest-asyncio`, `ruff`; optionally `pytest-cov`, `pytest-xdist`)
- [x] Get `pytest tests/qa` green, or record each remaining failure as a real defect (83 passed, 2026-10-18)
- [x] Add `.github/workflows/fork-gate.yml` (Python gate plus the QA workbench suite) and disable the inherited upstream suite
- [x] Confirm the gate runs green on `main` (2026-10-18, runs 39128233554 and 39128813135)
- [x] Pin the runner to `ubuntu-24.04` and apply the same documentation-only filter to push and pull request
- [x] Add `scripts/hooks/pre-push` so the gate runs locally before a push
- [ ] Fix the five WebUI failures in `app-layout.test.tsx` and `temporary-chat-navigation.test.tsx` with a boot-aware readiness helper, then gate the full suite

## M2 - Documentation truth pass

Exit condition: a new session can answer "what is this, what works, what is next" from `docs/` alone, in one read.

- [ ] Audit `docs/qa-agent.md` against the current code and fix drift
- [ ] Decide the language policy for fork-owned docs (currently English, matching upstream)
- [ ] Add a one-page Chinese quickstart for the owner if the English pages stay canonical
- [ ] Fold the four `docs/research/` files into a single "what we learned" page with sources

## M3 - QA platform product work

Exit condition: set by the owner. This section is intentionally empty until the owner writes it; sessions must not invent product scope.

Candidate items observed in the code and design contract, unconfirmed:

- [ ] Add an assertion type end to end (`validation.py`, `runner.py`, `qa-api-testing` skill, WebUI editor)
- [ ] Separate `blocked_by_env` from product defects in run reports
- [ ] Cover `nanobot/qa/` beyond the current `tests/qa` set

## M4 - Multi-session orchestration

Exit condition: three sessions work in parallel for a week with no lost change and no duplicated work.

- [ ] Adopt a task card per session (DSH task board, or GitHub Issues once the remote exists)
- [ ] Evaluate `automazeio/ccpm` (issues + worktrees) and `github/spec-kit` (spec-first) against the rules in `COLLABORATION.md`; adopt only what the rules lack
- [ ] Decide whether QA skills ship as nanobot skills (current) or as portable `SKILL.md` bundles
