import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QaSchedules, type QaSchedulesProps } from "@/components/qa/QaSchedules";
import i18n from "@/i18n";

const project = {
  id: "proj-1",
  key: "WEB",
  name: "Web 商城",
  description: "",
  base_url: "https://shop.example.test",
  repo_path: "",
  default_env: "staging",
  stats: { cases: 2, ready_cases: 1, scripts: 1, runs: 1, active_tasks: 0 },
};

const script = {
  id: "script-1",
  project_id: "proj-1",
  name: "登录脚本",
  framework: "pytest",
  language: "python",
  file_path: "tests/api/test_login.py",
  case_ids: [],
  tags: [],
  status: "ready",
  created_at: "2026-02-01T02:00:00Z",
  updated_at: "2026-02-01T02:00:00Z",
};

const schedule = {
  id: "sch-1",
  project_id: "proj-1",
  name: "Nightly",
  cron: "0 3 * * *",
  timezone: "UTC",
  enabled: 1,
  target: { kind: "script", script_id: "script-1" },
  next_run_at: "2026-02-02T03:00:00Z",
  last_run_at: "",
  last_run_id: "",
  last_status: "",
  last_error: "",
  created_at: "2026-02-01T02:00:00Z",
  updated_at: "2026-02-01T02:00:00Z",
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
  steps: [],
  expected: "",
  tags: [],
  api: {},
  source: "seed",
  author: "qa",
  created_at: "2026-02-01T02:00:00Z",
  updated_at: "2026-02-01T02:00:00Z",
};

const run = {
  id: "run-1",
  project_id: "proj-1",
  script_id: "script-1",
  case_ids: [],
  name: "Nightly",
  environment: "",
  trigger: "schedule",
  status: "passed",
  passed: 2,
  failed: 0,
  errors: 0,
  skipped: 0,
  duration_ms: 1200,
  started_at: "2026-02-02T03:00:00Z",
  finished_at: "2026-02-02T03:00:01Z",
  report: { summary: "2 passed", tests: [] },
  log: "",
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
  if (path === "/api/qa/schedules") return jsonResponse({ ok: true, items: [schedule] });
  if (path === "/api/qa/scripts") return jsonResponse({ ok: true, items: [script], total: 1 });
  if (path === "/api/qa/cases") {
    return jsonResponse({ ok: true, items: [qaCase], total: 1, limit: 200, offset: 0 });
  }
  return jsonResponse({ ok: false, error: `unexpected ${path}` }, 404);
}

type Transport = QaSchedulesProps["client"];
type MutationHandler = (action: string, payload?: Record<string, unknown>) => unknown;

function renderSchedules(mutate?: MutationHandler) {
  const requestMutation = vi.fn(
    async (action: string, payload?: Record<string, unknown>) => {
      const custom = mutate?.(action, payload);
      if (custom !== undefined) return custom;
      return { ok: true };
    },
  );
  const transport: Transport = {
    requestMutation: requestMutation as unknown as Transport["requestMutation"],
  };
  const utils = render(
    <QaSchedules
      token="test-token"
      client={transport}
      projects={[project]}
      refreshSignal={0}
      pollIntervalMs={0}
      onChanged={() => {}}
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

describe("QA schedules", () => {
  it("renders a schedule with its target and next run", async () => {
    renderSchedules();

    expect(await screen.findByTestId("qa-schedule-row-sch-1")).toBeInTheDocument();
    expect(screen.getByText("Nightly")).toBeInTheDocument();
    expect(screen.getByText("0 3 * * *")).toBeInTheDocument();
    expect(screen.getByText("登录脚本")).toBeInTheDocument();
    expect(screen.getByText("UTC")).toBeInTheDocument();
    expect(screen.getByText("启用")).toBeInTheDocument();
  });

  it("creates a schedule that runs a script", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderSchedules();
    await screen.findByTestId("qa-schedule-row-sch-1");

    await user.click(screen.getByTestId("qa-schedule-create"));
    const dialog = await screen.findByTestId("qa-schedule-dialog");
    await user.type(within(dialog).getByTestId("qa-schedule-name"), "每小时");
    const cron = within(dialog).getByTestId("qa-schedule-cron");
    await user.clear(cron);
    await user.type(cron, "0 * * * *");
    // The dialog preselects the first script of the project once scripts load.
    await waitFor(() => {
      expect(within(dialog).getByTestId("qa-schedule-script")).toHaveTextContent("登录脚本");
    });
    await user.click(within(dialog).getByTestId("qa-schedule-submit"));

    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.schedule.create",
        expect.objectContaining({
          project_id: "proj-1",
          name: "每小时",
          cron: "0 * * * *",
          target: { kind: "script", script_id: "script-1" },
        }),
        expect.any(Number),
      );
    });
  });

  it("runs a schedule now and shows the resulting run", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderSchedules((action) =>
      action === "qa.schedule.run_now" ? { ok: true, run } : undefined,
    );
    await screen.findByTestId("qa-schedule-row-sch-1");

    await user.click(screen.getByTestId("qa-schedule-run-sch-1"));
    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.schedule.run_now",
        { id: "sch-1" },
        180000,
      );
    });
    const result = await screen.findByTestId("qa-run-result");
    expect(result).toHaveTextContent("通过 2");
  });

  it("pauses and then deletes a schedule", async () => {
    const user = userEvent.setup();
    const { requestMutation } = renderSchedules();
    await screen.findByTestId("qa-schedule-row-sch-1");

    await user.click(screen.getByTestId("qa-schedule-toggle-sch-1"));
    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.schedule.update",
        { id: "sch-1", enabled: false },
        expect.any(Number),
      );
    });

    await user.click(screen.getByTestId("qa-schedule-delete-sch-1"));
    const dialog = await screen.findByTestId("qa-schedule-delete-dialog");
    await user.click(within(dialog).getByTestId("qa-schedule-delete-confirm"));
    await waitFor(() => {
      expect(requestMutation).toHaveBeenCalledWith(
        "qa.schedule.delete",
        { id: "sch-1" },
        expect.any(Number),
      );
    });
  });
});
