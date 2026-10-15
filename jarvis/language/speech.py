"""Typed text verbalization. Longest semantic forms precede generic numbers.

Output is speech-only: the original chat/LLM text is never overwritten.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from .numbers import cardinal, ordinal, roman_value
from .context import context_at, explicit_number_context
from .morphology import noun_form, noun_parse, inflect, numeral_parse
from .units import unit_at, Unit

TOKEN = re.compile(
    r"(?P<url>https?://[^\s<>]+)|"
    r"(?P<email>[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})|"
    r"(?P<path>[A-Za-z]:[\\/][^\s<>]+)|"
    r"(?P<date>\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})\b)|"
    r"(?P<version>\b\d+(?:\.\d+){2,}\b)|"
    r"(?P<clock>\b\d{1,2}:\d{2}\b)|"
    r"(?P<fraction>(?<!\w)\d+\s*/\s*\d+(?!\w))|"
    r"(?P<range>(?<!\w)\d+\s*[–—]\s*\d+(?!\w))|"
    r"(?P<ordinal>(?<!\w)\d+-(?:ого|ому|ыми|ыми|ая|ое|ые|ий|ый|ой|го|му|ми|й|я|е|м|х)\b)|"
    r"(?P<roman>(?<!\w)[IVXLCDM\u2160-\u216F]+(?!\w))|"
    r"(?P<number>(?<!\w)[−+\-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?![\dA-Za-z_]))"
)
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
IDENTIFIER_WORDS = re.compile(
    r"(?:верси[яию]|сборк[аи]|код|пин|артикул|телефон|id|ip)\s*$", re.I
)
SIGNS = {
    "+": "плюс",
    "−": "минус",
    "=": "равно",
    "≠": "не равно",
    "≥": "больше или равно",
    "≤": "меньше или равно",
    ">": "больше чем",
    "<": "меньше чем",
    "≈": "примерно",
    "±": "плюс-минус",
    "×": "умножить на",
    "÷": "разделить на",
    "→": "стрелка вправо",
    "←": "стрелка влево",
    "↔": "двунаправленная стрелка",
    "∞": "бесконечность",
    "√": "корень из",
    "π": "пи",
    "©": "знак авторского права",
    "®": "зарегистрированный товарный знак",
    "™": "товарный знак",
    "²": "в квадрате",
    "³": "в кубе",
    "^": "в степени",
    "~": "примерно",
    "#": "решётка",
    "°": "градус",
    "%": "процент",
    "‰": "промилле",
    "№": "номер",
    "@": "собака",
    "&": "и",
    "§": "параграф",
}
IDENTIFIER_SIGNS = {
    ".": "точка",
    "/": "косая черта",
    "\\": "обратная косая черта",
    ":": "двоеточие",
    "@": "собака",
    "-": "дефис",
    "_": "нижнее подчёркивание",
    "+": "плюс",
    "?": "вопросительный знак",
    "=": "равно",
    "&": "амперсанд",
    "#": "решётка",
}


def _verbalize_identifier(text):
    # Keep letter groups intact; digit groups are unambiguous sequences, not quantities.
    return re.sub(
        r"\d+|[./\\:@_+?=&#-]",
        lambda m: (
            " "
            + (
                " ".join(cardinal(int(c)) for c in m.group())
                if m.group().isdigit()
                else IDENTIFIER_SIGNS[m.group()]
            )
            + " "
        ),
        text,
    )


def _quantity(value, unit, case):
    modifier, _, noun = unit.lemma.rpartition(" ")
    noun = noun or unit.lemma
    p = noun_parse(noun)
    gender = p.tag.gender if p and p.tag.gender else "masc"
    words = cardinal(value, case, gender)
    noun_words = noun_form(
        noun, value, case, decimal=value != value.to_integral_value()
    )
    if modifier:
        n = abs(int(value))
        singular = n % 10 == 1 and n % 100 != 11
        is_decimal = value != value.to_integral_value()
        adj_case = (
            "gent"
            if is_decimal
            else case
            if singular or case not in ("nomn", "accs")
            else "gent"
        )
        adj = inflect(
            numeral_parse(modifier, ordinal=True),
            adj_case,
            gender,
            "sing" if singular or is_decimal else "plur",
        )
        noun_words = adj + " " + noun_words
    return " ".join(part for part in (words, noun_words, unit.tail) if part)


def _money(value, unit, case):
    if abs(value.as_tuple().exponent) > 2:
        return _quantity(value, unit, case)
    absolute = abs(value)
    whole = int(absolute)
    cents = int((absolute - whole) * 100)
    main = _quantity(Decimal(whole), unit, case)
    if cents:
        minor = "копейка" if unit.lemma == "рубль" else "цент"
        main += (
            " "
            + cardinal(cents, case, "femn" if minor == "копейка" else "masc")
            + " "
            + noun_form(minor, cents, case)
        )
    return ("минус " if value < 0 else "") + main


def _date(token, ctx):
    try:
        if "-" in token:
            year, month, day = map(int, token.split("-"))
        else:
            day, month, year = map(int, token.split("."))
        date(year, month, day)
    except ValueError:
        return _verbalize_identifier(token)
    case = ctx.case if ctx.case not in ("nomn", "accs") else "nomn"
    return (
        f"{ordinal(day, case, 'neut')} {MONTHS[month - 1]} {ordinal(year, 'gent')} года"
    )


def _ordinal_suffix(token, ctx):
    raw, suffix = token.split("-")
    forms = {
        "й": ("nomn", "masc"),
        "ий": ("nomn", "masc"),
        "ый": ("nomn", "masc"),
        "ой": ("nomn", "masc"),
        "я": ("nomn", "femn"),
        "ая": ("nomn", "femn"),
        "е": ("nomn", "neut"),
        "ое": ("nomn", "neut"),
        "го": ("gent", "masc"),
        "ого": ("gent", "masc"),
        "му": ("datv", "masc"),
        "ому": ("datv", "masc"),
        "м": ("loct" if ctx.case == "loct" or ctx.case == "accs" else "ablt", "masc"),
        "ые": ("nomn", "masc"),
        "ми": ("ablt", "masc"),
        "ыми": ("ablt", "masc"),
        "х": ("gent", "masc"),
    }
    case, gender = forms.get(suffix, (ctx.case, ctx.gender))
    return (
        ordinal(
            int(raw),
            case,
            gender,
            "plur" if suffix in ("ые", "ми", "ыми", "х") else "sing",
        )
        if int(raw) < 10**12
        else "порядковый номер " + cardinal(Decimal(raw))
    )


def prepare_speech(text):
    if not text:
        return text
    # Markup is structural, never spoken as arithmetic.
    text = re.sub(r"```[\s\S]*?```", " Фрагмент кода. ", text)
    text = re.sub(r"\[([^\]]+)\]\([^\s)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*•]\s+)", "", text)
    text = re.sub(
        r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), text
    )
    parts = []
    position = 0
    for m in TOKEN.finditer(text):
        if m.start() < position:
            continue
        parts.append(text[position : m.start()])
        token = m.group()
        kind = m.lastgroup
        end = m.end()
        ctx = context_at(text, m.start(), end)
        if kind in ("url", "email", "path", "version"):
            spoken = _verbalize_identifier(token)
        elif kind == "date":
            spoken = _date(token, ctx)
        elif kind == "clock":
            hour, minute = map(int, token.split(":"))
            spoken = (
                (
                    _quantity(Decimal(hour), Unit("час", "duration"), ctx.case)
                    + " "
                    + _quantity(Decimal(minute), Unit("минута", "duration"), ctx.case)
                )
                if hour < 24 and minute < 60
                else _verbalize_identifier(token)
            )
        elif kind == "fraction":
            numerator, denominator = map(int, re.split(r"\s*/\s*", token))
            if denominator >= 10**12:
                spoken = (
                    "числитель "
                    + cardinal(numerator)
                    + " знаменатель "
                    + cardinal(denominator)
                )
            elif denominator == 0:
                spoken = cardinal(numerator) + " разделить на ноль"
            else:
                spoken = (
                    cardinal(numerator, ctx.case, "femn")
                    + " "
                    + ordinal(
                        denominator,
                        ctx.case if numerator == 1 else "gent",
                        "femn",
                        "sing" if numerator == 1 else "plur",
                    )
                )
        elif kind == "range":
            left, right = map(int, re.split(r"\s*[–—]\s*", token))
            spoken = "от " + cardinal(left, "gent") + " до " + cardinal(right, "gent")
        elif kind == "roman":
            value = roman_value(token)
            explicit = explicit_number_context(text, m.start())
            spoken = (
                (
                    ordinal(value, ctx.case, ctx.gender, ctx.number, ctx.animate)
                    if ctx.ordinal
                    else cardinal(value)
                    if explicit
                    else token
                )
                if value is not None
                else token
            )
        elif kind == "ordinal":
            spoken = _ordinal_suffix(token, ctx)
        else:
            raw = (
                re.sub(r"[ \u00a0\u202f]", "", token)
                .replace("−", "-")
                .replace(",", ".")
            )
            try:
                value = Decimal(raw)
            except InvalidOperation:
                parts.append(token)
                position = end
                continue
            unit = unit_at(text, end)
            year_abbr = re.match(r"\s*г\.(?!\w)", text[end:])
            if IDENTIFIER_WORDS.search(text[max(0, m.start() - 24) : m.start()]) or (
                len(raw) > 1 and raw[0] == "0" and "." not in raw
            ):
                spoken = _verbalize_identifier(token)
            elif year_abbr and 1000 <= value <= 9999 and value == int(value):
                year_case = "loct" if ctx.case in ("loct", "accs") else "gent"
                spoken = (
                    ordinal(int(value), year_case)
                    + " "
                    + ("году" if year_case == "loct" else "года")
                )
                end += year_abbr.end()
            elif unit:
                u, end = unit
                spoken = (
                    _money(value, u, ctx.case)
                    if u.dimension == "currency"
                    else _quantity(value, u, ctx.case)
                )
            elif (
                value == value.to_integral_value()
                and 0 <= value < 10**12
                and (ctx.ordinal or (ctx.head == "год" and value >= 1000))
            ):
                spoken = ordinal(
                    int(value), ctx.case, ctx.gender, ctx.number, ctx.animate
                )
            elif re.search(r"[A-Za-z]\s*$", text[: m.start()]) and "." in raw:
                spoken = _verbalize_identifier(token)
            else:
                spoken = cardinal(value, ctx.case, ctx.gender, ctx.animate)
            if token.startswith("+") and not spoken.startswith("плюс "):
                spoken = "плюс " + spoken
        parts.append(
            token if kind == "roman" and spoken == token else " " + spoken + " "
        )
        position = end
    parts.append(text[position:])
    result = "".join(parts)
    # Only residual standalone symbols are handled here, after typed expressions.
    result = re.sub(
        r"->|<-|>=|<=|!=",
        lambda m: {
            "->": " стрелка вправо ",
            "<-": " стрелка влево ",
            ">=": " больше или равно ",
            "<=": " меньше или равно ",
            "!=": " не равно ",
        }[m.group()],
        result,
    )
    for symbol, name in SIGNS.items():
        result = result.replace(symbol, " " + name + " ")
    result = re.sub(r"(?<=\S)\s*\*\s*(?=\S)", " умножить на ", result)
    result = re.sub(r"(?<=\S)\s*/\s*(?=\S)", " разделить на ", result)
    result = re.sub(r"(?<!\w)-(?=\s)", " минус ", result)
    result = result.replace("`", "")
    result = re.sub(r"\s+", " ", result).strip()
    return re.sub(r"\s+([,.!?;:])", r"\1", result)
