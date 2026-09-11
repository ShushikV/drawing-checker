"""Normative data only: no GUI, file access, or executable checks."""
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from math import isfinite

from app.models import Severity
from app.standards.errors import NormativeValidationError


class RuleStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class AutomationLevel(StrEnum):
    DETERMINISTIC = "deterministic"
    AI_ASSISTED = "ai_assisted"
    MANUAL = "manual"


class StandardStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


def require_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise NormativeValidationError(f"{field_name}: expected a non-empty string")


def require_enum(value, enum_type, field_name):
    if not isinstance(value, enum_type):
        raise NormativeValidationError(
            f"{field_name}: expected {enum_type.__name__} ({', '.join(enum_type)})")


def require_json_object(value, field_name):
    if not isinstance(value, dict):
        raise NormativeValidationError(f"{field_name}: expected a JSON object")

    def check(item, path):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and isfinite(item):
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                check(child, f"{path}[{index}]")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise NormativeValidationError(f"{path}: object keys must be strings")
                check(child, f"{path}.{key}")
            return
        raise NormativeValidationError(f"{path}: expected a finite JSON value")

    check(value, field_name)


@dataclass(frozen=True)
class StandardDocument:
    id: str
    title: str
    designation: str
    version: str
    source_path: str
    status: StandardStatus
    effective_date: date | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("id", "title", "designation", "version", "source_path"):
            require_text(getattr(self, name), name)
        require_enum(self.status, StandardStatus, "status")
        if self.effective_date is not None and type(self.effective_date) is not date:
            raise NormativeValidationError("effective_date: expected date or None")
        require_json_object(self.metadata, "metadata")


@dataclass(frozen=True)
class StandardClause:
    id: str
    document_id: str
    clause_number: str
    source_text: str
    title: str | None = None
    page: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("id", "document_id", "clause_number", "source_text"):
            require_text(getattr(self, name), name)
        if self.title is not None:
            require_text(self.title, "title")
        if self.page is not None and (type(self.page) is not int or self.page < 1):
            raise NormativeValidationError("page: expected a positive, one-based page number")
        require_json_object(self.metadata, "metadata")


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    title: str
    description: str
    category: str
    standard_document_id: str
    clause_ids: tuple[str, ...]
    check_type: str
    parameters: dict[str, object]
    automation_level: AutomationLevel
    status: RuleStatus
    severity: Severity
    version: int
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("id", "title", "description", "category", "standard_document_id", "check_type"):
            require_text(getattr(self, name), name)
        if not isinstance(self.clause_ids, tuple):
            raise NormativeValidationError("clause_ids: expected a tuple of clause identifiers")
        for clause_id in self.clause_ids:
            require_text(clause_id, "clause_ids")
        if len(set(self.clause_ids)) != len(self.clause_ids):
            raise NormativeValidationError("clause_ids: duplicate clause identifier")
        require_enum(self.automation_level, AutomationLevel, "automation_level")
        require_enum(self.status, RuleStatus, "status")
        require_enum(self.severity, Severity, "severity")
        if type(self.version) is not int or self.version < 1:
            raise NormativeValidationError("version: expected a positive integer")
        require_json_object(self.parameters, "parameters")
        require_json_object(self.metadata, "metadata")
