import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QaApiAssets } from "@/components/qa/QaApiAssets";
import "@/i18n";
import { loadQaApiOperation, loadQaApiOperations } from "@/lib/qa-api";

vi.mock("@/lib/qa-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/qa-api")>();
  return {
    ...actual,
    loadQaApiOperations: vi.fn(),
    loadQaApiOperation: vi.fn(),
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

describe("API asset catalog view", () => {
  beforeEach(() => {
    vi.mocked(loadQaApiOperations).mockResolvedValue({
      items: [operation],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(loadQaApiOperation).mockResolvedValue(operation);
  });

  it("lists catalog operations", async () => {
    render(<QaApiAssets token="test" projects={[]} refreshSignal={0} />);
    const row = await screen.findByTestId("qa-api-operation-op-1");
    expect(row).toBeInTheDocument();
    expect(screen.getByText("/api/orders")).toBeInTheDocument();
    expect(screen.getByText("Create order")).toBeInTheDocument();
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
