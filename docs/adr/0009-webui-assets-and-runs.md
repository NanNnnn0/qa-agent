# ADR 0009: Show API assets, revisions and pinned run details in the workbench

- Status: accepted
- Date: 2026-10-19

## Context

The API testing work landed as store APIs, MCP tools and CLI commands, and the plan deliberately left the WebUI untouched. Operators could therefore not see the catalog, a case's revision history, or what a pinned run actually executed. Worse, the run drawer rendered the new structured summary through the old prose field, so a pinned run showed `[object Object]` where its counts belong.

## Decision

1. **Reads get HTTP GET routes, writes stay on the WebSocket channel.** `GET /api/qa/api-operations` (list with project, method, status, query, paging), `GET /api/qa/api-operations/{id}`, `GET /api/qa/cases/{id}/revisions` and `GET /api/qa/cases/{id}/revisions/{revision}`. The `qa.*` mutation contract is untouched, so the workbench gained no new write surface.
2. **A new API assets tab.** It lists method, path, summary, catalog status and update time, filters by project and free text, and opens a drawer with the evidence references and the normalized spec JSON. It loads once per filter change and on refresh; it does not poll.
3. **The run drawer renders the pinned report.** The structured summary becomes count cells plus per-phase rows (setup, cases, cleanup), the snapshot block shows the template version, the plan version, the executed case revisions with their content hashes, and the batch count, and each test row carries its phase and classification. Legacy prose summaries still render as text.
4. **The case drawer lists revisions.** Revision number, change source, author, time and content hash, newest first, refreshed after a save.
5. **The client normalizes both report shapes.** `QaRunReport.summary` is `string | QaRunSummary | null`, and the snapshot, batches and per-test classification are optional, so old runs keep rendering.

## Consequences

- The three new capabilities are visible where the operator already works; nothing new to install.
- The catalog view is read-only. Ingesting, staging and applying still happen through `qa_api_catalog` and `qa_api_workflow`, because a write from the browser would need a new mutation contract and a review that this slice did not ask for.
- The run drawer now shows evidence for "which case body ran", which is what makes a pinned run auditable from the UI.
- `QaScripts` renders a structured summary as `passed/tests` instead of the raw object.
- The workbench has one more tab, so the tab list and its labels must stay in sync with `QaTab`.

## Alternatives rejected

- **A separate page outside the workbench.** The workbench already owns project scope, tokens and polling; a second page would duplicate all three.
- **Expose ingest through a new mutation.** It needs a payload shape, validation parity with the MCP tool and a review of the write channel; the read-only view answers the question "what is in the catalog" without that.
- **Render the summary object as JSON text.** It hides the counts and the phases behind a wall of braces, which is the same problem as the prose field.
