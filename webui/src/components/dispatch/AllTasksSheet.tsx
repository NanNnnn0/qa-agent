import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { DispatchStatusDot } from "@/components/dispatch/DispatchStatusDot";
import { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  DISPATCH_STATUSES,
  dispatchTasksByStatus,
  type DispatchStatus,
} from "@/lib/dispatch-desk";
import { cn } from "@/lib/utils";

export function AllTasksSheet() {
  const desk = useDispatchDesk();
  const { t } = useTranslation();
  const [filter, setFilter] = useState<DispatchStatus>("pending");
  const open = desk?.allTasksOpen ?? false;
  const latestStatus = desk?.tasks[0]?.status;
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open && !wasOpen.current) setFilter(latestStatus ?? "pending");
    wasOpen.current = open;
  }, [latestStatus, open]);

  if (!desk) return null;
  const visible = dispatchTasksByStatus(desk.tasks, filter);

  return (
    <Sheet open={open} onOpenChange={desk.setAllTasksOpen}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
        <div className="shrink-0 space-y-1 border-b px-5 py-5 pr-14">
          <SheetTitle>{t("dispatch.allTasks")}</SheetTitle>
          <SheetDescription>{t("dispatch.allTasksHint")}</SheetDescription>
        </div>
        <div
          role="group"
          aria-label={t("dispatch.allTasks")}
          className="flex shrink-0 flex-wrap gap-1 px-5 py-3"
        >
          {DISPATCH_STATUSES.map((status) => {
            const selected = filter === status;
            return (
              <button
                key={status}
                type="button"
                aria-pressed={selected}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium",
                  selected
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
                onClick={() => setFilter(status)}
              >
                {t(`dispatch.status.${status}`)}
              </button>
            );
          })}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {visible.length === 0 ? (
            <p className="px-2 py-6 text-sm text-muted-foreground">{t("dispatch.emptyFilter")}</p>
          ) : (
            <ul className="space-y-1">
              {visible.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    className="flex w-full items-start gap-2 rounded-control px-2 py-2 text-left hover:bg-accent"
                    onClick={() => desk.selectTask(task.id)}
                  >
                    <DispatchStatusDot status={task.status} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-foreground">{task.title}</span>
                      <span className="block text-xs text-muted-foreground">
                        {t(`dispatch.status.${task.status}`)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
