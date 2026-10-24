"""Bounded, session-only slot filling shared by GUI and voice.

Reuse handler._pending_question; never write corrections/facts or call the LLM.
Resolved commands return to the normal pipeline, including password checks.
"""

from dataclasses import dataclass
import re
import time

from jarvis.language import analyze_command
from jarvis.language.numbers import digit_numbers, word_numbers
from jarvis.language.time import HALF, parse_duration
from jarvis.language.units import TOKEN, unit_at
from jarvis.intents.verbs import COMMAND_VERBS
from jarvis.text_utils import normalize

TIMEOUT = 30.0
MAX_ATTEMPTS = 3
OPEN = re.compile(r"^(?:открой|открывай|запусти|включи|врубай)$")
TIMER = re.compile(
    r"^(?:(?:поставь|установи)\s+)?(?:таймер|напоминание|напомни|напоминай)\b\s*",
    re.I,
)
CORRECTION = re.compile(r"(?:^|[\s,;.…]+)(?:нет|точнее)\s*[,;:.…]?\s+", re.I)
PROMPTS = {
    "target": "Какое приложение открыть? Назови приложение или скажи «отмена».",
    "time": "На сколько поставить таймер или в какое время напомнить?",
    "unit": "В каких единицах: секундах, минутах или часах?",
}


@dataclass(frozen=True)
class TimeSlot:
    command: str = ""
    body: str = ""
    partial: str = ""
    issue: str = ""


def pending_alive(pending):
    if not isinstance(pending, dict):
        return False
    if pending.get("type") == "command_slot":
        return time.monotonic() < pending.get("deadline", 0)
    return time.time() < pending.get("expires_at", 0)


def _ask(handler, slot, **data):
    handler._pending_question = {
        "type": "command_slot",
        "slot": slot,
        "deadline": time.monotonic() + TIMEOUT,
        # Совместимость окна голосового ввода; проверка срока — монотонная.
        "expires_at": time.time() + TIMEOUT,
        "attempts": 0,
        **data,
    }
    return PROMPTS[slot]


def _retry(handler, pending, prompt):
    pending["attempts"] += 1
    if pending["attempts"] >= MAX_ATTEMPTS:
        handler._pending_question = None
        return "Не удалось уточнить команду. Действие отменено; скажи команду заново."
    # Не продлеваем срок при каждом непонятном ответе.
    return prompt


def _last_version(text):
    return CORRECTION.split(text)[-1].strip().rstrip(" .!?…")


def _has_duration_unit(text):
    if HALF.search(text):
        return True
    for token in TOKEN.finditer(text):
        unit = unit_at(text, token.start())
        if unit and unit[0].dimension == "duration":
            return True
    return False


def _time_slot(text):
    """Use shared numeric grammar; a bare number never defaults to minutes."""
    text = text.strip().rstrip(" .!?…")
    if re.match(r"^[.,]\d", text):
        return TimeSlot(issue="Укажи ноль перед десятичным разделителем.")
    if not text:
        return TimeSlot()
    if re.fullmatch(r"\d{1,2}[:.]\d{2}", text):
        text = "в " + text
    if normalize(text).startswith("не "):
        return TimeSlot(issue="Укажи время без отрицания.")
    analysis = analyze_command("таймер " + text)
    if analysis.issue:
        return TimeSlot(issue=analysis.issue)
    clock = re.match(r"^в\s+(\d{1,2}:\d{2})\b\s*", analysis.command[7:], re.I)
    if clock:
        rest = analysis.command[7:][clock.end() :].strip()
        return TimeSlot(command="в " + clock[1], body=rest)
    duration = parse_duration(text)
    if duration and _has_duration_unit(text[: duration.end]):
        if duration.issue:
            return TimeSlot(issue=duration.issue)
        seconds = duration.seconds
        if seconds <= 0 or seconds != seconds.to_integral_value():
            return TimeSlot(issue="Укажи положительное время с точностью до секунды.")
        return TimeSlot(
            command=f"через {int(seconds)} секунд",
            body=text[duration.end :].strip(" ,.!?…"),
        )
    number_text = re.sub(r"^(?:на|через)\s+", "", text, flags=re.I)
    numbers = (*word_numbers(number_text), *digit_numbers(number_text))
    whole = [n for n in numbers if n.start == 0 and n.end == len(number_text)]
    if len(whole) == 1 and whole[0].kind == "cardinal" and whole[0].value > 0:
        return TimeSlot(partial=number_text)
    return TimeSlot()


