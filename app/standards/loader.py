"""Strict UTF-8 JSON loaders. One entity per file; never execute file contents."""
from dataclasses import MISSING, fields
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from app.models import Severity
from app.standards.errors import NormativeValidationError
from app.standards.models import (
    AutomationLevel, RuleDefinition, RuleStatus, StandardClause, StandardDocument, StandardStatus,
    SourceProvenance, ClauseSourceSpan,
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise NormativeValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise NormativeValidationError(f"invalid JSON constant: {value}")


def _nested_model(data, model, field_name):
    if not isinstance(data, dict):
        raise NormativeValidationError(f"{field_name}: expected a JSON object")
    try:
        return model(**data)
    except (TypeError, ValueError) as exc:
        raise NormativeValidationError(f"{field_name}: {exc}") from exc


def _load(path, model, enums=None):
    label = "<JSON data>" if isinstance(path, dict) else str(path)
    try:
        data = deepcopy(path) if isinstance(path, dict) else json.loads(
            Path(path).read_text(encoding="utf-8-sig"),
            object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        if not isinstance(data, dict):
            raise NormativeValidationError("expected one JSON object per file")
        schema = {item.name: item for item in fields(model)}
        missing = [name for name, item in schema.items()
                   if item.default is MISSING and item.default_factory is MISSING and name not in data]
        if missing:
            raise NormativeValidationError(f"missing required fields: {', '.join(missing)}")
        unknown = sorted(data.keys() - schema.keys())
        if unknown:
            raise NormativeValidationError(f"unknown fields: {', '.join(unknown)}")
        for name, enum_type in (enums or {}).items():
            try:
                data[name] = enum_type(data[name])
            except (ValueError, TypeError):
                raise NormativeValidationError(
                    f"{name}: expected one of {', '.join(enum_type)}") from None
        if model is RuleDefinition:
            if not isinstance(data["clause_ids"], list):
                raise NormativeValidationError("clause_ids: expected an array")
            data["clause_ids"] = tuple(data["clause_ids"])
        if model is StandardDocument and data.get("effective_date") is not None:
            raw = data["effective_date"]
            try:
                parsed = date.fromisoformat(raw)
                if parsed.isoformat() != raw:
                    raise ValueError
                data["effective_date"] = parsed
            except (ValueError, TypeError):
                raise NormativeValidationError("effective_date: expected YYYY-MM-DD") from None
        if model is StandardDocument and data.get("provenance") is not None:
            data["provenance"] = _nested_model(data["provenance"], SourceProvenance, "provenance")
        if model is StandardClause and "source_spans" in data:
            if not isinstance(data["source_spans"], list):
                raise NormativeValidationError("source_spans: expected an array")
            data["source_spans"] = tuple(_nested_model(item, ClauseSourceSpan, "source_spans")
                                         for item in data["source_spans"])
        return model(**data)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise NormativeValidationError(f"{label}: {exc}") from exc


def document_from_dict(data) -> StandardDocument:
    if not isinstance(data, dict):
        raise NormativeValidationError("document: expected a JSON object")
    return _load(data, StandardDocument, {"status": StandardStatus})


def clause_from_dict(data) -> StandardClause:
    if not isinstance(data, dict):
        raise NormativeValidationError("clause: expected a JSON object")
    return _load(data, StandardClause)


def load_document(path) -> StandardDocument:
    return _load(path, StandardDocument, {"status": StandardStatus})


def load_clause(path) -> StandardClause:
    return _load(path, StandardClause)


def load_rule(path) -> RuleDefinition:
    """Validate shape and types; use NormativeRegistry to validate references."""
    return _load(path, RuleDefinition, {
        "automation_level": AutomationLevel, "status": RuleStatus, "severity": Severity,
    })
