"""Numeral grammar shared by command understanding and speech rendering.

Lexical forms come from num2words and pymorphy3, not a list of user phrases.
The parser validates descending groups/scales and retains source offsets.
"""

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
import re

from num2words import num2words
from .morphology import numeral_parse, parses, inflect, noun_parse


@dataclass(frozen=True)
class Number:
    start: int
    end: int
    value: Decimal
    kind: str = "cardinal"
    source: str = ""


@dataclass(frozen=True)
class Lexeme:
    value: int
    kind: str


BASES = tuple(range(20)) + tuple(range(20, 100, 10)) + tuple(range(100, 1000, 100))
SCALES = (1000, 1000000, 1000000000, 1000000000000)
WORD = re.compile(r"[А-Яа-яЁё]+")
DIGIT = re.compile(r"(?<![\w])[-+−]?\d+(?:[.,]\d+)?(?![\dA-Za-z_])")


@lru_cache(maxsize=1)
def lexicon():
    result = {}
    seeds = tuple(
        sorted(
            set(
                BASES
                + SCALES
                + tuple(
                    n * s
                    for n in BASES
                    if n > 1
                    for s in (1000, 1000000, 1000000000)
                    if n * s < 10**12
                )
            )
        )
    )
    for value in seeds:
        for kind in (
            ("cardinal", "ordinal") if value in BASES + SCALES else ("ordinal",)
        ):
            word = num2words(value, lang="ru", to=kind).split()[-1]
            p = (
                numeral_parse(word, ordinal=True)
                if kind == "ordinal"
                else (noun_parse(word) if value in SCALES else numeral_parse(word))
            )
            if p is None:
                continue
            for form in p.lexeme:
                result.setdefault(form.word.replace("ё", "е"), Lexeme(value, kind))
    return result


def _group(tokens, index, text, allow_ordinal=True):
    """Longest valid integer/ordinal phrase starting at token index."""
    total = group = 0
    last_rank, last_scale = 1000, 10**15
    end = index
    previous = None
    for j in range(index, min(len(tokens), index + 32)):
        if (
            previous is not None
            and not text[previous.end() : tokens[j].start()].isspace()
        ):
            break
        item = lexicon().get(tokens[j].group().lower().replace("ё", "е"))
        if item is None:
            break
        n = item.value
        if item.kind == "ordinal":
            if not allow_ordinal:
                break
            if n < 1000 and (100 if n >= 100 else 10 if n >= 20 else 1) >= last_rank:
                break
            return total + group + n, "ordinal", j + 1
        if n >= 1000:
            if n >= last_scale:
                break
            total += (group or 1) * n
            group, last_rank, last_scale = 0, 1000, n
        else:
            rank = 100 if n >= 100 else 10 if n >= 20 else 1
            if rank >= last_rank or (n == 0 and (group or total)):
                break
            group += n
            last_rank = rank
        end, previous = j + 1, tokens[j]
    return (total + group, "cardinal", end) if end > index else None


def word_numbers(text):
    tokens = list(WORD.finditer(text))
    i = 0
    while i < len(tokens):
        token = tokens[i]
        word = token.group().lower().replace("ё", "е")
        if word in ("полтора", "полторы"):
            yield Number(
                token.start(), token.end(), Decimal("1.5"), source=token.group()
            )
            i += 1
            continue
        sign, first = 1, i
        if (
            word == "минус"
            and i + 1 < len(tokens)
            and text[token.end() : tokens[i + 1].start()].isspace()
        ):
            sign, i = -1, i + 1
        parsed = _group(tokens, i, text)
        if parsed is None:
            i = max(i + 1, first + 1)
            continue
        value, kind, end = parsed
        value = Decimal(value)
        # Rational decimal: «три целых пять десятых», with exact Decimal arithmetic.
        if (
            kind == "cardinal"
            and end < len(tokens)
            and any(p.normal_form == "целый" for p in parses(tokens[end].group()))
        ):
            fraction = _group(tokens, end + 1, text, allow_ordinal=False)
            if fraction and fraction[1] == "cardinal" and fraction[2] < len(tokens):
                denom = lexicon().get(
                    tokens[fraction[2]].group().lower().replace("ё", "е")
                )
                if (
                    denom
                    and denom.kind == "ordinal"
                    and denom.value in (10, 100, 1000, 1000000)
                    and fraction[0] < denom.value
                ):
                    value += Decimal(fraction[0]) / Decimal(denom.value)
                    end = fraction[2] + 1
        last = tokens[end - 1].end()
        yield Number(
            tokens[first].start(),
            last,
            sign * value,
            kind,
            text[tokens[first].start() : last],
        )
        i = end


