import { Brain, Check } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  floatingItemClassName,
  floatingItemFocusClassName,
} from "@/components/ui/floating-surface";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatReasoningEffort } from "@/lib/reasoning-effort";
import { cn } from "@/lib/utils";

/**
 * Levels offered by the composer control.
 *
 * ``default`` is not a provider token: it tells the backend to clear the
 * per-session override. The remaining values are sent verbatim.
 */
const REASONING_EFFORT_OPTIONS = [
  { value: "default", labelKey: "thinkingDefault" },
  { value: "none", labelKey: null },
  { value: "low", labelKey: null },
  { value: "medium", labelKey: null },
  { value: "high", labelKey: null },
  { value: "xhigh", labelKey: null },
] as const;

export interface ReasoningEffortMenuProps {
  /** Per-session reasoning effort; ``null``/empty means the provider default. */
  value: string | null;
  /** Receives the raw token, or ``"default"`` to clear the override. */
  onChange: (value: string) => void;
  disabled?: boolean;
}

function normalize(value: string | null | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

export function ReasoningEffortMenu({
  value,
  onChange,
  disabled = false,
}: ReasoningEffortMenuProps) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const current = normalize(value);
  const isDefault = current === "" || current === "default";
  const thinkingLabel = t("thread.composer.thinking", {
    defaultValue: "Thinking effort",
  });
  const defaultLabel = t("thread.composer.thinkingDefault", {
    defaultValue: "Default",
  });
  const hint = t("thread.composer.thinkingHint", {
    defaultValue: "Reasoning effort for this chat",
  });
  const currentLabel = isDefault
    ? defaultLabel
    : formatReasoningEffort(current, i18n.language);
  const optionLabel = (option: (typeof REASONING_EFFORT_OPTIONS)[number]) =>
    option.labelKey === "thinkingDefault"
      ? defaultLabel
      : formatReasoningEffort(option.value, i18n.language);
  const isSelected = (option: (typeof REASONING_EFFORT_OPTIONS)[number]) =>
    option.value === "default" ? isDefault : current === option.value;

  const select = (next: string) => {
    setOpen(false);
    onChange(next);
  };

  return (
    <Popover
      open={open && !disabled}
      onOpenChange={(next) => {
        if (disabled) return;
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="reasoning-effort-menu"
          aria-label={`${thinkingLabel}: ${currentLabel}`}
          aria-haspopup="listbox"
          aria-expanded={open && !disabled}
          title={hint}
          disabled={disabled}
          className={cn(
            "thread-composer-reasoning-effort inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-border/55 bg-card px-2.5",
            "text-[12px] font-medium text-foreground/70 transition-colors duration-150",
            "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45",
            "disabled:pointer-events-none disabled:opacity-50 motion-reduce:transition-none",
          )}
        >
          <Brain className="h-3.5 w-3.5 shrink-0" aria-hidden strokeWidth={1.75} />
          <span className="max-w-[7rem] truncate whitespace-nowrap">{currentLabel}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="top"
        sideOffset={10}
        collisionPadding={12}
        role="dialog"
        aria-label={hint}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          const content = event.currentTarget;
          if (!(content instanceof HTMLElement)) return;
          content
            .querySelector<HTMLElement>('[role="option"][aria-selected="true"]')
            ?.focus();
        }}
        className={cn(
          "w-[min(13rem,calc(100vw-2rem))] p-1.5",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-bottom-1 data-[state=open]:slide-in-from-bottom-1 duration-200 ease-out motion-reduce:animate-none",
        )}
      >
        <div role="listbox" aria-label={hint} className="py-1">
          {REASONING_EFFORT_OPTIONS.map((option) => {
            const selected = isSelected(option);
            const label = optionLabel(option);
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-label={label}
                aria-selected={selected}
                data-value={option.value}
                onClick={() => select(option.value)}
                className={cn(
                  floatingItemClassName,
                  floatingItemFocusClassName,
                  "flex min-h-9 w-full cursor-pointer items-center justify-between gap-2.5 px-2.5 py-1.5 text-left hover:bg-muted/55 max-sm:min-h-11",
                  selected && "bg-muted/55 text-foreground",
                )}
              >
                <span className="truncate text-[13px] font-medium text-foreground">
                  {label}
                </span>
                {selected ? (
                  <Check className="h-4 w-4 shrink-0 text-foreground/80" aria-hidden />
                ) : null}
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
