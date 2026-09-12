from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest

from app.models import Severity
from app.standards import (
    AutomationLevel, NormativeRegistry, NormativeValidationError, RuleDefinition, RuleStatus, StandardStatus,
)
from app.standards.importer import StandardPdfImporter
from app.standards.processed_writer import write_processed
from app.standards.review_cli import main
from app.standards.verification_models import (
    ClauseVerificationStatus, ReviewStatus, VerificationError, VerificationConflict,
)
from app.standards.verification_service import VerificationService
from app.standards.verification_source import content_hash


def processed_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in (root / "processed").rglob("*") if p.is_file()}


def reimport_new_version(project):
    provenance = replace(project.imported.document.provenance, importer_version="test-new-importer")
    changed = replace(project.imported, document=replace(project.imported.document, provenance=provenance))
    write_processed(changed, project.root, overwrite=True)
    return changed


def test_candidate_reads_do_not_create_revisions(review_project):
    p = review_project
    before = processed_bytes(p.root)
    for _ in range(2):
        state = p.service.get_state(p.clause_id)
        assert state.status == ReviewStatus.CANDIDATE
        assert state.revision is None
        assert p.service.get_candidate(p.clause_id) == p.imported.clauses[0]
        assert p.service.history(p.clause_id) == ()
        assert p.service.latest_verified_revision(p.clause_id) is None
    assert processed_bytes(p.root) == before
    assert not (p.root / "verified").exists()


def test_verify_without_edits_and_noop_repeat(review_project):
    p = review_project
    revision = p.service.verify(p.clause_id, verified_by="Test reviewer")
    assert revision.status == ClauseVerificationStatus.VERIFIED
    assert revision.verified_text == p.imported.clauses[0].normalized_text
    assert revision.verified_by == "Test reviewer"
    assert datetime.fromisoformat(revision.verified_at).tzinfo is not None
    assert revision.source_reference.source_sha256 == p.imported.document.provenance.sha256
    assert p.service.require_verified(p.clause_id) == revision
    assert p.service.verify(p.clause_id, verified_by="Test reviewer") == revision
    assert len(p.service.history(p.clause_id)) == 1


def test_edit_fields_note_metadata_and_preserve_import(review_project):
    p = review_project
    before = processed_bytes(p.root)
    revision = p.service.verify(p.clause_id, verified_by="Test editor", note="Checked against synthetic source",
        changes={"clause_number": "TEST-A", "title": "Corrected test title", "verified_text": "Human test correction",
                 "page_start": 1, "page_end": 2}, metadata={"test_only": True})
    assert revision.clause_number == "TEST-A"
    assert revision.title == "Corrected test title"
    assert revision.verified_text == "Human test correction"
    assert (revision.page_start, revision.page_end) == (1, 2)
    assert revision.verification_note == "Checked against synthetic source"
    assert revision.metadata == {"test_only": True}
    assert p.service.get_candidate(p.clause_id) == p.imported.clauses[0]
    assert p.service.revision_source(p.clause_id, 1) == p.imported.clauses[0]
    assert processed_bytes(p.root) == before


def test_needs_review_rejected_and_required_reopen(review_project):
    p = review_project
    first = p.service.mark_needs_review(p.clause_id, reviewed_by="Test", note="Check bounds")
    assert first.verified_by is None and first.verified_at is None
    assert p.service.get_state(p.clause_id).status == ReviewStatus.NEEDS_REVIEW
    p.service.reject(p.clause_id, reviewed_by="Test", note="Not a clause")
    assert p.service.get_state(p.clause_id).status == ReviewStatus.REJECTED
    with pytest.raises(VerificationError, match="needs_review"):
        p.service.verify(p.clause_id, verified_by="Test")
    assert len(p.service.history(p.clause_id)) == 2
    p.service.mark_needs_review(p.clause_id, reviewed_by="Test", note="Reopened")
    confirmed = p.service.verify(p.clause_id, verified_by="Test")
    assert confirmed.revision == 4
    assert [r.revision for r in p.service.history(p.clause_id)] == [1, 2, 3, 4]


def test_save_corrections_requires_fresh_confirmation(review_project):
    p = review_project
    confirmed = p.service.verify(p.clause_id, verified_by="Test")
    edited = p.service.save_corrections(p.clause_id, reviewed_by="Test", changes={"verified_text": "Edited test text"})
    assert edited.status == ClauseVerificationStatus.NEEDS_REVIEW
    assert p.service.latest_verified_revision(p.clause_id) == confirmed
    with pytest.raises(VerificationError, match="needs_review"):
        p.service.require_verified(p.clause_id)
    current = p.service.verify(p.clause_id, verified_by="Test")
    assert current.verified_text == "Edited test text"
    assert current.revision == 3


