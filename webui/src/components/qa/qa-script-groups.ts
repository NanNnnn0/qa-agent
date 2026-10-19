import type { QaProject, QaScript } from "@/lib/qa-api";

/**
 * Scripts carry no module column, so the automation list groups by the
 * directory that owns `file_path`. `tests/api/test_login.py` belongs to the
 * `tests/api` module; a script at the project root gets its own bucket, and a
 * script without a path is ungrouped.
 */
export type QaScriptModuleKind = "module" | "root" | "ungrouped";

export interface QaScriptModuleGroup {
  kind: QaScriptModuleKind;
  /** Directory path for `module`; empty for the root and ungrouped buckets. */
  key: string;
  scripts: QaScript[];
}

export interface QaScriptProjectGroup {
  projectId: string;
  /** Project key, or the raw id when the project list did not include it. */
  key: string;
  name: string;
  modules: QaScriptModuleGroup[];
}

export function qaScriptModulePath(filePath: string): {
  kind: QaScriptModuleKind;
  key: string;
} {
  const normalized = filePath
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\.\//, "")
    .replace(/^\/+/, "");
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length === 0) return { kind: "ungrouped", key: "" };
  const directories = segments.slice(0, -1);
  if (directories.length === 0) return { kind: "root", key: "" };
  return { kind: "module", key: directories.join("/") };
}

const MODULE_RANK: Record<QaScriptModuleKind, number> = {
  module: 0,
  root: 1,
  ungrouped: 2,
};

/**
 * Groups scripts as project -> module. Known projects keep the order of the
 * project list (usually by key); a project that only appears on a script is
 * appended by id so a stale list never hides that script.
 */
export function groupQaScripts(
  scripts: QaScript[],
  projects: QaProject[],
): QaScriptProjectGroup[] {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const scriptsByProject = new Map<string, QaScript[]>();
  for (const script of scripts) {
    const bucket = scriptsByProject.get(script.project_id) ?? [];
    bucket.push(script);
    scriptsByProject.set(script.project_id, bucket);
  }

  const orderedIds: string[] = [];
  for (const project of projects) {
    if (scriptsByProject.has(project.id)) orderedIds.push(project.id);
  }
  const unknownIds = [...scriptsByProject.keys()]
    .filter((id) => !projectById.has(id))
    .sort();

  return [...orderedIds, ...unknownIds].map((projectId) => {
    const project = projectById.get(projectId);
    const modules = new Map<string, QaScriptModuleGroup>();
    for (const script of scriptsByProject.get(projectId) ?? []) {
      const { kind, key } = qaScriptModulePath(script.file_path);
      const moduleId = `${kind}:${key}`;
      const group = modules.get(moduleId) ?? { kind, key, scripts: [] };
      group.scripts.push(script);
      modules.set(moduleId, group);
    }
    return {
      projectId,
      key: project?.key || projectId,
      name: project?.name || "",
      modules: [...modules.values()].sort(
        (left, right) =>
          MODULE_RANK[left.kind] - MODULE_RANK[right.kind] ||
          left.key.localeCompare(right.key),
      ),
    };
  });
}
