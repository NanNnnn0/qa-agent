"""Content and dependency digests for review validity (plan section 3.4).

A review is only current while the entity *and everything it depends on* still
say what they said when the reviewer looked at them.  Two digests carry that:

* the **content hash** covers the declared business fields of one entity, and
* the **dependency fingerprint** covers the entity's own content hash plus the
  dependency fingerprints of its declared upstream entities, so a change three
  levels up reaches the case that hangs off it.

Everything excluded from the content hash is deliberate:

* review metadata (``reviewed_by``/``reviewed_at``/hash fields) must not be part
  of the content it describes, or recording a review would invalidate it;
* the manual ``stale`` flag is a review-validity marker, not business content
  (a stale source is reported through :mod:`qa_trace.staleness`, and clearing the
  flag is a separate explicit operation);
* derived state (``needs_recheck``, coverage) never lives in the files;
* unknown keys (``extra``) are preserved by the models but are not hashed, so a
  future phase must bump :data:`FINGERPRINT_VERSION` when it adds a business
  field.

Canonical JSON (sorted keys, no whitespace, UTF-8) makes the digest independent
of YAML layout, key order and the platform, which is what makes "only reindented
the file" not trigger a re-check.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .loader import Project
from .models import Case, Source, TestPoint

#: Version of the digest recipe.  Bump it when a hashed payload changes, so old
#: indexes are refused instead of silently comparing incompatible digests.
#: Version 2 added the case business fields ``code``/``expected``/``api``/
#: ``legacy_id`` (the workbench case fields, still YAML source of truth).
FINGERPRINT_VERSION = 2

KIND_SOURCE = "source"
KIND_TESTPOINT = "testpoint"
KIND_CASE = "case"


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text of ``value`` (stable key order, no spaces)."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default,
    )


def sha256_text(text: str) -> str:
    """Return the lowercase hexadecimal SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase hexadecimal SHA-256 of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def source_payload(source: Source) -> dict[str, Any]:
    """Return the hashed business fields of a source."""
    return {
        "schema_version": source.schema_version,
        "id": source.id,
        "type": source.type.value,
        "title": source.title,
        "evidence": [
            {
                "type": item.type.value,
                "locator": item.locator,
                "description": item.description,
                "sha256": item.sha256,
                "verified": item.verified.value if item.verified is not None else None,
            }
            for item in source.evidence
        ],
        "status": source.status.value,
        "confidence": source.confidence.value,
        "module": source.module,
        "url": source.url,
        "app_version": source.app_version,
        "observed_at": source.observed_at.isoformat() if source.observed_at else None,
        "owner": source.owner,
        "note": source.note,
    }


def testpoint_payload(testpoint: TestPoint) -> dict[str, Any]:
    """Return the hashed business fields of a test point."""
    return {
        "schema_version": testpoint.schema_version,
        "id": testpoint.id,
        "title": testpoint.title,
        "sources": list(testpoint.sources),
        "method": testpoint.method.value,
        "risk": testpoint.risk.value,
        "status": testpoint.status.value,
        "module": testpoint.module,
        "owner": testpoint.owner,
        "tags": list(testpoint.tags),
        "note": testpoint.note,
    }


