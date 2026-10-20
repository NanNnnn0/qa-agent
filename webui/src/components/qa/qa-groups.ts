/**
 * Breadcrumb grouping for the workbench lists.
 *
 * A test point (and the cases that hang off it) carries a `模块/页面` group such
 * as `登录模块/注册界面`.  The library lists are flat rows, so this module turns
 * the group strings into a small tree and flattens it back into renderable rows:
 * one header row per level, then the items of the deepest node.
 *
 * The group is a *display* path, not an id: renaming it moves rows, deleting a
 * test point never renumbers anything.
 */

export interface QaGroupNode<T> {
  /** Full path of this level, e.g. `登录模块/注册界面`. */
  path: string;
  /** Just this level's name. */
  name: string;
  /** 1-based depth. */
  level: number;
  /** Items in this subtree. */
  count: number;
  children: QaGroupNode<T>[];
  /** Items that sit exactly on this node. */
  items: T[];
}

/** Rows the renderer walks: a group header, or an item with its depth. */
export type QaGroupRow<T> =
  | { kind: "group"; node: QaGroupNode<T> }
  | { kind: "item"; item: T; depth: number };

const UNGROUPED_PATH = "";

function levelsOf(path: string | null | undefined): string[] {
  if (!path) return [];
  return path
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean);
}

/**
 * Build the group tree of a flat list.
 *
 * Groups sort by name (Chinese collation); ungrouped items come last under a
 * single `未分组` header so a half-linked library is visible instead of hidden.
 */
export function buildGroupTree<T>(
  items: T[],
  pathOf: (item: T) => string | null | undefined,
  ungroupedLabel = "未分组",
): QaGroupNode<T>[] {
  const root: QaGroupNode<T> = {
    path: UNGROUPED_PATH,
    name: "",
    level: 0,
    count: 0,
    children: [],
    items: [],
  };
  for (const item of items) {
    const levels = levelsOf(pathOf(item));
    if (levels.length === 0) {
      root.items.push(item);
      continue;
    }
    let node = root;
    for (const level of levels) {
      const path = node.path ? `${node.path}/${level}` : level;
      let child = node.children.find((candidate) => candidate.path === path);
      if (!child) {
        child = { path, name: level, level: node.level + 1, count: 0, children: [], items: [] };
        node.children.push(child);
      }
      node = child;
    }
    node.items.push(item);
  }

  const finish = (node: QaGroupNode<T>): number => {
    node.children.sort((left, right) => left.name.localeCompare(right.name, "zh-Hans-CN"));
    node.count = node.items.length + node.children.reduce((sum, child) => sum + finish(child), 0);
    return node.count;
  };
  finish(root);

  const nodes = root.children;
  if (root.items.length > 0) {
    nodes.push({
      path: UNGROUPED_PATH,
      name: ungroupedLabel,
      level: 1,
      count: root.items.length,
      children: [],
      items: root.items,
    });
  }
  return nodes;
}

/** Flatten the tree into header rows plus item rows, honouring the collapsed set. */
export function flattenGroups<T>(
  nodes: QaGroupNode<T>[],
  collapsed: ReadonlySet<string>,
  depth = 1,
): QaGroupRow<T>[] {
  const rows: QaGroupRow<T>[] = [];
  for (const node of nodes) {
    rows.push({ kind: "group", node });
    if (collapsed.has(node.path)) continue;
    for (const item of node.items) {
      rows.push({ kind: "item", item, depth });
    }
    rows.push(...flattenGroups(node.children, collapsed, depth + 1));
  }
  return rows;
}

/** Toggle one path in a collapsed set, returning a new set. */
export function toggleCollapsed(collapsed: ReadonlySet<string>, path: string): Set<string> {
  const next = new Set(collapsed);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  return next;
}

/** `登录模块/注册界面` → `登录模块 / 注册界面`, for a drawer field. */
export function groupLabel(path: string | null | undefined, separator = " / "): string {
  return levelsOf(path).join(separator);
}
