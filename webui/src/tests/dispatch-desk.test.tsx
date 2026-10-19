import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DispatchDeskProvider } from "@/components/dispatch/DispatchDeskProvider";
import {
  DispatchArtifactPreview,
  DispatchHomeExtras,
  DispatchTaskView,
} from "@/components/dispatch/DispatchTaskView";
import { DispatchRail } from "@/components/dispatch/DispatchRail";
import { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";
import { setAppLanguage } from "@/i18n";
import {
  activeDispatchTasks,
  dispatchTaskTitle,
  sessionsWithoutDispatchChildren,
  visibleDispatchTask,
  type DispatchTask,
} from "@/lib/dispatch-desk";

function task(partial: Pick<DispatchTask, "id" | "status"> & Partial<DispatchTask>): DispatchTask {
  return {
    title: partial.title ?? partial.id,
    prompt: partial.prompt ?? partial.id,
    createdAt: partial.createdAt ?? 1,
    sessionKey: partial.sessionKey ?? null,
    artifacts: partial.artifacts ?? [],
    id: partial.id,
    status: partial.status,
  };
}

describe("dispatch desk model", () => {
  it("keeps only not-started and in-progress tasks on the active rail", () => {
    const tasks = [
      task({ id: "pending", status: "pending" }),
      task({ id: "running", status: "running" }),
      task({ id: "done", status: "done" }),
      task({ id: "failed", status: "failed" }),
    ];
    expect(activeDispatchTasks(tasks).map((item) => item.id)).toEqual(["pending", "running"]);
  });

  it("names the checklist template and hides child topics from the flat list", () => {
    const prompt = "Run a QA checklist";
    expect(dispatchTaskTitle(prompt, prompt, "Run checklist")).toBe("Run checklist");
    expect(dispatchTaskTitle("x".repeat(30), prompt, "Run checklist").endsWith("…")).toBe(true);
    const tasks = [task({ id: "child", status: "running", sessionKey: "websocket:child" })];
    expect(sessionsWithoutDispatchChildren(
      [{ key: "websocket:child" }, { key: "websocket:other" }],
      tasks,
    ).map((session) => session.key)).toEqual(["websocket:other"]);
    expect(visibleDispatchTask(tasks, "websocket:child", null)?.id).toBe("child");
    expect(visibleDispatchTask(tasks, null, "child")).toBeNull();
  });
});

function DeskScreen({
  activeKey,
  outcome,
}: {
  activeKey: string | null;
  outcome: "session" | "failed";
}) {
  const desk = useDispatchDesk();
  const [openArtifactId, setOpenArtifactId] = useState<string | null>(null);
  if (!desk) return null;
  const bound = visibleDispatchTask(desk.tasks, activeKey, desk.focusedTaskId);
  const artifact = bound?.artifacts.find((item) => item.id === openArtifactId) ?? null;
  return (
    <>
      <DispatchHomeExtras
        onDispatch={(prompt) => {
          const id = desk.startDispatch(prompt);
          desk.finishDispatch(id, outcome === "session" ? "websocket:child-1" : null);
        }}
      />
      <DispatchRail activeKey={activeKey} />
      {bound ? <DispatchTaskView task={bound} onOpenArtifact={setOpenArtifactId} /> : null}
      {artifact ? (
        <DispatchArtifactPreview artifact={artifact} onClose={() => setOpenArtifactId(null)} />
      ) : null}
    </>
  );
}

function DeskHarness({ outcome }: { outcome: "session" | "failed" }) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  return (
    <DispatchDeskProvider
      persist={false}
      onOpenSession={setActiveKey}
      onGoHome={() => setActiveKey(null)}
    >
      <DeskScreen activeKey={activeKey} outcome={outcome} />
    </DispatchDeskProvider>
  );
}

