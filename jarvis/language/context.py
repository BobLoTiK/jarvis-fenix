"""Local grammatical evidence. Ambiguous sentences are not a full syntax parse."""

from dataclasses import dataclass
import re
from .morphology import noun_parse

WORDS = re.compile(r"[А-Яа-яЁё]+")
ORDER_HEADS = frozenset(
    (
        "век",
        "глава",
        "часть",
        "том",
        "раздел",
        "пункт",
        "этап",
        "класс",
        "акт",
        "степень",
        "курс",
    )
)
PREPOSITIONS = {
    "к": "datv",
    "ко": "datv",
    "до": "gent",
    "от": "gent",
    "ото": "gent",
    "из": "gent",
    "без": "gent",
    "около": "gent",
    "после": "gent",
    "для": "gent",
    "перед": "ablt",
    "над": "ablt",
    "между": "ablt",
    "о": "loct",
    "об": "loct",
    "обо": "loct",
    "при": "loct",
}


@dataclass(frozen=True)
class Context:
    case: str = "nomn"
    gender: str = "masc"
    number: str = "sing"
    animate: bool = False
    ordinal: bool = False
    head: str = ""


def context_at(text, start, end, *, force_ordinal=False):
    before = list(WORDS.finditer(re.split(r"[.!?;:\n]", text[:start])[-1]))
    after = (
        WORDS.match(text, end)
        if end < len(text) and text[end].isalpha()
        else re.match(r"\s*([А-Яа-яЁё]+)", text[end:])
    )
    next_word = (
        after.group(1) if after and after.lastindex else after.group() if after else ""
    )
    prev_word = before[-1].group() if before else ""
    next_noun = noun_parse(next_word) if next_word else None
    prev_noun = noun_parse(prev_word) if prev_word else None
    next_is_order = next_noun and next_noun.normal_form in ORDER_HEADS
    prev_is_order = prev_noun and (
        prev_noun.normal_form in ORDER_HEADS or "Name" in prev_noun.tag
    )
    is_order = force_ordinal or bool(next_is_order or prev_is_order)
    noun = next_noun
    if is_order and prev_is_order and not next_is_order:
        noun = prev_noun
    # A non-order noun in a distant sentence is not evidence for Roman numbers.
    prep = None
    for token in reversed(before[-4:]):
        w = token.group().lower().replace("ё", "е")
        if w in PREPOSITIONS or w in ("в", "во", "на", "с", "со", "через"):
            prep = w
            break
    case = PREPOSITIONS.get(prep, "nomn")
    if prep in ("в", "во", "на"):
        case = "loct" if noun and noun.tag.case in ("loct", "loc2") else "accs"
    elif prep in ("с", "со"):
        case = "gent" if noun and noun.tag.case == "gent" else "ablt"
    elif prep == "через":
        case = "accs"
    elif prep is None and noun and noun.tag.case in ("datv", "ablt", "loct"):
        case = noun.tag.case
    if is_order and noun and noun.tag.case in ("gent", "datv", "ablt", "loct", "accs"):
        # Actual head form is stronger evidence than a distant preposition.
        case = "loct" if noun.tag.case == "loc2" else noun.tag.case
    gender = noun.tag.gender if noun and noun.tag.gender else "masc"
    return Context(
        case,
        gender,
        noun.tag.number or "sing" if noun else "sing",
        bool(noun and noun.tag.animacy == "anim"),
        is_order,
        noun.normal_form if noun else "",
    )


def explicit_number_context(text, start):
    return bool(
        re.search(
            r"(?:римск\w*\s+(?:числ\w*|цифр\w*)|число|номер)\s*$",
            text[:start],
            re.I,
        )
    )
