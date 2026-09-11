"""UI-independent findings. Coordinates use PDF points, never screen pixels."""

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from uuid import uuid4


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class IssueStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


@dataclass(frozen=True)
class BoundingBox:
    """Unrotated page coordinates: origin at top left, 1 point = 1/72 inch."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        if not all(isfinite(v) for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("Coordinates must be finite")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("Bounding box coordinates are reversed")


@dataclass(frozen=True)
class IssueLocation:
    """Zero-based page index; omitted box means a page-level finding."""

    page_index: int
    bbox: BoundingBox | None = None

    def __post_init__(self):
        if self.page_index < 0:
            raise ValueError("Page index must be non-negative")


@dataclass(frozen=True)
class RequirementReference:
    document: str
    section: str | None = None
    url: str | None = None
    document_id: str | None = None
    document_version: str | None = None
    clause_id: str | None = None
    excerpt: str | None = None
    page: int | None = None


@dataclass
class DrawingIssue:
    rule_id: str
    title: str
    description: str
    locations: tuple[IssueLocation, ...] = ()
    requirements: tuple[RequirementReference, ...] = ()
    severity: Severity = Severity.ERROR
    status: IssueStatus = IssueStatus.OPEN
    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, object] = field(default_factory=dict)

    def mark_done(self):
        self.status = IssueStatus.DONE

    def reopen(self):
        self.status = IssueStatus.OPEN
