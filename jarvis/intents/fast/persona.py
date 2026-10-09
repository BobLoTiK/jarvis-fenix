"""Команды персоны: стиль общения, описание, сброс онбординга."""

import re

from jarvis import persona


def persona_fast(handler, cmd: str) -> str | None:
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