import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";
import { beforeAll, beforeEach } from "vitest";

import i18n, { initializeI18n, loadAllLocaleResources } from "@/i18n";
import { DISPATCH_DESK_STORAGE_KEY } from "@/lib/dispatch-desk";

// A lazily imported surface (settings, thread shell) can take longer than the
// 1s default to mount on a cold module graph, which made findBy*/waitFor give
// up before the chunk arrived. 8s keeps the queries honest: a genuinely
// missing element still fails, it just no longer fails on cold-start latency.
configure({ asyncUtilTimeout: 8_000 });

// The DOM test environment does not implement pointer capture used by Radix Select.
if (!HTMLElement.prototype.hasPointerCapture) {
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLElement.prototype.setPointerCapture = () => {};
  HTMLElement.prototype.releasePointerCapture = () => {};
}
if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => {};
}

// happy-dom does not load fonts; text measurements can run immediately.
Object.defineProperty(document, "fonts", {
  value: { ready: Promise.resolve() },
  configurable: true,
});

function createTestStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.get(String(key)) ?? null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(String(key));
    },
    setItem(key: string, value: string) {
      store.set(String(key), String(value));
    },
  };
}

if (typeof window !== "undefined" && typeof localStorage.setItem !== "function") {
  const storage = createTestStorage();
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
  });
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

// happy-dom doesn't ship with ``crypto.randomUUID``; shim a tiny v4-ish helper.
if (!("randomUUID" in globalThis.crypto)) {
  Object.defineProperty(globalThis.crypto, "randomUUID", {
    value: () =>
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      }),
    configurable: true,
  });
}

beforeAll(async () => {
  await initializeI18n();
  await loadAllLocaleResources();
});

beforeEach(async () => {
  await i18n.changeLanguage("en");
  document.documentElement.lang = "en";
  document.title = "nanobot";
  localStorage.removeItem(DISPATCH_DESK_STORAGE_KEY);
  // App restores the pre-restart route on the next visit to /new for five
  // minutes (App.tsx RESTART_ROUTE_KEY/RESTART_STARTED_KEY). A test that
  // exercises a restart would otherwise redirect every later test's /new
  // navigation back to that chat, so reset the pair with the rest of the state.
  localStorage.removeItem("nanobot-webui.restartRoute");
  localStorage.removeItem("nanobot-webui.restartStartedAt");
  localStorage.setItem("nanobot.locale", "en");
});
