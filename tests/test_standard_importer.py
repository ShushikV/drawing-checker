"""Synthetic documents only; none of these strings or numbers are ESKD norms."""
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

from app.standards import NormativeRegistry, NormativeValidationError, StandardStatus
from app.standards.clause_extractor import NumberedClauseExtractor
from app.standards.import_cli import main
from app.standards.importer import StandardPdfImporter
from app.standards.import_types import (
    DocumentRequiresOCR, ImportedPage, ProcessedExistsError, SourceHashConflict, StandardImportError,
)
from app.standards.loader import load_clause, load_document
from app.standards.normalizer import TextNormalizer
from app.standards.processed_writer import write_processed


def make_pdf(path, texts):
    with pymupdf.open() as pdf:
        for text in texts:
            page = pdf.new_page()
            if text:
                page.insert_text((40, 40), text, fontsize=11)
        pdf.save(path)
    return path


@pytest.fixture
def source(tmp_path):
    return make_pdf(tmp_path / "test-only.pdf", [
        "TEST FIXTURE ONLY - NOT A STANDARD\n1 Scope\nSome test text\n\n"
        "1.1 First clause\nClause text\nAnother line\n1.1.1 Nested clause\nNested text begins",
        "Synthetic continuation of nested text\n1.2 Second clause\nMore test text\n"
        "2 Another section\nLast synthetic text",
    ])


def do_import(path, **kwargs):
    return StandardPdfImporter().import_pdf(path, document_id="test-standard", title="TEST FIXTURE ONLY",
        designation="TEST", version="test-edition-1", **kwargs)


@pytest.fixture
def imported(source):
    return do_import(source)


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_import_hash_provenance_pages_and_unmodified_source(source, imported):
    before = source.read_bytes()
    provenance = imported.document.provenance
    assert provenance.sha256 == sha256(before).hexdigest()
    assert provenance.file_size == len(before)
    assert provenance.page_count == 2
    assert provenance.source_filename == source.name
    assert provenance.importer_version == "1"
    assert provenance.extraction_engine.startswith("PyMuPDF/")
    assert imported.document.status == StandardStatus.DRAFT
    assert imported.document.metadata["review_required"] is True
    assert [page.page for page in imported.pages] == [1, 2]
    assert source.read_bytes() == before
    with pymupdf.open(source) as pdf:
        assert imported.pages[0].source_text == pdf[0].get_text("text", sort=False)
    assert imported == do_import(source)


