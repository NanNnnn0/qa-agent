import { fetchWithTimeout } from "./http";

/**
 * Typed client for the QA platform API (`/api/qa/*`).
 *
 * Reads are ordinary authenticated GETs with `Authorization: Bearer <token>`.
 * Writes are ONLY accepted through the authenticated WebSocket mutation
 * channel (the `qa.*` actions below) — a plain POST answers 405 by design.
 *
 * This module deliberately keeps its own small `request()` helper instead of
 * reaching into `lib/api.ts` internals; the behaviour (Bearer token,
 * `fetchWithTimeout`, JSON error extraction) mirrors that module.
 */

const QA_READ_TIMEOUT_MS = 20_000;
const QA_MUTATION_TIMEOUT_MS = 20_000;
/** `qa.run.start` executes the suite synchronously before answering. */
export const QA_RUN_TIMEOUT_MS = 180_000;
/** `qa.run.import` parses a whole CI report synchronously before answering. */
export const QA_RUN_IMPORT_TIMEOUT_MS = 120_000;

export class QaApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "QaApiError";
  }
}

/** The slice of `NanobotClient` the QA mutations need. */
export interface QaMutationTransport {
  requestMutation<T>(
    action: string,
    payload?: Record<string, unknown>,
    timeoutMs?: number,
  ): Promise<T>;
}

// -- entity types ---------------------------------------------------------

export type QaCaseKind = "api" | "ui" | "manual";
export type QaCasePriority = "P0" | "P1" | "P2" | "P3";
export type QaCaseStatus = "draft" | "ready" | "deprecated";
export type QaTaskRole = "orchestrator" | "api" | "ui" | "automation" | "review";
export type QaTaskStatus =
  | "queued"
  | "running"
  | "needs_review"
  | "blocked"
  | "done"
  | "failed"
  | "cancelled";
export type QaRunStatus =
  | "running"
  | "passed"
  | "failed"
  | "error"
  | "blocked_by_env"
  | "cancelled";
/** Where a run came from (v1.1 run metadata). */
export type QaRunTrigger = "manual" | "ci" | "agent" | "schedule";

export const QA_RUN_TRIGGERS: QaRunTrigger[] = ["manual", "ci", "agent", "schedule"];

export interface QaCaseStep {
  action: string;
  expected: string;
}

export interface QaCaseApiRequest {
  method?: string;
  path?: string;
  headers?: Record<string, string>;
  query?: Record<string, string>;
  body?: unknown;
}

export interface QaCaseApi {
  request?: QaCaseApiRequest;
  assertions?: unknown[];
  variables?: Record<string, string>;
}

export interface QaCase {
  id: string;
  project_id: string;
  code: string;
  title: string;
  kind: QaCaseKind;
  priority: QaCasePriority;
  status: QaCaseStatus;
  preconditions: string;
  steps: QaCaseStep[];
  expected: string;
  tags: string[];
  api: QaCaseApi;
  source: string;
  author: string;
  created_at: string;
  updated_at: string;
}

export interface QaScript {
  id: string;
  project_id: string;
  name: string;
  framework: string;
  language: string;
  file_path: string;
  content?: string;
  case_ids: string[];
  tags: string[];
  status: string;
  content_bytes?: number;
  content_lines?: number;
  created_at: string;
  updated_at: string;
}

export interface QaRunTest {
  name: string;
  code: string;
  status: string;
  message: string;
  duration: number | null;
  checks: unknown[];
}

export interface QaRunReport {
  summary: string;
  tests: QaRunTest[];
}

export interface QaRun {
  id: string;
  project_id: string;
  script_id: string | null;
  case_ids: string[];
  /** Human label for the run (v1.1); empty for runs created before v1.1. */
  name: string;
  /** Environment the run executed against, e.g. `staging` (v1.1). */
  environment: string;
  /** `manual` | `ci` | `agent` | `schedule` (v1.1, defaults to `manual`). */
  trigger: QaRunTrigger;
  status: QaRunStatus;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_ms: number;
  started_at: string;
  finished_at: string | null;
  report: QaRunReport | null;
  log: string;
}

export interface QaTaskArtifact {
  kind: string;
  ref_id: string;
  title: string;
}

export interface QaTask {
  id: string;
  project_id: string | null;
  parent_id: string | null;
  role: QaTaskRole;
  title: string;
  prompt: string;
  status: QaTaskStatus;
  progress: number;
  subagent_task_id: string;
  result: string;
  created_at: string;
  updated_at: string;
  project_key?: string;
  artifacts?: QaTaskArtifact[];
  children?: QaTask[];
}

export interface QaTaskEvent {
  id: number | string;
  task_id: string;
  at: string;
  kind: string;
  message: string;
  data: Record<string, unknown>;
}

export interface QaProjectStats {
  cases: number;
  ready_cases: number;
  scripts: number;
  runs: number;
  active_tasks: number;
}

export interface QaProject {
  id: string;
  key: string;
  name: string;
  description: string;
  base_url: string;
  repo_path: string;
  default_env: string;
  stats: QaProjectStats;
}

export interface QaOverviewCounts {
  projects: number;
  cases: number;
  ready_cases: number;
  scripts: number;
  runs: number;
  tasks: number;
  active_tasks: number;
}

export interface QaOverview {
  counts: QaOverviewCounts;
  projects: QaProject[];
  recent_tasks: QaTask[];
  recent_runs: QaRun[];
}

export interface QaCaseExport {
  format: string;
  project: { key: string; name: string } | null;
  exported_at: string;
  cases: QaCase[];
}

export interface QaCaseList {
  items: QaCase[];
  total: number;
  limit: number;
  offset: number;
}

export interface QaScriptList {
  items: QaScript[];
  total: number;
}

export interface QaRunList {
  items: QaRun[];
  total: number;
}

export interface QaTaskList {
  items: QaTask[];
  total: number;
}

export interface QaTaskDetail extends QaTask {
  artifacts: QaTaskArtifact[];
  children: QaTask[];
}

export interface QaImportSummary {
  created: number;
  skipped: unknown[];
  errors: unknown[];
}

// -- defensive normalization ---------------------------------------------

type RawRecord = Record<string, unknown>;

function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function integer(value: unknown, fallback = 0): number {
  return Math.trunc(number(value, fallback));
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry) => text(entry).trim()).filter(Boolean);
}

function stringRecord(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) out[key] = text(entry);
  return out;
}

function normalizeCaseStep(value: unknown): QaCaseStep {
  if (!isRecord(value)) return { action: "", expected: "" };
  return { action: text(value.action), expected: text(value.expected) };
}

function normalizeCaseApi(value: unknown): QaCaseApi {
  if (!isRecord(value)) return {};
  const api: QaCaseApi = {};
  if (isRecord(value.request)) {
    const request: QaCaseApiRequest = {
      method: text(value.request.method),
      path: text(value.request.path),
      headers: stringRecord(value.request.headers),
      query: stringRecord(value.request.query),
    };
    if ("body" in value.request) request.body = value.request.body;
    api.request = request;
  }
  if (Array.isArray(value.assertions)) api.assertions = value.assertions;
  if (isRecord(value.variables)) api.variables = stringRecord(value.variables);
  return api;
}

