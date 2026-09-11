"""All entities and values are synthetic fixtures, not ESKD requirements."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import pytest

from app.models import Severity
from app.standards import (
    AutomationLevel, NormativeLookupError, NormativeRegistry, NormativeValidationError,
    RuleDefinition, RuleStatus, StandardClause, StandardDocument, StandardStatus,
)
from app.standards.loader import load_clause, load_document, load_rule


FIXTURES = Path(__file__).parent / "fixtures" / "normative"


@pytest.fixture
def document():
    return load_document(FIXTURES / "document.json")


@pytest.fixture
def clause():
    return load_clause(FIXTURES / "clause.json")


@pytest.fixture
def rule():
    return load_rule(FIXTURES / "rule.json")


def test_create_document():
    document = StandardDocument("test", "Test only", "TEST", "v1", "source/test.txt", StandardStatus.DRAFT)
    assert document.status == StandardStatus.DRAFT
    assert document.effective_date is None
    assert document.metadata == {}


def test_create_clause():
    clause = StandardClause("test.c", "test", "TEST-A", "Test text, no requirements")
    assert clause.page is None
    assert clause.title is None


def test_create_rule():
    rule = RuleDefinition("test.r", "Test", "Test only", "test", "test", (), "test_echo", {},
                          AutomationLevel.DETERMINISTIC, RuleStatus.DRAFT, Severity.INFO, 1)
    assert rule.status == RuleStatus.DRAFT
    assert rule.parameters == {}


def test_load_valid_entities(document, clause, rule):
    assert document.effective_date == date(2020, 1, 1)
    assert document.version == "test-edition-1"
    assert clause.page == 1
    assert rule.clause_ids == (clause.id,)
    assert rule.automation_level == AutomationLevel.DETERMINISTIC
    assert rule.severity == Severity.WARNING


@pytest.mark.parametrize("field", [
    "id", "title", "description", "category", "standard_document_id", "clause_ids",
    "check_type", "parameters", "automation_level", "status", "severity", "version",
])
def test_missing_rule_fields(tmp_path, field):
    data = json.loads((FIXTURES / "rule.json").read_text(encoding="utf-8"))
    del data[field]
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(NormativeValidationError, match=f"missing required fields: {field}") as error:
        load_rule(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("status", "enabled"), ("automation_level", "automatic"), ("severity", "fatal"),
    ("parameters", []), ("parameters", None), ("parameters", "{}"),
    ("metadata", []), ("version", True), ("version", "1"), ("version", 0),
    ("clause_ids", "TEST-A"), ("clause_ids", [3]), ("clause_ids", ["same", "same"]),
    ("title", " "), ("id", 42), ("unknown", "typo"),
])
def test_invalid_rule_fields(tmp_path, field, value):
    data = json.loads((FIXTURES / "rule.json").read_text(encoding="utf-8"))
    data[field] = value
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(NormativeValidationError, match=field):
        load_rule(path)


@pytest.mark.parametrize("content", ["[]", "{", '{"id":"a","id":"b"}', '{"x":NaN}'])
def test_invalid_json(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(NormativeValidationError) as error:
        load_rule(path)
    assert str(path) in str(error.value)


def test_missing_file_and_bad_encoding(tmp_path):
    with pytest.raises(NormativeValidationError, match="missing.json"):
        load_rule(tmp_path / "missing.json")
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(NormativeValidationError, match="bad.json"):
        load_rule(path)


@pytest.mark.parametrize("field,value", [("status", "invalid"), ("effective_date", "2020-02-30"),
                                          ("effective_date", "20200101"), ("version", 1)])
def test_invalid_document_file(tmp_path, field, value):
    data = json.loads((FIXTURES / "document.json").read_text(encoding="utf-8"))
    data[field] = value
    path = tmp_path / "document.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(NormativeValidationError, match=field):
        load_document(path)


@pytest.mark.parametrize("page", [0, -1, True, "1"])
def test_invalid_clause_page(clause, page):
    with pytest.raises(NormativeValidationError, match="page"):
        replace(clause, page=page)


def test_direct_model_validation(rule):
    with pytest.raises(NormativeValidationError, match="status"):
        replace(rule, status="active")
    with pytest.raises(NormativeValidationError, match="parameters"):
        replace(rule, parameters={"value": float("inf")})
    with pytest.raises(NormativeValidationError, match="metadata"):
        replace(rule, metadata={1: "bad key"})


def test_duplicate_ids(document, clause, rule):
    for documents, clauses, rules, name in [
        ([document, document], [clause], [rule], "StandardDocument"),
        ([document], [clause, clause], [rule], "StandardClause"),
        ([document], [clause], [rule, rule], "RuleDefinition"),
    ]:
        with pytest.raises(NormativeValidationError, match=f"duplicate {name} id"):
            NormativeRegistry(documents, clauses, rules)


def test_unknown_documents(document, clause, rule):
    with pytest.raises(NormativeValidationError, match="unknown document_id"):
        NormativeRegistry([], None, [rule])
    with pytest.raises(NormativeValidationError, match="unknown document_id"):
        NormativeRegistry([], [clause])


def test_unknown_clause_and_unloaded_catalog(document, rule):
    with pytest.raises(NormativeValidationError, match="unknown clause"):
        NormativeRegistry([document], [], [rule])
    assert not NormativeRegistry([document], None, [rule]).clauses_loaded


def test_clause_must_belong_to_rule_document(document, clause, rule):
    other = replace(document, id="test.other.v1")
    with pytest.raises(NormativeValidationError, match="another document"):
        NormativeRegistry([document, other], [replace(clause, document_id=other.id)], [rule])


@pytest.mark.parametrize("status", [StandardStatus.DRAFT, StandardStatus.SUPERSEDED, StandardStatus.ARCHIVED])
def test_active_rule_requires_active_document(document, clause, rule, status):
    with pytest.raises(NormativeValidationError, match="active rule requires active document"):
        NormativeRegistry([replace(document, status=status)], [clause], [rule])
    NormativeRegistry([replace(document, status=status)], [clause], [replace(rule, status=RuleStatus.DRAFT)])


def test_search_filter_active_and_lookup(document, clause, rule):
    draft = replace(rule, id="test.draft", status=RuleStatus.DRAFT, category="test-other")
    catalog = NormativeRegistry([document], [clause], [rule, draft])
    assert catalog.get_rule(rule.id) == rule
    assert catalog.get_document(document.id) == document
    assert catalog.get_clause(clause.id) == clause
    assert catalog.find_rules(category="test-other") == (draft,)
    assert catalog.find_rules(status="draft") == (draft,)
    assert catalog.find_rules(category="test-other", status=RuleStatus.ACTIVE) == ()
    assert catalog.active_rules() == (rule,)
    with pytest.raises(NormativeValidationError, match="unknown rule status"):
        catalog.find_rules(status="typo")
    for getter in (catalog.get_rule, catalog.get_document, catalog.get_clause):
        with pytest.raises(NormativeLookupError, match="missing"):
            getter("missing")


def test_catalog_protects_snapshot(document, clause, rule):
    catalog = NormativeRegistry([document], [clause], [rule])
    rule.parameters["nested"]["items"].append(3)
    catalog.get_rule(rule.id).parameters["nested"]["items"].append(4)
    catalog.active_rules()[0].metadata["changed"] = True
    assert catalog.get_rule(rule.id).parameters["nested"]["items"] == [1, 2]
    assert "changed" not in catalog.get_rule(rule.id).metadata


def test_load_catalog_from_files_and_duplicate_error():
    catalog = NormativeRegistry.from_files(document_files=[FIXTURES / "document.json"],
        clause_files=[FIXTURES / "clause.json"], rule_files=[FIXTURES / "rule.json"])
    assert len(catalog.active_rules()) == 1
    with pytest.raises(NormativeValidationError, match="duplicate RuleDefinition id") as error:
        NormativeRegistry.from_files(document_files=[FIXTURES / "document.json"],
            rule_files=[FIXTURES / "rule.json", FIXTURES / "rule.json"])
    assert "rule.json" in str(error.value)


def test_directory_loading(tmp_path):
    for folder, filename in [("processed/documents", "document.json"),
                              ("processed/clauses", "clause.json"), ("rules", "rule.json")]:
        target = tmp_path / folder
        target.mkdir(parents=True)
        (target / filename).write_bytes((FIXTURES / filename).read_bytes())
    catalog = NormativeRegistry.from_directory(tmp_path)
    assert len(catalog.active_rules()) == 1
    assert catalog.clauses_loaded
    with pytest.raises(NormativeValidationError, match="missing catalog directory"):
        NormativeRegistry.from_directory(tmp_path / "missing")


def test_production_catalog_has_no_real_or_test_rules():
    root = Path(__file__).resolve().parents[1] / "standards"
    assert NormativeRegistry.from_directory(root).find_rules() == ()
