"""Trace assets: sources and test points, written as drafts (ADR 0012).

The chain is ``source -> test point -> case``. A case normally links a test
point; linking a source directly is the exception and needs a ``direct_reason``
(``qa_trace`` rules). This module is the one place that writes the two upstream
entities, so the agent tool, the HTTP route and the CLI share one contract:

* an agent write is a **draft** under ``draft/<batch>/<collection>/<ID>.yaml``,
* a draft only reaches the formal library through review,
* a case may only reference assets that already exist in the formal library,
* the project module segment comes from the project key, like cases do.
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from nanobot.qa.case_files import CaseFiles
from nanobot.qa.validation import (
    QaError,
    QaNotFoundError,
    QaValidationError,
    optional_text,
    require_enum,
    require_text,
)
from qa_trace.caseyaml import case_module
from qa_trace.drafts import add_draft, list_drafts
from qa_trace.errors import QaTraceError
from qa_trace.ids import IdKind, new_id
from qa_trace.loader import load_project
from qa_trace.models import (
    EvidenceType,
    EvidenceVerification,
    Method,
    Risk,
    Source,
    TestPoint,
)
from qa_trace.yamlfile import write_yaml

#: Draft batch every agent-written trace asset lands in.
AGENT_BATCH = "agent"

SOURCE_TYPES = ("req", "api", "ui", "bug", "std", "ex")
TESTPOINT_METHODS = tuple(item.value for item in Method)
TESTPOINT_RISKS = tuple(item.value for item in Risk)
EVIDENCE_TYPES = tuple(item.value for item in EvidenceType)
EVIDENCE_VERIFICATIONS = tuple(item.value for item in EvidenceVerification)

_SOURCE_ID_KINDS = {
    "req": IdKind.REQ,
    "api": IdKind.API,
    "ui": IdKind.UI,
    "bug": IdKind.BUG,
    "std": IdKind.STD,
    "ex": IdKind.EX,
}

MAX_TESTPOINTS_PER_CASE = 3


def project_module(project: dict[str, Any]) -> str:
    """Return the ``module`` segment the trace IDs of a project use."""
    return case_module(str(project["key"]))


def require_links_for_ready(
    status: Any,
    testpoints: Any,
    sources: Any,
    direct_reason: Any,
) -> None:
    """Refuse a ``ready`` case that has nothing to hang off (ADR 0012, policy C).

    ``draft`` stays permissive so a case can be written first and linked later;
    ``ready`` means executable, and execution, coverage and impact all walk the
    chain.
    """
    if status != "ready":
        return
    has_testpoints = bool(testpoints)
    has_sources = bool(sources)
    if not has_testpoints and not has_sources:
        raise QaValidationError(
            "a ready case must link at least one test point: call "
            "qa_testpoint action=list entity=testpoint to reuse one, or "
            "action=create entity=testpoint to write one (draft cases may stay unlinked)"
        )
    if has_sources and not has_testpoints and not direct_reason:
        raise QaValidationError(
            "a case that links a source directly needs direct_reason; prefer a test point "
            "unless there is no test point for this case"
        )


def _evidence_list(evidence: Any) -> list[dict[str, Any]]:
    """Validate the evidence payload a source needs."""
    if not isinstance(evidence, list) or not evidence:
        raise QaValidationError(
            "a source needs at least one evidence entry: "
            '[{"type": "openapi", "locator": "#/paths/~1api~1orders/post"}]'
        )
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(evidence):
        if not isinstance(raw, dict):
            raise QaValidationError(f"evidence[{index}] must be an object")
        kind = require_enum(raw.get("type"), f"evidence[{index}].type", EVIDENCE_TYPES)
        locator = require_text(raw.get("locator"), f"evidence[{index}].locator", max_length=1000)
        item: dict[str, Any] = {"type": kind, "locator": locator}
        description = optional_text(raw.get("description"), f"evidence[{index}].description", max_length=2000)
        if description:
            item["description"] = description
        verified = raw.get("verified")
        if verified is not None:
            item["verified"] = require_enum(
                verified, f"evidence[{index}].verified", EVIDENCE_VERIFICATIONS
            )
        items.append(item)
    return items


def _write_draft(
    directory: Path, document: dict[str, Any], *, batch: str, kind: str
) -> dict[str, Any]:
    """Write one entity document into the draft batch and return its location."""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", prefix="qa-trace-", delete=False, encoding="utf-8"
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            write_yaml(temp_path, document)
        target = add_draft(directory, temp_path, batch=batch)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        "id": str(document["id"]),
        "kind": kind,
        "draft": True,
        "batch": batch,
        "path": target.relative_to(directory).as_posix(),
        "next": (
            "review it (workbench test points tab, or qa trace review approve) "
            "before a case can link it"
        ),
    }


def create_source(
    store: Any,
    project_id: str,
    *,
    source_type: str,
    title: str,
    evidence: Any,
    module: str | None = None,
    owner: str = "agent",
    note: str | None = None,
    confidence: str = "observed",
    batch: str = AGENT_BATCH,
) -> dict[str, Any]:
    """Write one source draft (the root of the chain)."""
    project = store.get_project(project_id)
    directory = CaseFiles(store).ensure_project(project)
    kind = require_enum(source_type, "source_type", SOURCE_TYPES)
    module_name = (module or project_module(project)).strip().upper()
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": new_id(_SOURCE_ID_KINDS[kind], module_name, uuid4()),
        "type": kind,
        "module": module_name,
        "title": require_text(title, "title", max_length=300),
        "evidence": _evidence_list(evidence),
        "status": "active",
        "confidence": require_enum(confidence, "confidence", ("observed", "confirmed")),
        "owner": owner,
    }
    if note:
        document["note"] = optional_text(note, "note", max_length=2000)
    try:
        Source.from_dict(document)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    return _write_draft(directory, document, batch=batch, kind="source")


def create_testpoint(
    store: Any,
    project_id: str,
    *,
    title: str,
    sources: Any,
    method: str = "equivalence",
    risk: str = "medium",
    module: str | None = None,
    owner: str = "agent",
    tags: Any = None,
    note: str | None = None,
    batch: str = AGENT_BATCH,
) -> dict[str, Any]:
    """Write one test point draft under existing formal sources."""
    project = store.get_project(project_id)
    library = CaseFiles(store)
    directory = library.ensure_project(project)
    source_ids = [str(item).strip() for item in (sources or []) if str(item).strip()]
    if not source_ids:
        raise QaValidationError(
            "a test point needs at least one source: create one with "
            "qa_testpoint action=create entity=source first"
        )
    try:
        library_state = load_project(directory)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    drafts = {item.entity_id for item in list_drafts(directory).drafts}
    missing = [item for item in source_ids if item not in library_state.sources]
    if missing:
        pending = [item for item in missing if item in drafts]
        hint = (
            f" (still a draft: {', '.join(pending)} - approve it first)"
            if pending
            else ""
        )
        raise QaValidationError(
            "unknown source(s): " + ", ".join(missing) + hint
            + "; list them with qa_testpoint action=list entity=source"
        )
    module_name = (module or project_module(project)).strip().upper()
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": new_id(IdKind.TESTPOINT, module_name, uuid4()),
        "module": module_name,
        "title": require_text(title, "title", max_length=300),
        "sources": source_ids,
        "method": require_enum(method, "method", TESTPOINT_METHODS),
        "risk": require_enum(risk, "risk", TESTPOINT_RISKS),
        "status": "draft",
        "owner": owner,
    }
    tag_values = [str(item).strip() for item in (tags or []) if str(item).strip()]
    if tag_values:
        document["tags"] = tag_values
    if note:
        document["note"] = optional_text(note, "note", max_length=2000)
    try:
        TestPoint.from_dict(document)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    return _write_draft(directory, document, batch=batch, kind="testpoint")


def attach_cases(
    store: Any,
    testpoint_id: str,
    case_ids: Any,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Link existing cases to one formal test point."""
    project_id = None
    library = CaseFiles(store)
    testpoint = None
    attached: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    ids = [str(item).strip() for item in (case_ids or []) if str(item).strip()]
    if not ids:
        raise QaValidationError("attach requires case_ids")
    for case_id in ids:
        try:
            current = library.get_case(case_id)
        except QaError as exc:
            errors.append({"case_id": case_id, "error": str(exc)})
            continue
        project_id = project_id or current["project_id"]
        if testpoint is None:
            directory = library.project_dir(store.get_project(project_id))
            try:
                state = load_project(directory)
            except QaTraceError as exc:
                raise QaValidationError(exc.format()) from None
            testpoint = state.testpoints.get(testpoint_id)
            if testpoint is None:
                raise QaNotFoundError(
                    f"test point '{testpoint_id}' is not in the formal library; approve the "
                    "draft before linking cases to it"
                )
        existing = [str(item) for item in current.get("testpoints") or []]
        if testpoint_id in existing:
            attached.append({"case_id": case_id, "status": "already_linked"})
            continue
        merged = [testpoint_id] if replace else [*existing, testpoint_id]
        if len(merged) > MAX_TESTPOINTS_PER_CASE:
            errors.append({
                "case_id": case_id,
                "error": (
                    f"a case may link at most {MAX_TESTPOINTS_PER_CASE} test points; "
                    "split it or detach one first"
                ),
            })
            continue
        try:
            library.update_case(case_id, testpoints=merged)
        except QaError as exc:
            errors.append({"case_id": case_id, "error": str(exc)})
            continue
        attached.append({"case_id": case_id, "status": "linked", "testpoints": merged})
    return {
        "testpoint_id": testpoint_id,
        "attached": attached,
        "errors": errors,
        "count": len([item for item in attached if item["status"] == "linked"]),
    }