describe("dispatch desk click path", () => {
  it("dispatches a checklist, drills into the child, and opens its output", () => {
    render(<DeskHarness outcome="session" />);

    expect(screen.getByRole("heading", { name: "Nan-Agent" })).toBeInTheDocument();
    expect(screen.getByText("No active child tasks")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run checklist" }));

    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    expect(within(rail).queryByRole("button", { name: /Done/ })).not.toBeInTheDocument();
    fireEvent.click(within(rail).getByRole("button", { name: /Run checklist/ }));

    const taskView = screen.getByTestId("dispatch-task-view");
    expect(within(taskView).getByText("In progress")).toBeInTheDocument();
    expect(within(taskView).getByText("Dispatched to a topic")).toBeInTheDocument();
    expect(within(taskView).getByText("Output")).toBeInTheDocument();
    expect(within(taskView).getByText("Local preview")).toBeInTheDocument();
    fireEvent.click(within(taskView).getByRole("button", { name: "Open Checklist" }));

    const preview = screen.getByTestId("dispatch-artifact-preview");
    expect(preview).toHaveTextContent("Main path");
    expect(preview).toHaveTextContent("Local preview");
    expect(preview).toHaveTextContent("The gateway has no task-artifact API yet.");
  });

  it("filters every status from All tasks and keeps finished work off the rail", () => {
    const tasks = [
      task({ id: "running", title: "Active check", status: "running", sessionKey: "websocket:running" }),
      task({ id: "pending", title: "Waiting check", status: "pending" }),
      task({ id: "done", title: "Finished check", status: "done", sessionKey: "websocket:done" }),
      task({ id: "failed", title: "Broken check", status: "failed" }),
    ];
    render(
      <DispatchDeskProvider
        persist={false}
        initialTasks={tasks}
        onOpenSession={() => {}}
        onGoHome={() => {}}
      >
        <DispatchRail activeKey={null} />
      </DispatchDeskProvider>,
    );

    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    expect(within(rail).getByRole("button", { name: /Active check/ })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: /Waiting check/ })).toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: /Finished check/ })).not.toBeInTheDocument();
    expect(within(rail).queryByRole("button", { name: /Broken check/ })).not.toBeInTheDocument();

    fireEvent.click(within(rail).getByRole("button", { name: "All tasks" }));
    const dialog = screen.getByRole("dialog", { name: "All tasks" });
    expect(within(dialog).getByRole("button", { name: /Active check/ })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Done", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Finished check/ })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Active check/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Failed", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Broken check/ })).toBeInTheDocument();
  });

  it("archives a task off the rail and restores it from the archived list", async () => {
    const tasks = [
      task({
        id: "archivable",
        title: "Archivable check",
        status: "running",
        sessionKey: "websocket:archivable",
      }),
    ];
    render(
      <DispatchDeskProvider
        persist={false}
        initialTasks={tasks}
        onOpenSession={() => {}}
        onGoHome={() => {}}
      >
        <DispatchRail activeKey={null} />
      </DispatchDeskProvider>,
    );

    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    expect(within(rail).getByRole("button", { name: /Archivable check/ })).toBeInTheDocument();

    fireEvent.pointerDown(
      within(rail).getByRole("button", { name: "任务操作" }),
      { button: 0, ctrlKey: false },
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: "归档" }));

    expect(within(rail).queryByRole("button", { name: /Archivable check/ })).not.toBeInTheDocument();

    fireEvent.click(within(rail).getByRole("button", { name: "All tasks" }));
    const dialog = screen.getByRole("dialog", { name: "All tasks" });
    fireEvent.click(within(dialog).getByRole("button", { name: "已归档", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Archivable check/ }))
      .toHaveTextContent("已归档");

    fireEvent.click(within(dialog).getByRole("button", { name: "恢复", exact: true }));
    expect(within(dialog).queryByRole("button", { name: /Archivable check/ })).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "全部", exact: true }));
    fireEvent.click(within(dialog).getByRole("button", { name: "In progress", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Archivable check/ })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(await within(rail).findByRole("button", { name: /Archivable check/ })).toBeInTheDocument();
  });

  it("follows the chat session instead of freezing the dispatch status", async () => {
    const createdAt = Date.parse("2026-01-01T00:00:00.000Z");
    const tasks = [
      task({ id: "live", title: "Live check", status: "running", createdAt, sessionKey: "websocket:live" }),
      task({ id: "settled", title: "Settled check", status: "running", createdAt, sessionKey: "websocket:settled" }),
    ];
    render(
      <DispatchDeskProvider
        persist={false}
        initialTasks={tasks}
        sessions={[
          { key: "websocket:live", runStartedAt: Math.floor(Date.now() / 1000) - 5, updatedAt: "2026-01-01T00:00:05.000Z" },
          { key: "websocket:settled", runStartedAt: null, updatedAt: "2026-01-01T00:01:00.000Z" },
        ]}
        onOpenSession={() => {}}
        onGoHome={() => {}}
      >
        <DispatchRail activeKey={null} />
      </DispatchDeskProvider>,
    );

    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    expect(within(rail).getByRole("button", { name: /Live check/ })).toHaveTextContent("In progress");
    expect(within(rail).queryByRole("button", { name: /Settled check/ })).not.toBeInTheDocument();

    fireEvent.click(within(rail).getByRole("button", { name: "All tasks" }));
    const dialog = screen.getByRole("dialog", { name: "All tasks" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Done", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Settled check/ })).toHaveTextContent("Done");
    fireEvent.click(within(dialog).getByRole("button", { name: "In progress", exact: true }));
    expect(within(dialog).getByRole("button", { name: /Live check/ })).toHaveTextContent("In progress");
  });

  it("mirrors archive and restore onto the task's chat session", async () => {
    const onArchiveSession = vi.fn();
    const tasks = [
      task({ id: "mirror", title: "Mirror check", status: "running", sessionKey: "websocket:mirror" }),
    ];
    render(
      <DispatchDeskProvider
        persist={false}
        initialTasks={tasks}
        onOpenSession={() => {}}
        onGoHome={() => {}}
        onArchiveSession={onArchiveSession}
      >
        <DispatchRail activeKey={null} />
      </DispatchDeskProvider>,
    );

    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    fireEvent.pointerDown(
      within(rail).getByRole("button", { name: "任务操作" }),
      { button: 0, ctrlKey: false },
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: "归档" }));
    expect(onArchiveSession).toHaveBeenCalledWith("websocket:mirror", true);

    fireEvent.click(within(rail).getByRole("button", { name: "All tasks" }));
    const dialog = screen.getByRole("dialog", { name: "All tasks" });
    fireEvent.click(within(dialog).getByRole("button", { name: "已归档", exact: true }));
    fireEvent.click(within(dialog).getByRole("button", { name: "恢复", exact: true }));
    expect(onArchiveSession).toHaveBeenCalledWith("websocket:mirror", false);
  });

  it("shows a failed dispatch on the home desk when no topic was created", () => {
    render(<DeskHarness outcome="failed" />);
    fireEvent.click(screen.getByRole("button", { name: "Run checklist" }));
    const taskView = screen.getByTestId("dispatch-task-view");
    expect(within(taskView).getByText("Failed")).toBeInTheDocument();
    expect(within(taskView).getByText("Could not open a topic")).toBeInTheDocument();
    const rail = screen.getByRole("region", { name: "Dispatch desk" });
    expect(within(rail).getByText("No active child tasks")).toBeInTheDocument();
    fireEvent.click(within(taskView).getByRole("button", { name: "Open Checklist" }));
    expect(screen.getByTestId("dispatch-artifact-preview")).toHaveTextContent("Main path");
  });

  it("uses the Chinese desk labels", async () => {
    await setAppLanguage("zh-CN");
    render(<DeskHarness outcome="session" />);
    expect(screen.getByRole("heading", { name: "Nan-Agent" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "总调度" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "执行检查清单" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "全部任务" })).toBeInTheDocument();
  });
});
