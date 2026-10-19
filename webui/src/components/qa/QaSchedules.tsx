import { useEffect, useMemo, useState } from "react";
import { Loader2, Pause, Pencil, Play, Plus, Trash2 } from "lucide-react";

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
import { usePageVisibility } from "@/hooks/usePageVisibility";
import {
  createQaSchedule,
  deleteQaSchedule,
  loadQaCases,
  loadQaScripts,
  loadQaSchedules,
  qaErrorMessage,
  runQaSchedule,
  updateQaSchedule,
  type QaMutationTransport,
  type QaProject,
  type QaRun,
  type QaRunStatus,
  type QaSchedule,
  type QaScheduleTarget,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import {
  formatQaTime,
  QaBadge,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaRunStatusBadge,
  QaSectionTitle,
  QaTableShell,
  QaTruncate,
  QA_TD_CLASS,
  QA_TH_CLASS,
  useQaCopy,
} from "./qa-ui";
import { QaRunResult } from "./QaScripts";
import { useQaQuery } from "./useQaQuery";

const RUN_STATUSES: QaRunStatus[] = [
  "running",
  "passed",
  "failed",
  "error",
  "blocked_by_env",
  "cancelled",
];

function isRunStatus(value: string): value is QaRunStatus {
  return (RUN_STATUSES as string[]).includes(value);
}

export interface QaSchedulesProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  refreshSignal: number;
  pollIntervalMs: number;
  onChanged: () => void;
  initialProjectId?: string;
}