function normalizeCase(value: unknown): QaCase {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    project_id: text(row.project_id),
    code: text(row.code),
    title: text(row.title),
    kind: (["api", "ui", "manual"].includes(text(row.kind)) ? text(row.kind) : "api") as QaCaseKind,
    priority: (["P0", "P1", "P2", "P3"].includes(text(row.priority))
      ? text(row.priority)
      : "P1") as QaCasePriority,
    status: (["draft", "ready", "deprecated"].includes(text(row.status))
      ? text(row.status)
      : "draft") as QaCaseStatus,
    preconditions: text(row.preconditions),
    steps: Array.isArray(row.steps) ? row.steps.map(normalizeCaseStep) : [],
    expected: text(row.expected),
    tags: textList(row.tags),
    api: normalizeCaseApi(row.api),
    source: text(row.source),
    author: text(row.author),
    created_at: text(row.created_at),
    updated_at: text(row.updated_at),
  };
}

function normalizeScript(value: unknown): QaScript {
  const row = isRecord(value) ? value : {};
  const script: QaScript = {
    id: text(row.id),
    project_id: text(row.project_id),
    name: text(row.name),
    framework: text(row.framework, "pytest") || "pytest",
    language: text(row.language, "python") || "python",
    file_path: text(row.file_path),
    case_ids: textList(row.case_ids),
    tags: textList(row.tags),
    status: text(row.status, "draft") || "draft",
    created_at: text(row.created_at),
    updated_at: text(row.updated_at),
  };
  if (typeof row.content === "string") script.content = row.content;
  if (row.content_bytes !== undefined) script.content_bytes = integer(row.content_bytes);
  if (row.content_lines !== undefined) script.content_lines = integer(row.content_lines);
  return script;
}

const RUN_STATUSES: QaRunStatus[] = [
  "running",
  "passed",
  "failed",
  "error",
  "blocked_by_env",
  "cancelled",
];

function normalizeRunTest(value: unknown): QaRunTest {
  const row = isRecord(value) ? value : {};
  return {
    name: text(row.name),
    code: text(row.code),
    status: text(row.status, "unknown") || "unknown",
    message: text(row.message),
    duration: row.duration === undefined || row.duration === null ? null : number(row.duration),
    checks: Array.isArray(row.checks) ? row.checks : [],
  };
}

function normalizeRun(value: unknown): QaRun {
  const row = isRecord(value) ? value : {};
  const status = text(row.status);
  const trigger = text(row.trigger);
  const report = isRecord(row.report)
    ? {
        summary: text(row.report.summary),
        tests: Array.isArray(row.report.tests) ? row.report.tests.map(normalizeRunTest) : [],
      }
    : null;
  return {
    id: text(row.id),
    project_id: text(row.project_id),
    script_id: typeof row.script_id === "string" && row.script_id ? row.script_id : null,
    case_ids: textList(row.case_ids),
    // v1.1 metadata: pre-v1.1 rows have no values, so fall back to the
    // contract defaults ("", "", "manual") instead of showing blanks.
    name: text(row.name),
    environment: text(row.environment),
    trigger: (QA_RUN_TRIGGERS.includes(trigger as QaRunTrigger)
      ? trigger
      : "manual") as QaRunTrigger,
    status: (RUN_STATUSES.includes(status as QaRunStatus) ? status : "error") as QaRunStatus,
    passed: integer(row.passed),
    failed: integer(row.failed),
    errors: integer(row.errors),
    skipped: integer(row.skipped),
    duration_ms: integer(row.duration_ms),
    started_at: text(row.started_at),
    finished_at: typeof row.finished_at === "string" ? row.finished_at : null,
    report,
    log: text(row.log),
  };
}

const TASK_STATUSES: QaTaskStatus[] = [
  "queued",
  "running",
  "needs_review",
  "blocked",
  "done",
  "failed",
  "cancelled",
];

const TASK_ROLES: QaTaskRole[] = ["orchestrator", "api", "ui", "automation", "review"];

function normalizeArtifact(value: unknown): QaTaskArtifact {
  const row = isRecord(value) ? value : {};
  return { kind: text(row.kind), ref_id: text(row.ref_id), title: text(row.title) };
}

function normalizeTask(value: unknown): QaTask {
  const row = isRecord(value) ? value : {};
  const status = text(row.status);
  const role = text(row.role);
  const task: QaTask = {
    id: text(row.id),
    project_id: typeof row.project_id === "string" && row.project_id ? row.project_id : null,
    parent_id: typeof row.parent_id === "string" && row.parent_id ? row.parent_id : null,
    role: (TASK_ROLES.includes(role as QaTaskRole) ? role : "orchestrator") as QaTaskRole,
    title: text(row.title),
    prompt: text(row.prompt),
    status: (TASK_STATUSES.includes(status as QaTaskStatus)
      ? status
      : "queued") as QaTaskStatus,
    progress: Math.max(0, Math.min(100, integer(row.progress))),
    subagent_task_id: text(row.subagent_task_id),
    result: text(row.result),
    created_at: text(row.created_at),
    updated_at: text(row.updated_at),
  };
  const projectKey = text(row.project_key);
  if (projectKey) task.project_key = projectKey;
  if (Array.isArray(row.artifacts)) task.artifacts = row.artifacts.map(normalizeArtifact);
  if (Array.isArray(row.children)) task.children = row.children.map(normalizeTask);
  return task;
}

function normalizeTaskEvent(value: unknown): QaTaskEvent {
  const row = isRecord(value) ? value : {};
  return {
    id: typeof row.id === "number" ? row.id : text(row.id),
    task_id: text(row.task_id),
    at: text(row.at),
    kind: text(row.kind, "progress") || "progress",
    message: text(row.message),
    data: isRecord(row.data) ? row.data : {},
  };
}

function normalizeProject(value: unknown): QaProject {
  const row = isRecord(value) ? value : {};
  const stats = isRecord(row.stats) ? row.stats : {};
  return {
    id: text(row.id),
    key: text(row.key),
    name: text(row.name),
    description: text(row.description),
    base_url: text(row.base_url),
    repo_path: text(row.repo_path),
    default_env: text(row.default_env),
    stats: {
      cases: integer(stats.cases),
      ready_cases: integer(stats.ready_cases),
      scripts: integer(stats.scripts),
      runs: integer(stats.runs),
      active_tasks: integer(stats.active_tasks),
    },
  };
}

function normalizeOverview(value: unknown): QaOverview {
  const row = isRecord(value) ? value : {};
  const counts = isRecord(row.counts) ? row.counts : {};
  return {
    counts: {
      projects: integer(counts.projects),
      cases: integer(counts.cases),
      ready_cases: integer(counts.ready_cases),
      scripts: integer(counts.scripts),
      runs: integer(counts.runs),
      tasks: integer(counts.tasks),
      active_tasks: integer(counts.active_tasks),
    },
    projects: Array.isArray(row.projects) ? row.projects.map(normalizeProject) : [],
    recent_tasks: Array.isArray(row.recent_tasks) ? row.recent_tasks.map(normalizeTask) : [],
    recent_runs: Array.isArray(row.recent_runs) ? row.recent_runs.map(normalizeRun) : [],
  };
}

/** Turn any thrown value (fetch failure, mutation rejection) into readable copy. */
export function qaErrorMessage(reason: unknown): string {
  if (reason instanceof Error && reason.message.trim()) return reason.message.trim();
  if (typeof reason === "string" && reason.trim()) return reason.trim();
  return "QA request failed";
}

// -- transport ------------------------------------------------------------

function qaQuery(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (!text) continue;
    search.set(key, text);
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithTimeout(
    path,
    {
      ...(init ?? {}),
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
        Authorization: `Bearer ${token}`,
      },
      credentials: "same-origin",
    },
    QA_READ_TIMEOUT_MS,
  );
  if (!res.ok) {
    const body = typeof res.text === "function" ? (await res.text()).trim() : "";
    let message = body;
    if (body.startsWith("{")) {
      try {
        const payload: unknown = JSON.parse(body);
        if (payload && typeof payload === "object") {
          const error = (payload as { error?: unknown }).error;
          if (typeof error === "string" && error.trim()) message = error.trim();
        }
      } catch {
        // Keep the raw body: the gateway may answer non-JSON on proxy errors.
      }
    }
    throw new QaApiError(res.status, message || `HTTP ${res.status}`);
  }
  const contentType = res.headers?.get?.("content-type") ?? "";
  if (contentType && !contentType.toLowerCase().includes("application/json")) {
    throw new QaApiError(res.status, "Gateway returned a non-JSON response.");
  }
  return (await res.json()) as T;
}

async function mutation<T>(
  transport: QaMutationTransport,
  action: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = QA_MUTATION_TIMEOUT_MS,
): Promise<T> {
  try {
    return await transport.requestMutation<T>(action, payload, timeoutMs);
  } catch (reason) {
    const status = (isRecord(reason) && typeof reason.status === "number") ? reason.status : 500;
    throw new QaApiError(status, qaErrorMessage(reason));
  }
}

// -- reads ----------------------------------------------------------------

export async function loadQaOverview(token: string): Promise<QaOverview> {
  const payload = await request<RawRecord>("/api/qa/overview", token);
  return normalizeOverview(payload);
}

export async function loadQaProjects(token: string): Promise<QaProject[]> {
  const payload = await request<RawRecord>("/api/qa/projects", token);
  return Array.isArray(payload.projects) ? payload.projects.map(normalizeProject) : [];
}

export interface QaCaseQuery {
  projectId?: string;
  kind?: string;
  status?: string;
  query?: string;
  limit?: number;
  offset?: number;
}

export async function loadQaCases(
  token: string,
  query: QaCaseQuery = {},
): Promise<QaCaseList> {
  const payload = await request<RawRecord>(
    `/api/qa/cases${qaQuery({
      project_id: query.projectId,
      kind: query.kind,
      status: query.status,
      q: query.query,
      limit: query.limit,
      offset: query.offset,
    })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeCase) : [];
  return {
    items,
    total: integer(payload.total, items.length),
    limit: integer(payload.limit, query.limit ?? 100),
    offset: integer(payload.offset, query.offset ?? 0),
  };
}

export async function loadQaCase(token: string, id: string): Promise<QaCase> {
  const payload = await request<RawRecord>(`/api/qa/cases/${encodeURIComponent(id)}`, token);
  return normalizeCase(payload.case);
}

export async function loadQaCaseExport(
  token: string,
  projectId?: string,
): Promise<QaCaseExport> {
  const payload = await request<RawRecord>(
    `/api/qa/cases/export${qaQuery({ project_id: projectId })}`,
    token,
  );
  const project = isRecord(payload.project)
    ? { key: text(payload.project.key), name: text(payload.project.name) }
    : null;
  return {
    format: text(payload.format, "qa-agent.cases.v1"),
    project,
    exported_at: text(payload.exported_at),
    cases: Array.isArray(payload.cases) ? payload.cases.map(normalizeCase) : [],
  };
}

export interface QaScriptQuery {
  projectId?: string;
  query?: string;
  limit?: number;
}

export async function loadQaScripts(
  token: string,
  query: QaScriptQuery = {},
): Promise<QaScriptList> {
  const payload = await request<RawRecord>(
    `/api/qa/scripts${qaQuery({
      project_id: query.projectId,
      q: query.query,
      limit: query.limit,
    })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeScript) : [];
  return { items, total: integer(payload.total, items.length) };
}

export async function loadQaScript(token: string, id: string): Promise<QaScript> {
  const payload = await request<RawRecord>(`/api/qa/scripts/${encodeURIComponent(id)}`, token);
  return normalizeScript(payload.script);
}

export interface QaRunQuery {
  projectId?: string;
  limit?: number;
}

export async function loadQaRuns(token: string, query: QaRunQuery = {}): Promise<QaRunList> {
  const payload = await request<RawRecord>(
    `/api/qa/runs${qaQuery({ project_id: query.projectId, limit: query.limit })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeRun) : [];
  return { items, total: integer(payload.total, items.length) };
}

export async function loadQaRun(token: string, id: string): Promise<QaRun> {
  const payload = await request<RawRecord>(`/api/qa/runs/${encodeURIComponent(id)}`, token);
  return normalizeRun(payload.run);
}

export interface QaTaskQuery {
  projectId?: string;
  status?: string;
  role?: string;
  limit?: number;
}

export async function loadQaTasks(token: string, query: QaTaskQuery = {}): Promise<QaTaskList> {
  const payload = await request<RawRecord>(
    `/api/qa/tasks${qaQuery({
      project_id: query.projectId,
      status: query.status,
      role: query.role,
      limit: query.limit,
    })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeTask) : [];
  return { items, total: integer(payload.total, items.length) };
}

export async function loadQaTask(token: string, id: string): Promise<QaTaskDetail> {
  const payload = await request<RawRecord>(`/api/qa/tasks/${encodeURIComponent(id)}`, token);
  const task = normalizeTask(payload.task);
  return { ...task, artifacts: task.artifacts ?? [], children: task.children ?? [] };
}

export async function loadQaTaskEvents(token: string, id: string): Promise<QaTaskEvent[]> {
  const payload = await request<RawRecord>(
    `/api/qa/tasks/${encodeURIComponent(id)}/events`,
    token,
  );
  return Array.isArray(payload.events) ? payload.events.map(normalizeTaskEvent) : [];
}

// -- mutations ------------------------------------------------------------

export interface QaProjectInput {
  key: string;
  name: string;
  description?: string;
  base_url?: string;
  repo_path?: string;
}

export interface QaCaseInput {
  project_id: string;
  title: string;
  kind: QaCaseKind;
  priority: QaCasePriority;
  status: QaCaseStatus;
  preconditions?: string;
  steps?: QaCaseStep[];
  api?: QaCaseApi;
  expected?: string;
  tags?: string[];
}

export interface QaScriptInput {
  project_id: string;
  name: string;
  framework: string;
  language: string;
  file_path: string;
  content?: string;
  case_ids?: string[];
  tags?: string[];
}

export interface QaTaskInput {
  title: string;
  project_id?: string;
  role?: QaTaskRole;
  prompt?: string;
}

export interface QaRunStartInput {
  project_id: string;
  case_ids?: string[];
  kind?: string;
  script_id?: string;
  /** Optional human label (v1.1); empty lets the backend keep its default. */
  name?: string;
  /** Optional target environment (v1.1), e.g. `staging`. */
  environment?: string;
  /** Origin of the run (v1.1); the backend defaults to `manual`. */
  trigger?: QaRunTrigger;
}

/** A review decision on a `needs_review` task (v1.1). */
export interface QaTaskDecisionInput {
  /** Free-form note stored on the task result and the event. */
  note?: string;
  /** Who decided; recorded on the `approved` / `rejected` event. */
  reviewer?: string;
}

export interface QaRunImportInput {
  project_id: string;
  /** JUnit XML body (`<testsuites>` or `<testsuite>`). */
  xml: string;
  name?: string;
  environment?: string;
  /** Defaults to `ci` on the backend; pass a value to override. */
  trigger?: QaRunTrigger;
}

/** Drop empty optional fields so the gateway keeps its defaults. */
function compactPayload(input: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "string" && !value.trim()) continue;
    if (Array.isArray(value) && value.length === 0) continue;
    payload[key] = value;
  }
  return payload;
}

