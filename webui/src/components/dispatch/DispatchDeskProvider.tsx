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
  withDerivedDispatchStatus,
  type DispatchArtifact,
  type DispatchSessionSummary,
  type DispatchTask,
} from "@/lib/dispatch-desk";

export type { DispatchDeskApi };
export { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";

interface DispatchDeskProviderProps {
  children: ReactNode;
  onOpenSession: (sessionKey: string) => void;
  onGoHome: () => void;
  /** Live topics, so a row's status follows its chat instead of freezing. */
  sessions?: readonly DispatchSessionSummary[];
  /** Mirrors a task's archive state onto its chat in the main sidebar. */
  onArchiveSession?: (sessionKey: string, archived: boolean) => void;
  initialTasks?: DispatchTask[];
  persist?: boolean;
  homeActionRef?: MutableRefObject<(() => void) | null>;
}

const NO_SESSIONS: readonly DispatchSessionSummary[] = [];

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
  sessions = NO_SESSIONS,
  onArchiveSession,
  initialTasks,
  persist = true,
  homeActionRef,
}: DispatchDeskProviderProps) {
  const { t } = useTranslation();
  // The stored rows keep their own status; the API exposes a derived view.
  const [storedTasks, setStoredTasks] = useState<DispatchTask[]>(
    () => initialTasks ?? readStoredTasks(persist),
  );
  const [focusedTaskId, setFocusedTaskId] = useState<string | null>(null);
  const [allTasksOpen, setAllTasksOpen] = useState(false);
  const tasks = useMemo(
    () => withDerivedDispatchStatus(storedTasks, sessions),
    [sessions, storedTasks],
  );

  useEffect(() => {
    if (!persist || typeof window === "undefined") return;
    try {
      window.localStorage.setItem(DISPATCH_DESK_STORAGE_KEY, JSON.stringify(storedTasks));
    } catch {
      // The desk still works for this page if storage is blocked.
    }
  }, [persist, storedTasks]);

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
    setStoredTasks((current) => [task, ...current]);
    return id;
  }, [t]);

  const finishDispatch = useCallback((id: string, sessionKey: string | null) => {
    if (!id) return;
    setStoredTasks((current) => current.map((task) => (
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

  // Archiving only flips the desk row; the chat is never deleted. The topic is
  // archived alongside the row so the main sidebar hides it the same way.
  const archiveTask = useCallback((id: string) => {
    const target = storedTasks.find((task) => task.id === id);
    if (!target) return;
    setStoredTasks((current) => current.map((task) => (
      task.id === id ? { ...task, archived: true } : task
    )));
    setFocusedTaskId((current) => (current === id ? null : current));
    if (target.sessionKey) onArchiveSession?.(target.sessionKey, true);
  }, [onArchiveSession, storedTasks]);

  const restoreTask = useCallback((id: string) => {
    const target = storedTasks.find((task) => task.id === id);
    if (!target) return;
    setStoredTasks((current) => current.map((task) => (
      task.id === id ? { ...task, archived: false } : task
    )));
    if (target.sessionKey) onArchiveSession?.(target.sessionKey, false);
  }, [onArchiveSession, storedTasks]);

  const selectTask = useCallback((id: string) => {
    const task = storedTasks.find((item) => item.id === id);
    if (!task) return;
    setFocusedTaskId(id);
    setAllTasksOpen(false);
    if (task.sessionKey) onOpenSession(task.sessionKey);
  }, [onOpenSession, storedTasks]);

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
    archiveTask,
    restoreTask,
    selectTask,
    selectDispatcher,
    clearFocus,
  }), [
    allTasksOpen,
    archiveTask,
    clearFocus,
    finishDispatch,
    focusedTaskId,
    restoreTask,
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
