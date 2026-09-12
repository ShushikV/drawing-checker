"""Human decisions, separate from immutable imported candidates."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re

from app.standards.models import require_json_object, require_positive_int, require_text


class VerificationError(ValueError):
    pass


class VerificationConflict(VerificationError):
    pass


class ClauseVerificationStatus(StrEnum):
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"  # Projection, never a persisted human decision.


def check_hash(value, name):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise VerificationError(f"{name}: expected a SHA-256 hex digest")


def parse_timestamp(value):
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
        return timestamp
    except (TypeError, ValueError):
        raise VerificationError("timestamp: expected an ISO datetime with timezone") from None


@dataclass(frozen=True)
class SourceRevisionReference:
    document_id: str
    source_sha256: str
    import_fingerprint: str
    clause_fingerprint: str

    def __post_init__(self):
        require_text(self.document_id, "document_id")
        for name in ("source_sha256", "import_fingerprint", "clause_fingerprint"):
            check_hash(getattr(self, name), name)


@dataclass(frozen=True)
class VerifiedClauseRevision:
    clause_id: str
    document_id: str
    revision: int
    status: ClauseVerificationStatus
    clause_number: str
    title: str | None
    verified_text: str
    page_start: int
    page_end: int
    source_reference: SourceRevisionReference
    saved_at: str
    reviewed_by: str
    verified_at: str | None = None
    verified_by: str | None = None
    verification_note: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise VerificationError("unsupported verification schema_version")
        for name in ("clause_id", "document_id", "clause_number", "verified_text", "reviewed_by"):
            require_text(getattr(self, name), name)
        if self.title is not None:
            require_text(self.title, "title")
        require_positive_int(self.revision, "revision")
        require_positive_int(self.page_start, "page_start")
        require_positive_int(self.page_end, "page_end")
        if self.page_end < self.page_start:
            raise VerificationError("page_end must be >= page_start")
        if not isinstance(self.status, ClauseVerificationStatus) or self.status == ClauseVerificationStatus.CANDIDATE:
            raise VerificationError("candidate is implicit; only human decisions can be saved")
        if not isinstance(self.source_reference, SourceRevisionReference):
            raise VerificationError("source_reference must be SourceRevisionReference")
        self.source_reference.__post_init__()
        if self.source_reference.document_id != self.document_id:
            raise VerificationError("source_reference document mismatch")
        saved = parse_timestamp(self.saved_at)
        if self.status == ClauseVerificationStatus.VERIFIED:
            require_text(self.verified_by, "verified_by")
            if parse_timestamp(self.verified_at) != saved or self.verified_by != self.reviewed_by:
                raise VerificationError("confirmation must identify this revision's actor and timestamp")
        elif self.verified_at is not None or self.verified_by is not None:
            raise VerificationError("unverified decisions cannot have verified_at/verified_by")
        if not isinstance(self.verification_note, str):
            raise VerificationError("verification_note must be a string")
        require_json_object(self.metadata, "verification metadata")


def revision_from_dict(data):
    try:
        data = dict(data)
        data["status"] = ClauseVerificationStatus(data["status"])
        data["source_reference"] = SourceRevisionReference(**data["source_reference"])
        return VerifiedClauseRevision(**data)
    except (TypeError, ValueError, KeyError) as exc:
        raise VerificationError(f"invalid verified revision: {exc}") from exc


def validate_transition(previous, target):
    """Rejected decisions must be reopened before confirmation; stale needs fresh review."""
    if target == ClauseVerificationStatus.CANDIDATE:
        raise VerificationError("cannot return to candidate; use needs_review")
    if previous == ReviewStatus.REJECTED and target == ClauseVerificationStatus.VERIFIED:
        raise VerificationError("rejected clause must move to needs_review before confirmation")
