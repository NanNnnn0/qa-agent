export const DISPATCH_DESK_STORAGE_KEY = "nanobot-webui.dispatch-desk.v1";

export const DISPATCH_STATUSES = ["pending", "running", "done", "failed"] as const;

export type DispatchStatus = (typeof DISPATCH_STATUSES)[number];

/** A turn left behind by a crash stops counting as running after this long. */
export const STALE_RUNNING_SECONDS = 30 * 60;

/** Local desk preview. The gateway has no parent/child artifact API. */
export interface DispatchArtifact {
  id: string;
  title: string;
  summary: string;
  fileName: string;
  language: string;
  content: string;
  source: "local-desk";
}

/**
 * A child of the home dispatcher.
 * `sessionKey` is an ordinary WebUI topic (`websocket:<chat id>`) when the
 * gateway accepted `new_chat`. Status and artifacts live in this browser.
 */
export interface DispatchTask {
  id: string;
  title: string;
  prompt: string;
  status: DispatchStatus;
  createdAt: number;
  sessionKey: string | null;
  artifacts: DispatchArtifact[];
  /**
   * Codex-style archive: the row leaves the dispatch rail but stays in storage.
   * Absent means not archived, so desks written before this field keep working.
   */
  archived?: boolean;
}

function isStatus(value: unknown): value is DispatchStatus {
  return typeof value === "string" && (DISPATCH_STATUSES as readonly string[]).includes(value);
}

function isArtifact(value: unknown): value is DispatchArtifact {
  if (!value || typeof value !== "object") return false;
  const artifact = value as Partial<DispatchArtifact>;
  return typeof artifact.id === "string"
    && typeof artifact.title === "string"
    && typeof artifact.summary === "string"
    && typeof artifact.fileName === "string"
    && typeof artifact.language === "string"
    && typeof artifact.content === "string"
    && artifact.source === "local-desk";
}

export function isDispatchTask(value: unknown): value is DispatchTask {
  if (!value || typeof value !== "object") return false;
  const task = value as Partial<DispatchTask>;
  return typeof task.id === "string"
    && typeof task.title === "string"
    && typeof task.prompt === "string"
    && isStatus(task.status)
    && typeof task.createdAt === "number"
    && (task.sessionKey === null || typeof task.sessionKey === "string")
    && (task.archived === undefined || typeof task.archived === "boolean")
    && Array.isArray(task.artifacts)
    && task.artifacts.every(isArtifact);
}

export function readDispatchTasks(raw: string | null): DispatchTask[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isDispatchTask);
  } catch {
    return [];
  }
}

export function isActiveDispatchStatus(status: DispatchStatus): boolean {
  return status === "pending" || status === "running";
}

export function isArchivedDispatchTask(task: DispatchTask): boolean {
  return task.archived === true;
}

/** Rail rows. Archiving only hides the row; the task stays in storage. */
export function visibleDispatchTasks(tasks: readonly DispatchTask[]): DispatchTask[] {
  return tasks.filter((task) => !isArchivedDispatchTask(task));
}

/** The All tasks sheet's archived view, and the restore source. */
export function archivedDispatchTasks(tasks: readonly DispatchTask[]): DispatchTask[] {
  return tasks.filter(isArchivedDispatchTask);
}

export function activeDispatchTasks(tasks: readonly DispatchTask[]): DispatchTask[] {
  return tasks.filter((task) => isActiveDispatchStatus(task.status));
}

export function dispatchTasksByStatus(
  tasks: readonly DispatchTask[],
  status: DispatchStatus,
): DispatchTask[] {
  return tasks.filter((task) => task.status === status);
}

/** The session facts a dispatch row reflects. `ChatSummary` already fits. */
export interface DispatchSessionSummary {
  key: string;
  /** Unix epoch seconds while a turn is in flight. */
  runStartedAt?: number | null;
  /** ISO timestamp of the last session update. */
  updatedAt?: string | null;
}

/**
 * A dispatch row mirrors its chat: the stored status is only the starting
 * point, and the session's live turn wins afterwards. An archived row is
 * settled history, so it never reports itself as running.
 */
export function dispatchTaskStatus(
  task: DispatchTask,
  sessions: readonly DispatchSessionSummary[],
): DispatchStatus {
  // A dispatch that never opened a topic stays failed; no session can override it.
  if (task.status === "failed") return "failed";
  if (task.archived) return "done";
  if (!task.sessionKey) return task.status === "pending" ? "pending" : task.status;
  const session = sessions.find((item) => item.key === task.sessionKey);
  if (!session) return task.status;
  if (session.runStartedAt) {
    const ageSeconds = Date.now() / 1000 - session.runStartedAt;
    if (ageSeconds < STALE_RUNNING_SECONDS) return "running";
  }
  const updatedAt = session.updatedAt ? Date.parse(session.updatedAt) : Number.NaN;
  if (Number.isFinite(updatedAt) && updatedAt > task.createdAt) return "done";
  return task.status;
}

/** Copy of the desk with every row's status derived from its live session. */
export function withDerivedDispatchStatus(
  tasks: readonly DispatchTask[],
  sessions: readonly DispatchSessionSummary[],
): DispatchTask[] {
  return tasks.map((task) => {
    const status = dispatchTaskStatus(task, sessions);
    return status === task.status ? task : { ...task, status };
  });
}

export function dispatchTaskTitle(
  prompt: string,
  checklistPrompt: string,
  checklistTitle: string,
): string {
  const trimmed = prompt.trim();
  if (trimmed === checklistPrompt.trim()) return checklistTitle;
  const line = trimmed.split("\n")[0] ?? trimmed;
  const chars = Array.from(line);
  if (chars.length <= 24) return line;
  return `${chars.slice(0, 24).join("")}…`;
}

export function sessionsWithoutDispatchChildren<T extends { key: string }>(
  sessions: readonly T[],
  tasks: readonly DispatchTask[],
): T[] {
  const hidden = new Set(
    tasks.flatMap((task) => (task.sessionKey ? [task.sessionKey] : [])),
  );
  if (hidden.size === 0) return [...sessions];
  return sessions.filter((session) => !hidden.has(session.key));
}

/** Home shows a session-less focused task. An open topic shows its own child. */
export function visibleDispatchTask(
  tasks: readonly DispatchTask[],
  sessionKey: string | null,
  focusedTaskId: string | null,
): DispatchTask | null {
  if (sessionKey) {
    return tasks.find((task) => task.sessionKey === sessionKey) ?? null;
  }
  if (!focusedTaskId) return null;
  const focused = tasks.find((task) => task.id === focusedTaskId) ?? null;
  return focused && !focused.sessionKey ? focused : null;
}
