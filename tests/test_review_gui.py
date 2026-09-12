import tkinter as tk

import pytest

from app.standards.review_gui import ReviewWindow
from app.standards.verification_models import ReviewStatus


@pytest.fixture
def review_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_window_list_selection_edit_save_filter(review_root, review_project):
    p = review_project
    window = ReviewWindow(review_root, p.service)
    review_root.update()
    assert len(window.document_list.get_children()) == 1
    assert len(window.clause_list.get_children()) == 3
    assert window.state_data.candidate.id == p.clause_id
    assert window.current_status.get() == "candidate"
    assert window.raw_text.get("1.0", "end-1c") == p.imported.clauses[0].source_text
    assert window.preview.canvas.find_withtag("source_image")
    assert not window.preview.canvas.find_withtag("overlay")
    window.operator.set("GUI test reviewer")
    window.verified_text.delete("1.0", "end")
    window.verified_text.insert("1.0", "Synthetic manual correction")
    window.fields["title"].set("Corrected test title")
    window.fields["page_end"].set("2")
    window.goto_page("page_end")
    assert window.preview.page == 2
    window.buttons["save"].invoke()
    review_root.update()
    assert p.service.get_state(p.clause_id).status == ReviewStatus.NEEDS_REVIEW
    assert "needs_review" in window.current_status.get()
    window.buttons["verify"].invoke()
    review_root.update()
    revision = p.service.require_verified(p.clause_id)
    assert revision.verified_text == "Synthetic manual correction"
    assert revision.title == "Corrected test title"
    assert revision.verified_by == "GUI test reviewer"
    window.filter_status.set("verified")
    window.filter.event_generate("<<ComboboxSelected>>")
    review_root.update()
    assert window.clause_list.get_children() == (p.clause_id,)
    window.filter_status.set("candidate")
    window.refresh_clauses()
    review_root.update()
    assert len(window.clause_list.get_children()) == 2
    chosen = window.clause_list.get_children()[-1]
    window.clause_list.selection_set(chosen)
    review_root.update()
    assert window.state_data.candidate.id == chosen


def test_missing_pdf_fallback_and_offline_save(review_root, review_project):
    p = review_project
    p.source.unlink()
    window = ReviewWindow(review_root, p.service)
    review_root.update()
    assert "Исходный PDF недоступен локально" in window.preview.message.get()
    assert window.raw_text.get("1.0", "end-1c")
    assert window.normalized_text.get("1.0", "end-1c")
    window.operator.set("Offline GUI test reviewer")
    window.buttons["review"].invoke()
    assert p.service.get_state(p.clause_id).status == ReviewStatus.NEEDS_REVIEW


def test_gui_rejects_missing_operator_and_guards_unsaved_edits(review_root, review_project):
    p = review_project
    window = ReviewWindow(review_root, p.service)
    review_root.update()
    window.buttons["verify"].invoke()
    assert "Не сохранено" in window.message.get()
    assert p.service.history(p.clause_id) == ()
    window.verified_text.insert("end", " unsaved test edit")
    window.clause_list.selection_set(p.imported.clauses[1].id)
    review_root.update()
    assert window.state_data.candidate.id == p.clause_id
    assert "Сохраните" in window.message.get()
