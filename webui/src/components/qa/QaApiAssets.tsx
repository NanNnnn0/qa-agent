import { useState } from "react";

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
  type QaApiOperation,
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

/**
 * Read-only view of the API reference catalog: which endpoints the material
 * declares, their evidence and the normalized spec the case generator used.
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

  const items = list.data?.items ?? [];
  const selected = detail.data ?? items.find((item) => item.id === selectedId) ?? null;

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
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr>
                <th className={QA_TH_CLASS}>{tx("qa.assets.method", "方法")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.path", "路径")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.summary", "摘要")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.status", "状态")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.assets.updated", "更新时间")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((operation) => (
                <tr
                  key={operation.id}
                  data-testid={`qa-api-operation-${operation.id}`}
                  onClick={() => setSelectedId(operation.id)}
                  className="cursor-pointer transition-colors hover:bg-accent/40"
                >
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
              ))}
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
    </div>
  );
}
