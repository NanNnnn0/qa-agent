import { useMemo, useState } from "react";
import { ArrowRight, ChevronDown, ChevronRight } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { loadQaTestpoints, type QaProject, type QaTraceSource } from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailSection } from "./QaDetailDrawer";
import {
  QaBadge,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaSectionTitle,
  QaTableShell,
  QA_TD_CLASS,
  QA_TH_CLASS,
  useQaCopy,
} from "./qa-ui";
import { buildGroupTree, flattenGroups, groupLabel, toggleCollapsed } from "./qa-groups";
import { useQaQuery } from "./useQaQuery";

const SOURCE_TONE: Record<string, "blue" | "violet" | "amber" | "neutral" | "red"> = {
  req: "blue",
  api: "violet",
  ui: "amber",
  bug: "red",
  std: "neutral",
  ex: "neutral",
};

const RISK_TONE: Record<string, "red" | "amber" | "neutral"> = {
  high: "red",
  medium: "amber",
  low: "neutral",
};

/** Design method → what it means for the person reading the test point. */
const METHOD_LABEL: Record<string, string> = {
  equivalence: "等价类划分",
  boundary: "边界值",
  scenario: "场景法",
  state: "状态迁移",
  orthogonal: "正交组合",
  "error-guess": "错误猜测",
};

const METHOD_HINT: Record<string, string> = {
  equivalence: "把输入分成有效/无效的等价类，每类挑代表值",
  boundary: "取区间端点及其两侧，覆盖长度、范围与格式的临界",
  scenario: "按一条完整业务流程串起步骤，验证主干链路",
  state: "覆盖对象在状态之间的迁移，包括非法迁移",
  orthogonal: "多因素组合时用正交表压掉冗余组合",
  "error-guess": "凭经验猜最容易出错的地方：空值、类型、越权、乱序",
};

const RISK_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };
const RISK_HINT: Record<string, string> = {
  high: "挂了会阻断主流程或造成资金/数据错误，必须回归",
  medium: "影响局部功能或体验，按版本回归",
  low: "边角场景，冒烟或按需回归",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  reviewed: "已评审",
  deprecated: "已归档",
};

const STATUS_TONE: Record<string, "neutral" | "green" | "amber"> = {
  draft: "amber",
  reviewed: "green",
  deprecated: "neutral",
};

/**
 * The chain above the cases: sources and the test points derived from them.
 *
 * Test points are grouped by their `模块/页面` breadcrumb so a project with a
 * hundred of them still reads as a product outline.  Read-only on purpose:
 * creating a draft is the agent's job (qa_testpoint) and promoting one is a
 * review decision that stays in the trace tab.
 */
