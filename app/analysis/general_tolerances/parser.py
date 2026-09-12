"""Small token grammar: recognition is distinct from class and spacing validation."""
import re

from app.analysis.general_tolerances.models import GeneralToleranceReference, FormattingDiagnostic, ParseStatus, ReferenceKind
from app.analysis.general_tolerances.normalization import DASH_FLAGS, Token, geometry_symbol, recognition_text, technical_symbol, tokens
from app.analysis.general_tolerances.policy import validate_parameters


ANCHOR = re.compile(r"(?<!\w)(?P<keyword>Г[ОO][СC][ТT])(?P<gap>[ \t]*)(?P<standard>30893\.[12])(?![\d.])", re.IGNORECASE)
SLOT_LABELS = {
    "keyword_to_number": "Между ГОСТ и номером", "before_separator": "Перед разделителем",
    "after_separator": "После разделителя", "between_classes": "Между обозначениями классов",
    "before_colon": "Перед двоеточием", "after_colon": "После двоеточия",
    "after_comma": "После запятой", "plus_to_t": "Между + и обозначением допуска",
    "minus_to_t": "Между минусом и обозначением допуска", "plus_minus_to_t": "Между ± и обозначением допуска",
    "before_slash": "Перед /", "after_slash": "После /",
}


class _Parser:
    def __init__(self, raw, match, limit, parameters):
        self.raw, self.text, self.match, self.p = raw, recognition_text(raw), match, parameters
        self.items = tokens(self.text, match.end(), limit)
        self.index = 0
        self.end = match.end()
        self.spaces, self.errors = [], []
        self.kind = None
        self.size = self.geometry = self.variant = None
        self.expected = ""
        self.canonical_replacements = []

    def error(self, code, field, token, message):
        self.errors.append(FormattingDiagnostic(code, field, message, token.start, token.end, self.raw[token.start:token.end]))

    def take(self, symbol=None):
        if self.index >= len(self.items):
            token = Token("", self.end, self.end)
        else:
            token = self.items[self.index]
            self.index += 1
            self.end = token.end
        if symbol is not None and token.text != symbol:
            self.error("invalid_reference_format", "syntax", token, f"Ожидается символ {symbol!r}.")
        return token

    def peek(self):
        return self.items[self.index] if self.index < len(self.items) else Token("", self.end, self.end)

    def spacing(self, slot, start, end):
        policy = self.p["space_policy"][self.kind.value][slot]
        actual = self.raw[start:end]
        valid = bool(actual) and all(c in " \t\u00a0\u202f" for c in actual) if policy == "required" else not actual
        if not valid:
            self.spaces.append(FormattingDiagnostic("invalid_spacing", slot,
                SLOT_LABELS[slot] + ": " + ("требуется пробел" if policy == "required" else "пробелы не допускаются"),
                start, end, actual, policy))

    def dash(self, token):
        if token.text != "-":
            self.error("invalid_reference_format", "separator", token, "Отсутствует разделитель записи.")
        elif not self.p["dash_policy"].get(DASH_FLAGS.get(self.raw[token.start:token.end], ""), False):
            self.error("invalid_reference_format", "dash_policy", token, "Этот разделитель не разрешён параметрами правила.")

    def allowed(self, token, values, code, field, canonical=None):
        value = canonical if canonical is not None else token.text
        if value not in values:
            self.error(code, field, token, "Допустимые обозначения: " + ", ".join(values))
        elif value != token.text:
            self.canonical_replacements.append((token.start, token.end, value))
        return value

    def spelling(self, value, values):
        return value if value in values else "<" + "|".join(values) + ">"

    def separator_form(self, standard):
        sep = self.take()
        self.dash(sep)
        first = self.take()
        if not first.text or not first.text.isalpha():
            self.kind = ReferenceKind.SIZE if standard.endswith("1") else ReferenceKind.GEOMETRY
            self.error("missing_class" if not first.text else "invalid_reference_format", "class", first, "Не указан допустимый класс записи.")
        elif standard.endswith("1"):
            self.kind = ReferenceKind.SIZE
            self.size = self.allowed(first, self.p["size_classes"], "invalid_size_class", "size_class")
        else:
            second = None
            if len(first.text) == 1 and first.text.islower() and len(self.peek().text) == 1 and self.peek().text.isalpha():
                second = self.take()
            if len(first.text) == 2 or second is not None or (len(first.text) == 1 and first.text.islower()):
                self.kind = ReferenceKind.COMBINED
                a = Token(first.text[0], first.start, first.start + 1)
                b = second or Token(first.text[1:], first.start + 1, first.end)
                self.size = self.allowed(a, self.p["size_classes"], "invalid_size_class", "size_class")
                if not b.text:
                    self.error("incomplete_combined_reference", "geometry_class", b, "В объединённой записи отсутствует класс формы и расположения.")
                else:
                    self.geometry = self.allowed(b, self.p["geometry_classes"], "invalid_geometry_class", "geometry_class", geometry_symbol(b.text))
                self.spacing("between_classes", a.end, b.start)
            else:
                self.kind = ReferenceKind.GEOMETRY
                self.geometry = self.allowed(first, self.p["geometry_classes"], "invalid_geometry_class", "geometry_class", geometry_symbol(first.text))
        self.spacing("before_separator", self.match.end(), sep.start)
        self.spacing("after_separator", sep.end, first.start)
        before = " " if self.p["space_policy"][self.kind.value]["before_separator"] == "required" else ""
        after = " " if self.p["space_policy"][self.kind.value]["after_separator"] == "required" else ""
        classes = self.spelling(self.size, self.p["size_classes"]) if self.kind in (ReferenceKind.SIZE, ReferenceKind.COMBINED) else ""
        if self.kind in (ReferenceKind.GEOMETRY, ReferenceKind.COMBINED):
            between = " " if self.kind == ReferenceKind.COMBINED and self.p["space_policy"][self.kind.value]["between_classes"] == "required" else ""
            classes += between + self.spelling(self.geometry, self.p["geometry_classes"])
        self.expected = f"ГОСТ {standard}{before}-{after}{classes}"

    def appendix(self, standard):
        colon = self.take(":")
        self.kind = ReferenceKind.APPENDIX_2 if self.peek().text == "+" else ReferenceKind.APPENDIX_1
        self.variant = "2" if self.kind == ReferenceKind.APPENDIX_2 else "1"
        self.spacing("before_colon", self.match.end(), colon.start)
        self.spacing("after_colon", colon.end, self.peek().start)
        appendix = self.p["appendix_a"]
        pieces = []
        for position in range(3):
            if position:
                comma = self.take(",")
                self.spacing("after_comma", comma.end, self.peek().start)
            if position < 2 and self.kind == ReferenceKind.APPENDIX_1:
                token = self.take()
                values = appendix["hole" if position == 0 else "shaft"]
                value = self.allowed(token, values, "invalid_reference_format", "technical_designation", technical_symbol(token.text))
                pieces.append(self.spelling(value, values))
            else:
                sign = self.take("+" if position == 0 else "-" if position == 1 else "±")
                if sign.text == "-":
                    self.dash(sign)
                token = self.take()
                slot = "plus_to_t" if position == 0 else "minus_to_t" if position == 1 else "plus_minus_to_t"
                self.spacing(slot, sign.end, token.start)
                values = appendix["symmetric" if position == 2 and self.kind == ReferenceKind.APPENDIX_1 else "unilateral"]
                value = self.allowed(token, values, "invalid_reference_format", "technical_designation", technical_symbol(token.text))
                gap = " " if self.p["space_policy"][self.kind.value][slot] == "required" else ""
                piece = sign.text + gap + self.spelling(value, values)
                if position == 2:
                    slash = self.take("/")
                    denominator = self.take()
                    self.spacing("before_slash", token.end, slash.start)
                    self.spacing("after_slash", slash.end, denominator.start)
                    if denominator.text != appendix["denominator"]:
                        self.error("invalid_reference_format", "denominator", denominator, "Неверное обозначение знаменателя.")
                    piece += "/" + appendix["denominator"]
                pieces.append(piece)
        self.expected = f"ГОСТ {standard}: " + ", ".join(pieces)

    def parse(self):
        standard = self.match["standard"]
        if standard == "30893.1" and self.peek().text == ":":
            self.appendix(standard)
        else:
            self.separator_form(standard)
        self.spacing("keyword_to_number", self.match.end("keyword"), self.match.start("standard"))
        # Retain the original offsets even when a scoped technical glyph has an ASCII spelling.
        normalized = self.text[self.match.start():self.end]
        for start, end, value in sorted(self.canonical_replacements, reverse=True):
            a, b = start - self.match.start(), end - self.match.start()
            normalized = normalized[:a] + value + normalized[b:]
        return GeneralToleranceReference(ParseStatus.RECOGNIZED_INVALID if self.spaces or self.errors else ParseStatus.VALID,
            standard, self.kind, self.size, self.geometry, self.variant, self.raw[self.match.start():self.end],
            normalized, tuple(self.spaces), tuple(self.errors), self.expected, self.match.start(), self.end)


def find_references(text, parameters):
    validate_parameters(parameters)
    recognized = recognition_text(text)
    matches = list(ANCHOR.finditer(recognized))
    return tuple(_Parser(text, match, matches[index + 1].start() if index + 1 < len(matches) else len(text), parameters).parse()
                 for index, match in enumerate(matches))


def parse_reference(text, parameters):
    found = find_references(text, parameters)
    if found:
        return found[0]
    return GeneralToleranceReference(ParseStatus.NOT_A_REFERENCE, None, None, None, None, None,
                                     text, recognition_text(text), (), (), "", 0, len(text))
