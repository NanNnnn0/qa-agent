import { useEffect, useMemo, useState } from "react";
import { Download, Plus, Upload } from "lucide-react";

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
  createQaCase,
  importQaCases,
  loadQaCase,
  loadQaCaseExport,
  loadQaCaseRevisions,
  loadQaCases,
  qaErrorMessage,
  updateQaCase,
  type QaCase,
  type QaCaseApi,
  type QaCaseKind,
  type QaCasePriority,
  type QaCaseStatus,
  type QaCaseStep,
  type QaMutationTransport,
  type QaProject,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailField, QaDetailSection } from "./QaDetailDrawer";
import {
  formatQaTime,
  QaBadge,
  QaCaseStatusBadge,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPanel,
  QaPriorityBadge,
  QaSectionTitle,
  QaTableShell,
  QaTagChips,
  QaTruncate,
  QA_TD_CLASS,
  QA_TH_CLASS,
  qaKindLabel,
  useQaCopy,
} from "./qa-ui";
import { useQaDebouncedValue, useQaQuery } from "./useQaQuery";

const CASE_KINDS: QaCaseKind[] = ["api", "ui", "manual"];
const CASE_PRIORITIES: QaCasePriority[] = ["P0", "P1", "P2", "P3"];
const CASE_STATUSES: QaCaseStatus[] = ["draft", "ready", "deprecated"];

export interface QaCaseLibraryProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  refreshSignal: number;
  onChanged: () => void;
}

