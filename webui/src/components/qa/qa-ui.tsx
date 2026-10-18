import type { ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import type {
  QaCaseKind,
  QaCasePriority,
  QaCaseStatus,
  QaRun,
  QaRunStatus,
  QaRunTrigger,
  QaTaskRole,
  QaTaskStatus,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

/** `t()` with a Chinese fallback, so a missing locale key never blanks the UI. */
export function qaText(
  t: TFunction,
  key: string,
  fallback: string,
  values?: Record<string, unknown>,
): string {
  return t(key, { defaultValue: fallback, ...(values ?? {}) }) as string;
}

export function useQaCopy() {
  const { t } = useTranslation();
  return (key: string, fallback: string, values?: Record<string, unknown>) =>
    qaText(t, key, fallback, values);
}

// -- tones ----------------------------------------------------------------

export type QaTone = "blue" | "amber" | "green" | "red" | "neutral" | "violet";

const TONE_CLASS: Record<QaTone, string> = {
  blue: "bg-blue-500/10 text-blue-700 ring-blue-500/20 dark:text-blue-300",
  amber: "bg-amber-500/10 text-amber-700 ring-amber-500/20 dark:text-amber-300",
  green: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/20 dark:text-emerald-300",
  red: "bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300",
  neutral: "bg-muted/60 text-muted-foreground ring-border/60",
  violet: "bg-violet-500/10 text-violet-700 ring-violet-500/20 dark:text-violet-300",
};

const DOT_CLASS: Record<QaTone, string> = {
  blue: "bg-blue-500",
  amber: "bg-amber-500",
  green: "bg-emerald-500",
  red: "bg-red-500",
  neutral: "bg-muted-foreground/50",
  violet: "bg-violet-500",
};

export const TASK_STATUS_TONE: Record<QaTaskStatus, QaTone> = {
  queued: "neutral",
  running: "blue",
  needs_review: "amber",
  blocked: "neutral",
  done: "green",
  failed: "red",
  cancelled: "neutral",
};

const RUN_STATUS_TONE: Record<QaRunStatus, QaTone> = {
  running: "blue",
  passed: "green",
  failed: "red",
  error: "red",
  // Environment problems are not product defects: amber, never red.
  blocked_by_env: "amber",
  cancelled: "neutral",
};

const CASE_STATUS_TONE: Record<QaCaseStatus, QaTone> = {
  draft: "neutral",
  ready: "green",
  deprecated: "neutral",
};

/** Run origin: one distinct colour per trigger so CI runs stand out. */
const RUN_TRIGGER_TONE: Record<QaRunTrigger, QaTone> = {
  manual: "blue",
  ci: "violet",
  agent: "green",
  schedule: "amber",
};

const PRIORITY_TONE: Record<QaCasePriority, QaTone> = {
  P0: "red",
  P1: "amber",
  P2: "neutral",
  P3: "neutral",
};

export function QaBadge({
  tone,
  children,
  className,
  dot = false,
  title,
}: {
  tone: QaTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full shrink-0 items-center gap-1.5 truncate rounded-full px-2 py-0.5",
        "text-[11px] font-medium ring-1 ring-inset",
        TONE_CLASS[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASS[tone])} /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export function QaTaskStatusBadge({ status }: { status: QaTaskStatus }) {
  const tx = useQaCopy();
  const labels: Record<QaTaskStatus, string> = {
    queued: tx("qa.taskStatus.queued", "排队中"),
    running: tx("qa.taskStatus.running", "进行中"),
    needs_review: tx("qa.taskStatus.needsReview", "待复核"),
    blocked: tx("qa.taskStatus.blocked", "受阻"),
    done: tx("qa.taskStatus.done", "已完成"),
    failed: tx("qa.taskStatus.failed", "失败"),
    cancelled: tx("qa.taskStatus.cancelled", "已取消"),
  };
  return (
    <QaBadge tone={TASK_STATUS_TONE[status]} dot title={labels[status]}>
      {labels[status]}
    </QaBadge>
  );
}

export function QaRunStatusBadge({ status }: { status: QaRunStatus }) {
  const tx = useQaCopy();
  const labels: Record<QaRunStatus, string> = {
    running: tx("qa.runStatus.running", "运行中"),
    passed: tx("qa.runStatus.passed", "通过"),
    failed: tx("qa.runStatus.failed", "失败"),
    error: tx("qa.runStatus.error", "错误"),
    blocked_by_env: tx("qa.runStatus.blockedByEnv", "环境阻塞"),
    cancelled: tx("qa.runStatus.cancelled", "已取消"),
  };
  return (
    <QaBadge tone={RUN_STATUS_TONE[status]} dot title={labels[status]}>
      {labels[status]}
    </QaBadge>
  );
}

export function QaCaseStatusBadge({ status }: { status: QaCaseStatus }) {
  const tx = useQaCopy();
  const labels: Record<QaCaseStatus, string> = {
    draft: tx("qa.caseStatus.draft", "草稿"),
    ready: tx("qa.caseStatus.ready", "就绪"),
    deprecated: tx("qa.caseStatus.deprecated", "已废弃"),
  };
  return <QaBadge tone={CASE_STATUS_TONE[status]}>{labels[status]}</QaBadge>;
}

/** `manual` / `ci` / `agent` / `schedule`, each with its own colour. */
export function QaRunTriggerBadge({ trigger }: { trigger: QaRunTrigger }) {
  const tx = useQaCopy();
  const hints: Record<QaRunTrigger, string> = {
    manual: tx("qa.trigger.manualHint", "手动触发"),
    ci: tx("qa.trigger.ciHint", "CI 导入"),
    agent: tx("qa.trigger.agentHint", "Agent 触发"),
    schedule: tx("qa.trigger.scheduleHint", "定时任务"),
  };
  return (
    <QaBadge tone={RUN_TRIGGER_TONE[trigger]} className="font-mono" title={hints[trigger]}>
      {trigger}
    </QaBadge>
  );
}

/** Run label: the explicit name, else the first 8 characters of the id. */
export function qaRunName(run: Pick<QaRun, "id" | "name">): string {
  const name = run.name.trim();
  if (name) return name;
  return run.id ? run.id.slice(0, 8) : "";
}

export function QaPriorityBadge({ priority }: { priority: QaCasePriority }) {
  return (
    <QaBadge tone={PRIORITY_TONE[priority]} className="font-mono tabular-nums">
      {priority}
    </QaBadge>
  );
}

export function qaKindLabel(kind: QaCaseKind, tx: ReturnType<typeof useQaCopy>): string {
  const labels: Record<QaCaseKind, string> = {
    api: tx("qa.kind.api", "接口"),
    ui: tx("qa.kind.ui", "界面"),
    manual: tx("qa.kind.manual", "手工"),
  };
  return labels[kind];
}

export function qaRoleLabel(role: QaTaskRole, tx: ReturnType<typeof useQaCopy>): string {
  const labels: Record<QaTaskRole, string> = {
    orchestrator: tx("qa.role.orchestrator", "编排"),
    api: tx("qa.role.api", "接口"),
    ui: tx("qa.role.ui", "界面"),
    automation: tx("qa.role.automation", "自动化"),
    review: tx("qa.role.review", "复核"),
  };
  return labels[role];
}

// -- layout atoms ----------------------------------------------------------

export function QaProgress({ value, className }: { value: number; className?: string }) {
  const safe = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        role="progressbar"
        aria-valuenow={safe}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1.5 w-full min-w-10 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none",
            safe >= 100 ? "bg-emerald-500" : "bg-blue-500",
          )}
          style={{ width: `${safe}%` }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
        {safe}%
      </span>
    </div>
  );
}

export function QaPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-lg border border-border/60 bg-card", className)}>
      {children}
    </div>
  );
}

