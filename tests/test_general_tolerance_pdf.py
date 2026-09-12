"""All normative sources and confirmations here are explicitly synthetic test fixtures."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk

import pymupdf
import pytest

from app.analysis import AnalysisContext
from app.analysis.general_tolerances.analyzer import CHECK_TYPE, GeneralToleranceAnalyzer
from app.analysis.general_tolerances.lines import reconstruct_lines, extract_lines
from app.analysis.general_tolerances.policy import project_parameters
from app.analysis.general_tolerances.normalization import recognition_text
from app.analysis.general_tolerances.runtime import check_drawing
from app.analysis.normative import AnalyzerRegistry, RuleBindingError
from app.pdf_reader import extract_text_spans
from app.standards import NormativeRegistry, StandardStatus
from app.standards.general_tolerance_rules import AppendixClauseExtractor, SOURCES, build_rules, publish_rules
from app.standards.importer import StandardPdfImporter
from app.standards.processed_writer import write_processed
from app.standards.verification_service import VerificationService
from app.viewer import PdfViewer


@pytest.fixture
def family_root(tmp_path):
    root = tmp_path / "standards"
    source = root / "source"
    source.mkdir(parents=True)
    for document_id, (filename, designation, _) in SOURCES.items():
        path = source / filename
        text = ("6 TEST FIXTURE ONLY\nNo normative text.\nA.4 TEST FIXTURE ONLY\nNo normative text."
                if "-1-" in document_id else "7.1 TEST FIXTURE ONLY\nNo normative text.\n7.2 TEST FIXTURE ONLY\nNo normative text.")
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((40, 40), text)
            pdf.save(path)
        imported = StandardPdfImporter(clause_extractor=AppendixClauseExtractor()).import_pdf(
            path, document_id=document_id, designation=designation, title="TEST FIXTURE ONLY — not a standard",
            version="2002", metadata={"test_only": True})
        write_processed(replace(imported, document=replace(imported.document, status=StandardStatus.ACTIVE)), root)
    return root


def verify_test_sources(root):
    service = VerificationService(root)
    for document_id in SOURCES:
        for state in service.list_clauses(document_id):
            service.verify(state.candidate.id, verified_by="SYNTHETIC TEST OPERATOR")


@pytest.fixture
def drawing(tmp_path):
    fonts = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((path for path in fonts if path.is_file()), None)
    if font_path is None:
        pytest.skip("A Cyrillic-capable font is required for this PDF integration fixture")
    font = pymupdf.Font(fontfile=str(font_path))
    path = tmp_path / "synthetic-drawing.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=800, height=500)
        for row, text in enumerate(["ГОСТ 30893.2-mK", "ГОСТ 30893.2 - mK", "ГОСТ 30893.1 - x"]):
            page.insert_text((40, 40 + row * 40), text, fontname="test", fontfile=str(font_path), fontsize=12)
        x = 40
        for index, text in enumerate(["ГОСТ ", "30893.2", "-mK"]):
            page.insert_text((x, 180), text, fontname="test", fontfile=str(font_path), fontsize=12,
                             color=(index / 3, 0, 0))
            x += font.text_length(text, fontsize=12)
        pdf.save(path)
    return path


def test_pdf_extraction_reconstruction_and_analysis(drawing):
    spans = extract_text_spans(drawing)
    lines = tuple(extract_lines(drawing))
    assert len(lines) == 4
    split = lines[-1]
    assert recognition_text(split.text) == "ГОСТ 30893.2-mK"
    assert split.text == "".join(span["text"] for span in split.spans)
    assert len(split.spans) >= 3
    assert len(set(split.char_to_span)) >= 3
    assert len(split.char_to_span) == len(split.text)
    results = list(GeneralToleranceAnalyzer().analyze(AnalysisContext(drawing), parameters=project_parameters()))
    assert len(results) == 2
    assert {r.metadata["reasons"][0] for r in results} == {"invalid_spacing", "invalid_size_class"}
    for result in results:
        line = next(line for line in lines if line.text == result.metadata["raw_text"])
        assert result.locations[0].bbox == line.bbox
        assert result.locations[0].page_index == 0
    assert sum(len(line.spans) for line in lines) == len(spans)


def test_no_fabricated_spaces_and_mapping():
    spans = [dict(text="ГОСТ ", size=10.0, font="test", bbox=(0, 0, 25, 10)),
             dict(text="30893.2", size=10.0, font="test", bbox=(25, 0, 65, 10)),
             dict(text="-mK", size=10.0, font="test", bbox=(65, 0, 85, 10))]
    line = reconstruct_lines(spans)[0]
    assert line.text == "ГОСТ 30893.2-mK"
    assert line.char_to_span[:5] == (0,) * 5
    assert line.bbox_for(5, len(line.text)).x0 == 25
    spans[1]["bbox"] = (28, 0, 65, 10)
    spans[0]["text"] = "ГОСТ"
    line = reconstruct_lines(spans)[0]
    assert line.text == "ГОСТ30893.2-mK"
    assert line.visual_gap_positions == (4,)


def test_missing_base_and_no_unverified_rule_publication(family_root, drawing):
    catalog = NormativeRegistry.from_directory(family_root)
    assert catalog.find_rules() == ()
    with pytest.raises(ValueError, match="verified"):
        build_rules(catalog, VerificationService(family_root))
    report = check_drawing(drawing, family_root)
    assert not report.ready and report.issues == []
    assert "не выполнена" in report.message
    assert not (family_root / "rules/general_tolerances").exists()


def test_verified_vertical_slice_and_viewer(family_root, drawing):
    verify_test_sources(family_root)
    definitions = publish_rules(family_root)
    assert len(definitions) == 4
    report = check_drawing(drawing, family_root)
    assert report.ready, report.message
    assert len(report.issues) == 2
    for issue in report.issues:
        assert "TEST FIXTURE ONLY" in issue.requirements[0].excerpt
        assert issue.metadata["normative"]["verified_clauses"][0]["verified_by"] == "SYNTHETIC TEST OPERATOR"
        assert issue.metadata["analysis"]["raw_text"] in issue.description
        assert issue.metadata["analysis"]["expected_format"] in issue.description
    root = tk.Tk()
    root.withdraw()
    try:
        viewer = PdfViewer(root, drawing, report.issues, analysis_message=report.message)
        root.update()
        assert len(viewer.canvas.find_withtag("issue_region")) == 2
        viewer.select_issue(report.issues[0].id)
        assert viewer.canvas.find_withtag("active")
        viewer.zoom(SimpleNamespace(x=100, y=100, delta=120))
        assert len(viewer.canvas.find_withtag("issue_region")) == 2
        assert "TEST FIXTURE ONLY" in viewer.issue_panel.details.get("1.0", "end")
    finally:
        root.destroy()


def test_family_binding_requires_verification_and_pinned_revision(family_root, drawing):
    verify_test_sources(family_root)
    publish_rules(family_root)
    catalog = NormativeRegistry.from_directory(family_root)
    rule = catalog.get_rule("eskd.general_tolerances.size")
    registry = AnalyzerRegistry()
    registry.register(CHECK_TYPE, GeneralToleranceAnalyzer())
    with pytest.raises(RuleBindingError, match="manual clause verification"):
        registry.bind(rule.id, catalog)
    service = VerificationService(family_root)
    bound = registry.bind(rule.id, catalog, verification_service=service)
    service.verify(rule.clause_ids[0], verified_by="SYNTHETIC TEST OPERATOR", changes={"verified_text": "Changed test text"})
    with pytest.raises(RuleBindingError, match="revision changed"):
        bound.analyze(AnalysisContext(drawing))
    assert not check_drawing(drawing, family_root).ready


def test_no_reference_is_not_an_error(tmp_path):
    path = tmp_path / "no-reference.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 40), "TEST DRAWING ONLY")
        pdf.save(path)
    assert list(GeneralToleranceAnalyzer().analyze(AnalysisContext(path), parameters=project_parameters())) == []


def test_production_catalog_stays_empty():
    catalog = NormativeRegistry.from_directory(Path(__file__).resolve().parents[1] / "standards")
    assert not [rule for rule in catalog.find_rules() if rule.check_type == CHECK_TYPE]
