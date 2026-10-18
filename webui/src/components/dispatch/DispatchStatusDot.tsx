import { cn } from "@/lib/utils";
import type { DispatchStatus } from "@/lib/dispatch-desk";

const DOT_CLASS: Record<DispatchStatus, string> = {
  pending: "bg-muted-foreground/45",
  running: "bg-primary motion-safe:animate-pulse",
  done: "bg-foreground/70",
  failed: "bg-destructive",
};

export function DispatchStatusDot({ status }: { status: DispatchStatus }) {
  return (
    <span
      aria-hidden
      data-dispatch-status={status}
      className={cn("h-2 w-2 shrink-0 rounded-full", DOT_CLASS[status])}
    />
  );
}
