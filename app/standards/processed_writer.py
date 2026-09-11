"""Deterministic serialization with explicit overwrite and staged, rollback-capable writes."""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

from app.standards.catalog import NormativeRegistry
from app.standards.importer import validate_document_id
from app.standards.import_types import (
    ImportedStandard, ProcessedExistsError, SourceHashConflict, StandardImportError,
)
from app.standards.loader import load_document


@dataclass(frozen=True)
class ProcessedWriteResult:
    files: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False,
                       default=lambda item: item.isoformat() if isinstance(item, date) else _unsupported(item))
            + "\n").encode("utf-8")


def _unsupported(item):
    raise TypeError(f"Cannot serialize {type(item).__name__}")


def _safe_path(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise StandardImportError(f"Output escapes the standards directory: {relative}")
    current = path
    while current != root:
        if current.is_symlink() or current.is_junction():
            raise StandardImportError(f"Linked output paths are not supported: {relative}")
        current = current.parent
    return path


def _validate_trace(imported):
    document = imported.document
    if document.provenance is None:
        raise StandardImportError("Imported document requires provenance")
    if [page.page for page in imported.pages] != list(range(1, document.provenance.page_count + 1)):
        raise StandardImportError("Imported page sequence does not match page_count")
    for clause in imported.clauses:
        if not clause.source_spans:
            raise StandardImportError(f"Clause {clause.id} has no source positions")
        raw, normalized = [], []
        for span in clause.source_spans:
            page = imported.pages[span.page - 1]
            if span.source_end > len(page.source_text) or span.normalized_end > len(page.normalized_text):
                raise StandardImportError(f"Clause {clause.id}: position outside page text")
            raw.append(page.source_text[span.source_start:span.source_end])
            normalized.append(page.normalized_text[span.normalized_start:span.normalized_end])
        if clause.source_text != "\n".join(raw) or clause.normalized_text != "\n".join(normalized):
            raise StandardImportError(f"Clause {clause.id}: text does not match page positions")


def write_processed(imported: ImportedStandard, standards_root, *, overwrite=False,
                    accept_source_change=False, imported_at=None) -> ProcessedWriteResult:
    """No timestamp in document/clauses/page data. Last import event is separate.

    Serializes imports under a single exclusive root lock. A normal write failure
    restores previous targets. This is not a power-loss-safe database transaction.
    """
    document = imported.document
    validate_document_id(document.id)
    NormativeRegistry([document], imported.clauses)
    _validate_trace(imported)
    if accept_source_change and not overwrite:
        raise StandardImportError("accept_source_change requires overwrite")
    timestamp = imported_at if imported_at is not None else datetime.now(timezone.utc)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise StandardImportError("imported_at must be a timezone-aware datetime")
    root = Path(standards_root).resolve()
    processed = _safe_path(root, Path("processed"))
    doc_relative = Path("documents") / f"{document.id}.json"
    clauses_relative = Path("clauses") / document.id
    pages_relative = Path("imported") / f"{document.id}.json"
    record_relative = Path("imports") / f"{document.id}.json"
    if document.provenance.import_record != record_relative.as_posix():
        raise StandardImportError("Provenance import_record does not match document id")
    relatives = (clauses_relative, pages_relative, record_relative, doc_relative)
    targets = {relative: _safe_path(root, Path("processed") / relative) for relative in relatives}
    source = imported.source_path.resolve()
    if any(source == target or source.is_relative_to(target) for target in targets.values()):
        raise StandardImportError("Output would replace the source PDF; choose a different output directory")
    for relative in ("processed/documents", "processed/clauses", "rules"):
        _safe_path(root, relative).mkdir(parents=True, exist_ok=True)
    lock = _safe_path(root, "processed/.import.lock")
    try:
        lock_handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise StandardImportError("Import lock exists; another import may be running") from None
    stage = None
    preserve_stage = False
    try:
        with lock_handle:
            lock_handle.write(f"pid={os.getpid()}\n")
            lock_handle.flush()
            existing = [target for target in targets.values() if target.exists()]
            warnings = []
            if existing:
                old_path = targets[doc_relative]
                old = load_document(old_path) if old_path.exists() else None
                if old is not None and old.id != document.id:
                    raise StandardImportError("Existing output file belongs to a different document id")
                previous_sha = old.provenance.sha256 if old and old.provenance else None
                if previous_sha != document.provenance.sha256:
                    if not accept_source_change:
                        raise SourceHashConflict(
                            f"Source SHA-256 conflict for {document.id}: {previous_sha or 'unknown'} -> "
                            f"{document.provenance.sha256}; use a new id or --overwrite --accept-source-change")
                    warnings.append(f"Source SHA-256 changed: {previous_sha or 'unknown'} -> {document.provenance.sha256}")
                if not overwrite:
                    raise ProcessedExistsError(f"Processed data for {document.id} already exists; use --overwrite")
            stage = Path(tempfile.mkdtemp(prefix=".import-", dir=processed)).resolve()
            payloads = {
                doc_relative: asdict(document),
                pages_relative: {
                    "schema_version": 1, "document_id": document.id,
                    "source_sha256": document.provenance.sha256,
                    "pages": [asdict(page) for page in imported.pages],
                    "diagnostics": [asdict(item) for item in imported.diagnostics],
                },
                record_relative: {
                    "schema_version": 1, "document_id": document.id,
                    "source_sha256": document.provenance.sha256,
                    "importer_version": document.provenance.importer_version,
                    "imported_at": timestamp.astimezone(timezone.utc).isoformat(),
                },
            }
            # One entity per JSON, compatible with the existing strict catalog loader.
            for index, clause in enumerate(imported.clauses, 1):
                payloads[clauses_relative / f"{index:04d}.json"] = asdict(clause)
            (stage / clauses_relative).mkdir(parents=True)
            for relative, payload in payloads.items():
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_json_bytes(payload))
            # Validate the new full catalog, including rules and unmanaged clause files.
            docs = [p for p in (processed / "documents").rglob("*.json") if p != targets[doc_relative]]
            clauses = [p for p in (processed / "clauses").rglob("*.json")
                       if not p.is_relative_to(targets[clauses_relative])]
            NormativeRegistry.from_files(document_files=docs + [stage / doc_relative],
                clause_files=clauses + sorted((stage / clauses_relative).glob("*.json")),
                rule_files=sorted((root / "rules").rglob("*.json")))
            moved_old, installed = [], []
            try:
                for relative in relatives:
                    target = targets[relative]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        backup = stage / "backup" / relative
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(target, backup)
                        moved_old.append(relative)
                    os.replace(stage / relative, target)
                    installed.append(relative)
            except OSError as exc:
                try:
                    for relative in reversed(installed):
                        os.replace(targets[relative], stage / relative)
                    for relative in reversed(moved_old):
                        os.replace(stage / "backup" / relative, targets[relative])
                except OSError as recovery_error:
                    preserve_stage = True
                    raise StandardImportError(f"Write and rollback failed; recovery data retained at {stage}") from recovery_error
                raise StandardImportError(f"Processed write failed; previous data restored: {exc}") from exc
            return ProcessedWriteResult(tuple(processed / relative for relative in sorted(payloads)), tuple(warnings))
    finally:
        # Stage is a directory created by this call; never delete an input-derived path.
        if stage is not None and not preserve_stage and stage.parent == processed.resolve():
            shutil.rmtree(stage)
        if preserve_stage:
            lock.write_text(f"recovery_required={stage.name}\n", encoding="utf-8")
        else:
            lock.unlink()
