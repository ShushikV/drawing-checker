"""Reconstruct PDF lines without inventing or collapsing whitespace characters."""
from dataclasses import dataclass
from typing import Callable

from app.models import BoundingBox
from app.pdf_reader import TextSpan, extract_text_spans, get_page_count


def union_bbox(spans):
    boxes = [span["bbox"] for span in spans]
    return BoundingBox(min(b[0] for b in boxes), min(b[1] for b in boxes),
                       max(b[2] for b in boxes), max(b[3] for b in boxes))


@dataclass(frozen=True)
class TextLine:
    page_index: int
    text: str
    spans: tuple[TextSpan, ...]
    bbox: BoundingBox
    char_to_span: tuple[int, ...]
    visual_gap_positions: tuple[int, ...] = ()

    def bbox_for(self, start, end):
        selected = sorted(set(self.char_to_span[start:end]))
        return union_bbox([self.spans[index] for index in selected]) if selected else self.bbox


def reconstruct_lines(spans, page_index=0):
    groups = []
    for span in spans:
        if not span["text"]:
            continue
        direction = span.get("direction", (1, 0))
        origin = span.get("origin", (span["bbox"][0], span["bbox"][3]))
        group = None
        for candidate in reversed(groups):
            last = candidate[-1]
            last_direction = last.get("direction", (1, 0))
            last_origin = last.get("origin", (last["bbox"][0], last["bbox"][3]))
            same_native = ("line_index" in span and "line_index" in last and
                (span["block_index"], span["line_index"]) == (last["block_index"], last["line_index"]))
            size = max(span["size"], last["size"])
            gap = span["bbox"][0] - last["bbox"][2]
            close = (abs(origin[1] - last_origin[1]) <= size * 0.2 and -size * 0.15 <= gap <= size)
            if direction == last_direction and (same_native or (direction == (1, 0) and close)):
                group = candidate
                break
        if group is None:
            groups.append([span])
        else:
            group.append(span)
    lines = []
    for group in groups:
        parts, mapping, gaps = [], [], []
        offset = 0
        for index, span in enumerate(group):
            if index:
                previous = group[index - 1]
                gap = span["bbox"][0] - previous["bbox"][2]
                if (gap >= max(previous["size"], span["size"]) * 0.2
                        and not previous["text"][-1].isspace() and not span["text"][0].isspace()):
                    gaps.append(offset)
            parts.append(span["text"])
            mapping.extend([index] * len(span["text"]))
            offset += len(span["text"])
        lines.append(TextLine(page_index, "".join(parts), tuple(group), union_bbox(group), tuple(mapping), tuple(gaps)))
    return tuple(lines)


def extract_lines(pdf_path, region_filter: Callable[[TextLine], bool] | None = None):
    """Search the entire text layer by default; future TT-region filtering is explicit."""
    for page_index in range(get_page_count(pdf_path)):
        for line in reconstruct_lines(extract_text_spans(pdf_path, page_index), page_index):
            if region_filter is None or region_filter(line):
                yield line
