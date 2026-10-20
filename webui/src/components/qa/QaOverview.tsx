import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";

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
import { usePageVisibility } from "@/hooks/usePageVisibility";
import {
  createQaProject,
  deleteQaProject,
  loadQaOverview,
  qaErrorMessage,
  updateQaProject,
  type QaMutationTransport,
  type QaProject,
} from "@/lib/qa-api";
import { cn } from "@/lib/utils";

import type { QaTab } from "./QaWorkbench";
import {
  formatQaDuration,
  formatQaTime,
  QaEmptyState,
  QaErrorBar,
  QaLoading,
  QaPanel,
  QaRunStatusBadge,
  QaSectionTitle,
  QaStatCard,
  QaTableShell,
  QaTaskStatusBadge,
  QaTruncate,
  QA_TD_CLASS,
  QA_TH_CLASS,
  useQaCopy,
} from "./qa-ui";
import { useQaQuery } from "./useQaQuery";

export interface QaOverviewProps {
  token: string;
  client: QaMutationTransport;
  projects: QaProject[];
  projectsLoading: boolean;
  projectsError: string;
  onReloadProjects: () => void;
  pollIntervalMs: number;
  refreshSignal: number;
  onOpenTab: (tab: QaTab) => void;
}

export function QaOverview({
  token,
  client,
  projects,
  projectsLoading,
  projectsError,
  onReloadProjects,
  pollIntervalMs,
  refreshSignal,
  onOpenTab,
}: QaOverviewProps) {
  const tx = useQaCopy();
  const visible = usePageVisibility();
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [editingProject, setEditingProject] = useState<QaProject | null>(null);
  const [deletingProject, setDeletingProject] = useState<QaProject | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const overview = useQaQuery(
    () => loadQaOverview(token),
    [token, refreshSignal],
    { intervalMs: visible ? pollIntervalMs : 0 },
  );

  const confirmDeleteProject = async () => {
    if (!deletingProject || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      await deleteQaProject(client, deletingProject.id);
      setDeletingProject(null);
      onReloadProjects();
      overview.reload();
    } catch (reason) {
      setDeleteError(qaErrorMessage(reason));
    } finally {
      setDeleteBusy(false);
    }
  };

  const counts = overview.data?.counts;
  const projectRows = projects.length > 0 ? projects : (overview.data?.projects ?? []);
  const recentTasks = overview.data?.recent_tasks ?? [];
  const recentRuns = overview.data?.recent_runs ?? [];

  if (overview.loading && !overview.data) {
    return <QaLoading label={tx("qa.status.loading", "加载中…")} />;
  }

  return (
    <div className="flex flex-col gap-5" data-testid="qa-overview">
      {overview.error ? (
        <QaErrorBar
          message={`${tx("qa.error.overview", "加载概览失败")}: ${overview.error}`}
          onRetry={overview.reload}
          retryLabel={tx("qa.actions.retry", "重试")}
        />
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <QaStatCard
          testId="qa-count-projects"
          label={tx("qa.overview.projects", "项目")}
          value={counts?.projects ?? projectRows.length}
        />
        <QaStatCard
          testId="qa-count-cases"
          label={tx("qa.overview.cases", "用例")}
          value={counts?.cases ?? 0}
          hint={tx("qa.overview.readyCases", "就绪 {{count}}", { count: counts?.ready_cases ?? 0 })}
        />
        <QaStatCard
          testId="qa-count-scripts"
          label={tx("qa.overview.scripts", "脚本")}
          value={counts?.scripts ?? 0}
        />
        <QaStatCard
          testId="qa-count-runs"
          label={tx("qa.overview.runs", "运行")}
          value={counts?.runs ?? 0}
        />
        <QaStatCard
          testId="qa-count-active-tasks"
          label={tx("qa.overview.activeTasks", "进行中任务")}
          value={counts?.active_tasks ?? 0}
          hint={tx("qa.overview.totalTasks", "累计 {{count}}", { count: counts?.tasks ?? 0 })}
        />
      </div>

      <section>
        <QaSectionTitle
          title={tx("qa.overview.projectsTitle", "项目")}
          count={projectRows.length}
          action={
            <>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-[12px]"
                onClick={() => onOpenTab("cases")}
              >
                {tx("qa.overview.browseCases", "查看用例库")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 gap-1 px-2 text-[12px]"
                onClick={() => setProjectDialogOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {tx("qa.overview.projectCreate", "新建项目")}
              </Button>
            </>
          }
        />
        {projectRows.length === 0 ? (
          <QaEmptyState
            title={
              projectsError
                ? tx("qa.error.projects", "加载项目列表失败")
                : tx("qa.overview.noProjects", "还没有 QA 项目")
            }
            hint={
              projectsError
                ? projectsError
                : tx(
                    "qa.overview.noProjectsHint",
                    "让 QA Agent 初始化一个项目，或直接新建；项目是存放用例、脚本与运行记录的地方。",
                  )
            }
            action={
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={onReloadProjects}
                  disabled={projectsLoading}
                >
                  {tx("qa.actions.refresh", "刷新")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setProjectDialogOpen(true)}
                >
                  {tx("qa.overview.projectCreate", "新建项目")}
                </Button>
              </>
            }
          />
        ) : (
          <QaTableShell label={tx("qa.overview.projectsTitle", "项目")}>
            <thead>
              <tr>
                <th className={QA_TH_CLASS}>{tx("qa.overview.projectKey", "KEY")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.overview.projectName", "名称")}</th>
                <th className={QA_TH_CLASS}>{tx("qa.overview.baseUrl", "BASE URL")}</th>
                <th className={cn(QA_TH_CLASS, "text-right")}>
                  {tx("qa.overview.caseCount", "用例")}
                </th>
                <th className={cn(QA_TH_CLASS, "text-right")}>
                  {tx("qa.overview.readyCount", "就绪")}
                </th>
                <th className={cn(QA_TH_CLASS, "text-right")}>
                  {tx("qa.overview.activeTaskCount", "活跃任务")}
                </th>
                <th className={cn(QA_TH_CLASS, "text-right")}>
                  {tx("qa.overview.projectActions", "操作")}
                </th>
              </tr>
            </thead>
            <tbody>
              {projectRows.map((project) => (
                <tr key={project.id || project.key} className="hover:bg-muted/30">
                  <td className={cn(QA_TD_CLASS, "font-mono text-[12px] font-medium uppercase")}>
                    <QaTruncate text={project.key} className="max-w-[10rem]" />
                  </td>
                  <td className={QA_TD_CLASS}>
                    <QaTruncate
                      text={project.name || project.key}
                      className="max-w-[16rem] font-medium text-foreground"
                    />
                    {project.description ? (
                      <span
                        title={project.description}
                        className="mt-0.5 block max-w-[20rem] truncate text-[11px] text-muted-foreground"
                      >
                        {project.description}
                      </span>
                    ) : null}
                  </td>
                  <td className={cn(QA_TD_CLASS, "text-[12px] text-muted-foreground")}>
                    <QaTruncate text={project.base_url} className="max-w-[16rem] font-mono" />
                  </td>
                  <td className={cn(QA_TD_CLASS, "text-right tabular-nums")}>
                    {project.stats.cases}
                  </td>
                  <td className={cn(QA_TD_CLASS, "text-right tabular-nums text-muted-foreground")}>
                    {project.stats.ready_cases}
                  </td>
                  <td className={cn(QA_TD_CLASS, "text-right tabular-nums")}>
                    {project.stats.active_tasks > 0 ? (
                      <span className="font-medium text-blue-700 dark:text-blue-300">
                        {project.stats.active_tasks}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                  <td className={cn(QA_TD_CLASS, "text-right")}>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-7 gap-1 px-2 text-[12px]"
                      aria-label={`${tx("qa.overview.projectEdit", "编辑项目")} ${project.key}`}
                      data-testid="qa-project-edit"
                      onClick={() => setEditingProject(project)}
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                      {tx("qa.overview.projectEditShort", "编辑")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-7 gap-1 px-2 text-[12px] text-destructive"
                      aria-label={`${tx("qa.overview.projectDelete", "删除项目")} ${project.key}`}
                      data-testid="qa-project-delete"
                      onClick={() => setDeletingProject(project)}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      {tx("qa.overview.projectDeleteShort", "删除")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </QaTableShell>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section>
          <QaSectionTitle
            title={tx("qa.overview.recentTasks", "最近任务")}
            action={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[12px]"
                onClick={() => onOpenTab("tasks")}
              >
                {tx("qa.overview.viewAll", "查看全部")}
              </Button>
            }
          />
          <QaPanel>
            {recentTasks.length === 0 ? (
              <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">
                {tx("qa.tasks.empty", "暂无任务")}
              </p>
            ) : (
              <ul className="divide-y divide-border/40">
                {recentTasks.map((task) => (
                  <li key={task.id}>
                    <button
                      type="button"
                      onClick={() => onOpenTab("tasks")}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/30"
                    >
                      <QaTaskStatusBadge status={task.status} />
                      <span
                        title={task.title}
                        className="min-w-0 flex-1 truncate text-[13px] text-foreground"
                      >
                        {task.title}
                      </span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        {formatQaTime(task.updated_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QaPanel>
        </section>

        <section>
          <QaSectionTitle
            title={tx("qa.overview.recentRuns", "最近运行")}
            action={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[12px]"
                onClick={() => onOpenTab("runs")}
              >
                {tx("qa.overview.viewAll", "查看全部")}
              </Button>
            }
          />
          <QaPanel>
            {recentRuns.length === 0 ? (
              <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">
                {tx("qa.runs.empty", "暂无运行记录")}
              </p>
            ) : (
              <ul className="divide-y divide-border/40">
                {recentRuns.map((run) => (
                  <li key={run.id}>
                    <button
                      type="button"
                      onClick={() => onOpenTab("runs")}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/30"
                    >
                      <QaRunStatusBadge status={run.status} />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground">
                        {tx("qa.runs.counts", "通过 {{passed}} · 失败 {{failed}} · 错误 {{errors}}", {
                          passed: run.passed,
                          failed: run.failed,
                          errors: run.errors,
                        })}
                      </span>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {formatQaDuration(run.duration_ms)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </QaPanel>
        </section>
      </div>

      <QaProjectDialog
        client={client}
        open={projectDialogOpen}
        onOpenChange={setProjectDialogOpen}
        onSaved={onReloadProjects}
      />

      <Dialog
        open={deletingProject !== null}
        onOpenChange={(open) => {
          if (!open) setDeletingProject(null);
        }}
      >
        <DialogContent className="max-w-sm" data-testid="qa-project-delete-dialog">
          <DialogHeader>
            <DialogTitle>{tx("qa.overview.projectDelete", "删除项目")}</DialogTitle>
            <DialogDescription>
              {tx(
                "qa.overview.projectDeleteHint",
                "项目下的用例、脚本、运行记录、任务和定时任务会一并删除，且不可撤销。",
              )}
            </DialogDescription>
          </DialogHeader>
          {deleteError ? <QaErrorBar message={deleteError} /> : null}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDeletingProject(null)}
              disabled={deleteBusy}
            >
              {tx("qa.actions.cancel", "取消")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="qa-project-delete-confirm"
              disabled={deleteBusy}
              onClick={() => void confirmDeleteProject()}
            >
              {tx("qa.overview.projectDeleteConfirm", "确认删除")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <QaProjectDialog
        client={client}
        open={editingProject !== null}
        project={editingProject}
        onOpenChange={(open) => {
          if (!open) setEditingProject(null);
        }}
        onSaved={() => {
          setEditingProject(null);
          onReloadProjects();
          overview.reload();
        }}
      />
    </div>
  );
}

export function QaProjectDialog({
  client,
  open,
  onOpenChange,
  project = null,
  onSaved,
}: {
  client: QaMutationTransport;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pass a project to edit it; omit (or `null`) to create one. */
  project?: QaProject | null;
  onSaved: () => void;
}) {
  const tx = useQaCopy();
  const editing = project !== null;
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Re-seed on every open: the same component instance serves create and edit.
  useEffect(() => {
    if (!open) return;
    setKey(project?.key ?? "");
    setName(project?.name ?? "");
    setDescription(project?.description ?? "");
    setBaseUrl(project?.base_url ?? "");
    setRepoPath(project?.repo_path ?? "");
    setError("");
  }, [open, project]);

  const submit = async () => {
    if (!key.trim() || !name.trim() || busy) return;
    setBusy(true);
    setError("");
    const fields = {
      key: key.trim(),
      name: name.trim(),
      description: description.trim(),
      base_url: baseUrl.trim(),
      repo_path: repoPath.trim(),
    };
    try {
      if (project) {
        await updateQaProject(client, project.id, fields);
      } else {
        await createQaProject(client, fields);
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
      <DialogContent className="max-w-md" data-testid="qa-project-dialog">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? tx("qa.overview.projectEdit", "编辑项目")
              : tx("qa.overview.projectCreate", "新建项目")}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? tx(
                  "qa.overview.projectEditHint",
                  "修改 KEY 只影响之后生成的用例编号，已有用例编号保持不变。",
                )
              : tx("qa.overview.projectCreateHint", "KEY 用于用例编号前缀，例如 WEB-API-001。")}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 text-left">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              {tx("qa.overview.projectKey", "KEY")}
            </span>
            <Input
              value={key}
              aria-label={tx("qa.overview.projectKey", "KEY")}
              onChange={(event) => setKey(event.target.value)}
              disabled={busy}
              data-testid="qa-project-key"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              {tx("qa.overview.projectName", "名称")}
            </span>
            <Input
              value={name}
              aria-label={tx("qa.overview.projectName", "名称")}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
              data-testid="qa-project-name"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              {tx("qa.overview.projectDescription", "描述")}
            </span>
            <Input
              value={description}
              aria-label={tx("qa.overview.projectDescription", "描述")}
              onChange={(event) => setDescription(event.target.value)}
              disabled={busy}
              data-testid="qa-project-description"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              {tx("qa.overview.baseUrl", "BASE URL")}
            </span>
            <Input
              value={baseUrl}
              aria-label={tx("qa.overview.baseUrl", "BASE URL")}
              onChange={(event) => setBaseUrl(event.target.value)}
              disabled={busy}
              data-testid="qa-project-base-url"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
              {tx("qa.overview.repoPath", "仓库路径")}
            </span>
            <Input
              value={repoPath}
              aria-label={tx("qa.overview.repoPath", "仓库路径")}
              onChange={(event) => setRepoPath(event.target.value)}
              disabled={busy}
              data-testid="qa-project-repo-path"
            />
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
            disabled={busy || !key.trim() || !name.trim()}
            data-testid="qa-project-submit"
          >
            {tx("qa.actions.save", "保存")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
