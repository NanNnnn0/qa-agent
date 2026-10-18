import { useCallback, useState } from "react";
import { ChevronLeft, FlaskConical, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { usePageVisibility } from "@/hooks/usePageVisibility";
import { loadQaProjects, type QaMutationTransport } from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import { QaCaseLibrary } from "./QaCaseLibrary";
import { QaOverview } from "./QaOverview";
import { QaRuns } from "./QaRuns";
import { QaScripts } from "./QaScripts";
import { QaTaskBoard } from "./QaTaskBoard";
import { QaErrorBar, useQaCopy } from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

export type QaTab = "overview" | "tasks" | "cases" | "scripts" | "runs";

const QA_TABS: QaTab[] = ["overview", "tasks", "cases", "scripts", "runs"];

/** Visible list polling cadence; tests pass `pollIntervalMs={0}`. */
export const QA_POLL_INTERVAL_MS = 3_000;

export interface QaWorkbenchProps {
  token: string;
  client: QaMutationTransport;
  onBackToChat: () => void;
  initialTab?: QaTab;
  pollIntervalMs?: number;
}

export function QaWorkbench({
  token,
  client,
  onBackToChat,
  initialTab = "overview",
  pollIntervalMs = QA_POLL_INTERVAL_MS,
}: QaWorkbenchProps) {
  const tx = useQaCopy();
  const [tab, setTab] = useState<QaTab>(initialTab);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const visible = usePageVisibility();

  const projectsQuery = useQaQuery(
    () => loadQaProjects(token),
    [token, refreshSignal],
    {
      // Project stats are only shown on the overview; poll there only.
      intervalMs: visible && tab === "overview" ? pollIntervalMs : 0,
    },
  );
  const projects = projectsQuery.data ?? [];

  const refresh = useCallback(() => setRefreshSignal((current) => current + 1), []);

  const labels: Record<QaTab, string> = {
    overview: tx("qa.tabs.overview", "概览"),
    tasks: tx("qa.tabs.tasks", "任务板"),
    cases: tx("qa.tabs.cases", "用例库"),
    scripts: tx("qa.tabs.scripts", "自动化"),
    runs: tx("qa.tabs.runs", "运行记录"),
  };

  return (
    <div data-testid="qa-workbench" className="flex h-full min-h-0 w-full flex-col bg-background">
      <header className="flex-none border-b border-border/60 bg-background/95">
        <div className="mx-auto w-full max-w-[1200px] px-4 pt-3 sm:px-6 sm:pt-4">
          <button
            type="button"
            onClick={onBackToChat}
            data-testid="qa-back"
            className="touch-target mb-2 inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            {tx("qa.backToChat", "返回对话")}
          </button>

          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="flex min-w-0 items-center gap-2 text-[22px] font-semibold leading-tight tracking-[-0.01em] text-foreground">
                <FlaskConical className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden />
                <span className="truncate">{tx("qa.title", "QA 工作台")}</span>
              </h1>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
                {tx("qa.subtitle", "用例、自动化脚本、执行与 Agent 任务的统一入口。")}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 shrink-0 gap-1.5 px-2.5"
              onClick={refresh}
              disabled={projectsQuery.loading && projects.length === 0}
              aria-label={tx("qa.actions.refresh", "刷新")}
              data-testid="qa-refresh"
            >
              <RefreshCw
                className={cn(
                  "h-3.5 w-3.5",
                  projectsQuery.loading && "animate-spin motion-reduce:animate-none",
                )}
                aria-hidden
              />
              {tx("qa.actions.refresh", "刷新")}
            </Button>
          </div>

          <nav
            role="tablist"
            aria-label={tx("qa.tabsLabel", "QA 工作台标签页")}
            className="mt-3 flex gap-1 overflow-x-auto border-b border-transparent pb-0"
          >
            {QA_TABS.map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`qa-tab-${id}`}
                aria-selected={tab === id}
                aria-controls="qa-tabpanel"
                data-testid={`qa-tab-${id}`}
                onClick={() => setTab(id)}
                className={cn(
                  "relative -mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
                  tab === id
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
                )}
              >
                {labels[id]}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-[1200px] px-4 py-4 sm:px-6 sm:py-5">
          {projectsQuery.error && projects.length === 0 ? (
            <div className="mb-4">
              <QaErrorBar
                message={`${tx("qa.error.projects", "加载项目列表失败")}: ${projectsQuery.error}`}
                onRetry={projectsQuery.reload}
                retryLabel={tx("qa.actions.retry", "重试")}
              />
            </div>
          ) : null}

          <div role="tabpanel" id="qa-tabpanel" aria-labelledby={`qa-tab-${tab}`}>
            {tab === "overview" ? (
              <QaOverview
                token={token}
                client={client}
                projects={projects}
                projectsLoading={projectsQuery.loading}
                projectsError={projects.length === 0 ? projectsQuery.error : ""}
                onReloadProjects={projectsQuery.reload}
                pollIntervalMs={pollIntervalMs}
                refreshSignal={refreshSignal}
                onOpenTab={setTab}
              />
            ) : null}
            {tab === "tasks" ? (
              <QaTaskBoard
                token={token}
                client={client}
                projects={projects}
                pollIntervalMs={pollIntervalMs}
                refreshSignal={refreshSignal}
                onChanged={refresh}
              />
            ) : null}
            {tab === "cases" ? (
              <QaCaseLibrary
                token={token}
                client={client}
                projects={projects}
                refreshSignal={refreshSignal}
                onChanged={refresh}
              />
            ) : null}
            {tab === "scripts" ? (
              <QaScripts
                token={token}
                client={client}
                projects={projects}
                refreshSignal={refreshSignal}
                onChanged={refresh}
              />
            ) : null}
            {tab === "runs" ? (
              <QaRuns
                token={token}
                client={client}
                projects={projects}
                pollIntervalMs={pollIntervalMs}
                refreshSignal={refreshSignal}
              />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
