"""Conservative normalization: line endings and a leading BOM only."""
import re

from app.standards.import_types import ImportedPage, LinePosition, NormalizedPage


class TextNormalizer:
    version = "line-endings-bom/1"

    def normalize(self, page: ImportedPage) -> NormalizedPage:
        source = page.source_text
        lines = []
        chunks = []
        source_start = 0
        normalized_start = 0
        # Do not strip spaces, join hyphenated words, alter spelling or Unicode glyphs.
        for match in re.finditer(r"[^\r\n]*(?:\r\n|\r|\n|$)", source):
            raw = match.group()
            if not raw:
                continue
            text = raw.replace("\r\n", "\n").replace("\r", "\n")
            if source_start == 0:
                text = text.removeprefix("\ufeff")
            chunks.append(text)
            lines.append(LinePosition(source_start, match.end(), normalized_start,
                                      normalized_start + len(text)))
            source_start = match.end()
            normalized_start += len(text)
        return NormalizedPage(page.page, source, "".join(chunks), tuple(lines))
