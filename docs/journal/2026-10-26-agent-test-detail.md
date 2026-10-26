# 2026-10-26 agent-test-detail

- Goal: expand the user's 20 planned Agent tests into executable prompts and reviewable expected traces without running their tests.
- Scope: this session continues ownership of the existing documentation worktree; adds `docs/learning/11-prompts-and-expected-traces.md`, updates navigation in `08-test-plan.md`, `09-execution-records.md`, `README.md`, and adds this journal.
- Changed: concrete prompts, placeholder setup table, required facts versus optional tool paths, expected parameters and result fields, final-response criteria and per-sample evidence checks. AT-014 now has a concrete read-only not-found tool error branch; its coverage is explicitly narrower than all recovery behavior.
- Implementation review: read deployment tool schemas and execution/runner code; documented project-global blockers versus case readiness, actual report detail limits, asynchronous completion, and environment classifications. Source behavior is not presented as verified model behavior.
- Verified: `git diff --check` and `git diff --cached --check` passed; a read-only Node documentation check resolved 54 local links, matched 20 ordered manual sample IDs, parsed 18 JSON parameter examples and confirmed all 20 execution-overview rows remain pending.
- Gate: documentation-only; Python/WebUI gates skipped under `docs/COLLABORATION.md`.
- Not done: business/model tests, user results, generated test suites, business code changes, deployment, merge or push.
- Affects other sessions: none; no deployment or existing business data changed.
- Next step: user fills actual IDs, sends each prompt, and records traces and conclusions in the matching execution record.
