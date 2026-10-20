import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, RefreshCw, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { QaDetailDrawer, QaDetailSection } from "./QaDetailDrawer";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  approveQaTraceReview,
  approveQaTraceReviews,
  loadQaCase,
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
  type QaTraceCoverageBlock,
  type QaCase,
  type QaTraceDraft,
  type QaTraceFailure,
  type QaTraceImpact,
  type QaTraceRatio,
  type QaTraceRunSummary,
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
  const [draftDetail, setDraftDetail] = useState<QaTraceDraft | null>(null);
  const [caseDetail, setCaseDetail] = useState<QaCase | null>(null);
  const openCase = (id: string) => {
    void (async () => {
      try {
        setCaseDetail(await loadQaCase(token, id));
      } catch (reason) {
        setActionError(qaErrorMessage(reason));
      }
    })();
  };
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

  const approveAllDrafts = () => {
    const ids = drafts
      .filter((draft) => draft.valid && draft.status !== "rejected")
      .map((draft) => draft.id);
    if (ids.length === 0) return;
    void runAction("approve-all", async () => {
      const outcome = await approveQaTraceReviews(client, {
        project: projectId || undefined,
        ids,
        reviewer: reviewer.trim() || undefined,
      });
      if (outcome.failed.length === 0) {
        return tx("qa.trace.drafts.approvedAll", "已通过 {{count}} 条草稿", {
          count: outcome.approved,
        });
      }
      return tx(
        "qa.trace.drafts.approvedSome",
        "通过 {{approved}} 条，失败 {{failed}} 条：{{reason}}",
        {
          approved: outcome.approved,
          failed: outcome.failed.length,
          reason: outcome.failed[0]?.error ?? "",
        },
      );
    });
  };

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
              <TraceGapsPanel query={treeQuery} onOpenCase={openCase} />
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
                onApproveAll={approveAllDrafts}
                onInspect={setDraftDetail}
                onRetry={draftsQuery.reload}
              />
              <QaDetailDrawer
                open={draftDetail !== null}
                onOpenChange={(open) => {
                  if (!open) setDraftDetail(null);
                }}
                testId="qa-trace-draft-drawer"
                title={draftDetail ? `${draftDetail.kind} ${draftDetail.id}` : ""}
                description={draftDetail?.path ?? ""}
                badge={
                  draftDetail ? (
                    <QaBadge tone={draftDetail.valid ? "amber" : "red"}>
                      {draftDetail.valid
                        ? tx("qa.trace.drafts.pending", "待审核")
                        : tx("qa.trace.drafts.invalid", "草稿无效")}
                    </QaBadge>
                  ) : null
                }
                meta={
                  draftDetail
                    ? [
                        { label: tx("qa.trace.drafts.batch", "批次"), value: draftDetail.batch, mono: true },
                        { label: tx("qa.trace.drafts.status", "状态"), value: draftDetail.status },
                      ]
                    : []
                }
              >
                {draftDetail && draftDetail.problems.length > 0 ? (
                  <QaDetailSection title={tx("qa.trace.drafts.problems", "问题")}>
                    <ul className="flex flex-col gap-1 text-[11.5px] text-destructive">
                      {draftDetail.problems.map((problem) => (
                        <li key={problem}>{problem}</li>
                      ))}
                    </ul>
                  </QaDetailSection>
                ) : null}
                <QaDetailSection title={tx("qa.trace.drafts.content", "内容")} hint="YAML">
                  <QaPre className="max-h-[26rem]">
                    {JSON.stringify(
                      (draftDetail as (QaTraceDraft & { entity?: Record<string, unknown> }) | null)
                        ?.entity ?? {},
                      null,
                      2,
                    )}
                  </QaPre>
                </QaDetailSection>
              </QaDetailDrawer>
              <QaDetailDrawer
                open={caseDetail !== null}
                onOpenChange={(open) => {
                  if (!open) setCaseDetail(null);
                }}
                testId="qa-trace-case-drawer"
                title={caseDetail ? `${caseDetail.code} · ${caseDetail.title}` : ""}
                description={caseDetail?.code ?? ""}
                meta={
                  caseDetail
                    ? [
                        { label: tx("qa.cases.kind", "类型"), value: caseDetail.kind },
                        { label: tx("qa.cases.priority", "优先级"), value: caseDetail.priority },
                        { label: tx("qa.cases.status", "状态"), value: caseDetail.status },
                        {
                          label: tx("qa.testpoints.tags", "标签"),
                          value: caseDetail.tags.join(", ") || "—",
                          mono: true,
                        },
                      ]
                    : []
                }
              >
                {caseDetail ? (
                  <>
                    <QaDetailSection title={tx("qa.assets.caseRequest", "请求")} hint="JSON">
                      <QaPre className="max-h-64">
                        {JSON.stringify(caseDetail.api?.request ?? {}, null, 2)}
                      </QaPre>
                    </QaDetailSection>
                    <QaDetailSection
                      title={tx("qa.assets.caseAssertions", "断言")}
                      hint={String(caseDetail.api?.assertions?.length ?? 0)}
                    >
                      <QaPre className="max-h-64">
                        {JSON.stringify(caseDetail.api?.assertions ?? [], null, 2)}
                      </QaPre>
                    </QaDetailSection>
                    <QaDetailSection title={tx("qa.assets.caseExpected", "预期结果")}>
                      <p className="whitespace-pre-wrap text-[12.5px]">
                        {caseDetail.expected || "—"}
                      </p>
                    </QaDetailSection>
                  </>
                ) : null}
              </QaDetailDrawer>
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

