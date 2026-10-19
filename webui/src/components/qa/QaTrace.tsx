import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, GitBranch, RefreshCw, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  approveQaTraceReview,
  loadQaTraceDrafts,
  loadQaTraceFailure,
  loadQaTraceImpact,
  loadQaTraceProjects,
  loadQaTraceRuns,
  loadQaTraceStale,
  loadQaTraceSummary,
  loadQaTraceTree,
  qaErrorMessage,
  rejectQaTraceReview,
  writeQaTraceBaseline,
  type QaMutationTransport,
  type QaTraceCaseNode,
  type QaTraceCoverageBlock,
  type QaTraceDraft,
  type QaTraceFailure,
  type QaTraceImpact,
  type QaTraceRatio,
  type QaTraceRunSummary,
  type QaTraceSourceNode,
  type QaTraceStale,
  type QaTraceSummary,
  type QaTraceTree,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import {
  formatQaTime,
  QaBadge,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPanel,
  QaPre,
  QaPriorityBadge,
  QaSectionTitle,
  QaStatCard,
  useQaCopy,
  type QaTone,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

export interface QaTraceProps {
  token: string;
  client: QaMutationTransport;
  /** Bumped by the workbench refresh button; every trace read follows it. */
  refreshSignal: number;
}

/** Review state of a source / test point / case. */
const REVIEW_TONE: Record<string, QaTone> = {
  reviewed: "green",
  draft: "neutral",
  deprecated: "neutral",
  active: "green",
};

const REVIEW_LABEL: Record<string, string> = {
  reviewed: "已审核",
  draft: "草稿",
  deprecated: "已废弃",
  active: "生效中",
};

const REASON_LABEL: Record<string, string> = {
  content_changed: "内容变更",
  dependency_changed: "上游变更",
  source_stale: "来源标记过期",
  no_review_baseline: "缺少审核记录",
  stale: "来源标记过期",
};

function reasonText(reason: string): string {
  const [code, detail] = reason.split(":", 2);
  const label = REASON_LABEL[code] ?? code;
  return detail ? `${label}（${detail}）` : label;
}

function ratioPercent(ratio: QaTraceRatio | null | undefined): string {
  if (!ratio || ratio.denominator === 0 || ratio.percent === null) return "N/A";
  return `${ratio.percent.toFixed(2)}%`;
}

function ratioHint(ratio: QaTraceRatio | null | undefined): string {
  if (!ratio) return "0/0";
  return `${ratio.numerator}/${ratio.denominator}`;
}

function coverageHint(block: QaTraceCoverageBlock | null | undefined): string {
  if (!block) return "已审核 — · 当前有效 —";
  return `已审核 ${ratioHint(block.reviewed)} · 当前有效 ${ratioHint(block.current_valid)}`;
}

/**
 * 追溯标签页：把 `qa_trace` 的追溯链接进已有的 QA 工作台。
 *
 * 四个指标分开显示（需求 / 行为 / 自动化 / 孤儿），不做任何合并；链上的
 * draft/reviewed、stale、needs_recheck 都是后端派生出来的只读状态，页面只负责
 * 展示和触发三个显式动作（记录基线、通过、退回）。
 *
 * 这一页不轮询：一次 `summary` 会跑完整的库校验，按 3 秒轮询代价太高；顶部的
 * 「刷新」按钮（refreshSignal）会让所有读重新拉取。
 */
export function QaTrace({ token, client, refreshSignal }: QaTraceProps) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState("");
  const [impactKind, setImpactKind] = useState<"source" | "case">("source");
  const [impactInput, setImpactInput] = useState("");
  const [impactTarget, setImpactTarget] = useState<{ kind: "source" | "case"; id: string } | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [selectedRun, setSelectedRun] = useState("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");

  const projectsQuery = useQaQuery(() => loadQaTraceProjects(token), [token, refreshSignal]);
  const projects = projectsQuery.data ?? [];

  useEffect(() => {
    if (projectId || projects.length === 0) return;
    setProjectId(projects[0].id);
  }, [projectId, projects]);

  const query = projectId ? { project: projectId } : {};
  const summaryQuery = useQaQuery<QaTraceSummary>(
    () => loadQaTraceSummary(token, query),
    [token, projectId, refreshSignal],
    { enabled: Boolean(projectId) },
  );
  const treeQuery = useQaQuery<QaTraceTree>(
    () => loadQaTraceTree(token, query),
    [token, projectId, refreshSignal],
    { enabled: Boolean(projectId) },
  );
  const staleQuery = useQaQuery<QaTraceStale>(
    () => loadQaTraceStale(token, query),
    [token, projectId, refreshSignal],
    { enabled: Boolean(projectId) },
  );
  const draftsQuery = useQaQuery(
    () => loadQaTraceDrafts(token, query),
    [token, projectId, refreshSignal],
    { enabled: Boolean(projectId) },
  );
  const runsQuery = useQaQuery(
    () => loadQaTraceRuns(token, query),
    [token, projectId, refreshSignal],
    { enabled: Boolean(projectId) },
  );
  const impactQuery = useQaQuery<QaTraceImpact | null>(
    () =>
      impactTarget
        ? loadQaTraceImpact(token, {
            ...query,
            ...(impactTarget.kind === "source"
              ? { source: impactTarget.id }
              : { case: impactTarget.id }),
          })
        : Promise.resolve(null),
    [token, projectId, impactTarget],
    { enabled: impactTarget !== null },
  );
  const failureQuery = useQaQuery<QaTraceFailure | null>(
    () =>
      selectedRun
        ? loadQaTraceFailure(token, { ...query, run: selectedRun })
        : Promise.resolve(null),
    [token, projectId, selectedRun],
    { enabled: Boolean(selectedRun) },
  );

  const runs = runsQuery.data?.items ?? [];
  useEffect(() => {
    if (selectedRun || runs.length === 0) return;
    setSelectedRun(runs[0].run_id);
  }, [runs, selectedRun]);

  const summary = summaryQuery.data;
  const stale = staleQuery.data;
  const drafts = draftsQuery.data?.drafts ?? [];

  const reloadAll = useCallback(() => {
    summaryQuery.reload();
    treeQuery.reload();
    staleQuery.reload();
    draftsQuery.reload();
    runsQuery.reload();
    if (impactTarget) impactQuery.reload();
    if (selectedRun) failureQuery.reload();
  }, [
    summaryQuery,
    treeQuery,
    staleQuery,
    draftsQuery,
    runsQuery,
    impactQuery,
    failureQuery,
    impactTarget,
    selectedRun,
  ]);

  const runAction = async (key: string, action: () => Promise<string>) => {
    if (busy) return;
    setBusy(key);
    setActionError("");
    setActionNotice("");
    try {
      setActionNotice(await action());
      reloadAll();
    } catch (reason) {
      setActionError(qaErrorMessage(reason));
    } finally {
      setBusy("");
    }
  };

  const submitImpact = () => {
    const id = impactInput.trim();
    if (!id) {
      setActionError(tx("qa.trace.impactIdRequired", "请输入来源或用例 ID"));
      return;
    }
    setActionError("");
    setActionNotice("");
    setImpactTarget({ kind: impactKind, id });
  };

  const recordBaseline = () =>
    runAction("stale", async () => {
      const result = await writeQaTraceBaseline(client, projectId || undefined);
      return tx("qa.trace.baselineRecorded", "已记录 {{count}} 个实体的基线", {
        count: result.recorded,
      });
    });

  const decideDraft = (draft: QaTraceDraft, approved: boolean) =>
    runAction(`${approved ? "approve" : "reject"}:${draft.id}`, async () => {
      const input = {
        project: projectId || undefined,
        id: draft.id,
        batch: draft.batch || undefined,
        reviewer: reviewer.trim() || undefined,
      };
      const outcome = approved
        ? await approveQaTraceReview(client, input)
        : await rejectQaTraceReview(client, input);
      const label = outcome.mode === "rejected" ? "已退回" : "已通过";
      return `${label} ${outcome.id}`;
    });

  const projectOptions = useMemo(
    () => projects.map((project) => ({ id: project.id, label: project.name || project.id })),
    [projects],
  );

  return (
    <div className="flex flex-col gap-4" data-testid="qa-trace">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.trace.title", "追溯")}
          count={summary?.counts.cases ?? treeQuery.data?.counts.cases}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger
              aria-label={tx("qa.trace.project", "追溯项目")}
              className="h-8 w-[12rem]"
              data-testid="qa-trace-project"
            >
              <SelectValue placeholder={tx("qa.trace.projectPlaceholder", "选择项目")} />
            </SelectTrigger>
            <SelectContent>
              {projectOptions.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => {
              projectsQuery.reload();
              reloadAll();
            }}
            disabled={summaryQuery.loading && !summary}
            data-testid="qa-trace-refresh"
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                summaryQuery.loading && "animate-spin motion-reduce:animate-none",
              )}
              aria-hidden
            />
            {tx("qa.actions.refresh", "刷新")}
          </Button>
        </div>
      </div>

      {projectsQuery.error ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.projects", "加载追溯项目失败")}: ${projectsQuery.error}`}
          onRetry={projectsQuery.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}
      {actionError ? <QaErrorBar message={actionError} /> : null}
      {actionNotice ? (
        <p
          data-testid="qa-trace-notice"
          className="rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] px-3 py-2 text-[12.5px] text-emerald-800 dark:text-emerald-200"
        >
          {actionNotice}
        </p>
      ) : null}

      {projectsQuery.loading && projects.length === 0 ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : projects.length === 0 ? (
        <QaEmptyState
          testId="qa-trace-empty"
          title={tx("qa.trace.empty", "没有追溯项目")}
          hint={tx(
            "qa.trace.emptyHint",
            "追溯库放在 qa-workbench/projects/<project-id>/，或用环境变量 NANOBOT_QA_TRACE_ROOT 指向其他目录。",
          )}
          action={
            <Button type="button" size="sm" variant="outline" onClick={projectsQuery.reload}>
              {tx("qa.actions.refresh", "刷新")}
            </Button>
          }
        />
      ) : (
        <>
          {summaryQuery.error ? (
            <QaErrorBar
              message={`${tx("qa.trace.error.summary", "加载指标失败")}: ${summaryQuery.error}`}
              onRetry={summaryQuery.reload}
              retryLabel={tx("qa.actions.retry", "重试")}
            />
          ) : null}
          {summaryQuery.loading && !summary ? (
            <QaLoading label={tx("qa.status.loading", "加载中…")} />
          ) : (
            <TraceMetrics summary={summary} />
          )}

          <div className="grid gap-4 xl:grid-cols-2">
            <div className="flex flex-col gap-4">
              <TraceTreePanel
                query={treeQuery}
                onPickImpact={(kind, id) => {
                  setImpactKind(kind);
                  setImpactInput(id);
                  setImpactTarget({ kind, id });
                }}
              />
              <TraceImpactPanel
                impact={impactQuery.data}
                loading={impactQuery.loading}
                error={impactQuery.error}
                kind={impactKind}
                onKindChange={setImpactKind}
                value={impactInput}
                onValueChange={setImpactInput}
                onSubmit={submitImpact}
                onRetry={impactQuery.reload}
                target={impactTarget}
              />
            </div>
            <div className="flex flex-col gap-4">
              <TraceStalePanel
                stale={stale}
                loading={staleQuery.loading && !stale}
                error={staleQuery.error}
                busy={busy === "stale"}
                onRecordBaseline={recordBaseline}
                onRetry={staleQuery.reload}
              />
              <TraceDraftsPanel
                drafts={drafts}
                loading={draftsQuery.loading && !draftsQuery.data}
                error={draftsQuery.error}
                busy={busy}
                reviewer={reviewer}
                onReviewerChange={setReviewer}
                onDecide={decideDraft}
                onRetry={draftsQuery.reload}
              />
              <TraceFailurePanel
                runs={runs}
                runsLoading={runsQuery.loading && runs.length === 0}
                runsError={runsQuery.error}
                selectedRun={selectedRun}
                onSelectRun={setSelectedRun}
                failure={failureQuery.data}
                failureLoading={failureQuery.loading && !failureQuery.data}
                failureError={failureQuery.error}
                onRetry={() => {
                  runsQuery.reload();
                  failureQuery.reload();
                }}
              />
            </div>
          </div>

          <TraceDiagnostics summary={summary} />
        </>
      )}
    </div>
  );
}

