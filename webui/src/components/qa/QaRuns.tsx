import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Upload } from "lucide-react";

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
import { usePageVisibility } from "@/hooks/usePageVisibility";
import {
  importRun,
  loadQaRun,
  loadQaRuns,
  qaErrorMessage,
  type QaMutationTransport,
  type QaProject,
  type QaRun,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailField, QaDetailSection } from "./QaDetailDrawer";
import {
  formatQaDuration,
  formatQaTime,
  QaBadge,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPre,
  QaRunStatusBadge,
  QaRunTriggerBadge,
  QaSectionTitle,
  QaTableShell,
  QaTruncate,
  qaRunName,
  QA_TD_CLASS,
  QA_TH_CLASS,
  useQaCopy,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

export interface QaRunsProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  pollIntervalMs: number;
  refreshSignal: number;
}

export function QaRuns({
  token,
  client,
  projects,
  pollIntervalMs,
  refreshSignal,
}: QaRunsProps) {
  const tx = useQaCopy();
  const visible = usePageVisibility();
  const [projectId, setProjectId] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const runs = useQaQuery(
    () =>
      loadQaRuns(token, {
        projectId: projectId === "all" ? undefined : projectId,
        limit: 100,
      }),
    [token, projectId, refreshSignal],
    { intervalMs: visible ? pollIntervalMs : 0 },
  );

  const items = runs.data?.items ?? [];
  const projectKeys = useMemo(() => {
    const map = new Map<string, string>();
    projects.forEach((project) => map.set(project.id, project.key || project.name));
    return map;
  }, [projects]);
  const defaultProjectId = useMemo(
    () => (projectId !== "all" ? projectId : projects[0]?.id ?? ""),
    [projectId, projects],
  );

  /** Show the imported run immediately and open its drawer. */
  const handleImported = (imported: QaRun) => {
    const current = runs.data;
    if (current) {
      const exists = current.items.some((item) => item.id === imported.id);
      runs.setData({
        items: [imported, ...current.items.filter((item) => item.id !== imported.id)],
        total: exists ? current.total : current.total + 1,
      });
    }
    if (imported.id) setSelectedId(imported.id);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="qa-runs">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.runs.title", "运行记录")}
          count={runs.data?.total ?? items.length}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger aria-label={tx("qa.runs.filterProject", "项目筛选")} className="h-8 w-[10rem]">
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
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => setImportOpen(true)}
            data-testid="qa-run-import"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.runs.importAction", "导入 JUnit")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={runs.reload}
            disabled={runs.loading && items.length === 0}
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                runs.loading && "animate-spin motion-reduce:animate-none",
              )}
              aria-hidden
            />
            {tx("qa.actions.refresh", "刷新")}
          </Button>
        </div>
      </div>

      {runs.error ? (
        <QaErrorBar
          message={`${tx("qa.error.runs", "加载运行记录失败")}: ${runs.error}`}
          onRetry={runs.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}

      {runs.loading && !runs.data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <QaEmptyState
          title={tx("qa.runs.empty", "暂无运行记录")}
          hint={tx(
            "qa.runs.emptyHint",
            "在自动化脚本里点“运行”，或让接口用例执行一次，结果会出现在这里。环境阻塞的运行为黄色，不算产品缺陷。",
          )}
          action={
            <>
              <Button type="button" size="sm" variant="outline" onClick={runs.reload}>
                {tx("qa.actions.refresh", "刷新")}
              </Button>
              <Button type="button" size="sm" onClick={() => setImportOpen(true)}>
                {tx("qa.runs.importAction", "导入 JUnit")}
              </Button>
            </>
          }
        />
      ) : (
        <QaTableShell label={tx("qa.runs.title", "运行记录")}>
          <thead>
            <tr>
              <th className={QA_TH_CLASS}>{tx("qa.runs.status", "状态")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.runs.name", "运行")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.runs.environment", "环境")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.runs.countsHeader", "通过 / 失败 / 错误")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>{tx("qa.runs.skipped", "跳过")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>{tx("qa.runs.duration", "耗时")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.runs.project", "项目")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>{tx("qa.runs.startedAt", "开始时间")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((run) => (
              <tr
                key={run.id}
                className="cursor-pointer hover:bg-muted/30"
                onClick={() => setSelectedId(run.id)}
              >
                <td className={QA_TD_CLASS}>
                  <QaRunStatusBadge status={run.status} />
                </td>
                <td className={QA_TD_CLASS}>
                  <button
                    type="button"
                    className="flex max-w-[16rem] flex-col items-start gap-1 text-left"
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(run.id);
                    }}
                  >
                    <span
                      className="block max-w-full truncate font-medium text-foreground"
                      title={qaRunName(run)}
                    >
                      {qaRunName(run) || "—"}
                    </span>
                    <QaRunTriggerBadge trigger={run.trigger} />
                  </button>
                </td>
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  <QaTruncate text={run.environment} className="max-w-[7rem]" />
                </td>
                <td className={QA_TD_CLASS}>
                  <QaRunCounts run={run} />
                </td>
                <td className={cn(QA_TD_CLASS, "text-right tabular-nums text-muted-foreground")}>
                  {run.skipped}
                </td>
                <td className={cn(QA_TD_CLASS, "text-right tabular-nums")}>
                  {formatQaDuration(run.duration_ms)}
                </td>
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  <QaTruncate text={projectKeys.get(run.project_id) ?? ""} className="max-w-[8rem]" />
                </td>
                <td className={cn(QA_TD_CLASS, "text-right text-[12px] text-muted-foreground")}>
                  {formatQaTime(run.started_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </QaTableShell>
      )}

      <QaRunDrawer
        token={token}
        runId={selectedId}
        open={selectedId !== null}
        onOpenChange={(open) => { if (!open) setSelectedId(null); }}
      />

      <QaRunImportDialog
        client={client}
        open={importOpen}
        onOpenChange={setImportOpen}
        projects={projects}
        defaultProjectId={defaultProjectId}
        onImported={handleImported}
      />
    </div>
  );
}

/** Passed/failed/error counters shared by the list and the pytest run result. */
export function QaRunCounts({ run }: { run: QaRun }) {
  const tx = useQaCopy();
  return (
    <span
      data-testid="qa-run-counts"
      className="inline-flex items-center gap-2 text-[12px] tabular-nums"
    >
      <span className="font-medium text-emerald-700 dark:text-emerald-300">
        {tx("qa.runs.passed", "通过 {{count}}", { count: run.passed })}
      </span>
      <span className="font-medium text-red-700 dark:text-red-300">
        {tx("qa.runs.failed", "失败 {{count}}", { count: run.failed })}
      </span>
      <span className="text-muted-foreground">
        {tx("qa.runs.errors", "错误 {{count}}", { count: run.errors })}
      </span>
    </span>
  );
}

function QaRunDrawer({
  token,
  runId,
  open,
  onOpenChange,
}: {
  token: string;
  runId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const tx = useQaCopy();
  const detail = useQaQuery<QaRun | null>(
    () => (runId ? loadQaRun(token, runId) : Promise.resolve(null)),
    [token, runId],
    { enabled: open && Boolean(runId), intervalMs: 0 },
  );
  const run = detail.data;
  const tests = run?.report?.tests ?? [];

  return (
    <QaDetailDrawer
      open={open}
      onOpenChange={onOpenChange}
      testId="qa-run-drawer"
      title={run ? qaRunName(run) : tx("qa.runs.detailTitle", "运行详情")}
      description={run?.id ?? ""}
      badge={
        run ? (
          <>
            <QaRunStatusBadge status={run.status} />
            <QaRunTriggerBadge trigger={run.trigger} />
            <QaRunCounts run={run} />
          </>
        ) : null
      }
      meta={
        run
          ? [
              {
                label: tx("qa.runs.name", "运行"),
                value: qaRunName(run),
              },
              {
                label: tx("qa.runs.environment", "环境"),
                value: run.environment,
                mono: true,
              },
              {
                label: tx("qa.runs.duration", "耗时"),
                value: formatQaDuration(run.duration_ms),
              },
              {
                label: tx("qa.runs.startedAt", "开始时间"),
                value: formatQaTime(run.started_at),
              },
              {
                label: tx("qa.runs.finishedAt", "结束时间"),
                value: run.finished_at ? formatQaTime(run.finished_at) : "—",
              },
              {
                label: tx("qa.runs.caseCount", "用例数"),
                value: String(run.case_ids.length),
                mono: true,
              },
            ]
          : []
      }
    >
      {detail.error ? <QaErrorBar message={detail.error} onRetry={detail.reload} /> : null}
      {!run ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : (
        <>
          {run.status === "blocked_by_env" ? (
            <p
              data-testid="qa-run-env-blocked"
              className="rounded-lg border border-amber-500/25 bg-amber-500/[0.06] px-3 py-2 text-[12.5px] text-amber-800 dark:text-amber-200"
            >
              {tx(
                "qa.runs.envBlocked",
                "环境不可用，本次运行未真正验证产品行为：请先修复环境后重跑，不要按失败处理。",
              )}
            </p>
          ) : null}

          <QaDetailSection title={tx("qa.runs.summary", "摘要")}>
            <QaPre>{run.report?.summary || tx("qa.runs.noSummary", "（无摘要）")}</QaPre>
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.runs.tests", "用例结果")}
            hint={String(tests.length)}
          >
            {tests.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.runs.noTests", "本次运行没有逐条用例结果")}
              </p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {tests.map((test, index) => (
                  <li
                    key={`${test.code || test.name}-${index}`}
                    className="rounded-lg border border-border/60 bg-card px-3 py-2"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <QaBadge
                        tone={
                          test.status === "passed"
                            ? "green"
                            : test.status === "failed" || test.status === "error"
                              ? "red"
                              : test.status === "skipped"
                                ? "neutral"
                                : "amber"
                        }
                      >
                        {test.status}
                      </QaBadge>
                      <span
                        title={test.name || test.code}
                        className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground"
                      >
                        {test.name || test.code || "—"}
                      </span>
                      {test.duration !== null ? (
                        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                          {formatQaDuration(test.duration)}
                        </span>
                      ) : null}
                    </div>
                    {test.message ? (
                      <p className="mt-1 whitespace-pre-wrap break-words text-[12px] leading-5 text-muted-foreground">
                        {test.message}
                      </p>
                    ) : null}
                    {test.checks.length > 0 ? (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {tx("qa.runs.checkCount", "{{count}} 项校验", { count: test.checks.length })}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </QaDetailSection>

          {run.log ? (
            <QaDetailSection title={tx("qa.runs.log", "日志")}>
              <QaPre className="max-h-60">{run.log}</QaPre>
            </QaDetailSection>
          ) : null}
        </>
      )}
    </QaDetailDrawer>
  );
}

/**
 * CI bridge: paste the JUnit XML a pipeline produced and store it as one
 * `ci` run, so CI results live next to manually triggered runs.
 */
function QaRunImportDialog({
  client,
  open,
  onOpenChange,
  projects,
  defaultProjectId,
  onImported,
}: {
  client: QaMutationTransport;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: QaProject[];
  defaultProjectId: string;
  onImported: (run: QaRun) => void;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState("");
  const [xml, setXml] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setProjectId(defaultProjectId);
    setName("");
    setEnvironment("");
    setXml("");
    setError("");
  }, [open, defaultProjectId]);

  const submit = async () => {
    if (busy) return;
    if (!projectId) {
      setError(tx("qa.cases.projectRequired", "请选择项目"));
      return;
    }
    if (!xml.trim()) {
      setError(tx("qa.runs.importXmlRequired", "请粘贴 JUnit XML 内容"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const imported = await importRun(client, {
        project_id: projectId,
        xml,
        name: name.trim(),
        environment: environment.trim(),
      });
      onOpenChange(false);
      onImported(imported);
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="qa-run-import-dialog">
        <DialogHeader>
          <DialogTitle>{tx("qa.runs.importTitle", "导入 JUnit 运行")}</DialogTitle>
          <DialogDescription>
            {tx(
              "qa.runs.importHint",
              "粘贴 CI 产出的 JUnit XML（<testsuites> 或 <testsuite>），会作为一次 ci 运行导入。",
            )}
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
          <div className="grid gap-2 sm:grid-cols-2">
            <QaDetailField label={tx("qa.runs.importName", "运行名称（可选）")}>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label={tx("qa.runs.importName", "运行名称（可选）")}
                placeholder="nightly smoke"
                disabled={busy}
                data-testid="qa-run-import-name"
              />
            </QaDetailField>
            <QaDetailField label={tx("qa.runs.importEnvironment", "环境（可选）")}>
              <Input
                value={environment}
                onChange={(event) => setEnvironment(event.target.value)}
                aria-label={tx("qa.runs.importEnvironment", "环境（可选）")}
                placeholder="staging"
                className="font-mono text-[12px]"
                disabled={busy}
                data-testid="qa-run-import-environment"
              />
            </QaDetailField>
          </div>
          <QaDetailField label={tx("qa.runs.importXml", "JUnit XML")}>
            <Textarea
              value={xml}
              onChange={(event) => setXml(event.target.value)}
              aria-label={tx("qa.runs.importXml", "JUnit XML")}
              rows={12}
              className="font-mono text-[12px] leading-5"
              spellCheck={false}
              placeholder={'<testsuite name="smoke">\n  <testcase name="login" classname="api" />\n</testsuite>'}
              disabled={busy}
              data-testid="qa-run-import-xml"
            />
          </QaDetailField>
          {error ? <QaErrorBar message={error} /> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            {tx("qa.actions.cancel", "取消")}
          </Button>
          <Button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !xml.trim()}
            data-testid="qa-run-import-submit"
          >
            {tx("qa.runs.importSubmit", "导入")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
