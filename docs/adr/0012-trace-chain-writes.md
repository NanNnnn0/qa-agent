# ADR 0012: Make the trace chain writable and require it for a ready case

- Status: accepted
- Date: 2026-10-20

## Context

`qa_trace` already models the chain - a source (requirement, API spec, bug, standard, exploration) carries evidence, a test point is derived from one or more sources, a case links a test point - and the workbench already renders it (the trace tab and the chain badges in the case library). What did not exist was any way to fill it in:

- no agent tool wrote a source or a test point; the only writers were hand-edited YAML and the `qa trace draft` CLI,
- `qa_case` did not expose `testpoints` / `sources` even though `CaseFiles.create_case` accepted them,
- every live case was a legacy SQLite row (`derived=0`, no YAML document), so it could not carry a link at all.

The result is what the operator saw: twenty cases, every one of them showing "no source / no test point", and a chain that is decorative.

## Decision

1. **`qa_testpoint` writes the upstream entities.** `action=create entity=source` and `entity=testpoint` write a **draft** under `draft/agent/...`; `action=list` reads sources, test points or pending drafts; `action=get` reads one; `action=attach` links existing cases to a formal test point. Drafts are promoted by review (`qa trace review approve`, or the trace tab), so an agent cannot stamp its own traceability.
2. **`qa_case` exposes the links.** `testpoints`, `sources`, `direct_reason` and `risk` are now tool parameters (HTTP already passed them).
3. **A ready case must link a test point** (policy C). The rule lives in `require_links_for_ready` and is enforced by the tool and the HTTP write route: `draft` may stay unlinked so a case can be written first and linked later, but `ready` means executable, and execution, coverage and impact all walk the chain. A case that links a source directly must also declare `direct_reason`.
4. **A test point may only link formal sources.** Creating one against a draft source is refused with "still a draft - approve it first", and review refuses a test point whose source is only `observed` confidence.
5. **The workbench gets a test points tab.** Sources and their test points with coverage counts, the pending drafts, and the cases that still have no chain. Read-only: creating is the agent's job, promoting stays in the trace tab.
6. **The skills state the rule.** `qa-api-testing` and `qa-functional-testing` now describe the order (source -> test point -> case), the 1..3 test points per case limit, and that a direct source link is the exception.

## Consequences

- A new case enters the chain only when it is created with a link; an unlinked ready case is now an error rather than a silent draft. That is the point: the badge stops being able to lie.
- The chain grows one review step at a time. For a fresh project the agent writes a source draft, a human confirms it, then a test point draft, a human approves it, then the cases.
- Legacy rows still need `qa trace migrate-sqlite` before they can be linked; until then they stay in the "unlinked cases" list of the new tab.
- The case library still shows the *direct* `sources` of a case, so a case linked only through a test point shows no source. Computing that transitively is the next step.
- `attach` refuses more than three test points per case, which keeps coverage counts meaningful.

## Alternatives rejected

- **Let a ready case stay unlinked.** That is the state this ADR fixes: the chain would keep looking decorative because nothing forces it.
- **Write sources and test points directly into the formal library.** It would make the agent's guess look reviewed, and coverage would measure the agent's optimism.
- **Auto-create a test point from each case.** Fabricated traceability: the point of a test point is that it was designed before the case.

## Follow-up: grouping, short codes, resolved chain (2026-10-20)

The first pass left three things a growing library could not absorb, and the operator named all three: test points and cases were flat lists, a case linked through a test point still showed "缺少来源", and the detail drawer of a test point showed its id and little else.

1. **`group` is a breadcrumb, not an id.** `qa_testpoint` accepts `group="登录模块/注册界面"` (up to four levels, `/` or `>` separators). The workbench groups the test points tab and the case library by it; a case inherits the group of its first linked test point, so grouping never needs a second field on the case. An ungrouped test point is shown under 未分组 rather than hidden.
2. **`group` is deliberately not part of the review fingerprint.** Re-checking exists to catch content that cases assert; moving a test point between modules is navigation. `testpoint_payload` therefore leaves `group` out, and changing it does not mark a single case for a re-check.
3. **Short codes are derived, never stored.** Trace ids carry the project module and a uuid, which is the right key and unreadable in a list. `qa_trace.labels.testpoint_codes` numbers the test points of a project in id order (`TP-01`), every list shows the code, and the full id stays in the drawer and the `title` attribute. Nothing passes a short code as an argument.
4. **The chain badges resolve transitively.** The case payload now carries `trace_testpoints` (id, code, title, group, risk) and `trace_sources` (id, title, type, `direct`), computed from the loaded library: direct sources plus every source reachable through the linked test points. The badge counts the resolved set and the drawer spells it out by title, marking a source as 直接 or 经由测试点.
5. **The test point drawer explains the test point.** Group breadcrumb, design method with what it means, risk with its regression rule, the sources with their evidence locators, the covered cases with status and human code, and the full id at the bottom.

Consequences:

- The case library groups across projects by putting the project key in front of the breadcrumb, so two `注册界面` groups never mix when the filter is 全部项目.
- Renaming a group rewrites every test point that carries it; that is a YAML edit (or a new tool call), not a migration.
- `group` on a source stays what it always was (the id namespace); the breadcrumb lives on test points only.
- Grouping is a display concern: the trace CLI, the graph and coverage never read `group`.
