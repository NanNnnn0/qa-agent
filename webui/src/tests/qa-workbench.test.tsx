import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QaWorkbench, type QaWorkbenchProps } from "@/components/qa/QaWorkbench";
import i18n from "@/i18n";

const project = {
  id: "proj-1",
  key: "WEB",
  name: "Web 商城",
  description: "",
  base_url: "https://shop.example.test",
  repo_path: "",
  default_env: "staging",
  stats: { cases: 12, ready_cases: 9, scripts: 3, runs: 4, active_tasks: 2 },
};

const task = {
  id: "task-1",
  project_id: "proj-1",
  parent_id: null,
  role: "api",
  title: "登录接口回归",
  prompt: "跑一遍登录接口",
  status: "running",
  progress: 40,
  subagent_task_id: "",
  result: "",
  created_at: "2026-02-01T02:00:00Z",
  updated_at: "2026-02-01T02:05:00Z",
  project_key: "WEB",
};

const qaCase = {
  id: "case-1",
  project_id: "proj-1",
  code: "WEB-API-001",
  title: "登录成功返回 token",
  kind: "api",
  priority: "P1",
  status: "ready",
  preconditions: "",
  steps: [{ action: "POST /login", expected: "200" }],
  expected: "200 且带 token",
  tags: ["smoke", "login"],
  api: { request: { method: "POST", path: "/login" } },
  source: "seed",
  author: "qa",
  created_at: "2026-02-01T02:00:00Z",
  updated_at: "2026-02-01T02:00:00Z",
};

const run = {
  id: "run-1",
  project_id: "proj-1",
  script_id: "script-1",
  case_ids: ["case-1", "case-2"],
  status: "failed",
  passed: 3,
  failed: 1,
  errors: 0,
  skipped: 1,
  duration_ms: 1234,
  started_at: "2026-02-01T02:00:00Z",
  finished_at: "2026-02-01T02:00:01Z",
  report: { summary: "3 passed, 1 failed", tests: [] },
  log: "",
};

const envBlockedRun = {
  ...run,
  id: "run-2",
  status: "blocked_by_env",
  passed: 0,
  failed: 0,
  duration_ms: 12,
  report: { summary: "environment unavailable", tests: [] },
};

/** v1.1 run metadata: name/environment/trigger come from the contract. */
const ciRun = {
  ...run,
  id: "run-ci-1",
  name: "CI smoke",
  environment: "staging",
  trigger: "ci",
  status: "passed",
  passed: 2,
  failed: 0,
  errors: 0,
  skipped: 0,
  report: { summary: "2 passed", tests: [] },
};

const JUNIT_XML =
  '<testsuite name="smoke"><testcase name="login" classname="api" /></testsuite>';

const reviewTask = { ...task, status: "needs_review", progress: 80 };

/** A reviewed trace case with a full chain: source → test point → script. */
const tracedCase = {
  ...qaCase,
  testpoints: ["TP-LOGIN-005"],
  sources: ["REQ-LOGIN-01"],
  script: { binding: "scripts/test_login.py::test_lock_after_5_failures", resolves: true },
  needs_recheck: true,
  recheck_reasons: ["dependency_changed"],
  trace_status: "reviewed",
  draft: false,
  batch: null,
  needs_links: false,
  yaml_path: "cases/TC-LOGIN-003.yaml",
};


/** Second project, so the script hierarchy is visibly project -> module. */
const secondProject = {
  ...project,
  id: "proj-2",
  key: "APP",
  name: "移动端",
  base_url: "",
  stats: { cases: 1, ready_cases: 0, scripts: 2, runs: 0, active_tasks: 0 },
};

const scriptRows = [
  {
    id: "script-api",
    project_id: "proj-1",
    name: "登录脚本",
    framework: "pytest",
    language: "python",
    file_path: "tests/api/test_login.py",
    case_ids: ["case-1"],
    tags: ["smoke"],
    status: "ready",
    created_at: "2026-02-01T02:00:00Z",
    updated_at: "2026-02-01T02:00:00Z",
  },
  {
    id: "script-ui",
    project_id: "proj-1",
    name: "下单脚本",
    framework: "pytest",
    language: "python",
    file_path: "tests/ui/test_order.py",
    case_ids: [],
    tags: [],
    status: "draft",
    created_at: "2026-02-01T02:00:00Z",
    updated_at: "2026-02-01T02:00:00Z",
  },
  {
    id: "script-ungrouped",
    project_id: "proj-1",
    name: "无路径脚本",
    framework: "pytest",
    language: "python",
    file_path: "",
    case_ids: [],
    tags: [],
    status: "draft",
    created_at: "2026-02-01T02:00:00Z",
    updated_at: "2026-02-01T02:00:00Z",
  },
  {
    id: "script-root",
    project_id: "proj-2",
    name: "冒烟脚本",
    framework: "pytest",
    language: "python",
    file_path: "test_smoke.py",
    case_ids: [],
    tags: [],
    status: "draft",
    created_at: "2026-02-01T02:00:00Z",
    updated_at: "2026-02-01T02:00:00Z",
  },
];

