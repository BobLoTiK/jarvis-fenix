"""Cached Russian morphology. No model downloads or network access."""

from functools import lru_cache
from threading import RLock

_LOCK = RLock()


@lru_cache(maxsize=1)
def analyzer():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=8192)
def parses(word):
    with _LOCK:
        return tuple(analyzer().parse(word.lower().replace("ё", "е")))


def numeral_parse(word, ordinal=False):
    candidates = [
        p
        for p in parses(word)
        if ("Anum" in p.tag if ordinal else p.tag.POS == "NUMR" or "Anum" in p.tag)
    ]
    return next(
        (
            p
            for p in candidates
            if p.tag.case == "nomn" and p.tag.gender in (None, "masc")
        ),
        candidates[0] if candidates else parses(word)[0],
    )


def noun_parse(word):
    return next((p for p in parses(word) if p.tag.POS == "NOUN"), None)


def inflect(parse, case="nomn", gender=None, number=None, animate=False):
    tags = {case}
    if parse.tag.POS in ("ADJF", "PRTF"):
        tags.add(number or "sing")
        if number != "plur":
            tags.add(gender or "masc")
        if case == "accs" and (number == "plur" or gender in (None, "masc")):
            tags.add("anim" if animate else "inan")
    elif parse.tag.POS == "NOUN":
        if number:
            tags.add(number)
    elif parse.tag.POS == "NUMR" and parse.normal_form == "два":
        if gender == "femn":
            tags.add("femn")
        elif gender in ("masc", "neut"):
            tags.add("masc")
        if case == "accs" and animate:
            tags.add("anim")
    form = parse.inflect(tags) or parse.inflect({case})
    if form and "Coun" in form.tag:
        form = next(
            (
                p
                for p in parse.lexeme
                if tags <= set(p.tag.grammemes) and "Coun" not in p.tag
            ),
            form,
        )
    return form.word if form else parse.word


def noun_form(lemma, value, case="nomn", *, decimal=False):
    p = noun_parse(lemma)
    if p is None:
        return lemma
    if decimal:
        return inflect(p, "gent", number="sing")
    n = abs(int(value))
    if case in ("nomn", "accs"):
        last, hundred = n % 10, n % 100
        if last == 1 and hundred != 11:
            return inflect(p, case, number="sing")
        if case == "accs" and p.tag.animacy == "anim":
            return inflect(p, "gent", number="plur")
        if last in (2, 3, 4) and hundred not in (12, 13, 14):
            return inflect(p, "gent", number="sing")
        return inflect(p, "gent", number="plur")
    singular = n % 10 == 1 and n % 100 != 11
    return inflect(p, case, number="sing" if singular else "plur")
