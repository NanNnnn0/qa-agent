import { ListChecks } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DispatchStatusDot } from "@/components/dispatch/DispatchStatusDot";
import { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";
import { Button } from "@/components/ui/button";
import { activeDispatchTasks } from "@/lib/dispatch-desk";
import { cn } from "@/lib/utils";

const rowClass = "flex min-h-8 w-full min-w-0 items-center gap-2 rounded-control px-2 text-left text-[13px] leading-5";

export function DispatchRail({
  activeKey,
  homeActive = false,
}: {
  activeKey: string | null;
  homeActive?: boolean;
}) {
  const desk = useDispatchDesk();
  const { t } = useTranslation();
  if (!desk) return null;

  const active = activeDispatchTasks(desk.tasks);
  const dispatcherActive = homeActive && desk.focusedTaskId === null;

  return (
    <section aria-label={t("dispatch.railLabel")} className="shrink-0 px-2 pb-2">
      <button
        type="button"
        className={cn(
          rowClass,
          dispatcherActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground"
            : "text-sidebar-content media-hover:hover:bg-sidebar-accent/60",
        )}
        onClick={desk.selectDispatcher}
      >
        <ListChecks className="h-4 w-4 shrink-0" aria-hidden />
        <span className="truncate font-medium">{t("dispatch.dispatcher")}</span>
      </button>
      {active.length === 0 ? (
        <p className="px-2 py-1 text-xs text-sidebar-muted-foreground">{t("dispatch.activeEmpty")}</p>
      ) : (
        <ul className="mt-0.5 space-y-0.5 ps-4">
          {active.map((task) => {
            const selected = task.sessionKey !== null && task.sessionKey === activeKey;
            return (
              <li key={task.id}>
                <button
                  type="button"
                  className={cn(
                    rowClass,
                    selected
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-content media-hover:hover:bg-sidebar-accent/60",
                  )}
                  aria-current={selected ? "page" : undefined}
                  onClick={() => desk.selectTask(task.id)}
                >
                  <DispatchStatusDot status={task.status} />
                  <span className="min-w-0 flex-1 truncate">{task.title}</span>
                  <span className="sr-only">{t(`dispatch.status.${task.status}`)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="mt-1 h-8 w-full justify-start px-2 text-sidebar-muted-foreground"
        onClick={() => desk.setAllTasksOpen(true)}
      >
        {t("dispatch.allTasks")}
      </Button>
    </section>
  );
}
