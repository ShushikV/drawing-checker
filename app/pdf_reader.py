
from os import PathLike
from math import isfinite
from typing import TypedDict
from PIL import Image

import pymupdf

class TextSpan(TypedDict):
    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]


def get_page_geometry(pdf_path: str | PathLike, page_index: int = 0):
    """Unrotated dimensions and transform to the rotated rendered page."""
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        return page.cropbox.width, page.cropbox.height, tuple(page.rotation_matrix)

def get_page_count(pdf_path: str | PathLike) -> int:
    with pymupdf.open(pdf_path) as document:
        return len(document)

def get_page_size(
    pdf_path: str | PathLike,
    page_index: int = 0,
) -> tuple[float, float]:
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        return page.rect.width, page.rect.height

def extract_text_spans(
    pdf_path: str | PathLike,
    page_index: int = 0,
) -> list[TextSpan]:
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]
        blocks = page.get_text("dict")["blocks"]

    spans: list[TextSpan] = []

    for block in blocks:
        if block.get("type") != 0:
            continue

        for line in block["lines"]:
            for span in line["spans"]:
                spans.append(
                    {
                        "text": span["text"],
                        "font": span["font"],
                        "size": span["size"],
                        "bbox": span["bbox"],
                    }
                )

    return spans

def render_page(
    pdf_path: str | PathLike,
    page_index: int = 0,
    zoom: float = 1.0,
) -> pymupdf.Pixmap:
    if not isfinite(zoom) or zoom <= 0:
        raise ValueError("Zoom must be finite and positive")
    with pymupdf.open(pdf_path) as document:
        page = document[page_index]

        matrix = pymupdf.Matrix(zoom, zoom)

        return page.get_pixmap(
            matrix=matrix,
            colorspace=pymupdf.csRGB,
            alpha=False,
        )

def pixmap_to_image(pixmap: pymupdf.Pixmap) -> Image.Image:
    return Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )
