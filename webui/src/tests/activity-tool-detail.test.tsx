import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentActivityCluster } from "@/components/thread/AgentActivityCluster";
import type { ToolProgressEvent, UIMessage } from "@/lib/types";

afterEach(cleanup);

function traceMessage(
  traces: string[],
  toolEvents: ToolProgressEvent[],
  id = "trace-1",
): UIMessage {
  return {
    id,
    role: "tool",
    kind: "trace",
    content: traces[0] ?? "",
    traces,
    toolEvents,
    createdAt: 1,
  };
}

function renderExpanded(messages: UIMessage[]) {
  render(
    <AgentActivityCluster
      messages={messages}
      isTurnStreaming={false}
      hasBodyBelow={false}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Worked" }));
}

function activityRow(label: string): HTMLElement {
  const row = screen.getAllByTestId("activity-line")
    .find((candidate) => (candidate.textContent ?? "").includes(label));
  expect(row, `activity row containing ${label}`).toBeDefined();
  return row as HTMLElement;
}

describe("activity tool call details", () => {
  it("reveals the arguments and result of a completed tool call", () => {
    const line = 'qa_case({"action":"get","case_id":"CHEYICHA-API-API-001"})';
    renderExpanded([
      traceMessage([line], [{
        phase: "end",
        call_id: "call-1",
        name: "qa_case",
        arguments: { action: "get", case_id: "CHEYICHA-API-API-001" },
        result: { ok: true, title: "Login case" },
      }]),
    ]);

    const row = activityRow("Completed Qa case");
    expect(row.tagName).toBe("BUTTON");
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("activity-tool-detail")).not.toBeInTheDocument();

    fireEvent.click(row);

    expect(row).toHaveAttribute("aria-expanded", "true");
    const detail = screen.getByTestId("activity-tool-detail");
    expect(detail).toHaveTextContent('"case_id": "CHEYICHA-API-API-001"');
    expect(detail).toHaveTextContent('"ok": true');
    expect(within(detail).getByText("Arguments")).toBeInTheDocument();
    expect(within(detail).getByText("Result")).toBeInTheDocument();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("activity-tool-detail")).not.toBeInTheDocument();
  });

  it("lists every call kept inside a grouped activity row", () => {
    const first = 'qa_case({"action":"list","project_id":"SHOP"})';
    const second = 'qa_case({"action":"get","case_id":"SHOP-001"})';
    renderExpanded([
      traceMessage([first, second], [
        {
          phase: "end",
          call_id: "call-1",
          name: "qa_case",
          arguments: { action: "list", project_id: "SHOP" },
          result: [{ id: "SHOP-001" }],
        },
        {
          phase: "end",
          call_id: "call-2",
          name: "qa_case",
          arguments: { action: "get", case_id: "SHOP-001" },
          result: { ok: true },
        },
      ]),
    ]);

    const row = activityRow("Completed Qa case");
    expect(row).toHaveAttribute("aria-label", "Completed Qa case, 2 actions");
    fireEvent.click(row);

    const entries = within(screen.getByTestId("activity-tool-detail"))
      .getAllByTestId("activity-tool-detail-entry");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent('"project_id": "SHOP"');
    expect(entries[1]).toHaveTextContent('"case_id": "SHOP-001"');
  });

  it("shows the full shell command and its output", () => {
    const command = "cd /root/.nanobot/workspace/qa-projects/cheyicha-api && npm test";
    const line = `exec(${JSON.stringify({ command, timeout: 600 })})`;
    renderExpanded([
      traceMessage([line], [{
        phase: "end",
        call_id: "call-exec",
        name: "exec",
        arguments: { command, timeout: 600 },
        result: "2829 passed",
      }]),
    ]);

    fireEvent.click(activityRow("Ran command"));

    const detail = screen.getByTestId("activity-tool-detail");
    expect(within(detail).getByText("Command")).toBeInTheDocument();
    expect(within(detail).getByText(command)).toBeInTheDocument();
    expect(detail).toHaveTextContent('"timeout": 600');
    expect(detail).toHaveTextContent("2829 passed");
  });

  it("collapses long output behind an explicit show-all control", () => {
    const output = "line of output\n".repeat(400);
    const line = 'exec({"command":"npm test"})';
    renderExpanded([
      traceMessage([line], [{
        phase: "end",
        call_id: "call-exec",
        name: "exec",
        arguments: { command: "npm test" },
        result: output,
      }]),
    ]);

    fireEvent.click(activityRow("Ran command"));

    const detail = screen.getByTestId("activity-tool-detail");
    expect(detail.textContent?.length).toBeLessThan(output.length);
    const showAll = within(detail).getByRole("button", { name: "Show all" });
    fireEvent.click(showAll);

    expect(detail.textContent?.length).toBeGreaterThanOrEqual(output.length);
    expect(within(detail).getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("keeps rows without recorded payload non-interactive", () => {
    renderExpanded([traceMessage(["search()"], [])]);

    const row = activityRow("Completed Search");
    expect(row.tagName).toBe("DIV");
    expect(row).not.toHaveAttribute("aria-expanded");
    expect(screen.queryByTestId("activity-tool-detail")).not.toBeInTheDocument();
  });
});
