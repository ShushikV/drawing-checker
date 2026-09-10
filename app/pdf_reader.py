
from os import PathLike
import pymupdf


def get_page_count(pdf_path: str | PathLike) -> int:
    document = pymupdf.open(pdf_path)
    return len(document)


def extract_text_spans(
    pdf_path: str | PathLike,
    page_index: int = 0,
) -> list[dict]:
    document = pymupdf.open(pdf_path)
    page = document[page_index]
    blocks = page.get_text("dict")["blocks"]

    spans = []

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
