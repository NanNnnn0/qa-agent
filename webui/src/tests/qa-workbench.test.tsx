import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
});

describe("QA workbench", () => {
  it("renders the five tabs and the overview data", async () => {
    renderWorkbench();

    for (const id of ["overview", "tasks", "cases", "scripts", "runs"]) {
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
});