@pytest.mark.parametrize("changes", [{"verified_text": ""}, {"clause_number": " "}, {"page_start": 0},
                                     {"page_end": 3}, {"page_start": 2, "page_end": 1}, {"page_start": True},
                                     {"source_text": "overwrite forbidden"}])
def test_invalid_edits_do_not_write(review_project, changes):
    p = review_project
    with pytest.raises(ValueError):
        p.service.verify(p.clause_id, verified_by="Test", changes=changes)
    assert p.service.history(p.clause_id) == ()


def test_operator_required(review_project):
    with pytest.raises(ValueError, match="reviewed_by"):
        review_project.service.verify(review_project.clause_id, verified_by=" ")


def test_stale_after_changed_source_and_old_history_retained(review_project):
    p = review_project
    old = p.service.verify(p.clause_id, verified_by="Test")
    changed_pdf = p.root / "source/changed-test.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 40), "1 Scope\nDifferent test text")
        pdf.save(changed_pdf)
    changed = StandardPdfImporter().import_pdf(changed_pdf, document_id="test-review", title="TEST FIXTURE ONLY",
                                               designation="TEST", version="1")
    write_processed(changed, p.root, overwrite=True, accept_source_change=True)
    state = p.service.get_state(p.clause_id)
    assert state.status == ReviewStatus.STALE
    assert p.service.revision_source(p.clause_id, 1) == p.imported.clauses[0]
    with pytest.raises(VerificationError, match="stale"):
        p.service.require_verified(p.clause_id)
    current = p.service.verify(p.clause_id, verified_by="Test", note="Reviewed new source")
    assert current.revision == 2
    assert current.verified_text == changed.clauses[0].normalized_text
    assert current.source_reference.source_sha256 != old.source_reference.source_sha256
    assert len(p.service.history(p.clause_id)) == 2


def test_stale_after_new_importer_version(review_project):
    p = review_project
    old = p.service.verify(p.clause_id, verified_by="Test")
    reimport_new_version(p)
    assert p.service.get_state(p.clause_id).status == ReviewStatus.STALE
    assert p.service.history(p.clause_id)[0] == old
    with pytest.raises(VerificationError, match="stale"):
        p.service.validate()


