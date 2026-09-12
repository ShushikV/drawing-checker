"""Verification workflow; GUI/CLI are clients and never modify imported data."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from app.standards.loader import load_document
from app.standards.models import StandardClause
from app.standards.processed_writer import _safe_path
from app.standards.verification_models import (
    ClauseVerificationStatus, ReviewStatus, SourceRevisionReference, VerifiedClauseRevision,
    VerificationError, VerificationConflict, validate_transition,
)
from app.standards.verification_source import content_hash, load_current_snapshot
from app.standards.verification_store import VerificationStore


@dataclass(frozen=True)
class ClauseReviewState:
    candidate: StandardClause  # Current candidate, or historical candidate when removed.
    status: ReviewStatus
    revision: VerifiedClauseRevision | None
    import_fingerprint: str
    current: bool
    diagnostics: tuple[dict, ...]


class VerificationService:
    def __init__(self, standards_root="standards"):
        self.root = Path(standards_root).resolve()
        self.store = VerificationStore(self.root)

    @contextmanager
    def _locked(self):
        # Same lock as stage-4 writer: a reviewed import cannot change during saving.
        path = _safe_path(self.root, "processed/.import.lock")
        if not path.parent.is_dir():
            raise VerificationError("processed directory not found; import a document first")
        try:
            stream = path.open("x", encoding="utf-8")
        except FileExistsError:
            raise VerificationConflict("import/review is busy or recovery is required; retry after checking the lock") from None
        try:
            with stream:
                stream.write("verification\n")
                stream.flush()
                yield
        finally:
            path.unlink()

    def _documents(self):
        return {document.id: document for document in (
            load_document(path) for path in sorted(_safe_path(self.root, "processed/documents").glob("*.json")))}

    def documents(self):
        with self._locked():
            documents = self._documents()
            for history in self.store.all_histories().values():
                latest = history[-1]
                if latest.document_id not in documents:
                    documents[latest.document_id] = self.store.source_snapshot(latest.source_reference.import_fingerprint).document
            return tuple(documents.values())

    def get_document(self, document_id):
        for document in self.documents():
            if document.id == document_id:
                return document
        raise VerificationError(f"unknown document: {document_id}")

    def _states(self, document_id):
        current = None
        if _safe_path(self.root, f"processed/documents/{document_id}.json").exists():
            current = load_current_snapshot(self.root, document_id)
        histories = {key: history for key, history in self.store.all_histories().items()
                     if history[-1].document_id == document_id}
        if current is None and not histories:
            raise VerificationError(f"unknown document: {document_id}")
        clauses = {clause.id: clause for clause in current.clauses} if current else {}
        for clause_id, history in histories.items():
            if clause_id not in clauses:
                clauses[clause_id] = self.store.source_snapshot(history[-1].source_reference.import_fingerprint).get_clause(clause_id)
        states = []
        current_ids = {c.id for c in current.clauses} if current else set()
        for clause_id, candidate in clauses.items():
            revision = histories[clause_id][-1] if clause_id in histories else None
            present = clause_id in current_ids
            fingerprint = current.fingerprint if present else ""
            status = ReviewStatus.CANDIDATE if revision is None else ReviewStatus(revision.status.value)
            if revision is not None and (not present or revision.source_reference.import_fingerprint != fingerprint):
                status = ReviewStatus.STALE
            snapshot = current if present else self.store.source_snapshot(revision.source_reference.import_fingerprint)
            diagnostics = tuple(deepcopy(d) for d in snapshot.imported["diagnostics"]
                if d["page"] is None or candidate.page <= d["page"] <= candidate.page_end)
            states.append(ClauseReviewState(candidate, status, revision, fingerprint, present, diagnostics))
        return tuple(states)

    def list_clauses(self, document_id, *, status=None):
        with self._locked():
            states = self._states(document_id)
            return tuple(state for state in states if status is None or state.status == ReviewStatus(status))

    def _state(self, clause_id):
        for document_id in self._documents():
            for state in self._states(document_id):
                if state.candidate.id == clause_id:
                    return state
        history = self.store.history(clause_id)
        if history:
            return next(state for state in self._states(history[-1].document_id) if state.candidate.id == clause_id)
        raise VerificationError(f"unknown clause: {clause_id}")

    def get_state(self, clause_id):
        with self._locked():
            return self._state(clause_id)

    def get_candidate(self, clause_id):
        return self.get_state(clause_id).candidate

    def history(self, clause_id):
        with self._locked():
            return self.store.history(clause_id)

    def latest_verified_revision(self, clause_id):
        """Historical accessor; use require_verified for a currently usable confirmation."""
        return next((revision for revision in reversed(self.history(clause_id))
                     if revision.status == ClauseVerificationStatus.VERIFIED), None)

    def _save(self, clause_id, target, *, reviewed_by, changes=None, note=None,
              expected_revision=None, expected_import_fingerprint=None, metadata=None):
        with self._locked():
            state = self._state(clause_id)
            if not state.current:
                raise VerificationError("clause is no longer in the current import; cannot confirm or edit its historical revision")
            previous_number = state.revision.revision if state.revision else 0
            if expected_revision is not None and previous_number != expected_revision:
                raise VerificationConflict("verification changed; reload before saving")
            if expected_import_fingerprint is not None and state.import_fingerprint != expected_import_fingerprint:
                raise VerificationConflict("import changed; reload and review the current candidate")
            validate_transition(state.status, target)
            candidate = state.candidate
            previous = state.revision if state.status != ReviewStatus.STALE else None
            fields = {
                "clause_number": previous.clause_number if previous else candidate.clause_number,
                "title": previous.title if previous else candidate.title,
                "verified_text": previous.verified_text if previous else candidate.normalized_text or candidate.source_text,
                "page_start": previous.page_start if previous else candidate.page,
                "page_end": previous.page_end if previous else candidate.page_end or candidate.page,
            }
            changes = changes if changes is not None else {}
            if not isinstance(changes, dict) or set(changes) - fields.keys():
                raise VerificationError("only clause_number, title, verified_text, page_start/page_end can be edited")
            fields.update(deepcopy(changes))
            snapshot = load_current_snapshot(self.root, candidate.document_id)
            now = datetime.now(timezone.utc).isoformat()
            revision = VerifiedClauseRevision(
                clause_id=clause_id, document_id=candidate.document_id, revision=previous_number + 1,
                status=target, **fields,
                source_reference=SourceRevisionReference(candidate.document_id, snapshot.document.provenance.sha256,
                    snapshot.fingerprint, content_hash(asdict(candidate))),
                saved_at=now, reviewed_by=reviewed_by,
                verified_at=now if target == ClauseVerificationStatus.VERIFIED else None,
                verified_by=reviewed_by if target == ClauseVerificationStatus.VERIFIED else None,
                verification_note=note if note is not None else previous.verification_note if previous else "",
                metadata=deepcopy(metadata if metadata is not None else previous.metadata if previous else {}),
            )
            if revision.page_end > snapshot.document.provenance.page_count:
                raise VerificationError("page range exceeds source page_count")
            if previous:
                before, after = asdict(previous), asdict(revision)
                for key in ("revision", "saved_at", "verified_at"):
                    before.pop(key)
                    after.pop(key)
                if before == after:
                    return previous
            self.store.append(revision, snapshot, expected_revision=previous_number)
            return revision

    def verify(self, clause_id, *, verified_by, **kwargs):
        return self._save(clause_id, ClauseVerificationStatus.VERIFIED, reviewed_by=verified_by, **kwargs)

    def save_corrections(self, clause_id, *, reviewed_by, **kwargs):
        return self._save(clause_id, ClauseVerificationStatus.NEEDS_REVIEW, reviewed_by=reviewed_by, **kwargs)

    def mark_needs_review(self, clause_id, *, reviewed_by, **kwargs):
        return self._save(clause_id, ClauseVerificationStatus.NEEDS_REVIEW, reviewed_by=reviewed_by, **kwargs)

    def reject(self, clause_id, *, reviewed_by, **kwargs):
        return self._save(clause_id, ClauseVerificationStatus.REJECTED, reviewed_by=reviewed_by, **kwargs)

    def status_counts(self, document_id):
        states = self.list_clauses(document_id)
        return {"total": len(states), **{status.value: sum(s.status == status for s in states) for status in ReviewStatus}}

    def require_verified(self, clause_id, *, document=None, clause=None):
        with self._locked():
            state = self._state(clause_id)
            if state.status != ReviewStatus.VERIFIED:
                raise VerificationError(f"clause {clause_id} is {state.status.value}, expected verified and non-stale")
            snapshot = load_current_snapshot(self.root, state.candidate.document_id)
            if (document is not None and document != snapshot.document) or (clause is not None and clause != state.candidate):
                raise VerificationError("normative registry snapshot differs from the current import")
            return state.revision

    def revision_source(self, clause_id, revision_number):
        with self._locked():
            history = self.store.history(clause_id)
            revision = next((r for r in history if r.revision == revision_number), None)
            if revision is None:
                raise VerificationError("unknown revision")
            return self.store.source_snapshot(revision.source_reference.import_fingerprint).get_clause(clause_id)

    def validate(self):
        with self._locked():
            self.store.validate()
            document_ids = set(self._documents())
            document_ids.update(history[-1].document_id for history in self.store.all_histories().values())
            stale = [state.candidate.id for document_id in document_ids for state in self._states(document_id)
                     if state.status == ReviewStatus.STALE]
            if stale:
                raise VerificationError("stale verification decisions: " + ", ".join(stale))

    def find_source_pdf(self, document_id):
        """Filename is a hint; only matching original bytes may be shown as the source."""
        with self._locked():
            document = self._documents().get(document_id)
            if document is None:
                return None
            provenance = document.provenance
            if provenance is None:
                return None
            folder = _safe_path(self.root, "source")
            for path in sorted(folder.rglob("*")):
                if path.name != provenance.source_filename or not path.is_file():
                    continue
                if not path.resolve().is_relative_to(folder.resolve()):
                    continue
                try:
                    if sha256(path.read_bytes()).hexdigest() == provenance.sha256:
                        return path
                except OSError:
                    continue
        return None
