import { useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ChevronRight, type LucideIcon } from "lucide-react";

import { StreamingLabelSheen } from "@/components/ui/streaming-label-sheen";
import { formControlFocusClassName } from "@/components/ui/form-control";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ActivityStepTone = "neutral" | "active" | "success" | "error";

export interface ActivityStepProps {
  icon?: LucideIcon;
  marker?: ReactNode;
  showMarker?: boolean;
  label: ReactNode;
  detail?: string;
  detailClassName?: string;
  tooltipContent?: ReactNode;
  ariaLabel?: string;
  active?: boolean;
  animateLabel?: boolean;
  tone?: ActivityStepTone;
  className?: string;
  contentClassName?: string;
  labelClassName?: string;
  markerClassName?: string;
  style?: CSSProperties;
  /** Expandable payload rendered under the row: tool arguments, output, errors. */
  details?: ReactNode;
}

export function ActivityStep({
  icon: Icon,
  marker,
  showMarker = true,
  label,
  detail,
  detailClassName,
  tooltipContent,
  ariaLabel,
  active = false,
  animateLabel = true,
  tone = active ? "active" : "neutral",
  className,
  contentClassName,
  labelClassName,
  markerClassName,
  style,
  details,
}: ActivityStepProps) {
  const lineRef = useRef<HTMLElement | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const expandable = details !== undefined && details !== null;
  const textLabel = typeof label === "string" ? [label, detail].filter(Boolean).join("\n") : undefined;
  const lineClassName = cn(
    "flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap",
    formControlFocusClassName,
  );
  const lineContent = (
    <>
      <span className={cn("flex min-w-0 flex-1 items-baseline", detail && "gap-2")}>
        <StreamingLabelSheen
          active={active && animateLabel}
          className={cn(
            "min-w-0 truncate font-medium",
            detail ? "max-w-[70%] shrink-0" : "flex-1",
            tone === "error" ? "text-destructive/[0.78]" : "text-muted-foreground",
            labelClassName,
          )}
        >
          {label}
        </StreamingLabelSheen>
        {detail ? (
          <>
            {" "}
            <span className={cn("min-w-0 flex-1 truncate font-normal text-muted-foreground", detailClassName)}>{detail}</span>
          </>
        ) : null}
      </span>
      {expandable ? (
        <ChevronRight
          aria-hidden
          strokeWidth={2}
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground/40 transition-transform duration-150",
            detailsOpen && "rotate-90",
          )}
        />
      ) : null}
    </>
  );
  const line = expandable ? (
    <button
      ref={(node) => { lineRef.current = node; }}
      type="button"
      data-testid="activity-line"
      aria-expanded={detailsOpen}
      aria-controls={detailsId}
      aria-label={detail && typeof label === "string" ? `${label}, ${detail}` : undefined}
      onClick={() => setDetailsOpen((open) => !open)}
      className={cn(
        lineClassName,
        "-mx-1 w-[calc(100%+0.5rem)] rounded-md px-1 text-left",
        "media-hover:hover:bg-muted/50",
      )}
    >
      {lineContent}
    </button>
  ) : (
    <div
      ref={(node) => { lineRef.current = node; }}
      data-testid="activity-line"
      tabIndex={typeof label === "string" ? 0 : undefined}
      aria-label={detail && typeof label === "string" ? `${label}, ${detail}` : undefined}
      className={lineClassName}
    >
      {lineContent}
    </div>
  );

  return (
    <div
      data-testid="activity-step"
      aria-label={ariaLabel}
      className={cn(
        "relative grid min-w-0 py-0.5 text-[13px] leading-5",
        showMarker ? "grid-cols-[1.125rem_minmax(0,1fr)] gap-2" : "grid-cols-1",
        className,
      )}
      style={style}
    >
      {showMarker ? (
        <span
          className={cn(
            "flex h-5 w-[1.125rem] shrink-0 items-start justify-center pt-[3px]",
          )}
          aria-hidden
        >
          {marker ?? (
            <span
              className={cn(
                "grid h-3.5 w-3.5 place-items-center transition-colors",
                tone === "error" ? "text-destructive/[0.78]" : "text-muted-foreground",
                markerClassName,
              )}
            >
              {Icon ? <Icon className="h-3.5 w-3.5" strokeWidth={1.75} /> : null}
            </span>
          )}
        </span>
      ) : null}
      <div className={cn("min-w-0", contentClassName)}>
        {typeof label === "string" ? (
          <TooltipProvider>
            <Tooltip open={hintOpen} onOpenChange={(open) => {
              const truncated = Array.from(lineRef.current?.querySelectorAll<HTMLElement>(".truncate") ?? [])
                .some((element) => element.scrollWidth > element.clientWidth);
              setHintOpen(open && (truncated || tooltipContent !== undefined && tooltipContent !== textLabel));
            }}>
              <TooltipTrigger asChild>{line}</TooltipTrigger>
              <TooltipContent side="top" className="max-w-[min(32rem,calc(100vw-2rem))] whitespace-pre-wrap break-words">
                {tooltipContent ?? textLabel}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : line}
        {expandable && detailsOpen ? (
          <div id={detailsId} className="min-w-0">
            {details}
          </div>
        ) : null}
      </div>
    </div>
  );
}