def _new_turn(cmd):
    tokens = cmd.split()
    if not tokens:
        return False
    return tokens[0] in COMMAND_VERBS or tokens[0] in {
        "установи",
        "таймер",
        "напоминание",
        "расскажи",
        "почему",
        "зачем",
        "как",
        "кто",
        "что",
        "какие",
        "список",
        "погода",
        "привет",
        "спасибо",
        "режим",
        "пауза",
        "продолжи",
        "следующий",
        "предыдущий",
        "отмени",
        "сбрось",
        "который",
        "громкость",
        "яркость",
        "плей",
        "play",
        "pause",
        "дальше",
        "останови",
    }


def _known_target(handler, answer):
    """Only an exact known name: a slot answer must not guess an arbitrary site."""
    target = normalize(answer)
    if not target or len(target) > 100:
        return None
    for app in handler.apps:
        names = (app.key, app.title, *app.aliases)
        if any(target == normalize(name) for name in names):
            return normalize(app.aliases[0]) if app.aliases else normalize(app.title)
    # Installed indexes are already warmed by IntentHandler; no extra scan/cache.
    for name in handler.installed:
        if normalize(name) == target:
            return target
    for title, _appid in handler.steam_games:
        if normalize(title) == target:
            return target
    return None


def begin(ctx):
    """Start only supported, explicitly incomplete commands; other intents pass."""
    h = ctx.handler
    from jarvis.intents.fast.custom import find_custom

    if OPEN.fullmatch(ctx.cmd):
        if find_custom(getattr(h, "custom", []), ctx.cmd) is not None:
            return None
        return _ask(h, "target", action="open")
    raw = (getattr(h, "_raw_cmd", "") or ctx.cmd).strip()
    # Reuse analysis already done by handle(); do not parse every command twice.
    analysis = getattr(h, "_number_analysis", None)
    if analysis is None or normalize(analysis.command) != ctx.cmd:
        raw = ctx.cmd
    match = TIMER.match(raw)
    if not match:
        return None
    if find_custom(getattr(h, "custom", []), ctx.cmd) is not None:
        return None
    tail = raw[match.end() :].strip()
    corrected = _last_version(tail)
    value = _time_slot(corrected)
    if value.command:
        if re.match(r"^(?:или|либо)\b", value.body, re.I):
            return _ask(h, "time", action="timer", text="") + " Назови одно время."
        if corrected != tail.strip(" ,.!?…"):
            # Only an explicit replacement of a time, not "say no" in a reminder.
            if not value.body:
                original = _time_slot(CORRECTION.split(tail)[0].strip())
                body = original.body if original.command else ""
                ctx.cmd = normalize("таймер " + value.command + " " + body)
        return None
    if value.issue:
        return _ask(h, "time", action="timer", text="") + " " + value.issue
    if value.partial:
        return _ask(h, "unit", action="timer", text="", partial=value.partial)
    # Preserve the payload of an incomplete reminder, but not malformed time.
    body = tail if tail and not re.match(r"^(?:на|через|в)\b", tail, re.I) else ""
    return _ask(h, "time", action="timer", text=body)


def resume(ctx):
    h = ctx.handler
    pending = h._pending_question
    if not pending_alive(pending):
        h._pending_question = None
        # New full commands still work; a stale slot answer never reaches LLM.
        if _new_turn(ctx.cmd):
            return None
        return "Время уточнения истекло. Скажи команду заново."
    answer = _last_version(getattr(h, "_raw_cmd", "") or ctx.cmd)
    clean = normalize(answer)
    if clean in {"нет", "не надо", "не нужно", "отмени"}:
        h._pending_question = None
        return "Действие отменено."
    if _new_turn(clean):
        h._pending_question = None
        return None
    if pending["slot"] == "target":
        target = _known_target(h, answer)
        if not target:
            return _retry(
                h,
                pending,
                "Не нашёл однозначное название приложения. " + PROMPTS["target"],
            )
        command = "открой " + target
    else:
        if pending["slot"] == "unit":
            unit = unit_at(answer, 0)
            if unit and unit[0].dimension == "duration" and unit[1] == len(answer):
                answer = pending["partial"] + " " + answer
        value = _time_slot(answer)
        if value.partial:
            pending.update(slot="unit", partial=value.partial)
            return _retry(h, pending, PROMPTS["unit"])
        if not value.command or value.body:
            return _retry(h, pending, value.issue or PROMPTS["time"])
        command = "таймер " + value.command
        if pending.get("text"):
            command += " " + pending["text"]
    h._pending_question = None
    ctx.cmd = normalize(command)
    ctx.state["clarification_resumed"] = True
    return None