export function QaStatCard({
  label,
  value,
  hint,
  testId,
}: {
  label: string;
  value: number | string;
  hint?: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-lg border border-border/60 bg-card px-4 py-3"
    >
      <p className="truncate text-[12px] font-medium text-muted-foreground" title={label}>
        {label}
      </p>
      <p className="mt-1 text-[24px] font-semibold leading-none tabular-nums text-foreground">
        {value}
      </p>
      {hint ? <p className="mt-1 truncate text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function QaSectionTitle({
  title,
  count,
  action,
}: {
  title: string;
  count?: number;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold text-foreground">
        <span className="truncate">{title}</span>
        {count !== undefined ? (
          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground">
            {count}
          </span>
        ) : null}
      </h2>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

export function QaLoading({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-busy="true"
      className="flex h-40 items-center justify-center gap-2 rounded-lg border border-border/60 bg-card text-sm text-muted-foreground"
    >
      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {label}
    </div>
  );
}

export function QaErrorBar({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      data-testid="qa-error"
      className="flex items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-[13px] text-destructive"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 break-words">{message}</span>
      {onRetry ? (
        <Button type="button" size="sm" variant="ghost" className="h-7 shrink-0 px-2" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

export function QaEmptyState({
  title,
  hint,
  action,
  testId,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId ?? "qa-empty"}
      className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border/70 bg-card/40 px-6 py-12 text-center"
    >
      <p className="text-sm font-medium text-foreground">{title}</p>
      {hint ? <p className="max-w-md text-[13px] leading-5 text-muted-foreground">{hint}</p> : null}
      {action ? <div className="mt-2 flex items-center gap-2">{action}</div> : null}
    </div>
  );
}

// -- tables ---------------------------------------------------------------

export const QA_TH_CLASS =
  "sticky top-0 z-10 border-b border-border/60 bg-card px-3 py-2 text-left text-[11px] font-medium uppercase tracking-[0.04em] text-muted-foreground";

export const QA_TD_CLASS = "border-b border-border/40 px-3 py-2.5 align-middle text-sm";

export function QaTableShell({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <QaPanel className={className}>
      {/* Vertical overflow stays off the table so the sticky header sticks to
          the page scroller; small screens still get a horizontal scrollport. */}
      <div className="max-w-full overflow-x-auto md:overflow-x-visible">
        <table aria-label={label} className="w-full min-w-[42rem] border-collapse text-sm">
          {children}
        </table>
      </div>
    </QaPanel>
  );
}

/** Truncating cell with a native tooltip — the list screens are density-first. */
export function QaTruncate({ text, className }: { text: string; className?: string }) {
  if (!text) return <span className="text-muted-foreground">—</span>;
  return (
    <span title={text} className={cn("block max-w-[22rem] truncate", className)}>
      {text}
    </span>
  );
}

export function QaTagChips({ tags, limit = 3 }: { tags: string[]; limit?: number }) {
  if (tags.length === 0) return <span className="text-muted-foreground">—</span>;
  const shown = tags.slice(0, limit);
  const rest = tags.length - shown.length;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((tag) => (
        <span
          key={tag}
          title={tag}
          className="max-w-[7rem] truncate rounded bg-muted/70 px-1.5 py-0.5 text-[11px] text-muted-foreground"
        >
          {tag}
        </span>
      ))}
      {rest > 0 ? (
        <span className="text-[11px] text-muted-foreground" title={tags.join(", ")}>
          +{rest}
        </span>
      ) : null}
    </span>
  );
}

// -- formatting ------------------------------------------------------------

export function formatQaTime(value: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatQaDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

// -- drawer ----------------------------------------------------------------

export function QaDrawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  testId = "qa-drawer",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  testId?: string;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        data-testid={testId}
        className="w-full gap-0 p-0 sm:max-w-2xl"
      >
        <div className="border-b border-border/60 px-5 py-4 pr-12">
          <SheetTitle className="truncate text-base font-semibold">{title}</SheetTitle>
          <SheetDescription className="mt-1 text-[12px] text-muted-foreground">
            {description || " "}
          </SheetDescription>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border/60 px-5 py-3">
            {footer}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

export function QaFieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="mb-1 block text-[12px] font-medium text-muted-foreground">{children}</span>
  );
}

export function QaPre({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-muted/25">
      {label ? (
        <p className="border-b border-border/50 px-3 py-1.5 text-[11px] font-medium text-muted-foreground">
          {label}
        </p>
      ) : null}
      <pre
        className={cn(
          "max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[12px] leading-5 text-foreground",
          className,
        )}
      >
        {children}
      </pre>
    </div>
  );
}