export function QaCaseLibrary({
  token,
  client,
  projects,
  refreshSignal,
  onChanged,
}: QaCaseLibraryProps) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [search, setSearch] = useState("");
  const debouncedSearch = useQaDebouncedValue(search, 250);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);

  const cases = useQaQuery(
    () =>
      loadQaCases(token, {
        projectId: projectId === "all" ? undefined : projectId,
        kind: kind === "all" ? undefined : kind,
        status: status === "all" ? undefined : status,
        query: debouncedSearch.trim() || undefined,
        limit: 200,
      }),
    [token, projectId, kind, status, debouncedSearch, refreshSignal],
    { intervalMs: 0 },
  );

  const items = cases.data?.items ?? [];
  const selectedCase = items.find((item) => item.id === selectedId) ?? null;
  const defaultProjectId = useMemo(() => {
    if (projectId !== "all") return projectId;
    return projects[0]?.id ?? "";
  }, [projectId, projects]);

  const exportCases = async () => {
    if (exporting) return;
    setExporting(true);
    setExportError("");
    try {
      const payload = await loadQaCaseExport(
        token,
        projectId === "all" ? undefined : projectId,
      );
      const projectKey = payload.project?.key || "all";
      downloadJson(`qa-cases-${projectKey.toLowerCase()}-${Date.now()}.json`, payload);
    } catch (reason) {
      setExportError(qaErrorMessage(reason));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="qa-cases">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.cases.title", "用例库")}
          count={cases.data?.total ?? items.length}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => setImportOpen(true)}
            data-testid="qa-case-import"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.cases.importAction", "导入")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => void exportCases()}
            disabled={exporting}
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.cases.exportAction", "导出")}
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 gap-1.5 px-2.5"
            onClick={() => setCreateOpen(true)}
            data-testid="qa-case-create"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.cases.create", "新建用例")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={projectId} onValueChange={setProjectId}>
          <SelectTrigger
            aria-label={tx("qa.cases.filterProject", "项目筛选")}
            className="h-8 w-[11rem]"
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
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger aria-label={tx("qa.cases.filterKind", "类型筛选")} className="h-8 w-[7.5rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{tx("qa.filters.allKinds", "全部类型")}</SelectItem>
            {CASE_KINDS.map((value) => (
              <SelectItem key={value} value={value}>
                {qaKindLabel(value, tx)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger
            aria-label={tx("qa.cases.filterStatus", "状态筛选")}
            className="h-8 w-[7.5rem]"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{tx("qa.filters.allStatus", "全部状态")}</SelectItem>
            {CASE_STATUSES.map((value) => (
              <SelectItem key={value} value={value}>
                {value === "draft"
                  ? tx("qa.caseStatus.draft", "草稿")
                  : value === "ready"
                    ? tx("qa.caseStatus.ready", "就绪")
                    : tx("qa.caseStatus.deprecated", "已废弃")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={tx("qa.cases.searchPlaceholder", "搜索编号、标题、标签…")}
          aria-label={tx("qa.cases.searchPlaceholder", "搜索编号、标题、标签…")}
          className="h-8 w-[15rem] rounded-control text-[13px]"
          data-testid="qa-case-search"
        />
      </div>

      {cases.error ? (
        <QaErrorBar
          message={`${tx("qa.error.cases", "加载用例失败")}: ${cases.error}`}
          onRetry={cases.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}
      {exportError ? <QaErrorBar message={exportError} /> : null}

      {cases.loading && !cases.data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <QaEmptyState
          title={tx("qa.cases.empty", "没有匹配的用例")}
          hint={tx(
            "qa.cases.emptyHint",
            "调整筛选条件，或新建第一条用例；也可以从 QA Agent 导出的 JSON 批量导入。",
          )}
          action={
            <>
              <Button type="button" size="sm" variant="outline" onClick={() => setImportOpen(true)}>
                {tx("qa.cases.importAction", "导入")}
              </Button>
              <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
                {tx("qa.cases.create", "新建用例")}
              </Button>
            </>
          }
        />
      ) : (
        <QaTableShell label={tx("qa.cases.title", "用例库")}>
          <thead>
            <tr>
              <th className={QA_TH_CLASS}>{tx("qa.cases.code", "编号")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.cases.name", "标题")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.cases.kind", "类型")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.cases.priority", "优先级")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.cases.status", "状态")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.cases.tags", "标签")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="cursor-pointer hover:bg-muted/30"
                onClick={() => setSelectedId(item.id)}
              >
                <td className={cn(QA_TD_CLASS, "font-mono text-[12px] text-muted-foreground")}>
                  <QaTruncate text={item.code} className="max-w-[9rem]" />
                </td>
                <td className={QA_TD_CLASS}>
                  <button
                    type="button"
                    className="block max-w-[26rem] truncate text-left font-medium text-foreground hover:underline"
                    title={item.title}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(item.id);
                    }}
                  >
                    {item.title || item.code}
                  </button>
                </td>
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  {qaKindLabel(item.kind, tx)}
                </td>
                <td className={QA_TD_CLASS}>
                  <QaPriorityBadge priority={item.priority} />
                </td>
                <td className={QA_TD_CLASS}>
                  <QaCaseStatusBadge status={item.status} />
                </td>
                <td className={QA_TD_CLASS}>
                  <QaTagChips tags={item.tags} />
                </td>
              </tr>
            ))}
          </tbody>
        </QaTableShell>
      )}

      <QaCaseDrawer
        token={token}
        client={client}
        caseId={selectedId}
        listCase={selectedCase}
        open={selectedId !== null}
        onOpenChange={(open) => { if (!open) setSelectedId(null); }}
        onSaved={() => {
          cases.reload();
          onChanged();
        }}
      />

      <QaCaseCreateDialog
        client={client}
        open={createOpen}
        onOpenChange={setCreateOpen}
        projects={projects}
        defaultProjectId={defaultProjectId}
        onCreated={() => {
          cases.reload();
          onChanged();
        }}
      />

      <QaCaseImportDialog
        client={client}
        open={importOpen}
        onOpenChange={setImportOpen}
        projects={projects}
        defaultProjectId={defaultProjectId}
        onImported={() => {
          cases.reload();
          onChanged();
        }}
      />
    </div>
  );
}

function downloadJson(filename: string, data: unknown): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function stepsToText(steps: QaCaseStep[]): string {
  return steps.map((step) => `${step.action} | ${step.expected}`).join("\n");
}

function textToSteps(value: string): QaCaseStep[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const index = line.indexOf("|");
      if (index === -1) return { action: line, expected: "" };
      return {
        action: line.slice(0, index).trim(),
        expected: line.slice(index + 1).trim(),
      };
    });
}

