import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QaTrace } from "@/components/qa/QaTrace";
import { QaWorkbench, type QaWorkbenchProps } from "@/components/qa/QaWorkbench";
import i18n from "@/i18n";

const project = {
  id: "login-lock",
  name: "登录锁定演示库（qa-trace P4）",
  root: "F:/xiangmu/qa-agent/qa-workbench/projects/login-lock",
  valid: true,
  error: null,
  modules: ["LOGIN"],
  counts: { sources: 2, testpoints: 1, cases: 1 },
};

const ratio = (numerator: number, denominator: number, percent: number) => ({
  numerator,
  denominator,
  percent,
});

const summaryPayload = {
  ok: true,
  trace_version: 1,
  tool_version: "0.4.0",
  project: {
    id: "login-lock",
    name: "登录锁定演示库（qa-trace P4）",
    root: "F:/xiangmu/qa-agent/qa-workbench/projects/login-lock",
    modules: ["LOGIN"],
  },
  valid: true,
  counts: {
    sources: 2,
    active_sources: 2,
    testpoints: 1,
    cases: 1,
    library_cases: 1,
    reviewed_cases: 1,
    dangling_references: 0,
  },
  coverage: {
    requirement: {
      label: "requirement",
      types: ["req"],
      reviewed: ratio(1, 1, 100),
      current_valid: ratio(1, 1, 100),
      uncovered: [],
      unconfirmed_sources: [],
    },
    behavior: {
      label: "behavior",
      types: ["ui", "api"],
      reviewed: ratio(1, 1, 100),
      current_valid: ratio(1, 1, 100),
      uncovered: [],
      unconfirmed_sources: [],
    },
    automation: {
      label: "automation",
      reviewed: ratio(1, 1, 100),
      provisional: true,
      provisional_reason: "markers are linted statically (ast)",
      unresolved_scripts: [],
    },
    orphan: {
      label: "orphan",
      library: ratio(0, 1, 0),
      case_ids: [],
    },
  },
  requirement_gaps: {
    uncovered_requirements: [],
    cases_without_requirement_root: [],
    count: 0,
    uncovered_requirement_count: 0,
  },
  requirement_gap_count: 0,
  dangling_count: 0,
  dead_assets: {
    sources_without_downstream: [],
    deprecated_cases: [],
    manual_p0_cases: { status: "unknown", candidates: [] },
    count: 0,
  },
  needs_recheck: [],
  metrics_suppressed: null,
  diagnostics: { counts: { error: 0, warn: 0, info: 0 }, items: [] },
  stale: {
    error: null,
    baseline: "recorded",
    counts: { changed: 1, removed: 0, needs_recheck: 1, reviewed_cases: 1 },
    needs_recheck: [
      {
        case_id: "TC-LOGIN-003",
        reasons: ["dependency_changed"],
        changed_ids: ["UI-LOGIN-02"],
        reviewed_by: null,
      },
    ],
  },
  drafts: { error: null, counts: { drafts: 1, pending: 1 }, batches: ["login-lock"] },
  runs: { error: null, counts: { runs: 1, failed_cases: 1 } },
};

const caseNode = {
  id: "TC-LOGIN-003",
  title: "密码连续错误 5 次锁定账号",
  status: "reviewed",
  priority: "P1",
  type: "functional",
  automation: "done",
  owner: "qa.zhang",
  tags: ["login", "security"],
  testpoints: ["TP-LOGIN-005"],
  sources: [],
  script: {
    case_id: "TC-LOGIN-003",
    binding: "scripts/test_login.py::test_lock_after_5_failures",
    file: "scripts/test_login.py",
    nodeid: "test_lock_after_5_failures",
    resolves: true,
    problem: null,
  },
  needs_recheck: true,
  recheck_reasons: ["dependency_changed"],
  changed_ids: ["UI-LOGIN-02"],
};

