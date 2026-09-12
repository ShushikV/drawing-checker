"""Recognition-only transforms preserve character counts and all spacing evidence."""
from dataclasses import dataclass
import re


DASH_FLAGS = {"-": "accept_hyphen", "\u00ad": "accept_hyphen", "–": "accept_en_dash", "—": "accept_em_dash", "−": "accept_minus_sign"}


def recognition_text(text):
    # Some PDF font maps extract a printed hyphen as U+00AD. Keep its position;
    # never delete it as a discretionary line break.
    return text.translate(str.maketrans({"\u00a0": " ", "\u202f": " ", "\u00ad": "-", "–": "-", "—": "-", "−": "-"}))


def technical_symbol(text):
    # Only complete technical tokens, never general prose or all Cyrillic text.
    return {"Н14": "H14", "t₂": "t2", "IT₁₄": "IT14"}.get(text, text)


def geometry_symbol(text):
    return {"Н": "H", "К": "K"}.get(text, text)


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def tokens(text, start, end):
    """Whitespace is not a token, but its exact original interval is never discarded."""
    return tuple(Token(m.group(), start + m.start(), start + m.end())
                 for m in re.finditer(r"[^\W_]+|[^\s]", text[start:end]))
