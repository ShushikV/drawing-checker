"""Notation examples are from the user's project specification, not verified norms."""
import pytest

from app.analysis.general_tolerances.models import ParseStatus
from app.analysis.general_tolerances.normalization import recognition_text
from app.analysis.general_tolerances.parser import find_references, parse_reference
from app.analysis.general_tolerances.policy import project_parameters, validate_parameters


@pytest.fixture
def parameters():
    return project_parameters()


VALID = [
    *(f"ГОСТ 30893.1 - {c}" for c in "fmcv"),
    "Общие допуски по ГОСТ 30893.1 - m",
    "Общие допуски по ГОСТ 30893.1: H14, h14, ±t2/2",
    "Общие допуски по ГОСТ 30893.1: H14, h14, ±IT14/2",
    "Общие допуски по ГОСТ 30893.1: + t2, - t2, ±t2/2",
    *(f"ГОСТ 30893.2-{c}" for c in "HKL"),
    "Общие допуски формы и расположения - ГОСТ 30893.2-K",
    "Общие допуски ГОСТ 30893.2-mK",
    *(f"ГОСТ 30893.2-{a}{b}" for a in "fmcv" for b in "HKL"),
]


@pytest.mark.parametrize("text", VALID)
def test_supported_valid_forms(text, parameters):
    result = parse_reference(text, parameters)
    assert result.status == ParseStatus.VALID, result.diagnostics
    assert result.raw_text == text[result.start:result.end]
    assert result.formatting_issues == ()


@pytest.mark.parametrize("dash", ["-", "–", "—", "−"])
@pytest.mark.parametrize("template", ["ГОСТ 30893.1 {dash} m", "ГОСТ 30893.2{dash}K",
                                      "ГОСТ 30893.2{dash}mK", "ГОСТ 30893.1: + t2, {dash} t2, ±t2/2"])
def test_dash_equivalence(template, dash, parameters):
    text = template.format(dash=dash)
    result = parse_reference(text, parameters)
    assert result.status == ParseStatus.VALID
    assert result.raw_text == text
    if template.startswith("ГОСТ 30893.1:"):
        assert "- t2" in result.normalized_text


@pytest.mark.parametrize("text", [
    "ГОСТ 30893.1-m", "ГОСТ 30893.1- m", "ГОСТ 30893.1 -m",
    "ГОСТ 30893.2 - K", "ГОСТ 30893.2- K", "ГОСТ 30893.2 -K",
    "ГОСТ 30893.2 - mK", "ГОСТ 30893.2- mK", "ГОСТ 30893.2 -mK", "ГОСТ 30893.2-m K",
    "ГОСТ 30893.1:H14, h14, ±t2/2", "ГОСТ 30893.1: H14,h14,±t2/2",
    "ГОСТ 30893.1 : H14, h14, ±t2/2", "ГОСТ 30893.1: +t2, -t2, ±t2/2",
    "ГОСТ 30893.1: + t2,- t2,±t2/2", "ГОСТ 30893.1: + t2, - t2, ± t2/2",
])
def test_invalid_spacing_is_recognized_and_preserved(text, parameters):
    result = parse_reference(text, parameters)
    assert result.status == ParseStatus.RECOGNIZED_INVALID
    assert result.raw_text == text
    assert "invalid_spacing" in {d.code for d in result.diagnostics}
    for diagnostic in result.formatting_issues:
        assert text[diagnostic.start:diagnostic.end] == diagnostic.actual


@pytest.mark.parametrize("text,reason", [
    ("ГОСТ 30893.1 - x", "invalid_size_class"), ("ГОСТ 30893.2-M", "invalid_geometry_class"),
    ("ГОСТ 30893.2-xK", "invalid_size_class"), ("ГОСТ 30893.2-mX", "invalid_geometry_class"),
    ("ГОСТ 30893.2-m", "incomplete_combined_reference"), ("ГОСТ 30893.2-", "missing_class"),
    ("ГОСТ 30893.1", "missing_class"), ("ГОСТ 30893.1: H13, h14, ±t2/2", "invalid_reference_format"),
    ("ГОСТ 30893.1: + t2, - t2, ±IT14/2", "invalid_reference_format"),
])
def test_invalid_semantics(text, reason, parameters):
    result = parse_reference(text, parameters)
    assert result.status == ParseStatus.RECOGNIZED_INVALID
    assert reason in {d.code for d in result.diagnostics}


def test_not_a_reference_and_multiple_references(parameters):
    assert parse_reference("ГОСТ 12345", parameters).status == ParseStatus.NOT_A_REFERENCE
    assert find_references("Чертёж без записей общих допусков", parameters) == ()
    result = find_references("ГОСТ 30893.1 - m; ГОСТ 30893.2 - K.", parameters)
    assert len(result) == 2
    assert result[0].status == ParseStatus.VALID
    assert result[1].raw_text == "ГОСТ 30893.2 - K"


@pytest.mark.parametrize("text,expected", [
    ("ГОСТ 30893.2-Н", "ГОСТ 30893.2-H"), ("ГОСТ 30893.2-mК", "ГОСТ 30893.2-mK"),
    ("ГОСТ 30893.1: Н14, h14, ±t2/2", "ГОСТ 30893.1: H14, h14, ±t2/2"),
    ("ГОСТ\u00a030893.1\u00a0-\u00a0m", "ГОСТ 30893.1 - m"),
])
def test_scoped_technical_normalization(text, expected, parameters):
    result = parse_reference(text, parameters)
    assert result.status == ParseStatus.VALID
    assert result.raw_text == text
    assert result.normalized_text == expected
    assert recognition_text("Номер Н14 и -t2") == "Номер Н14 и -t2"


def test_policies_control_validation(parameters):
    parameters["space_policy"]["30893_2_geometry"]["before_separator"] = "required"
    parameters["space_policy"]["30893_2_geometry"]["after_separator"] = "required"
    assert parse_reference("ГОСТ 30893.2 - K", parameters).status == ParseStatus.VALID
    parameters["geometry_classes"] = ["H", "L"]
    assert "invalid_geometry_class" in {d.code for d in parse_reference("ГОСТ 30893.2 - K", parameters).diagnostics}
    parameters["dash_policy"]["accept_hyphen"] = False
    assert parse_reference("ГОСТ 30893.2 - H", parameters).status == ParseStatus.RECOGNIZED_INVALID


@pytest.mark.parametrize("key,value", [("dash_policy", {}), ("space_policy", {}), ("size_classes", []),
                                      ("reference_kinds", ["unknown"]), ("appendix_a", {})])
def test_invalid_policy(key, value, parameters):
    parameters[key] = value
    with pytest.raises(ValueError):
        validate_parameters(parameters)
