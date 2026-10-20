import { render, screen } from "@testing-library/react";
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
      title: "username boundary",
      sources: ["API-SHOP-01"],
      method: "boundary",
      risk: "low",
      status: "reviewed",
      module: "SHOP",
      owner: "agent",
      tags: [],
      note: null,
      case_count: 2,
      reviewed_case_count: 2,
    },
  ],
  drafts: [
    {
      batch: "agent",
      id: "TP-SHOP-002",
      kind: "testpoint",
      path: "draft/agent/testpoints/TP-SHOP-002.yaml",
      status: "pending",
      valid: true,
      problems: [],
    },
  ],
  unlinked_cases: [
    { case_id: "case-1", code: "SHOP-API-009", title: "unlinked", status: "ready", legacy: true },
  ],
  counts: { sources: 1, testpoints: 1, drafts: 1, unlinked_cases: 1, cases: 3 },
};

describe("test points tab", () => {
  beforeEach(() => {
    vi.mocked(loadQaTestpoints).mockResolvedValue(assets);
  });

  it("shows the chain counts", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-testpoints-count-sources")).toHaveTextContent("1");
    expect(screen.getByTestId("qa-testpoints-count-testpoints")).toHaveTextContent("1");
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

  it("lists drafts and the cases that still have no chain", async () => {
    render(<QaTestpoints token="t" projects={[project]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-testpoints-drafts")).toHaveTextContent("TP-SHOP-002");
    expect(screen.getByTestId("qa-testpoints-unlinked")).toHaveTextContent("SHOP-API-009");
  });

  it("asks for a project when there is none", async () => {
    render(<QaTestpoints token="t" projects={[]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-empty")).toBeInTheDocument();
  });
});