const treePayload = {
  ok: true,
  trace_version: 1,
  project: summaryPayload.project,
  counts: { sources: 2, testpoints: 1, cases: 1, scripts: 1, orphans: 0 },
  sources: [
    {
      id: "REQ-LOGIN-01",
      type: "req",
      title: "连续 5 次登录失败后锁定账号 15 分钟",
      status: "active",
      confidence: "confirmed",
      module: "LOGIN",
      owner: "qa.zhang",
      url: null,
      app_version: null,
      observed_at: null,
      stale: false,
      evidence: [
        {
          type: "document",
          locator: "artifacts/req/login-lock.md#2.1",
          description: "需求文档 2.1",
          verified: "verified_local",
        },
      ],
      testpoints: [
        {
          id: "TP-LOGIN-005",
          title: "连续失败计数与锁定阈值",
          status: "reviewed",
          method: "boundary",
          risk: "high",
          module: "LOGIN",
          owner: "qa.zhang",
          sources: ["REQ-LOGIN-01", "UI-LOGIN-02"],
          cases: [caseNode],
        },
      ],
      cases: [],
      case_count: 1,
    },
    {
      id: "UI-LOGIN-02",
      type: "ui",
      title: "登录失败 5 次触发账号锁定",
      status: "active",
      confidence: "confirmed",
      module: "LOGIN",
      owner: "qa.zhang",
      url: "/login",
      app_version: "3.4.1",
      observed_at: "2026-10-18",
      stale: false,
      evidence: [],
      testpoints: [
        {
          id: "TP-LOGIN-005",
          title: "连续失败计数与锁定阈值",
          status: "reviewed",
          method: "boundary",
          risk: "high",
          module: "LOGIN",
          owner: "qa.zhang",
          sources: ["REQ-LOGIN-01", "UI-LOGIN-02"],
          cases: [caseNode],
        },
      ],
      cases: [],
      case_count: 1,
    },
  ],
  orphans: [],
  scripts: [caseNode.script],
};

const stalePayload = {
  ok: true,
  stale_version: 1,
  project: { id: "login-lock", root: project.root },
  baseline: "recorded",
  fingerprint_version: 1,
  written: false,
  recorded: 0,
  index: ".qa-trace/index.json",
  counts: { changed: 1, removed: 0, needs_recheck: 1, reviewed_cases: 1 },
  changed: [
    {
      id: "UI-LOGIN-02",
      kind: "source",
      content_changed: true,
      dependency_changed: true,
      in_baseline: true,
    },
  ],
  removed: [],
  needs_recheck: [
    {
      case_id: "TC-LOGIN-003",
      reasons: ["dependency_changed"],
      changed_ids: ["UI-LOGIN-02"],
      reviewed_by: null,
    },
  ],
};

const draftsPayload = {
  ok: true,
  review_version: 1,
  project: { id: "login-lock", root: project.root },
  counts: { drafts: 1, pending: 1, rejected: 0, invalid: 0, batches: 1 },
  batches: ["login-lock"],
  drafts: [
    {
      batch: "login-lock",
      id: "TC-LOGIN-004",
      kind: "case",
      path: "draft/login-lock/cases/TC-LOGIN-004.yaml",
      status: "pending",
      valid: true,
      problems: [],
      content_hash: "abc",
      base_content_hash: null,
      file_hash: "def",
      rejected_by: null,
      rejected_at: null,
      note: null,
    },
  ],
};

const runId = "20261018T133422Z-b64b06bc";

const runsPayload = {
  ok: true,
  trace_version: 1,
  project: summaryPayload.project,
  counts: { runs: 1, failed_runs: 1, failed_cases: 1, unreadable: 0 },
  items: [
    {
      run_id: runId,
      status: "complete",
      exitstatus: 1,
      started_at: "2026-10-18T13:34:22+00:00",
      finished_at: "2026-10-18T13:34:24+00:00",
      environment: "win32/python-3.12.7",
      app_version: null,
      code_commit: "0a3cf427f4249e8112f77fb194c9891de7075a12",
      tool_version: "0.4.0",
      path: `runs/${runId}/manifest.json`,
      results: 1,
      failed_cases: 1,
      failed_case_ids: ["TC-LOGIN-003"],
    },
  ],
};

