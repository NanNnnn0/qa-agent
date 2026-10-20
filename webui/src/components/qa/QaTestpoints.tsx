import { useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { loadQaTestpoints, type QaProject } from "@/lib/qa-api";
import { cn } from "@/lib/utils";

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

/**
 * The chain above the cases: sources and the test points derived from them.
 *
 * Read-only on purpose: creating a draft is the agent's job (qa_testpoint) and
 * promoting one is a review decision that stays in the trace tab.
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
  const resolved = projectId === "all" ? (projects[0]?.id ?? "") : projectId;

  const query = useQaQuery(
    () =>
      resolved
        ? loadQaTestpoints(token, resolved)
        : Promise.resolve(null),
    [token, resolved, refreshSignal],
    { enabled: Boolean(resolved), intervalMs: 0 },
  );

  const data = query.data;
  const counts = data?.counts;

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
                      <td className={cn(QA_TD_CLASS, "font-mono text-[12px] text-muted-foreground")}>
                        {source.id}
                      </td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge tone={SOURCE_TONE[source.type] ?? "neutral"}>{source.type}</QaBadge>
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

          <section className="flex flex-col gap-2" data-testid="qa-testpoints-list">
            <h3 className="text-[12.5px] font-medium">
              {tx("qa.testpoints.testpoints", "测试点")}
              <span className="ml-2 font-normal text-muted-foreground">
                {tx(
                  "qa.testpoints.listHint",
                  "用例挂在这里；「覆盖」= 已挂用例数",
                )}
              </span>
            </h3>
            {data && data.testpoints.length > 0 ? (
              <QaTableShell label={tx("qa.testpoints.testpoints", "测试点")}>
                <thead>
                  <tr>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.id", "编号")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.title", "标题")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.sourceIds", "来源")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.method", "方法")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.risk", "风险")}</th>
                    <th className={QA_TH_CLASS}>{tx("qa.testpoints.coverage", "覆盖")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.testpoints.map((testpoint) => (
                    <tr key={testpoint.id} data-testid={`qa-testpoint-${testpoint.id}`}>
                      <td className={cn(QA_TD_CLASS, "font-mono text-[12px] text-muted-foreground")}>
                        {testpoint.id}
                      </td>
                      <td className={cn(QA_TD_CLASS, "max-w-[22rem] truncate")}>
                        {testpoint.title}
                      </td>
                      <td className={cn(QA_TD_CLASS, "font-mono text-[11.5px] text-muted-foreground")}>
                        {testpoint.sources.join(", ")}
                      </td>
                      <td className={cn(QA_TD_CLASS, "text-[12px]")}>{testpoint.method}</td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge tone={RISK_TONE[testpoint.risk] ?? "neutral"}>
                          {testpoint.risk}
                        </QaBadge>
                      </td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge tone={testpoint.case_count > 0 ? "green" : "amber"}>
                          {testpoint.case_count}
                        </QaBadge>
                      </td>
                    </tr>
                  ))}
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
    </div>
  );
}