// -- metric cards ---------------------------------------------------------

function TraceMetrics({ summary }: { summary: QaTraceSummary | null }) {
  const tx = useQaCopy();
  if (!summary) return null;
  const coverage = summary.coverage;
  const automation = coverage?.automation ?? null;
  const orphan = coverage?.orphan ?? null;
  const suppressed = !summary.valid || !coverage;
  return (
    <div data-testid="qa-trace-metrics" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <QaStatCard
        testId="qa-trace-metric-requirement"
        label={tx("qa.trace.metric.requirement", "需求覆盖率")}
        value={ratioPercent(coverage?.requirement.reviewed)}
        hint={coverageHint(coverage?.requirement)}
      />
      <QaStatCard
        testId="qa-trace-metric-behavior"
        label={tx("qa.trace.metric.behavior", "行为覆盖率")}
        value={ratioPercent(coverage?.behavior.reviewed)}
        hint={coverageHint(coverage?.behavior)}
      />
      <QaStatCard
        testId="qa-trace-metric-automation"
        label={tx("qa.trace.metric.automation", "自动化率")}
        value={ratioPercent(automation?.reviewed)}
        hint={
          automation
            ? tx("qa.trace.metric.automationHint", "已审核 {{ratio}} · 静态 marker 校验", {
                ratio: ratioHint(automation.reviewed),
              })
            : "—"
        }
      />
      <QaStatCard
        testId="qa-trace-metric-orphan"
        label={tx("qa.trace.metric.orphan", "孤儿率")}
        value={ratioPercent(orphan?.library)}
        hint={
          orphan
            ? tx("qa.trace.metric.orphanHint", "{{ratio}} · 必须为 0", {
                ratio: ratioHint(orphan.library),
              })
            : "—"
        }
      />
      {suppressed ? (
        <p
          data-testid="qa-trace-suppressed"
          className="rounded-lg border border-amber-500/25 bg-amber-500/[0.06] px-3 py-2 text-[12.5px] text-amber-800 sm:col-span-2 xl:col-span-4 dark:text-amber-200"
        >
          {tx("qa.trace.metricsSuppressed", "指标已抑制：{{reason}}", {
            reason:
              summary.metrics_suppressed ||
              tx("qa.trace.metricsSuppressedFallback", "库存在结构错误，先修断链再看覆盖率"),
          })}
        </p>
      ) : null}
    </div>
  );
}

