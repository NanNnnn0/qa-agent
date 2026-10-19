# Working on nanobot

The Python gateway owns agent execution, sessions, tools, memory, and security policy. WebUI and TUI share that runtime; keep execution and policy out of the clients.

## QA Agent (this fork)

This fork adds a test-work platform on top of nanobot. Product docs: [`docs/qa-agent.md`](docs/qa-agent.md); design contract: [`docs/design/qa-platform.md`](docs/design/qa-platform.md); WebUI integration brief: [`docs/design/qa-webui-brief.md`](docs/design/qa-webui-brief.md); competitor/tool research: [`docs/research/`](docs/research/).

| Area | Files |
| --- | --- |
| QA persistence, validation, execution | `nanobot/qa/store.py`, `nanobot/qa/validation.py`, `nanobot/qa/runner.py`, `nanobot/qa/service.py` |
| `/api/qa/*` routes + WebSocket mutation mapping | `nanobot/qa/http.py` (merged into `nanobot/webui/ws_http.py`; corrections to that merge point only) |
| Model-facing tools and dispatch | `nanobot/agent/tools/qa.py`, `nanobot/qa/roles.py`, `nanobot/agent/subagent.py` (`spawn_task`) |
| Skills that pin output shape | `nanobot/skills/qa-orchestrator`, `qa-api-testing`, `qa-functional-testing`, `qa-automation`, `qa-report` |
| MCP server, demo fixtures, CLI | `nanobot/qa/mcp_server.py`, `nanobot/qa/seed.py`, `nanobot/qa/demo_server.py`, `nanobot/cli/qa.py` |
| QA workbench | `webui/src/components/qa/`, `webui/src/lib/qa-api.ts` |
| Tests | `tests/qa/` (Python), `webui/src/tests/qa-*.test.tsx` |

Rules for changing the QA layer:

- The structured `case.api` contract (`request` + typed `assertions`) is public API. Adding an assertion type means updating `validation.py`, `runner.py`, the `qa-api-testing` skill and the WebUI case editor together.
- Writes must stay on the WebSocket mutation channel (`qa.*` actions in `nanobot/qa/http.py`); never add an HTTP POST/Q&A route that mutates state.
- Distinguish product failures from `blocked_by_env`; never count environment failures as defects.
- Dispatch prompts and completion contracts live in `roles.py`; do not inline role text in tools or skills.
- QA database defaults to `<config-dir>/qa/qa.sqlite3`; `NANOBOT_QA_DB` overrides it (tests and demos rely on this).

## Task-specific guidance

| When working on | Read |
| --- | --- |
| Core boundaries, extensions, or internal types | [`.agent/design.md`](.agent/design.md) |
| Refactoring, fallbacks, or test selection | [`.agent/simplify.md`](.agent/simplify.md) |
| User-facing copy, feature naming, or localization | [`.agent/copywriting.md`](.agent/copywriting.md) |
| Path permissions, HTTP/MCP, or shell isolation | [`.agent/security.md`](.agent/security.md) |
| Dependency setup, WebUI transport, config, Windows, prompts, or persistence | [`.agent/gotchas.md`](.agent/gotchas.md) |
| Reusing verification evidence | [`.agent/workflow.md`](.agent/workflow.md) |
| WebUI/host compatibility | [`.agent/review-guide.md`](.agent/review-guide.md) |
| Contribution or publication | [`CONTRIBUTING.md`](CONTRIBUTING.md), [`docs/releasing.md`](docs/releasing.md) |

## Development constraints

- Analyze the required behavior, state ownership, and root cause before extending existing code. Refactor when the structure causes the problem; a smaller diff does not justify another fallback.
- Do not add defensive tests for hypothetical internal states or unsupported combinations. Each new test needs a reachable path and a meaningful contract to protect.
- Do not run `ruff format`; mechanical formatting obscures git blame and creates unrelated diffs. This constraint takes precedence over the optional touched-file formatting in `CONTRIBUTING.md`.
- Do not manually wrap prose in Markdown files. Keep each paragraph on one source line; use line breaks only for Markdown structure.
