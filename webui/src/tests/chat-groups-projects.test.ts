
import { describe, expect, it } from "vitest";

import { groupSessions, type ChatGroupLabels, type ChatGroupingOptions } from "@/lib/chat-groups";
import type { ChatSummary } from "@/lib/types";

const labels: ChatGroupLabels = {
  pinned: "置顶",
  all: "话题",
  today: "今天",
  yesterday: "昨天",
  earlier: "更早",
  archived: "已归档",
  projects: "项目",
  fallbackTitle: "新建话题",
};

const options: ChatGroupingOptions = {
  pinnedKeys: [],
  archivedKeys: [],
  titleOverrides: {},
  projectNameOverrides: {},
  sessionOrder: [],
  showArchived: false,
  sort: "updated_desc",
  defaultWorkspacePath: "/workspace",
};

function session(overrides: Partial<ChatSummary>): ChatSummary {
  return {
    key: "websocket:one",
    channel: "websocket",
    chatId: "one",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    title: "chat",
    preview: "",
    ...overrides,
  };
}

describe("chat groups with projects", () => {
  it("lists a QA project even when it has no sessions", () => {
    const groups = groupSessions([], labels, {
      ...options,
      projects: [{ id: "qa:p1", label: "SHOP", path: "/srv/shop", qaProjectId: "p1" }],
    });
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("SHOP");
    expect(groups[0].sessions).toEqual([]);
    expect(groups[0].qaProjectId).toBe("p1");
  });

  it("groups a bound chat under its QA project", () => {
    const chat = session({
      key: "websocket:two",
      chatId: "two",
      qaProject: { id: "p1", key: "SHOP", name: "Demo" },
    });
    const groups = groupSessions([chat], labels, {
      ...options,
      projects: [{ id: "qa:p1", label: "SHOP", path: "/srv/shop", qaProjectId: "p1" }],
    });
    const shop = groups.find((group) => group.qaProjectId === "p1");
    expect(shop?.sessions.map((item) => item.key)).toEqual(["websocket:two"]);
  });

  it("keeps chats without a project in the topics group", () => {
    const chat = session({
      key: "websocket:three",
      chatId: "three",
      workspaceScope: {
        project_path: "/workspace",
        access_mode: "full",
      },
    });
    const groups = groupSessions([chat], labels, {
      ...options,
      projects: [{ id: "qa:p1", label: "SHOP", path: "/srv/shop", qaProjectId: "p1" }],
    });
    const topics = groups.find((group) => group.id === "workspace:chats");
    expect(topics?.label).toBe("话题");
    expect(topics?.sessions.map((item) => item.key)).toEqual(["websocket:three"]);
  });

  it("treats a favorite directory as a normal project", () => {
    const groups = groupSessions([], labels, {
      ...options,
      projects: [{ id: "path:/srv/plain", label: "plain", path: "/srv/plain" }],
    });
    expect(groups[0].label).toBe("plain");
    expect(groups[0].qaProjectId).toBeUndefined();
  });
});
