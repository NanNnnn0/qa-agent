"""Adjacency over the ``Source <- TestPoint <- Case`` chain.

References are single-directional (children name their parents, never the other
way round), so the whole graph is built from the loaded entities: two reverse
indexes answer "what hangs below this source" and a small BFS answers "which
sources can this case reach".  No graph library is needed for three levels.

Only references that resolve to a loaded entity produce edges; a dangling
reference is reported by :mod:`qa_trace.rules` and deliberately does not create
a path, which is what makes an orphan case visible to the BFS.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .loader import Project
from .models import Case, Source, TestPoint


@dataclass(frozen=True, slots=True)
class TracePath:
    """One route from a case up to a source, through a test point or directly."""

    source_id: str
    testpoint_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this path."""
        return {"source_id": self.source_id, "testpoint_id": self.testpoint_id}


class TraceGraph:
    """Forward and reverse lookups for one project library."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.sources: dict[str, Source] = dict(project.sources)
        self.testpoints: dict[str, TestPoint] = dict(project.testpoints)
        self.cases: dict[str, Case] = dict(project.cases)

        testpoints_by_source: dict[str, list[str]] = {}
        for testpoint in self.testpoints.values():
            for source_id in testpoint.sources:
                testpoints_by_source.setdefault(source_id, []).append(testpoint.id)
        self._testpoints_by_source: dict[str, tuple[str, ...]] = {
            key: tuple(sorted(values)) for key, values in testpoints_by_source.items()
        }

        cases_by_testpoint: dict[str, list[str]] = {}
        for case in self.cases.values():
            for testpoint_id in case.testpoints:
                cases_by_testpoint.setdefault(testpoint_id, []).append(case.id)
        self._cases_by_testpoint: dict[str, tuple[str, ...]] = {
            key: tuple(sorted(values)) for key, values in cases_by_testpoint.items()
        }

        cases_by_source: dict[str, list[str]] = {}
        for case in self.cases.values():
            for source_id in case.sources:
                cases_by_source.setdefault(source_id, []).append(case.id)
        self._cases_by_source: dict[str, tuple[str, ...]] = {
            key: tuple(sorted(values)) for key, values in cases_by_source.items()
        }

    def downstream_testpoints(self, source_id: str) -> tuple[str, ...]:
        """Return the test points that name ``source_id``."""
        return self._testpoints_by_source.get(source_id, ())

    def cases_of_testpoint(self, testpoint_id: str) -> tuple[str, ...]:
        """Return the cases that name ``testpoint_id``."""
        return self._cases_by_testpoint.get(testpoint_id, ())

    def cases_of_source(self, source_id: str) -> tuple[str, ...]:
        """Return the cases that name ``source_id`` directly."""
        return self._cases_by_source.get(source_id, ())

    def downstream_cases(self, source_id: str) -> tuple[str, ...]:
        """Return the cases below ``source_id``, directly or through a test point."""
        found = set(self._cases_by_source.get(source_id, ()))
        for testpoint_id in self.downstream_testpoints(source_id):
            found.update(self._cases_by_testpoint.get(testpoint_id, ()))
        return tuple(sorted(found))

    def case_paths(self, case_id: str) -> tuple[TracePath, ...]:
        """Return every path from ``case_id`` to a source that actually exists.

        The traversal is a breadth-first search over the parents of the case
        (test points, then their sources) with a visited set, so a hand-built or
        corrupted graph cannot loop.
        """
        case = self.cases.get(case_id)
        if case is None:
            return ()
        paths: set[TracePath] = set()
        for source_id in case.sources:
            if source_id in self.sources:
                paths.add(TracePath(source_id=source_id))
        queue: deque[str] = deque(case.testpoints)
        visited: set[str] = set()
        while queue:
            testpoint_id = queue.popleft()
            if testpoint_id in visited:
                continue
            visited.add(testpoint_id)
            testpoint = self.testpoints.get(testpoint_id)
            if testpoint is None:
                continue
            for source_id in testpoint.sources:
                if source_id in self.sources:
                    paths.add(TracePath(source_id=source_id, testpoint_id=testpoint.id))
        return tuple(sorted(paths, key=lambda path: (path.source_id, path.testpoint_id or "")))

    def case_sources(self, case_id: str) -> tuple[str, ...]:
        """Return the existing sources reachable from ``case_id``, sorted."""
        return tuple(sorted({path.source_id for path in self.case_paths(case_id)}))

    def is_orphan(self, case_id: str) -> bool:
        """Return whether a case reaches no source at all."""
        return not self.case_sources(case_id)


def build_graph(project: Project) -> TraceGraph:
    """Build the graph for a loaded project."""
    return TraceGraph(project)
