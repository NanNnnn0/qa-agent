import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QaTestpoints } from "@/components/qa/QaTestpoints";
import "@/i18n";
import { loadQaTestpoints, type QaProject, type QaTestpointAssets } from "@/lib/qa-api";

vi.mock("@/lib/qa-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/qa-api")>();
  return { ...actual, loadQaTestpoints: vi.fn() };
});

const project = { id: "proj-1", key: "SHOP", name: "Shop" } as unknown as QaProject;

const assets: QaTestpointAssets = {
  project_id: "proj-1",
  root: "/tmp/trace/shop",
  sources: [
    {
      id: "API-SHOP-01",
      type: "api",
      title: "register contract",
      status: "active",
      confidence: "confirmed",
      module: "SHOP",
      owner: "agent",
      evidence: [{ type: "openapi", locator: "#/paths/~1x/post", description: "" }],
      testpoint_count: 1,
    },
  ],
  testpoints: [
    {
      id: "TP-SHOP-001",
      code: "TP-01",
      title: "username boundary",
      sources: ["API-SHOP-01"],
      method: "boundary",
      risk: "low",
      status: "reviewed",
      module: "SHOP",
      group: "登录模块/注册界面",
      owner: "agent",
      tags: [],
      note: "2 字符和 20 字符都能注册成功",
      case_count: 2,
      reviewed_case_count: 1,
      cases: [
        { case_id: "case-1", code: "SHOP-API-001", title: "2 chars", status: "reviewed" },
        { case_id: "case-2", code: "SHOP-API-002", title: "20 chars", status: "draft" },
      ],
    },
    {
      id: "TP-SHOP-002",
      code: "TP-02",
      title: "login smoke",
      sources: ["API-SHOP-01"],
      method: "scenario",
      risk: "high",
      status: "reviewed",
      module: "SHOP",
      group: "登录模块/登录界面",
      owner: "agent",
      tags: [],
      note: null,
      case_count: 0,
      reviewed_case_count: 0,
      cases: [],
    },
  ],
  drafts: [
    {
      batch: "agent",
      id: "TP-SHOP-003",
      kind: "testpoint",
      path: "draft/agent/testpoints/TP-SHOP-003.yaml",
      status: "pending",
      valid: true,
      problems: [],
    },
  ],
  unlinked_cases: [
    { case_id: "case-9", code: "SHOP-API-009", title: "unlinked", status: "ready", legacy: true },
  ],
  counts: { sources: 1, testpoints: 2, drafts: 1, unlinked_cases: 1, cases: 3 },
};

describe("test points tab", () => {
  beforeEach(() => {
    vi.mocked(loadQaTestpoints).mockResolvedValue(assets);
  });

  it("shows the chain counts", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-testpoints-count-sources")).toHaveTextContent("1");
    expect(screen.getByTestId("qa-testpoints-count-testpoints")).toHaveTextContent("2");
    expect(screen.getByTestId("qa-testpoints-count-drafts")).toHaveTextContent("1");
    expect(screen.getByTestId("qa-testpoints-count-unlinked")).toHaveTextContent("1");
  });

  it("lists sources and their test points", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-source-API-SHOP-01")).toBeInTheDocument();
    const testpoint = screen.getByTestId("qa-testpoint-TP-SHOP-001");
    expect(testpoint).toHaveTextContent("username boundary");
    expect(testpoint).toHaveTextContent("register contract");
    expect(testpoint).toHaveTextContent("2");
  });

  it("groups test points by their 模块/页面 breadcrumb", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-testpoint-group-登录模块")).toHaveTextContent("2");
    expect(screen.getByTestId("qa-testpoint-group-登录模块/注册界面")).toHaveTextContent("1");
    expect(screen.getByTestId("qa-testpoint-group-登录模块/登录界面")).toHaveTextContent("1");
  });

  it("shows a readable code and keeps the full id for the drawer", async () => {
    const user = userEvent.setup();
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    const row = await screen.findByTestId("qa-testpoint-TP-SHOP-001");
    // The list shows TP-01, not the 40-character trace id.
    expect(row).toHaveTextContent("TP-01");
    expect(row).not.toHaveTextContent("TP-SHOP-001");
    expect(row).toHaveTextContent("边界值");

    await user.click(row);
    const drawer = await screen.findByTestId("qa-testpoint-drawer");
    expect(drawer).toHaveTextContent("TP-01");
    expect(drawer).toHaveTextContent("登录模块 / 注册界面");
    expect(drawer).toHaveTextContent("username boundary");
    expect(drawer).toHaveTextContent("2 字符和 20 字符都能注册成功");
    expect(drawer).toHaveTextContent("SHOP-API-001");
    // The full id is still reachable, so two same-titled points stay distinct.
    expect(drawer).toHaveTextContent("TP-SHOP-001");
  });

  it("collapses a group when its header is clicked", async () => {
    const user = userEvent.setup();
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    const header = await screen.findByTestId("qa-testpoint-group-登录模块");
    await user.click(header.querySelector("button") as HTMLElement);
    expect(screen.queryByTestId("qa-testpoint-TP-SHOP-001")).not.toBeInTheDocument();
  });

  it("lists drafts and the cases that still have no chain", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-testpoints-drafts")).toHaveTextContent("TP-SHOP-003");
    expect(screen.getByTestId("qa-testpoints-unlinked")).toHaveTextContent("SHOP-API-009");
  });

  it("asks for a project when there is none", async () => {
    render(<QaTestpoints token="t" projects={[]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-empty")).toBeInTheDocument();
  });
});
