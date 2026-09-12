"""Shared synthetic data for manual-verification tests; no real standards."""
from types import SimpleNamespace

import pymupdf
import pytest

from app.standards.importer import StandardPdfImporter
from app.standards.processed_writer import write_processed
from app.standards.verification_service import VerificationService


@pytest.fixture
def review_project(tmp_path):
    root = tmp_path / "standards"
    source = root / "source" / "test-only.pdf"
    source.parent.mkdir(parents=True)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 40), "TEST FIXTURE ONLY\n1 Scope\nOriginal synthetic text\n1.1 First clause\nBody")
        pdf.new_page().insert_text((40, 40), "Synthetic continuation\n2 Another section\nMore test text")
        pdf.save(source)
    imported = StandardPdfImporter().import_pdf(source, document_id="test-review",
        title="TEST FIXTURE ONLY", designation="TEST", version="1")
    write_processed(imported, root)
    return SimpleNamespace(root=root, source=source, imported=imported,
        service=VerificationService(root), clause_id=imported.clauses[0].id)