def digit_numbers(text):
    for m in DIGIT.finditer(text):
        yield Number(
            m.start(),
            m.end(),
            Decimal(m.group().replace("−", "-").replace(",", ".")),
            source=m.group(),
        )


def cardinal(value, case="nomn", gender="masc", animate=False):
    value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("Expected a finite number")
    if value != value.to_integral_value():
        return decimal_words(value, case)
    n = int(value)
    if abs(n) >= 10**15:
        # Keep identifiers/very long integers unambiguous instead of guessing a scale.
        return " ".join(
            num2words(int(ch), lang="ru") if ch.isdigit() else "минус" for ch in str(n)
        )
    words = num2words(abs(n), lang="ru").split()
    rendered = []
    # Every triad agrees with its own scale; the final triad with the target noun.
    for i, word in enumerate(words):
        scale = next(
            (
                k
                for k in range(i, len(words))
                if any(
                    p.normal_form in ("тысяча", "миллион", "миллиард", "триллион")
                    for p in parses(words[k])
                )
            ),
            None,
        )
        local_gender = gender
        if scale is not None:
            local_gender = (
                "femn"
                if any(p.normal_form == "тысяча" for p in parses(words[scale]))
                else "masc"
            )
        p = next(
            (
                p
                for p in parses(word)
                if p.normal_form in ("тысяча", "миллион", "миллиард", "триллион")
            ),
            None,
        )
        if p is not None:
            if case in ("nomn", "accs"):
                rendered.append(word)
            else:
                scale_value = {
                    "тысяча": 1000,
                    "миллион": 10**6,
                    "миллиард": 10**9,
                    "триллион": 10**12,
                }[p.normal_form]
                triad = abs(n) // scale_value % 1000
                singular = triad % 10 == 1 and triad % 100 != 11
                rendered.append(inflect(p, case, number="sing" if singular else "plur"))
        else:
            rendered.append(
                inflect(numeral_parse(word), case, local_gender, animate=animate)
            )
    return ("минус " if n < 0 else "") + " ".join(rendered)


def ordinal(value, case="nomn", gender="masc", number="sing", animate=False):
    n = int(value)
    if n < 0 or n >= 10**12:
        raise ValueError("Ordinal outside supported range")
    words = num2words(n, lang="ru", to="ordinal").split()
    words[-1] = inflect(
        numeral_parse(words[-1], ordinal=True), case, gender, number, animate
    )
    return " ".join(words)


def decimal_words(value, case="nomn"):
    value = Decimal(str(value))
    sign = "минус " if value < 0 else ""
    raw = format(abs(value).normalize(), "f")
    if "." not in raw:
        return cardinal(value, case)
    whole, frac = raw.split(".")
    if len(frac) > 6:
        return (
            sign
            + cardinal(int(whole), case)
            + " запятая "
            + " ".join(cardinal(int(c)) for c in frac)
        )
    numerator, denominator = int(frac), 10 ** len(frac)
    adjective = "целая" if int(whole) % 10 == 1 and int(whole) % 100 != 11 else "целых"
    # Decimal grammatical agreement is feminine, independent of the measured noun.
    whole_form = (
        inflect(
            numeral_parse(adjective, ordinal=True),
            case,
            "femn",
            "sing" if adjective == "целая" else "plur",
        )
        if case not in ("nomn", "accs")
        else adjective
    )
    denom_case = (
        case
        if case not in ("nomn", "accs") or numerator % 10 == 1 and numerator % 100 != 11
        else "gent"
    )
    denom_number = "sing" if numerator % 10 == 1 and numerator % 100 != 11 else "plur"
    return (
        sign
        + cardinal(int(whole), case, "femn")
        + " "
        + whole_form
        + " "
        + cardinal(numerator, case, "femn")
        + " "
        + ordinal(denominator, denom_case, "femn", denom_number)
    )


_ROMAN = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def roman_value(token):
    import unicodedata

    token = unicodedata.normalize("NFKC", token)
    if not token or not re.fullmatch("[IVXLCDM]+", token):
        return None
    total, remaining = 0, token
    for value, symbol in _ROMAN:
        while remaining.startswith(symbol):
            total += value
            remaining = remaining[len(symbol) :]
    if remaining or not 0 < total < 4000:
        return None
    canonical, n = "", total
    for value, symbol in _ROMAN:
        count, n = divmod(n, value)
        canonical += symbol * count
    return total if canonical == token else None
