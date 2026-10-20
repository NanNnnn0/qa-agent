import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QaApiAssets } from "@/components/qa/QaApiAssets";
import "@/i18n";
import { loadQaApiOperation, loadQaApiOperations, loadQaCases } from "@/lib/qa-api";

vi.mock("@/lib/qa-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/qa-api")>();
  return {
    ...actual,
    loadQaApiOperations: vi.fn(),
    loadQaApiOperation: vi.fn(),
    loadQaCases: vi.fn(),
  };
});

const operation = {
  id: "op-1",
  project_id: "proj-1",
  method: "POST",
  path: "/api/orders",
  path_template: "/api/orders",
  operation_id: "createOrder",
  summary: "Create order",
  status: "active" as const,
  source_kind: "spec",
  source_ref: "specs/orders.json",
  source_version: "v1",
  created_at: "2026-10-19T00:00:00Z",
  updated_at: "2026-10-19T00:00:00Z",
  evidence: [{ kind: "openapi", ref: "#/paths/~1api~1orders/post" }],
  spec: { operation_id: "createOrder" },
};

const apiCase = {
  id: "case-1",
  project_id: "proj-1",
  code: "SHOP-API-001",
  title: "create an order",
  kind: "api" as const,
  priority: "P0" as const,
  status: "ready" as const,
  preconditions: "",
  steps: [],
  expected: "returns 201",
  tags: ["orders"],
  api: {
    request: { method: "POST", path: "/api/orders", body: { qty: 1 } },
    assertions: [{ type: "status", expect: 201 }],
  },
  source: "ai",
  author: "",
  created_at: "2026-10-19T00:00:00Z",
  updated_at: "2026-10-19T00:00:00Z",
};

/** A case whose concrete path parameter still has to find `/api/orders/{}`. */
const parameterizedCase = {
  ...apiCase,
  id: "case-2",
  code: "SHOP-API-002",
  title: "read one order",
  api: {
    request: { method: "GET", path: "/api/orders/42" },
    assertions: [{ type: "status", expect: 200 }],
  },
};

const unrelatedCase = {
  ...apiCase,
  id: "case-3",
  code: "SHOP-API-003",
  title: "login",
  api: {
    request: { method: "POST", path: "/api/auth/login" },
    assertions: [{ type: "status", expect: 200 }],
  },
};

describe("API asset catalog view", () => {
  beforeEach(() => {
    vi.mocked(loadQaApiOperations).mockResolvedValue({
      items: [operation],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(loadQaApiOperation).mockResolvedValue(operation);
    vi.mocked(loadQaCases).mockResolvedValue({
      items: [apiCase, unrelatedCase],
      total: 2,
      limit: 500,
      offset: 0,
    });
  });

  it("lists catalog operations", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    const row = await screen.findByTestId("qa-api-operation-op-1");
    expect(row).toBeInTheDocument();
    expect(screen.getByText("/api/orders")).toBeInTheDocument();
    expect(screen.getByText("Create order")).toBeInTheDocument();
  });

  it("counts only the cases that belong to the operation", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    const row = await screen.findByTestId("qa-api-operation-op-1");
    // `login` posts to another path, so the count stays at one.
    await waitFor(() => expect(within(row).getByText("1")).toBeInTheDocument());
  });

  it("nests the operation's cases under the row", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    fireEvent.click(await screen.findByTestId("qa-api-operation-toggle-op-1"));

    const panel = await screen.findByTestId("qa-api-operation-cases-op-1");
    expect(within(panel).getByText("SHOP-API-001")).toBeInTheDocument();
    expect(within(panel).getByText("create an order")).toBeInTheDocument();
    expect(within(panel).queryByText("SHOP-API-003")).not.toBeInTheDocument();
  });

  it("matches a case with a concrete path parameter", async () => {
    vi.mocked(loadQaCases).mockResolvedValue({
      items: [parameterizedCase],
      total: 1,
      limit: 500,
      offset: 0,
    });
    vi.mocked(loadQaApiOperations).mockResolvedValue({
      items: [
        {
          ...operation,
          id: "op-2",
          method: "GET",
          path: "/api/orders/{}",
          path_template: "/api/orders/{}",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    fireEvent.click(await screen.findByTestId("qa-api-operation-toggle-op-2"));

    const panel = await screen.findByTestId("qa-api-operation-cases-op-2");
    expect(within(panel).getByText("SHOP-API-002")).toBeInTheDocument();
  });

  it("says so when an operation has no cases yet", async () => {
    vi.mocked(loadQaCases).mockResolvedValue({
      items: [unrelatedCase],
      total: 1,
      limit: 500,
      offset: 0,
    });
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    fireEvent.click(await screen.findByTestId("qa-api-operation-toggle-op-1"));

    await screen.findByTestId("qa-api-operation-cases-op-1");
    expect(screen.queryByTestId("qa-api-case-case-1")).not.toBeInTheDocument();
  });

  it("opens the case drawer from the nested list", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    fireEvent.click(await screen.findByTestId("qa-api-operation-toggle-op-1"));
    fireEvent.click(await screen.findByTestId("qa-api-case-case-1"));

    await waitFor(() => expect(screen.getByTestId("qa-api-case-drawer")).toBeInTheDocument());
    expect(await screen.findByText("SHOP-API-001 · create an order")).toBeInTheDocument();
    expect(await screen.findByText("returns 201")).toBeInTheDocument();
  });

  it("opens the operation drawer with its evidence", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    fireEvent.click(await screen.findByTestId("qa-api-operation-op-1"));
    await waitFor(() =>
      expect(screen.getByTestId("qa-api-operation-drawer")).toBeInTheDocument(),
    );
    expect(await screen.findByText("#/paths/~1api~1orders/post")).toBeInTheDocument();
    expect(await screen.findByText("POST /api/orders")).toBeInTheDocument();
  });

  it("shows the empty state before any material is ingested", async () => {
    vi.mocked(loadQaApiOperations).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    expect(await screen.findByTestId("qa-api-assets-empty")).toBeInTheDocument();
  });
});
