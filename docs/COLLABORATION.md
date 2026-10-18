# Parallel sessions on qa-agent

Several agent sessions work on this repository at the same time, each with its own conversation, model context and owner. This page is the contract that keeps them from silently destroying each other's work. Read it before your first edit; where it conflicts with a habit from another project, this page wins.

## Why the rules exist

`/opt/qa-agent` is a single directory that a systemd unit runs from. Two sessions editing it at once do not merge: the later write wins and the earlier change disappears without a diff, a conflict, or a warning. The repository therefore separates *where work happens* from *what runs*: sessions write in their own worktree, and only merged commits reach the deployment checkout.

## One session, one branch, one worktree, one task

| Location | Branch | Written by | Purpose |
|---|---|---|---|
| `/opt/qa-agent` | `main` | merge only | deployment checkout; the systemd unit runs from here |
| `/opt/worktrees/<slug>` | `feat/*`, `fix/*`, `docs/*`, `chore/*` | exactly one session | all edits, tests and commits |
| `/root/qa-agent-deploy.tar.gz` | - | nobody | frozen backup of the pre-git tree |

Start a session:

```bash
cd /opt/qa-agent
git fetch --all
git worktree add /opt/worktrees/<slug> -b <type>/<topic> origin/main
cd /opt/worktrees/<slug>
```

`<slug>` names the session, not the feature (`docs-skeleton`, `qa-runner`). Two sessions never share a slug, and two sessions never share a branch.

## Session lifecycle

1. **Claim.** State the scope in one sentence and name the paths you will touch. If another session's handoff note or open branch already covers those paths, stop and coordinate instead of starting.
2. **Read the contract.** `AGENTS.md` routes you to the `.agent/` page for your area. Do not read the whole tree; the routing table exists to avoid that.
3. **Work small.** One concern per commit, committed before switching context, so a crashed session loses at most one commit.
4. **Verify.** Run the merge gate below and record the exact commands with their outcome in the handoff note. An unverified claim is a defect handed to the next session.
5. **Hand off.** Write `docs/journal/<YYYY-MM-DD>-<slug>.md` and commit it with the work.
6. **Merge.** From `/opt/qa-agent`: `git merge --no-ff <branch>`, rerun the gate on `main`, restart the service, verify, then `git worktree remove /opt/worktrees/<slug>`.

## Ownership boundaries

`AGENTS.md` maps areas to files. Within one wave of parallel work, no two sessions own the same file; split by area, never by line:

| Area | Owner path prefix |
|---|---|
| QA domain logic | `nanobot/qa/` |
| QA tools, roles, dispatch | `nanobot/agent/tools/qa.py`, `nanobot/qa/roles.py`, `nanobot/agent/subagent.py` |
| QA WebUI | `webui/src/components/qa/`, `webui/src/lib/qa-api.ts` |
| QA skills | `nanobot/skills/qa-*` |
| Docs and collaboration rules | `docs/`, `.agent/`, `AGENTS.md` |

A task that needs an edit outside your prefix either hands that part to the owning session or gets explicit agreement first, recorded in the handoff note.

## Interface contracts

These are public and cannot be changed by one session alone:

- the structured `case.api` contract (`request` plus typed `assertions`);
- the WebSocket mutation channel (`qa.*` actions);
- dispatch prompts and completion contracts in `nanobot/qa/roles.py`;
- the `NANOBOT_QA_DB` override and the default `<config-dir>/qa/qa.sqlite3` location.

Changing one means: write an ADR under `docs/adr/`, say so in the handoff note under "Affects other sessions", and expect other sessions to rebase before their next commit.

## Merge gate

Run from the worktree, on the branch being merged:

```bash
.venv/bin/python -m pytest tests/qa -q          # QA domain
.venv/bin/python -m pytest -q                   # full suite when shared code changed
.venv/bin/python -m ruff check nanobot/qa       # lint; never run `ruff format`
cd webui && npm test                            # when webui/ changed
```

A red gate blocks the merge. Environment failures are recorded as `blocked_by_env`, never reported as product defects. Do not merge on "it passed earlier" without the reasoning in `.agent/workflow.md`.

The gate needs `pytest-asyncio` and `ruff` in `.venv`; both were installed on 2026-10-18 and `tests/qa` has been green since (see `STATUS.md`). A checkout without them reports every async test as a failure, which is an environment problem, not a code problem.

## Handoff note

Path: `docs/journal/<YYYY-MM-DD>-<slug>.md`, committed with the work.

```markdown
# 2026-10-18 docs-skeleton

- Goal: bootstrap collaboration docs and the git baseline
- Changed: `docs/COLLABORATION.md`, `docs/deploy.md`, `CHANGELOG.md` (+N lines)
- Verified: `pytest tests/qa` -> 57 passed, 26 blocked_by_env; `ruff` unavailable
- Not done: `docs/ROADMAP.md` milestones need product input
- Affects other sessions: none
- Next step: install the missing dev test plugins, then split coverage gaps
```

"Affects other sessions" is the line that prevents duplicated or conflicting work. Write it even when the answer is "none".

## Deploying

See [`deploy.md`](deploy.md). A deploy is a merge into `main` followed by `systemctl restart qa-agent`, nothing else. Never edit `/opt/qa-agent` directly and never restart the service from a worktree.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Your edit vanished | another session wrote the same file in the deployment checkout | stop editing `/opt/qa-agent`; redo the change in a worktree |
| `git worktree add` says the branch is already checked out | that branch is live in another worktree | pick another branch, or `git worktree list` and coordinate |
| The service runs old code after a merge | not restarted; the install is editable, so restart *is* the deploy | `systemctl restart qa-agent` |
| Docs contradict the code | the change skipped its handoff note | fix the doc in the commit that fixes the code |
| Two sessions want the same file with different intent | missing ownership split | record the split in `docs/journal/` and in an ADR |
