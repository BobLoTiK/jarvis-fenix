"""Профиль: смена, список, факты «запомни: X — Y»."""

import logging
import re

from jarvis import learning, profile

log = logging.getLogger("jarvis.intents")


_NOT_A_CITY = (
    "открой", "закрой", "найди", "включи", "выключи",
    "как дела", "кто ты", "спасибо", "привет", "пока",
    "который час", "какое число", "сделай скриншот",
    "загугли", "поищи", "напечатай",
)

# «мой город Казань» / «моя работа программист» / «мое имя Максим»
# Первое слово после «мой/моя/мое/мои» — ключ, остальное — значение.
_MY_KEY_MAP = {
    "город": "город",
    "работа": "работа",
    "имя": "имя",
    "возраст": "возраст",
    "профессия": "профессия",
    "день": "день рождения",
    "день рождения": "день рождения",
    "любимая игра": "любимая игра",
    "любимый фильм": "любимый фильм",
    "любимая музыка": "любимая музыка",
}


def profile_fast(handler, cmd: str) -> str | None:
    log.info("profile_fast: %r", cmd)

    # «я — Маша», «зови меня X», «переключись на X».
    # БЕЗ голого «я » — иначе «я хочу спать» создаёт профиль.
    m = re.match(
        r"^(?:я\s*[-—]\s*|зови\s+меня\s+|переключись\s+на\s+|я\s+это\s+)"
        r"([а-яёa-z][а-яёa-z\s\-]{0,40})$",
        cmd,
    )
    if m:
        name = m.group(1).strip()
        if name and name not in _NOT_A_CITY:
            return profile.switch(name)

    # «кто активен», «какой профиль»
    if (re.search(r"(кто|какой)\s+(сейчас\s+)?(активен|профиль|пользователь)", cmd)
            or cmd in {"кто активен", "какой профиль", "текущий профиль"}):
        name = profile.get("name") or profile.current()
        return f"Сейчас профиль {name}."

    # «список профилей»
    if (re.search(r"(список|какие|покажи)\s+профил", cmd)
            or cmd in {"список профилей", "какие профили"}):
        all_p = profile.list_all()
        if not all_p:
            return "Профилей нет."
        return f"Профили: {', '.join(all_p)}."

    # «запомни: X — Y» → facts
    m = re.match(r"^(?:запомни|запиши)\s*[,:]?\s*(?:что\s+)?(.+)$", cmd)
    if m:
        fact = m.group(1).strip(" ,.:!?")
        if not fact:
            return "Что запомнить?"

        key, value = _parse_fact(fact)
        if not key or not value:
            return "Что запомнить?"

        ok = learning.add_fact(key, value)
        if ok:
            return f"Запомнил: {key} — {value}."
        return "Не удалось сохранить — проверь профиль (возможно, битый JSON)."

    # «что ты обо мне знаешь»
    if (re.search(r"(что|чё)\s+ты\s+(обо\s+мне\s+)?знаешь", cmd)
            or cmd in {"что ты обо мне знаешь", "что ты знаешь"}):
        return _describe_known(profile)

    # «забудь X»
    m = re.match(r"^забудь\s+(?:факт\s+)?(.+)$", cmd)
    if m:
        key = m.group(1).strip(" ,.:!?").lower()
        if profile.forget_fact(key):
            return f"Забыл: {key}."
        return f"Факта «{key}» не знаю."

    return None


def _parse_fact(fact: str) -> tuple[str, str]:
    """Разбирает факт из строки.

    Варианты:
        «мой город Казань»       → ("город", "Казань")
        «город — Казань»         → ("город", "Казань")
        «город: Казань»          → ("город", "Казань")
        «работа программист»     → ("работа", "программист")
        «люблю пиццу»            → ("люблю", "пиццу")  — как есть
    """
    # 1. С разделителем: «X — Y», «X: Y», «X = Y»
    m = re.match(r"^(.+?)\s*[—\-=:]\s*(.+)$", fact)
    if m:
        return m.group(1).strip().lower(), m.group(2).strip()

    # 2. «мой/моя/мое/мои X Y» → ключ X, значение Y
    m = re.match(r"^мо(?:й|я|е|и)\s+(.+)$", fact, flags=re.IGNORECASE)
    if m:
        rest = m.group(1).strip()
        # Первое слово — ключ (нормализуем через карту), остальное — значение.
        parts = rest.split(maxsplit=1)
        if len(parts) == 2:
            key_raw = parts[0].lower()
            value = parts[1].strip()
            key = _MY_KEY_MAP.get(key_raw, key_raw)
            return key, value

    # 3. «X Y» — первое слово ключ (если есть в карте), остальное — значение.
    parts = fact.split(maxsplit=1)
    if len(parts) == 2:
        key_raw = parts[0].lower()
        if key_raw in _MY_KEY_MAP:
            return _MY_KEY_MAP[key_raw], parts[1].strip()

    # 4. Fallback — весь факт как ключ, значение «да».
    return fact.lower(), "да"


def _describe_known(profile_module) -> str:
    facts = profile_module.all_facts()
    name = profile_module.get("name")
    city = profile_module.get("default_city")

    parts = []
    if name:
        parts.append(f"Тебя зовут {name}")
    if city:
        parts.append(f"твой город — {city}")
    if facts:
        facts_str = "; ".join(f"{k} — {v}" for k, v in facts.items())
        parts.append(f"Знаю: {facts_str}")
    if not parts:
        return "Пока ничего о тебе не знаю."
    return ". ".join(parts) + "."