
from os import PathLike
from typing import TypedDict

import pymupdf

class TextSpan(TypedDict):
    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]

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