/**
 * Updates keep explicit empty values: clearing a field in the editor ("",
 * `[]`) must reach the store instead of being dropped as "not provided".
 */
function compactUpdate(input: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null) continue;
    payload[key] = value;
  }
  return payload;
}

function readEntity<T>(payload: unknown, key: string, normalize: (value: unknown) => T): T {
  const record = isRecord(payload) ? payload : {};
  return normalize(record[key]);
}

export async function createQaProject(
  transport: QaMutationTransport,
  input: QaProjectInput,
): Promise<QaProject> {
  const payload = await mutation<unknown>(
    transport,
    "qa.project.create",
    compactPayload({ ...input }),
  );
  return readEntity(payload, "project", normalizeProject);
}

export async function deleteQaProject(
  transport: QaMutationTransport,
  id: string,
): Promise<void> {
  await mutation(transport, "qa.project.delete", { id });
}

export async function createQaCase(
  transport: QaMutationTransport,
  input: QaCaseInput,
): Promise<QaCase> {
  const payload = await mutation<unknown>(
    transport,
    "qa.case.create",
    compactPayload({
      project_id: input.project_id,
      title: input.title,
      kind: input.kind,
      priority: input.priority,
      status: input.status,
      preconditions: input.preconditions,
      steps: input.steps,
      api: input.api,
      expected: input.expected,
      tags: input.tags,
    }),
  );
  return readEntity(payload, "case", normalizeCase);
}

export async function updateQaCase(
  transport: QaMutationTransport,
  id: string,
  fields: Partial<Omit<QaCaseInput, "project_id">>,
): Promise<QaCase> {
  const payload = await mutation<unknown>(
    transport,
    "qa.case.update",
    compactUpdate({ id, ...fields }),
  );
  return readEntity(payload, "case", normalizeCase);
}

export async function deleteQaCase(
  transport: QaMutationTransport,
  id: string,
): Promise<void> {
  await mutation(transport, "qa.case.delete", { id });
}

export async function importQaCases(
  transport: QaMutationTransport,
  projectId: string,
  cases: unknown[],
): Promise<QaImportSummary> {
  const payload = await mutation<unknown>(transport, "qa.case.import", {
    project_id: projectId,
    payload: { cases },
  });
  const record = isRecord(payload) ? payload : {};
  return {
    created: integer(record.created),
    skipped: Array.isArray(record.skipped) ? record.skipped : [],
    errors: Array.isArray(record.errors) ? record.errors : [],
  };
}

export async function createQaScript(
  transport: QaMutationTransport,
  input: QaScriptInput,
): Promise<QaScript> {
  const payload = await mutation<unknown>(
    transport,
    "qa.script.create",
    compactPayload({ ...input }),
  );
  return readEntity(payload, "script", normalizeScript);
}

export async function updateQaScript(
  transport: QaMutationTransport,
  id: string,
  fields: Partial<Omit<QaScriptInput, "project_id">>,
): Promise<QaScript> {
  const payload = await mutation<unknown>(
    transport,
    "qa.script.update",
    compactUpdate({ id, ...fields }),
  );
  return readEntity(payload, "script", normalizeScript);
}

export async function deleteQaScript(
  transport: QaMutationTransport,
  id: string,
): Promise<void> {
  await mutation(transport, "qa.script.delete", { id });
}

export async function createQaTask(
  transport: QaMutationTransport,
  input: QaTaskInput,
): Promise<QaTask> {
  const payload = await mutation<unknown>(
    transport,
    "qa.task.create",
    compactPayload({ ...input }),
  );
  return readEntity(payload, "task", normalizeTask);
}

export async function updateQaTask(
  transport: QaMutationTransport,
  id: string,
  fields: { status?: QaTaskStatus; progress?: number; result?: string },
): Promise<QaTask> {
  const payload = await mutation<unknown>(
    transport,
    "qa.task.update",
    compactPayload({ id, ...fields }),
  );
  return readEntity(payload, "task", normalizeTask);
}

export async function cancelQaTask(
  transport: QaMutationTransport,
  id: string,
): Promise<QaTask> {
  const payload = await mutation<unknown>(transport, "qa.task.cancel", { id });
  return readEntity(payload, "task", normalizeTask);
}

/**
 * Close a `needs_review` task as done (`qa.task.approve`).
 *
 * The backend appends `[approved]` to the result and writes an `approved`
 * event carrying the reviewer, which is the audit trail the drawer shows.
 */
export async function approveTask(
  transport: QaMutationTransport,
  id: string,
  input: QaTaskDecisionInput = {},
): Promise<QaTask> {
  const payload = await mutation<unknown>(
    transport,
    "qa.task.approve",
    compactPayload({ id, note: input.note, reviewer: input.reviewer }),
  );
  return readEntity(payload, "task", normalizeTask);
}

/**
 * Send a `needs_review` task back as failed (`qa.task.reject`) so the
 * orchestrator can open a rework task.
 */
export async function rejectTask(
  transport: QaMutationTransport,
  id: string,
  input: QaTaskDecisionInput = {},
): Promise<QaTask> {
  const payload = await mutation<unknown>(
    transport,
    "qa.task.reject",
    compactPayload({ id, note: input.note, reviewer: input.reviewer }),
  );
  return readEntity(payload, "task", normalizeTask);
}

export async function startQaRun(
  transport: QaMutationTransport,
  input: QaRunStartInput,
): Promise<QaRun> {
  const payload = await mutation<unknown>(
    transport,
    "qa.run.start",
    compactPayload({ ...input }),
    QA_RUN_TIMEOUT_MS,
  );
  return readEntity(payload, "run", normalizeRun);
}

/**
 * Import a CI-produced JUnit XML report as one run (`qa.run.import`).
 *
 * Parsing a full report is synchronous on the backend, so this mutation gets
 * the longer import timeout rather than the default one.
 */
export async function importRun(
  transport: QaMutationTransport,
  input: QaRunImportInput,
): Promise<QaRun> {
  const payload = await mutation<unknown>(
    transport,
    "qa.run.import",
    compactPayload({
      project_id: input.project_id,
      xml: input.xml,
      name: input.name,
      environment: input.environment,
      trigger: input.trigger,
    }),
    QA_RUN_IMPORT_TIMEOUT_MS,
  );
  return readEntity(payload, "run", normalizeRun);
}

// -- P4: trace chain ------------------------------------------------------
//
// The traceability chain is served by `nanobot/qa/trace_api.py`, which calls the
// `qa_trace` library. The four headline metrics stay separate all the way into
// the UI: requirement coverage, behavior coverage, automation rate and orphan
// rate are never merged into one "coverage" number (spec section 4).

