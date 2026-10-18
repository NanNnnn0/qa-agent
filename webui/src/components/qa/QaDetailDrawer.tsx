import type { ReactNode } from "react";

import { QaDrawer, QaFieldLabel } from "./qa-ui";
import { cn } from "@/lib/utils";

export interface QaDetailMeta {
  label: string;
  value: string;
  mono?: boolean;
}

/**
 * Right-side detail surface shared by every QA tab: identity header, status
 * badge, a compact meta grid and one scrolling body.
 */
export function QaDetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  badge,
  meta = [],
  children,
  footer,
  testId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  badge?: ReactNode;
  meta?: QaDetailMeta[];
  children: ReactNode;
  footer?: ReactNode;
  testId?: string;
}) {
  return (
    <QaDrawer
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={footer}
      testId={testId}
    >
      {badge ? <div className="mb-3 flex flex-wrap items-center gap-2">{badge}</div> : null}
      {meta.length > 0 ? (
        <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5">
          {meta.map((item) => (
            <div key={item.label} className="min-w-0">
              <dt className="text-[11px] font-medium text-muted-foreground">{item.label}</dt>
              <dd
                title={item.value}
                className={cn(
                  "mt-0.5 truncate text-[12.5px] text-foreground",
                  item.mono && "font-mono text-[12px]",
                )}
              >
                {item.value || "—"}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      <div className="flex flex-col gap-4">{children}</div>
    </QaDrawer>
  );
}

export function QaDetailSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3 className="text-[12px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
          {title}
        </h3>
        {hint ? <span className="truncate text-[11px] text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function QaDetailField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <QaFieldLabel>{label}</QaFieldLabel>
      {children}
    </div>
  );
}
