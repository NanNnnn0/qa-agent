import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, ListChecks, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { FilePreviewPanelView } from "@/components/FilePreviewPanelView";
import { DispatchStatusDot } from "@/components/dispatch/DispatchStatusDot";
import { useDispatchDesk } from "@/components/dispatch/dispatch-desk-context";
import { Button } from "@/components/ui/button";
import type { DispatchArtifact, DispatchTask } from "@/lib/dispatch-desk";
import type { FilePreviewPayload } from "@/lib/types";

function artifactPayload(artifact: DispatchArtifact): FilePreviewPayload {
  return {
    path: artifact.fileName,
    display_path: artifact.fileName,
    project_path: "",
    size: new TextEncoder().encode(artifact.content).length,
    language: artifact.language,
    content: artifact.content,
    truncated: false,
  };
}

export function DispatchHomeExtras({
  disabled,
  onDispatch,
  children,
}: {
  disabled?: boolean;
  onDispatch: (prompt: string) => void;
  children?: ReactNode;
}) {
  const desk = useDispatchDesk();
  const { t } = useTranslation();
  if (!desk) return children ?? null;
  const prompt = t("dispatch.checklistPrompt");
  return (
    <div className="flex w-full max-w-[40rem] flex-col items-center gap-5">
      {children ?? (
        <h2 className="select-none text-[32px] font-normal leading-tight tracking-normal text-foreground">
          {t("dispatch.homeTitle")}
        </h2>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="rounded-full"
        disabled={disabled}
        onClick={() => onDispatch(prompt)}
      >
        <ListChecks className="mr-2 h-3.5 w-3.5" aria-hidden />
        {t("dispatch.templateChecklist")}
      </Button>
    </div>
  );
}

export function DispatchTaskView({
  task,
  onOpenArtifact,
  variant = "inline",
}: {
  task: DispatchTask;
  onOpenArtifact: (artifactId: string) => void;
  variant?: "inline" | "sticky";
}) {
  const desk = useDispatchDesk();
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (variant === "sticky") {
    return (
      <div
        data-testid="dispatch-task-view"
        data-variant="sticky"
        className="pointer-events-auto w-full overflow-hidden rounded-xl border border-amber-200/50 bg-amber-50/60 text-left shadow-sm backdrop-blur dark:border-amber-400/15 dark:bg-amber-500/[0.06]"
      >
        <button
          type="button"
          aria-expanded={expanded}
          data-testid="dispatch-sticky-toggle"
          onClick={() => setExpanded((current) => !current)}
          className="flex w-full items-center gap-2 px-3 py-2"
        >
          <DispatchStatusDot status={task.status} />
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">
            {task.title}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground">
            {t(`dispatch.status.${task.status}`)}
          </span>
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          )}
        </button>
        {expanded ? (
          <div className="max-h-64 overflow-y-auto border-t border-amber-300/40 px-3 py-2">
            <p className="text-[11.5px] text-muted-foreground">
              {t(`dispatch.progress.${task.status}`)}
            </p>
            <ul className="mt-2 space-y-1.5">
              {task.artifacts.map((artifact) => (
                <li
                  key={artifact.id}
                  className="flex items-start gap-2 rounded-md border border-border/60 bg-card/70 px-2 py-1.5"
                >
                  <ListChecks className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12px] font-medium text-foreground">
                      {artifact.title}
                    </div>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {artifact.summary}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 shrink-0 px-1.5 text-[11px]"
                    aria-label={t("dispatch.openArtifact", { title: artifact.title })}
                    onClick={() => onOpenArtifact(artifact.id)}
                  >
                    {t("dispatch.open")}
                  </Button>
                </li>
              ))}
            </ul>
            {!task.sessionKey && desk ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-2 h-6 px-1.5 text-[11px]"
                onClick={desk.clearFocus}
              >
                {t("dispatch.back")}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="px-3 pb-2 text-[11px] text-muted-foreground">
            {t("dispatch.artifacts")} · {task.artifacts.length}
          </p>
        )}
      </div>
    );
  }
  return (
    <div data-testid="dispatch-task-view" className="flex w-full max-w-[40rem] flex-col items-stretch gap-4 text-left">
      <div className="flex items-center gap-2">
        <DispatchStatusDot status={task.status} />
        <h2 className="min-w-0 flex-1 truncate text-base font-medium text-foreground">{task.title}</h2>
        <span className="text-sm text-muted-foreground">{t(`dispatch.status.${task.status}`)}</span>
      </div>
      <p className="text-sm text-muted-foreground">{t(`dispatch.progress.${task.status}`)}</p>
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">{t("dispatch.artifacts")}</h3>
        <ul className="space-y-2">
          {task.artifacts.map((artifact) => (
            <li
              key={artifact.id}
              className="flex items-start gap-3 rounded-control border border-border bg-card px-3 py-3"
            >
              <ListChecks className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">{artifact.title}</div>
                <p className="text-sm text-muted-foreground">{artifact.summary}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t("dispatch.localBadge")}</p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label={t("dispatch.openArtifact", { title: artifact.title })}
                onClick={() => onOpenArtifact(artifact.id)}
              >
                {t("dispatch.open")}
              </Button>
            </li>
          ))}
        </ul>
      </div>
      {!task.sessionKey && desk ? (
        <Button type="button" variant="ghost" size="sm" className="self-start" onClick={desk.clearFocus}>
          {t("dispatch.back")}
        </Button>
      ) : null}
    </div>
  );
}

export function DispatchArtifactPreview({
  artifact,
  onClose,
}: {
  artifact: DispatchArtifact;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [imageOpen, setImageOpen] = useState(false);
  return (
    <aside
      data-testid="dispatch-artifact-preview"
      className="absolute inset-y-0 right-0 z-30 flex w-[min(32rem,100%)] flex-col border-l border-border/60 bg-background"
    >
      <div className="flex shrink-0 items-start gap-2 border-b border-border/40 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">{artifact.title}</p>
          <p className="text-xs text-muted-foreground">{t("dispatch.localHelp")}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("dispatch.previewClose")}
          onClick={onClose}
        >
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </div>
      <FilePreviewPanelView
        path={artifact.fileName}
        state={{ status: "ready", payload: artifactPayload(artifact) }}
        imageOpen={imageOpen}
        onImageOpenChange={setImageOpen}
        onImageError={() => {}}
      />
    </aside>
  );
}