export interface QaTraceProjectCounts {
  sources: number;
  testpoints: number;
  cases: number;
}

export interface QaTraceProject {
  id: string;
  name: string;
  root: string;
  /** `null` when the project could not be inspected at all. */
  valid: boolean | null;
  error: string;
  modules: string[];
  counts: QaTraceProjectCounts;
}

export interface QaTraceRatio {
  numerator: number;
  denominator: number;
  /** `null` when the denominator is 0 — never rendered as 100%. */
  percent: number | null;
}

export interface QaTraceCoverageBlock {
  label: string;
  types: string[];
  reviewed: QaTraceRatio;
  current_valid: QaTraceRatio;
  uncovered: string[];
  unconfirmed_sources: string[];
}

export interface QaTraceAutomationBlock {
  label: string;
  reviewed: QaTraceRatio;
  provisional: boolean;
  provisional_reason: string;
  unresolved_scripts: string[];
}

export interface QaTraceOrphanBlock {
  label: string;
  library: QaTraceRatio;
  case_ids: string[];
}

export interface QaTraceCoverage {
  requirement: QaTraceCoverageBlock;
  behavior: QaTraceCoverageBlock;
  automation: QaTraceAutomationBlock;
  orphan: QaTraceOrphanBlock;
}

export interface QaTraceRecheck {
  case_id: string;
  reasons: string[];
  changed_ids: string[];
  reviewed_by: string | null;
}

export interface QaTraceDiagnostic {
  severity: string;
  code: string;
  entity_id: string | null;
  path: string | null;
  field: string | null;
  message: string;
  suggestion: string | null;
}

export interface QaTraceStaleBlock {
  error: string;
  baseline: string;
  counts: Record<string, number>;
  needs_recheck: QaTraceRecheck[];
}

export interface QaTraceDraftsBlock {
  error: string;
  counts: Record<string, number>;
  batches: string[];
}

export interface QaTraceRunsBlock {
  error: string;
  counts: Record<string, number>;
}

export interface QaTraceProjectRef {
  id: string;
  name: string;
  root: string;
  modules: string[];
}

export interface QaTraceSummary {
  project: QaTraceProjectRef;
  valid: boolean;
  counts: Record<string, number>;
  coverage: QaTraceCoverage | null;
  requirement_gaps: {
    uncovered_requirements: string[];
    cases_without_requirement_root: string[];
    count: number;
    uncovered_requirement_count: number;
  } | null;
  dangling_count: number;
  dead_assets: {
    sources_without_downstream: string[];
    deprecated_cases: string[];
    manual_p0_cases: { status: string; candidates: string[] };
    count: number;
  } | null;
  metrics_suppressed: string;
  diagnostics: { counts: Record<string, number>; items: QaTraceDiagnostic[] };
  stale: QaTraceStaleBlock | null;
  drafts: QaTraceDraftsBlock | null;
  runs: QaTraceRunsBlock | null;
}

export interface QaTraceScriptRef {
  case_id: string;
  binding: string;
  file: string;
  nodeid: string;
  resolves: boolean;
  problem: string;
}

export interface QaTraceCaseNode {
  id: string;
  title: string;
  status: string;
  priority: string;
  type: string;
  automation: string;
  owner: string;
  tags: string[];
  testpoints: string[];
  sources: string[];
  script: QaTraceScriptRef | null;
  needs_recheck: boolean;
  recheck_reasons: string[];
  changed_ids: string[];
}

export interface QaTraceTestPointNode {
  id: string;
  title: string;
  status: string;
  method: string;
  risk: string;
  module: string;
  owner: string;
  sources: string[];
  cases: QaTraceCaseNode[];
}

export interface QaTraceEvidenceNode {
  type: string;
  locator: string;
  description: string;
  verified: string;
}

export interface QaTraceSourceNode {
  id: string;
  type: string;
  title: string;
  status: string;
  confidence: string;
  module: string;
  owner: string;
  url: string;
  app_version: string;
  observed_at: string;
  stale: boolean;
  evidence: QaTraceEvidenceNode[];
  testpoints: QaTraceTestPointNode[];
  /** Cases that hang directly off the source (they must declare direct_reason). */
  cases: QaTraceCaseNode[];
  case_count: number;
}

export interface QaTraceTree {
  project: QaTraceProjectRef;
  counts: {
    sources: number;
    testpoints: number;
    cases: number;
    scripts: number;
    orphans: number;
  };
  sources: QaTraceSourceNode[];
  orphans: QaTraceCaseNode[];
  scripts: QaTraceScriptRef[];
}

export interface QaTraceImpactCase {
  id: string;
  title: string;
  status: string;
  priority: string;
  automation: string;
  script: string;
  needs_recheck: boolean;
  reasons: string[];
  changed_ids: string[];
  via: { source_id: string; testpoint_id: string | null }[];
}

export interface QaTraceImpact {
  target: { id: string; kind: string };
  counts: {
    testpoints: number;
    cases: number;
    scripts: number;
    needs_recheck: number;
  };
  testpoints: {
    id: string;
    exists: boolean;
    title: string;
    status: string;
    method: string;
    risk: string;
  }[];
  cases: QaTraceImpactCase[];
  scripts: QaTraceScriptRef[];
  sources: {
    id: string;
    exists: boolean;
    type: string;
    title: string;
    status: string;
    confidence: string;
    stale: boolean | null;
  }[];
}

export interface QaTraceChangedEntity {
  id: string;
  kind: string;
  content_changed: boolean;
  dependency_changed: boolean;
  in_baseline: boolean;
}

export interface QaTraceStale {
  baseline: string;
  written: boolean;
  recorded: number;
  index: string;
  counts: Record<string, number>;
  changed: QaTraceChangedEntity[];
  removed: string[];
  needs_recheck: QaTraceRecheck[];
}

export interface QaTraceDraft {
  batch: string;
  id: string;
  kind: string;
  path: string;
  status: string;
  valid: boolean;
  problems: string[];
  note: string;
  rejected_by: string;
  rejected_at: string;
}

export interface QaTraceDraftList {
  counts: Record<string, number>;
  batches: string[];
  drafts: QaTraceDraft[];
}

export interface QaTraceReviewOutcome {
  id: string;
  kind: string;
  mode: string;
  path: string;
  reviewed_by: string;
  reviewed_at: string;
  note: string;
  needs_recheck: boolean;
}

export interface QaTraceFailureResult {
  nodeid: string;
  attempt: number;
  outcome: string;
  failure_stage: string;
  duration_ms: number;
  error_summary: string;
}

export interface QaTraceFailureCase {
  case_id: string;
  results: QaTraceFailureResult[];
  chain: {
    origin: string;
    testpoints: { id: string; exists: boolean; title: string; status: string }[];
    sources: {
      id: string;
      exists: boolean;
      type: string;
      status: string;
      confidence: string;
      stale: boolean | null;
    }[];
  };
  current: {
    exists: boolean;
    status: string;
    changed_since_run: boolean | null;
    needs_recheck: boolean;
    reasons: string[];
    changed_ids: string[];
  };
  last_run: { run_id: string; outcome: string; finished_at: string } | null;
}

