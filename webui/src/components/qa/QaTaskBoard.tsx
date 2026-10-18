import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";

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
  approveTask,
  cancelQaTask,
  loadQaTask,
  loadQaTaskEvents,
  loadQaTasks,
  qaErrorMessage,
  rejectTask,
  type QaMutationTransport,
  type QaProject,
  type QaTask,
  type QaTaskDetail,
  type QaTaskEvent,
  type QaTaskStatus,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaDetailDrawer, QaDetailField, QaDetailSection } from "./QaDetailDrawer";
import {
  formatQaTime,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPre,
  QaProgress,
  QaSectionTitle,
  QaTableShell,
  QaTaskStatusBadge,
  QaTruncate,
  QA_TD_CLASS,
  QA_TH_CLASS,
  qaRoleLabel,
  useQaCopy,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

const TASK_STATUS_FILTERS: QaTaskStatus[] = [
  "queued",
  "running",
  "needs_review",
  "blocked",
  "done",
  "failed",
  "cancelled",
];

export interface QaTaskBoardProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  pollIntervalMs: number;
  refreshSignal: number;
  onChanged: () => void;
}

export function QaTaskBoard({
  token,
  client,
  projects,
  pollIntervalMs,
  refreshSignal,
  onChanged,
}: QaTaskBoardProps) {
  const tx = useQaCopy();
  const visible = usePageVisibility();
  const [status, setStatus] = useState<string>("all");
  const [role, setRole] = useState<string>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  /** The review dialog target: which task, and approve or reject. */
  const [decision, setDecision] = useState<{ task: QaTask; approved: boolean } | null>(null);
  /** Bumped after a decision so an open drawer reloads its task and events. */
  const [detailNonce, setDetailNonce] = useState(0);

  const tasks = useQaQuery(
    () =>
      loadQaTasks(token, {
        status: status === "all" ? undefined : status,
        role: role === "all" ? undefined : role,
        limit: 200,
      }),
    [token, status, role, refreshSignal],
    { intervalMs: visible ? pollIntervalMs : 0 },
  );

  const items = tasks.data?.items ?? [];
  const projectNames = useMemo(() => {
    const map = new Map<string, string>();
    projects.forEach((project) => map.set(project.id, project.key || project.name));
    return map;
  }, [projects]);

  const statusLabels: Record<QaTaskStatus, string> = {
    queued: tx("qa.taskStatus.queued", "排队中"),
    running: tx("qa.taskStatus.running", "进行中"),
    needs_review: tx("qa.taskStatus.needsReview", "待复核"),
    blocked: tx("qa.taskStatus.blocked", "受阻"),
    done: tx("qa.taskStatus.done", "已完成"),
    failed: tx("qa.taskStatus.failed", "失败"),
    cancelled: tx("qa.taskStatus.cancelled", "已取消"),
  };

  return (
    <div className="flex flex-col gap-3" data-testid="qa-tasks">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <QaSectionTitle
          title={tx("qa.tasks.title", "任务板")}
          count={tasks.data?.total ?? items.length}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger aria-label={tx("qa.tasks.filterStatus", "状态筛选")} className="h-8 w-[8.5rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{tx("qa.filters.allStatus", "全部状态")}</SelectItem>
              {TASK_STATUS_FILTERS.map((value) => (
                <SelectItem key={value} value={value}>
                  {statusLabels[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={role} onValueChange={setRole}>
            <SelectTrigger aria-label={tx("qa.tasks.filterRole", "角色筛选")} className="h-8 w-[7.5rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{tx("qa.filters.allRoles", "全部角色")}</SelectItem>
              {(["orchestrator", "api", "ui", "automation", "review"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {qaRoleLabel(value, tx)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 px-2.5"
            onClick={tasks.reload}
            disabled={tasks.loading && items.length === 0}
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5",
                tasks.loading && "animate-spin motion-reduce:animate-none",
              )}
              aria-hidden
            />
            {tx("qa.actions.refresh", "刷新")}
          </Button>
        </div>
      </div>

      {tasks.error ? (
        <QaErrorBar
          message={`${tx("qa.error.tasks", "加载任务失败")}: ${tasks.error}`}
          onRetry={tasks.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}

      {tasks.loading && !tasks.data ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : items.length === 0 ? (
        <QaEmptyState
          title={tx("qa.tasks.empty", "暂无任务")}
          hint={tx(
            "qa.tasks.emptyHint",
            "QA Agent 追加任务后会出现在这里；每 3 秒自动刷新，可查看进度、产物与事件时间线。",
          )}
          action={
            <Button type="button" size="sm" variant="outline" onClick={tasks.reload}>
              {tx("qa.actions.refresh", "刷新")}
            </Button>
          }
        />
      ) : (
        <QaTableShell label={tx("qa.tasks.title", "任务板")}>
          <thead>
            <tr>
              <th className={QA_TH_CLASS}>{tx("qa.tasks.role", "角色")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.tasks.name", "任务")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.tasks.status", "状态")}</th>
              <th className={cn(QA_TH_CLASS, "w-[9rem]")}>{tx("qa.tasks.progress", "进度")}</th>
              <th className={QA_TH_CLASS}>{tx("qa.tasks.project", "项目")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>{tx("qa.tasks.updatedAt", "更新时间")}</th>
              <th className={cn(QA_TH_CLASS, "text-right")}>{tx("qa.tasks.actions", "操作")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((task) => (
              <tr
                key={task.id}
                className="cursor-pointer hover:bg-muted/30"
                onClick={() => setSelectedId(task.id)}
              >
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  {qaRoleLabel(task.role, tx)}
                </td>
                <td className={QA_TD_CLASS}>
                  <button
                    type="button"
                    className="block max-w-[26rem] truncate text-left font-medium text-foreground hover:underline"
                    title={task.title}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedId(task.id);
                    }}
                  >
                    {task.title || task.id}
                  </button>
                </td>
                <td className={QA_TD_CLASS}>
                  <QaTaskStatusBadge status={task.status} />
                </td>
                <td className={QA_TD_CLASS}>
                  <QaProgress value={task.progress} />
                </td>
                <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                  <QaTruncate
                    text={
                      (task.project_id && projectNames.get(task.project_id))
                      || task.project_key
                      || ""
                    }
                    className="max-w-[8rem]"
                  />
                </td>
                <td className={cn(QA_TD_CLASS, "text-right text-[12px] text-muted-foreground")}>
                  {formatQaTime(task.updated_at)}
                </td>
                <td className={cn(QA_TD_CLASS, "text-right")}>
                  {task.status === "needs_review" ? (
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        type="button"
                        size="sm"
                        className="h-7 px-2"
                        data-testid="qa-task-approve"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDecision({ task, approved: true });
                        }}
                      >
                        {tx("qa.tasks.approve", "通过")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 px-2"
                        data-testid="qa-task-reject"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDecision({ task, approved: false });
                        }}
                      >
                        {tx("qa.tasks.reject", "退回")}
                      </Button>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </QaTableShell>
      )}

      <QaTaskDrawer
        token={token}
        client={client}
        taskId={selectedId}
        open={selectedId !== null}
        onOpenChange={(open) => { if (!open) setSelectedId(null); }}
        pollIntervalMs={pollIntervalMs}
        refreshToken={detailNonce}
        onDecide={(task, approved) => setDecision({ task, approved })}
        onChanged={() => {
          tasks.reload();
          onChanged();
        }}
      />

      <QaTaskDecisionDialog
        client={client}
        decision={decision}
        onOpenChange={(open) => { if (!open) setDecision(null); }}
        onDecided={() => {
          // The list changes status and the drawer gains the audit event.
          setDetailNonce((current) => current + 1);
          tasks.reload();
          onChanged();
        }}
      />
    </div>
  );
}

function QaTaskDrawer({
  token,
  client,
  taskId,
  open,
  onOpenChange,
  pollIntervalMs,
  refreshToken,
  onDecide,
  onChanged,
}: {
  token: string;
  client: QaMutationTransport;
  taskId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pollIntervalMs: number;
  /** Bumped by the board after a review decision so detail + events reload. */
  refreshToken: number;
  onDecide: (task: QaTask, approved: boolean) => void;
  onChanged: () => void;
}) {
  const tx = useQaCopy();
  const visible = usePageVisibility();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  const drawerQuery = useQaQuery<{
    detail: QaTaskDetail;
    events: Awaited<ReturnType<typeof loadQaTaskEvents>>;
  } | null>(
    async () => {
      if (!taskId) return null;
      const [detail, eventList] = await Promise.all([
        loadQaTask(token, taskId),
        loadQaTaskEvents(token, taskId),
      ]);
      return { detail, events: eventList };
    },
    [token, taskId, refreshToken],
    {
      enabled: open && Boolean(taskId),
      // Live tasks are watched while the drawer is open.
      intervalMs: visible ? pollIntervalMs : 0,
    },
  );

  const detail = drawerQuery.data?.detail ?? null;
  const eventsList = drawerQuery.data?.events ?? [];
  const drawerError = drawerQuery.error;
  const reloadAll = drawerQuery.reload;

  const runAction = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setActionError("");
    try {
      await action();
      reloadAll();
      onChanged();
    } catch (reason) {
      setActionError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const terminal = detail
    ? detail.status === "done" || detail.status === "failed" || detail.status === "cancelled"
    : true;

  return (
    <QaDetailDrawer
      open={open}
      onOpenChange={onOpenChange}
      testId="qa-task-drawer"
      title={detail?.title || tx("qa.tasks.detailTitle", "任务详情")}
      description={detail?.id ?? ""}
      badge={
        detail ? (
          <>
            <QaTaskStatusBadge status={detail.status} />
            <span className="text-[11px] text-muted-foreground">
              {qaRoleLabel(detail.role, tx)} · {formatQaTime(detail.updated_at)}
            </span>
          </>
        ) : null
      }
      meta={
        detail
          ? [
              { label: tx("qa.tasks.progress", "进度"), value: `${detail.progress}%` },
              {
                label: tx("qa.tasks.project", "项目"),
                value: detail.project_key
                  || (detail.project_id ?? ""),
              },
              {
                label: tx("qa.tasks.createdAt", "创建时间"),
                value: formatQaTime(detail.created_at),
              },
              {
                label: tx("qa.tasks.subagent", "Subagent"),
                value: detail.subagent_task_id,
                mono: true,
              },
            ]
          : []
      }
      footer={
        detail && !terminal ? (
          <>
            {detail.status === "needs_review" ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  data-testid="qa-task-drawer-reject"
                  onClick={() => onDecide(detail, false)}
                >
                  {tx("qa.tasks.reject", "退回")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  data-testid="qa-task-drawer-approve"
                  onClick={() => onDecide(detail, true)}
                >
                  {tx("qa.tasks.approve", "通过")}
                </Button>
              </>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                data-testid="qa-task-cancel"
                onClick={() => void runAction(() => cancelQaTask(client, detail.id))}
              >
                {tx("qa.tasks.cancelTask", "取消任务")}
              </Button>
            )}
          </>
        ) : null
      }
    >
      {actionError ? <QaErrorBar message={actionError} /> : null}
      {drawerError ? <QaErrorBar message={drawerError} onRetry={reloadAll} /> : null}
      {!detail ? (
        <QaLoading label={tx("qa.status.loading", "加载中…")} />
      ) : (
        <>
          <QaDetailSection title={tx("qa.tasks.prompt", "Prompt")}>
            <QaPre>{detail.prompt || tx("qa.tasks.noPrompt", "（无 prompt）")}</QaPre>
          </QaDetailSection>

          <QaDetailSection title={tx("qa.tasks.result", "结果")}>
            <QaPre>{detail.result || tx("qa.tasks.noResult", "（尚未产出结果）")}</QaPre>
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.tasks.children", "子任务")}
            hint={String(detail.children.length)}
          >
            {detail.children.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.tasks.noChildren", "无子任务")}
              </p>
            ) : (
              <ul className="divide-y divide-border/40 rounded-lg border border-border/60">
                {detail.children.map((child) => (
                  <li key={child.id} className="flex items-center gap-2 px-3 py-2">
                    <QaTaskStatusBadge status={child.status} />
                    <span className="min-w-0 flex-1 truncate text-[12.5px]" title={child.title}>
                      {child.title}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                      {child.progress}%
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.tasks.artifacts", "产物")}
            hint={String(detail.artifacts.length)}
          >
            {detail.artifacts.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.tasks.noArtifacts", "无产物")}
              </p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {detail.artifacts.map((artifact) => (
                  <li
                    key={`${artifact.kind}:${artifact.ref_id}`}
                    className="max-w-full rounded-control border border-border/60 bg-muted/30 px-2 py-1 text-[11.5px]"
                    title={`${artifact.kind}: ${artifact.ref_id}`}
                  >
                    <span className="font-medium text-foreground">
                      {artifact.title || artifact.ref_id}
                    </span>
                    <span className="ml-1.5 text-muted-foreground">{artifact.kind}</span>
                  </li>
                ))}
              </ul>
            )}
          </QaDetailSection>

          <QaDetailSection
            title={tx("qa.tasks.events", "事件时间线")}
            hint={String(eventsList.length)}
          >
            {eventsList.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                {tx("qa.tasks.noEvents", "暂无事件")}
              </p>
            ) : (
              <ol className="relative flex flex-col gap-2 border-l border-border/60 pl-3">
                {eventsList.map((event) => (
                  <QaTaskEventItem key={String(event.id)} event={event} />
                ))}
              </ol>
            )}
          </QaDetailSection>
        </>
      )}
    </QaDetailDrawer>
  );
}

/**
 * One timeline row. `approved` / `rejected` events carry the reviewer in
 * `data.reviewer` and the note in `message`, so they get their own icon and
 * colour instead of the generic progress dot.
 */
function QaTaskEventItem({ event }: { event: QaTaskEvent }) {
  const tx = useQaCopy();
  const decision =
    event.kind === "approved" || event.kind === "rejected" ? event.kind : null;
  const reviewer = typeof event.data.reviewer === "string" ? event.data.reviewer : "";
  // Without a note the backend repeats the decision word as the message, which
  // the badge already shows; keep the note line empty instead of echoing it.
  const note = decision && event.message !== event.kind ? event.message : "";

  return (
    <li data-testid={`qa-task-event-${event.kind}`} className="relative">
      <span
        aria-hidden
        className={cn(
          "absolute top-1 grid place-items-center rounded-full",
          decision
            ? "-left-[1.15rem] h-3.5 w-3.5"
            : "-left-[0.95rem] h-1.5 w-1.5 bg-border",
          decision === "approved"
            ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
            : decision === "rejected"
              ? "bg-red-500/15 text-red-600 dark:text-red-400"
              : "",
        )}
      >
        {decision === "approved" ? (
          <CheckCircle2 className="h-3 w-3" aria-hidden />
        ) : decision === "rejected" ? (
          <XCircle className="h-3 w-3" aria-hidden />
        ) : null}
      </span>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {formatQaTime(event.at)}
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10.5px] font-medium",
            decision === "approved"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : decision === "rejected"
                ? "bg-red-500/10 text-red-700 dark:text-red-300"
                : "bg-muted/70 text-muted-foreground",
          )}
        >
          {decision === "approved"
            ? tx("qa.tasks.approved", "通过")
            : decision === "rejected"
              ? tx("qa.tasks.rejected", "退回")
              : event.kind}
        </span>
        {reviewer ? (
          <span className="text-[11px] text-muted-foreground">
            {tx("qa.tasks.reviewerLabel", "评审人")}: {reviewer}
          </span>
        ) : null}
      </div>
      <p className="mt-0.5 whitespace-pre-wrap break-words text-[12.5px] text-foreground">
        {(decision ? note : event.message) || "—"}
      </p>
    </li>
  );
}

/**
 * Review dialog shared by the list rows and the drawer: an optional note and
 * an optional reviewer, then `qa.task.approve` / `qa.task.reject`.
 */
function QaTaskDecisionDialog({
  client,
  decision,
  onOpenChange,
  onDecided,
}: {
  client: QaMutationTransport;
  decision: { task: QaTask; approved: boolean } | null;
  onOpenChange: (open: boolean) => void;
  onDecided: () => void;
}) {
  const tx = useQaCopy();
  const open = decision !== null;
  const taskId = decision?.task.id ?? "";
  const approved = decision?.approved ?? true;

  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setNote("");
    setReviewer("");
    setError("");
  }, [open, taskId, approved]);

  const submit = async () => {
    if (!decision || busy) return;
    setBusy(true);
    setError("");
    try {
      if (decision.approved) {
        await approveTask(client, decision.task.id, { note, reviewer });
      } else {
        await rejectTask(client, decision.task.id, { note, reviewer });
      }
      onOpenChange(false);
      onDecided();
    } catch (reason) {
      setError(qaErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="qa-task-decision-dialog">
        <DialogHeader>
          <DialogTitle>
            {approved
              ? tx("qa.tasks.approveTitle", "通过任务")
              : tx("qa.tasks.rejectTitle", "退回任务")}
          </DialogTitle>
          <DialogDescription>
            {decision?.task.title || taskId}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-left">
          <p className="text-[12px] leading-5 text-muted-foreground">
            {tx(
              "qa.tasks.decisionHint",
              "备注与评审人都是可选项；提交后会写入事件时间线，退回的任务会标记为失败以便返工。",
            )}
          </p>
          <QaDetailField label={tx("qa.tasks.note", "备注（可选）")}>
            <Textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              aria-label={tx("qa.tasks.note", "备注（可选）")}
              data-testid="qa-task-decision-note"
              disabled={busy}
            />
          </QaDetailField>
          <QaDetailField label={tx("qa.tasks.reviewer", "评审人（可选）")}>
            <Input
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value)}
              aria-label={tx("qa.tasks.reviewer", "评审人（可选）")}
              data-testid="qa-task-decision-reviewer"
              disabled={busy}
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
            variant={approved ? "default" : "outline"}
            onClick={() => void submit()}
            disabled={busy}
            data-testid="qa-task-decision-submit"
          >
            {approved
              ? tx("qa.tasks.approveSubmit", "确认通过")
              : tx("qa.tasks.rejectSubmit", "确认退回")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
