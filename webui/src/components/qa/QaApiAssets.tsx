import { Fragment, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  loadQaApiOperation,
  loadQaApiOperations,
  loadQaCases,
  type QaApiOperation,
  type QaCase,
  type QaProject,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailSection } from "./QaDetailDrawer";
import {
  QaBadge,
  QaErrorBar,
  QaLoading,
  QaPre,
  QaSectionTitle,
  QA_TD_CLASS,
  QA_TH_CLASS,
  formatQaTime,
  useQaCopy,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

const PATH_PARAMETER = /^\{.+\}$/;
const NUMERIC_SEGMENT = /^\d+$/;
const UUID_SEGMENT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Collapse path parameters so a case's concrete request path finds its
 * operation. The catalog stores `/orders/{}`; a case may carry `/orders/42`.
 */
function normalizePath(path: string): string {
  return path
    .split("/")
    .map((segment) =>
      PATH_PARAMETER.test(segment) || NUMERIC_SEGMENT.test(segment) || UUID_SEGMENT.test(segment)
        ? "{}"
        : segment,
    )
    .join("/")
    .replace(/\/+$/, "");
}

function operationKey(projectId: string, method: string, path: string): string {
  return `${projectId}|${method.toUpperCase()}|${normalizePath(path)}`;
}

function priorityTone(priority: QaCase["priority"]) {
  if (priority === "P0") return "red" as const;
  if (priority === "P1") return "amber" as const;
  return "neutral" as const;
}

function caseStatusTone(status: QaCase["status"]) {
  if (status === "ready") return "green" as const;
  if (status === "deprecated") return "neutral" as const;
  return "amber" as const;
}

/**
 * Read-only view of the API reference catalog: which endpoints the material
 * declares, their evidence, the normalized spec the case generator used, and
 * the cases that hang off each endpoint.
 *
 * The case nesting is a temporary grouping: it matches a case to an operation
 * by project + method + normalized request path, because cases created outside
 * the catalog workflow carry no `operation_id` link. The durable fix is a
 * catalog link on every case (see ADR 0011).
 */
export function QaApiAssets({
  token,
  projects,
  refreshSignal,
}: {
  token: string;
  projects: QaProject[];
  refreshSignal: number;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  const list = useQaQuery(
    () =>
      loadQaApiOperations(token, {
        projectId: projectId === "all" ? undefined : projectId,
        query: query.trim() || undefined,
        limit: 50,
      }),
    [token, projectId, query, refreshSignal],
    { intervalMs: 0 },
  );
  const detail = useQaQuery<QaApiOperation | null>(
    () => (selectedId ? loadQaApiOperation(token, selectedId) : Promise.resolve(null)),
    [token, selectedId],
    { enabled: Boolean(selectedId), intervalMs: 0 },
  );
  const caseList = useQaQuery(
    () =>
      loadQaCases(token, {
        projectId: projectId === "all" ? undefined : projectId,
        limit: 500,
      }),
    [token, projectId, refreshSignal],
    { intervalMs: 0 },
  );

  const items = list.data?.items ?? [];
  const selected = detail.data ?? items.find((item) => item.id === selectedId) ?? null;
  const allCases = caseList.data?.items ?? [];
  const selectedCase = selectedCaseId
    ? (allCases.find((item) => item.id === selectedCaseId) ?? null)
    : null;

  const casesByOperation = useMemo(() => {
    const byKey = new Map<string, string>();
    const grouped = new Map<string, QaCase[]>();
    for (const operation of items) {
      byKey.set(
        operationKey(operation.project_id, operation.method, operation.path_template || operation.path),
        operation.id,
      );
      grouped.set(operation.id, []);
    }
    for (const qaCase of allCases) {
      const request = qaCase.api?.request;
      if (!request?.method || !request.path) continue;
      const operationId = byKey.get(
        operationKey(qaCase.project_id, request.method, request.path),
      );
      if (!operationId) continue;
      grouped.get(operationId)?.push(qaCase);
    }
    return grouped;
  }, [items, allCases]);

  return (
    <div className="flex flex-col gap-3" data-testid="qa-api-assets">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.assets.title", "接口资产")}
          count={list.data?.total ?? items.length}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger
              aria-label={tx("qa.assets.filterProject", "项目筛选")}
              className="h-8 w-[11rem]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{tx("qa.assets.allProjects", "全部项目")}</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={tx("qa.assets.search", "搜索路径 / 摘要")}
            aria-label={tx("qa.assets.search", "搜索路径 / 摘要")}
            className="h-8 w-[14rem]"
          />
        </div>
      </div>

      {list.error ? <QaErrorBar message={list.error} onRetry={list.reload} /> : null}

      {list.loading && items.length === 0 ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <p
          data-testid="qa-api-assets-empty"
          className="rounded-lg border border-dashed border-border/70 px-3 py-6 text-center text-[12.5px] text-muted-foreground"
        >
          {tx(
            "qa.assets.empty",
            "还没有登记接口资料。用 qa_api_catalog action=ingest 导入 OpenAPI 文档后，接口会出现在这里。",
          )}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border/60">
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr>
                <th className={cn(QA_TH_CLASS, "w-8 pr-0")} aria-label={tx("qa.assets.cases", "用例")} />
                <th className={QA_TH_CLASS}>{tx("qa.assets.method", "方法")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.path", "路径")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.summary", "摘要")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.cases", "用例")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.status", "状态")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.updated", "更新时间")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((operation) => {
                const linked = casesByOperation.get(operation.id) ?? [];
                const expanded = expandedId === operation.id;
                return (
                  <Fragment key={operation.id}>
                    <tr
                      data-testid={`qa-api-operation-${operation.id}`}
                      onClick={() => setSelectedId(operation.id)}
                      className="cursor-pointer transition-colors hover:bg-accent/40"
                    >
                      <td className={cn(QA_TD_CLASS, "w-8 pr-0")}>
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-label={tx("qa.assets.toggleCases", "展开这个接口下的用例")}
                          data-testid={`qa-api-operation-toggle-${operation.id}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            setExpandedId(expanded ? null : operation.id);
                          }}
                          className="rounded p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                        >
                          <ChevronRight
                            aria-hidden
                            className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")}
                          />
                        </button>
                      </td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge
                          tone={
                            operation.method === "DELETE"
                              ? "red"
                              : operation.method === "GET"
                                ? "neutral"
                                : "green"
                          }
                        >
                          {operation.method}
                        </QaBadge>
                      </td>
                      <td className={cn(QA_TD_CLASS, "font-mono text-[12px]")}>{operation.path}</td>
                      <td className={cn(QA_TD_CLASS, "max-w-[22rem] truncate")}>
                        {operation.summary || "—"}
                      </td>
                      <td className={QA_TD_CLASS}>
                        <QaBadge
                          tone={linked.length > 0 ? "blue" : "neutral"}
                          title={tx("qa.assets.caseCount", "挂在这个接口下的用例数")}
                        >
                          {linked.length}
                        </QaBadge>
                      </td>
                      <td className={QA_TD_CLASS}>
                        {operation.status === "missing" ? (
                          <QaBadge tone="amber">{tx("qa.assets.missing", "资料已删除")}</QaBadge>
                        ) : (
                          <QaBadge tone="neutral">{tx("qa.assets.active", "有效")}</QaBadge>
                        )}
                      </td>
                      <td
                        className={cn(
                          QA_TD_CLASS,
                          "whitespace-nowrap text-[12px] text-muted-foreground",
                        )}
                      >
                        {formatQaTime(operation.updated_at)}
                      </td>
                    </tr>
                    {expanded ? (
                      <tr data-testid={`qa-api-operation-cases-${operation.id}`}>
                        <td
                          colSpan={7}
                          className="border-b border-border/40 bg-accent/20 px-3 py-2 pl-11"
                        >
                          {linked.length === 0 ? (
                            <p className="text-[12px] text-muted-foreground">
                              {tx(
                                "qa.assets.noCases",
                                "这个接口下还没有用例。用 qa_api_workflow 提交候选批次后，用例会挂在这里。",
                              )}
                            </p>
                          ) : (
                            <ul className="flex flex-col gap-1">
                              {linked.map((qaCase) => (
                                <li key={qaCase.id}>
                                  <button
                                    type="button"
                                    data-testid={`qa-api-case-${qaCase.id}`}
                                    onClick={() => setSelectedCaseId(qaCase.id)}
                                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent/60"
                                  >
                                    <span className="font-mono text-[11.5px] text-muted-foreground">
                                      {qaCase.code}
                                    </span>
                                    <span className="flex-1 truncate text-[12.5px]">
                                      {qaCase.title}
                                    </span>
                                    <QaBadge tone={priorityTone(qaCase.priority)}>
                                      {qaCase.priority}
                                    </QaBadge>
                                    <QaBadge tone={caseStatusTone(qaCase.status)}>
                                      {qaCase.status}
                                    </QaBadge>
                                  </button>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <QaDetailDrawer
        open={Boolean(selectedId)}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        testId="qa-api-operation-drawer"
        title={selected ? `${selected.method} ${selected.path}` : tx("qa.assets.detailTitle", "接口详情")}
        description={selected?.operation_id || selected?.id || ""}
        badge={
          selected ? (
            <QaBadge tone={selected.status === "missing" ? "amber" : "neutral"}>
              {selected.status}
            </QaBadge>
          ) : null
        }
        meta={
          selected
            ? [
                {
                  label: tx("qa.assets.source", "资料来源"),
                  value: selected.source_ref || selected.source_kind || "—",
                  mono: true,
                },
                {
                  label: tx("qa.assets.version", "资料版本"),
                  value: selected.source_version || "—",
                  mono: true,
                },
                {
                  label: tx("qa.assets.template", "路径模板"),
                  value: selected.path_template,
                  mono: true,
                },
                {
                  label: tx("qa.assets.updated", "更新时间"),
                  value: formatQaTime(selected.updated_at),
                },
              ]
            : []
        }
      >
        {detail.error ? <QaErrorBar message={detail.error} onRetry={detail.reload} /> : null}
        {!selected ? (
          <QaLoading label={tx("qa.status.loading", "加载中…")} />
        ) : (
          <>
            <QaDetailSection
              title={tx("qa.assets.cases", "用例")}
              hint={String((casesByOperation.get(selected.id) ?? []).length)}
            >
              {(casesByOperation.get(selected.id) ?? []).length === 0 ? (
                <p className="text-[12px] text-muted-foreground">
                  {tx("qa.assets.noCases", "这个接口下还没有用例。用 qa_api_workflow 提交候选批次后，用例会挂在这里。")}
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {(casesByOperation.get(selected.id) ?? []).map((qaCase) => (
                    <li key={qaCase.id} className="flex items-center gap-2 text-[12px]">
                      <span className="font-mono text-[11.5px] text-muted-foreground">
                        {qaCase.code}
                      </span>
                      <span className="flex-1 truncate">{qaCase.title}</span>
                      <QaBadge tone={priorityTone(qaCase.priority)}>{qaCase.priority}</QaBadge>
                      <QaBadge tone={caseStatusTone(qaCase.status)}>{qaCase.status}</QaBadge>
                    </li>
                  ))}
                </ul>
              )}
            </QaDetailSection>
            <QaDetailSection
              title={tx("qa.assets.evidence", "证据")}
              hint={String(selected.evidence?.length ?? 0)}
            >
              {selected.evidence && selected.evidence.length > 0 ? (
                <ul className="flex flex-col gap-1 text-[12px]">
                  {selected.evidence.map((item, index) => (
                    <li
                      key={`${item.ref}-${index}`}
                      className="rounded-lg border border-border/60 bg-card px-2.5 py-1.5"
                    >
                      <span className="font-mono text-[11.5px] text-muted-foreground">
                        {item.kind}
                      </span>
                      <span className="ml-2 break-all font-mono text-[11.5px]">{item.ref}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[12px] text-muted-foreground">
                  {tx("qa.assets.noEvidence", "没有登记证据")}
                </p>
              )}
            </QaDetailSection>
            <QaDetailSection title={tx("qa.assets.spec", "接口定义")} hint="JSON">
              <QaPre className="max-h-80">{JSON.stringify(selected.spec ?? {}, null, 2)}</QaPre>
            </QaDetailSection>
          </>
        )}
      </QaDetailDrawer>

      <QaDetailDrawer
        open={Boolean(selectedCaseId)}
        onOpenChange={(open) => {
          if (!open) setSelectedCaseId(null);
        }}
        testId="qa-api-case-drawer"
        title={
          selectedCase
            ? `${selectedCase.code} · ${selectedCase.title}`
            : tx("qa.assets.caseDetailTitle", "用例详情")
        }
        description={selectedCase?.code || ""}
        badge={
          selectedCase ? (
            <QaBadge tone={caseStatusTone(selectedCase.status)}>{selectedCase.status}</QaBadge>
          ) : null
        }
        meta={
          selectedCase
            ? [
                { label: tx("qa.assets.caseKind", "类型"), value: selectedCase.kind },
                {
                  label: tx("qa.assets.casePriority", "优先级"),
                  value: selectedCase.priority,
                },
                {
                  label: tx("qa.assets.caseTags", "标签"),
                  value: selectedCase.tags.join(", ") || "—",
                  mono: true,
                },
                {
                  label: tx("qa.assets.updated", "更新时间"),
                  value: formatQaTime(selectedCase.updated_at),
                },
              ]
            : []
        }
      >
        {!selectedCase ? (
          <QaLoading label={tx("qa.status.loading", "加载中…")} />
        ) : (
          <>
            <QaDetailSection title={tx("qa.assets.caseRequest", "请求")} hint="JSON">
              <QaPre className="max-h-64">
                {JSON.stringify(selectedCase.api?.request ?? {}, null, 2)}
              </QaPre>
            </QaDetailSection>
            <QaDetailSection
              title={tx("qa.assets.caseAssertions", "断言")}
              hint={String(selectedCase.api?.assertions?.length ?? 0)}
            >
              <QaPre className="max-h-64">
                {JSON.stringify(selectedCase.api?.assertions ?? [], null, 2)}
              </QaPre>
            </QaDetailSection>
            <QaDetailSection title={tx("qa.assets.caseExpected", "预期结果")}>
              <p className="whitespace-pre-wrap text-[12.5px]">
                {selectedCase.expected || "—"}
              </p>
            </QaDetailSection>
          </>
        )}
      </QaDetailDrawer>
    </div>
  );
}