def list_assets(store: Any, project_id: str) -> dict[str, Any]:
    """Return the project's sources, test points, drafts and unlinked cases."""
    project = store.get_project(project_id)
    library = CaseFiles(store)
    directory = library.project_dir(project)
    cases = library.list_cases(project_id=project_id, limit=500)["items"]
    unlinked = [
        {
            "case_id": case["id"],
            "code": case["code"],
            "title": case["title"],
            "status": case["status"],
            "legacy": bool(case.get("legacy")),
        }
        for case in cases
        if not case.get("testpoints") and not case.get("sources")
    ]
    if not (directory / "project.yaml").is_file():
        return {
            "project_id": project_id,
            "root": str(directory),
            "sources": [],
            "testpoints": [],
            "drafts": [],
            "unlinked_cases": unlinked,
            "counts": {
                "sources": 0,
                "testpoints": 0,
                "drafts": 0,
                "unlinked_cases": len(unlinked),
                "cases": len(cases),
            },
        }
    try:
        state = load_project(directory)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    listing = list_drafts(directory)
    coverage: dict[str, int] = {}
    reviewed: dict[str, int] = {}
    for case in state.cases.values():
        for testpoint_id in case.testpoints:
            coverage[testpoint_id] = coverage.get(testpoint_id, 0) + 1
            if case.status.value == "reviewed":
                reviewed[testpoint_id] = reviewed.get(testpoint_id, 0) + 1
    testpoints = [
        {
            "id": item.id,
            "title": item.title,
            "sources": list(item.sources),
            "method": item.method.value,
            "risk": item.risk.value,
            "status": item.status.value,
            "module": item.module,
            "owner": item.owner,
            "tags": list(item.tags),
            "note": item.note,
            "case_count": coverage.get(item.id, 0),
            "reviewed_case_count": reviewed.get(item.id, 0),
        }
        for item in sorted(state.testpoints.values(), key=lambda row: row.id)
    ]
    sources = [
        {
            "id": item.id,
            "type": item.type.value,
            "title": item.title,
            "status": item.status.value,
            "confidence": item.confidence.value,
            "module": item.module,
            "owner": item.owner,
            "evidence": [
                {
                    "type": evidence.type.value,
                    "locator": evidence.locator,
                    "description": evidence.description or "",
                }
                for evidence in item.evidence
            ],
            "testpoint_count": sum(
                1 for testpoint in state.testpoints.values() if item.id in testpoint.sources
            ),
        }
        for item in sorted(state.sources.values(), key=lambda row: row.id)
    ]
    drafts = [item.to_dict(root=directory) for item in listing.drafts]
    return {
        "project_id": project_id,
        "root": str(directory),
        "sources": sources,
        "testpoints": testpoints,
        "drafts": drafts,
        "unlinked_cases": unlinked,
        "counts": {
            "sources": len(sources),
            "testpoints": len(testpoints),
            "drafts": len(drafts),
            "unlinked_cases": len(unlinked),
            "cases": len(cases),
        },
    }


def get_asset(store: Any, project_id: str, asset_id: str) -> dict[str, Any]:
    """Return one source, test point or draft of the project."""
    project = store.get_project(project_id)
    library = CaseFiles(store)
    directory = library.project_dir(project)
    if not (directory / "project.yaml").is_file():
        raise QaNotFoundError(f"project '{project_id}' has no trace library yet")
    try:
        state = load_project(directory)
    except QaTraceError as exc:
        raise QaValidationError(exc.format()) from None
    source = state.sources.get(asset_id)
    if source is not None:
        return {"kind": "source", "draft": False, "entity": asdict(source)}
    testpoint = state.testpoints.get(asset_id)
    if testpoint is not None:
        return {"kind": "testpoint", "draft": False, "entity": asdict(testpoint)}
    for draft in list_drafts(directory).drafts:
        if draft.entity_id == asset_id:
            return {
                "kind": draft.kind,
                "draft": True,
                "batch": draft.batch,
                "path": draft.path.relative_to(directory).as_posix(),
                "valid": draft.valid,
                "problems": [error.format() for error in draft.errors],
                "entity": dict(draft.raw),
            }
    raise QaNotFoundError(
        f"'{asset_id}' is not a source, test point or draft of this project"
    )
