"""Mock implementations here are test scaffolding, never production checks."""
from dataclasses import replace
from pathlib import Path

import pytest

from app.analysis import AnalysisContext, RuleRunner
from app.analysis.normative import (
    AnalyzerNotFoundError, AnalyzerRegistrationError, AnalyzerRegistry,
    AnalyzerResult, RuleBindingError, issue_from_result,
)
from app.models import BoundingBox, IssueLocation, RequirementReference
from app.standards import AutomationLevel, NormativeRegistry, RuleStatus
from app.standards.loader import load_clause, load_document, load_rule


FIXTURES = Path(__file__).parent / "fixtures" / "normative"


@pytest.fixture
def catalog():
    return NormativeRegistry.from_files(document_files=[FIXTURES / "document.json"],
        clause_files=[FIXTURES / "clause.json"], rule_files=[FIXTURES / "rule.json"])


class MockAnalyzer:
    def __init__(self):
        self.calls = []

    def validate_parameters(self, parameters):
        if not isinstance(parameters.get("sample_label"), str):
            raise ValueError("sample_label must be a string")

    def analyze(self, context, *, parameters):
        self.calls.append((context, parameters))
        yield AnalyzerResult((IssueLocation(0, BoundingBox(1, 2, 3, 4)),),
                             "Test-only observation", {"echo": parameters["sample_label"]})


def test_registration_and_missing_analyzer():
    registry = AnalyzerRegistry()
    mock = MockAnalyzer()
    registry.register("test_echo", mock)
    assert registry.get("test_echo") is mock
    with pytest.raises(AnalyzerRegistrationError, match="already registered"):
        registry.register("test_echo", mock)
    with pytest.raises(AnalyzerRegistrationError, match="requires"):
        registry.register("invalid", object())
    with pytest.raises(AnalyzerNotFoundError, match="missing"):
        registry.get("missing")


def test_execute_mock_parameters_and_issue_provenance(catalog):
    registry = AnalyzerRegistry()
    mock = MockAnalyzer()
    registry.register("test_echo", mock)
    rule = catalog.get_rule("test.rule.echo")
    bound = registry.bind(rule.id, catalog)
    assert mock.calls == []  # Binding is not execution.
    assert RuleRunner().analyze(AnalysisContext(Path("test-only.pdf"))) == []
    context = AnalysisContext(Path("test-only.pdf"))
    issues = RuleRunner([bound]).analyze(context)
    assert mock.calls == [(context, rule.parameters)]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.rule_id == rule.id
    assert issue.title == rule.title
    assert issue.description == rule.description + "\n\nTest-only observation"
    assert issue.severity == rule.severity
    assert issue.locations == (IssueLocation(0, BoundingBox(1, 2, 3, 4)),)
    reference = issue.requirements[0]
    assert reference.document == "TEST-DOCUMENT"
    assert reference.section == "TEST-A"
    assert reference.document_id == "test.document.v1"
    assert reference.document_version == "test-edition-1"
    assert reference.clause_id == "test.document.v1.clause-a"
    assert reference.excerpt.startswith("TEST FIXTURE ONLY")
    assert reference.page == 1
    assert issue.metadata["analysis"] == {"echo": "fixture-only"}
    assert issue.metadata["rule_metadata"] == {"test_only": True}
    assert issue.metadata["normative"]["rule_version"] == 1
    assert issue.metadata["normative"]["parameters"] == rule.parameters


def test_conversion_without_clauses_and_no_locations(catalog):
    definition = replace(catalog.get_rule("test.rule.echo"), clause_ids=())
    result = AnalyzerResult(metadata={"normative": "must not overwrite provenance"})
    issue = issue_from_result(definition, result, catalog)
    assert issue.locations == ()
    assert issue.description == definition.description
    assert issue.requirements[0].section is None
    assert issue.requirements[0].document == "TEST-DOCUMENT"
    assert issue.metadata["normative"]["rule_version"] == 1
    assert issue.metadata["analysis"]["normative"] == "must not overwrite provenance"


