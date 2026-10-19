import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Play, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  createQaScript,
  loadQaScript,
  loadQaScripts,
  qaErrorMessage,
  startQaRun,
  updateQaScript,
  type QaMutationTransport,
  type QaProject,
  type QaRun,
  type QaScript,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailField, QaDetailSection } from "./QaDetailDrawer";
import { groupQaScripts, type QaScriptModuleGroup } from "./qa-script-groups";
import {
  formatQaDuration,
  formatQaTime,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPanel,
  QaRunStatusBadge,
  QaRunTriggerBadge,
  QaSectionTitle,
  QaTableShell,
  QaTagChips,
  QaTruncate,
  QA_TD_CLASS,
  QA_TH_CLASS,
  useQaCopy,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

const SCRIPT_FRAMEWORKS = ["pytest", "playwright", "postman"] as const;

/** Only the pytest runner is wired end-to-end today. */
const RUNNABLE_FRAMEWORK = "pytest";

/** Runs started here are manual; the environment stays empty by default. */
const DEFAULT_RUN_ENVIRONMENT = "";

/** Default run label: `<script name> @ <local date/time>`. */
function defaultRunName(scriptName: string): string {
  const stamp = new Date().toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${scriptName || "pytest"} @ ${stamp}`;
}

export interface QaScriptsProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  refreshSignal: number;
  onChanged: () => void;
}

export function QaScripts({
  token,
  client,
  projects,
  refreshSignal,
  onChanged,
}: QaScriptsProps) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(() => new Set());
  const [collapsedModules, setCollapsedModules] = useState<Set<string>>(() => new Set());

  const scripts = useQaQuery(
    () =>
      loadQaScripts(token, {
        projectId: projectId === "all" ? undefined : projectId,
        limit: 200,
      }),
    [token, projectId, refreshSignal],
    { intervalMs: 0 },
  );

  const items = scripts.data?.items ?? [];
  const groups = useMemo(() => groupQaScripts(items, projects), [items, projects]);
  const defaultProjectId = useMemo(
    () => (projectId !== "all" ? projectId : projects[0]?.id ?? ""),
    [projectId, projects],
  );

  const toggleProject = (id: string) => {
    setCollapsedProjects((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleModule = (id: string) => {
    setCollapsedModules((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /** `根目录`/`未分组` are buckets, not paths; only module keys read as paths. */
  const moduleLabel = (module: QaScriptModuleGroup) =>
    module.kind === "module"
      ? module.key
      : module.kind === "root"
        ? tx("qa.scripts.groupRoot", "根目录")
        : tx("qa.scripts.groupUngrouped", "未分组");

  return (
    <div className="flex flex-col gap-3" data-testid="qa-scripts">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.scripts.title", "自动化脚本")}
          count={scripts.data?.total ?? items.length}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger
              aria-label={tx("qa.scripts.filterProject", "项目筛选")}
              className="h-8 w-[10rem]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{tx("qa.filters.allProjects", "全部项目")}</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.key || project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => setCreateOpen(true)}
            data-testid="qa-script-create"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.scripts.create", "新建脚本")}
          </Button>
        </div>
      </div>

      {scripts.error ? (
        <QaErrorBar
          message={`${tx("qa.error.scripts", "加载脚本失败")}: ${scripts.error}`}
          onRetry={scripts.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}

      {scripts.loading && !scripts.data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <QaEmptyState
          title={tx("qa.scripts.empty", "还没有自动化脚本")}
          hint={tx(
            "qa.scripts.emptyHint",
            "自动化 Agent 产出的 pytest 脚本会保存在这里；也可以手工新建后直接编辑内容。",
          )}
          action={
            <>
              <Button type="button" size="sm" variant="outline" onClick={scripts.reload}>
                {tx("qa.actions.refresh", "刷新")}
              </Button>
              <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
                {tx("qa.scripts.create", "新建脚本")}
              </Button>
            </>
          }
        />
      ) : (
        <div className="flex flex-col gap-4" data-testid="qa-script-groups">
          {groups.map((group) => {
            const projectOpen = !collapsedProjects.has(group.projectId);
            const scriptCount = group.modules.reduce(
              (total, module) => total + module.scripts.length,
              0,
            );
            return (
              <section
                key={group.projectId}
                data-testid={`qa-script-project-${group.projectId}`}
                className="flex flex-col gap-2"
              >
                <button
                  type="button"
                  aria-expanded={projectOpen}
                  data-testid={`qa-script-project-toggle-${group.projectId}`}
                  onClick={() => toggleProject(group.projectId)}
                  className="flex items-center gap-2 self-start rounded-lg px-1 py-0.5 text-left transition-colors hover:text-foreground"
                >
                  {projectOpen ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                  )}
                  <span className="font-mono text-[12px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                    {group.key}
                  </span>
                  {group.name ? (
                    <span className="truncate text-sm font-semibold text-foreground">
                      {group.name}
                    </span>
                  ) : null}
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
                    {scriptCount}
                  </span>
                </button>

                {projectOpen ? (
                  <QaTableShell label={group.name ? `${group.key} ${group.name}` : group.key}>
                    <thead>
                      <tr>
                        <th className={QA_TH_CLASS}>{tx("qa.scripts.name", "名称")}</th>
                        <th className={QA_TH_CLASS}>{tx("qa.scripts.framework", "框架")}</th>
                        <th className={QA_TH_CLASS}>{tx("qa.scripts.filePath", "文件路径")}</th>
                        <th className={cn(QA_TH_CLASS, "text-right")}>
                          {tx("qa.scripts.caseCount", "关联用例")}
                        </th>
                        <th className={QA_TH_CLASS}>{tx("qa.scripts.tags", "标签")}</th>
                        <th className={cn(QA_TH_CLASS, "text-right")}>
                          {tx("qa.scripts.updatedAt", "更新时间")}
                        </th>
                      </tr>
                    </thead>
                    {group.modules.map((module) => {
                      const moduleId = `${group.projectId}::${module.kind}:${module.key}`;
                      const moduleTestId = `${group.projectId}-${module.kind}-${module.key || "base"}`;
                      const moduleOpen = !collapsedModules.has(moduleId);
                      return (
                        <tbody key={moduleId} data-testid={`qa-script-module-${moduleTestId}`}>
                          <tr className="bg-muted/40">
                            <td colSpan={6} className="border-b border-border/40 px-3 py-2">
                              <button
                                type="button"
                                aria-expanded={moduleOpen}
                                data-testid={`qa-script-module-toggle-${moduleTestId}`}
                                onClick={() => toggleModule(moduleId)}
                                className="flex items-center gap-1.5 rounded text-[12.5px] font-medium text-foreground"
                              >
                                {moduleOpen ? (
                                  <ChevronDown
                                    className="h-3.5 w-3.5 text-muted-foreground"
                                    aria-hidden
                                  />
                                ) : (
                                  <ChevronRight
                                    className="h-3.5 w-3.5 text-muted-foreground"
                                    aria-hidden
                                  />
                                )}
                                <span
                                  className={cn(
                                    module.kind === "module" ? "font-mono" : "text-muted-foreground",
                                  )}
                                >
                                  {moduleLabel(module)}
                                </span>
                                <span className="rounded-full bg-background/70 px-1.5 py-0.5 text-[10.5px] tabular-nums text-muted-foreground">
                                  {module.scripts.length}
                                </span>
                              </button>
                            </td>
                          </tr>
                          {moduleOpen
                            ? module.scripts.map((script) => (
                                <ScriptRow
                                  key={script.id}
                                  script={script}
                                  onOpen={() => setSelectedId(script.id)}
                                />
                              ))
                            : null}
                        </tbody>
                      );
                    })}
                  </QaTableShell>
                ) : null}
              </section>
            );
          })}
        </div>
      )}

      <QaScriptDrawer
        token={token}
        client={client}
        scriptId={selectedId}
        open={selectedId !== null}
        onOpenChange={(open) => { if (!open) setSelectedId(null); }}
        onChanged={() => {
          scripts.reload();
          onChanged();
        }}
      />

      <QaScriptCreateDialog
        client={client}
        open={createOpen}
        onOpenChange={setCreateOpen}
        projects={projects}
        defaultProjectId={defaultProjectId}
        onCreated={() => {
          scripts.reload();
          onChanged();
        }}
      />
    </div>
  );
}

function ScriptRow({ script, onOpen }: { script: QaScript; onOpen: () => void }) {
  return (
    <tr
      data-testid={`qa-script-row-${script.id}`}
      className="cursor-pointer hover:bg-muted/30"
      onClick={onOpen}
    >
      <td className={QA_TD_CLASS}>
        <button
          type="button"
          className="block max-w-[22rem] truncate text-left font-medium text-foreground hover:underline"
          title={script.name}
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
        >
          {script.name || script.id}
        </button>
      </td>
      <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
        <span className="rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[11px]">
          {script.framework}
        </span>
      </td>
      <td className={cn(QA_TD_CLASS, "font-mono text-[11.5px] text-muted-foreground")}>
        <QaTruncate text={script.file_path} className="max-w-[18rem]" />
      </td>
      <td className={cn(QA_TD_CLASS, "text-right tabular-nums")}>
        {script.case_ids.length}
      </td>
      <td className={QA_TD_CLASS}>
        <QaTagChips tags={script.tags} limit={2} />
      </td>
      <td className={cn(QA_TD_CLASS, "text-right text-[12px] text-muted-foreground")}>
        {formatQaTime(script.updated_at)}
      </td>
    </tr>
  );
}

function QaScriptDrawer({
  token,
  client,
  scriptId,
  open,
  onOpenChange,
  onChanged,
}: {
  token: string;
  client: QaMutationTransport;
  scriptId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void;
}) {
  const tx = useQaCopy();
  const detail = useQaQuery<QaScript | null>(
    () => (scriptId ? loadQaScript(token, scriptId) : Promise.resolve(null)),
    [token, scriptId],
    { enabled: open && Boolean(scriptId), intervalMs: 0 },
  );
  const script = detail.data;

  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [run, setRun] = useState<QaRun | null>(null);
  const [runError, setRunError] = useState("");
  const [running, setRunning] = useState(false);

  const loadedId = script?.id ?? "";
  useEffect(() => {
    if (!script) return;
    setContent(script.content ?? "");
    setError("");
    setNotice("");
    setRun(null);
    setRunError("");
    // Reset the editor only when a different script is opened.
  }, [loadedId]);

  const save = async () => {
    if (!script || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await updateQaScript(client, script.id, { content });
      setNotice(tx("qa.scripts.saved", "已保存"));
      detail.reload();
      onChanged();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const runScript = async () => {
    if (!script || running) return;
    setRunning(true);
    setRunError("");
    setRun(null);
    try {
      const result = await startQaRun(client, {
        project_id: script.project_id,
        script_id: script.id,
        name: defaultRunName(script.name),
        environment: DEFAULT_RUN_ENVIRONMENT,
      });
      setRun(result);
      onChanged();
    } catch (reason) {
      setRunError(qaErrorMessage(reason));
    } finally {
      setRunning(false);
    }
  };

  const runnable = script?.framework === RUNNABLE_FRAMEWORK;

  return (
    <QaDetailDrawer
      open={open}
      onOpenChange={onOpenChange}
      testId="qa-script-drawer"
      title={script?.name || tx("qa.scripts.detailTitle", "脚本详情")}
      description={script?.file_path || ""}
      badge={
        script ? (
          <>
            <span className="rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
              {script.framework}
            </span>
            <span className="text-[11px] text-muted-foreground">{script.language}</span>
            {run ? <QaRunStatusBadge status={run.status} /> : null}
          </>
        ) : null
      }
      meta={
        script
          ? [
              { label: tx("qa.scripts.caseCount", "关联用例"), value: String(script.case_ids.length) },
              {
                label: tx("qa.scripts.lines", "行数"),
                value: script.content_lines !== undefined ? String(script.content_lines) : "—",
              },
              { label: tx("qa.scripts.updatedAt", "更新时间"), value: formatQaTime(script.updated_at) },
              { label: tx("qa.scripts.status", "状态"), value: script.status },
            ]
          : []
      }
      footer={
        script ? (
          <>
            {notice ? (
              <span className="mr-auto text-[12px] text-emerald-700 dark:text-emerald-300">
                {notice}
              </span>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              disabled={!runnable || running}
              title={
                runnable
                  ? undefined
                  : tx("qa.scripts.runUnsupported", "playwright / postman 暂不支持在此运行")
              }
              data-testid="qa-script-run"
              onClick={() => void runScript()}
            >
              {running ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden />
              )}
              {running
                ? tx("qa.status.running", "运行中…")
                : tx("qa.scripts.run", "运行")}
            </Button>
            <Button type="button" disabled={busy} data-testid="qa-script-save" onClick={() => void save()}>
              {tx("qa.actions.save", "保存")}
            </Button>
          </>
        ) : null
      }
    >
      {detail.error ? <QaErrorBar message={detail.error} onRetry={detail.reload} /> : null}
      {error ? <QaErrorBar message={error} /> : null}
      {runError ? <QaErrorBar message={runError} /> : null}
      {!runnable && script ? (
        <p className="rounded-lg border border-amber-500/25 bg-amber-500/[0.06] px-3 py-2 text-[12.5px] text-amber-800 dark:text-amber-200">
          {tx(
            "qa.scripts.runUnsupportedHint",
            "当前只支持运行 pytest 脚本；该脚本请用对应框架在本地或 CI 执行。",
          )}
        </p>
      ) : null}
      {run ? <QaRunResult run={run} /> : null}
      {!script ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : (
        <>
          <QaDetailSection
            title={tx("qa.scripts.content", "脚本内容")}
            hint={`${content.length} chars`}
          >
            <Textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              aria-label={tx("qa.scripts.content", "脚本内容")}
              rows={18}
              className="font-mono text-[12px] leading-5"
              spellCheck={false}
              disabled={busy}
              data-testid="qa-script-content"
            />
          </QaDetailSection>
          {script.case_ids.length > 0 ? (
            <QaDetailSection title={tx("qa.scripts.linkedCases", "关联用例")}>
              <div className="flex flex-wrap gap-1.5">
                {script.case_ids.map((caseId) => (
                  <span
                    key={caseId}
                    className="max-w-full truncate rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
                    title={caseId}
                  >
                    {caseId}
                  </span>
                ))}
              </div>
            </QaDetailSection>
          ) : null}
        </>
      )}
    </QaDetailDrawer>
  );
}

export function QaRunResult({ run }: { run: QaRun }) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-3 py-2.5" data-testid="qa-run-result">
      <div className="flex flex-wrap items-center gap-2">
        <QaRunStatusBadge status={run.status} />
        <QaRunTriggerBadge trigger={run.trigger} />
        <span className="text-[12px] text-muted-foreground">
          {tx("qa.runs.counts", "通过 {{passed}} · 失败 {{failed}} · 错误 {{errors}}", {
            passed: run.passed,
            failed: run.failed,
            errors: run.errors,
          })}
        </span>
        <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
          {formatQaDuration(run.duration_ms)}
        </span>
      </div>
      {run.name ? (
        <p className="mt-1.5 truncate text-[12px] font-medium text-foreground" title={run.name}>
          {run.name}
        </p>
      ) : null}
      <p className="mt-1.5 text-[11.5px] text-muted-foreground">
        {formatQaTime(run.started_at)}
        {run.environment ? ` · ${run.environment}` : ""}
      </p>
      {run.report?.summary ? (
        <p className="mt-1 whitespace-pre-wrap break-words text-[12.5px] text-foreground">
          {run.report.summary}
        </p>
      ) : null}
    </QaPanel>
  );
}

function QaScriptCreateDialog({
  client,
  open,
  onOpenChange,
  projects,
  defaultProjectId,
  onCreated,
}: {
  client: QaMutationTransport;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: QaProject[];
  defaultProjectId: string;
  onCreated: () => void;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [name, setName] = useState("");
  const [framework, setFramework] = useState<string>("pytest");
  const [filePath, setFilePath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) setProjectId(defaultProjectId);
  }, [open, defaultProjectId]);

  const submit = async () => {
    if (busy) return;
    if (!projectId) {
      setError(tx("qa.cases.projectRequired", "请选择项目"));
      return;
    }
    if (!name.trim()) {
      setError(tx("qa.scripts.nameRequired", "请填写脚本名称"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createQaScript(client, {
        project_id: projectId,
        name: name.trim(),
        framework,
        language: framework === "postman" ? "json" : "python",
        file_path: filePath.trim(),
      });
      onOpenChange(false);
      setName("");
      setFilePath("");
      onCreated();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{tx("qa.scripts.create", "新建脚本")}</DialogTitle>
          <DialogDescription>
            {tx("qa.scripts.createHint", "创建后可在详情抽屉里编辑脚本内容并运行 pytest。")}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-left">
          <QaDetailField label={tx("qa.cases.fieldProject", "项目")}>
            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger aria-label={tx("qa.cases.fieldProject", "项目")} className="h-9">
                <SelectValue placeholder={tx("qa.cases.projectRequired", "请选择项目")} />
              </SelectTrigger>
              <SelectContent>
                {projects.map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.key || project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </QaDetailField>
          <QaDetailField label={tx("qa.scripts.name", "名称")}>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-label={tx("qa.scripts.name", "名称")}
              data-testid="qa-new-script-name"
              disabled={busy}
            />
          </QaDetailField>
          <div className="grid grid-cols-2 gap-2">
            <QaDetailField label={tx("qa.scripts.framework", "框架")}>
              <Select value={framework} onValueChange={setFramework}>
                <SelectTrigger aria-label={tx("qa.scripts.framework", "框架")} className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCRIPT_FRAMEWORKS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </QaDetailField>
            <QaDetailField label={tx("qa.scripts.filePath", "文件路径")}>
              <Input
                value={filePath}
                onChange={(event) => setFilePath(event.target.value)}
                aria-label={tx("qa.scripts.filePath", "文件路径")}
                className="font-mono text-[12px]"
                disabled={busy}
              />
            </QaDetailField>
          </div>
          {error ? <QaErrorBar message={error} /> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            {tx("qa.actions.cancel", "取消")}
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={busy}>
            {tx("qa.actions.save", "保存")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