const overviewPayload = {
  ok: true,
  counts: { projects: 1, cases: 12, ready_cases: 9, scripts: 3, runs: 4, tasks: 7, active_tasks: 2 },
  projects: [project],
  recent_tasks: [task],
  recent_runs: [run],
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "application/json" : null,
    },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function routeFetch(input: RequestInfo | URL): Response {
  const path = new URL(String(input), "http://127.0.0.1").pathname;
  if (path === "/api/qa/overview") return jsonResponse(overviewPayload);
  if (path === "/api/qa/projects") return jsonResponse({ ok: true, projects: [project] });
  if (path === "/api/qa/tasks") {
    return jsonResponse({ ok: true, items: [task], total: 1 });
  }
  if (path === "/api/qa/tasks/task-1") {
    return jsonResponse({
      ok: true,
      task: { ...task, artifacts: [], children: [] },
    });
  }
  if (path === "/api/qa/tasks/task-1/events") {
    return jsonResponse({
      ok: true,
      events: [
        {
          id: 1,
          task_id: "task-1",
          at: "2026-02-01T02:01:00Z",
          kind: "progress",
          message: "开始执行登录用例",
          data: {},
        },
      ],
    });
  }
  if (path === "/api/qa/cases") {
    return jsonResponse({ ok: true, items: [qaCase], total: 1, limit: 200, offset: 0 });
  }
  if (path === "/api/qa/cases/case-1") return jsonResponse({ ok: true, case: qaCase });
  if (path === "/api/qa/scripts") return jsonResponse({ ok: true, items: [], total: 0 });
  if (path === "/api/qa/runs") {
    return jsonResponse({ ok: true, items: [run, envBlockedRun], total: 2 });
  }
  if (path === "/api/qa/runs/run-1") return jsonResponse({ ok: true, run });
  return jsonResponse({ ok: false, error: `unexpected ${path}` }, 404);
}

type Transport = QaWorkbenchProps["client"];

/** Override selected reads; anything else falls through to `routeFetch`. */
function stubFetch(override: (path: string) => Response | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://127.0.0.1").pathname;
      return override(path) ?? routeFetch(input);
    }),
  );
}

/** A `needs_review` task, plus the detail/event reads its drawer needs. */
function stubReviewTask(reviewTask: Record<string, unknown>) {
  stubFetch((path) => {
    if (path === "/api/qa/tasks") {
      return jsonResponse({ ok: true, items: [reviewTask], total: 1 });
    }
    if (path === "/api/qa/tasks/task-1") {
      return jsonResponse({ ok: true, task: { ...reviewTask, artifacts: [], children: [] } });
    }
    if (path === "/api/qa/tasks/task-1/events") {
      return jsonResponse({ ok: true, events: [] });
    }
    return null;
  });
}

/** Two projects and four scripts spread over modules, the root and no path. */
function stubScriptHierarchy() {
  stubFetch((path) => {
    if (path === "/api/qa/projects") {
      return jsonResponse({ ok: true, projects: [project, secondProject] });
    }
    if (path === "/api/qa/scripts") {
      return jsonResponse({ ok: true, items: scriptRows, total: scriptRows.length });
    }
    return null;
  });
}

type MutationHandler = (action: string, payload?: Record<string, unknown>) => unknown;

