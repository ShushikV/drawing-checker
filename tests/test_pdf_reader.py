
import pytest

from pathlib import Path

from app.pdf_reader import (
    extract_text_spans,
    get_page_count,
    get_page_size,
    render_page,
    pixmap_to_image,
)


TEST_PDF_PATH = Path(__file__).parent / "fixtures" / "Корпус хабмотора.pdf"

def test_get_page_count():
    pdf_path = TEST_PDF_PATH

    assert get_page_count(pdf_path) == 1

def test_extract_text_spans():
    pdf_path = TEST_PDF_PATH

    spans = extract_text_spans(pdf_path)

    assert len(spans) == 68

def test_extract_text_contains_hole_note():
    pdf_path = TEST_PDF_PATH

    spans = extract_text_spans(pdf_path)
    texts = [span["text"] for span in spans]

    assert "6 отв.M3" in texts

def test_extract_text_spans_invalid_page():
    with pytest.raises(IndexError):
        extract_text_spans(TEST_PDF_PATH, page_index=1)

def test_extract_text_span_structure():
    spans = extract_text_spans(TEST_PDF_PATH)

    first_span = spans[0]

    assert "text" in first_span
    assert "font" in first_span
    assert "size" in first_span
    assert "bbox" in first_span
    assert len(first_span["bbox"]) == 4
    assert isinstance(first_span["text"], str)
    assert isinstance(first_span["font"], str)
    assert isinstance(first_span["size"], float)
    assert isinstance(first_span["bbox"], tuple)

def test_get_page_size():
    width, height = get_page_size(TEST_PDF_PATH)

    assert width > 0
    assert height > 0


def test_render_resolution_and_rgb():
    base = render_page(TEST_PDF_PATH)
    enlarged = render_page(TEST_PDF_PATH, zoom=2)
    assert abs(enlarged.width - base.width * 2) <= 1
    assert abs(enlarged.height - base.height * 2) <= 1
    image = pixmap_to_image(enlarged)
    assert image.mode == "RGB"
    assert image.size == (enlarged.width, enlarged.height)
    assert image.tobytes() == enlarged.samples


@pytest.mark.parametrize("zoom", [0, -1, float("inf"), float("nan")])
def test_invalid_zoom(zoom):
    with pytest.raises(ValueError):
        render_page(TEST_PDF_PATH, zoom=zoom)


def test_render_invalid_page():
    with pytest.raises(IndexError):
        render_page(TEST_PDF_PATH, page_index=1)