const failurePayload = {
  ok: true,
  failure_version: 1,
  project: { id: "login-lock", root: project.root },
  run: {
    run_id: runId,
    status: "complete",
    exitstatus: 1,
    started_at: "2026-10-18T13:34:22+00:00",
    finished_at: "2026-10-18T13:34:24+00:00",
    environment: "win32/python-3.12.7",
    app_version: null,
    code_commit: "0a3cf427f4249e8112f77fb194c9891de7075a12",
    tool_version: "0.4.0",
    path: `runs/${runId}/manifest.json`,
  },
  requested_case: null,
  case_missing: false,
  counts: { results: 1, failed_results: 1, failed_cases: 1, reported_cases: 1 },
  failures: [
    {
      case_id: "TC-LOGIN-003",
      results: [
        {
          nodeid: "qa-workbench/projects/login-lock/scripts/test_login.py::test_lock_after_5_failures",
          attempt: 1,
          outcome: "failed",
          failure_stage: "call",
          duration_ms: 4,
          started_at: "2026-10-18T13:34:24+00:00",
          error_summary: "AssertionError: 第 5 次失败后应返回 423 并锁定账号",
        },
      ],
      chain: {
        origin: "snapshot",
        testpoints: [{ id: "TP-LOGIN-005", exists: true, title: "连续失败计数与锁定阈值", status: "reviewed" }],
        sources: [
          {
            id: "REQ-LOGIN-01",
            exists: true,
            type: "req",
            status: "active",
            confidence: "confirmed",
            stale: false,
          },
          {
            id: "UI-LOGIN-02",
            exists: true,
            type: "ui",
            status: "active",
            confidence: "confirmed",
            stale: false,
          },
        ],
      },
      current: {
        exists: true,
        status: "reviewed",
        changed_since_run: false,
        needs_recheck: true,
        reasons: ["dependency_changed"],
        changed_ids: ["UI-LOGIN-02"],
      },
      last_run: { run_id: runId, outcome: "failed", finished_at: "2026-10-18T13:34:24+00:00" },
    },
  ],
};

const impactPayload = {
  ok: true,
  impact_version: 1,
  project: { id: "login-lock", root: project.root },
  target: { id: "REQ-LOGIN-01", kind: "source" },
  counts: { testpoints: 1, cases: 1, scripts: 1, needs_recheck: 1 },
  testpoints: [
    {
      id: "TP-LOGIN-005",
      exists: true,
      title: "连续失败计数与锁定阈值",
      status: "reviewed",
      method: "boundary",
      risk: "high",
    },
  ],
  cases: [
    {
      id: "TC-LOGIN-003",
      title: "密码连续错误 5 次锁定账号",
      status: "reviewed",
      priority: "P1",
      automation: "done",
      script: "scripts/test_login.py::test_lock_after_5_failures",
      needs_recheck: true,
      reasons: ["dependency_changed"],
      changed_ids: ["TP-LOGIN-005"],
      via: [{ source_id: "REQ-LOGIN-01", testpoint_id: "TP-LOGIN-005" }],
    },
  ],
  scripts: [caseNode.script],
  sources: [
    {
      id: "REQ-LOGIN-01",
      exists: true,
      type: "req",
      title: "连续 5 次登录失败后锁定账号 15 分钟",
      status: "active",
      confidence: "confirmed",
      stale: false,
    },
  ],
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
  const url = new URL(String(input), "http://127.0.0.1");
  const path = url.pathname;
  if (path === "/api/qa/projects") {
    return jsonResponse({ ok: true, projects: [] });
  }
  if (path === "/api/qa/trace/projects") {
    return jsonResponse({ ok: true, root: "qa-workbench/projects", projects: [project] });
  }
  if (path === "/api/qa/trace/summary") return jsonResponse(summaryPayload);
  if (path === "/api/qa/trace/tree") return jsonResponse(treePayload);
  if (path === "/api/qa/trace/stale") return jsonResponse(stalePayload);
  if (path === "/api/qa/trace/drafts") return jsonResponse(draftsPayload);
  if (path === "/api/qa/trace/runs") return jsonResponse(runsPayload);
  if (path === "/api/qa/trace/failure") return jsonResponse(failurePayload);
  if (path === "/api/qa/trace/impact") return jsonResponse(impactPayload);
  return jsonResponse({ ok: false, error: `unexpected ${path}` }, 404);
}

