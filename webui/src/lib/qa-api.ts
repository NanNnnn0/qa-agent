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
  /** setup | cases | cleanup when the run used an ordered plan. */
  phase: string;
  /** assertion_failed | config_error | env_blocked | cleanup_failed | dependency_blocked. */
  classification: string;
}

export interface QaRunPhaseSummary {
  tests: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
}

export interface QaRunSummary {
  tests: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
  duration: number;
  batches?: number;
  phases?: Record<string, QaRunPhaseSummary>;
}

export interface QaRunBatch {
  index: number;
  phase?: string;
  cases: number;
  reported: number;
  exit_code: number;
  duration_ms: number;
}

export interface QaRunSnapshotCase {
  case_id: string;
  code: string;
  revision: number;
  content_hash: string;
}

export interface QaRunSnapshot {
  template_version: string;
  cases: QaRunSnapshotCase[];
  plan?: { version: string; phases: Record<string, { case_id: string; revision: number }[]> };
}

export interface QaRunReport {
  /** Legacy runs store prose; pinned runs store the structured summary. */
  summary: string | QaRunSummary | null;
  tests: QaRunTest[];
  template_version: string;
  plan_version: string;
  batches: QaRunBatch[];
  snapshot: QaRunSnapshot | null;
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
    phase: text(row.phase),
    classification: text(row.classification),
  };
}

function normalizeRunSummary(value: unknown): QaRunSummary | null {
  if (!isRecord(value)) return null;
  const phases = isRecord(value.phases) ? value.phases : null;
  const normalizedPhases: Record<string, QaRunPhaseSummary> = {};
  if (phases) {
    for (const [name, phase] of Object.entries(phases)) {
      if (!isRecord(phase)) continue;
      normalizedPhases[name] = {
        tests: integer(phase.tests, 0),
        passed: integer(phase.passed, 0),
        failed: integer(phase.failed, 0),
        skipped: integer(phase.skipped, 0),
        error: integer(phase.error, 0),
      };
    }
  }
  return {
    tests: integer(value.tests, 0),
    passed: integer(value.passed, 0),
    failed: integer(value.failed, 0),
    skipped: integer(value.skipped, 0),
    error: integer(value.error, 0),
    duration: integer(value.duration, 0),
    batches: value.batches === undefined ? undefined : integer(value.batches, 0),
    phases: Object.keys(normalizedPhases).length > 0 ? normalizedPhases : undefined,
  };
}

function normalizeRunSnapshot(value: unknown): QaRunSnapshot | null {
  if (!isRecord(value)) return null;
  const cases = Array.isArray(value.cases)
    ? value.cases.filter(isRecord).map((row) => ({
        case_id: text(row.case_id),
        code: text(row.code),
        revision: integer(row.revision, 0),
        content_hash: text(row.content_hash),
      }))
    : [];
  const plan = isRecord(value.plan) && isRecord(value.plan.phases)
    ? {
        version: text(value.plan.version),
        phases: Object.fromEntries(
          Object.entries(value.plan.phases)
            .filter(([, steps]) => Array.isArray(steps))
            .map(([name, steps]) => [
              name,
              (steps as unknown[]).filter(isRecord).map((step) => ({
                case_id: text(step.case_id),
                revision: integer(step.revision, 0),
              })),
            ]),
        ),
      }
    : undefined;
  return { template_version: text(value.template_version), cases, plan };
}