// -- coverage gaps --------------------------------------------------------

/** What the chain is missing, not what it already contains.
 *
 * Every case in the library is linked by construction (a ready case must hang
 * off a test point), so drawing the whole chain produced a tree that could only
 * ever be complete - it told the operator nothing.  This panel answers the
 * question that does change: which source has no test point, which test point
 * has no case, and which case has no link at all.
 */
function TraceGapsPanel({
  query,
  onOpenCase,
}: {
  query: ReturnType<typeof useQaQuery<QaTraceTree>>;
  onOpenCase: (id: string) => void;
}) {
  const tx = useQaCopy();
  const tree = query.data;
  const gaps = useMemo(() => {
    const sources: { id: string; title: string; hint: string }[] = [];
    const testpoints: { id: string; title: string; hint: string }[] = [];
    for (const source of tree?.sources ?? []) {
      // A retired source is closed on purpose, not a coverage gap.
      if (source.status !== "active") continue;
      if (source.testpoints.length === 0) {
        sources.push({ id: source.id, title: source.title, hint: source.id });
      }
      for (const testpoint of source.testpoints) {
        if (testpoint.status === "deprecated") continue;
        if (testpoint.cases.length > 0) continue;
        if (testpoints.some((item) => item.id === testpoint.id)) continue;
        testpoints.push({
          id: testpoint.id,
          title: testpoint.title,
          hint: `${testpoint.id} · ${source.id}`,
        });
      }
    }
    return { sources, testpoints, orphans: tree?.orphans ?? [] };
  }, [tree]);
  const total = gaps.sources.length + gaps.testpoints.length + gaps.orphans.length;

  const chip = (
    item: { id: string; title: string; hint: string },
    onOpen?: (id: string) => void,
  ) => {
    const body = (
      <>
        <span className="font-mono text-muted-foreground">{item.id}</span>
        <span className="ml-1.5">{item.title}</span>
      </>
    );
    if (!onOpen) {
      return (
        <span
          className="inline-flex items-center rounded-full border border-border/60 bg-card px-2 py-0.5 text-[11.5px]"
          title={item.hint}
        >
          {body}
        </span>
      );
    }
    return (
      <button
        type="button"
        className="inline-flex items-center rounded-full border border-border/60 bg-card px-2 py-0.5 text-[11.5px] hover:bg-accent/40"
        title={item.hint}
        onClick={() => onOpen(item.id)}
      >
        {body}
      </button>
    );
  };

  const group = (
    key: string,
    label: string,
    items: { id: string; title: string; hint: string }[],
    onOpen?: (id: string) => void,
  ) =>
    items.length === 0 ? null : (
      <div key={key} className="flex flex-col gap-1" data-testid={`qa-trace-gaps-${key}`}>
        <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
        <ul className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <li key={item.id}>{chip(item, onOpen)}</li>
          ))}
        </ul>
      </div>
    );

  return (
    <QaPanel className="px-4 py-3">
      <QaSectionTitle title={tx("qa.trace.gaps.title", "覆盖缺口")} count={total} />
      {query.error ? (
        <QaErrorBar
          message={`${tx("qa.trace.error.tree", "加载追溯链失败")}: ${query.error}`}
          onRetry={query.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : query.loading && !tree ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : total === 0 ? (
        <p
          data-testid="qa-trace-gaps-empty"
          className="rounded-lg border border-dashed border-border/70 px-3 py-3 text-[12px] text-muted-foreground"
        >
          {tx(
            "qa.trace.gaps.none",
            "没有缺口：每条来源都有测试点，每个测试点都有用例。链路本身在「测试点」页签按模块分层看。",
          )}
        </p>
      ) : (
        <div className="flex flex-col gap-2" data-testid="qa-trace-gaps">
          {group("sources", tx("qa.trace.gaps.sources", "来源没有测试点"), gaps.sources)}
          {group("testpoints", tx("qa.trace.gaps.testpoints", "测试点没有用例"), gaps.testpoints)}
          {group(
            "orphans",
            tx("qa.trace.gaps.orphans", "用例没有链路"),
            gaps.orphans.map((item) => ({
              id: item.id,
              title: item.title,
              hint: item.id,
            })),
            onOpenCase,
          )}
        </div>
      )}
    </QaPanel>
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
  onApproveAll,
  onInspect,
  onRetry,
}: {
  drafts: QaTraceDraft[];
  loading: boolean;
  error: string;
  busy: string;
  reviewer: string;
  onReviewerChange: (value: string) => void;
  onDecide: (draft: QaTraceDraft, approved: boolean) => void;
  onApproveAll: () => void;
  onInspect: (draft: QaTraceDraft) => void;
  onRetry: () => void;
}) {
  const tx = useQaCopy();
  return (
    <QaPanel className="px-4 py-3" testId="qa-trace-drafts">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <QaSectionTitle
          title={tx("qa.trace.drafts.title", "草稿审核")}
          count={drafts.length}
        />
        {drafts.some((draft) => draft.valid && draft.status !== "rejected") ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 gap-1 px-2 text-[12px]"
            onClick={onApproveAll}
            disabled={Boolean(busy)}
            data-testid="qa-trace-approve-all"
          >
            <Check className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.trace.drafts.approveAll", "通过本批全部")}
          </Button>
        ) : null}
      </div>
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
            {drafts.slice(0, 5).map((draft) => {
              const rejected = draft.status === "rejected";
              const needsLink = draft.problems.some((problem) =>
                problem.includes("TRACE_LINK_MISSING"),
              );
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
                      variant="ghost"
                      className="h-7 gap-1 px-2 text-[12px]"
                      onClick={() => onInspect(draft)}
                      data-testid={`qa-trace-inspect-${draft.id}`}
                    >
                      {tx("qa.trace.drafts.inspect", "详情")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      className="h-7 gap-1 px-2 text-[12px]"
                      onClick={() => onDecide(draft, true)}
                      disabled={Boolean(busy) || rejected || !draft.valid}
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
                  {needsLink ? (
                    <p className="mt-1 text-[11px] text-amber-600">
                      {tx(
                        "qa.trace.drafts.needsLink",
                        "这条用例还没有测试点。先让 Agent 用 qa_testpoint action=attach 挂上测试点（或先建一条测试点），再回来通过。",
                      )}
                    </p>
                  ) : null}
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
          {drafts.length > 5 ? (
            <p className="text-[11.5px] text-muted-foreground" data-testid="qa-trace-drafts-more">
              {tx("qa.trace.drafts.more", "还有 {{count}} 条，通过一条就会补上一条", {
                count: drafts.length - 5,
              })}
            </p>
          ) : null}
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
