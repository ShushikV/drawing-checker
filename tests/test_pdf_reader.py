
from app.pdf_reader import extract_text_spans, get_page_count


def test_get_page_count():
    pdf_path = "tests/fixtures/Корпус хабмотора.pdf"

    assert get_page_count(pdf_path) == 1

def test_extract_text_spans():
    pdf_path = "tests/fixtures/Корпус хабмотора.pdf"

    spans = extract_text_spans(pdf_path)

    assert len(spans) == 68

def test_extract_text_contains_hole_note():
    pdf_path = "tests/fixtures/Корпус хабмотора.pdf"

    spans = extract_text_spans(pdf_path)
    texts = [span["text"] for span in spans]

    assert "6 отв.M3" in texts