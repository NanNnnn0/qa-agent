# Changelog

All notable changes to this fork are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow the packaged `nanobot_ai` version while the fork has no independent release cadence.

History begins on 2026-10-18, when the deployed tree was placed under version control. Everything before that date exists only as code, without a record of intent.

## [Unreleased]

### Added

- `docs/COLLABORATION.md`: the multi-session contract (one session, one branch, one worktree; ownership boundaries; handoff notes; merge gate).
- `docs/deploy.md`: host facts, service unit, ports, the two artifacts git does not carry, deploy and rollback procedures.
- `docs/STATUS.md`: verified state of the deployment, including which checks cannot currently run.
- `docs/ROADMAP.md`: ordered milestones M0-M4 with exit conditions.
- `docs/adr/`: decision records, starting with ADR 0001.
- `docs/journal/`: per-session handoff notes and their template.
- Git repository with a baseline commit of the deployed tree, pushed to the private remote `NanNnnn0/qa-agent` with a write-scoped deploy key on the host.
- `.github/workflows/fork-gate.yml`: CI gate running `ruff check nanobot/qa`, `pytest tests/qa` and the QA workbench WebUI suite on every push and pull request. The inherited upstream `ci.yml` is disabled manually.
- `scripts/hooks/pre-push`: the same gate run locally before a push, installed with `git config core.hooksPath scripts/hooks`. Documentation-only pushes skip it.

### Changed

- `AGENTS.md`: routes sessions to the collaboration contract and the status page.
- `.venv`: installed `pytest-asyncio` and `ruff`, which the merge gate requires and the deployed environment lacked; `tests/qa` went from 26 environment failures to 83 passed.

### Fixed

- WebUI tests: seven assertions still expected the hero greeting on the blank start page, which was removed in favour of the workbench pane, and two expected a `Back to chat` control that settings and apps no longer render when no chat is mounted. They now assert `workbench-pane-new-topic` and wait for boot; the full WebUI suite (2797 tests) passes, and CI runs it instead of the QA-only subset.

## [0.3.5] - baseline

The deployed state captured on 2026-10-18: `nanobot_ai` 0.3.5 installed editable in `/opt/qa-agent/.venv`, served by `qa-agent.service` behind nginx on port 8443, with the QA work platform (`nanobot/qa/`, `/api/qa/*`, QA skills, QA workbench) present.