export function QaTestpoints({
  token,
  projects,
  initialProjectId = "all",
  refreshSignal,
}: {
  token: string;
  projects: QaProject[];
  initialProjectId?: string;
  refreshSignal: number;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState(initialProjectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const resolved = projectId === "all" ? (projects[0]?.id ?? "") : projectId;

  const query = useQaQuery(
    () => (resolved ? loadQaTestpoints(token, resolved) : Promise.resolve(null)),
    [token, resolved, refreshSignal],
    { enabled: Boolean(resolved), intervalMs: 0 },
  );

  const data = query.data;
  const counts = data?.counts;
  const selected = data?.testpoints.find((item) => item.id === selectedId) ?? null;
  const sourcesById = useMemo(() => {
    const map = new Map<string, QaTraceSource>();
    for (const source of data?.sources ?? []) map.set(source.id, source);
    return map;
  }, [data?.sources]);

  const rows = useMemo(
    () => flattenGroups(buildGroupTree(data?.testpoints ?? [], (item) => item.group), collapsed),
    [data?.testpoints, collapsed],
  );

  return (
    <div className="flex flex-col gap-3" data-testid="qa-testpoints">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.testpoints.title", "测试点")}
          count={counts?.testpoints ?? 0}
        />
        <Select value={projectId} onValueChange={setProjectId}>
          <SelectTrigger
            aria-label={tx("qa.testpoints.filterProject", "项目筛选")}
            className="h-8 w-[13rem]"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{tx("qa.filters.allProjects", "全部项目")}</SelectItem>
            {projects.map((project) => (
              <SelectItem key={project.id} value={project.id}>
                {project.key}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {query.error ? <QaErrorBar message={query.error} onRetry={query.reload} /> : null}

      {!resolved ? (
        <QaEmptyState
          title={tx("qa.testpoints.noProject", "先创建一个 QA 项目")}
          hint={tx(
            "qa.testpoints.noProjectHint",
            "测试点挂在项目下：创建项目并让 Agent 用 qa_testpoint 写入来源与测试点。",
          )}
        />
      ) : query.loading && !data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { key: "sources", label: tx("qa.testpoints.sources", "来源"), value: counts?.sources ?? 0 },
              { key: "testpoints", label: tx("qa.testpoints.testpoints", "测试点"), value: counts?.testpoints ?? 0 },
              { key: "drafts", label: tx("qa.testpoints.drafts", "待评审草稿"), value: counts?.drafts ?? 0 },
              {
                key: "unlinked",
                label: tx("qa.testpoints.unlinked", "未挂链路用例"),
                value: counts?.unlinked_cases ?? 0,
              },
            ].map((item) => (
              <div
                key={item.key}
                data-testid={`qa-testpoints-count-${item.key}`}
                className="rounded-lg border border-border/60 bg-card px-3 py-2"
              >
                <p className="text-[11px] uppercase tracking-[0.04em] text-muted-foreground">
                  {item.label}
                </p>
                <p className="text-lg font-semibold tabular-nums">{item.value}</p>
              </div>
            ))}
          </div>

          <section className="flex flex-col gap-2" data-testid="qa-testpoints-list">
            <h3 className="text-[12.5px] font-medium">
              {tx("qa.testpoints.testpoints", "测试点")}
              <span className="ml-2 font-normal text-muted-foreground">
                {tx(
                  "qa.testpoints.listHint",
                  "按「模块 / 页面」分组；「覆盖」= 已挂用例数",
                )}
              </span>
            </h3>
            {data && data.testpoints.length > 0 ? (
              <QaTableShell label={tx("qa.testpoints.testpoints", "测试点")}>
                <thead>
                  <tr>
                    <th className={cn(QA_TH_CLASS, "w-[5.5rem]")}>
                      {tx("qa.testpoints.id", "编号")}
                    </th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.title", "标题")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.sourceIds", "来源")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.method", "方法")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.risk", "风险")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.coverage", "覆盖")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) =>
                    row.kind === "group" ? (
                      <tr
                        key={`group:${row.node.path || "ungrouped"}`}
                        className="bg-muted/40"
                        data-testid={`qa-testpoint-group-${row.node.path || "ungrouped"}`}
                      >
                        <td colSpan={6} className="px-2 py-1">
                          <button
                            type="button"
                            className="flex w-full items-center gap-1.5 text-left text-[12.5px] font-medium text-foreground"
                            style={{ paddingLeft: `${(row.node.level - 1) * 14}px` }}
                            onClick={() =>
                              setCollapsed((current) => toggleCollapsed(current, row.node.path))
                            }
                            aria-expanded={!collapsed.has(row.node.path)}
                          >
                            {collapsed.has(row.node.path) ? (
                              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                            )}
                            <span className="truncate">{row.node.name}</span>
                            <span className="rounded-full bg-background px-1.5 text-[11px] tabular-nums text-muted-foreground ring-1 ring-border/60">
                              {row.node.count}
                            </span>
                          </button>
                        </td>
                      </tr>
                    ) : (
                      <tr
                        key={row.item.id}
                        data-testid={`qa-testpoint-${row.item.id}`}
                        onClick={() => setSelectedId(row.item.id)}
                        className="cursor-pointer transition-colors hover:bg-accent/40"
                      >
                        <td
                          className={cn(QA_TD_CLASS, "font-mono text-[12px] text-muted-foreground")}
                          title={row.item.id}
                        >
                          {row.item.code || row.item.id}
                        </td>
                        <td className={cn(QA_TD_CLASS, "max-w-[22rem] truncate")}>
                          {row.item.title}
                        </td>
                        <td className={cn(QA_TD_CLASS, "max-w-[16rem] truncate text-[11.5px] text-muted-foreground")}>
                          {row.item.sources
                            .map((id) => sourcesById.get(id)?.title || id)
                            .join(", ")}
                        </td>
                        <td className={cn(QA_TD_CLASS, "text-[12px]")}>
                          {METHOD_LABEL[row.item.method] ?? row.item.method}
                        </td>
                        <td className={QA_TD_CLASS}>
                          <QaBadge tone={RISK_TONE[row.item.risk] ?? "neutral"}>
                            {RISK_LABEL[row.item.risk] ?? row.item.risk}
                          </QaBadge>
                        </td>
                        <td className={QA_TD_CLASS}>
                          <QaBadge tone={row.item.case_count > 0 ? "green" : "amber"}>
                            {row.item.case_count}
                          </QaBadge>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </QaTableShell>
            ) : (
              <p className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-[12px] text-muted-foreground">
                {tx(
                  "qa.testpoints.noTestpoints",
                  "还没有测试点。让 Agent 用 qa_testpoint action=create entity=testpoint 从一个来源派生测试点。",
                )}
              </p>
            )}
          </section>

          <section className="flex flex-col gap-2" data-testid="qa-testpoints-sources">
            <h3 className="text-[12.5px] font-medium">
              {tx("qa.testpoints.sources", "来源")}
              <span className="ml-2 font-normal text-muted-foreground">
                {tx(
                  "qa.testpoints.sourcesHint",
                  "链路的根：需求 / 接口契约 / 缺陷 / 规范，每条都带证据",
                )}
              </span>
            </h3>
            {data && data.sources.length > 0 ? (
              <QaTableShell label={tx("qa.testpoints.sources", "来源")}>
                <thead>
                  <tr>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.id", "编号")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.type", "类型")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.title", "标题")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.evidence", "证据")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.coverage", "测试点")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((source) => (
                    <tr key={source.id} data-testid={`qa-source-${source.id}`}>
                      <td
                        className={cn(QA_TD_CLASS, "max-w-[13rem] truncate font-mono text-[11.5px] text-muted-foreground")}
                        title={source.id}
                      >
                        {source.id}
                      </td>
                      <td className={QA_TD_CLASS}>
                        <span className="inline-flex items-center gap-1">
                          <QaBadge tone={SOURCE_TONE[source.type] ?? "neutral"}>
                            {source.type}
                          </QaBadge>
                          {source.status === "deprecated" ? (
                            <QaBadge tone="neutral">
                              {tx("qa.testpoints.deprecated", "已弃用")}
                            </QaBadge>
                          ) : null}
                        </span>
                      </td>
                      <td className={cn(QA_TD_CLASS, "max-w-[24rem] truncate")}>{source.title}</td>
                      <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                        {source.evidence.length}
                      </td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge tone={source.testpoint_count > 0 ? "violet" : "neutral"}>
                          {source.testpoint_count}
                        </QaBadge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </QaTableShell>
            ) : (
              <p className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-[12px] text-muted-foreground">
                {tx(
                  "qa.testpoints.noSources",
                  "还没有来源。让 Agent 用 qa_testpoint action=create entity=source 写一条带证据的来源草稿。",
                )}
              </p>
            )}
          </section>

          {data && data.drafts.length > 0 ? (
            <section className="flex flex-col gap-2" data-testid="qa-testpoints-drafts">
              <h3 className="text-[12.5px] font-medium">
                {tx("qa.testpoints.drafts", "待评审草稿")}
                <span className="ml-2 font-normal text-muted-foreground">
                  {tx("qa.testpoints.draftsHint", "在「追溯」页签通过后，用例才能挂上")}
                </span>
              </h3>
              <ul className="flex flex-col gap-1">
                {data.drafts.map((draft) => (
                  <li
                    key={`${draft.batch}-${draft.id}`}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 bg-card px-2.5 py-1.5 text-[12px]"
                  >
                    <QaBadge tone={draft.valid ? "neutral" : "red"}>{draft.kind}</QaBadge>
                    <span className="font-mono text-[11.5px] text-muted-foreground">{draft.id}</span>
                    <span className="text-muted-foreground">{draft.batch}</span>
                    {draft.valid ? null : (
                      <span className="text-[11.5px] text-red-600">
                        {draft.problems.join("; ")}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {data && data.unlinked_cases.length > 0 ? (
            <section className="flex flex-col gap-2" data-testid="qa-testpoints-unlinked">
              <h3 className="text-[12.5px] font-medium">
                {tx("qa.testpoints.unlinked", "未挂链路用例")}
                <span className="ml-2 font-normal text-muted-foreground">
                  {tx(
                    "qa.testpoints.unlinkedHint",
                    "没有来源也没有测试点：让 Agent 用 qa_testpoint action=attach 挂上，或补一条测试点",
                  )}
                </span>
              </h3>
              <ul className="flex flex-wrap gap-1.5">
                {data.unlinked_cases.map((item) => (
                  <li
                    key={item.case_id}
                    className="rounded-full border border-border/60 bg-card px-2 py-0.5 text-[11.5px]"
                  >
                    <span className="font-mono text-muted-foreground">{item.code}</span>
                    <span className="ml-1.5">{item.title}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      <QaDetailDrawer
        open={Boolean(selectedId)}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        testId="qa-testpoint-drawer"
        title={selected ? selected.code || selected.id : ""}
        description={selected?.title ?? ""}
        badge={
          selected ? (
            <>
              <QaBadge tone={RISK_TONE[selected.risk] ?? "neutral"}>
                {tx("qa.testpoints.riskPrefix", "风险")} {RISK_LABEL[selected.risk] ?? selected.risk}
              </QaBadge>
              <QaBadge tone={STATUS_TONE[selected.status] ?? "neutral"}>
                {STATUS_LABEL[selected.status] ?? selected.status}
              </QaBadge>
            </>
          ) : null
        }
        meta={
          selected
            ? [
                {
                  label: tx("qa.testpoints.group", "分组"),
                  value: groupLabel(selected.group) || tx("qa.testpoints.ungrouped", "未分组"),
                },
                {
                  label: tx("qa.testpoints.method", "方法"),
                  value: METHOD_LABEL[selected.method] ?? selected.method,
                },
                {
                  label: tx("qa.testpoints.owner", "负责人"),
                  value: selected.owner || "—",
                },
                {
                  label: tx("qa.testpoints.tags", "标签"),
                  value: selected.tags.join(", ") || "—",
                },
              ]
            : []
        }
      >
        {selected ? (
          <>
            <QaDetailSection title={tx("qa.testpoints.tracePath", "追溯路径")}>
              <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                <QaBadge tone="blue">
                  {tx("qa.testpoints.sources", "来源")} {selected.sources.length}
                </QaBadge>
                <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />
                <QaBadge tone="violet">{selected.code || selected.id}</QaBadge>
                <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden />
                <QaBadge tone="green">
                  {tx("qa.testpoints.coveredCases", "用例")} {selected.case_count}
                </QaBadge>
                {selected.reviewed_case_count !== selected.case_count ? (
                  <span className="text-[11.5px] text-muted-foreground">
                    {tx("qa.testpoints.reviewedOf", "其中已评审")} {selected.reviewed_case_count}
                  </span>
                ) : null}
              </div>
            </QaDetailSection>

            <QaDetailSection title={tx("qa.testpoints.note", "测试点说明")}>
              {selected.note ? (
                <p className="whitespace-pre-wrap text-[12.5px]">{selected.note}</p>
              ) : (
                <p className="rounded-lg border border-dashed border-border/70 px-2.5 py-2 text-[12px] text-muted-foreground">
                  {tx(
                    "qa.testpoints.noNote",
                    "还没有说明。让 Agent 建测试点时用 note 写清「测什么、怎么判定」，这里才会显示。",
                  )}
                </p>
              )}
            </QaDetailSection>

            <QaDetailSection
              title={tx("qa.testpoints.design", "设计方法")}
              hint={METHOD_LABEL[selected.method] ?? selected.method}
            >
              <p className="text-[12.5px] text-muted-foreground">
                {METHOD_HINT[selected.method] ?? "—"}
              </p>
              <p className="mt-1.5 text-[12.5px]">
                <span className="text-muted-foreground">
                  {tx("qa.testpoints.riskLabel", "风险")}：
                </span>
                {RISK_LABEL[selected.risk] ?? selected.risk}
                <span className="ml-1.5 text-muted-foreground">
                  {RISK_HINT[selected.risk] ?? ""}
                </span>
              </p>
            </QaDetailSection>

            <QaDetailSection
              title={tx("qa.testpoints.sources", "来源")}
              hint={String(selected.sources.length)}
            >
              <ul className="flex flex-col gap-1.5 text-[12px]">
                {selected.sources.map((id) => {
                  const source = sourcesById.get(id);
                  return (
                    <li
                      key={id}
                      className="rounded-lg border border-border/60 bg-card px-2.5 py-1.5"
                      data-testid={`qa-testpoint-source-${id}`}
                    >
                      <div className="flex items-center gap-1.5">
                        <QaBadge tone={SOURCE_TONE[source?.type ?? ""] ?? "neutral"}>
                          {source?.type ?? "source"}
                        </QaBadge>
                        <span className="min-w-0 flex-1 truncate">
                          {source?.title || tx("qa.testpoints.sourceMissing", "（来源不在正式库）")}
                        </span>
                      </div>
                      {source && source.evidence.length > 0 ? (
                        <ul className="mt-1 flex flex-col gap-0.5">
                          {source.evidence.map((evidence) => (
                            <li
                              key={`${evidence.type}:${evidence.locator}`}
                              className="truncate font-mono text-[11px] text-muted-foreground"
                              title={evidence.description || evidence.locator}
                            >
                              {evidence.type} · {evidence.locator}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <p className="mt-1 truncate font-mono text-[10.5px] text-muted-foreground/70" title={id}>
                        {id}
                      </p>
                    </li>
                  );
                })}
              </ul>
            </QaDetailSection>

            <QaDetailSection
              title={tx("qa.testpoints.covered", "覆盖用例")}
              hint={String(selected.cases.length)}
            >
              {selected.cases.length === 0 ? (
                <p className="text-[12px] text-muted-foreground">
                  {tx("qa.testpoints.noCovered", "还没有用例挂到这个测试点")}
                </p>
              ) : (
                <ul className="flex flex-col gap-1 text-[12px]">
                  {selected.cases.map((item) => (
                    <li
                      key={item.case_id}
                      className="flex items-center gap-2"
                      data-testid={`qa-testpoint-case-${item.case_id}`}
                    >
                      <QaBadge tone={STATUS_TONE[item.status] ?? "neutral"}>
                        {STATUS_LABEL[item.status] ?? item.status}
                      </QaBadge>
                      <span className="font-mono text-[11.5px] text-muted-foreground">
                        {item.code || item.case_id}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{item.title}</span>
                    </li>
                  ))}
                </ul>
              )}
            </QaDetailSection>

            <QaDetailSection
              title={tx("qa.testpoints.fullId", "完整编号")}
              hint={tx("qa.testpoints.fullIdHint", "唯一，防冲突；列表里显示短号")}
            >
              <code className="block break-all rounded-lg border border-border/60 bg-muted/30 px-2.5 py-1.5 font-mono text-[11.5px] text-muted-foreground">
                {selected.id}
              </code>
            </QaDetailSection>
          </>
        ) : null}
      </QaDetailDrawer>
    </div>
  );
}