export interface QaTraceFailure {
  run: {
    run_id: string;
    status: string;
    exitstatus: number | null;
    started_at: string;
    finished_at: string;
    environment: string;
    code_commit: string | null;
    tool_version: string;
    path: string;
  };
  requested_case: string;
  case_missing: boolean;
  counts: Record<string, number>;
  failures: QaTraceFailureCase[];
}

export interface QaTraceRunSummary {
  run_id: string;
  status: string;
  exitstatus: number | null;
  started_at: string;
  finished_at: string;
  environment: string;
  app_version: string;
  code_commit: string | null;
  tool_version: string;
  path: string;
  results: number;
  failed_cases: number;
  failed_case_ids: string[];
}

export interface QaTraceRunList {
  counts: Record<string, number>;
  items: QaTraceRunSummary[];
}

// -- trace normalization --------------------------------------------------

function numberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const out: Record<string, number> = {};
  for (const [key, entry] of Object.entries(value)) out[key] = integer(entry);
  return out;
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = number(value, Number.NaN);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeTraceRatio(value: unknown): QaTraceRatio {
  const row = isRecord(value) ? value : {};
  return {
    numerator: integer(row.numerator),
    denominator: integer(row.denominator),
    percent: nullableNumber(row.percent),
  };
}

function normalizeTraceProjectRef(value: unknown): QaTraceProjectRef {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    name: text(row.name),
    root: text(row.root),
    modules: textList(row.modules),
  };
}

function normalizeTraceProject(value: unknown): QaTraceProject {
  const row = isRecord(value) ? value : {};
  const counts = isRecord(row.counts) ? row.counts : {};
  const valid = row.valid;
  return {
    id: text(row.id),
    name: text(row.name),
    root: text(row.root),
    valid: typeof valid === "boolean" ? valid : null,
    error: text(row.error),
    modules: textList(row.modules),
    counts: {
      sources: integer(counts.sources),
      testpoints: integer(counts.testpoints),
      cases: integer(counts.cases),
    },
  };
}

function normalizeTraceCoverageBlock(value: unknown): QaTraceCoverageBlock {
  const row = isRecord(value) ? value : {};
  return {
    label: text(row.label),
    types: textList(row.types),
    reviewed: normalizeTraceRatio(row.reviewed),
    current_valid: normalizeTraceRatio(row.current_valid),
    uncovered: textList(row.uncovered),
    unconfirmed_sources: textList(row.unconfirmed_sources),
  };
}

function normalizeTraceCoverage(value: unknown): QaTraceCoverage | null {
  if (!isRecord(value)) return null;
  const automation = isRecord(value.automation) ? value.automation : {};
  const orphan = isRecord(value.orphan) ? value.orphan : {};
  return {
    requirement: normalizeTraceCoverageBlock(value.requirement),
    behavior: normalizeTraceCoverageBlock(value.behavior),
    automation: {
      label: text(automation.label, "automation") || "automation",
      reviewed: normalizeTraceRatio(automation.reviewed),
      provisional: automation.provisional !== false,
      provisional_reason: text(automation.provisional_reason),
      unresolved_scripts: textList(automation.unresolved_scripts),
    },
    orphan: {
      label: text(orphan.label, "orphan") || "orphan",
      library: normalizeTraceRatio(orphan.library),
      case_ids: textList(orphan.case_ids),
    },
  };
}

function normalizeTraceRecheck(value: unknown): QaTraceRecheck {
  const row = isRecord(value) ? value : {};
  // The report's P1 re-check list carries `{source_id, reason}` objects; the
  // P3 stale list carries plain strings. Both collapse to readable strings.
  const reasons = Array.isArray(row.reasons)
    ? row.reasons.map((entry) => {
        if (isRecord(entry)) {
          const reason = text(entry.reason);
          const sourceId = text(entry.source_id);
          return sourceId ? `${reason}:${sourceId}` : reason;
        }
        return text(entry);
      }).filter(Boolean)
    : [];
  return {
    case_id: text(row.case_id),
    reasons,
    changed_ids: textList(row.changed_ids),
    reviewed_by: text(row.reviewed_by) || null,
  };
}

function normalizeTraceDiagnostic(value: unknown): QaTraceDiagnostic {
  const row = isRecord(value) ? value : {};
  return {
    severity: text(row.severity, "info") || "info",
    code: text(row.code),
    entity_id: text(row.entity_id) || null,
    path: text(row.path) || null,
    field: text(row.field) || null,
    message: text(row.message),
    suggestion: text(row.suggestion) || null,
  };
}

function normalizeTraceStaleBlock(value: unknown): QaTraceStaleBlock | null {
  if (!isRecord(value)) return null;
  return {
    error: text(value.error),
    baseline: text(value.baseline),
    counts: numberRecord(value.counts),
    needs_recheck: Array.isArray(value.needs_recheck)
      ? value.needs_recheck.map(normalizeTraceRecheck)
      : [],
  };
}

function normalizeTraceDraftsBlock(value: unknown): QaTraceDraftsBlock | null {
  if (!isRecord(value)) return null;
  return {
    error: text(value.error),
    counts: numberRecord(value.counts),
    batches: textList(value.batches),
  };
}

function normalizeTraceRunsBlock(value: unknown): QaTraceRunsBlock | null {
  if (!isRecord(value)) return null;
  return { error: text(value.error), counts: numberRecord(value.counts) };
}

function normalizeTraceSummary(value: unknown): QaTraceSummary {
  const row = isRecord(value) ? value : {};
  const gaps = isRecord(row.requirement_gaps) ? row.requirement_gaps : null;
  const dead = isRecord(row.dead_assets) ? row.dead_assets : null;
  const manualP0 = dead && isRecord(dead.manual_p0_cases) ? dead.manual_p0_cases : {};
  const diagnostics = isRecord(row.diagnostics) ? row.diagnostics : {};
  return {
    project: normalizeTraceProjectRef(row.project),
    valid: row.valid === true,
    counts: numberRecord(row.counts),
    coverage: normalizeTraceCoverage(row.coverage),
    requirement_gaps: gaps
      ? {
          uncovered_requirements: textList(gaps.uncovered_requirements),
          cases_without_requirement_root: textList(gaps.cases_without_requirement_root),
          count: integer(gaps.count),
          uncovered_requirement_count: integer(gaps.uncovered_requirement_count),
        }
      : null,
    dangling_count: integer(row.dangling_count),
    dead_assets: dead
      ? {
          sources_without_downstream: textList(dead.sources_without_downstream),
          deprecated_cases: textList(dead.deprecated_cases),
          manual_p0_cases: {
            status: text(manualP0.status, "unknown") || "unknown",
            candidates: textList(manualP0.candidates),
          },
          count: integer(dead.count),
        }
      : null,
    metrics_suppressed: text(row.metrics_suppressed),
    diagnostics: {
      counts: numberRecord(diagnostics.counts),
      items: Array.isArray(diagnostics.items)
        ? diagnostics.items.map(normalizeTraceDiagnostic)
        : [],
    },
    stale: normalizeTraceStaleBlock(row.stale),
    drafts: normalizeTraceDraftsBlock(row.drafts),
    runs: normalizeTraceRunsBlock(row.runs),
  };
}

function normalizeTraceScriptRef(value: unknown): QaTraceScriptRef | null {
  if (!isRecord(value)) return null;
  return {
    case_id: text(value.case_id),
    binding: text(value.binding),
    file: text(value.file),
    nodeid: text(value.nodeid),
    resolves: value.resolves !== false,
    problem: text(value.problem),
  };
}

