"""Validate the data contract; no normative parameters are embedded in the analyzer."""
from copy import deepcopy
import json
from pathlib import Path

from app.analysis.general_tolerances.models import ReferenceKind
from app.analysis.general_tolerances.normalization import DASH_FLAGS


PROFILE_PATH = Path(__file__).resolve().parents[3] / "config/general_tolerances.project.json"


def project_parameters():
    """User-supplied stage-6 specification, NOT an activated normative RuleDefinition."""
    return deepcopy(json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["parameters"])


def validate_parameters(parameters):
    required = {"reference_kinds", "size_classes", "geometry_classes", "dash_policy", "space_policy", "appendix_a"}
    if not isinstance(parameters, dict) or set(parameters) != required:
        raise ValueError("general tolerances parameters must contain: " + ", ".join(sorted(required)))
    kinds = parameters["reference_kinds"]
    if not isinstance(kinds, list) or not kinds or len(set(kinds)) != len(kinds):
        raise ValueError("reference_kinds must be a non-empty unique list")
    for kind in kinds:
        ReferenceKind(kind)
    for key, upper in (("size_classes", False), ("geometry_classes", True)):
        values = parameters[key]
        if (not isinstance(values, list) or not values or len(set(values)) != len(values)
                or any(not isinstance(v, str) or len(v) != 1 or not v.isascii() or not v.isalpha()
                       or v.isupper() != upper for v in values)):
            raise ValueError(f"{key}: expected unique single ASCII class letters in the appropriate case")
    dash = parameters["dash_policy"]
    if not isinstance(dash, dict) or set(dash) != set(DASH_FLAGS.values()) or any(type(v) is not bool for v in dash.values()):
        raise ValueError("dash_policy must explicitly specify the four boolean acceptance flags")
    slots = {
        ReferenceKind.SIZE: {"keyword_to_number", "before_separator", "after_separator"},
        ReferenceKind.GEOMETRY: {"keyword_to_number", "before_separator", "after_separator"},
        ReferenceKind.COMBINED: {"keyword_to_number", "before_separator", "after_separator", "between_classes"},
        ReferenceKind.APPENDIX_1: {"keyword_to_number", "before_colon", "after_colon", "after_comma", "plus_minus_to_t", "before_slash", "after_slash"},
        ReferenceKind.APPENDIX_2: {"keyword_to_number", "before_colon", "after_colon", "after_comma", "plus_to_t", "minus_to_t", "plus_minus_to_t", "before_slash", "after_slash"},
    }
    space = parameters["space_policy"]
    if not isinstance(space, dict):
        raise ValueError("space_policy must be an object")
    for kind in ReferenceKind:
        if kind not in space or set(space[kind]) != slots[ReferenceKind(kind)]:
            raise ValueError(f"space_policy missing/unknown slots for {kind}")
        if any(value not in ("required", "forbidden") for value in space[kind].values()):
            raise ValueError("space_policy values must be required or forbidden")
    appendix = parameters["appendix_a"]
    if not isinstance(appendix, dict) or set(appendix) != {"hole", "shaft", "symmetric", "unilateral", "denominator"}:
        raise ValueError("appendix_a requires hole, shaft, symmetric, unilateral, denominator")
    for key in ("hole", "shaft", "symmetric", "unilateral"):
        if not isinstance(appendix[key], list) or not appendix[key] or any(not isinstance(v, str) or not v.isalnum() for v in appendix[key]):
            raise ValueError(f"appendix_a.{key}: expected nonempty technical token list")
    if not isinstance(appendix["denominator"], str) or not appendix["denominator"].isdigit():
        raise ValueError("appendix_a.denominator must be a digit string")
