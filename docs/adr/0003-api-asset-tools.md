# ADR 0003: Expose the API asset workflow as MCP tools and move the role protocol onto it

- Status: accepted
- Date: 2026-10-19

## Context

ADR 0002 added a catalog, case revisions and transactional batches, but only Python callers can reach them. Two audiences need them: an external MCP client that manages the same QA database, and the dispatched subagents whose prompts live in `nanobot/qa/roles.py`. That prompt file is a public contract, so changing what it tells a model to call is a decision, not an implementation detail.

The plan names three tools. The third one, `qa_api_run`, needs preflight and a fixed execution template that do not exist yet, and the existing `qa_run` tool already covers ad hoc execution.

## Decision

1. **Two tools now.** `nanobot/qa/api_tools.py` defines `qa_api_catalog` (`ingest`, `list`, `get`, `diff`) and `qa_api_workflow` (`create`, `get`, `validate`, `submit`, `apply`, `resume`, `export`). They are plain classes exposing `name`, `description`, `parameters`, `to_schema()` and `async execute(**kwargs)`, registered in `nanobot/qa/mcp_server.py`. The module imports no agent runtime, so the store stays usable without a gateway.
2. **`qa_api_run` waits for the execution loop.** A tool that cannot preflight or start honestly would teach a model to trust a call that only reports nothing. It lands with the pytest template, auth fixtures and run snapshot.
3. **Errors are data.** A validation or conflict failure returns `{"action": ..., "error": ...}` so a model can correct its own call in the next step; the MCP server would otherwise turn an exception into a string it cannot act on.
4. **Local references need an allow list.** `NANOBOT_QA_SPEC_ROOTS` (`os.pathsep` separated) is the only way to read a file by path. Unset means path ingestion is refused outright, which is the honest default: no directory, no read.
5. **The protocol moves with the tool.** The `api` role guide and the shared tool contract in `roles.py` now name the two tools in the fixed order (catalog, then case dedupe, then batch, then run), and `nanobot/skills/qa-api-testing/SKILL.md` is rewritten to the same order. The old "every case must assert a failure path" rule is gone, because a normal-path case with a real assertion is legitimate work.

## Consequences

- An MCP client and a dispatched subagent now share one tool surface and one store, and both see the same evidence and revision rules.
- The gateway agent does not see these two tools yet: that needs a `Tool` subclass in `nanobot/agent/tools/qa.py`, which this slice deliberately leaves alone. The MCP surface is the documented one.
- `validate` reports create versus update before anything is written, so a batch can be reviewed without a dry-run side effect.
- `export` returns the batch plus the case revisions it produced, which is the shape a Git snapshot needs.
- The skill no longer promises a failure assertion per case; reviewers must judge assertion strength from the evidence, not from a keyword rule.

## Alternatives rejected

- **Subclass the agent `Tool` now.** It would pull the runtime into `nanobot/qa` and register the same tools twice; the MCP server is the surface this slice was asked for.
- **Ship `qa_api_run` as a stub.** A `start` that silently does nothing is worse than an absent action, and the model would report a run that never happened.
- **Take allowed roots as a tool argument.** The caller would grant itself filesystem access, which defeats the restriction.
- **Return exceptions and let MCP stringify them.** The model then cannot tell a fixable field error from a store failure.
