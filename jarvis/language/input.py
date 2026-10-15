"""Conservative semantic input adapter. Does not rewrite arbitrary text payloads."""

from dataclasses import dataclass
from decimal import Decimal
import re
from .numbers import Number, word_numbers, digit_numbers, roman_value, ordinal, cardinal
from .context import context_at, explicit_number_context
from .time import parse_duration

ROMANS = re.compile(r"(?<![\w])[IVXLCDM\u2160-\u216F]+(?![\w])")
TIME_COMMAND = re.compile(
    r"^\s*(?:(?:поставь|установи)\s+)?(?:напомни|напоминай|напоминание|таймер)\b", re.I
)
LEVEL_COMMAND = re.compile(
    r"\b(?:громкость|яркость|потише|тише|погромче|громче)\b", re.I
)
PAYLOAD_COMMAND = re.compile(
    r"^\s*(?:добавь|запиши|внеси|напечатай|напиши|запомни|найди|поищи|открой|запусти)\b",
    re.I,
)


@dataclass(frozen=True)
class Analysis:
    original: str
    command: str
    numbers: tuple[Number, ...] = ()
    issue: str | None = None


def _apply(text, replacements):
    for start, end, value in sorted(replacements, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def _digits(value):
    return format(value.normalize(), "f")


def analyze_command(text):
    numbers = tuple(
        sorted((*word_numbers(text), *digit_numbers(text)), key=lambda n: n.start)
    )
    replacements = []
    time_command = TIME_COMMAND.search(text)
    level_command = LEVEL_COMMAND.search(text)
    # Payloads (a task, filename, search text) are not executable numeric slots.
    if PAYLOAD_COMMAND.match(text):
        return Analysis(text, text, numbers)
    if level_command:
        # Only a number adjacent to the level word/delta construction is a parameter.
        for n in numbers:
            gap = (
                text[level_command.end() : n.start].strip().lower()
                if n.start >= level_command.end()
                else None
            )
            delta = re.search(r"\bна\s*$", text[: n.start], re.I) and re.match(
                r"\s*(?:потише|тише|погромче|громче)\b", text[n.end :], re.I
            )
            if gap not in ("", "на") and not delta:
                continue
            if any(
                other.start > n.end and text[n.end : other.start].isspace()
                for other in numbers
            ):
                return Analysis(
                    text,
                    text,
                    numbers,
                    "Не удалось однозначно разобрать число. Повтори значение.",
                )
            if (
                n.kind != "cardinal"
                or n.value != n.value.to_integral_value()
                or not 0 <= n.value <= 100
            ):
                return Analysis(
                    text,
                    text,
                    numbers,
                    "Для громкости и яркости нужно целое число от нуля до ста.",
                )
            replacements.append((n.start, n.end, _digits(n.value)))
    if time_command:
        # Only the time specification, never the reminder body.
        prefix = text[time_command.end() :]
        spec = re.match(r"\s*(?:через|на|в)?\s*", prefix, re.I)
        position = time_command.end() + spec.end()
        clock = re.match(r"\d{1,2}[:.]\d{2}\b", text[position:])
        if clock:
            hh, mm = map(int, re.split(r"[:.]", clock.group()))
            if not 0 <= hh < 24 or not 0 <= mm < 60:
                return Analysis(
                    text,
                    text,
                    numbers,
                    "Время вне диапазона: укажи часы от 0 до 23 и минуты от 0 до 59.",
                )
        candidate = (
            None if clock else next((n for n in numbers if n.start == position), None)
        )
        if candidate:
            # Spoken hour: «в восемнадцать часов тридцать минут».
            if re.search(r"\bв\s*$", text[: candidate.start], re.I):
                following = next(
                    (
                        n
                        for n in numbers
                        if n.start > candidate.end
                        and re.fullmatch(
                            r"\s*(?:час(?:а|ов)?)?\s*",
                            text[candidate.end : n.start],
                            re.I,
                        )
                    ),
                    None,
                )
                hour = (
                    int(candidate.value)
                    if candidate.value == candidate.value.to_integral_value()
                    else -1
                )
                minute = (
                    int(following.value)
                    if following
                    and following.value == following.value.to_integral_value()
                    else 0
                )
                ending = following.end if following else candidate.end
                suffix = (
                    re.match(r"\s*минут\w*\b", text[ending:], re.I)
                    if following
                    else re.match(r"\s*час\w*\b", text[ending:], re.I)
                )
                if suffix:
                    ending += suffix.end()
                period = re.match(r"\s*(утра|дня|вечера|ночи)\b", text[ending:], re.I)
                if period:
                    if period.group(1).lower() in ("дня", "вечера") and 1 <= hour < 12:
                        hour += 12
                    elif period.group(1).lower() in ("утра", "ночи") and hour == 12:
                        hour = 0
                    ending += period.end()
                if not 0 <= hour < 24 or not 0 <= minute < 60:
                    return Analysis(
                        text,
                        text,
                        numbers,
                        "Не удалось определить время. Укажи часы от нуля до двадцати трёх и минуты от нуля до пятидесяти девяти.",
                    )
                replacements = [
                    r for r in replacements if not candidate.start <= r[0] < ending
                ]
                replacements.append(
                    (candidate.start, ending, f"{hour:02d}:{minute:02d}")
                )
        half = re.search(r"\bв\s+(?:половине|пол)\s*", text[time_command.end() :], re.I)
        if half:
            pos = time_command.end() + half.end()
            n = next(
                (n for n in numbers if n.start == pos and n.kind == "ordinal"), None
            )
            if n and 1 <= n.value <= 12:
                suffix = re.match(r"\s*(утра|дня|вечера|ночи)\b", text[n.end :], re.I)
                if suffix:
                    hour = (int(n.value) - 1) % 12
                    if suffix.group(1).lower() in ("дня", "вечера"):
                        hour += 12
                    replacements.append(
                        (
                            time_command.end() + half.start(),
                            n.end + suffix.end(),
                            f"в {hour:02d}:30",
                        )
                    )
                else:
                    return Analysis(
                        text, text, numbers, "Уточни время: утром или вечером?"
                    )
    if time_command and not re.search(r"\bв\s+", text[time_command.end() :]):
        duration = parse_duration(text[time_command.end() :].lstrip())
        if duration:
            if duration.issue:
                return Analysis(text, text, numbers, duration.issue)
            offset = (
                time_command.end()
                + len(text[time_command.end() :])
                - len(text[time_command.end() :].lstrip())
            )
            if (
                duration.seconds <= 0
                or duration.seconds != duration.seconds.to_integral_value()
            ):
                return Analysis(
                    text,
                    text,
                    numbers,
                    "Укажи положительную длительность с точностью до секунды.",
                )
            replacements.append(
                (
                    offset + duration.start,
                    offset + duration.end,
                    "через " + _digits(duration.seconds) + " секунд",
                )
            )
    # A Roman token is ordinal only with a grammatical head (century/chapter/person).
    for m in ROMANS.finditer(text):
        value = roman_value(m.group())
        ctx = context_at(text, m.start(), m.end())
        if value is not None and (
            ctx.ordinal or explicit_number_context(text, m.start())
        ):
            spoken = (
                ordinal(value, ctx.case, ctx.gender, ctx.number, ctx.animate)
                if ctx.ordinal
                else cardinal(value)
            )
            replacements.append((m.start(), m.end(), spoken))
    roman_entities = tuple(
        Number(
            m.start(),
            m.end(),
            Decimal(roman_value(m.group())),
            "ordinal" if context_at(text, m.start(), m.end()).ordinal else "cardinal",
            m.group(),
        )
        for m in ROMANS.finditer(text)
        if roman_value(m.group()) is not None
        and (
            context_at(text, m.start(), m.end()).ordinal
            or explicit_number_context(text, m.start())
        )
    )
    return Analysis(
        text,
        _apply(text, replacements),
        tuple(sorted((*numbers, *roman_entities), key=lambda n: n.start)),
    )