function renderWorkbench(
  overrides: Partial<QaWorkbenchProps> = {},
  mutate?: MutationHandler,
) {
  const requestMutation = vi.fn(
    async (action: string, payload?: Record<string, unknown>) => {
      const custom = mutate?.(action, payload);
      if (custom !== undefined) return custom;
      if (action === "qa.case.create") {
        return { ok: true, case: { ...qaCase, id: "case-2", title: "登录校验" } };
      }
      return { ok: true };
    },
  );
  const transport: Transport = { requestMutation: requestMutation as unknown as Transport["requestMutation"] };
  const utils = render(
    <QaWorkbench
      token="test-token"
      client={transport}
      onBackToChat={() => {}}
      pollIntervalMs={0}
      {...overrides}
    />,
  );
  return { requestMutation, ...utils };
}

beforeEach(async () => {
  await i18n.changeLanguage("zh-CN");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => routeFetch(input)));
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("QA workbench", () => {
  it("renders the five tabs and the overview data", async () => {
    renderWorkbench();

    for (const id of ["overview", "tasks", "cases", "scripts", "schedules", "runs"]) {
      expect(screen.getByTestId(`qa-tab-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("qa-tab-overview")).toHaveAttribute("aria-selected", "true");

    await waitFor(() => {
      expect(screen.getByTestId("qa-count-cases")).toHaveTextContent("12");
    });
    expect(screen.getByTestId("qa-count-projects")).toHaveTextContent("1");
    expect(screen.getByTestId("qa-count-active-tasks")).toHaveTextContent("2");
    expect(screen.getByTestId("qa-count-scripts")).toHaveTextContent("3");

    const projectRow = within(screen.getByTestId("qa-overview")).getByText("Web 商城");
    expect(projectRow).toBeInTheDocument();
    expect(screen.getByText("https://shop.example.test")).toBeInTheDocument();
  });

  it("switches to the task board and shows project keys without polling", async () => {
    const user = userEvent.setup();
    renderWorkbench();

    await user.click(screen.getByTestId("qa-tab-tasks"));
    expect(await screen.findByTestId("qa-tasks")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("登录接口回归")).toBeInTheDocument();
    });
    expect(screen.getByText("进行中")).toBeInTheDocument();
    expect(screen.queryByTestId("qa-tab-unknown")).not.toBeInTheDocument();
  });

  it("creates a case with the qa.case.create mutation", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderWorkbench();

    // Projects must be loaded before the dialog can default to one.
    await waitFor(() => {
      expect(screen.getByTestId("qa-count-cases")).toHaveTextContent("12");
    });
    await user.click(screen.getByTestId("qa-tab-cases"));
    expect(await screen.findByTestId("qa-cases")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("登录成功返回 token")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("qa-case-create"));
    const titleInput = await screen.findByTestId("qa-new-case-title");
    await user.type(titleInput, "登录校验");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.case.create",
        expect.objectContaining({
          project_id: "proj-1",
          title: "登录校验",
          kind: "api",
          priority: "P1",
          status: "draft",
        }),
        expect.any(Number),
      );
    });
  });

  it("renders pass and fail counts for a run result", async () => {
    renderWorkbench({ initialTab: "runs" });

    expect(await screen.findByTestId("qa-runs")).toBeInTheDocument();
    const counts = await screen.findAllByTestId("qa-run-counts");
    expect(counts[0]).toHaveTextContent("通过 3");
    expect(counts[0]).toHaveTextContent("失败 1");
    expect(counts[0]).toHaveTextContent("错误 0");
    // Environment failures must not read as product failures.
    expect(screen.getByText("环境阻塞")).toBeInTheDocument();
  });

  it("shows an error bar instead of a blank page when a read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ok: false, error: "boom" }, 500)));
    renderWorkbench({ initialTab: "runs" });

    const alerts = await screen.findAllByTestId("qa-error");
    expect(alerts.some((alert) => alert.textContent?.includes("boom"))).toBe(true);
  });

  it("approves a needs_review task with qa.task.approve, note and reviewer", async () => {
    const user = userEvent.setup();
    stubReviewTask(reviewTask);
    const { requestMutation } = renderWorkbench({ initialTab: "tasks" });

    // The row only offers the review actions while the task needs review.
    await user.click(await screen.findByTestId("qa-task-approve"));
    const dialog = await screen.findByTestId("qa-task-decision-dialog");
    await user.type(within(dialog).getByTestId("qa-task-decision-note"), "回归通过");
    await user.type(within(dialog).getByTestId("qa-task-decision-reviewer"), "alice");
    await user.click(within(dialog).getByTestId("qa-task-decision-submit"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.task.approve",
        { id: "task-1", note: "回归通过", reviewer: "alice" },
        expect.any(Number),
      );
    });
  });

  it("rejects a needs_review task with qa.task.reject", async () => {
    const user = userEvent.setup();
    stubReviewTask(reviewTask);
    const { requestMutation } = renderWorkbench({ initialTab: "tasks" });

    await user.click(await screen.findByTestId("qa-task-reject"));
    const dialog = await screen.findByTestId("qa-task-decision-dialog");
    // Empty note is optional: the payload must omit it, not send "".
    await user.type(within(dialog).getByTestId("qa-task-decision-reviewer"), "bob");
    await user.click(within(dialog).getByTestId("qa-task-decision-submit"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.task.reject",
        { id: "task-1", reviewer: "bob" },
        expect.any(Number),
      );
    });
  });

  it("imports a JUnit run with qa.run.import and shows the new run", async () => {
    const user = userEvent.setup();
    stubFetch((path) => {
      if (path === "/api/qa/runs/run-ci-1") return jsonResponse({ ok: true, run: ciRun });
      return null;
    });
    const { requestMutation } = renderWorkbench({ initialTab: "runs" }, (action) =>
      action === "qa.run.import" ? { ok: true, run: ciRun } : undefined,
    );

    await screen.findByTestId("qa-runs");
    await waitFor(() => {
      expect(screen.getAllByTestId("qa-run-counts").length).toBeGreaterThan(0);
    });
    await user.click(screen.getByTestId("qa-run-import"));

    const dialog = await screen.findByTestId("qa-run-import-dialog");
    await user.type(within(dialog).getByTestId("qa-run-import-name"), "CI smoke");
    await user.type(within(dialog).getByTestId("qa-run-import-environment"), "staging");
    // fireEvent keeps the XML literal: userEvent would parse `{` / `[` as keys.
    fireEvent.change(within(dialog).getByTestId("qa-run-import-xml"), {
      target: { value: JUNIT_XML },
    });
    await user.click(within(dialog).getByTestId("qa-run-import-submit"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.run.import",
        {
          project_id: "proj-1",
          xml: JUNIT_XML,
          name: "CI smoke",
          environment: "staging",
        },
        120000,
      );
    });
    // Prepended to the list and opened in the drawer.
    expect((await screen.findAllByText("CI smoke")).length).toBeGreaterThan(0);
    expect(await screen.findByTestId("qa-run-drawer")).toBeInTheDocument();
    // The imported run carries the `ci` trigger badge.
    expect(screen.getAllByText("ci").length).toBeGreaterThan(0);
  });

  it("shows the trace chain badges of a case (来源/测试点/脚本/需复核)", async () => {
    stubFetch((path) => {
      if (path === "/api/qa/cases") {
        return jsonResponse({ ok: true, items: [tracedCase], total: 1, limit: 200, offset: 0 });
      }
      if (path === "/api/qa/cases/case-1") {
        return jsonResponse({ ok: true, case: tracedCase });
      }
      return null;
    });
    renderWorkbench({ initialTab: "cases" });

    const chain = await screen.findByTestId("qa-case-chain");
    expect(chain).toHaveTextContent("来源 1");
    expect(chain).toHaveTextContent("测试点 1");
    expect(chain).toHaveTextContent("脚本");
    expect(chain).toHaveTextContent("需复核");
  });

  it("marks a case as reviewed with qa.case.update and status=ready", async () => {
    const user = userEvent.setup();
    stubFetch((path) => {
      if (path === "/api/qa/cases") {
        return jsonResponse({ ok: true, items: [tracedCase], total: 1, limit: 200, offset: 0 });
      }
      if (path === "/api/qa/cases/case-1") {
        return jsonResponse({ ok: true, case: tracedCase });
      }
      return null;
    });
    const { requestMutation } = renderWorkbench({ initialTab: "cases" }, (action) =>
      action === "qa.case.update" ? { ok: true, case: tracedCase } : undefined,
    );

    await user.click(await screen.findByText("登录成功返回 token"));
    await user.click(await screen.findByTestId("qa-case-review"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.case.update",
        expect.objectContaining({ id: "case-1", status: "ready" }),
        expect.any(Number),
      );
    });
  });

  it("archives a case with qa.case.delete", async () => {
    const user = userEvent.setup();
    stubFetch((path) => {
      if (path === "/api/qa/cases") {
        return jsonResponse({ ok: true, items: [tracedCase], total: 1, limit: 200, offset: 0 });
      }
      if (path === "/api/qa/cases/case-1") {
        return jsonResponse({ ok: true, case: tracedCase });
      }
      return null;
    });
    const { requestMutation } = renderWorkbench({ initialTab: "cases" });

    await user.click(await screen.findByText("登录成功返回 token"));
    await user.click(await screen.findByTestId("qa-case-archive"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.case.delete",
        { id: "case-1" },
        expect.any(Number),
      );
    });
  });

  it("deletes a project with qa.project.delete after confirmation", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderWorkbench();

    await waitFor(() => {
      expect(screen.getByTestId("qa-count-cases")).toHaveTextContent("12");
    });
    await user.click(screen.getByTestId("qa-project-delete"));
    const dialog = await screen.findByTestId("qa-project-delete-dialog");
    await user.click(within(dialog).getByTestId("qa-project-delete-confirm"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.project.delete",
        { id: "proj-1" },
        expect.any(Number),
      );
    });
  });

  it("edits an existing project with qa.project.update", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderWorkbench();

    await waitFor(() => {
      expect(screen.getByTestId("qa-count-cases")).toHaveTextContent("12");
    });
    await user.click(screen.getByTestId("qa-project-edit"));

    const dialog = await screen.findByTestId("qa-project-dialog");
    expect(dialog).toHaveTextContent("编辑项目");
    const nameInput = within(dialog).getByTestId("qa-project-name");
    expect(nameInput).toHaveValue("Web 商城");
    expect(within(dialog).getByTestId("qa-project-key")).toHaveValue("WEB");

    await user.clear(nameInput);
    await user.type(nameInput, "Web 商城 2.0");
    await user.click(within(dialog).getByTestId("qa-project-submit"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.project.update",
        expect.objectContaining({
          id: "proj-1",
          key: "WEB",
          name: "Web 商城 2.0",
          base_url: "https://shop.example.test",
        }),
        expect.any(Number),
      );
    });
  });

  it("groups automation scripts by project and module", async () => {
    stubScriptHierarchy();
    renderWorkbench({ initialTab: "scripts" });

    const firstProject = await screen.findByTestId("qa-script-project-proj-1");
    expect(within(firstProject).getByText("WEB")).toBeInTheDocument();
    expect(within(firstProject).getByText("Web 商城")).toBeInTheDocument();

    const apiModule = within(firstProject).getByTestId(
      "qa-script-module-proj-1-module-tests/api",
    );
    expect(within(apiModule).getByText("登录脚本")).toBeInTheDocument();
    expect(within(apiModule).queryByText("下单脚本")).not.toBeInTheDocument();

    const uiModule = within(firstProject).getByTestId(
      "qa-script-module-proj-1-module-tests/ui",
    );
    expect(within(uiModule).getByText("下单脚本")).toBeInTheDocument();

    // Path-less scripts land in their own bucket instead of creating a module.
    const ungrouped = within(firstProject).getByTestId("qa-script-module-proj-1-ungrouped-base");
    expect(within(ungrouped).getByText("未分组")).toBeInTheDocument();
    expect(within(ungrouped).getByText("无路径脚本")).toBeInTheDocument();

    // A project at the root of its repository gets a `根目录` bucket.
    const secondGroup = screen.getByTestId("qa-script-project-proj-2");
    const rootModule = within(secondGroup).getByTestId("qa-script-module-proj-2-root-base");
    expect(within(rootModule).getByText("根目录")).toBeInTheDocument();
    expect(within(rootModule).getByText("冒烟脚本")).toBeInTheDocument();
  });

  it("collapses a script module and then its project group", async () => {
    stubScriptHierarchy();
    const user = userEvent.setup();
    renderWorkbench({ initialTab: "scripts" });

    await screen.findByTestId("qa-script-row-script-api");
    const moduleToggle = screen.getByTestId("qa-script-module-toggle-proj-1-module-tests/api");
    expect(moduleToggle).toHaveAttribute("aria-expanded", "true");

    await user.click(moduleToggle);
    expect(moduleToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("登录脚本")).not.toBeInTheDocument();
    // Sibling modules stay visible: collapsing is per module, not per project.
    expect(screen.getByText("下单脚本")).toBeInTheDocument();

    const projectToggle = screen.getByTestId("qa-script-project-toggle-proj-1");
    await user.click(projectToggle);
    expect(projectToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("下单脚本")).not.toBeInTheDocument();
    expect(screen.getByTestId("qa-script-project-proj-2")).toBeInTheDocument();
  });

  it("paginates cases at fifty per page and requests summaries", async () => {
    const user = userEvent.setup();
    const urls: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://127.0.0.1");
        urls.push(url);
        if (url.pathname === "/api/qa/cases/facets") {
          return jsonResponse({
            ok: true,
            modules: [{ id: "登录模块", count: 60 }],
            operations: [],
          });
        }
        if (url.pathname === "/api/qa/cases") {
          const offset = Number(url.searchParams.get("offset") ?? "0");
          const items = Array.from({ length: offset === 0 ? 50 : 10 }, (_, index) => ({
            ...qaCase,
            id: `case-${offset + index + 1}`,
            code: `WEB-API-${String(offset + index + 1).padStart(3, "0")}`,
            title: `用例 ${offset + index + 1}`,
            group: "登录模块/注册界面",
            trace_state: "fresh",
            testpoint_count: 1,
            source_count: 1,
          }));
          return jsonResponse({ ok: true, items, total: 60, limit: 50, offset });
        }
        return routeFetch(input);
      }),
    );
    renderWorkbench({ initialTab: "cases" });

    await screen.findByTestId("qa-case-pagination");
    expect(screen.getByTestId("qa-case-pagination")).toHaveTextContent("第 1 / 2 页");
    await waitFor(() => {
      expect(
        urls.some(
          (url) =>
            url.pathname === "/api/qa/cases" &&
            url.searchParams.get("limit") === "50" &&
            url.searchParams.get("offset") === "0",
        ),
      ).toBe(true);
    });

    await user.click(screen.getByTestId("qa-case-page-next"));
    await waitFor(() => {
      expect(
        urls.some(
          (url) =>
            url.pathname === "/api/qa/cases" &&
            url.searchParams.get("limit") === "50" &&
            url.searchParams.get("offset") === "50",
        ),
      ).toBe(true);
    });
    expect(screen.getByTestId("qa-case-pagination")).toHaveTextContent("第 2 / 2 页");
  });

  it("restores case filters from the URL and corrects an out-of-range page", async () => {
    window.location.hash =
      "#/qa?tab=cases&project=proj-1&kind=api&q=login&page=99";
    try {
      renderWorkbench();
      await screen.findByTestId("qa-case-search");
      expect(screen.getByTestId("qa-case-search")).toHaveValue("login");
      await waitFor(() => {
        expect(window.location.hash).not.toContain("page=99");
      });
      expect(window.location.hash).toContain("q=login");
      expect(window.location.hash).toContain("project=proj-1");
    } finally {
      window.location.hash = "";
    }
  });

  it("restores filters from the URL on popstate", async () => {
    window.location.hash = "#/qa?tab=cases";
    try {
      renderWorkbench();
      await screen.findByTestId("qa-case-search");
      await act(async () => {
        window.location.hash = "#/qa?tab=cases&kind=ui&q=other";
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
      await waitFor(() => {
        expect(screen.getByTestId("qa-case-search")).toHaveValue("other");
      });
      expect(window.location.hash).toContain("kind=ui");
    } finally {
      window.location.hash = "";
    }
  });

  it("writes a debounced search to the URL", async () => {
    const user = userEvent.setup();
    window.location.hash = "#/qa?tab=cases";
    try {
      renderWorkbench();
      const search = await screen.findByTestId("qa-case-search");
      await user.type(search, "checkout");
      await waitFor(() => {
        expect(window.location.hash).toContain("q=checkout");
      });
    } finally {
      window.location.hash = "";
    }
  });

  it("defaults the workbench scope to the chat's bound QA project", async () => {
    const user = userEvent.setup();
    renderWorkbench({ initialProjectId: "proj-1" });

    await waitFor(() => {
      expect(screen.getByTestId("qa-count-cases")).toHaveTextContent("12");
    });
    expect(screen.getByTestId("qa-scope-project")).toHaveTextContent("WEB");

    const fetchMock = vi.mocked(globalThis.fetch);
    await user.click(screen.getByTestId("qa-tab-scripts"));
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(
        urls.some(
          (url) => url.includes("/api/qa/scripts") && url.includes("project_id=proj-1"),
        ),
      ).toBe(true);
    });
  });
});
