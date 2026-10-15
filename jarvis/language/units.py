"""Semantic unit lexicon shared by input and output; spelling is data, not phrase patches."""

from dataclasses import dataclass
import re
from .morphology import noun_parse


@dataclass(frozen=True)
class Unit:
    lemma: str
    dimension: str
    multiplier: int = 1
    tail: str = ""


UNITS = {
    "%": Unit("процент", "percent"),
    "‰": Unit("промилле", "percent"),
    "км/ч": Unit("километр", "speed", tail="в час"),
    "м/с": Unit("метр", "speed", tail="в секунду"),
    "км/с": Unit("километр", "speed", tail="в секунду"),
    "°C": Unit("градус", "temperature", tail="Цельсия"),
    "°С": Unit("градус", "temperature", tail="Цельсия"),
    "°F": Unit("градус", "temperature", tail="Фаренгейта"),
    "°": Unit("градус", "temperature"),
    "кг": Unit("килограмм", "mass"),
    "мг": Unit("миллиграмм", "mass"),
    "г": Unit("грамм", "mass"),
    "см": Unit("сантиметр", "length"),
    "мм": Unit("миллиметр", "length"),
    "км": Unit("километр", "length"),
    "м": Unit("метр", "length"),
    "м²": Unit("квадратный метр", "area"),
    "м³": Unit("кубический метр", "volume"),
    "МБ": Unit("мегабайт", "data"),
    "ГБ": Unit("гигабайт", "data"),
    "КБ": Unit("килобайт", "data"),
    "ТБ": Unit("терабайт", "data"),
    "Б": Unit("байт", "data"),
    "сек": Unit("секунда", "duration", 1),
    "с": Unit("секунда", "duration", 1),
    "мин": Unit("минута", "duration", 60),
    "ч": Unit("час", "duration", 3600),
    "руб": Unit("рубль", "currency"),
    "₽": Unit("рубль", "currency"),
    "$": Unit("доллар", "currency"),
    "€": Unit("евро", "currency"),
    "№": Unit("номер", "identifier"),
}
LEMMA_UNITS = {
    "секунда": Unit("секунда", "duration", 1),
    "минута": Unit("минута", "duration", 60),
    "час": Unit("час", "duration", 3600),
    "сутки": Unit("сутки", "duration", 86400),
    "день": Unit("день", "duration", 86400),
    "неделя": Unit("неделя", "duration", 604800),
    "процент": Unit("процент", "percent"),
}
TOKEN = re.compile(
    "|".join(re.escape(s) for s in sorted(UNITS, key=len, reverse=True))
    + r"|[А-Яа-яЁё]+"
)


def unit_at(text, position):
    m = re.match(r"\s*", text[position:])
    start = position + m.end()
    token = TOKEN.match(text, start)
    if not token:
        return None
    spelling = token.group()
    # A short abbreviation must not consume the beginning of a full word.
    if spelling in UNITS and (
        token.end() == len(text) or not text[token.end()].isalpha()
    ):
        end = token.end()
        if end < len(text) and text[end] == "." and spelling in ("сек", "мин", "руб"):
            end += 1
        return UNITS[spelling], end
    word = re.match(r"[А-Яа-яЁё]+", text[start:])
    if word:
        p = noun_parse(word.group())
        if p and p.normal_form in LEMMA_UNITS:
            return LEMMA_UNITS[p.normal_form], start + word.end()
    return None
