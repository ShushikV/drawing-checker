"""Integration tests use real Tk widgets and a small generated PDF."""
import tkinter as tk
from types import SimpleNamespace

import pymupdf
import pytest

from app.viewer import PdfViewer
from app.models import BoundingBox, DrawingIssue, IssueLocation, IssueStatus, RequirementReference
from app.demo_issues import create_demo_issues


@pytest.fixture
def root():
    window = tk.Tk()
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "drawing.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=1400, height=1000)
        page.insert_text((100, 100), "Drawing")
        doc.save(path)
    return path


def test_render_zoom_pan_close(root, pdf):
    viewer = PdfViewer(root, pdf)
    root.update()
    canvas = viewer.canvas
    assert canvas.image.width() == 1400
    event = SimpleNamespace(x=200, y=200, delta=120)
    old_point = canvas.canvasx(200)
    viewer.zoom(event)
    assert viewer.zoom_scale == pytest.approx(1.2)
    assert canvas.image.width() == 1680
    assert canvas.canvasx(200) / viewer.zoom_scale == pytest.approx(old_point, abs=2)
    viewer.start_pan(event)
    before = canvas.canvasx(0)
    viewer.pan(SimpleNamespace(x=100, y=100))
    assert canvas.canvasx(0) > before
    viewer.stop_pan(event)
    assert canvas.cget("cursor") == ""
    viewer.zoom(SimpleNamespace(x=200, y=200, delta=-120))
    assert viewer.zoom_scale == pytest.approx(1)
    viewer.close()
    assert not viewer.winfo_exists()
    assert root.state() == "normal"


@pytest.mark.parametrize("scale,delta", [(5.0, 120), (0.2, -120), (1.0, 0)])
def test_zoom_limits(root, pdf, monkeypatch, scale, delta):
    viewer = PdfViewer(root, pdf)
    viewer.zoom_scale = scale
    monkeypatch.setattr(viewer, "render_drawing", lambda: pytest.fail("Unnecessary render"))
    viewer.zoom(SimpleNamespace(x=20, y=20, delta=delta))
    assert viewer.zoom_scale == scale


def test_failed_open_removes_partial_window(root, tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"invalid PDF")
    with pytest.raises(pymupdf.FileDataError):
        PdfViewer(root, path)
    assert root.winfo_children() == []


def test_failed_zoom_keeps_image_and_scale(root, pdf, monkeypatch):
    viewer = PdfViewer(root, pdf)
    previous = viewer.canvas.image

    def fail(*args, **kwargs):
        raise OSError("Cannot read PDF")

    errors = []
    monkeypatch.setattr("app.viewer.render_page", fail)
    monkeypatch.setattr("app.viewer.messagebox.showerror", lambda *a, **kw: errors.append(a))
    viewer.zoom(SimpleNamespace(x=20, y=20, delta=120))
    assert viewer.zoom_scale == 1
    assert viewer.canvas.image is previous
    assert len(errors) == 1


def test_issue_list_selection_status_and_overlays(root, pdf):
    issues = create_demo_issues(pdf)
    viewer = PdfViewer(root, pdf, issues, demo=True)
    root.update()
    panel = viewer.issue_panel
    assert len(panel.tree.get_children()) == 4
    assert panel.tree.item(issues[0].id, "text") == "1. Демо: одна область"
    assert panel.tree.item(issues[0].id, "values") == ("error", "Открыто")
    assert len(viewer.canvas.find_withtag("issue_region")) == 3
    panel.tree.selection_set(issues[1].id)
    root.update()
    assert viewer.active_issue_id == issues[1].id
    assert len(viewer.canvas.find_withtag("active")) == 6
    assert issues[1].description in panel.details.get("1.0", "end")
    panel.button.invoke()
    assert issues[1].status == IssueStatus.DONE
    assert panel.tree.item(issues[1].id, "values")[1] == "Выполнено"
    assert panel.button.cget("text") == "Вернуть ошибку"
    panel.button.invoke()
    assert issues[1].status == IssueStatus.OPEN
    viewer.select_issue(issues[0].id)
    assert "Демонстрационное требование" in panel.details.get("1.0", "end")


