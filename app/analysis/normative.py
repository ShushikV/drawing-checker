"""Explicit bridge from data definitions to registered Python implementations."""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from app.analysis.runner import AnalysisContext
from app.models import DrawingIssue, IssueLocation, RequirementReference
from app.standards import AutomationLevel, NormativeRegistry, RuleDefinition, RuleStatus
from app.standards.models import require_json_object, require_text


class AnalyzerRegistrationError(ValueError):
    pass


class AnalyzerNotFoundError(LookupError):
    pass


class RuleBindingError(ValueError):
    pass


@dataclass(frozen=True)
class AnalyzerResult:
    """One finding; locations use the same PDF coordinate convention as DrawingIssue."""

    locations: tuple[IssueLocation, ...] = ()
    observation: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.locations, tuple) or not all(
                isinstance(location, IssueLocation) for location in self.locations):
            raise ValueError("locations: expected a tuple of IssueLocation")
        if self.observation is not None:
            require_text(self.observation, "observation")
        require_json_object(self.metadata, "result metadata")


class Analyzer(Protocol):
    """Implementation owns mechanics and parameter schema, never normative values."""

    def validate_parameters(self, parameters: dict[str, object]) -> None: ...

    def analyze(self, context: AnalysisContext, *, parameters: dict[str, object]) -> Iterable[AnalyzerResult]: ...


def issue_from_result(definition: RuleDefinition, result: AnalyzerResult,
                      catalog: NormativeRegistry) -> DrawingIssue:
    catalog.validate_rule(definition)
    if not isinstance(result, AnalyzerResult):
        raise TypeError("analyzer must return AnalyzerResult instances")
    result.__post_init__()
    document = catalog.get_document(definition.standard_document_id)
    clauses = [catalog.get_clause(clause_id) for clause_id in definition.clause_ids]
    common = dict(document=document.designation, document_id=document.id,
                  document_version=document.version)
    references = tuple(RequirementReference(
        **common, section=clause.clause_number, clause_id=clause.id,
        excerpt=clause.source_text, page=clause.page) for clause in clauses)
    if not references:
        references = (RequirementReference(**common),)
    description = definition.description
    if result.observation:
        description += "\n\n" + result.observation
    return DrawingIssue(
        rule_id=definition.id, title=definition.title, description=description,
        severity=definition.severity, locations=result.locations, requirements=references,
        metadata={
            "normative": {"rule_version": definition.version, "check_type": definition.check_type,
                          "document_id": document.id, "document_version": document.version,
                          "source_path": document.source_path,
                          "parameters": deepcopy(definition.parameters)},
            "rule_metadata": deepcopy(definition.metadata),
            "analysis": deepcopy(result.metadata),
        },
    )


@dataclass(frozen=True)
class _BoundRule:
    definition: RuleDefinition
    analyzer: Analyzer
    catalog: NormativeRegistry

    @property
    def rule_id(self):
        return self.definition.id

    def analyze(self, context):
        # A fresh copy on every execution prevents analyzer mutations from changing the rule.
        results = self.analyzer.analyze(context, parameters=deepcopy(self.definition.parameters))
        return [issue_from_result(self.definition, result, self.catalog) for result in results]


class AnalyzerRegistry:
    """Only explicitly registered implementations can execute; files cannot import code."""

    def __init__(self):
        self._analyzers = {}

    def register(self, check_type: str, analyzer: Analyzer):
        require_text(check_type, "check_type")
        if check_type in self._analyzers:
            raise AnalyzerRegistrationError(f"analyzer already registered: {check_type}")
        if not callable(getattr(analyzer, "analyze", None)) or not callable(
                getattr(analyzer, "validate_parameters", None)):
            raise AnalyzerRegistrationError("analyzer requires analyze and validate_parameters methods")
        self._analyzers[check_type] = analyzer

    def get(self, check_type: str) -> Analyzer:
        try:
            return self._analyzers[check_type]
        except KeyError:
            raise AnalyzerNotFoundError(f"no analyzer registered for check_type: {check_type}") from None

    def bind(self, rule_id: str, catalog: NormativeRegistry):
        """Explicitly select an active deterministic rule for the existing RuleRunner."""
        definition = catalog.get_rule(rule_id)
        if definition.status != RuleStatus.ACTIVE:
            raise RuleBindingError(f"rule {rule_id}: only active rules can execute")
        if definition.automation_level != AutomationLevel.DETERMINISTIC:
            raise RuleBindingError(f"rule {rule_id}: only deterministic analyzers are supported")
        if definition.clause_ids and not catalog.clauses_loaded:
            raise RuleBindingError(f"rule {rule_id}: load the clause catalog before execution")
        analyzer = self.get(definition.check_type)
        try:
            analyzer.validate_parameters(deepcopy(definition.parameters))
        except (ValueError, TypeError) as exc:
            raise RuleBindingError(f"rule {rule_id}: invalid analyzer parameters: {exc}") from exc
        return _BoundRule(definition, analyzer, catalog)
