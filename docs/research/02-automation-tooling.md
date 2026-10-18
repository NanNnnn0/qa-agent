# 02 · 自动化测试工具链与文件格式选型（v1）

> 目标读者：QA Agent 架构组。范围：API 测试、UI 测试、报告互操作、用例设计方法、AI 生成模式。
> 结论一律以 **确定性产物优先**（可重复、可解析、可 diff）为判定标准，聊天输出不计分。

## 0. 结论摘要

v1 只押注 **两条生成链路**：`pytest + httpx`（API，含 Schemathesis 做 schema 属性测试）与 `Playwright Test（Python 或 Node）+ JUnit reporter`（UI）。报告层统一收敛到 **JUnit XML + CTRF JSON + Allure results 目录** 三件套。刻意**不**引入 Hurl / Postman+Newman / Karate / Dredd / Robot Framework 作为一级格式，理由见下表（多数是「人写友好、但 AI 生成+机器解析不友好」或「上游已停止维护」）。

关键事实：Postman 官方文档已明确 **Newman 不再维护**，且不兼容 Postman v12 起唯一支持的 collection v3 格式，官方建议迁移到 Postman CLI（[Postman Docs](https://learning.postman.com/docs/reference/newman-cli/command-line-integration-with-newman/)）。这直接否决了「以 Postman collection 作为生成产物」的路线。

## 1. API 测试工具对比

| 工具 | 文件格式 | CI 友好度 | 从 OpenAPI 生成 | 断言质量 | 人/AI 可编辑性 | 建议 |
|---|---|---|---|---|---|---|
| **pytest + httpx** | `.py` | 高（退出码 + JUnit XML，原生） | 需自写或配合 Schemathesis | 任意 Python 断言，最高 | 高；AI 生成 Python 最稳 | **主链路** |
| pytest + requests | `.py` | 高 | 同上 | 同上 | 同上 | 用 httpx 替代（异步/HTTP2） |
| **Schemathesis** | `.py` / CLI | 高（JUnit XML、Allure、HAR 输出） | **原生**：OpenAPI 2.0/3.0/3.1/3.2、GraphQL | 属性断言 + 服务端 5xx/schema 违规，每条含最小 curl 复现 | CLI 零维护 | **主链路**（schema 段） |
| Hurl | `.hurl` 纯文本 | 高（`--test`、`--report-junit`、退出码 4=断言失败） | 否 | 中：状态码/header/XPath/JSONPath 谓词、captures 串联 | 人极友好，AI 生成易上手但缺逻辑分支 | 可选 DSL |
| Postman + Newman | collection JSON | 中 | 弱 | 中（JS 测试脚本） | 差：巨型 JSON，diff 噪声大 | **否决**（已停止维护） |
| Karate | `.feature` DSL | 中 | 需社区插件 | 强（内建 match/JSON schema） | 中；DSL 生态窄 | 不选 |
| Dredd | 基于 API 描述文档 | 中 | 是（API Blueprint / OpenAPI） | **弱**：只做「实现是否符合文档」 | 无测试代码可编辑 | 作为 CI 校验补充 |
| Pact | `.py` / JSON pact 文件 | 高（可接 Pact Broker） | 否 | 强，但只覆盖契约（"contract by example"），非 schema（[Pact Docs](https://docs.pact.io/)） | 中 | 微服务契约场景再引入 |
| REST Assured | `.java` | 高 | 否 | 强 | 低（Java 生态与 Python 后端不匹配） | 不选 |
| Bruno | `.bru` 纯文本 | 中（bruno CLI） | 弱 | 中 | **好**（文件可读、可入库） | 观察，不入 v1 |

要点：

- Hurl 的模型是「文件即用例」，一个文件内请求串行、文件间并行，有 `--report-junit` / `--report-json`，因此**可解析性达标**，但缺少参数化与逻辑编排能力（[Hurl Manual](https://hurl.dev/docs/manual.html)）。
- Schemathesis 的价值在于「无需按端点写维护成本」：指向 schema 即跑，且自动串联操作做有状态测试，失败保留最小复现（[Schemathesis Docs](https://schemathesis.readthedocs.io/en/stable/)）。它**替代不了**业务断言，需与手写 pytest 并存。

## 2. UI / 功能自动化对比

| 工具 | 语言 | 可靠性特性 | AI 生成/修复适配度 | 建议 |
|---|---|---|---|---|
| **Playwright** | TS/JS、Python、Java、.NET | 自动等待、web-first 断言、Trace Viewer、重试、sharding | **最高**：官方 planner/generator/healer 三 agent、MCP、codegen 优先 role/text/test-id 定位 | **主链路** |
| Cypress | JS/TS | 自动等待、时间旅行调试、网络桩 | 中：单标签页、跨域受限，生成代码结构与官方 agent 生态弱 | 不选 |
| Selenium | 多语言 | 需自建显式等待，无内置 runner/trace | 低：AI 易写出 flaky 等待逻辑 | 不选（仅兜底遗留） |
| Robot Framework | `.robot` 关键字 | 关键字驱动、库生态广 | 中：关键字 DSL 抽象层过多，AI 易编造不存在的关键字 | 不选 |

Playwright 官方 agent 分工值得直接照抄：**planner** 产出 `specs/*.md` 人读计划 → **generator** 把 Markdown 计划转成 `tests/*.spec.ts`（生成时实时校验选择器与断言）→ **healer** 重放失败步骤、定位等价元素、给补丁并**重跑到通过或触发护栏为止**（[Playwright Test Agents](https://playwright.dev/docs/test-agents)）。其目录约定 `specs/` + `tests/` + `seed.spec.ts` 正是我们需要的「计划与产物分离」。

Playwright MCP 则提供另一条路：基于无障碍树快照（每个元素给 `ref`），**不需要视觉模型**；`--caps=testing` 下还有 `browser_generate_locator`、`browser_verify_text_visible` 等断言类工具（[Playwright MCP](https://playwright.dev/mcp/introduction)）。对我们的架构意义是：**探索阶段用 MCP，落盘阶段用 codegen/runner**，两段分离避免把不确定的自然语言步骤直接跑进回归集。codegen 会优先选 role/text/test-id 定位并在多元素匹配时自动加固（[Playwright Test Generator](https://playwright.dev/docs/codegen)）。

## 3. 报告与互操作标准

| 标准 | 性质 | 缺陷 | 在 QA Agent 中的角色 |
|---|---|---|---|
| **JUnit XML** | 事实标准 XML | 无统一 schema，字段方言多（`skipped`/`failure`/`error` 各家不一） | **必须产出**：一切 runner 都能吐，最稳的摄取基线 |
| **CTRF** | JSON 交换格式 | 生态较新 | **必须产出**：扁平 `tests[]`、严格核心字段 + 仅 `extra` 允许扩展、分层身份 `runId/testId/executionId`（[CTRF Spec](https://ctrf.io/docs/specification/overview)），作为自有 DB 的主摄取格式 |
| **Allure** | 结果目录（`*-result.json` + container/environment/executor/history） | 需额外 CLI 生成 HTML；目录结构复杂 | **产出 results 目录**：给人看的历史/重试/稳定性分析与质量门（[Allure Docs](https://allurereport.org/docs/)） |
| OpenAPI / JSON Schema | 规范描述 | 不描述业务语义 | **输入**：生成测试的契约来源 |
| Cucumber / Gherkin | `.feature` 文本 + step definitions | 抽象层导致「步骤定义爆炸」，且断言与步骤分离 | **仅在需求阶段**用于人读计划，不进入执行层 |
| TestNG XML | Java 测试编排 | 强绑定 JVM 生态 | 不采用 |

决策：**执行层只用代码**（pytest / Playwright），**Gherkin 只出现在 `specs/` 的计划文档中**（可借用 `Scenario Outline + Examples` 的数据驱动表结构，参见 [Gherkin Reference](https://cucumber.io/docs/gherkin/reference/)），摄取层固定 JUnit XML（兜底）+ CTRF（主）+ Allure results（人看）。

## 4. 值得写进 skill/template 的用例设计方法

| 方法 | 何时强制 | 落地形式 |
|---|---|---|
| 等价类划分 | 所有输入字段 | `@pytest.mark.parametrize` 分组，每组注释 `# EP: valid/invalid` |
| 边界值 | 数值/长度/日期字段 | 生成 `min-1, min, max, max+1` 四元组，禁止手挑 |
| 判定表 | 多条件业务规则 | 模板内联 Markdown 判定表 → 逐行转 parametrize |
| 组合（pairwise） | 参数 ≥4 且组合爆炸 | `allpairspy`（[PyPI](https://pypi.org/project/allpairspy/)）或 PICT（[microsoft/pict](https://github.com/microsoft/pict)） |
| 状态迁移 | 有生命周期实体（订单/工单/会话） | 显式 `states` 表 + 合法/非法迁移矩阵，非法迁移单独用例 |
| 风险分级 | 全部 | `@pytest.mark.priority("P1")` + `risk` 字段，驱动执行顺序与超时预算 |

pairwise 工具选 **`allpairspy`**（纯 Python、无依赖、支持 `filter_func` 剔除非法组合、支持 n-wise）；PICT 适合参数表极大时离线生成再用 CSV 固化。注意 allpairspy 官方自陈「非最优解，存在覆盖更小的工具」（同页 Known issues），因此**组合数只作为参考，不作为覆盖率证明**。

## 5. 既有「AI 生成自动化」模式与护栏

四种已被验证的模式：

1. **计划→生成→修复闭环**（Playwright planner/generator/healer）。价值在于把「探索」与「产物」分成两种上下文（[来源](https://playwright.dev/docs/test-agents)）。
2. **快照驱动交互**（Playwright MCP 无障碍树 + `ref`）。价值是把「选择器猜测」换成「结构化引用」（[来源](https://playwright.dev/mcp/introduction)）。
3. **spec-first 生成**（从 OpenAPI/JSON Schema 出发）。Schemathesis 证明「零维护按端点」可行。
4. **self-healing locator**。**必须限制**：修复只允许改定位器与等待条件，且每个用例修复次数上限 2，超限即标记 `needs_human`——否则会把真实缺陷「修」成通过。

让 AI 产物确定且可维护的护栏（v1 强制执行）：

- 生成后**必须在沙箱 subprocess 内真跑通**才算完成；跑不通的产物不落盘。
- **同一用例连跑 2 次**均通过才准入库（反 flaky 门）。
- 静态门禁：`ruff`（Python）/ `eslint`（TS）+ 禁止模式扫描（见 §7）。
- **定位器唯一性校验**：`locator.count() == 1`，否则回炉。
- 修复 diff 行数上限（建议 ≤20 行），超限转人工。
- 禁止访问生产域名：allowlist 仅测试环境 base URL。

## 6. v1 推荐技术栈

### 6.1 依赖清单

```toml
# pyproject.toml (backend)
[project]
dependencies = [
  "httpx>=0.27",            # API 客户端（同步 + 异步）
  "pytest>=8",              # 执行器
  "pytest-xdist>=3",        # 并行
  "pytest-timeout>=2",      # 硬超时，禁裸 sleep
  "pytest-repeat>=0.9",     # 反 flaky 双跑
  "jsonschema>=4",          # 响应 schema 断言
  "schemathesis>=4",        # OpenAPI 属性测试
  "allpairspy>=2.5",        # pairwise 生成
  "junitparser>=3",         # 解析 JUnit XML
  "allure-pytest>=2",       # Allure results
]
# UI 侧（Node 优先，生态最全）
# @playwright/test, @playwright/mcp(可选), @ctrf/ctrf-reporter
```

### 6.2 每个项目的文件布局

```
projects/{project_id}/
  qa.config.yaml              # base_url, env, auth ref, timeouts, allowlist
  specs/                      # 输入：OpenAPI 快照 + 人读测试计划 *.md
    openapi.json
    api-{domain}.md
    ui-{flow}.md
  data/                       # 参数化数据（CSV/JSON）与 pairwise 产物
    boundary-{field}.json
    pairwise-{feature}.csv
  tests/
    api/
      conftest.py
      test_{domain}_{nnn}_{slug}.py
    ui/
      playwright.config.ts
      tests/{flow}/{nnn}-{slug}.spec.ts
      fixtures/auth.setup.ts
  .qa/runs/{run_id}/          # 输出，全部不可变
    manifest.json             # run 元数据 + 产物索引
    junit.xml
    ctrf.json
    allure-results/
    stdout.log / stderr.log
    traces/                   # Playwright trace.zip
```

### 6.3 脚本骨架

API（pytest）：

```python
# tests/api/test_orders_003_boundary_amount.py
import pytest, httpx
from jsonschema import validate

pytestmark = [
    pytest.mark.qa(id="TC-ORD-003", priority="P1", risk="high", method="boundary"),
    pytest.mark.timeout(30),
]

CASES = [("amount", 0, 400), ("amount", -1, 400), ("amount", 1, 201), ("amount", 100000, 201)]

@pytest.mark.parametrize("field,value,expected", CASES, ids=[f"{f}={v}" for f, v, _ in CASES])
def test_create_order_amount_boundary(api: httpx.Client, field, value, expected):
    r = api.post("/v1/orders", json={"sku": "SKU-1", field: value})
    assert r.status_code == expected, r.text
    if expected == 201:
        validate(r.json(), ORDER_SCHEMA)
```

UI（Playwright）：

```ts
// tests/ui/checkout/010-guest-checkout.spec.ts
import { test, expect } from '@playwright/test';

test.use({ trace: 'retain-on-failure' });

test('TC-CO-010 游客下单成功', async ({ page, baseURL }) => {
  await page.goto('/cart');
  await expect(page.getByTestId('cart-total')).toHaveText(/\d+\.\d{2}/);
  await page.getByTestId('checkout-as-guest').click();
  await expect(page.getByRole('heading', { name: '配送信息' })).toBeVisible();
});
```

### 6.4 运行与结果存储（后端视角）

后端把 runner 当 subprocess 调，不内嵌 pytest 进程：

```bash
python -m pytest tests/api -q \
  --junitxml=.qa/runs/$RUN_ID/junit.xml \
  --allure-report-dir=.qa/runs/$RUN_ID/allure-results \
  -p no:cacheprovider -n 4 --timeout=120

npx playwright test --reporter=junit,ctrf \
  --output=.qa/runs/$RUN_ID/traces
```

约定：`run_id = {project_id}-{utc_iso8601}-{git_sha[:7]}`；`.qa/runs/` 只增不改（与 CTRF 报告的不可变性一致）；后端先解析 `junit.xml`（junitparser）即时失败聚合，再把 `ctrf.json` 写入测试管理库，Allure results 只做归档与人工查看链接。

## 7. AI 生成测试的确定性契约

**必须（MUST）**

1. 每个用例可寻址 id：`TC-{DOMAIN}-{NNN}`，同时写入 markdown 元数据、pytest `mark.qa(id=...)` / Playwright 标题前缀。
2. 必须声明 `priority`、`risk`、`method`（等价类/边界/判定表/pairwise/状态迁移）三字段。
3. 必须经 `pytest.raises` 或显式状态码断言覆盖失败路径；每用例至少一个**主断言**在首行可读。
4. 必须使用 `base_url` 注入、fixture 工厂造数据、显式超时；测试数据带唯一 `run_id` 前缀以便清理。
5. 必须产出可解析结果（JUnit XML + CTRF），失败带最小复现（curl 命令或 Playwright trace）。
6. 必须可在干净环境独立运行（无顺序依赖、无外部手工状态）。

**禁止（MUST NOT）**

1. 禁止 `sleep` / 固定延时；禁止重试掩盖断言失败。
2. 禁止硬编码域名、凭证、绝对路径；禁止指向生产环境。
3. 禁止对时间戳、随机数、自增 id 做等值断言（改为格式/范围断言）。
4. 禁止 CSS 层级/xpath 绝对路径定位；只允许 `data-testid`、role、label、text。
5. 禁止 `try/except: pass`、禁止无 reason 的 `skip`、禁止删除/弱化既有断言来自证通过。
6. 禁止一文件多功能（>5 用例须拆分文件），禁止跨用例共享可变全局状态。

## 8. 总对比表（含推荐）

| 维度 | 候选 | 推荐 | 理由（一句话） |
|---|---|---|---|
| API 执行器 | pytest / Hurl / Newman / Karate | **pytest + httpx** | 断言无上限、JUnit 原生、AI 生成 Python 成功率最高 |
| Schema 测试 | Schemathesis / Dredd | **Schemathesis** | 原生 OpenAPI 2.0–3.2 + 有状态，含最小 curl 复现 |
| 文本 DSL | Hurl / Bruno / Karate | **Hurl（可选）** | 纯文本可入库、`--report-junit`、退出码语义清晰 |
| 契约测试 | Pact / Dredd | **暂不引入** | v1 单体前后端，收益低于维护成本 |
| UI 执行器 | Playwright / Cypress / Selenium / Robot | **Playwright** | 官方三 agent + MCP + codegen + trace，唯一「AI 可闭环」栈 |
| 结果摄取 | JUnit XML / CTRF / Allure | **CTRF 主 + JUnit 兜底 + Allure 归档** | 机器语义、跨工具、可长期分析三者兼得 |
| 用例描述 | Gherkin / Markdown 计划 | **Markdown 计划（`specs/`）** | 保留人读性，但执行层不留抽象层 |
| 组合生成 | allpairspy / PICT | **allpairspy**（PICT 备用） | 纯 Python 无依赖、支持非法组合过滤 |

---

**参考来源**：[Hurl Manual](https://hurl.dev/docs/manual.html) · [Schemathesis](https://schemathesis.readthedocs.io/en/stable/) · [Postman/Newman](https://learning.postman.com/docs/reference/newman-cli/command-line-integration-with-newman/) · [Pact](https://docs.pact.io/) · [Playwright Test Agents](https://playwright.dev/docs/test-agents) · [Playwright MCP](https://playwright.dev/mcp/introduction) · [Playwright Codegen](https://playwright.dev/docs/codegen) · [Playwright Reporters](https://playwright.dev/docs/test-reporters) · [CTRF](https://ctrf.io/docs/specification/overview) · [Allure](https://allurereport.org/docs/) · [Gherkin](https://cucumber.io/docs/gherkin/reference/) · [allpairspy](https://pypi.org/project/allpairspy/) · [PICT](https://github.com/microsoft/pict) · [pytest](https://docs.pytest.org/en/stable/) · [httpx](https://www.python-httpx.org/) · [OpenAPI Spec](https://spec.openapis.org/oas/latest.html) · [JSON Schema](https://json-schema.org/) · [Cypress](https://docs.cypress.io/) · [Selenium](https://www.selenium.dev/documentation/) · [Robot Framework](https://robotframework.org/) · [REST Assured](https://rest-assured.io/) · [Dredd](https://dredd.org/) · [Karate](https://github.com/karatelabs/karate) · [Bruno](https://docs.usebruno.com/) · [TestNG](https://testng.org/)
