"""Typed errors for the qa-trace library.

Every error carries a stable machine-readable ``code`` plus the ``path`` of the
file and the ``field`` path inside that file (for example ``steps[1].expected``),
so the CLI, the tests and later the workbench adapter report the same
diagnostic.  Codes are part of the contract: rename them only with a migration.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class QaTraceError(Exception):
    """Base class for every qa-trace failure."""

    code = "TRACE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        field: str | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message
        self.path = str(path) if path is not None else None
        self.field = field
        if code is not None:
            self.code = code
        super().__init__(self.format())

    def format(self) -> str:
        """Return the single-line diagnostic printed by the CLI."""
        location = self.path or ""
        if self.field:
            location = f"{location}:{self.field}" if location else self.field
        if not location:
            return f"{self.code}: {self.message}"
        return f"{self.code}: {location}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable form of this diagnostic."""
        return {
            "code": self.code,
            "path": self.path,
            "field": self.field,
            "message": self.message,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"path={self.path!r}, field={self.field!r})"
        )


class IdError(QaTraceError):
    """An ID is missing, malformed, or cannot be generated."""

    code = "TRACE_ID_INVALID"


class IdTypeMismatchError(QaTraceError):
    """An ID has a valid grammar but the wrong prefix for its position."""

    code = "TRACE_ID_TYPE_MISMATCH"


class SchemaVersionError(QaTraceError):
    """A document declares a schema version this build does not understand."""

    code = "TRACE_SCHEMA_VERSION"


class SchemaError(QaTraceError):
    """A document does not have the expected top-level shape."""

    code = "TRACE_SCHEMA_INVALID"


class FieldMissingError(QaTraceError):
    """A required field is absent or empty."""

    code = "TRACE_FIELD_MISSING"


class FieldInvalidError(QaTraceError):
    """A field is present but has the wrong type, shape or value."""

    code = "TRACE_FIELD_INVALID"


class EnumValueError(QaTraceError):
    """A field holds a value outside its declared enumeration."""

    code = "TRACE_ENUM_INVALID"


class EvidenceMissingError(QaTraceError):
    """A source has no evidence, so it cannot anchor the trace chain."""

    code = "TRACE_EVIDENCE_MISSING"


class LinkMissingError(QaTraceError):
    """A case declares neither test points nor direct sources."""

    code = "TRACE_LINK_MISSING"


class DirectReasonMissingError(QaTraceError):
    """A case references a source directly without a ``direct_reason``."""

    code = "TRACE_DIRECT_REASON_MISSING"


class StepExpectedMissingError(QaTraceError):
    """A case step has no usable expected result."""

    code = "TRACE_STEP_EXPECTED_MISSING"


class ScriptBindingError(QaTraceError):
    """A script binding is not ``<file>::<nodeid>``."""

    code = "TRACE_SCRIPT_INVALID"


class ReferenceMissingError(QaTraceError):
    """A declared reference (source, test point or script target) does not exist."""

    code = "TRACE_REF_MISSING"


class ReferenceTypeMismatchError(QaTraceError):
    """A reference resolves to an entity or file of the wrong kind."""

    code = "TRACE_REF_TYPE_MISMATCH"


class ReferenceOutsideProjectError(QaTraceError):
    """A path reference points outside the project directory."""

    code = "TRACE_REF_OUTSIDE_PROJECT"


class CaseOrphanError(QaTraceError):
    """A case cannot be traced up to any source."""

    code = "TRACE_CASE_ORPHAN"


class DuplicateIdError(QaTraceError):
    """The same ID is defined by more than one entity in a project."""

    code = "TRACE_ID_DUPLICATE"


class FileIdMismatchError(QaTraceError):
    """The file name does not match the entity ID it declares."""

    code = "TRACE_FILE_ID_MISMATCH"


class YamlError(QaTraceError):
    """A YAML file cannot be read or parsed."""

    code = "TRACE_YAML_INVALID"


class YamlDuplicateKeyError(QaTraceError):
    """A YAML mapping repeats a key, which silently drops data."""

    code = "TRACE_YAML_DUPLICATE_KEY"


class ProjectError(QaTraceError):
    """The project directory or its ``project.yaml`` is unusable."""

    code = "TRACE_PROJECT_INVALID"


class EntityNotFoundError(QaTraceError):
    """A queried entity ID is not defined by the project."""

    code = "TRACE_ENTITY_NOT_FOUND"


class TraceIndexError(QaTraceError):
    """The derived index (``.qa-trace/index.json``) is unreadable or incompatible."""

    code = "TRACE_INDEX_INVALID"


class DraftError(QaTraceError):
    """A draft command received input it cannot use."""

    code = "TRACE_DRAFT_INVALID"


class DraftNotFoundError(QaTraceError):
    """No draft carries the requested ID (or several batches do)."""

    code = "TRACE_DRAFT_NOT_FOUND"


class DraftIdConflictError(QaTraceError):
    """A draft would take an ID the formal library already owns."""

    code = "TRACE_DRAFT_ID_CONFLICT"


class DraftBaseMismatchError(QaTraceError):
    """An update draft was written against a formal entity that has since changed."""

    code = "TRACE_DRAFT_BASE_MISMATCH"


class ReviewBlockedError(QaTraceError):
    """A draft or entity cannot be promoted/reviewed for a business reason."""

    code = "TRACE_REVIEW_BLOCKED"


class RunNotFoundError(QaTraceError):
    """The requested run manifest does not exist."""

    code = "TRACE_RUN_NOT_FOUND"


class RunInvalidError(QaTraceError):
    """A run manifest cannot be read as a run record."""

    code = "TRACE_RUN_INVALID"


class DiffNotGitError(QaTraceError):
    """The project directory is not inside a git work tree, so there is no base."""

    code = "TRACE_DIFF_NOT_GIT"


class DiffBaseUnknownError(QaTraceError):
    """``--base`` does not resolve to a commit of the project's repository."""

    code = "TRACE_DIFF_BASE_UNKNOWN"


class DiffBaseMissingError(QaTraceError):
    """The project does not exist at the requested base commit."""

    code = "TRACE_DIFF_BASE_MISSING"


class DiffGitError(QaTraceError):
    """git is missing, or a git command (archive) failed."""

    code = "TRACE_DIFF_GIT_FAILED"


class DiffInputError(QaTraceError):
    """A ``diff`` argument or project threshold cannot be used."""

    code = "TRACE_DIFF_INVALID"


class MigrateError(QaTraceError):
    """The SQLite case export cannot run (database, project or argument unusable)."""

    code = "TRACE_MIGRATE_INVALID"


class QaTraceGroupError(QaTraceError):
    """Several independent errors found in one scan.

    ``load_project`` raises the single error directly when a project has exactly
    one problem, so callers that check ``.code`` keep working; a group is only
    used when more than one entity is broken.
    """

    code = "TRACE_ERRORS"

    def __init__(self, errors: Iterable[QaTraceError]) -> None:
        self.errors = tuple(errors)
        if not self.errors:
            raise ValueError("an error group needs at least one error")
        summary = f"{len(self.errors)} errors"
        detail = "\n".join(f"  {error.format()}" for error in self.errors)
        super().__init__(f"{summary}\n{detail}")

    @property
    def codes(self) -> tuple[str, ...]:
        """Return the codes of the grouped errors, in discovery order."""
        return tuple(error.code for error in self.errors)
