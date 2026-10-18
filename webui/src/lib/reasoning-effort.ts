/**
 * Display labels for provider reasoning-effort values.
 *
 * The value sent to the backend must stay the provider's own token
 * (`low`, `high`, `none`, …); only the human-facing label is localized.
 * We keep the maps here instead of the locale bundles because the i18n test
 * requires every locale to carry the same key set, and these seven labels are
 * not worth duplicating into ten files.
 */

const ZH_LABELS: Record<string, string> = {
  none: "关闭",
  minimal: "极低",
  low: "低",
  medium: "中",
  high: "高",
  xhigh: "极高",
  ultra: "极高",
  max: "最高",
};

const EN_LABELS: Record<string, string> = {
  none: "None",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  ultra: "Ultra",
  max: "Max",
};

export function formatReasoningEffort(value: string, language?: string): string {
  if (!value) return "";
  const key = value.trim().toLowerCase();
  const isChinese = (language ?? "").toLowerCase().startsWith("zh");
  const labels = isChinese ? ZH_LABELS : EN_LABELS;
  return labels[key] ?? value;
}