function normalizeTraceCaseNode(value: unknown): QaTraceCaseNode {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    title: text(row.title),
    status: text(row.status),
    priority: text(row.priority),
    type: text(row.type),
    automation: text(row.automation),
    owner: text(row.owner),
    tags: textList(row.tags),
    testpoints: textList(row.testpoints),
    sources: textList(row.sources),
    script: normalizeTraceScriptRef(row.script),
    needs_recheck: row.needs_recheck === true,
    recheck_reasons: textList(row.recheck_reasons),
    changed_ids: textList(row.changed_ids),
  };
}

function normalizeTraceTestPointNode(value: unknown): QaTraceTestPointNode {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    title: text(row.title),
    status: text(row.status),
    method: text(row.method),
    risk: text(row.risk),
    module: text(row.module),
    owner: text(row.owner),
    sources: textList(row.sources),
    cases: Array.isArray(row.cases) ? row.cases.map(normalizeTraceCaseNode) : [],
  };
}

function normalizeTraceSourceNode(value: unknown): QaTraceSourceNode {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    type: text(row.type),
    title: text(row.title),
    status: text(row.status),
    confidence: text(row.confidence),
    module: text(row.module),
    owner: text(row.owner),
    url: text(row.url),
    app_version: text(row.app_version),
    observed_at: text(row.observed_at),
    stale: row.stale === true,
    evidence: Array.isArray(row.evidence)
      ? row.evidence.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            type: text(item.type),
            locator: text(item.locator),
            description: text(item.description),
            verified: text(item.verified),
          };
        })
      : [],
    testpoints: Array.isArray(row.testpoints)
      ? row.testpoints.map(normalizeTraceTestPointNode)
      : [],
    cases: Array.isArray(row.cases) ? row.cases.map(normalizeTraceCaseNode) : [],
    case_count: integer(row.case_count),
  };
}

function normalizeTraceTree(value: unknown): QaTraceTree {
  const row = isRecord(value) ? value : {};
  const counts = isRecord(row.counts) ? row.counts : {};
  return {
    project: normalizeTraceProjectRef(row.project),
    counts: {
      sources: integer(counts.sources),
      testpoints: integer(counts.testpoints),
      cases: integer(counts.cases),
      scripts: integer(counts.scripts),
      orphans: integer(counts.orphans),
    },
    sources: Array.isArray(row.sources) ? row.sources.map(normalizeTraceSourceNode) : [],
    orphans: Array.isArray(row.orphans) ? row.orphans.map(normalizeTraceCaseNode) : [],
    scripts: Array.isArray(row.scripts)
      ? row.scripts.map(normalizeTraceScriptRef).filter((item): item is QaTraceScriptRef => item !== null)
      : [],
  };
}

function normalizeTraceImpact(value: unknown): QaTraceImpact {
  const row = isRecord(value) ? value : {};
  const target = isRecord(row.target) ? row.target : {};
  const counts = isRecord(row.counts) ? row.counts : {};
  return {
    target: { id: text(target.id), kind: text(target.kind) },
    counts: {
      testpoints: integer(counts.testpoints),
      cases: integer(counts.cases),
      scripts: integer(counts.scripts),
      needs_recheck: integer(counts.needs_recheck),
    },
    testpoints: Array.isArray(row.testpoints)
      ? row.testpoints.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            id: text(item.id),
            exists: item.exists !== false,
            title: text(item.title),
            status: text(item.status),
            method: text(item.method),
            risk: text(item.risk),
          };
        })
      : [],
    cases: Array.isArray(row.cases)
      ? row.cases.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            id: text(item.id),
            title: text(item.title),
            status: text(item.status),
            priority: text(item.priority),
            automation: text(item.automation),
            script: text(item.script),
            needs_recheck: item.needs_recheck === true,
            reasons: textList(item.reasons),
            changed_ids: textList(item.changed_ids),
            via: Array.isArray(item.via)
              ? item.via.map((path) => {
                  const hop = isRecord(path) ? path : {};
                  return {
                    source_id: text(hop.source_id),
                    testpoint_id: text(hop.testpoint_id) || null,
                  };
                })
              : [],
          };
        })
      : [],
    scripts: Array.isArray(row.scripts)
      ? row.scripts.map(normalizeTraceScriptRef).filter((item): item is QaTraceScriptRef => item !== null)
      : [],
    sources: Array.isArray(row.sources)
      ? row.sources.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            id: text(item.id),
            exists: item.exists !== false,
            type: text(item.type),
            title: text(item.title),
            status: text(item.status),
            confidence: text(item.confidence),
            stale: typeof item.stale === "boolean" ? item.stale : null,
          };
        })
      : [],
  };
}

function normalizeTraceStale(value: unknown): QaTraceStale {
  const row = isRecord(value) ? value : {};
  return {
    baseline: text(row.baseline),
    written: row.written === true,
    recorded: integer(row.recorded),
    index: text(row.index),
    counts: numberRecord(row.counts),
    changed: Array.isArray(row.changed)
      ? row.changed.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            id: text(item.id),
            kind: text(item.kind),
            content_changed: item.content_changed === true,
            dependency_changed: item.dependency_changed === true,
            in_baseline: item.in_baseline !== false,
          };
        })
      : [],
    removed: textList(row.removed),
    needs_recheck: Array.isArray(row.needs_recheck)
      ? row.needs_recheck.map(normalizeTraceRecheck)
      : [],
  };
}

function normalizeTraceDraft(value: unknown): QaTraceDraft {
  const row = isRecord(value) ? value : {};
  return {
    batch: text(row.batch),
    id: text(row.id),
    kind: text(row.kind),
    path: text(row.path),
    status: text(row.status, "pending") || "pending",
    valid: row.valid !== false,
    problems: textList(row.problems),
    note: text(row.note),
    rejected_by: text(row.rejected_by),
    rejected_at: text(row.rejected_at),
  };
}

function normalizeTraceDraftList(value: unknown): QaTraceDraftList {
  const row = isRecord(value) ? value : {};
  return {
    counts: numberRecord(row.counts),
    batches: textList(row.batches),
    drafts: Array.isArray(row.drafts) ? row.drafts.map(normalizeTraceDraft) : [],
  };
}

function normalizeTraceReviewOutcome(value: unknown): QaTraceReviewOutcome {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    kind: text(row.kind),
    mode: text(row.mode),
    path: text(row.path),
    reviewed_by: text(row.reviewed_by),
    reviewed_at: text(row.reviewed_at),
    note: text(row.note),
    needs_recheck: row.needs_recheck === true,
  };
}