def test_reference_is_backward_compatible():
    reference = RequirementReference("Demo", "Section", "https://example.com")
    assert reference.url == "https://example.com"
    assert reference.excerpt is None
    assert reference.page is None


def test_unregistered_binding(catalog):
    with pytest.raises(AnalyzerNotFoundError, match="test_echo"):
        AnalyzerRegistry().bind("test.rule.echo", catalog)


@pytest.mark.parametrize("status", [RuleStatus.DRAFT, RuleStatus.VERIFIED, RuleStatus.DEPRECATED])
def test_binding_inactive_rules_is_rejected(status):
    rule = replace(load_rule(FIXTURES / "rule.json"), status=status)
    catalog = NormativeRegistry([load_document(FIXTURES / "document.json")],
                                [load_clause(FIXTURES / "clause.json")], [rule])
    with pytest.raises(RuleBindingError, match="only active"):
        AnalyzerRegistry().bind(rule.id, catalog)


@pytest.mark.parametrize("level", [AutomationLevel.AI_ASSISTED, AutomationLevel.MANUAL])
def test_non_deterministic_binding_is_rejected(level):
    rule = replace(load_rule(FIXTURES / "rule.json"), automation_level=level)
    catalog = NormativeRegistry([load_document(FIXTURES / "document.json")], None, [rule])
    with pytest.raises(RuleBindingError, match="only deterministic"):
        AnalyzerRegistry().bind(rule.id, catalog)


def test_clause_catalog_required_at_binding():
    rule = load_rule(FIXTURES / "rule.json")
    catalog = NormativeRegistry([load_document(FIXTURES / "document.json")], None, [rule])
    with pytest.raises(RuleBindingError, match="load the clause catalog"):
        AnalyzerRegistry().bind(rule.id, catalog)


def test_analyzer_parameter_validation():
    rule = replace(load_rule(FIXTURES / "rule.json"), parameters={})
    catalog = NormativeRegistry([load_document(FIXTURES / "document.json")],
                                [load_clause(FIXTURES / "clause.json")], [rule])
    registry = AnalyzerRegistry()
    registry.register(rule.check_type, MockAnalyzer())
    with pytest.raises(RuleBindingError, match="sample_label"):
        registry.bind(rule.id, catalog)


def test_analyzer_mutation_does_not_change_parameters(catalog):
    class MutatingMock(MockAnalyzer):
        def validate_parameters(self, parameters):
            parameters.clear()

        def analyze(self, context, *, parameters):
            assert parameters["nested"]["items"] == [1, 2]
            parameters["nested"]["items"].append(3)
            return [AnalyzerResult()]

    registry = AnalyzerRegistry()
    registry.register("test_echo", MutatingMock())
    runner = RuleRunner([registry.bind("test.rule.echo", catalog)])
    context = AnalysisContext(Path("test-only.pdf"))
    for _ in range(2):
        issue = runner.analyze(context)[0]
        assert issue.metadata["normative"]["parameters"]["nested"]["items"] == [1, 2]
    assert catalog.get_rule("test.rule.echo").parameters["nested"]["items"] == [1, 2]


def test_analyzer_failure_propagates(catalog):
    class BrokenMock(MockAnalyzer):
        def analyze(self, context, *, parameters):
            raise RuntimeError("test failure")

    registry = AnalyzerRegistry()
    registry.register("test_echo", BrokenMock())
    with pytest.raises(RuntimeError, match="test failure"):
        RuleRunner([registry.bind("test.rule.echo", catalog)]).analyze(AnalysisContext(Path("test.pdf")))


def test_wrong_result_type_rejected(catalog):
    with pytest.raises(TypeError, match="AnalyzerResult"):
        issue_from_result(catalog.get_rule("test.rule.echo"), {}, catalog)
