# ADR 0002: Add QA schedule actions and a session QA project binding

- Status: accepted
- Date: 2026-10-19

## Context

The QA workbench (`webui/src/components/qa/`) reads `/api/qa/*` and mutates only through `qa.*` WebSocket actions. Two workbench requests cannot be implemented inside that contract:

1. **Choose a QA project in the main chat.** A chat turn reaches the agent as a plain message; neither the session record nor the inbound message carries a QA project. A frontend-only picker can only prepend text to every prompt (pollutes history, not machine-readable, the agent can ignore it) and the server cannot default list/dispatch calls to the chosen project.
2. **Schedule a run.** `runs.trigger` already accepts `"schedule"`, but nothing can create a schedule: there is no `qa.schedule.*` action, no schedule table, and no execution hook. The existing `cron` automation service is created exclusively by the agent's `cron` tool for a linked chat topic; it has no WebUI create action. A `setTimeout` in the browser stops when the workbench closes, which defeats the purpose of scheduling.

Both requests therefore need a new public contract. Per `AGENTS.md`, QA writes stay on the WebSocket mutation channel and `qa.*` actions are a public contract, so the change is recorded here before any backend or UI code is written.

## Decision

Extend the QA backend contract and WebSocket mutation channel as follows.

### Session QA project binding

- The existing session update mutation accepts an optional `qa_project_id` (must reference a known project, or `null` to clear it).
- Session reads return `qa_project_id`.
- The gateway injects `当前 QA 项目: <KEY> (<id>)` into the agent context for that session, and `/api/qa/*` calls from the WebUI may pass `project_id` derived from it.
- The chat composer renders a QA project picker for the active session; selecting a project writes the binding and the QA workbench opens on that project by default.

### QA schedules

New mutation actions:

| action | payload |
|---|---|
| `qa.schedule.create` | `{project_id, name, cron, timezone?, enabled?, target}` |
| `qa.schedule.update` | `{id, ...fields}` |
| `qa.schedule.delete` | `{id}` |
| `qa.schedule.run_now` | `{id}` |

`target` is one of:

- `{"kind": "script", "script_id": "scr_..."}`
- `{"kind": "cases", "case_ids": ["case_...", ...], "run_kind": "api" | "ui" | "manual" | null}`

Read: `GET /api/qa/schedules?project_id=` returns `{items: [schedule]}` where

```ts
type QaSchedule = {
  id: string; project_id: string; name: string;
  cron: string; timezone: string; enabled: boolean;
  target: { kind: "script"; script_id: string } | { kind: "cases"; case_ids: string[]; run_kind?: string };
  next_run_at: string | null; last_run_at: string | null; last_run_id: string | null;
  created_at: string; updated_at: string;
};
```

- Schedules persist in `qa.sqlite3` (`schedules` table; `user_version` bump with the same migration style as `runs.name/environment/trigger`).
- The gateway's existing cron loop evaluates QA schedules alongside agent jobs, so runs happen while no browser is open and after a gateway restart.
- A fired schedule calls the existing run-start path with `trigger="schedule"`, `name=<schedule name>`, and records `last_run_id`; environment failures still surface as `blocked_by_env`.
- Validation reuses the cron parser already used by `nanobot/cron`, rejects an empty/duplicate target, and refuses a schedule whose project or script no longer exists.

## Consequences

- The workbench gains two deterministic features: a project context for chat turns and schedules that survive a closed browser.
- `nanobot/qa/store.py`, `service.py`, `http.py`, `qa-api.ts` and the QA WebUI all change together; the brief needs the new action table, and `tests/qa/` needs store/action coverage.
- The schedule table and the cron service become a shared surface: the QA owner and the automation owner must agree on which loop evaluates QA schedules before either implements it.
- Any existing `trigger="schedule"` run imported by CI keeps its meaning; the new scheduler is the first producer of that trigger.

## Alternatives rejected

- **Browser-local schedules (`localStorage` + `setInterval`).** Only fires while the QA page is open, invisible to other clients, lost on a different machine, and mislabeled if it still writes `trigger="schedule"`.
- **Create a cron automation by prompting the agent from the QA page.** Non-deterministic (model compliance), requires a linked chat topic, and the resulting job is an agent turn rather than a run — the schedule would be neither testable nor guaranteed.
- **Prefix every chat prompt with the project key.** Pollutes user history, cannot be enforced server-side, and breaks once the user edits the message.
- **Keep `trigger="schedule"` as a label on manually started runs.** Records provenance but schedules nothing.
- **Client-side filter of projects in the workbench only.** Already exists; it does not tell the chat agent which project a turn belongs to.

## Implementation

Implemented on 2026-10-19: the `schedules` table (schema v3), `nanobot/qa/schedule_time.py`, `nanobot/qa/scheduler.py`, the four `qa.schedule.*` actions, and the gateway-started `QaScheduler`. The session `qa_project_id` binding (the first half of this decision) is not implemented yet.
