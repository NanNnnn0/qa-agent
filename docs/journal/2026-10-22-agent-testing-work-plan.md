# 2026-10-22 agent-testing-work-plan

- Goal: make QA-Agent the system under test and reuse Cheyicha API work as task context; replace the concept-first curriculum with user-executed Agent testing work.
- Scope and ownership: this session owns `docs/learning/*.md` and this journal only, in `/opt/worktrees/agent-learning-roadmap` on `docs/agent-learning-roadmap`.
- Changed: rewrote the eight existing documents around task samples, tool arguments, action scope, completion evidence, failure attribution, regression work and personal contributions. Only AT-001 is expanded; no complete test suite or execution results were generated.
- Source basis: static inspection of `/opt/qa-agent` at `e43ba24d279589d53f487462cf667c9f59c8a515`. This documentation worktree has an older source baseline; actual tests must record the target service version separately.
- Verified: `git diff --check` exited 0. The read-only link checker below found 21 local Markdown links; all targets and referenced lines exist. Source inspection confirmed the preflight/start/get split, ready-only execution and the target YAML's reviewed status; the runtime case state remains unverified.
- Gate: documentation-only changes skip the Python and WebUI gates under `docs/COLLABORATION.md`. No business API request, model task, pytest suite, deployment or service restart was performed.
- Not done: user execution of AT-001, runtime tool-trace collection, defect reproduction, regression code and resume claims. The plan is assistant support, not completed user test work.
- Affects other sessions: none; no public contract, deployment file or existing untracked Cheyicha data was changed. No merge or push was performed.
- Next step: the user runs AT-001, preserves independent state and the tool trace, and makes an initial task-level judgement for joint analysis.

Local-link verification command, run from this worktree:

```bash
node <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
let count = 0;
const failures = [];
for (const name of fs.readdirSync('docs/learning').filter(name => name.endsWith('.md'))) {
  const file = path.join('docs/learning', name);
  for (const match of fs.readFileSync(file, 'utf8').matchAll(/\]\(([^)]+)\)/g)) {
    const target = match[1];
    if (/^[a-z]+:\/\//i.test(target) || target.startsWith('#')) continue;
    const parsed = /^(.*?)(?::(\d+))?$/.exec(target);
    const resolved = path.isAbsolute(parsed[1]) ? parsed[1] : path.resolve(path.dirname(file), parsed[1]);
    count++;
    if (!fs.existsSync(resolved)) failures.push(`${file}: missing ${target}`);
    else if (parsed[2] && Number(parsed[2]) > fs.readFileSync(resolved, 'utf8').split('\n').length) failures.push(`${file}: invalid line ${target}`);
  }
}
if (failures.length) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
} else {
  console.log(`${count} local Markdown links resolve; referenced lines exist.`);
}
NODE
```