type Transport = QaWorkbenchProps["client"];

function renderTrace(mutate?: (action: string, payload?: Record<string, unknown>) => unknown) {
  const requestMutation = vi.fn(async (action: string, payload?: Record<string, unknown>) => {
    const custom = mutate?.(action, payload);
    if (custom !== undefined) return custom;
    return {
      ok: true,
      review: {
        review_version: 1,
        id: payload?.id ?? "TC-LOGIN-004",
        kind: "case",
        mode: "promoted",
        path: "cases/TC-LOGIN-004.yaml",
        reviewed_by: payload?.reviewer ?? null,
        reviewed_at: "2026-10-18T13:40:00+00:00",
        note: null,
        needs_recheck: false,
      },
    };
  });
  const transport: Transport = {
    requestMutation: requestMutation as unknown as Transport["requestMutation"],
  };
  const utils = render(
    <QaTrace token="test-token" client={transport} refreshSignal={0} />,
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

describe("QA trace tab", () => {
  it("renders the four separate metrics and the coverage gaps", async () => {
    renderTrace();

    // Four metrics, each on its own card: never merged into one number.
    await waitFor(() => {
      expect(screen.getByTestId("qa-trace-metric-requirement")).toHaveTextContent("100.00%");
    });
    expect(screen.getByTestId("qa-trace-metric-requirement")).toHaveTextContent("已审核 1/1");
    expect(screen.getByTestId("qa-trace-metric-behavior")).toHaveTextContent("100.00%");
    expect(screen.getByTestId("qa-trace-metric-automation")).toHaveTextContent("100.00%");
    expect(screen.getByTestId("qa-trace-metric-orphan")).toHaveTextContent("0.00%");

    // The global tree is gone: a linked-only library could only ever show a
    // complete chain.  What is left is the gap list, empty for this fixture.
    expect(await screen.findByTestId("qa-trace-gaps-empty")).toBeInTheDocument();

    // Stale panel lists the derived re-check with its reason.
    const stale = await screen.findByTestId("qa-trace-stale");
    expect(within(stale).getByText("TC-LOGIN-003")).toBeInTheDocument();
    expect(within(stale).getByText(/上游变更/)).toBeInTheDocument();

    // Drafts waiting for a human decision.
    const drafts = await screen.findByTestId("qa-trace-drafts");
    expect(within(drafts).getByText("TC-LOGIN-004")).toBeInTheDocument();
    expect(within(drafts).getByTestId("qa-trace-approve-TC-LOGIN-004")).toBeInTheDocument();
    expect(within(drafts).getByTestId("qa-trace-reject-TC-LOGIN-004")).toBeInTheDocument();
  });

  it("shows the failure chain run -> case -> testpoint -> source", async () => {
    renderTrace();

    const result = await screen.findByTestId("qa-trace-failure-result");
    expect(within(result).getByText(/20261018T133422Z-b64b06bc/)).toBeInTheDocument();
    expect(within(result).getByText("TC-LOGIN-003")).toBeInTheDocument();
    expect(within(result).getByText("TP-LOGIN-005")).toBeInTheDocument();
    expect(within(result).getByText("REQ-LOGIN-01")).toBeInTheDocument();
    expect(within(result).getByText("UI-LOGIN-02")).toBeInTheDocument();
    expect(within(result).getByText(/AssertionError/)).toBeInTheDocument();
  });

  it("queries the impact route with the source id", async () => {
    const user = userEvent.setup();
    renderTrace();

    await screen.findByTestId("qa-trace-gaps-empty");
    await user.type(screen.getByTestId("qa-trace-impact-input"), "REQ-LOGIN-01");
    await user.click(screen.getByTestId("qa-trace-impact-submit"));

    const result = await screen.findByTestId("qa-trace-impact-result");
    expect(within(result).getByText(/source REQ-LOGIN-01/)).toBeInTheDocument();
    expect(within(result).getByText("TC-LOGIN-003")).toBeInTheDocument();

    const calls = (globalThis.fetch as unknown as { mock: { calls: [RequestInfo | URL][] } }).mock.calls;
    const impactUrl = calls
      .map(([input]) => String(input))
      .find((url) => url.includes("/api/qa/trace/impact"));
    expect(impactUrl).toBeDefined();
    expect(impactUrl).toContain("source=REQ-LOGIN-01");
    expect(impactUrl).toContain("project=login-lock");
  });

  it("approves the whole batch through one mutation", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderTrace();

    await user.click(await screen.findByTestId("qa-trace-approve-all"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.trace.review_approve",
        {
          project: "login-lock",
          ids: expect.arrayContaining(["TC-LOGIN-004"]),
        },
        expect.any(Number),
      );
    });
  });

  it("approves a draft through qa.trace.review_approve", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderTrace();

    await user.click(await screen.findByTestId("qa-trace-approve-TC-LOGIN-004"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.trace.review_approve",
        { project: "login-lock", id: "TC-LOGIN-004", batch: "login-lock" },
        expect.any(Number),
      );
    });
    expect(await screen.findByTestId("qa-trace-notice")).toHaveTextContent("已通过 TC-LOGIN-004");
  });

  it("rejects a draft through qa.trace.review_reject", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderTrace((action) =>
      action === "qa.trace.review_reject"
        ? {
            ok: true,
            review: {
              id: "TC-LOGIN-004",
              kind: "case",
              mode: "rejected",
              path: "draft/login-lock/cases/TC-LOGIN-004.yaml",
              reviewed_by: null,
              reviewed_at: "2026-10-18T13:40:00+00:00",
              note: null,
              needs_recheck: false,
            },
          }
        : undefined,
    );

    await user.click(await screen.findByTestId("qa-trace-reject-TC-LOGIN-004"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.trace.review_reject",
        expect.objectContaining({ id: "TC-LOGIN-004" }),
        expect.any(Number),
      );
    });
    expect(await screen.findByTestId("qa-trace-notice")).toHaveTextContent("已退回 TC-LOGIN-004");
  });

  it("records the stale baseline through qa.trace.stale_write", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderTrace((action) =>
      action === "qa.trace.stale_write"
        ? { ok: true, stale: { ...stalePayload, written: true, recorded: 4 } }
        : undefined,
    );

    await user.click(await screen.findByTestId("qa-trace-stale-write"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.trace.stale_write",
        { project: "login-lock" },
        expect.any(Number),
      );
    });
    expect(await screen.findByTestId("qa-trace-notice")).toHaveTextContent("已记录 4 个实体的基线");
  });

  it("surfaces a read failure as an error bar instead of a blank tab", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://127.0.0.1").pathname;
      if (path === "/api/qa/trace/projects") {
        return jsonResponse({ ok: true, root: "qa-workbench/projects", projects: [project] });
      }
      return jsonResponse({ ok: false, error: "boom" }, 500);
    }));
    renderTrace();

    const alerts = await screen.findAllByTestId("qa-error");
    expect(alerts.some((alert) => alert.textContent?.includes("boom"))).toBe(true);
  });
});

describe("QA workbench trace tab", () => {
  it("exposes the trace tab next to the existing workbench tabs", async () => {
    const transport: Transport = {
      requestMutation: vi.fn() as unknown as Transport["requestMutation"],
    };
    render(
      <QaWorkbench
        token="test-token"
        client={transport}
        onBackToChat={() => {}}
        initialTab="trace"
        pollIntervalMs={0}
      />,
    );

    expect(screen.getByTestId("qa-tab-trace")).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByTestId("qa-trace")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("qa-trace-metric-requirement")).toHaveTextContent("100.00%");
    });
  });
});
