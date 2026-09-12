"""Validated import snapshots and content-based identities. No GUI or decisions."""
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from app.standards.catalog import NormativeRegistry
from app.standards.import_types import ImportedStandard, NormalizedPage, LinePosition, ImportDiagnostic
from app.standards.loader import (
    _unique_object, _invalid_constant, load_document, load_clause, document_from_dict, clause_from_dict,
)
from app.standards.models import StandardDocument, StandardClause
from app.standards.processed_writer import _json_bytes, _validate_trace
from app.standards.verification_models import VerificationError, parse_timestamp


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data
    except (OSError, UnicodeError, ValueError) as exc:
        raise VerificationError(f"{path}: {exc}") from exc


def content_hash(value):
    return sha256(_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ImportSnapshot:
    document: StandardDocument
    clauses: tuple[StandardClause, ...]
    imported: dict
    import_record: dict

    def __post_init__(self):
        try:
            provenance = self.document.provenance
            if provenance is None:
                raise VerificationError("verification requires an imported document with provenance")
            NormativeRegistry([self.document], self.clauses)
            if set(self.imported) != {"schema_version", "document_id", "source_sha256", "pages", "diagnostics"}:
                raise VerificationError("invalid imported page schema")
            if set(self.import_record) != {"schema_version", "document_id", "source_sha256", "importer_version", "imported_at"}:
                raise VerificationError("invalid import record schema")
            for data in (self.imported, self.import_record):
                if type(data["schema_version"]) is not int or data["schema_version"] != 1:
                    raise VerificationError("unsupported import schema_version")
                if data["document_id"] != self.document.id or data["source_sha256"] != provenance.sha256:
                    raise VerificationError("import source revision does not match document provenance")
            if self.import_record["importer_version"] != provenance.importer_version:
                raise VerificationError("import record version does not match provenance")
            parse_timestamp(self.import_record["imported_at"])
            pages = []
            for raw in self.imported["pages"]:
                data = dict(raw)
                data["lines"] = tuple(LinePosition(**line) for line in data["lines"])
                page = NormalizedPage(**data)
                if type(page.page) is not int or page.page < 1:
                    raise VerificationError("page must be a positive integer")
                if not isinstance(page.source_text, str) or not isinstance(page.normalized_text, str):
                    raise VerificationError("page text must be a string")
                source_end = normalized_end = 0
                for line in page.lines:
                    values = (line.source_start, line.source_end, line.normalized_start, line.normalized_end)
                    if any(type(value) is not int or value < 0 for value in values):
                        raise VerificationError("invalid line positions")
                    if (line.source_start != source_end or line.normalized_start != normalized_end
                            or line.source_end <= source_end or line.normalized_end < normalized_end):
                        raise VerificationError("non-contiguous line positions")
                    source_end, normalized_end = line.source_end, line.normalized_end
                if source_end != len(page.source_text) or normalized_end != len(page.normalized_text):
                    raise VerificationError("line positions do not cover page text")
                pages.append(page)
            diagnostics = tuple(ImportDiagnostic(**item) for item in self.imported["diagnostics"])
            _validate_trace(ImportedStandard(self.document, tuple(pages), self.clauses, diagnostics, Path("unused")))
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise VerificationError(f"invalid import snapshot: {exc}") from exc

    @property
    def fingerprint(self):
        document = asdict(self.document)
        # Administrative activation is not a new extraction; dates of import are separate.
        document.pop("status")
        return content_hash({"document": document, "clauses": [asdict(c) for c in sorted(self.clauses, key=lambda c: c.id)],
                             "imported": self.imported})

    def get_clause(self, clause_id):
        for clause in self.clauses:
            if clause.id == clause_id:
                return deepcopy(clause)
        raise VerificationError(f"clause not present in source revision: {clause_id}")

    def to_dict(self):
        return {"schema_version": 1, "document": asdict(self.document),
                "clauses": [asdict(c) for c in self.clauses],
                "imported": self.imported, "import_record": self.import_record}


def snapshot_from_dict(data):
    try:
        if set(data) != {"schema_version", "document", "clauses", "imported", "import_record"}:
            raise VerificationError("invalid snapshot fields")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise VerificationError("unsupported snapshot schema_version")
        return ImportSnapshot(document_from_dict(data["document"]),
            tuple(clause_from_dict(c) for c in data["clauses"]), data["imported"], data["import_record"])
    except (TypeError, ValueError, KeyError) as exc:
        raise VerificationError(f"invalid stored source snapshot: {exc}") from exc


def load_current_snapshot(root, document_id):
    from app.standards.importer import validate_document_id
    from app.standards.processed_writer import _safe_path

    validate_document_id(document_id)
    root = Path(root).resolve()
    document = load_document(_safe_path(root, f"processed/documents/{document_id}.json"))
    if document.id != document_id:
        raise VerificationError("document id does not match its filename")
    if document.provenance is None or document.provenance.import_record != f"imports/{document_id}.json":
        raise VerificationError("document requires a valid import_record reference")
    clauses = tuple(load_clause(path) for path in sorted(
        _safe_path(root, f"processed/clauses/{document_id}").glob("*.json")))
    return ImportSnapshot(document, clauses,
        read_json(_safe_path(root, f"processed/imported/{document_id}.json")),
        read_json(_safe_path(root, f"processed/imports/{document_id}.json")))
