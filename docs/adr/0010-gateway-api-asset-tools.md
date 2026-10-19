# ADR 0010: Reach the API asset workflow from the agent runtime

- Status: accepted
- Date: 2026-10-19

## Context

ADR 0003 put the API asset tools in `nanobot/qa/api_tools.py` and registered them only in the stdio MCP server (`nanobot qa mcp`). The gateway builds its tool set with `ToolLoader`, which scans `nanobot/agent/tools/*` for `Tool` subclasses, and `tools.mcpServers` in the deployed config is empty. A chat turn therefore had 28 tools and none of them was `qa_api_catalog`, `qa_api_workflow` or `qa_api_run`.

The written contract already assumed they existed: `nanobot/skills/qa-api-testing/SKILL.md` leads with the fixed order (register the material, design the scenario matrix, stage the batch, validate, apply, preflight, run, conclude) and names the three tools by name, and the role prompts in `nanobot/qa/roles.py` (which `qa_task action=plan` turns into subagent prompts) repeat the same sequence. So the skill described a flow the chat agent could not execute. The realistic outcomes were a failed tool call the model then routed around, or a silent fall back to `qa_case create`, which keeps the case but loses the catalog evidence, the staged batch, the revision pinning and the preflight gate.

## Decision

1. **Thin adapters, one implementation.** `nanobot/agent/tools/qa_api.py` holds three `Tool` subclasses that delegate `name`, `description`, `parameters` and `execute` to the classes in `nanobot/qa/api_tools.py`. The behaviour, validation and error payloads stay in one place, so the MCP server and the agent runtime cannot drift.
2. **Let the loader find them.** `ToolLoader` discovers the module automatically, so the gateway gains the tools without a composition change.
3. **Main agent only.** `_scopes = {"core"}`. The subagent prompt budget is a tested contract (`tests/agent/test_subagent_consolidator_contract.py` asserts a subagent turn fits 20 928 tokens), and the three schemas cost about 2.3k tokens: with them in the subagent scope that test failed at 22 363 tokens, and no honest amount of trimming closes a 1 435-token gap. Subagents keep `qa_case` + `qa_run` for API work; the catalog and batch steps belong to the chat that owns the project binding.
4. **Default the project from the chat binding.** When `project_id` is omitted the adapter fills it from `bound_project_id(ctx.metadata)`, the contract the `qa_*` tools already use. An unbound chat keeps the explicit `project_id is required` error instead of guessing.
5. **No MCP registration.** `tools.mcpServers` stays empty: no extra process, no second SQLite handle, no namespaced tool names.
6. **Say which flow owns which case.** The bound-chat context block now states that API cases come from the catalog (`qa_api_catalog` -> `qa_api_workflow` -> `qa_api_run`) and that `qa_case` owns functional and UI cases.
7. **Compact schemas.** The parameter descriptions were shortened so the tool surface costs less prompt on every turn. The long form (scenario matrix, evidence kinds, plan and auth shapes) stays in `qa-api-testing/SKILL.md`, which both surfaces can read.

## Consequences

- A chat turn now registers 31 tools; the three `qa_api_*` tools answer with the same JSON payloads the MCP server returns.
- The `qa-api-testing` skill becomes executable as written, so the normative path is also the path of least resistance in the chat.
- The API path is additive: `qa_case`, `qa_script` and `qa_run` remain for functional, UI and manual work, and `qa_run` still shares the pinned pipeline.
- The `api` role prompt in `roles.py` still names the three tools, which a dispatched subagent does not have. Closing that needs either a compact subagent facade or a decision to raise the subagent budget; it is recorded as a known gap rather than half-fixed here.
- `tests/qa/test_api_agent_tools.py` pins discovery, the scope decision, the schema shape, the bound-project default, an unbound refusal, and an end-to-end stage -> validate -> apply -> preflight run through the agent tools.

## Alternatives rejected

- **Register the MCP server in `tools.mcpServers`.** It works, but it adds a supervised subprocess and a second connection to the same database, and the tools would only be present after the MCP handshake - a weaker guarantee for a chat that is already in the same process.
- **Give the tools the subagent scope too.** Measured: the consolidator contract test fails with the tools present (22 363 / 20 928 tokens). Trimming the schemas to fit would leave tens of tokens of headroom, which the next tool change breaks.
- **Teach the model to use `qa_case` only.** That is what happened by accident; it drops catalog evidence, idempotent batches, revision pins and the preflight gate, which are the reason the API layer exists.
- **Copy the implementation into `nanobot/agent/tools/qa.py`.** Two copies of the same validation would drift, and the MCP server would keep serving the stale one.
