# Session journal

One file per working session: `YYYY-MM-DD-<slug>.md`, where `<slug>` matches the worktree name. The note is written by the session that did the work, committed with that work, and never rewritten afterwards by anyone else.

The journal exists because a session's context is lost when the conversation ends, while the repository is not. The next session reads the last few notes to learn what is in flight, what was tried and rejected, and which files are already claimed.

## Rules

- Append a new file per session; do not edit another session's note.
- Fill every field, including "Affects other sessions" when the answer is "none".
- Record the verification commands and their outcome verbatim. "Tests pass" without the command is not evidence.
- Keep it short: the diff carries the detail, the note carries the intent.

## Template

```markdown
# YYYY-MM-DD <slug>

- Goal: one sentence, the outcome this session was asked for
- Changed: files and rough line counts
- Verified: exact commands and results
- Not done: what was deliberately left out, and why
- Affects other sessions: none, or the contract that moved and what to rebase
- Next step: the single most useful thing to do next
```

## Index

Notes are listed newest first. Update this table in the same commit that adds a note.

| Date | Slug | Summary |
|---|---|---|
| 2026-10-19 | [qa-api-merge](2026-10-19-qa-api-merge.md) | API testing branch merged into main and gated; schedule branch merge measured, store union resolution recorded |
| 2026-10-19 | [qa-api-flow](2026-10-19-qa-api-flow.md) | API asset schema v3, catalog ingestion, case revisions, transactional batches, complete export; ADR 0002 |
| 2026-10-18 | [webui-empty-state](2026-10-18-webui-empty-state.md) | Blank-start assertions retargeted to the workbench pane; full WebUI suite gated |
| 2026-10-18 | [gate-hardening](2026-10-18-gate-hardening.md) | Runner pinned, event filters unified, pre-push hook; WebUI failure root cause; qa-trace work found uncommitted |
| 2026-10-18 | [ci-gate](2026-10-18-ci-gate.md) | CI gate wired to the remote; upstream suite disabled; WebUI QA suite gated |
| 2026-10-18 | [docs-skeleton](2026-10-18-docs-skeleton.md) | Git baseline, collaboration contract, deploy and status docs |
