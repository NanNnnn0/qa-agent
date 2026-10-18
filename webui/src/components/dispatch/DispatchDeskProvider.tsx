import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { AllTasksSheet } from "@/components/dispatch/AllTasksSheet";
import {
  DispatchDeskContext,
  type DispatchDeskApi,
} from "@/components/dispatch/dispatch-desk-context";
import {
  DISPATCH_DESK_STORAGE_KEY,
  dispatchTaskTitle,
  readDispatchTasks,
  type DispatchArtifact,
  type DispatchTask,
} from "@/lib/dispatch-desk";

export type { DispatchDeskApi };
export { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";

interface DispatchDeskProviderProps {
  children: ReactNode;
  onOpenSession: (sessionKey: string) => void;
  onGoHome: () => void;
  initialTasks?: DispatchTask[];
  persist?: boolean;
  homeActionRef?: MutableRefObject<(() => void) | null>;
}

function readStoredTasks(persist: boolean): DispatchTask[] {
  if (!persist || typeof window === "undefined") return [];
  try {
    return readDispatchTasks(window.localStorage.getItem(DISPATCH_DESK_STORAGE_KEY));
  } catch {
    return [];
  }
}

export function DispatchDeskProvider({
  children,
  onOpenSession,
  onGoHome,
  initialTasks,
  persist = true,
  homeActionRef,
}: DispatchDeskProviderProps) {
  const { t } = useTranslation();
  const [tasks, setTasks] = useState<DispatchTask[]>(
    () => initialTasks ?? readStoredTasks(persist),
  );
  const [focusedTaskId, setFocusedTaskId] = useState<string | null>(null);
  const [allTasksOpen, setAllTasksOpen] = useState(false);

  useEffect(() => {
    if (!persist || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(DISPATCH_DESK_STORAGE_KEY, JSON.stringify(tasks));
    } catch {
      // The desk still works for this page if storage is blocked.
    }
  }, [persist, tasks]);

  const startDispatch = useCallback((prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed) return "";
    const id = crypto.randomUUID();
    const title = dispatchTaskTitle(
      trimmed,
      t("dispatch.checklistPrompt"),
      t("dispatch.templateChecklist"),
    );
    const artifact: DispatchArtifact = {
      id: `${id}:checklist`,
      title: t("dispatch.artifactTitle"),
      summary: t("dispatch.artifactSummary"),
      fileName: "qa-checklist.md",
      language: "markdown",
      content: t("dispatch.artifactBody", { prompt: trimmed }),
      source: "local-desk",
    };
    const task: DispatchTask = {
      id,
      title,
      prompt: trimmed,
      status: "pending",
      createdAt: Date.now(),
      sessionKey: null,
      artifacts: [artifact],
    };
    setTasks((current) => [task, ...current]);
    return id;
  }, [t]);

  const finishDispatch = useCallback((id: string, sessionKey: string | null) => {
    if (!id) return;
    setTasks((current) => current.map((task) => (
      task.id === id
        ? {
            ...task,
            status: sessionKey ? "running" : "failed",
            sessionKey,
          }
        : task
    )));
    if (!sessionKey) setFocusedTaskId(id);
  }, []);

  const selectTask = useCallback((id: string) => {
    const task = tasks.find((item) => item.id === id);
    if (!task) return;
    setFocusedTaskId(id);
    setAllTasksOpen(false);
    if (task.sessionKey) onOpenSession(task.sessionKey);
  }, [onOpenSession, tasks]);

  const selectDispatcher = useCallback(() => {
    setFocusedTaskId(null);
    setAllTasksOpen(false);
    onGoHome();
  }, [onGoHome]);

  const clearFocus = useCallback(() => {
    setFocusedTaskId(null);
  }, []);

  useEffect(() => {
    if (!homeActionRef) return undefined;
    homeActionRef.current = clearFocus;
    return () => {
      homeActionRef.current = null;
    };
  }, [clearFocus, homeActionRef]);

  const api = useMemo<DispatchDeskApi>(() => ({
    tasks,
    focusedTaskId,
    allTasksOpen,
    setAllTasksOpen,
    startDispatch,
    finishDispatch,
    selectTask,
    selectDispatcher,
    clearFocus,
  }), [
    allTasksOpen,
    clearFocus,
    finishDispatch,
    focusedTaskId,
    selectDispatcher,
    selectTask,
    startDispatch,
    tasks,
  ]);

  return (
    <DispatchDeskContext.Provider value={api}>
      {children}
      <AllTasksSheet />
    </DispatchDeskContext.Provider>
  );
}