// -- chain tree -----------------------------------------------------------

function TraceTreePanel({
  query,
  onPickImpact,
}: {
  query: ReturnType<typeof useQaQuery<QaTraceTree>>;
  onPickImpact: (kind: "source" | "case", id: string) => void;
}) {
  const tx = useQaCopy();
  const tree = query.data;
  return (
    <QaPanel className="px-4 py-3">
      <QaSectionTitle
        title={tx("qa.trace.tree.title", "追溯链")}
        count={tree?.counts.cases}
        action={
          <span className="text-[11px] text-muted-foreground">
            {tree
              ? tx("qa.trace.tree.counts", "{{sources}} 来源 · {{testpoints}} 测试点 · {{scripts}} 脚本", {
                  sources: tree.counts.sources,
                  testpoints: tree.counts.testpoints,
                  scripts: tree.counts.scripts,
                })
              : null}
          </span>
        }
      />
      {query.error ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.tree", "加载追溯链失败")}: ${query.error}`}
          onRetry={query.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : query.loading && !tree ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : !tree || tree.sources.length === 0 ? (
        <QaEmptyState
          testId="qa-trace-tree-empty"
          title={tx("qa.trace.tree.empty", "这个库还没有来源")}
          hint={tx(
            "qa.trace.tree.emptyHint",
            "先在 sources/ 里写一条带证据的 REQ/UI/API 来源，再挂测试点与用例。",
          )}
        />
      ) : (
        <ul className="flex flex-col gap-3" data-testid="qa-trace-tree">
          {tree.sources.map((source) => (
            <SourceRow key={source.id} source={source} onPickImpact={onPickImpact} />
          ))}
          {tree.orphans.length > 0 ? (
            <li
              data-testid="qa-trace-orphans"
              className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2"
            >
              <p className="text-[12.5px] font-medium text-destructive">
                {tx("qa.trace.tree.orphans", "无法上溯到来源的用例（{{count}}）", {
                  count: tree.orphans.length,
                })}
              </p>
              <ul className="mt-1 flex flex-col gap-1">
                {tree.orphans.map((item) => (
                  <li key={item.id} className="font-mono text-[12px] text-muted-foreground">
                    {item.id} · {item.title}
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
        </ul>
      )}
    </QaPanel>
  );
}

function SourceRow({
  source,
  onPickImpact,
}: {
  source: QaTraceSourceNode;
  onPickImpact: (kind: "source" | "case", id: string) => void;
}) {
  const tx = useQaCopy();
  return (
    <li
      data-testid={`qa-trace-source-${source.id}`}
      className="rounded-lg border border-border/60 bg-card px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <QaBadge tone="violet" className="font-mono">
          {source.type}
        </QaBadge>
        <button
          type="button"
          className="font-mono text-[12.5px] font-semibold text-foreground hover:underline"
          onClick={() => onPickImpact("source", source.id)}
          title={tx("qa.trace.tree.impactHint", "查看影响面")}
        >
          {source.id}
        </button>
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground" title={source.title}>
          {source.title}
        </span>
        <QaBadge tone={REVIEW_TONE[source.status] ?? "neutral"}>
          {REVIEW_LABEL[source.status] ?? source.status}
        </QaBadge>
        <QaBadge tone={source.confidence === "confirmed" ? "blue" : "amber"}>
          {source.confidence === "confirmed"
            ? tx("qa.trace.confidence.confirmed", "已确认")
            : tx("qa.trace.confidence.observed", "仅观测")}
        </QaBadge>
        {source.stale ? (
          <QaBadge tone="red" dot>
            {tx("qa.trace.badge.stale", "已过期")}
          </QaBadge>
        ) : null}
      </div>
      {source.testpoints.length === 0 && source.cases.length === 0 ? (
        <p className="mt-1 text-[12px] text-muted-foreground">
          {tx("qa.trace.tree.noDownstream", "没有下游测试点或用例（可能漏测）")}
        </p>
      ) : null}
      <ul className="mt-2 flex flex-col gap-2 border-l border-border/60 pl-3">
        {source.testpoints.map((testpoint) => (
          <li key={testpoint.id} data-testid={`qa-trace-testpoint-${testpoint.id}`}>
            <div className="flex flex-wrap items-center gap-2">
              <GitBranch className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="font-mono text-[12px] font-medium text-foreground">{testpoint.id}</span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground" title={testpoint.title}>
                {testpoint.title}
              </span>
              <QaBadge tone={REVIEW_TONE[testpoint.status] ?? "neutral"}>
                {REVIEW_LABEL[testpoint.status] ?? testpoint.status}
              </QaBadge>
              <QaBadge tone="neutral">{testpoint.risk}</QaBadge>
            </div>
            {testpoint.cases.length === 0 ? (
              <p className="mt-1 pl-5 text-[12px] text-muted-foreground">
                {tx("qa.trace.tree.noCases", "没有用例覆盖这个测试点")}
              </p>
            ) : (
              <ul className="mt-1 flex flex-col gap-1 pl-5">
                {testpoint.cases.map((item) => (
                  <CaseRow key={item.id} item={item} onPickImpact={onPickImpact} />
                ))}
              </ul>
            )}
          </li>
        ))}
        {source.cases.map((item) => (
          <CaseRow key={item.id} item={item} onPickImpact={onPickImpact} />
        ))}
      </ul>
    </li>
  );
}

function CaseRow({
  item,
  onPickImpact,
}: {
  item: QaTraceCaseNode;
  onPickImpact: (kind: "source" | "case", id: string) => void;
}) {
  const tx = useQaCopy();
  return (
    <li data-testid={`qa-trace-case-${item.id}`} className="rounded-md bg-muted/30 px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="font-mono text-[12px] font-medium text-foreground hover:underline"
          onClick={() => onPickImpact("case", item.id)}
          title={tx("qa.trace.tree.impactHint", "查看影响面")}
        >
          {item.id}
        </button>
        <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground" title={item.title}>
          {item.title}
        </span>
        <QaPriorityBadge priority={item.priority as "P0" | "P1" | "P2" | "P3"} />
        <QaBadge tone={REVIEW_TONE[item.status] ?? "neutral"}>
          {REVIEW_LABEL[item.status] ?? item.status}
        </QaBadge>
        {item.needs_recheck ? (
          <QaBadge
            tone="amber"
            dot
            title={item.recheck_reasons.map(reasonText).join("，") || undefined}
          >
            {tx("qa.trace.badge.needsRecheck", "待复核")}
          </QaBadge>
        ) : null}
        {item.automation === "manual" ? (
          <QaBadge tone="neutral">{tx("qa.trace.badge.manual", "手工")}</QaBadge>
        ) : null}
      </div>
      {item.script ? (
        <p
          className={cn(
            "mt-0.5 truncate font-mono text-[11px]",
            item.script.resolves ? "text-muted-foreground" : "text-destructive",
          )}
          title={item.script.problem || item.script.binding}
        >
          {item.script.binding}
          {item.script.resolves ? "" : ` · ${item.script.problem}`}
        </p>
      ) : null}
    </li>
  );
}

// -- impact ---------------------------------------------------------------

function TraceImpactPanel({
  impact,
  loading,
  error,
  kind,
  onKindChange,
  value,
  onValueChange,
  onSubmit,
  onRetry,
  target,
}: {
  impact: QaTraceImpact | null;
  loading: boolean;
  error: string;
  kind: "source" | "case";
  onKindChange: (kind: "source" | "case") => void;
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  onRetry: () => void;
  target: { kind: "source" | "case"; id: string } | null;
}) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-impact">
      <QaSectionTitle title={tx("qa.trace.impact.title", "影响面查询")} />
      <div className="flex flex-wrap items-center gap-2">
        <Select value={kind} onValueChange={(next) => onKindChange(next as "source" | "case")}>
          <SelectTrigger
            aria-label={tx("qa.trace.impact.kind", "查询类型")}
            className="h-8 w-[7.5rem]"
            data-testid="qa-trace-impact-kind"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="source">{tx("qa.trace.impact.bySource", "按来源")}</SelectItem>
            <SelectItem value="case">{tx("qa.trace.impact.byCase", "按用例")}</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSubmit();
          }}
          aria-label={tx("qa.trace.impact.id", "来源或用例 ID")}
          placeholder={kind === "source" ? "REQ-LOGIN-01 / UI-LOGIN-02" : "TC-LOGIN-003"}
          className="h-8 min-w-[12rem] flex-1 font-mono text-[12px]"
          data-testid="qa-trace-impact-input"
        />
        <Button
          type="button"
          size="sm"
          className="h-8 gap-1.5 px-2.5"
          onClick={onSubmit}
          disabled={loading}
          data-testid="qa-trace-impact-submit"
        >
          <Search className="h-3.5 w-3.5" aria-hidden />
          {tx("qa.trace.impact.submit", "查询")}
        </Button>
      </div>

      {error ? (
        <div className="mt-3">
          <QaErrorBar
            message={`${tx("qa.trace.error.impact", "影响面查询失败")}: ${error}`}
            onRetry={onRetry}
            retryLabel={tx("qa.actions.retry", "重试")}
          />
        </div>
      ) : null}

      {loading ? (
        <div className="mt-3">
          <QaLoading label={tx("qa.status.loading", "加载中…")} />
        </div>
      ) : impact ? (
        <div className="mt-3 flex flex-col gap-2" data-testid="qa-trace-impact-result">
          <p className="text-[12px] text-muted-foreground">
            {tx("qa.trace.impact.summary", "{{kind}} {{id}}：{{testpoints}} 测试点 · {{cases}} 用例 · {{scripts}} 脚本", {
              kind: impact.target.kind,
              id: impact.target.id,
              testpoints: impact.counts.testpoints,
              cases: impact.counts.cases,
              scripts: impact.counts.scripts,
            })}
          </p>
          <ul className="flex flex-col gap-1">
            {impact.testpoints.map((testpoint) => (
              <li key={testpoint.id} className="flex flex-wrap items-center gap-2 text-[12px]">
                <span className="font-mono font-medium text-foreground">{testpoint.id}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{testpoint.title}</span>
                <QaBadge tone={REVIEW_TONE[testpoint.status] ?? "neutral"}>
                  {REVIEW_LABEL[testpoint.status] ?? testpoint.status}
                </QaBadge>
              </li>
            ))}
            {impact.cases.map((item) => (
              <li
                key={item.id}
                data-testid={`qa-trace-impact-case-${item.id}`}
                className="flex flex-wrap items-center gap-2 text-[12px]"
              >
                <span className="font-mono font-medium text-foreground">{item.id}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.title}</span>
                {item.needs_recheck ? (
                  <QaBadge tone="amber" dot title={item.reasons.map(reasonText).join("，")}>
                    {tx("qa.trace.badge.needsRecheck", "待复核")}
                  </QaBadge>
                ) : null}
                <QaPriorityBadge priority={item.priority as "P0" | "P1" | "P2" | "P3"} />
              </li>
            ))}
            {impact.scripts.map((script) => (
              <li
                key={`${script.case_id}:${script.binding}`}
                className="truncate font-mono text-[11px] text-muted-foreground"
                title={script.problem || script.binding}
              >
                {script.case_id} · {script.binding}
              </li>
            ))}
          </ul>
          {impact.counts.cases === 0 && impact.counts.testpoints === 0 ? (
            <p className="text-[12px] text-muted-foreground">
              {tx("qa.trace.impact.empty", "这个目标下面没有测试点或用例")}
            </p>
          ) : null}
        </div>
      ) : target ? null : (
        <p className="mt-3 text-[12px] text-muted-foreground">
          {tx("qa.trace.impact.hint", "输入来源或用例 ID，列出要跟着改的测试点、用例与脚本。")}
        </p>
      )}
    </QaPanel>
  );
}

// -- stale ----------------------------------------------------------------

function TraceStalePanel({
  stale,
  loading,
  error,
  busy,
  onRecordBaseline,
  onRetry,
}: {
  stale: QaTraceStale | null;
  loading: boolean;
  error: string;
  busy: boolean;
  onRecordBaseline: () => void;
  onRetry: () => void;
}) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-stale">
      <QaSectionTitle
        title={tx("qa.trace.stale.title", "变更与待复核")}
        count={stale?.counts.needs_recheck}
        action={
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[12px]"
            onClick={onRecordBaseline}
            disabled={busy || !stale}
            data-testid="qa-trace-stale-write"
            title={tx(
              "qa.trace.stale.writeHint",
              "把当前指纹记录为基线：只回答“变了什么”，不会替人审核",
            )}
          >
            {tx("qa.trace.stale.write", "记录基线")}
          </Button>
        }
      />
      {error ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.stale", "加载变更失败")}: ${error}`}
          onRetry={onRetry}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : loading ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : !stale ? null : (
        <div className="flex flex-col gap-2">
          <p className="text-[12px] text-muted-foreground">
            {stale.baseline === "recorded"
              ? tx("qa.trace.stale.baselineRecorded", "基线已记录 · 变更 {{changed}} 项", {
                  changed: stale.counts.changed ?? 0,
                })
              : tx("qa.trace.stale.baselineMissing", "还没有基线：先点「记录基线」再比较变更")}
          </p>
          {stale.changed.length > 0 ? (
            <ul className="flex flex-col gap-1" data-testid="qa-trace-stale-changed">
              {stale.changed.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2 text-[12px]">
                  <QaBadge tone="neutral" className="font-mono">
                    {item.kind}
                  </QaBadge>
                  <span className="font-mono text-foreground">{item.id}</span>
                  <span className="text-muted-foreground">
                    {[
                      item.content_changed ? tx("qa.trace.stale.content", "内容") : "",
                      item.dependency_changed ? tx("qa.trace.stale.dependency", "上游") : "",
                      item.in_baseline ? "" : tx("qa.trace.stale.newEntity", "新增"),
                    ]
                      .filter(Boolean)
                      .join(" / ")}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {stale.needs_recheck.length > 0 ? (
            <ul className="flex flex-col gap-1" data-testid="qa-trace-stale-recheck">
              {stale.needs_recheck.map((item) => (
                <li key={item.case_id} className="flex flex-wrap items-center gap-2 text-[12px]">
                  <QaBadge tone="amber" dot>
                    {tx("qa.trace.badge.needsRecheck", "待复核")}
                  </QaBadge>
                  <span className="font-mono text-foreground">{item.case_id}</span>
                  <span className="text-muted-foreground">
                    {item.reasons.map(reasonText).join("，")}
                    {item.changed_ids.length > 0 ? ` · ${item.changed_ids.join(", ")}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-muted-foreground">
              {tx("qa.trace.stale.clean", "没有待复核的用例")}
            </p>
          )}
        </div>
      )}
    </QaPanel>
  );
}

// -- drafts ---------------------------------------------------------------

function TraceDraftsPanel({
  drafts,
  loading,
  error,
  busy,
  reviewer,
  onReviewerChange,
  onDecide,
  onRetry,
}: {
  drafts: QaTraceDraft[];
  loading: boolean;
  error: string;
  busy: string;
  reviewer: string;
  onReviewerChange: (value: string) => void;
  onDecide: (draft: QaTraceDraft, approved: boolean) => void;
  onRetry: () => void;
}) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-drafts">
      <QaSectionTitle title={tx("qa.trace.drafts.title", "草稿审核")} count={drafts.length} />
      {error ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.drafts", "加载草稿失败")}: ${error}`}
          onRetry={onRetry}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : loading ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : drafts.length === 0 ? (
        <QaEmptyState
          testId="qa-trace-drafts-empty"
          title={tx("qa.trace.drafts.empty", "没有待审草稿")}
          hint={tx(
            "qa.trace.drafts.emptyHint",
            "Agent 只写 draft/<batch>/，人审通过后才进入正式库并计入覆盖率。",
          )}
        />
      ) : (
        <div className="flex flex-col gap-2">
          <Input
            value={reviewer}
            onChange={(event) => onReviewerChange(event.target.value)}
            aria-label={tx("qa.trace.drafts.reviewer", "审核人（可选）")}
            placeholder={tx("qa.trace.drafts.reviewerPlaceholder", "审核人（可选，如 qa.zhang）")}
            className="h-8 text-[12px]"
            data-testid="qa-trace-reviewer"
          />
          <ul className="flex flex-col gap-2">
            {drafts.map((draft) => {
              const rejected = draft.status === "rejected";
              const approving = busy === `approve:${draft.id}`;
              const rejecting = busy === `reject:${draft.id}`;
              return (
                <li
                  key={`${draft.batch}/${draft.id}`}
                  data-testid={`qa-trace-draft-${draft.id}`}
                  className="rounded-lg border border-border/60 bg-card px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <QaBadge tone="blue" className="font-mono">
                      {draft.kind}
                    </QaBadge>
                    <span className="font-mono text-[12.5px] font-semibold text-foreground">
                      {draft.id}
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {draft.batch}
                    </span>
                    <QaBadge tone={rejected ? "red" : draft.valid ? "amber" : "red"}>
                      {rejected
                        ? tx("qa.trace.drafts.rejected", "已退回")
                        : draft.valid
                          ? tx("qa.trace.drafts.pending", "待审核")
                          : tx("qa.trace.drafts.invalid", "草稿无效")}
                    </QaBadge>
                    <span className="min-w-0 flex-1" />
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[12px]"
                      onClick={() => onDecide(draft, true)}
                      disabled={Boolean(busy) || rejected}
                      data-testid={`qa-trace-approve-${draft.id}`}
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden />
                      {tx("qa.trace.drafts.approve", "通过")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 gap-1 px-2 text-[12px]"
                      onClick={() => onDecide(draft, false)}
                      disabled={Boolean(busy) || rejected}
                      data-testid={`qa-trace-reject-${draft.id}`}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                      {tx("qa.trace.drafts.reject", "退回")}
                    </Button>
                  </div>
                  <p className="mt-1 truncate text-[11px] text-muted-foreground" title={draft.path}>
                    {draft.path}
                  </p>
                  {draft.problems.length > 0 ? (
                    <ul className="mt-1 flex flex-col gap-0.5">
                      {draft.problems.map((problem) => (
                        <li key={problem} className="text-[11px] text-destructive">
                          {problem}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {approving || rejecting ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {tx("qa.trace.drafts.working", "处理中…")}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </QaPanel>
  );
}

// -- failure --------------------------------------------------------------

function TraceFailurePanel({
  runs,
  runsLoading,
  runsError,
  selectedRun,
  onSelectRun,
  failure,
  failureLoading,
  failureError,
  onRetry,
}: {
  runs: QaTraceRunSummary[];
  runsLoading: boolean;
  runsError: string;
  selectedRun: string;
  onSelectRun: (run: string) => void;
  failure: QaTraceFailure | null;
  failureLoading: boolean;
  failureError: string;
  onRetry: () => void;
}) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-failure">
      <QaSectionTitle
        title={tx("qa.trace.failure.title", "失败追溯")}
        count={failure?.counts.failed_cases}
      />
      {runsError ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.runs", "加载运行记录失败")}: ${runsError}`}
          onRetry={onRetry}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : runsLoading ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : runs.length === 0 ? (
        <QaEmptyState
          testId="qa-trace-failure-empty"
          title={tx("qa.trace.failure.noRuns", "还没有运行记录")}
          hint={tx(
            "qa.trace.failure.noRunsHint",
            "用 pytest 插件跑一次：python -m pytest -p qa_trace.pytest_plugin --qa-project=<项目目录> <脚本>，manifest 会写进 runs/。",
          )}
        />
      ) : (
        <div className="flex flex-col gap-2">
          <Select value={selectedRun} onValueChange={onSelectRun}>
            <SelectTrigger
              aria-label={tx("qa.trace.failure.run", "选择运行")}
              className="h-8"
              data-testid="qa-trace-run-select"
            >
              <SelectValue placeholder={tx("qa.trace.failure.runPlaceholder", "选择运行记录")} />
            </SelectTrigger>
            <SelectContent>
              {runs.map((run) => (
                <SelectItem key={run.run_id} value={run.run_id}>
                  {`${run.run_id} · ${run.status} · ${run.failed_cases} 失败`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {failureError ? (
            <QaErrorBar
              message={`${tx("qa.trace.error.failure", "加载失败追溯失败")}: ${failureError}`}
              onRetry={onRetry}
              retryLabel={tx("qa.actions.retry", "重试")}
            />
          ) : failureLoading ? (
            <QaLoading label={tx("qa.status.loading", "加载中…")} />
          ) : !failure ? null : (
            <div className="flex flex-col gap-2" data-testid="qa-trace-failure-result">
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.trace.failure.summary", "{{run}} · {{results}} 条结果，{{failed}} 条失败 · 环境 {{env}}", {
                  run: failure.run.run_id,
                  results: failure.counts.results ?? 0,
                  failed: failure.counts.failed_results ?? 0,
                  env: failure.run.environment || "—",
                })}
              </p>
              {failure.case_missing ? (
                <p className="text-[12px] text-amber-700 dark:text-amber-300">
                  {tx("qa.trace.failure.caseMissing", "该用例本次没有执行：{{case}}", {
                    case: failure.requested_case,
                  })}
                </p>
              ) : null}
              {failure.failures.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">
                  {tx("qa.trace.failure.none", "这次运行没有失败结果")}
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {failure.failures.map((item) => (
                    <li
                      key={item.case_id}
                      data-testid={`qa-trace-failure-${item.case_id}`}
                      className="rounded-lg border border-border/60 bg-card px-3 py-2"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <QaBadge tone="red" dot>
                          {tx("qa.trace.failure.failed", "失败")}
                        </QaBadge>
                        <span className="font-mono text-[12.5px] font-semibold text-foreground">
                          {item.case_id}
                        </span>
                        <span className="min-w-0 flex-1" />
                        {item.current.needs_recheck ? (
                          <QaBadge tone="amber" dot title={item.current.reasons.map(reasonText).join("，")}>
                            {tx("qa.trace.badge.needsRecheck", "待复核")}
                          </QaBadge>
                        ) : null}
                        {item.current.exists === false ? (
                          <QaBadge tone="red">
                            {tx("qa.trace.failure.caseGone", "用例已不在库中")}
                          </QaBadge>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {tx("qa.trace.failure.chain", "回溯方式：{{origin}}", {
                          origin:
                            item.chain.origin === "snapshot"
                              ? tx("qa.trace.failure.originSnapshot", "运行快照")
                              : item.chain.origin === "current"
                                ? tx("qa.trace.failure.originCurrent", "当前库")
                                : tx("qa.trace.failure.originMissing", "用例已删除"),
                        })}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="text-[11px] text-muted-foreground">
                          {tx("qa.trace.failure.testpoints", "测试点")}
                        </span>
                        {item.chain.testpoints.length === 0 ? (
                          <span className="text-[11px] text-muted-foreground">—</span>
                        ) : (
                          item.chain.testpoints.map((testpoint) => (
                            <QaBadge key={testpoint.id} tone="blue" className="font-mono">
                              {testpoint.id}
                            </QaBadge>
                          ))
                        )}
                        <span className="text-[11px] text-muted-foreground">
                          {tx("qa.trace.failure.sources", "来源")}
                        </span>
                        {item.chain.sources.length === 0 ? (
                          <span className="text-[11px] text-muted-foreground">—</span>
                        ) : (
                          item.chain.sources.map((source) => (
                            <QaBadge key={source.id} tone="violet" className="font-mono">
                              {source.id}
                            </QaBadge>
                          ))
                        )}
                      </div>
                      {item.results.map((result) => (
                        <div key={`${result.nodeid}-${result.attempt}`} className="mt-1">
                          <p className="truncate font-mono text-[11px] text-muted-foreground" title={result.nodeid}>
                            {result.nodeid} · {result.outcome}
                            {result.failure_stage ? ` @${result.failure_stage}` : ""}
                          </p>
                          {result.error_summary ? (
                            <QaPre className="mt-1 max-h-32">{result.error_summary}</QaPre>
                          ) : null}
                        </div>
                      ))}
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {tx("qa.trace.failure.current", "当前状态：{{status}}", {
                          status: item.current.exists
                            ? `${item.current.status}${
                                item.current.changed_since_run === null
                                  ? ""
                                  : item.current.changed_since_run
                                    ? ` · ${tx("qa.trace.failure.changedSinceRun", "运行后已修改")}`
                                    : ` · ${tx("qa.trace.failure.unchanged", "与运行时一致")}`
                              }`
                            : tx("qa.trace.failure.caseGone", "用例已不在库中"),
                        })}
                        {item.last_run
                          ? ` · ${tx("qa.trace.failure.lastRun", "最近一次 {{time}}", {
                              time: formatQaTime(item.last_run.finished_at),
                            })}`
                          : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </QaPanel>
  );
}

// -- diagnostics ----------------------------------------------------------

function TraceDiagnostics({ summary }: { summary: QaTraceSummary | null }) {
  const tx = useQaCopy();
  const items = summary?.diagnostics.items ?? [];
  if (!summary || items.length === 0) return null;
  const counts = summary.diagnostics.counts;
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-diagnostics">
      <QaSectionTitle
        title={tx("qa.trace.diagnostics.title", "校验诊断")}
        count={items.length}
        action={
          <span className="text-[11px] text-muted-foreground">
            {tx("qa.trace.diagnostics.counts", "error {{error}} · warn {{warn}} · info {{info}}", {
              error: counts.error ?? 0,
              warn: counts.warn ?? 0,
              info: counts.info ?? 0,
            })}
          </span>
        }
      />
      <ul className="flex max-h-64 flex-col gap-1 overflow-y-auto">
        {items.map((item, index) => (
          <li
            key={`${item.code}-${item.path ?? ""}-${item.field ?? ""}-${index}`}
            className="flex flex-wrap items-baseline gap-2 text-[12px]"
          >
            <QaBadge tone={item.severity === "error" ? "red" : item.severity === "warn" ? "amber" : "neutral"}>
              {item.severity}
            </QaBadge>
            <span className="font-mono text-[11px] text-foreground">{item.code}</span>
            <span className="min-w-0 flex-1 break-words text-muted-foreground">
              {item.path ? `${item.path}${item.field ? `:${item.field}` : ""} · ` : ""}
              {item.message}
            </span>
          </li>
        ))}
      </ul>
    </QaPanel>
  );
}
