"""Intermediate representations shared by independent import pipeline stages."""
from dataclasses import dataclass
from pathlib import Path

from app.standards.models import StandardClause, StandardDocument


class StandardImportError(ValueError):
    """Source cannot be safely imported."""


class DocumentRequiresOCR(StandardImportError):
    pass


class ProcessedExistsError(StandardImportError):
    pass


class SourceHashConflict(StandardImportError):
    pass


@dataclass(frozen=True)
class ImportedPage:
    page: int
    source_text: str


@dataclass(frozen=True)
class LinePosition:
    source_start: int
    source_end: int
    normalized_start: int
    normalized_end: int


@dataclass(frozen=True)
class NormalizedPage:
    page: int
    source_text: str
    normalized_text: str
    lines: tuple[LinePosition, ...]


@dataclass(frozen=True)
class ImportDiagnostic:
    code: str
    message: str
    page: int | None = None
    line: int | None = None


@dataclass(frozen=True)
class ClauseExtraction:
    clauses: tuple[StandardClause, ...]
    diagnostics: tuple[ImportDiagnostic, ...]


@dataclass(frozen=True)
class ImportedStandard:
    document: StandardDocument
    pages: tuple[NormalizedPage, ...]
    clauses: tuple[StandardClause, ...]
    diagnostics: tuple[ImportDiagnostic, ...]
    source_path: Path  # Runtime protection only; never serialized.
