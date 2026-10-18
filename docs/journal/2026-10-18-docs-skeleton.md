# 2026-10-18 docs-skeleton

- Goal: put the deployed tree under version control and give parallel sessions a written contract.
- Changed: new `docs/COLLABORATION.md`, `docs/deploy.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `docs/adr/README.md`, `docs/adr/0001-record-architecture-decisions.md`, `docs/journal/README.md`, `CHANGELOG.md`; edited the routing table in `AGENTS.md`.
- Verified: `.venv/bin/python -m pytest tests/qa -q` -> 83 passed in 8.59s; `.venv/bin/python -m ruff check nanobot/qa` -> all checks passed. Both required installing `pytest-asyncio` and `ruff` into `.venv` first; before that, 26 async tests failed and `ruff` was absent.
- Not done: private remote repository, CI wiring, `webui` tests on this host.
- Affects other sessions: new rule - edit only in `/opt/worktrees/<slug>`, never in `/opt/qa-agent`; changes to `case.api`, `qa.*` actions, or `roles.py` require an ADR and a note here.
- Next step: create the private remote, push `main`, then start M1 (CI on the fork remote).
