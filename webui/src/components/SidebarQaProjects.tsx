
import { useTranslation } from "react-i18next";

export interface SidebarQaProject {
  id: string;
  key: string;
  name: string;
  repo_path?: string;
}

/**
 * QA projects shown in the conversation sidebar even before any chat exists.
 * Clicking one starts a new chat bound to that project (and its workspace).
 */
export function SidebarQaProjects({
  projects,
  onOpen,
}: {
  projects: SidebarQaProject[];
  onOpen: (projectId: string) => void;
}) {
  const { t } = useTranslation();
  if (projects.length === 0) return null;
  return (
    <div className="px-2 pb-1" data-testid="sidebar-qa-projects">
      <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-sidebar-content/60">
        {t("sidebar.qaProjects", { defaultValue: "QA 项目" })}
      </p>
      <div className="flex flex-col gap-0.5">
        {projects.map((project) => (
          <button
            key={project.id}
            type="button"
            data-testid={`sidebar-qa-project-${project.id}`}
            onClick={() => onOpen(project.id)}
            title={project.repo_path ? `${project.key} · ${project.repo_path}` : project.key}
            className="flex w-full min-w-0 items-center gap-2 rounded-control px-2 py-1.5 text-left text-[13px] text-sidebar-content hover:bg-foreground/[0.055]"
          >
            <span className="min-w-0 flex-1 truncate">{project.key || project.name}</span>
            <span className="shrink-0 text-[11px] text-sidebar-content/50">
              {t("sidebar.qaProjectNewChat", { defaultValue: "新建对话" })}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