def test_identical_reimport_timestamp_does_not_make_stale(review_project):
    p = review_project
    original = p.service.verify(p.clause_id, verified_by="Test")
    write_processed(p.imported, p.root, overwrite=True, imported_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert p.service.get_state(p.clause_id).status == ReviewStatus.VERIFIED
    assert p.service.verify(p.clause_id, verified_by="Test") == original
    p.service.validate()


def test_removed_candidate_is_stale_and_counted(review_project):
    p = review_project
    removed_id = p.imported.clauses[-1].id
    p.service.verify(removed_id, verified_by="Test")
    write_processed(replace(p.imported, clauses=p.imported.clauses[:-1]), p.root, overwrite=True)
    state = p.service.get_state(removed_id)
    assert state.status == ReviewStatus.STALE and not state.current
    assert p.service.status_counts("test-review")["stale"] == 1
    with pytest.raises(VerificationError, match="no longer"):
        p.service.verify(removed_id, verified_by="Test")


def test_json_roundtrip_and_portable_storage(review_project):
    p = review_project
    revision = p.service.verify(p.clause_id, verified_by="Test")
    reopened = VerificationService(p.root)
    assert reopened.history(p.clause_id) == (revision,)
    assert reopened.require_verified(p.clause_id) == revision
    files = list((p.root / "verified").rglob("*.json"))
    assert len(files) == 2
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert str(p.root) not in text and p.root.as_posix() not in text
        assert text.endswith("\n")
    reopened.validate()


@pytest.mark.parametrize("damage", ["invalid_json", "missing_snapshot", "bad_reference", "bad_revision", "bad_snapshot"])
def test_corrupt_storage_is_rejected(review_project, damage):
    p = review_project
    revision = p.service.verify(p.clause_id, verified_by="Test")
    path = next((p.root / "verified/revisions").rglob("*.json"))
    source = p.root / "verified/sources" / f"{revision.source_reference.import_fingerprint}.json"
    if damage == "invalid_json":
        path.write_text("{", encoding="utf-8")
    elif damage == "missing_snapshot":
        source.unlink()
    elif damage == "bad_snapshot":
        data = json.loads(source.read_text(encoding="utf-8"))
        data["document"]["title"] = "Tampered test title"
        source.write_text(json.dumps(data), encoding="utf-8")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if damage == "bad_reference":
            data["source_reference"]["source_sha256"] = "0" * 64
        else:
            data["revision"] = 5
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(VerificationError):
        p.service.validate()


def test_optimistic_conflicts(review_project):
    p = review_project
    state = p.service.get_state(p.clause_id)
    p.service.verify(p.clause_id, verified_by="First")
    with pytest.raises(VerificationConflict, match="verification changed"):
        p.service.verify(p.clause_id, verified_by="Second", expected_revision=0)
    reimport_new_version(p)
    with pytest.raises(VerificationConflict, match="import changed"):
        p.service.verify(p.clause_id, verified_by="Second", expected_revision=1,
                         expected_import_fingerprint=state.import_fingerprint)


def test_filter_counts_and_cli(review_project, capsys):
    p = review_project
    ids = [clause.id for clause in p.imported.clauses]
    p.service.verify(ids[0], verified_by="Test")
    p.service.reject(ids[1], reviewed_by="Test")
    counts = p.service.status_counts("test-review")
    assert counts == {"total": 3, "candidate": 1, "needs_review": 0, "verified": 1, "rejected": 1, "stale": 0}
    assert [s.candidate.id for s in p.service.list_clauses("test-review", status="verified")] == [ids[0]]
    assert main(["status", "test-review", "--standards-root", str(p.root)]) == 0
    assert "verified: 1" in capsys.readouterr().out
    assert main(["validate", "--standards-root", str(p.root)]) == 0
    reimport_new_version(p)
    assert main(["validate", "--standards-root", str(p.root)]) == 1
    assert "stale" in capsys.readouterr().err


def test_cli_module_entrypoint(review_project):
    result = subprocess.run([sys.executable, "-m", "app.standards.review_cli", "status", "test-review",
        "--standards-root", str(review_project.root)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "candidate: 3" in result.stdout


def test_missing_and_mismatched_source_does_not_hide_text(review_project):
    p = review_project
    assert p.service.find_source_pdf("test-review") == p.source
    p.source.write_bytes(b"mismatched test source")
    assert p.service.find_source_pdf("test-review") is None
    p.source.unlink()
    assert p.service.find_source_pdf("test-review") is None
    assert p.service.get_candidate(p.clause_id).source_text
    p.service.verify(p.clause_id, verified_by="Offline test reviewer", note="Source reviewed separately")


def test_activation_is_explicit_verified_and_current(review_project):
    p = review_project
    document = replace(p.imported.document, status=StandardStatus.ACTIVE)
    write_processed(replace(p.imported, document=document), p.root, overwrite=True)
    rule = RuleDefinition("test.activation", "Test only", "Not a real rule", "test", document.id,
        (p.clause_id,), "test_only", {}, AutomationLevel.DETERMINISTIC, RuleStatus.ACTIVE, Severity.WARNING, 1)
    catalog = NormativeRegistry([document], p.imported.clauses, [rule])
    assert catalog.active_rules() == (rule,)  # Legacy behavior preserved.
    with pytest.raises(NormativeValidationError, match="candidate"):
        catalog.validate_rule_activation(rule.id, p.service)
    revision = p.service.verify(p.clause_id, verified_by="Test")
    assert catalog.validate_rule_activation(rule.id, p.service) == (revision,)
    p.service.save_corrections(p.clause_id, reviewed_by="Test", changes={"verified_text": "Test correction"})
    with pytest.raises(NormativeValidationError, match="needs_review"):
        catalog.validate_rule_activation(rule.id, p.service)
    p.service.verify(p.clause_id, verified_by="Test")
    reimport_new_version(p)
    with pytest.raises(NormativeValidationError, match="stale"):
        catalog.validate_rule_activation(rule.id, p.service)


def test_shared_import_lock_blocks_save(review_project):
    p = review_project
    lock = p.root / "processed/.import.lock"
    lock.write_text("test lock", encoding="utf-8")
    with pytest.raises(VerificationConflict, match="busy"):
        p.service.verify(p.clause_id, verified_by="Test")
    assert lock.read_text(encoding="utf-8") == "test lock"
