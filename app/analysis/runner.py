from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from app.models import DrawingIssue


@dataclass(frozen=True)
class AnalysisContext:
    pdf_path: Path


class Rule(Protocol):
    """Rules return findings in PDF coordinates and must not depend on Tk."""

    rule_id: str

    def analyze(self, context: AnalysisContext) -> Iterable[DrawingIssue]: ...


class RuleRunner:
    """Run explicitly supplied rules in order. Failures propagate to the caller.

    An empty result from an empty runner does not mean a drawing was checked.
    """

    def __init__(self, rules: Iterable[Rule] = ()):
        self.rules = tuple(rules)
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule identifiers must be unique")

    def analyze(self, context: AnalysisContext) -> list[DrawingIssue]:
        return [issue for rule in self.rules for issue in rule.analyze(context)]
