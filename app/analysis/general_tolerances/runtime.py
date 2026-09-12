"""Minimal production entry point. Missing or unverified data never means a passed check."""
from dataclasses import dataclass
from pathlib import Path

from app.analysis import AnalysisContext, RuleRunner
from app.analysis.normative import AnalyzerRegistry
from app.analysis.general_tolerances.analyzer import CHECK_TYPE, GeneralToleranceAnalyzer
from app.standards import NormativeRegistry
from app.standards.verification_service import VerificationService


@dataclass(frozen=True)
class CheckReport:
    issues: list
    ready: bool
    message: str
    rule_count: int = 0


def check_drawing(pdf_path, standards_root="standards"):
    try:
        catalog = NormativeRegistry.from_directory(standards_root)
        rules = [rule for rule in catalog.active_rules() if rule.check_type == CHECK_TYPE]
        if not rules:
            return CheckReport([], False, "Проверка общих допусков не выполнена: нет активных правил с verified-пунктами ГОСТ 30893.1/30893.2. См. standards/README.md.")
        implementations = AnalyzerRegistry()
        implementations.register(CHECK_TYPE, GeneralToleranceAnalyzer())
        verification = VerificationService(standards_root)
        bound = [implementations.bind(rule.id, catalog, verification_service=verification) for rule in rules]
        covered = [kind for rule in rules for kind in rule.parameters["reference_kinds"]]
        if len(set(covered)) != len(covered):
            raise ValueError("Несколько правил проверяют одну форму записи: устраните дублирование.")
        issues = RuleRunner(bound).analyze(AnalysisContext(Path(pdf_path)))
        return CheckReport(issues, True,
            f"Проверка общих допусков завершена. Правил: {len(rules)}. Замечаний: {len(issues)}. "
            "Проверены только настроенные формы; отсутствие ссылки не считается ошибкой.", len(rules))
    except (ValueError, LookupError, OSError) as exc:
        return CheckReport([], False, f"Проверка общих допусков недоступна: {exc}")
