"""Персона ассистента — стиль общения, черты, backstory, tone.

Tone — «планка» общения, которую может задать юзер:
    auto         — LLM сама подстраивается под собеседника (по умолчанию)
    polite       — явно вежливый, без мата
    unrestricted — не стесняется, если юзер сам матерится

По умолчанию — auto: никаких счётчиков, никаких правил-костылей.
LLM получает инструкцию «подстраивайся» и делает это сама.
Tone — только ручной override, если юзер хочет явно ограничить.
"""

import logging
import time

from jarvis import profile

log = logging.getLogger("jarvis.persona")

DEFAULT_PERSONA = {
    "assistant_name": "Феникс",
    "speech_style": "friendly",
    "tone": "auto",
    "traits": [],
    "backstory": "",
    "onboarding_done": False,
    "onboarding_at": 0.0,
}

VALID_STYLES = ("formal", "friendly", "sarcastic", "brief")

STYLE_DESCRIPTIONS = {
    "formal": "на «вы», официально, без фамильярности",
    "friendly": "на «ты», тепло и по-дружески",
    "sarcastic": "с сухим юмором и лёгкой иронией",
    "brief": "коротко, по делу, минимум слов",
}

STYLE_ALIASES = {
    "формальный": "formal", "официальный": "formal", "на вы": "formal", "строгий": "formal",
    "дружеский": "friendly", "дружелюбный": "friendly", "тёплый": "friendly", "на ты": "friendly",
    "саркастичный": "sarcastic", "сарказм": "sarcastic", "ироничный": "sarcastic",
    "короткий": "brief", "краткий": "brief", "по делу": "brief", "лаконичный": "brief",
}

# --- Tone: «планка» общения -----------------------------------------------

VALID_TONES = ("auto", "polite", "unrestricted")

TONE_DESCRIPTIONS = {
    "auto": "подстраивается под собеседника",
    "polite": "явно вежливый, без мата",
    "unrestricted": "не стесняется, если юзер сам матерится",
}

TONE_ALIASES = {
    # auto
    "авто": "auto",
    "как обычно": "auto",
    "обычно": "auto",
    "проще": "auto",
    "по-простому": "auto",
    "на одной волне": "auto",
    # polite
    "вежли": "polite",
    "нормальн": "polite",
    "цензур": "polite",
    "без мата": "polite",
    "без матер": "polite",
    # unrestricted
    "без цензуры": "unrestricted",
    "без тормозов": "unrestricted",
    "материться": "unrestricted",
    "развяжи язык": "unrestricted",
    "не стесняйся": "unrestricted",
}


def get() -> dict:
    raw = profile.get("persona", {}) or {}
    result = dict(DEFAULT_PERSONA)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k not in DEFAULT_PERSONA:
                continue
            # Не позволяем None затирать дефолт.
            if v is None:
                continue
            result[k] = v
    # Валидация tone — если в профиле мусор, откатываем на auto.
    if result.get("tone") not in VALID_TONES:
        result["tone"] = "auto"
    return result


def set_persona(data: dict) -> bool:
    current = get()
    for key in DEFAULT_PERSONA:
        if key in data:
            current[key] = data[key]
    return profile.set("persona", current)


def set_field(key: str, value) -> bool:
    if key not in DEFAULT_PERSONA:
        log.warning("persona.set_field: неизвестный ключ %r", key)
        return False
    current = get()
    current[key] = value
    return profile.set("persona", current)


def normalize_style(text: str) -> str | None:
    text_low = text.strip().lower()
    if text_low in VALID_STYLES:
        return text_low
    for alias, style in STYLE_ALIASES.items():
        if alias in text_low:
            return style
    return None


def set_style(style: str) -> str:
    style = normalize_style(style) or "friendly"
    set_field("speech_style", style)
    log.info("Persona: стиль → %s", style)
    return f"Стиль общения: {STYLE_DESCRIPTIONS[style]}."


def normalize_tone(text: str) -> str | None:
    """«говори проще» → auto, «без цензуры» → unrestricted, ..."""
    text_low = text.strip().lower()
    if text_low in VALID_TONES:
        return text_low
    # Сортируем алиасы по длине (длинные первыми), чтобы
    # «без цензуры» матчилось раньше, чем «цензур».
    sorted_aliases = sorted(TONE_ALIASES.items(), key=lambda x: -len(x[0]))
    for alias, tone in sorted_aliases:
        if alias in text_low:
            return tone
    return None


def set_tone(tone: str) -> str:
    tone = normalize_tone(tone) or "auto"
    set_field("tone", tone)
    log.info("Persona: tone → %s", tone)
    return f"Тон общения: {TONE_DESCRIPTIONS[tone]}."


def is_onboarded() -> bool:
    return bool(get().get("onboarding_done"))


def mark_onboarded() -> bool:
    return set_persona({"onboarding_done": True, "onboarding_at": time.time()})


def reset_onboarding() -> bool:
    return set_persona({"onboarding_done": False, "onboarding_at": 0.0})


def build_prompt_block() -> str:
    """Блок для system prompt: стиль + tone + traits + backstory."""
    p = get()
    lines = []

    style = p.get("speech_style") or "friendly"
    style_desc = STYLE_DESCRIPTIONS.get(style)
    if style_desc:
        lines.append(f"- Стиль общения: {style_desc}")

    tone = p.get("tone") or "auto"
    if tone == "auto":
        lines.append(
            "- Тон: подстраивайся под собеседника. "
            "Юзер вежливый → вежливо. Юзер матерится → можешь вставить мат, "
            "если уместно. Юзер грустит → мягко, без шуток."
        )
    elif tone == "polite":
        lines.append("- Тон: явно вежливый. Без мата. Без грубости.")
    elif tone == "unrestricted":
        lines.append(
            "- Тон: не стесняйся. Если юзер матерится — можешь ответить тем же. "
            "Чёрный юмор допустим, если настроение позволяет."
        )

    traits = p.get("traits") or []
    if traits:
        lines.append(f"- Черты характера: {', '.join(traits)}")

    backstory = (p.get("backstory") or "").strip()
    if backstory:
        lines.append(f"- Контекст: {backstory}")

    assistant_name = (p.get("assistant_name") or "Феникс").strip()
    if assistant_name and assistant_name != "Феникс":
        lines.append(f"- Тебя зовут {assistant_name}")

    if not lines:
        return ""

    return "\n\nПерсона ассистента:\n" + "\n".join(lines) + "\n"


def describe() -> str:
    p = get()
    style = p.get("speech_style") or "friendly"
    style_desc = STYLE_DESCRIPTIONS.get(style, style)
    tone = p.get("tone") or "auto"
    tone_desc = TONE_DESCRIPTIONS.get(tone, tone)
    name = p.get("assistant_name") or "Феникс"

    parts = [f"Меня зовут {name}", f"стиль общения: {style_desc}",
             f"тон: {tone_desc}"]
    traits = p.get("traits") or []
    if traits:
        parts.append(f"черты: {', '.join(traits)}")
    return ". ".join(parts).capitalize() + "."