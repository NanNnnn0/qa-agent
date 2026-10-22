import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  MAX_DETAIL_CHARS,
  formatToolDetailValue,
  isToolCallDetailEntryVisible,
  type ToolCallDetailEntry,
} from "@/components/thread/activity/tool-detail-model";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

/**
 * Expanded payload for one activity row: what the agent actually called and
 * what came back. Rendered under the row so the timeline keeps its shape.
 */
export function ToolCallDetail({ entries }: { entries: ToolCallDetailEntry[] }) {
  const visible = entries.filter(isToolCallDetailEntryVisible);
  if (!visible.length) return null;
  return (
    <div
      data-testid="activity-tool-detail"
      className="my-1 flex min-w-0 flex-col gap-2 border-s border-border/60 ps-2.5"
    >
      {visible.map((entry, index) => (
        <ToolCallDetailEntryView
          key={`${entry.name}:${index}`}
          entry={entry}
          showHeader={visible.length > 1}
        />
      ))}
    </div>
  );
}

function ToolCallDetailEntryView({
  entry,
  showHeader,
}: {
  entry: ToolCallDetailEntry;
  showHeader: boolean;
}) {
  const { t } = useTranslation();
  const command = entry.command ?? "";
  const argsText = formatToolDetailValue(entry.arguments);
  const resultText = formatToolDetailValue(entry.result);
  const errorText = formatToolDetailValue(entry.error);
  return (
    <div data-testid="activity-tool-detail-entry" className="flex min-w-0 flex-col gap-1.5">
      {showHeader ? (
        <span className="truncate font-mono text-[11px] text-muted-foreground/80">{entry.name}</span>
      ) : null}
      {command ? <DetailSection label={t("message.toolDetail.command")} text={command} /> : null}
      {argsText ? <DetailSection label={t("message.toolDetail.arguments")} text={argsText} /> : null}
      {resultText ? <DetailSection label={t("message.toolDetail.result")} text={resultText} /> : null}
      {errorText ? <DetailSection label={t("message.toolDetail.error")} text={errorText} tone="error" /> : null}
    </div>
  );
}

function DetailSection({
  label,
  text,
  tone = "default",
}: {
  label: string;
  text: string;
  tone?: "default" | "error";
}) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const [copied, setCopied] = useState(false);
  const clipped = !showAll && text.length > MAX_DETAIL_CHARS;
  const shown = clipped ? text.slice(0, MAX_DETAIL_CHARS) : text;
  const copy = () => {
    void copyTextToClipboard(text).then((ok) => {
      if (!ok) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_500);
    });
  };
  return (
    <section className="min-w-0">
      <div className="mb-1 flex items-center gap-1.5">
        <span
          className={cn(
            "text-[11px] font-medium",
            tone === "error" ? "text-destructive/80" : "text-muted-foreground",
          )}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? t("message.toolDetail.copied") : t("message.toolDetail.copy")}
          className={cn(
            "grid h-4 w-4 place-items-center rounded text-muted-foreground/60 transition-colors",
            "media-hover:hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          {copied
            ? <Check className="h-3 w-3" strokeWidth={2} aria-hidden />
            : <Copy className="h-3 w-3" strokeWidth={1.8} aria-hidden />}
        </button>
      </div>
      <pre
        data-testid="activity-tool-detail-text"
        className={cn(
          "max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border/50 bg-muted/30 px-2 py-1.5 font-mono text-[11.5px] leading-[1.55]",
          tone === "error" ? "text-destructive/90" : "text-foreground/85",
        )}
      >
        {shown}
        {clipped ? "…" : ""}
      </pre>
      {text.length > MAX_DETAIL_CHARS ? (
        <button
          type="button"
          aria-expanded={showAll}
          onClick={() => setShowAll((open) => !open)}
          className={cn(
            "mt-1 rounded text-[11px] font-medium text-muted-foreground",
            "media-hover:hover:text-foreground",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          {showAll ? t("message.toolDetail.showLess") : t("message.toolDetail.showAll")}
        </button>
      ) : null}
    </section>
  );
}