function normalizeTraceFailure(value: unknown): QaTraceFailure {
  const row = isRecord(value) ? value : {};
  const run = isRecord(row.run) ? row.run : {};
  const counts = isRecord(row.counts) ? row.counts : {};
  return {
    run: {
      run_id: text(run.run_id),
      status: text(run.status),
      exitstatus: nullableNumber(run.exitstatus),
      started_at: text(run.started_at),
      finished_at: text(run.finished_at),
      environment: text(run.environment),
      code_commit: text(run.code_commit) || null,
      tool_version: text(run.tool_version),
      path: text(run.path),
    },
    requested_case: text(row.requested_case),
    case_missing: row.case_missing === true,
    counts: numberRecord(counts),
    failures: Array.isArray(row.failures)
      ? row.failures.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          const chain = isRecord(item.chain) ? item.chain : {};
          const current = isRecord(item.current) ? item.current : {};
          const lastRun = isRecord(item.last_run) ? item.last_run : null;
          return {
            case_id: text(item.case_id),
            results: Array.isArray(item.results)
              ? item.results.map((result) => {
                  const rowResult = isRecord(result) ? result : {};
                  return {
                    nodeid: text(rowResult.nodeid),
                    attempt: integer(rowResult.attempt, 1),
                    outcome: text(rowResult.outcome),
                    failure_stage: text(rowResult.failure_stage),
                    duration_ms: integer(rowResult.duration_ms),
                    error_summary: text(rowResult.error_summary),
                  };
                })
              : [],
            chain: {
              origin: text(chain.origin),
              testpoints: Array.isArray(chain.testpoints)
                ? chain.testpoints.map((testpoint) => {
                    const itemTestpoint = isRecord(testpoint) ? testpoint : {};
                    return {
                      id: text(itemTestpoint.id),
                      exists: itemTestpoint.exists !== false,
                      title: text(itemTestpoint.title),
                      status: text(itemTestpoint.status),
                    };
                  })
                : [],
              sources: Array.isArray(chain.sources)
                ? chain.sources.map((source) => {
                    const itemSource = isRecord(source) ? source : {};
                    return {
                      id: text(itemSource.id),
                      exists: itemSource.exists !== false,
                      type: text(itemSource.type),
                      status: text(itemSource.status),
                      confidence: text(itemSource.confidence),
                      stale:
                        typeof itemSource.stale === "boolean" ? itemSource.stale : null,
                    };
                  })
                : [],
            },
            current: {
              exists: current.exists !== false,
              status: text(current.status),
              changed_since_run:
                typeof current.changed_since_run === "boolean"
                  ? current.changed_since_run
                  : null,
              needs_recheck: current.needs_recheck === true,
              reasons: textList(current.reasons),
              changed_ids: textList(current.changed_ids),
            },
            last_run: lastRun
              ? {
                  run_id: text(lastRun.run_id),
                  outcome: text(lastRun.outcome),
                  finished_at: text(lastRun.finished_at),
                }
              : null,
          };
        })
      : [],
  };
}

function normalizeTraceRunList(value: unknown): QaTraceRunList {
  const row = isRecord(value) ? value : {};
  return {
    counts: numberRecord(row.counts),
    items: Array.isArray(row.items)
      ? row.items.map((entry) => {
          const item = isRecord(entry) ? entry : {};
          return {
            run_id: text(item.run_id),
            status: text(item.status),
            exitstatus: nullableNumber(item.exitstatus),
            started_at: text(item.started_at),
            finished_at: text(item.finished_at),
            environment: text(item.environment),
            app_version: text(item.app_version),
            code_commit: text(item.code_commit) || null,
            tool_version: text(item.tool_version),
            path: text(item.path),
            results: integer(item.results),
            failed_cases: integer(item.failed_cases),
            failed_case_ids: textList(item.failed_case_ids),
          };
        })
      : [],
  };
}

export interface QaTraceProjectQuery {
  /** Project directory name; omitted lets the backend pick the first one. */
  project?: string;
}

export interface QaTraceImpactQuery extends QaTraceProjectQuery {
  source?: string;
  testpoint?: string;
  case?: string;
}

export interface QaTraceFailureQuery extends QaTraceProjectQuery {
  run: string;
  case?: string;
}

export interface QaTraceReviewInput extends QaTraceProjectQuery {
  id: string;
  batch?: string;
  reviewer?: string;
  note?: string;
}

export async function loadQaTraceProjects(token: string): Promise<QaTraceProject[]> {
  const payload = await request<RawRecord>("/api/qa/trace/projects", token);
  return Array.isArray(payload.projects) ? payload.projects.map(normalizeTraceProject) : [];
}

export async function loadQaTraceSummary(
  token: string,
  query: QaTraceProjectQuery = {},
): Promise<QaTraceSummary> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/summary${qaQuery({ project: query.project })}`,
    token,
  );
  return normalizeTraceSummary(payload);
}

export async function loadQaTraceTree(
  token: string,
  query: QaTraceProjectQuery = {},
): Promise<QaTraceTree> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/tree${qaQuery({ project: query.project })}`,
    token,
  );
  return normalizeTraceTree(payload);
}

export async function loadQaTraceImpact(
  token: string,
  query: QaTraceImpactQuery = {},
): Promise<QaTraceImpact> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/impact${qaQuery({
      project: query.project,
      source: query.source,
      testpoint: query.testpoint,
      case: query.case,
    })}`,
    token,
  );
  return normalizeTraceImpact(payload);
}

export async function loadQaTraceStale(
  token: string,
  query: QaTraceProjectQuery = {},
): Promise<QaTraceStale> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/stale${qaQuery({ project: query.project })}`,
    token,
  );
  return normalizeTraceStale(payload);
}

export async function loadQaTraceDrafts(
  token: string,
  query: QaTraceProjectQuery & { batch?: string } = {},
): Promise<QaTraceDraftList> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/drafts${qaQuery({ project: query.project, batch: query.batch })}`,
    token,
  );
  return normalizeTraceDraftList(payload);
}

export async function loadQaTraceFailure(
  token: string,
  query: QaTraceFailureQuery,
): Promise<QaTraceFailure> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/failure${qaQuery({
      project: query.project,
      run: query.run,
      case: query.case,
    })}`,
    token,
  );
  return normalizeTraceFailure(payload);
}

export async function loadQaTraceRuns(
  token: string,
  query: QaTraceProjectQuery = {},
): Promise<QaTraceRunList> {
  const payload = await request<RawRecord>(
    `/api/qa/trace/runs${qaQuery({ project: query.project })}`,
    token,
  );
  return normalizeTraceRunList(payload);
}

/**
 * Record the current fingerprints as the new stale baseline (`qa.trace.stale_write`).
 *
 * This is the "记录基线" action: it answers "what changed since I last looked".
 * It never approves anything — clearing `needs_recheck` is a review decision.
 */
export async function writeQaTraceBaseline(
  transport: QaMutationTransport,
  project?: string,
): Promise<QaTraceStale> {
  const payload = await mutation<unknown>(
    transport,
    "qa.trace.stale_write",
    compactPayload({ project }),
  );
  return readEntity(payload, "stale", normalizeTraceStale);
}

/** Promote one draft, or re-review one formal test point/case. */
export async function approveQaTraceReview(
  transport: QaMutationTransport,
  input: QaTraceReviewInput,
): Promise<QaTraceReviewOutcome> {
  const payload = await mutation<unknown>(
    transport,
    "qa.trace.review_approve",
    compactPayload({ ...input }),
  );
  return readEntity(payload, "review", normalizeTraceReviewOutcome);
}

/** Record the rejection of one draft; the file stays in `draft/`. */
export async function rejectQaTraceReview(
  transport: QaMutationTransport,
  input: QaTraceReviewInput,
): Promise<QaTraceReviewOutcome> {
  const payload = await mutation<unknown>(
    transport,
    "qa.trace.review_reject",
    compactPayload({ ...input }),
  );
  return readEntity(payload, "review", normalizeTraceReviewOutcome);
}