def _canonical_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a JSON-ready copy of a nested mapping (``None`` stays ``None``)."""
    if value is None:
        return None
    return json.loads(json.dumps(dict(value), default=_json_default))


def case_payload(case: Case) -> dict[str, Any]:
    """Return the hashed business fields of a case."""
    binding = case.automation.script
    return {
        "schema_version": case.schema_version,
        "id": case.id,
        "title": case.title,
        "testpoints": list(case.testpoints),
        "sources": list(case.sources),
        "direct_reason": case.direct_reason,
        "priority": case.priority.value,
        "type": case.type.value,
        "steps": [{"action": step.action, "expected": step.expected} for step in case.steps],
        "status": case.status.value,
        "automation": {
            "status": case.automation.status.value,
            "script": binding.script if binding is not None else None,
        },
        "risk": case.risk.value if case.risk is not None else None,
        "code": case.code,
        "preconditions": case.preconditions,
        "postconditions": case.postconditions,
        "expected": case.expected,
        "api": _canonical_mapping(case.api),
        "legacy_id": case.legacy_id,
        "data": dict(case.data),
        "owner": case.owner,
        "tags": list(case.tags),
        "note": case.note,
    }


def content_payload(entity: Source | TestPoint | Case) -> dict[str, Any]:
    """Return the hashed business fields of any entity."""
    if isinstance(entity, Source):
        return source_payload(entity)
    if isinstance(entity, TestPoint):
        return testpoint_payload(entity)
    return case_payload(entity)


def entity_kind(entity: Source | TestPoint | Case) -> str:
    """Return the index kind name of ``entity``."""
    if isinstance(entity, Source):
        return KIND_SOURCE
    if isinstance(entity, TestPoint):
        return KIND_TESTPOINT
    return KIND_CASE


def content_hash(entity: Source | TestPoint | Case) -> str:
    """Return the content digest of one entity."""
    return sha256_text(canonical_json(content_payload(entity)))


def dependency_hash(
    entity_id: str,
    kind: str,
    entity_content_hash: str,
    upstream: Mapping[str, str | None],
) -> str:
    """Return the dependency fingerprint of one entity.

    ``upstream`` maps each declared upstream ID to *its* dependency fingerprint,
    so the digest is transitive; ``None`` marks a reference that does not
    resolve, which keeps a broken chain visible instead of collapsing to the
    same digest as a chain without that reference.
    """
    return sha256_text(
        canonical_json(
            {
                "fingerprint_version": FINGERPRINT_VERSION,
                "id": entity_id,
                "kind": kind,
                "content": entity_content_hash,
                "upstream": {key: upstream[key] for key in sorted(upstream)},
            }
        )
    )


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """The content hash and dependency fingerprint of one entity."""

    entity_id: str
    kind: str
    content_hash: str
    dependency_hash: str
    upstream: Mapping[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this fingerprint."""
        return {
            "id": self.entity_id,
            "kind": self.kind,
            "content_hash": self.content_hash,
            "dependency_hash": self.dependency_hash,
            "upstream": {key: self.upstream[key] for key in sorted(self.upstream)},
        }


def fingerprint_project(project: Project) -> dict[str, Fingerprint]:
    """Fingerprint every entity of a loaded project, in ID order.

    Sources are hashed first, then test points (over their sources), then cases
    (over their test points and direct sources); the reverse order would need a
    second pass.  A dangling reference contributes ``None``.
    """
    fingerprints: dict[str, Fingerprint] = {}
    source_dependencies: dict[str, str] = {}
    for source_id in sorted(project.sources):
        source = project.sources[source_id]
        digest = content_hash(source)
        dependency = dependency_hash(source_id, KIND_SOURCE, digest, {})
        source_dependencies[source_id] = dependency
        fingerprints[source_id] = Fingerprint(
            entity_id=source_id,
            kind=KIND_SOURCE,
            content_hash=digest,
            dependency_hash=dependency,
        )
    for testpoint_id in sorted(project.testpoints):
        testpoint = project.testpoints[testpoint_id]
        upstream = {
            source_id: source_dependencies.get(source_id) for source_id in testpoint.sources
        }
        digest = content_hash(testpoint)
        fingerprints[testpoint_id] = Fingerprint(
            entity_id=testpoint_id,
            kind=KIND_TESTPOINT,
            content_hash=digest,
            dependency_hash=dependency_hash(
                testpoint_id, KIND_TESTPOINT, digest, upstream
            ),
            upstream=upstream,
        )
    for case_id in sorted(project.cases):
        case = project.cases[case_id]
        upstream: dict[str, str | None] = {}
        for testpoint_id in case.testpoints:
            found = fingerprints.get(testpoint_id)
            upstream[testpoint_id] = (
                found.dependency_hash if found is not None and found.kind == KIND_TESTPOINT else None
            )
        for source_id in case.sources:
            upstream[source_id] = source_dependencies.get(source_id)
        digest = content_hash(case)
        fingerprints[case_id] = Fingerprint(
            entity_id=case_id,
            kind=KIND_CASE,
            content_hash=digest,
            dependency_hash=dependency_hash(case_id, KIND_CASE, digest, upstream),
            upstream=upstream,
        )
    return fingerprints


def changed_upstream(
    recorded: Mapping[str, str | None], current: Mapping[str, str | None]
) -> tuple[str, ...]:
    """Return the upstream IDs whose dependency fingerprint differs.

    A reference that disappeared (or appeared) counts as changed, and so does a
    reference that used to resolve and no longer does.
    """
    return tuple(
        sorted(
            key
            for key in set(recorded) | set(current)
            if recorded.get(key) != current.get(key)
        )
    )
