from app.analysis.normative import AnalyzerResult
from app.models import IssueLocation
from app.analysis.general_tolerances.lines import extract_lines
from app.analysis.general_tolerances.models import ParseStatus
from app.analysis.general_tolerances.parser import find_references
from app.analysis.general_tolerances.policy import validate_parameters


CHECK_TYPE = "general_tolerance_reference"


class GeneralToleranceAnalyzer:
    requires_verified_clauses = True
    def __init__(self, region_filter=None):
        self.region_filter = region_filter

    def validate_parameters(self, parameters):
        validate_parameters(parameters)

    def analyze(self, context, *, parameters):
        self.validate_parameters(parameters)
        for line in extract_lines(context.pdf_path, self.region_filter):
            for reference in find_references(line.text, parameters):
                if reference.reference_kind.value not in parameters["reference_kinds"]:
                    continue
                if reference.status != ParseStatus.RECOGNIZED_INVALID:
                    continue
                reasons = sorted({d.code for d in reference.diagnostics})
                uncertain = any(d.code == "invalid_spacing" and d.start == d.end
                                and d.start in line.visual_gap_positions for d in reference.diagnostics)
                observation = ("Неверно оформлена ссылка на общие допуски.\n"
                    + "\n".join(d.message for d in reference.diagnostics)
                    + f"\n\nНайдено:\n{reference.raw_text}\n\nОжидаемый формат:\n{reference.expected_format}")
                if uncertain:
                    observation = ("Проверьте запись общих допусков: между PDF spans есть визуальный зазор, "
                        "но нет символа пробела в текстовом слое. Формат нельзя подтвердить автоматически.\n\n"
                        + f"Извлечено:\n{reference.raw_text}\nОжидаемый формат:\n{reference.expected_format}")
                    reasons = ["uncertain_pdf_spacing"]
                box = line.bbox_for(reference.start, reference.end)
                yield AnalyzerResult((IssueLocation(line.page_index, box),), observation, {
                    "raw_text": reference.raw_text, "parsed": reference.to_dict(),
                    "expected_format": reference.expected_format, "reasons": reasons,
                    "page_index": line.page_index, "bbox": [box.x0, box.y0, box.x1, box.y1],
                    "line_text": line.text, "raw_spans": [
                        {key: list(value) if isinstance(value, tuple) else value for key, value in span.items()}
                        for span in line.spans],
                    "char_to_span": list(line.char_to_span[reference.start:reference.end]),
                    "visual_gap_positions": list(line.visual_gap_positions),
                })