export function QaSchedules({
  token,
  client,
  projects,
  refreshSignal,
  pollIntervalMs,
  onChanged,
  initialProjectId = "all",
}: QaSchedulesProps) {
  const tx = useQaCopy();
  const visible = usePageVisibility();
  const [projectId, setProjectId] = useState(initialProjectId);
  useEffect(() => {
    setProjectId(initialProjectId);
  }, [initialProjectId]);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<QaSchedule | null>(null);
  const [deleting, setDeleting] = useState<QaSchedule | null>(null);
  const [busyId, setBusyId] = useState("");
  const [run, setRun] = useState<QaRun | null>(null);
  const [error, setError] = useState("");

  const schedules = useQaQuery(
    () => loadQaSchedules(token, { projectId: projectId === "all" ? undefined : projectId }),
    [token, projectId, refreshSignal],
    { intervalMs: visible ? pollIntervalMs : 0 },
  );
  const scripts = useQaQuery(
    () => loadQaScripts(token, { limit: 200 }),
    [token, refreshSignal],
    { intervalMs: 0 },
  );

  const items = schedules.data ?? [];
  const scriptNames = useMemo(
    () => new Map((scripts.data?.items ?? []).map((script) => [script.id, script.name || script.id])),
    [scripts.data],
  );

  const projectLabel = (id: string) => projects.find((project) => project.id === id)?.key || id;

  const targetLabel = (target: QaScheduleTarget) =>
    target.kind === "script"
      ? scriptNames.get(target.script_id) ?? target.script_id
      : tx("qa.schedules.caseCount", "{{count}} 个用例", { count: target.case_ids.length });

  const runNow = async (schedule: QaSchedule) => {
    if (busyId) return;
    setBusyId(schedule.id);
    setError("");
    setRun(null);
    try {
      const result = await runQaSchedule(client, schedule.id);
      setRun(result);
      schedules.reload();
      onChanged();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusyId("");
    }
  };

  const toggle = async (schedule: QaSchedule) => {
    if (busyId) return;
    setBusyId(schedule.id);
    setError("");
    try {
      await updateQaSchedule(client, schedule.id, { enabled: !schedule.enabled });
      schedules.reload();
      onChanged();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusyId("");
    }
  };

  const confirmDelete = async () => {
    if (!deleting || busyId) return;
    setBusyId(deleting.id);
    setError("");
    try {
      await deleteQaSchedule(client, deleting.id);
      setDeleting(null);
      schedules.reload();
      onChanged();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="qa-schedules">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle title={tx("qa.schedules.title", "定时任务")} count={items.length} />
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
            data-testid="qa-schedule-create"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.schedules.create", "新建定时任务")}
          </Button>
        </div>
      </div>

      {error ? <QaErrorBar message={error} /> : null}
      {run ? <QaRunResult run={run} /> : null}

      {schedules.error ? (
        <QaErrorBar
          message={`${tx("qa.error.schedules", "加载定时任务失败")}: ${schedules.error}`}
          onRetry={schedules.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}

      {schedules.loading && !schedules.data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <QaEmptyState
          title={tx("qa.schedules.empty", "还没有定时任务")}
          hint={tx(
            "qa.schedules.emptyHint",
            "定时任务由网关进程执行，浏览器关闭后仍会按 cron 运行；每次触发都会生成一条运行记录。",
          )}
          action={
            <>
              <Button type="button" size="sm" variant="outline" onClick={schedules.reload}>
                {tx("qa.actions.refresh", "刷新")}
              </Button>
              <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
                {tx("qa.schedules.create", "新建定时任务")}
              </Button>
            </>
          }
        />
      ) : (
        <QaTableShell label={tx("qa.schedules.title", "定时任务")}>
          <thead>
            <tr>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.name", "名称")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.project", "项目")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.cron", "计划")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.target", "目标")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.status", "状态")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.schedules.nextRun", "下次运行")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>
                {tx("qa.overview.projectActions", "操作")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((schedule) => (
              <tr
                key={schedule.id}
                data-testid={`qa-schedule-row-${schedule.id}`}
                className="hover:bg-muted/30"
              >
                <td className={QA_TD_CLASS}>
                  <span
                    className="block max-w-[16rem] truncate font-medium text-foreground"
                    title={schedule.name}
                  >
                    {schedule.name}
                  </span>
                  {schedule.last_error ? (
                    <span
                      className="mt-0.5 block max-w-[16rem] truncate text-[11px] text-destructive"
                      title={schedule.last_error}
                    >
                      {schedule.last_error}
                    </span>
                  ) : null}
                </td>
                <td className={cn(QA_TD_CLASS, "font-mono text-[12px] uppercase text-muted-foreground")}>
                  {projectLabel(schedule.project_id)}
                </td>
                <td className={cn(QA_TD_CLASS, "font-mono text-[11.5px]")}>
                  <QaTruncate text={schedule.cron} className="max-w-[12rem]" />
                  {schedule.timezone ? (
                    <span className="block text-[10.5px] text-muted-foreground">
                      {schedule.timezone}
                    </span>
                  ) : null}
                </td>
                <td className={QA_TD_CLASS}>
                  <QaTruncate text={targetLabel(schedule.target)} className="max-w-[16rem]" />
                </td>
                <td className={QA_TD_CLASS}>
                  <span className="flex flex-wrap items-center gap-1">
                    <QaBadge tone={schedule.enabled ? "green" : "neutral"} dot>
                      {schedule.enabled
                        ? tx("qa.schedules.enabled", "启用")
                        : tx("qa.schedules.paused", "暂停")}
                    </QaBadge>
                    {schedule.last_status ? (
                      isRunStatus(schedule.last_status) ? (
                        <QaRunStatusBadge status={schedule.last_status} />
                      ) : (
                        <QaBadge tone="neutral">{schedule.last_status}</QaBadge>
                      )
                    ) : null}
                  </span>
                </td>
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  {schedule.next_run_at ? formatQaTime(schedule.next_run_at) : "—"}
                </td>
                <td className={cn(QA_TD_CLASS, "text-right")}>
                  <div className="flex items-center justify-end gap-0.5">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      aria-label={tx("qa.schedules.runNow", "立即运行")}
                      title={tx("qa.schedules.runNow", "立即运行")}
                      data-testid={`qa-schedule-run-${schedule.id}`}
                      disabled={busyId === schedule.id}
                      onClick={() => void runNow(schedule)}
                    >
                      {busyId === schedule.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                      ) : (
                        <Play className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      aria-label={
                        schedule.enabled
                          ? tx("qa.schedules.pause", "暂停")
                          : tx("qa.schedules.resume", "启用")
                      }
                      title={
                        schedule.enabled
                          ? tx("qa.schedules.pause", "暂停")
                          : tx("qa.schedules.resume", "启用")
                      }
                      data-testid={`qa-schedule-toggle-${schedule.id}`}
                      disabled={busyId === schedule.id}
                      onClick={() => void toggle(schedule)}
                    >
                      {schedule.enabled ? (
                        <Pause className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <Play className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      aria-label={tx("qa.schedules.edit", "编辑")}
                      title={tx("qa.schedules.edit", "编辑")}
                      data-testid={`qa-schedule-edit-${schedule.id}`}
                      onClick={() => setEditing(schedule)}
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      aria-label={tx("qa.schedules.delete", "删除")}
                      title={tx("qa.schedules.delete", "删除")}
                      data-testid={`qa-schedule-delete-${schedule.id}`}
                      onClick={() => setDeleting(schedule)}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </QaTableShell>
      )}

      <QaScheduleDialog
        token={token}
        client={client}
        open={createOpen}
        onOpenChange={setCreateOpen}
        projects={projects}
        scripts={scripts.data?.items ?? []}
        schedule={null}
        onSaved={() => {
          schedules.reload();
          onChanged();
        }}
      />

      <QaScheduleDialog
        token={token}
        client={client}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        projects={projects}
        scripts={scripts.data?.items ?? []}
        schedule={editing}
        onSaved={() => {
          setEditing(null);
          schedules.reload();
          onChanged();
        }}
      />

      <Dialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
      >
        <DialogContent className="max-w-sm" data-testid="qa-schedule-delete-dialog">
          <DialogHeader>
            <DialogTitle>{tx("qa.schedules.delete", "删除")}</DialogTitle>
            <DialogDescription>
              {tx(
                "qa.schedules.deleteHint",
                "删除后不再触发新的运行，已产生的运行记录会保留。",
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDeleting(null)}>
              {tx("qa.actions.cancel", "取消")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="qa-schedule-delete-confirm"
              disabled={busyId === deleting?.id}
              onClick={() => void confirmDelete()}
            >
              {tx("qa.schedules.deleteConfirm", "确认删除")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function QaScheduleDialog({
  token,
  client,
  open,
  onOpenChange,
  projects,
  scripts,
  schedule,
  onSaved,
}: {
  token: string;
  client: QaMutationTransport;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: QaProject[];
  scripts: Array<{ id: string; project_id: string; name: string }>;
  schedule: QaSchedule | null;
  onSaved: () => void;
}) {
  const tx = useQaCopy();
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [cron, setCron] = useState("0 3 * * *");
  const [timezone, setTimezone] = useState("");
  const [kind, setKind] = useState<"script" | "cases">("script");
  const [scriptId, setScriptId] = useState("");
  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const target = schedule?.target;
    setProjectId(schedule?.project_id || projects[0]?.id || "");
    setName(schedule?.name || "");
    setCron(schedule?.cron || "0 3 * * *");
    setTimezone(schedule?.timezone || "");
    setKind(target?.kind === "cases" ? "cases" : "script");
    setScriptId(target?.kind === "script" ? target.script_id : "");
    setCaseIds(target?.kind === "cases" ? [...target.case_ids] : []);
    setEnabled(schedule ? schedule.enabled : true);
    setError("");
  }, [open, schedule, projects]);

  const projectScripts = useMemo(
    () => scripts.filter((script) => script.project_id === projectId),
    [scripts, projectId],
  );
  const cases = useQaQuery(
    () => loadQaCases(token, { projectId, limit: 200 }),
    [token, projectId],
    { enabled: open && Boolean(projectId), intervalMs: 0 },
  );

  useEffect(() => {
    if (!open || kind !== "script" || scriptId) return;
    const first = projectScripts[0];
    if (first) setScriptId(first.id);
  }, [open, kind, scriptId, projectScripts]);

  const submit = async () => {
    if (busy) return;
    if (!projectId) {
      setError(tx("qa.cases.projectRequired", "请选择项目"));
      return;
    }
    if (!name.trim() || !cron.trim()) {
      setError(tx("qa.schedules.required", "请填写名称和 cron 表达式"));
      return;
    }
    if (kind === "script" && !scriptId) {
      setError(tx("qa.schedules.scriptRequired", "请选择要运行的脚本"));
      return;
    }
    if (kind === "cases" && caseIds.length === 0) {
      setError(tx("qa.schedules.casesRequired", "请至少选择一个用例"));
      return;
    }
    const target: QaScheduleTarget =
      kind === "script"
        ? { kind: "script", script_id: scriptId }
        : { kind: "cases", case_ids: caseIds };
    setBusy(true);
    setError("");
    try {
      if (schedule) {
        await updateQaSchedule(client, schedule.id, {
          name: name.trim(),
          cron: cron.trim(),
          timezone: timezone.trim(),
          enabled,
          target,
        });
      } else {
        await createQaSchedule(client, {
          project_id: projectId,
          name: name.trim(),
          cron: cron.trim(),
          timezone: timezone.trim(),
          enabled,
          target,
        });
      }
      onOpenChange(false);
      onSaved();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="qa-schedule-dialog">
        <DialogHeader>
          <DialogTitle>
            {schedule
              ? tx("qa.schedules.edit", "编辑")
              : tx("qa.schedules.create", "新建定时任务")}
          </DialogTitle>
          <DialogDescription>
            {tx(
              "qa.schedules.dialogHint",
              "cron 使用五段表达式（分 时 日 月 周），由网关进程按时触发。",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-left">
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {tx("qa.cases.fieldProject", "项目")}
              </span>
              <Select value={projectId} onValueChange={setProjectId} disabled={Boolean(schedule)}>
                <SelectTrigger
                  aria-label={tx("qa.cases.fieldProject", "项目")}
                  className="h-9"
                  data-testid="qa-schedule-project"
                >
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
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {tx("qa.schedules.name", "名称")}
              </span>
              <Input
                value={name}
                aria-label={tx("qa.schedules.name", "名称")}
                onChange={(event) => setName(event.target.value)}
                disabled={busy}
                data-testid="qa-schedule-name"
              />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {tx("qa.schedules.cron", "计划")}
              </span>
              <Input
                value={cron}
                aria-label={tx("qa.schedules.cron", "计划")}
                placeholder="0 3 * * *"
                onChange={(event) => setCron(event.target.value)}
                className="font-mono text-[12px]"
                disabled={busy}
                data-testid="qa-schedule-cron"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
                {tx("qa.schedules.timezone", "时区")}
              </span>
              <Input
                value={timezone}
                aria-label={tx("qa.schedules.timezone", "时区")}
                placeholder="Asia/Shanghai"
                onChange={(event) => setTimezone(event.target.value)}
                className="font-mono text-[12px]"
                disabled={busy}
                data-testid="qa-schedule-timezone"
              />
            </label>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] font-medium text-muted-foreground">
                {tx("qa.schedules.target", "目标")}
              </span>
              <Select
                value={kind}
                onValueChange={(value) => setKind(value === "cases" ? "cases" : "script")}
              >
                <SelectTrigger
                  aria-label={tx("qa.schedules.target", "目标")}
                  className="h-8 w-[9rem]"
                  data-testid="qa-schedule-target-kind"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="script">{tx("qa.schedules.targetScript", "自动化脚本")}</SelectItem>
                  <SelectItem value="cases">{tx("qa.schedules.targetCases", "用例集合")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {kind === "script" ? (
              <Select value={scriptId} onValueChange={setScriptId}>
                <SelectTrigger
                  aria-label={tx("qa.schedules.script", "脚本")}
                  className="h-9"
                  data-testid="qa-schedule-script"
                >
                  <SelectValue placeholder={tx("qa.schedules.scriptRequired", "请选择要运行的脚本")} />
                </SelectTrigger>
                <SelectContent>
                  {projectScripts.map((script) => (
                    <SelectItem key={script.id} value={script.id}>
                      {script.name || script.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <div className="max-h-48 overflow-y-auto rounded-md border border-border/60">
                {cases.loading && !cases.data ? (
                  <p className="px-3 py-2 text-[12px] text-muted-foreground">
                    {tx("qa.status.loading", "加载中…")}
                  </p>
                ) : (cases.data?.items ?? []).length === 0 ? (
                  <p className="px-3 py-2 text-[12px] text-muted-foreground">
                    {tx("qa.schedules.noCases", "该项目还没有可选择的用例")}
                  </p>
                ) : (
                  (cases.data?.items ?? []).map((item) => (
                    <label
                      key={item.id}
                      className="flex items-start gap-2 px-2 py-1.5 text-[12.5px] hover:bg-muted/30"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={caseIds.includes(item.id)}
                        data-testid={`qa-schedule-case-${item.id}`}
                        onChange={() =>
                          setCaseIds((current) =>
                            current.includes(item.id)
                              ? current.filter((id) => id !== item.id)
                              : [...current, item.id],
                          )
                        }
                      />
                      <span className="font-mono text-[11px] text-muted-foreground">{item.code}</span>
                      <span className="min-w-0 flex-1 truncate text-foreground">{item.title}</span>
                    </label>
                  ))
                )}
              </div>
            )}
          </div>

          <label className="flex items-center gap-2 text-[13px] text-foreground">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              data-testid="qa-schedule-enabled"
            />
            {tx("qa.schedules.enabledHint", "创建后立即启用")}
          </label>

          {error ? <QaErrorBar message={error} /> : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            {tx("qa.actions.cancel", "取消")}
          </Button>
          <Button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            data-testid="qa-schedule-submit"
          >
            {tx("qa.actions.save", "保存")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
