import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { DispatchStatusDot } from "@/components/dispatch/DispatchStatusDot";
import { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  DISPATCH_STATUSES,
  archivedDispatchTasks,
  dispatchTasksByStatus,
  isArchivedDispatchTask,
  type DispatchStatus,
} from "@/lib/dispatch-desk";
import { cn } from "@/lib/utils";

type DispatchScope = "all" | "archived";

const chipClass = (selected: boolean) => cn(
  "rounded-full px-3 py-1 text-xs font-medium",
  selected
    ? "bg-muted text-foreground"
    : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
);

export function AllTasksSheet() {
  const desk = useDispatchDesk();
  const { t } = useTranslation();
  const [filter, setFilter] = useState<DispatchStatus>("pending");
  const [scope, setScope] = useState<DispatchScope>("all");
  const open = desk?.allTasksOpen ?? false;
  const latestStatus = desk?.tasks[0]?.status;
  const wasOpen = useRef(false);

  useEffect(() => {
    if (open && !wasOpen.current) {
      setFilter(latestStatus ?? "pending");
      setScope("all");
    }
    wasOpen.current = open;
  }, [latestStatus, open]);

  if (!desk) return null;
  // 全部 keeps every task, archived ones included; 已归档 is the restore view.
  const visible = scope === "archived"
    ? archivedDispatchTasks(desk.tasks)
    : dispatchTasksByStatus(desk.tasks, filter);
  const scopeOptions: { value: DispatchScope; label: string }[] = [
    { value: "all", label: t("dispatch.filterAll", { defaultValue: "全部" }) },
    { value: "archived", label: t("dispatch.filterArchived", { defaultValue: "已归档" }) },
  ];

  return (
    <Sheet open={open} onOpenChange={desk.setAllTasksOpen}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-md">
        <div className="shrink-0 space-y-1 border-b px-5 py-5 pr-14">
          <SheetTitle>{t("dispatch.allTasks")}</SheetTitle>
          <SheetDescription>{t("dispatch.allTasksHint")}</SheetDescription>
        </div>
        <div
          role="group"
          aria-label={t("dispatch.viewFilter", { defaultValue: "视图" })}
          className="flex shrink-0 flex-wrap gap-1 px-5 pt-3"
        >
          {scopeOptions.map((option) => {
            const selected = scope === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={selected}
                className={chipClass(selected)}
                onClick={() => setScope(option.value)}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        {scope === "all" ? (
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
                  className={chipClass(selected)}
                  onClick={() => setFilter(status)}
                >
                  {t(`dispatch.status.${status}`)}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="shrink-0 pb-3" />
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {visible.length === 0 ? (
            <p className="px-2 py-6 text-sm text-muted-foreground">{t("dispatch.emptyFilter")}</p>
          ) : (
            <ul className="space-y-1">
              {visible.map((task) => {
                const archived = isArchivedDispatchTask(task);
                return (
                  <li
                    key={task.id}
                    className="flex min-w-0 items-center gap-1 rounded-control hover:bg-accent"
                  >
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-start gap-2 px-2 py-2 text-left"
                      onClick={() => desk.selectTask(task.id)}
                    >
                      <DispatchStatusDot status={task.status} />
                      <span className="min-w-0 flex-1">
                        <span className="flex min-w-0 items-center gap-1.5">
                          <span className="truncate text-sm text-foreground">{task.title}</span>
                          {archived ? (
                            <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium leading-4 text-muted-foreground">
                              {t("dispatch.archived", { defaultValue: "已归档" })}
                            </span>
                          ) : null}
                        </span>
                        {archived ? null : (
                          <span className="block text-xs text-muted-foreground">
                            {t(`dispatch.status.${task.status}`)}
                          </span>
                        )}
                      </span>
                    </button>
                    {archived ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="me-1 h-7 shrink-0 px-2 text-xs"
                        onClick={() => desk.restoreTask(task.id)}
                      >
                        {t("dispatch.restore", { defaultValue: "恢复" })}
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
