from dataclasses import asdict, dataclass
from enum import StrEnum


class ParseStatus(StrEnum):
    VALID = "VALID"
    RECOGNIZED_INVALID = "RECOGNIZED_INVALID"
    NOT_A_REFERENCE = "NOT_A_REFERENCE"


class ReferenceKind(StrEnum):
    SIZE = "30893_1_standard"
    APPENDIX_1 = "30893_1_appendix_a_variant_1"
    APPENDIX_2 = "30893_1_appendix_a_variant_2"
    GEOMETRY = "30893_2_geometry"
    COMBINED = "30893_2_combined"


@dataclass(frozen=True)
class FormattingDiagnostic:
    code: str
    field: str
    message: str
    start: int
    end: int
    actual: str = ""
    expected: str = ""


@dataclass(frozen=True)
class GeneralToleranceReference:
    status: ParseStatus
    standard: str | None
    reference_kind: ReferenceKind | None
    size_class: str | None
    geometry_class: str | None
    variant: str | None
    raw_text: str
    normalized_text: str
    formatting_issues: tuple[FormattingDiagnostic, ...]
    semantic_issues: tuple[FormattingDiagnostic, ...]
    expected_format: str
    start: int
    end: int

    @property
    def diagnostics(self):
        return self.formatting_issues + self.semantic_issues

    def to_dict(self):
        data = asdict(self)
        data["status"] = self.status.value
        data["reference_kind"] = self.reference_kind.value if self.reference_kind else None
        data["formatting_issues"] = [asdict(d) for d in self.formatting_issues]
        data["semantic_issues"] = [asdict(d) for d in self.semantic_issues]
        return data
