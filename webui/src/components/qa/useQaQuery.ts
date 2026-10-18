import { useCallback, useEffect, useRef, useState } from "react";

import { qaErrorMessage } from "@/lib/qa-api";

export interface QaQueryOptions {
  /** Polling cadence in ms; `0` disables the interval (used by tests). */
  intervalMs?: number;
  enabled?: boolean;
}

export interface QaQueryResult<T> {
  data: T | null;
  error: string;
  loading: boolean;
  /** Manual refresh (bumps the effect); the current data stays on screen. */
  reload: () => void;
  setData: (next: T | null) => void;
}

/**
 * Load one QA resource, optionally re-polling while it stays mounted.
 *
 * The interval is always cleared on unmount, and late answers from a cancelled
 * request are dropped so a slow read cannot overwrite newer state.
 */
export function useQaQuery<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  options: QaQueryOptions = {},
): QaQueryResult<T> {
  const { intervalMs = 0, enabled = true } = options;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(enabled);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((current) => current + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    let first = true;

    const run = async () => {
      if (first) setLoading(true);
      first = false;
      try {
        const next = await fetcherRef.current();
        if (cancelled) return;
        setData(next);
        setError("");
      } catch (reason) {
        if (cancelled) return;
        setError(qaErrorMessage(reason));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void run();
    if (intervalMs > 0) {
      timer = setInterval(() => { void run(); }, intervalMs);
    }
    return () => {
      cancelled = true;
      if (timer !== undefined) clearInterval(timer);
    };
    // The caller owns the dependency list; a spread keeps hooks stable.
  }, [enabled, intervalMs, nonce, ...deps]);

  return { data, error, loading, reload, setData };
}

/** Small debounce for search-as-you-type filters (no interval, clears on unmount). */
export function useQaDebouncedValue<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
