"""Heuristic numbered-clause candidates; never an authoritative GOST parser."""
import re
from typing import Protocol, Sequence

from app.standards.import_types import ClauseExtraction, ImportDiagnostic, NormalizedPage
from app.standards.models import ClauseSourceSpan, StandardClause


class ClauseExtractor(Protocol):
    version: str

    def extract(self, document_id: str, pages: Sequence[NormalizedPage]) -> ClauseExtraction: ...


class NumberedClauseExtractor:
    version = "numbered-candidates/1"
    heading = re.compile(r"^([1-9]\d*(?:\.\d+)*)[ \t]+(\S.*)$")

    def extract(self, document_id, pages):
        clauses = []
        diagnostics = []
        seen = set()
        current_number = None
        fragments = []

        def flush():
            nonlocal current_number, fragments
            if current_number is not None:
                spans = tuple(ClauseSourceSpan(page.page, first.source_start, last.source_end,
                    first.normalized_start, last.normalized_end) for page, first, last in fragments)
                clauses.append(StandardClause(
                    id=f"{document_id}::clause::{current_number}", document_id=document_id,
                    clause_number=current_number,
                    source_text="\n".join(page.source_text[first.source_start:last.source_end]
                                           for page, first, last in fragments),
                    normalized_text="\n".join(page.normalized_text[first.normalized_start:last.normalized_end]
                                               for page, first, last in fragments),
                    page=spans[0].page, page_end=spans[-1].page, source_spans=spans,
                    metadata={"review_required": True, "extractor_version": self.version},
                ))
            current_number, fragments = None, []

        for page in pages:
            if not page.normalized_text.strip():
                flush()
                diagnostics.append(ImportDiagnostic("empty_page", "No text on page; OCR may be required. Continuation stopped.", page.page))
                continue
            for line_number, position in enumerate(page.lines, 1):
                text = page.normalized_text[position.normalized_start:position.normalized_end].strip()
                match = self.heading.fullmatch(text)
                numeric_start = bool(re.match(r"^\d", text))
                ambiguous = numeric_start and (match is None or ".." in text or
                    re.fullmatch(r"[\d\s.,%+−-]+", match[2]) is not None)
                if match and match[1] in seen:
                    ambiguous = True
                if ambiguous:
                    flush()
                    diagnostics.append(ImportDiagnostic("ambiguous_numbered_fragment",
                        "Numbered fragment is ambiguous or repeated; left unassigned in page text.", page.page, line_number))
                    continue
                if match:
                    flush()
                    current_number = match[1]
                    seen.add(current_number)
                    diagnostics.append(ImportDiagnostic("clause_candidate",
                        f"Clause {current_number} is a heuristic candidate and requires human review.", page.page, line_number))
                if current_number is None:
                    if text:
                        diagnostics.append(ImportDiagnostic("unassigned_text",
                            "Fragment is retained in page text but not assigned to a clause.", page.page, line_number))
                    continue
                if fragments and fragments[-1][0].page == page.page:
                    old_page, first, _ = fragments[-1]
                    fragments[-1] = (old_page, first, position)
                else:
                    if fragments:
                        diagnostics.append(ImportDiagnostic("page_continuation_candidate",
                            f"Unnumbered text continues clause {current_number} on a new page; verify headers and footers.",
                            page.page, line_number))
                    fragments.append((page, position, position))
        flush()
        return ClauseExtraction(tuple(clauses), tuple(diagnostics))
