# ADR 0011: Nest API cases under their endpoint in the assets tab

- Status: accepted (temporary grouping)
- Date: 2026-10-20

## Context

The case library is one flat table sorted by case code. With twenty-plus API cases for a single endpoint the list says nothing about which endpoint a case exercises, and operators asked for hierarchy.

Cases created through `qa_api_workflow` carry `api_case_metadata.operation_id`. Cases written through `qa_case` - the path the chat agent took before ADR 0010 - carry no catalog link at all; the workbench shows them as missing sources. A metadata-only hierarchy would therefore render every endpoint with zero cases for exactly the data that motivated the request.

## Decision

1. **Group in the assets tab, not the case library.** An endpoint row gains a case count and an expand control. The expanded panel is a table with the case library's columns minus chain and tags (code, title, kind, priority, status), and clicking a row opens a case drawer with its request, assertions and expected result. The endpoint drawer does not repeat the list - expansion is the only place the cases appear.
2. **Match by project + method + normalized path.** Path segments that are `{...}`, pure digits or UUIDs collapse to `{}` on both sides, so a case that pins `/api/orders/42` still finds `/api/orders/{}`.
3. **Read-only and client-side.** The tab loads the project's cases (limit 500) through `GET /api/qa/cases` and groups them in memory. No new route, no new write surface.
4. **Say what it is.** The empty panel explains that a staged batch is what attaches cases here, and the component comment records that this grouping is temporary.

## Consequences

- The operator sees an endpoint's cases without leaving the tab, and the count makes an uncovered endpoint obvious.
- The heuristic can over-match when one project declares two operations that normalize to the same path (rare: the catalog already gives both the same identity) and can under-match when a case's request path differs from the operation, for example a different host prefix. Those cases stay in the flat library.
- Loading up to 500 cases per filter change is fine at the current data size. A paged per-operation route is the next step once a project grows past it.
- The durable fix is unchanged: write `operation_id` on every API case (including `qa_case` creates) and give the case library its own hierarchy. That needs a write-path decision, not a UI change.

## Alternatives rejected

- **A tree view in the case library.** It is the right long-term shape but a much larger slice, and the request was for a temporary grouping now.
- **A backend join route (`/api/qa/api-operations/{id}/cases`).** Cleaner, but it can only return metadata-linked cases, which is empty for the data that motivated the request; it would still need the path heuristic. Revisit it together with the write-path link.
