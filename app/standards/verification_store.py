"""Append-only JSON decisions and reusable immutable source snapshots."""
from dataclasses import asdict
import os
from pathlib import Path
import tempfile

from app.standards.processed_writer import _json_bytes, _safe_path
from app.standards.verification_models import (
    VerificationError, VerificationConflict, revision_from_dict, ReviewStatus, validate_transition, check_hash,
)
from app.standards.verification_source import content_hash, read_json, snapshot_from_dict


class VerificationStore:
    def __init__(self, standards_root):
        self.root = Path(standards_root).resolve()

    def _path(self, relative):
        return _safe_path(self.root, Path("verified") / relative)

    def source_snapshot(self, fingerprint):
        check_hash(fingerprint, "import_fingerprint")
        snapshot = snapshot_from_dict(read_json(self._path(f"sources/{fingerprint}.json")))
        if snapshot.fingerprint != fingerprint:
            raise VerificationError("stored source snapshot fingerprint mismatch")
        return snapshot

    def history(self, clause_id):
        folder = self._path(f"revisions/{content_hash(clause_id)}")
        history = []
        for number, path in enumerate(sorted(folder.glob("*.json")), 1):
            _safe_path(self.root, path.relative_to(self.root))
            revision = revision_from_dict(read_json(path))
            if revision.clause_id != clause_id or revision.revision != number or path.name != f"{number:06d}.json":
                raise VerificationError(f"invalid revision sequence or identity: {path}")
            source = self.source_snapshot(revision.source_reference.import_fingerprint)
            original = source.get_clause(clause_id)
            if (source.document.id != revision.document_id
                    or source.document.provenance.sha256 != revision.source_reference.source_sha256
                    or content_hash(asdict(original)) != revision.source_reference.clause_fingerprint):
                raise VerificationError(f"invalid source revision reference: {path}")
            if revision.page_end > source.document.provenance.page_count:
                raise VerificationError("verified page range exceeds source page_count")
            if history:
                if history[-1].document_id != revision.document_id:
                    raise VerificationError("revision document identity changed")
                previous = (ReviewStatus(history[-1].status.value)
                    if history[-1].source_reference.import_fingerprint == revision.source_reference.import_fingerprint
                    else ReviewStatus.STALE)
                validate_transition(previous, revision.status)
            history.append(revision)
        return tuple(history)

    def all_histories(self):
        histories = {}
        base = self._path("revisions")
        for path in sorted(base.rglob("*.json")):
            revision = revision_from_dict(read_json(path))
            expected = base / content_hash(revision.clause_id) / f"{revision.revision:06d}.json"
            if path != expected:
                raise VerificationError(f"unexpected revision path: {path}")
            if revision.clause_id not in histories:
                histories[revision.clause_id] = self.history(revision.clause_id)
        return histories

    def validate(self):
        self.all_histories()
        base = self._path("sources")
        for path in base.rglob("*.json"):
            if path.parent != base:
                raise VerificationError(f"unexpected snapshot path: {path}")
            self.source_snapshot(path.stem)
        for path in self._path("").rglob("*.json"):
            if path.parts[len(self._path("").parts)] not in ("sources", "revisions"):
                raise VerificationError(f"unexpected verification JSON: {path}")

    @staticmethod
    def _write_new(path, data):
        """Publish a fully written file without replacing any existing revision."""
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".review-", suffix=".tmp", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_json_bytes(data))
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temp, path)  # Atomic create-if-absent on the Windows NTFS workspace.
        except FileExistsError as exc:
            raise VerificationConflict(f"revision already exists: {path}") from exc
        finally:
            temp.unlink(missing_ok=True)

    def append(self, revision, snapshot, *, expected_revision):
        """Caller holds the shared import/review lock; still check revision number."""
        history = self.history(revision.clause_id)
        if len(history) != expected_revision or revision.revision != expected_revision + 1:
            raise VerificationConflict("verification changed; reload before saving")
        if revision.source_reference.import_fingerprint != snapshot.fingerprint:
            raise VerificationError("revision does not reference supplied snapshot")
        snapshot_path = self._path(f"sources/{snapshot.fingerprint}.json")
        if snapshot_path.exists():
            self.source_snapshot(snapshot.fingerprint)
        else:
            self._write_new(snapshot_path, snapshot.to_dict())
        revision_path = self._path(f"revisions/{content_hash(revision.clause_id)}/{revision.revision:06d}.json")
        self._write_new(revision_path, asdict(revision))