def test_coordinates_navigation_and_zoom_overlay_persistence(root, pdf):
    box = BoundingBox(1100, 800, 1200, 900)
    issue = DrawingIssue("test", "Far region", "Description", (IssueLocation(0, box),))
    viewer = PdfViewer(root, pdf, [issue])
    root.update()
    assert viewer.pdf_bbox_to_canvas(box) == (1100, 800, 1200, 900)
    viewer.select_issue(issue.id)
    canvas = viewer.canvas
    assert canvas.canvasx(0) <= 1100 < 1200 <= canvas.canvasx(canvas.winfo_width())
    assert canvas.canvasy(0) <= 800 < 900 <= canvas.canvasy(canvas.winfo_height())
    viewer.zoom(SimpleNamespace(x=200, y=200, delta=120))
    assert len(canvas.find_withtag("pdf_image")) == 1
    regions = canvas.find_withtag("issue_region")
    assert len(regions) == 1
    assert canvas.coords(regions[0]) == pytest.approx([1320, 960, 1440, 1080])
    assert "active" in canvas.gettags(regions[0])
    viewer.render_drawing()
    assert len(canvas.find_withtag("overlay")) == 3
    assert len(canvas.find_withtag("pdf_image")) == 1


@pytest.mark.parametrize("locations,expected", [
    ((), "ко всему документу"),
    ((IssueLocation(1, BoundingBox(10, 10, 20, 20)),), "Навигация по страницам ещё не реализована"),
    ((IssueLocation(0),), "нет области для выделения"),
])
def test_unlocated_and_other_page_issues(root, pdf, locations, expected):
    issue = DrawingIssue("test", "Notice", "Description", locations,
                         (RequirementReference("Example", "Section", "https://example.com"),))
    viewer = PdfViewer(root, pdf, [issue])
    root.update()
    before = viewer.canvas.xview(), viewer.canvas.yview()
    viewer.select_issue(issue.id)
    assert viewer.active_issue_id == issue.id
    assert viewer.canvas.find_withtag("overlay") == ()
    assert (viewer.canvas.xview(), viewer.canvas.yview()) == before
    details = viewer.issue_panel.details.get("1.0", "end")
    assert expected in details
    assert "https://example.com" in details
    viewer.issue_panel.button.invoke()
    assert issue.status == IssueStatus.DONE


@pytest.mark.parametrize("rotation,expected", [
    (0, (10, 20, 50, 70)), (90, (230, 10, 280, 50)),
    (180, (350, 230, 390, 280)), (270, (20, 350, 70, 390)),
])
def test_rotated_page_coordinates(root, tmp_path, rotation, expected):
    path = tmp_path / "rotated.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.set_rotation(rotation)
        doc.save(path)
    viewer = PdfViewer(root, path)
    assert viewer.pdf_bbox_to_canvas(BoundingBox(10, 20, 50, 70)) == expected
    viewer.zoom_scale = 2
    assert viewer.pdf_bbox_to_canvas(BoundingBox(10, 20, 50, 70)) == tuple(v * 2 for v in expected)


def test_mixed_page_locations_and_completed_style(root, pdf):
    issue = DrawingIssue("test", "Mixed", "Description", (
        IssueLocation(0, BoundingBox(20, 20, 100, 100)),
        IssueLocation(2, BoundingBox(30, 30, 100, 100))), status=IssueStatus.DONE)
    viewer = PdfViewer(root, pdf, [issue])
    region = viewer.canvas.find_withtag("issue_region")[0]
    assert viewer.canvas.itemcget(region, "outline") == "#28783c"
    assert viewer.canvas.itemcget(region, "dash")
    viewer.select_issue(issue.id)
    assert "Страницы: 3" in viewer.issue_panel.details.get("1.0", "end")
    assert len(viewer.canvas.find_withtag("issue_region")) == 1


def test_extended_requirement_reference_is_displayed(root, pdf):
    reference = RequirementReference("TEST-DOCUMENT", "TEST-A", document_id="test.v1",
                                     document_version="test-edition", clause_id="test.clause",
                                     excerpt="Test-only excerpt, no normative requirement", page=7)
    issue = DrawingIssue("test", "Test reference", "Test only", requirements=(reference,))
    viewer = PdfViewer(root, pdf, [issue])
    viewer.select_issue(issue.id)
    details = viewer.issue_panel.details.get("1.0", "end")
    assert "TEST-DOCUMENT" in details
    assert "TEST-A" in details
    assert "Редакция: test-edition" in details
    assert "Стр. 7" in details
    assert reference.excerpt in details