function normalizeRun(value: unknown): QaRun {
  const row = isRecord(value) ? value : {};
  const status = text(row.status);
  const trigger = text(row.trigger);
  const report = isRecord(row.report)
    ? {
        summary: isRecord(row.report.summary)
          ? normalizeRunSummary(row.report.summary)
          : text(row.report.summary) || null,
        tests: Array.isArray(row.report.tests) ? row.report.tests.map(normalizeRunTest) : [],
        template_version: text(row.report.template_version),
        plan_version: text(row.report.plan_version),
        batches: Array.isArray(row.report.batches)
          ? row.report.batches.filter(isRecord).map((batch) => ({
              index: integer(batch.index, 0),
              phase: text(batch.phase),
              cases: integer(batch.cases, 0),
              reported: integer(batch.reported, 0),
              exit_code: integer(batch.exit_code, 0),
              duration_ms: integer(batch.duration_ms, 0),
            }))
          : [],
        snapshot: normalizeRunSnapshot(row.report.snapshot),
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

// -- API reference assets and case revisions -------------------------------

export interface QaApiOperationEvidence {
  kind: string;
  ref: string;
  version?: string;
}

export interface QaApiOperation {
  id: string;
  project_id: string;
  method: string;
  path: string;
  path_template: string;
  operation_id: string;
  summary: string;
  status: "active" | "missing";
  source_kind: string;
  source_ref: string;
  source_version: string;
  created_at: string;
  updated_at: string;
  spec?: RawRecord;
  evidence?: QaApiOperationEvidence[];
}

export interface QaApiOperationList {
  items: QaApiOperation[];
  total: number;
  limit: number;
  offset: number;
}

export interface QaApiOperationQuery {
  projectId?: string;
  query?: string;
  method?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

function normalizeOperation(value: unknown): QaApiOperation {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    project_id: text(row.project_id),
    method: text(row.method).toUpperCase(),
    path: text(row.path),
    path_template: text(row.path_template) || text(row.path),
    operation_id: text(row.operation_id),
    summary: text(row.summary),
    status: text(row.status) === "missing" ? "missing" : "active",
    source_kind: text(row.source_kind),
    source_ref: text(row.source_ref),
    source_version: text(row.source_version),
    created_at: text(row.created_at),
    updated_at: text(row.updated_at),
    spec: isRecord(row.spec) ? row.spec : undefined,
    evidence: Array.isArray(row.evidence)
      ? row.evidence.filter(isRecord).map((item) => ({
          kind: text(item.kind),
          ref: text(item.ref),
          version: text(item.version) || undefined,
        }))
      : undefined,
  };
}

export async function loadQaApiOperations(
  token: string,
  query: QaApiOperationQuery = {},
): Promise<QaApiOperationList> {
  const payload = await request<RawRecord>(
    `/api/qa/api-operations${qaQuery({
      project_id: query.projectId,
      q: query.query,
      method: query.method,
      status: query.status,
      limit: query.limit,
      offset: query.offset,
    })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeOperation) : [];
  return {
    items,
    total: integer(payload.total, items.length),
    limit: integer(payload.limit, items.length),
    offset: integer(payload.offset, 0),
  };
}

export async function loadQaApiOperation(
  token: string,
  operationId: string,
): Promise<QaApiOperation> {
  const payload = await request<RawRecord>(
    `/api/qa/api-operations/${encodeURIComponent(operationId)}`,
    token,
  );
  return normalizeOperation(payload.operation);
}

export interface QaCaseRevision {
  id: string;
  case_id: string;
  revision: number;
  content_hash: string;
  change_source: string;
  changed_by: string;
  created_at: string;
  snapshot?: RawRecord;
}

export interface QaCaseRevisionList {
  items: QaCaseRevision[];
  total: number;
  limit: number;
  offset: number;
}

function normalizeRevision(value: unknown): QaCaseRevision {
  const row = isRecord(value) ? value : {};
  return {
    id: text(row.id),
    case_id: text(row.case_id),
    revision: integer(row.revision, 0),
    content_hash: text(row.content_hash),
    change_source: text(row.change_source),
    changed_by: text(row.changed_by),
    created_at: text(row.created_at),
    snapshot: isRecord(row.snapshot) ? row.snapshot : undefined,
  };
}

export async function loadQaCaseRevisions(
  token: string,
  caseId: string,
  query: { limit?: number; offset?: number } = {},
): Promise<QaCaseRevisionList> {
  const payload = await request<RawRecord>(
    `/api/qa/cases/${encodeURIComponent(caseId)}/revisions${qaQuery({
      limit: query.limit,
      offset: query.offset,
    })}`,
    token,
  );
  const items = Array.isArray(payload.items) ? payload.items.map(normalizeRevision) : [];
  return {
    items,
    total: integer(payload.total, items.length),
    limit: integer(payload.limit, items.length),
    offset: integer(payload.offset, 0),
  };
}

export async function loadQaCaseRevision(
  token: string,
  caseId: string,
  revision: number,
): Promise<QaCaseRevision> {
  const payload = await request<RawRecord>(
    `/api/qa/cases/${encodeURIComponent(caseId)}/revisions/${revision}`,
    token,
  );
  return normalizeRevision(payload.revision);
}
