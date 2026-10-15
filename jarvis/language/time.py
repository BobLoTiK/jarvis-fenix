"""Duration grammar with source spans. Uses the shared numeral/unit vocabulary."""

from dataclasses import dataclass
from decimal import Decimal
import re
from .numbers import word_numbers, digit_numbers
from .units import unit_at


@dataclass(frozen=True)
class Duration:
    start: int
    end: int
    seconds: Decimal
    issue: str | None = None


PREFIX = re.compile(r"\b(?:через|на|таймер)\s+", re.I)
HALF = re.compile(r"пол\s*(часа|минуты|секунды)\b", re.I)
SINGLE = re.compile(r"(?:час(?:а|ов)?|минут(?:у|а|ку|ы)?|секунд(?:у|а|ы)?)\b", re.I)


def parse_duration(text):
    intro = re.match(
        r"^\s*(?:(?:(?:поставь|установи)\s+)?(?:напомни|напоминай|напоминание|таймер)\b\s*)?",
        text,
        re.I,
    )
    base = intro.end()
    prefix = PREFIX.match(text, base)
    start = prefix.start() if prefix else base
    position = prefix.end() if prefix else base
    numbers = tuple(
        sorted((*word_numbers(text), *digit_numbers(text)), key=lambda n: n.start)
    )
    half = HALF.match(text, position)
    single = SINGLE.match(text, position)
    n = next((n for n in numbers if n.start == position and n.kind == "cardinal"), None)
    if half:
        amount, after = Decimal("0.5"), half.start(1)
    elif single:
        amount, after = Decimal(1), position
    elif n:
        amount, after = n.value, n.end
    else:
        return None
    total = Decimal(0)
    end = position
    issue = None
    while amount is not None:
        value = amount
        if value < 0:
            issue = "Компоненты длительности не должны быть отрицательными."
        half_tail = re.match(r"\s+с\s+половиной\b", text[after:], re.I)
        if half_tail:
            value += Decimal("0.5")
            after += half_tail.end()
        unit = unit_at(text, after)
        if unit and unit[0].dimension == "duration":
            multiplier = unit[0].multiplier
            end = unit[1]
        elif end == position and prefix:
            multiplier = 60
            end = after
        else:
            break
        total += value * multiplier
        half_tail = re.match(r"\s+с\s+половиной\b", text[end:], re.I)
        if half_tail:
            total += Decimal(multiplier) / 2
            end += half_tail.end()
        join = re.match(r"\s*(?:и\s+)?", text[end:])
        pos = end + join.end()
        n = next(
            (item for item in numbers if item.start == pos and item.kind == "cardinal"),
            None,
        )
        if n and not unit:
            issue = "Не удалось однозначно разобрать длительность. Укажи единицу после числа."
            break
        if n and not unit_at(text, n.end):
            break
        amount, after = (n.value, n.end) if n else (None, end)
    return Duration(start, end, total, issue) if end > position else None
