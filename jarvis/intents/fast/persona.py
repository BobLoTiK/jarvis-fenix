"""Команды персоны: стиль общения, описание, сброс онбординга."""

import logging
import re

from jarvis import persona

log = logging.getLogger("jarvis.intents")


def persona_fast(handler, cmd: str) -> str | None:
    # Mood: «как настроение», «не грусти», «успокойся»
    try:
        from jarvis import mood
        reply = mood.handle_mood_command(cmd)
        if reply:
            return reply
    except Exception:
        log.exception("mood.handle_mood_command упал")

    # Tone: «говори проще», «без цензуры», «верни цензуру»
    if re.search(r"(говори|общайся|отвечай)\s+(проще|по-простому|нормально|вежливо|без\s+цензуры|без\s+тормозов)", cmd) \
            or re.search(r"(верни|включи)\s+(цензуру|вежливость|нормальный\s+тон)", cmd) \
            or re.search(r"(можно|разрешаю)\s+материться", cmd):
        if "проще" in cmd or "по-простому" in cmd:
            tone_text = "auto"
        elif "без цензуры" in cmd or "без тормозов" in cmd or "материться" in cmd:
            tone_text = "unrestricted"
        elif "нормально" in cmd or "вежливо" in cmd or "цензур" in cmd:
            tone_text = "polite"
        else:
            tone_text = "auto"
        return persona.set_tone(tone_text)

    # «какой у тебя тон», «как ты общаешься»
    if re.search(r"(какой|какая|текущ)\w*\s+(у\s+тебя\s+)?тон", cmd) \
            or re.search(r"как\s+ты\s+(сейчас\s+)?общаешься", cmd):
        p = persona.get()
        tone = p.get("tone") or "auto"
        desc = persona.TONE_DESCRIPTIONS.get(tone, tone)
        return f"Тон общения: {desc}."

    # «поменяй стиль на строгий», «говори на ты»
    if (re.search(r"(поменяй|смени|переключи|поставь|установи)\s+стил", cmd)
            or re.search(r"(говори|общайся)\s+(на\s+)?(ты|вы)", cmd)):
        m = re.search(r"(?:на|стиль)\s+([а-яёa-z\- ]+)$", cmd)
        style_text = m.group(1).strip() if m else cmd

        if "на ты" in cmd or style_text == "ты":
            style_text = "дружеский"
        elif "на вы" in cmd or style_text == "вы":
            style_text = "формальный"

        style = persona.normalize_style(style_text)
        if style:
            return persona.set_style(style)
        return ("Не понял стиль. Доступные: формальный, дружеский, "
                "саркастичный, короткий.")

    # «какой у тебя стиль», «как ты ко мне обращаешься»
    if (re.search(r"(какой|какая|текущ)\w*\s+(у\s+тебя\s+)?стил", cmd)
            or re.search(r"как\s+ты\s+(ко\s+мне\s+)?обращаешься", cmd)):
        return persona.describe()

    # «как тебя зовут»
    if re.search(r"(как\s+тебя\s+зовут|как\s+тебя\s+звать|твое\s+имя)", cmd):
        name = persona.get().get("assistant_name") or "Феникс"
        return f"Меня зовут {name}."

    # «давай заново познакомимся»
    if (re.search(r"(давай|давай\s+же)\s+заново\s+познакомимся", cmd)
            or re.search(r"(сбрось|сбросить|reset)\s+(персон|знакомств|онбординг)", cmd)
            or cmd in {"заново познакомимся", "сбрось персону", "сбрось знакомство"}):
        persona.reset_onboarding()
        return "О, давай! Как тебя зовут?"

    return None