/** Editable case detail: quick triage fields plus the raw API definition. */
function QaCaseDrawer({
  token,
  client,
  caseId,
  listCase,
  open,
  onOpenChange,
  onSaved,
}: {
  token: string;
  client: QaMutationTransport;
  caseId: string | null;
  listCase: QaCase | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const tx = useQaCopy();
  const detail = useQaQuery<QaCase | null>(
    () => (caseId ? loadQaCase(token, caseId) : Promise.resolve(null)),
    [token, caseId],
    { enabled: open && Boolean(caseId), intervalMs: 0 },
  );
  const current = detail.data ?? listCase;

  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<QaCaseKind>("api");
  const [priority, setPriority] = useState<QaCasePriority>("P1");
  const [status, setStatus] = useState<QaCaseStatus>("draft");
  const [preconditions, setPreconditions] = useState("");
  const [expected, setExpected] = useState("");
  const [stepsText, setStepsText] = useState("");
  const [apiText, setApiText] = useState("{}");
  const [tagsText, setTagsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [savedAt, setSavedAt] = useState("");
  const revisions = useQaQuery(
    () => (caseId ? loadQaCaseRevisions(token, caseId, { limit: 20 }) : Promise.resolve(null)),
    [token, caseId, savedAt],
    { enabled: open && Boolean(caseId), intervalMs: 0 },
  );

  const loadedId = current?.id ?? "";
  useEffect(() => {
    if (!current) return;
    setTitle(current.title);
    setKind(current.kind);
    setPriority(current.priority);
    setStatus(current.status);
    setPreconditions(current.preconditions);
    setExpected(current.expected);
    setStepsText(stepsToText(current.steps));
    setApiText(JSON.stringify(current.api ?? {}, null, 2));
    setTagsText(current.tags.join(", "));
    setError("");
    setSavedAt("");
    // Reset the form only when a different case is opened.
  }, [loadedId]);

  const save = async () => {
    if (!current || busy) return;
    let parsedApi: QaCaseApi;
    try {
      const raw: unknown = apiText.trim() ? JSON.parse(apiText) : {};
      parsedApi = raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as QaCaseApi) : {};
    } catch {
      setError(tx("qa.cases.apiInvalid", "api 不是合法 JSON，请修正后再保存。"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await updateQaCase(client, current.id, {
        title: title.trim(),
        kind,
        priority,
        status,
        preconditions,
        expected,
        steps: textToSteps(stepsText),
        api: parsedApi,
        tags: tagsText.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      setSavedAt(tx("qa.cases.saved", "已保存"));
      detail.reload();
      onSaved();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <QaDetailDrawer
      open={open}
      onOpenChange={onOpenChange}
      testId="qa-case-drawer"
      title={current?.title || tx("qa.cases.detailTitle", "用例详情")}
      description={current?.code ?? ""}
      badge={
        current ? (
          <>
            <QaCaseStatusBadge status={current.status} />
            <QaPriorityBadge priority={current.priority} />
            <span className="text-[11px] text-muted-foreground">
              {qaKindLabel(current.kind, tx)}
            </span>
          </>
        ) : null
      }
      meta={
        current
          ? [
              { label: tx("qa.cases.code", "编号"), value: current.code, mono: true },
              { label: tx("qa.cases.source", "来源"), value: current.source || "—" },
              { label: tx("qa.cases.author", "作者"), value: current.author || "—" },
              { label: tx("qa.cases.updatedAt", "更新时间"), value: formatQaTime(current.updated_at) },
            ]
          : []
      }
      footer={
        current ? (
          <>
            {savedAt ? (
              <span className="mr-auto text-[12px] text-emerald-700 dark:text-emerald-300">
                {savedAt}
              </span>
            ) : null}
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {tx("qa.actions.close", "关闭")}
            </Button>
            <Button
              type="button"
              disabled={busy}
              data-testid="qa-case-save"
              onClick={() => void save()}
            >
              {tx("qa.actions.save", "保存")}
            </Button>
          </>
        ) : null
      }
    >
      {detail.error ? <QaErrorBar message={detail.error} onRetry={detail.reload} /> : null}
      {error ? <QaErrorBar message={error} /> : null}
      {!current ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : (
        <>
          <QaDetailSection title={tx("qa.cases.editFields", "基础信息")}>
            <div className="grid gap-3">
              <QaDetailField label={tx("qa.cases.fieldTitle", "标题")}>
                <Input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  aria-label={tx("qa.cases.fieldTitle", "标题")}
                  data-testid="qa-case-title-input"
                  disabled={busy}
                />
              </QaDetailField>
              <div className="grid grid-cols-3 gap-2">
                <QaDetailField label={tx("qa.cases.fieldKind", "类型")}>
                  <Select value={kind} onValueChange={(value) => setKind(value as QaCaseKind)}>
                    <SelectTrigger aria-label={tx("qa.cases.fieldKind", "类型")} className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CASE_KINDS.map((value) => (
                        <SelectItem key={value} value={value}>
                          {qaKindLabel(value, tx)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </QaDetailField>
                <QaDetailField label={tx("qa.cases.fieldPriority", "优先级")}>
                  <Select
                    value={priority}
                    onValueChange={(value) => setPriority(value as QaCasePriority)}
                  >
                    <SelectTrigger aria-label={tx("qa.cases.fieldPriority", "优先级")} className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CASE_PRIORITIES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </QaDetailField>
                <QaDetailField label={tx("qa.cases.fieldStatus", "状态")}>
                  <Select value={status} onValueChange={(value) => setStatus(value as QaCaseStatus)}>
                    <SelectTrigger aria-label={tx("qa.cases.fieldStatus", "状态")} className="h-9">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CASE_STATUSES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value === "draft"
                            ? tx("qa.caseStatus.draft", "草稿")
                            : value === "ready"
                              ? tx("qa.caseStatus.ready", "就绪")
                              : tx("qa.caseStatus.deprecated", "已废弃")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </QaDetailField>
              </div>
              <QaDetailField label={tx("qa.cases.fieldTags", "标签（逗号分隔）")}>
                <Input
                  value={tagsText}
                  onChange={(event) => setTagsText(event.target.value)}
                  aria-label={tx("qa.cases.fieldTags", "标签（逗号分隔）")}
                  disabled={busy}
                />
              </QaDetailField>
              <QaDetailField label={tx("qa.cases.fieldPreconditions", "前置条件")}>
                <Textarea
                  value={preconditions}
                  onChange={(event) => setPreconditions(event.target.value)}
                  aria-label={tx("qa.cases.fieldPreconditions", "前置条件")}
                  rows={2}
                  disabled={busy}
                />
              </QaDetailField>
              <QaDetailField label={tx("qa.cases.fieldExpected", "预期结果")}>
                <Textarea
                  value={expected}
                  onChange={(event) => setExpected(event.target.value)}
                  aria-label={tx("qa.cases.fieldExpected", "预期结果")}
                  rows={2}
                  disabled={busy}
                />
              </QaDetailField>
            </div>
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.cases.steps", "步骤")}
            hint={tx("qa.cases.stepsHint", "每行 “动作 | 预期”")}
          >
            <Textarea
              value={stepsText}
              onChange={(event) => setStepsText(event.target.value)}
              aria-label={tx("qa.cases.steps", "步骤")}
              rows={Math.max(3, Math.min(10, stepsText.split("\n").length + 1))}
              className="font-mono text-[12px] leading-5"
              disabled={busy}
            />
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.cases.revisions", "修订历史")}
            hint={String(revisions.data?.total ?? 0)}
          >
            {revisions.error ? (
              <QaErrorBar message={revisions.error} onRetry={revisions.reload} />
            ) : null}
            {(revisions.data?.items.length ?? 0) === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.cases.noRevisions", "还没有修订记录")}
              </p>
            ) : (
              <ul
                className="flex flex-col gap-1 text-[12px]"
                data-testid="qa-case-revisions"
              >
                {revisions.data?.items.map((item) => (
                  <li
                    key={item.id}
                    className="rounded-lg border border-border/60 bg-card px-2.5 py-1.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11.5px]">r{item.revision}</span>
                      <QaBadge tone="neutral">{item.change_source}</QaBadge>
                      <span className="text-muted-foreground">
                        {formatQaTime(item.created_at)}
                      </span>
                      <span className="ml-auto truncate font-mono text-[10.5px] text-muted-foreground/70">
                        {item.content_hash.slice(0, 12)}
                      </span>
                    </div>
                    {item.changed_by ? (
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {item.changed_by}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </QaDetailSection>

          <QaDetailSection title={tx("qa.cases.api", "API 定义")} hint="JSON">
            <Textarea
              value={apiText}
              onChange={(event) => setApiText(event.target.value)}
              aria-label={tx("qa.cases.api", "API 定义")}
              rows={10}
              className="font-mono text-[12px] leading-5"
              spellCheck={false}
              disabled={busy}
              data-testid="qa-case-api-input"
            />
          </QaDetailSection>
        </>
      )}
    </QaDetailDrawer>
  );
}

function QaCaseCreateDialog({
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
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<QaCaseKind>("api");
  const [priority, setPriority] = useState<QaCasePriority>("P1");
  const [status, setStatus] = useState<QaCaseStatus>("draft");
  const [expected, setExpected] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) setProjectId(defaultProjectId);
  }, [open, defaultProjectId]);

  const reset = () => {
    setTitle("");
    setKind("api");
    setPriority("P1");
    setStatus("draft");
    setExpected("");
    setTags("");
    setError("");
  };

  const submit = async () => {
    if (busy) return;
    if (!projectId) {
      setError(tx("qa.cases.projectRequired", "请选择项目"));
      return;
    }
    if (!title.trim()) {
      setError(tx("qa.cases.titleRequired", "请填写标题"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createQaCase(client, {
        project_id: projectId,
        title: title.trim(),
        kind,
        priority,
        status,
        expected: expected.trim(),
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      onOpenChange(false);
      reset();
      onCreated();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{tx("qa.cases.create", "新建用例")}</DialogTitle>
          <DialogDescription>
            {tx("qa.cases.createHint", "用例编号由后端按项目与类型自动生成。")}
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
          <QaDetailField label={tx("qa.cases.fieldTitle", "标题")}>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              aria-label={tx("qa.cases.fieldTitle", "标题")}
              data-testid="qa-new-case-title"
              disabled={busy}
            />
          </QaDetailField>
          <div className="grid grid-cols-3 gap-2">
            <QaDetailField label={tx("qa.cases.fieldKind", "类型")}>
              <Select value={kind} onValueChange={(value) => setKind(value as QaCaseKind)}>
                <SelectTrigger aria-label={tx("qa.cases.fieldKind", "类型")} className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CASE_KINDS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {qaKindLabel(value, tx)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </QaDetailField>
            <QaDetailField label={tx("qa.cases.fieldPriority", "优先级")}>
              <Select value={priority} onValueChange={(value) => setPriority(value as QaCasePriority)}>
                <SelectTrigger aria-label={tx("qa.cases.fieldPriority", "优先级")} className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CASE_PRIORITIES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </QaDetailField>
            <QaDetailField label={tx("qa.cases.fieldStatus", "状态")}>
              <Select value={status} onValueChange={(value) => setStatus(value as QaCaseStatus)}>
                <SelectTrigger aria-label={tx("qa.cases.fieldStatus", "状态")} className="h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CASE_STATUSES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value === "draft"
                        ? tx("qa.caseStatus.draft", "草稿")
                        : value === "ready"
                          ? tx("qa.caseStatus.ready", "就绪")
                          : tx("qa.caseStatus.deprecated", "已废弃")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </QaDetailField>
          </div>
          <QaDetailField label={tx("qa.cases.fieldExpected", "预期结果")}>
            <Textarea
              value={expected}
              onChange={(event) => setExpected(event.target.value)}
              aria-label={tx("qa.cases.fieldExpected", "预期结果")}
              rows={2}
              disabled={busy}
            />
          </QaDetailField>
          <QaDetailField label={tx("qa.cases.fieldTags", "标签（逗号分隔）")}>
            <Input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              aria-label={tx("qa.cases.fieldTags", "标签（逗号分隔）")}
              data-testid="qa-new-case-tags"
              disabled={busy}
            />
          </QaDetailField>
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

function QaCaseImportDialog({
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
  onImported: () => void;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState(defaultProjectId);
  const [payload, setPayload] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState("");

  useEffect(() => {
    if (open) setProjectId(defaultProjectId);
  }, [open, defaultProjectId]);

  const submit = async () => {
    if (busy) return;
    if (!projectId) {
      setError(tx("qa.cases.projectRequired", "请选择项目"));
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(payload);
    } catch {
      setError(tx("qa.cases.importInvalid", "导入内容不是合法 JSON。"));
      return;
    }
    const list = Array.isArray(parsed)
      ? parsed
      : parsed && typeof parsed === "object" && Array.isArray((parsed as { cases?: unknown }).cases)
        ? ((parsed as { cases: unknown[] }).cases)
        : null;
    if (!list) {
      setError(tx("qa.cases.importShape", "需要 JSON 数组或 {\"cases\": [...]} 结构。"));
      return;
    }
    setBusy(true);
    setError("");
    setSummary("");
    try {
      const result = await importQaCases(client, projectId, list);
      setSummary(
        tx("qa.cases.importDone", "已导入 {{created}} 条，跳过 {{skipped}} 条，失败 {{errors}} 条。", {
          created: result.created,
          skipped: result.skipped.length,
          errors: result.errors.length,
        }),
      );
      onImported();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{tx("qa.cases.importTitle", "导入用例")}</DialogTitle>
          <DialogDescription>
            {tx(
              "qa.cases.importHint",
              "粘贴 QA Agent 导出的 JSON（数组或 {\"cases\": [...]}），编号重复的用例会被跳过。",
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
          <Textarea
            value={payload}
            onChange={(event) => setPayload(event.target.value)}
            aria-label={tx("qa.cases.importPayload", "用例 JSON")}
            rows={12}
            className="font-mono text-[12px] leading-5"
            spellCheck={false}
            placeholder={'{\n  "cases": []\n}'}
            disabled={busy}
            data-testid="qa-case-import-payload"
          />
          {error ? <QaErrorBar message={error} /> : null}
          {summary ? (
            <QaPanel className="px-3 py-2 text-[12.5px] text-foreground">{summary}</QaPanel>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            {tx("qa.actions.close", "关闭")}
          </Button>
          <Button type="button" onClick={() => void submit()} disabled={busy || !payload.trim()}>
            {tx("qa.cases.importSubmit", "开始导入")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