def test_missing_and_corrupt_pdf(tmp_path):
    with pytest.raises(StandardImportError, match="Cannot read source PDF"):
        do_import(tmp_path / "missing.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(StandardImportError, match="Cannot open/extract PDF"):
        do_import(broken)


def test_empty_pdf_requires_ocr(tmp_path):
    source = make_pdf(tmp_path / "image-only-test.pdf", [""])
    with pytest.raises(DocumentRequiresOCR, match="document requires OCR"):
        do_import(source)


def test_password_protected_pdf(tmp_path):
    source = tmp_path / "encrypted-test.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 40), "1 Test only")
        pdf.save(source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-test", user_pw="user-test")
    with pytest.raises(StandardImportError, match="Encrypted PDF"):
        do_import(source)


def test_normalization_preserves_meaning_and_positions():
    raw = "\ufeff1 Test\r\nDo not re-\rphrase.  \n\tKeep typo sppelling\r2 Other\x00"
    page = TextNormalizer().normalize(ImportedPage(7, raw))
    assert page.source_text == raw
    assert page.page == 7
    assert page.normalized_text == "1 Test\nDo not re-\nphrase.  \n\tKeep typo sppelling\n2 Other\x00"
    assert TextNormalizer().normalize(ImportedPage(7, raw)) == page
    assert TextNormalizer().normalize(ImportedPage(7, page.normalized_text)).normalized_text == page.normalized_text
    assert page.lines[0].source_start == 0
    assert page.lines[-1].source_end == len(raw)
    assert page.lines[-1].normalized_end == len(page.normalized_text)


def test_clause_numbers_multiline_and_cross_page_trace(imported):
    clauses = imported.clauses
    assert [clause.clause_number for clause in clauses] == ["1", "1.1", "1.1.1", "1.2", "2"]
    assert "Clause text\nAnother line" in clauses[1].normalized_text
    assert clauses[2].page == 1
    assert clauses[2].page_end == 2
    assert len(clauses[2].source_spans) == 2
    assert "Synthetic continuation" in clauses[2].source_text
    assert clauses[3].page == 2
    assert any(d.code == "page_continuation_candidate" for d in imported.diagnostics)
    for clause in clauses:
        raw, normalized = [], []
        for span in clause.source_spans:
            page = imported.pages[span.page - 1]
            raw.append(page.source_text[span.source_start:span.source_end])
            normalized.append(page.normalized_text[span.normalized_start:span.normalized_end])
        assert clause.source_text == "\n".join(raw)
        assert clause.normalized_text == "\n".join(normalized)


def test_crlf_trace_and_three_level_numbering():
    page = TextNormalizer().normalize(ImportedPage(1, "1 Scope\r\nText\r1.1 Test\nBody\n1.1.1 Nested\r\nMore"))
    extracted = NumberedClauseExtractor().extract("test", [page])
    assert extracted.clauses[0].source_text == "1 Scope\r\nText\r"
    assert extracted.clauses[0].normalized_text == "1 Scope\nText\n"
    assert [c.clause_number for c in extracted.clauses] == ["1", "1.1", "1.1.1"]


@pytest.mark.parametrize("ambiguous", ["2", "1.1", "2. Heading", "2 Contents .... 7", "2 3 4", "1 Repeated heading"])
def test_ambiguous_fragments_remain_unassigned(ambiguous):
    page = TextNormalizer().normalize(ImportedPage(1, f"1 Scope\nBody\n{ambiguous}\nUnassigned text"))
    extracted = NumberedClauseExtractor().extract("test", [page])
    assert len(extracted.clauses) == 1
    assert extracted.clauses[0].normalized_text == "1 Scope\nBody\n"
    assert any(d.code == "ambiguous_numbered_fragment" and d.line == 3 for d in extracted.diagnostics)
    assert "Unassigned text" in page.source_text


def test_empty_page_interrupts_continuation(tmp_path):
    result = do_import(make_pdf(tmp_path / "partial-test.pdf", ["1 Test only\nBody", "", "Unassigned continuation"]))
    assert result.document.provenance.page_count == 3
    assert result.clauses[0].page_end == 1
    assert any(d.code == "empty_page" and d.page == 2 for d in result.diagnostics)
    assert any(d.code == "unassigned_text" and d.page == 3 for d in result.diagnostics)


def test_no_clause_candidates_retains_page(tmp_path):
    result = do_import(make_pdf(tmp_path / "unstructured-test.pdf", ["TEST ONLY\nUnstructured synthetic text"]))
    assert result.clauses == ()
    assert result.pages[0].normalized_text
    assert result.diagnostics


def test_processed_serialization_and_catalog_roundtrip(tmp_path, imported):
    root = tmp_path / "standards"
    timestamp = datetime(2024, 1, 2, tzinfo=timezone.utc)
    written = write_processed(imported, root, imported_at=timestamp)
    assert len(written.files) == 8  # document + five clauses + pages + import event
    document_path = root / "processed/documents/test-standard.json"
    assert load_document(document_path) == imported.document
    clause_files = sorted((root / "processed/clauses/test-standard").glob("*.json"))
    assert tuple(load_clause(path) for path in clause_files) == imported.clauses
    catalog = NormativeRegistry.from_directory(root)
    assert catalog.get_document("test-standard") == imported.document
    assert catalog.get_clause(imported.clauses[2].id) == imported.clauses[2]
    assert catalog.find_rules() == ()
    record = json.loads((root / "processed/imports/test-standard.json").read_text(encoding="utf-8"))
    assert record["imported_at"] == timestamp.isoformat()
    pages = json.loads((root / "processed/imported/test-standard.json").read_text(encoding="utf-8"))
    assert pages["pages"][0]["source_text"] == imported.pages[0].source_text
    for path in written.files:
        text = path.read_text(encoding="utf-8")
        assert str(tmp_path) not in text
        assert tmp_path.as_posix() not in text
        assert text.endswith("\n")


def test_repeat_without_overwrite_leaves_everything_unchanged(tmp_path, imported):
    root = tmp_path / "standards"
    write_processed(imported, root)
    before = snapshot(root)
    with pytest.raises(ProcessedExistsError, match="--overwrite"):
        write_processed(imported, root)
    assert snapshot(root) == before


def test_reproducible_content_and_separate_timestamp(tmp_path, imported):
    root = tmp_path / "standards"
    write_processed(imported, root, imported_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    first = snapshot(root)
    write_processed(imported, root, overwrite=True, imported_at=datetime(2024, 1, 2, tzinfo=timezone.utc))
    second = snapshot(root)
    assert first.keys() == second.keys()
    assert [path for path in first if first[path] != second[path]] == ["processed/imports/test-standard.json"]
    elsewhere = tmp_path / "elsewhere"
    write_processed(imported, elsewhere, imported_at=datetime(2024, 1, 2, tzinfo=timezone.utc))
    assert snapshot(elsewhere) == second


def test_source_hash_conflict_and_explicit_replacement(tmp_path, imported):
    root = tmp_path / "standards"
    write_processed(imported, root)
    before = snapshot(root)
    new_pdf = make_pdf(tmp_path / "changed-test.pdf", ["1 Changed synthetic text"])
    changed = do_import(new_pdf)
    with pytest.raises(SourceHashConflict, match="SHA-256 conflict"):
        write_processed(changed, root)
    with pytest.raises(SourceHashConflict, match="SHA-256 conflict"):
        write_processed(changed, root, overwrite=True)
    assert snapshot(root) == before
    result = write_processed(changed, root, overwrite=True, accept_source_change=True)
    assert any("SHA-256 changed" in warning for warning in result.warnings)
    assert len(list((root / "processed/clauses/test-standard").glob("*.json"))) == 1
    assert NormativeRegistry.from_directory(root).get_document("test-standard").provenance.sha256 == changed.document.provenance.sha256


def test_invalid_force_flag(tmp_path, imported):
    with pytest.raises(StandardImportError, match="requires overwrite"):
        write_processed(imported, tmp_path / "standards", accept_source_change=True)


@pytest.mark.parametrize("document_id", ["../escape", "C:\\escape", "a/b", "CON", "nul.txt", "trailing."])
def test_path_traversal_and_windows_reserved_ids(source, document_id):
    with pytest.raises(StandardImportError, match="portable filename"):
        StandardPdfImporter().import_pdf(source, document_id=document_id, title="Test", designation="TEST", version="1")


def test_preexisting_lock_prevents_writes(tmp_path, imported):
    root = tmp_path / "standards"
    lock = root / "processed/.import.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("test-lock", encoding="utf-8")
    with pytest.raises(StandardImportError, match="Import lock exists"):
        write_processed(imported, root)
    assert lock.read_text(encoding="utf-8") == "test-lock"
    assert not (root / "processed/documents/test-standard.json").exists()


def test_source_inside_output_cannot_be_replaced(tmp_path):
    root = tmp_path / "standards"
    folder = root / "processed/clauses/test-standard"
    folder.mkdir(parents=True)
    source = make_pdf(folder / "original.pdf", ["1 Test only"])
    before = source.read_bytes()
    with pytest.raises(StandardImportError, match="replace the source PDF"):
        write_processed(do_import(source), root, overwrite=True, accept_source_change=True)
    assert source.read_bytes() == before


def test_write_failure_rolls_back_previous_data(tmp_path, imported, monkeypatch):
    root = tmp_path / "standards"
    write_processed(imported, root)
    before = snapshot(root)
    import app.standards.processed_writer as writer
    actual_replace = writer.os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(target) == root / "processed/imported/test-standard.json" and not failed:
            failed = True
            raise OSError("test-only write failure")
        return actual_replace(source, target)

    monkeypatch.setattr(writer.os, "replace", fail_once)
    with pytest.raises(StandardImportError, match="previous data restored"):
        write_processed(imported, root, overwrite=True)
    assert failed
    assert snapshot(root) == before


def test_cli_statistics_and_errors(source, tmp_path, capsys):
    root = tmp_path / "output"
    args = [str(source), "--id", "test-standard", "--title", "TEST ONLY", "--designation", "TEST",
            "--version", "1", "--standards-root", str(root)]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "Pages: 2; clauses: 5" in output
    assert "WARNING" in output and "Written:" in output and "SHA-256:" in output
    assert main(args) == 1
    assert "--overwrite" in capsys.readouterr().err
    assert main(args + ["--overwrite"]) == 0


def test_cli_module_entrypoint(source, tmp_path):
    result = subprocess.run([sys.executable, "-m", "app.standards.import_cli", str(source),
        "--id", "test-cli", "--title", "TEST ONLY", "--designation", "TEST", "--version", "1",
        "--standards-root", str(tmp_path / "cli-output")], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "Pages: 2" in result.stdout


def test_loader_rejects_invalid_provenance_and_clause_positions(tmp_path, imported):
    root = tmp_path / "standards"
    write_processed(imported, root)
    path = root / "processed/documents/test-standard.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["provenance"]["sha256"] = "invalid"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(NormativeValidationError, match="sha256"):
        load_document(path)
    with pytest.raises(NormativeValidationError, match="page range"):
        replace(imported.clauses[0], page_end=2)
    with pytest.raises(NormativeValidationError, match="page_count"):
        NormativeRegistry([replace(imported.document, provenance=replace(imported.document.provenance, page_count=1))], imported.clauses)


def test_rollback_failure_retains_backup_and_lock(tmp_path, imported, monkeypatch):
    root = tmp_path / "standards"
    write_processed(imported, root)
    previous = (root / "processed/imported/test-standard.json").read_bytes()
    import app.standards.processed_writer as writer
    actual_replace = writer.os.replace

    def fail_install_and_restore(source, target):
        if Path(target) == root / "processed/imported/test-standard.json":
            raise OSError("test-only persistent write failure")
        return actual_replace(source, target)

    monkeypatch.setattr(writer.os, "replace", fail_install_and_restore)
    with pytest.raises(StandardImportError, match="recovery data retained"):
        write_processed(imported, root, overwrite=True)
    stages = list((root / "processed").glob(".import-*"))
    assert len(stages) == 1
    assert (stages[0] / "backup/imported/test-standard.json").read_bytes() == previous
    assert (root / "processed/.import.lock").read_text(encoding="utf-8").startswith("recovery_required=")


def test_invalid_catalog_does_not_replace_existing_data(tmp_path, imported):
    root = tmp_path / "standards"
    write_processed(imported, root)
    invalid = root / "rules/invalid.json"
    invalid.write_text('{"id": "test.invalid"}', encoding="utf-8")
    before = snapshot(root)
    with pytest.raises(NormativeValidationError, match="missing required fields"):
        write_processed(imported, root, overwrite=True)
    assert snapshot(root) == before


def test_gitignore_protects_sources_but_not_test_fixtures():
    repository = Path(__file__).resolve().parents[1]
    paths = ["standards/source/local.pdf", "standards/source/local.docx", "standards/source/nested/local.txt",
             "standards/source/.gitkeep", "standards/source/README.md", "tests/fixtures/normative/document.json"]
    result = subprocess.run(["git", "check-ignore", "--no-index", "--", *paths], cwd=repository,
                             capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(paths[:3])
