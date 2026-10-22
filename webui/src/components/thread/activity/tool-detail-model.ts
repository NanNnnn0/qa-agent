import { redactActivityText, redactShellCommand } from "./activity-text";

/** One tool invocation prepared for the expandable activity detail panel. */
export interface ToolCallDetailEntry {
  name: string;
  /** Verbatim shell/CLI command; rendered instead of the argument JSON. */
  command?: string;
  arguments?: unknown;
  result?: unknown;
  error?: unknown;
}

/** Long outputs stay scrollable; past this length the panel offers "show all". */
export const MAX_DETAIL_CHARS = 4_000;

export function buildToolCallDetailEntry(
  name: string,
  args: unknown,
  result?: unknown,
  error?: unknown,
): ToolCallDetailEntry {
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const record = args as Record<string, unknown>;
    const command = record.command;
    if (typeof command === "string" && command.trim()) {
      const rest: Record<string, unknown> = { ...record };
      delete rest.command;
      return {
        name,
        command: redactShellCommand(command),
        arguments: Object.keys(rest).length ? rest : undefined,
        result,
        error,
      };
    }
  }
  return { name, arguments: args, result, error };
}

export function isToolCallDetailEntryVisible(entry: ToolCallDetailEntry): boolean {
  return Boolean(entry.command)
    || hasDetailValue(entry.arguments)
    || hasDetailValue(entry.result)
    || hasDetailValue(entry.error);
}

export function hasToolCallDetail(entries: ToolCallDetailEntry[]): boolean {
  return entries.some(isToolCallDetailEntryVisible);
}

export function formatToolDetailValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return redactActivityText(value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const serialized = JSON.stringify(value, null, 2);
    return serialized ? redactActivityText(serialized) : "";
  } catch {
    return redactActivityText(String(value));
  }
}

function hasDetailValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0;
  return true;
}
