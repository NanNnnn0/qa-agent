export const DISPATCH_DESK_STORAGE_KEY = "nanobot-webui.dispatch-desk.v1";

export const DISPATCH_STATUSES = ["pending", "running", "done", "failed"] as const;

export type DispatchStatus = (typeof DISPATCH_STATUSES)[number];

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

export function activeDispatchTasks(tasks: readonly DispatchTask[]): DispatchTask[] {
  return tasks.filter((task) => isActiveDispatchStatus(task.status));
}

export function dispatchTasksByStatus(
  tasks: readonly DispatchTask[],
  status: DispatchStatus,
): DispatchTask[] {
  return tasks.filter((task) => task.status === status);
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
