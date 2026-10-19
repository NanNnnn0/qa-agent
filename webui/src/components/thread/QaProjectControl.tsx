
import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { QaProjectBinding } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface QaProjectControlProps {
  project: QaProjectBinding | null;
  projects: QaProjectBinding[] | null;
  onLoadProjects: () => Promise<QaProjectBinding[]>;
  onChange: (projectId: string | null) => void;
  disabled?: boolean;
}

/**
 * Composer control that explicitly binds this chat to a QA project.
 *
 * A binding makes the agent follow the QA workflow (cases into the case
 * library, scripts registered with qa_script). An unbound chat keeps the plain
 * assistant behaviour, and the workspace path never binds on its own.
 */
export function QaProjectControl({
  project,
  projects,
  onLoadProjects,
  onChange,
  disabled = false,
}: QaProjectControlProps) {
  const { t } = useTranslation();
  const options = projects ?? [];
  // A bound project missing from the loaded list (list not fetched yet) must
  // still render as the selected option instead of silently showing "unbound".
  const visible =
    project && !options.some((item) => item.id === project.id)
      ? [project, ...options]
      : options;
  return (
    <div
      className={cn(
        "inline-flex h-8 min-w-0 items-center gap-1 rounded-full border border-border/70 bg-background/70 px-2 text-[12px]",
        disabled && "pointer-events-none opacity-60",
      )}
      data-bound={project ? "true" : "false"}
      title={project ? `${project.key} · ${project.name}` : undefined}
    >
      <FlaskConical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <select
        aria-label={t("qa.chatProject.label", { defaultValue: "QA 项目" })}
        data-testid="qa-project-control"
        className="h-full min-w-0 max-w-[9rem] cursor-pointer appearance-none bg-transparent pr-0.5 text-[12px] text-foreground outline-none"
        value={project?.id ?? ""}
        disabled={disabled}
        onFocus={() => {
          void onLoadProjects();
        }}
        onPointerDown={() => {
          void onLoadProjects();
        }}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{t("qa.chatProject.none", { defaultValue: "未绑定 QA 项目" })}</option>
        {visible.map((item) => (
          <option key={item.id} value={item.id}>
            {item.key ? `${item.key} · ${item.name}` : item.name || item.id}
          </option>
        ))}
      </select>
    </div>
  );
}
