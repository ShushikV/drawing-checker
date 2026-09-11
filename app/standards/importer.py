"""Read-only source extraction and orchestration. No filesystem output here."""
from hashlib import sha256
from pathlib import Path
import re

import pymupdf

from app.standards.clause_extractor import ClauseExtractor, NumberedClauseExtractor
from app.standards.import_types import (
    DocumentRequiresOCR, ImportedPage, ImportedStandard, ImportDiagnostic, StandardImportError,
)
from app.standards.models import SourceProvenance, StandardDocument, StandardStatus
from app.standards.normalizer import TextNormalizer


IMPORTER_VERSION = "1"


def validate_document_id(document_id):
    if (not isinstance(document_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", document_id) is None
            or document_id.endswith(".")
            or re.match(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", document_id)):
        raise StandardImportError("document id must be a portable filename identifier (letters, digits, _, -, .)")


class StandardPdfImporter:
    def __init__(self, *, normalizer=None, clause_extractor: ClauseExtractor | None = None):
        self.normalizer = normalizer if normalizer is not None else TextNormalizer()
        self.clause_extractor = clause_extractor if clause_extractor is not None else NumberedClauseExtractor()

    def import_pdf(self, source, *, document_id, title, designation, version, metadata=None):
        validate_document_id(document_id)
        source = Path(source)
        try:
            # Hash and parse exactly the same immutable byte snapshot, avoiding a file-change race.
            raw = source.read_bytes()
        except OSError as exc:
            raise StandardImportError(f"Cannot read source PDF '{source.name}': {exc.strerror}") from exc
        digest = sha256(raw).hexdigest()
        diagnostics = []
        try:
            with pymupdf.open(stream=raw, filetype="pdf") as pdf:
                if not pdf.is_pdf:
                    raise StandardImportError("Source is not a PDF")
                if pdf.needs_pass:
                    raise StandardImportError("Encrypted PDF requires a password; password import is not supported")
                pages = tuple(ImportedPage(index + 1, page.get_text("text", sort=False))
                              for index, page in enumerate(pdf))
                if pdf.is_repaired:
                    diagnostics.append(ImportDiagnostic("repaired_pdf", "PDF needed repair while opening; verify extraction."))
        except StandardImportError:
            raise
        except Exception as exc:
            raise StandardImportError(f"Cannot open/extract PDF '{source.name}': {exc}") from exc
        if not pages or not any(page.source_text.strip() for page in pages):
            raise DocumentRequiresOCR("document requires OCR: no extractable text layer")
        normalized = tuple(self.normalizer.normalize(page) for page in pages)
        for page in pages:
            if "\ufffd" in page.source_text or "\x00" in page.source_text:
                diagnostics.append(ImportDiagnostic("suspect_text_encoding",
                    "Text contains replacement/NUL characters; retained unchanged for review.", page.page))
        extraction = self.clause_extractor.extract(document_id, normalized)
        document = StandardDocument(
            id=document_id, title=title, designation=designation, version=version,
            source_path=source.name, status=StandardStatus.DRAFT,
            metadata={**(metadata or {}), "review_required": True, "source_path_kind": "filename_only"},
            provenance=SourceProvenance(source.name, digest, len(raw), len(pages), IMPORTER_VERSION,
                f"PyMuPDF/{pymupdf.VersionBind}", self.normalizer.version, self.clause_extractor.version,
                f"imports/{document_id}.json"),
        )
        return ImportedStandard(document, normalized, extraction.clauses,
                                tuple(diagnostics) + extraction.diagnostics, source.resolve())
