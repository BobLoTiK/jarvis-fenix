"""Самообучение Феникса: факты и коррекции.

Факты:
    «Феникс, запомни: мой город Нижний Новгород» → facts["город"] = "Нижний Новгород".

Коррекции:
    «Феникс, открой лок» → Феникс: «Открываю калькулятор»
    «Феникс, это не то, я сказал логи» → corrections["открой лок"] = "открой логи"

Подгрузка:
    В brain.py перед запросом к LLM добавляется блок с фактами и corrections.

Хранение:
    profiles/<user>/profile.json — там же, где name, default_city.
    Ключи: facts (dict), corrections (dict).
"""

import logging
from difflib import SequenceMatcher

from jarvis import profile

log = logging.getLogger("jarvis.learning")


def _notify_index(func: str, *args) -> None:
    """Сообщает векторной памяти об изменении фактов.

    Импорт ленивый: vectormem сам импортирует learning (цикл был бы иначе).
    Ошибка памяти не должна ломать сохранение факта.
    """
    try:
        from jarvis import vectormem
        getattr(vectormem, func)(*args)
    except Exception:
        log.exception("vectormem.%s упал", func)


# ---------------------------------------------------------------
# Факты
# ---------------------------------------------------------------

def add_fact(key: str, value: str) -> bool:
    """Сохраняет факт. Ключ нормализуется (нижний регистр)."""
    key = key.strip().lower()
    value = value.strip()
    if not key or not value:
        return False

    facts = profile.get("facts", {}) or {}
    facts[key] = value
    ok = profile.set("facts", facts)
    if ok:
        log.info("Факт: %s = %r", key, value)
        _notify_index("index_fact", key, value)
    return ok


def get_fact(key: str, default=None):
    facts = profile.get("facts", {}) or {}
    return facts.get(key.strip().lower(), default)


def all_facts() -> dict:
    return profile.get("facts", {}) or {}


def forget_fact(key: str) -> bool:
    facts = profile.get("facts", {}) or {}
    key = key.strip().lower()
    if key not in facts:
        return False
    del facts[key]
    ok = profile.set("facts", facts)
    if ok:
        _notify_index("forget_fact", key)
    return ok


# ---------------------------------------------------------------
# Коррекции
# ---------------------------------------------------------------

def add_correction(wrong: str, right: str) -> bool:
    """Сохраняет коррекцию: «открой лок» → «открой логи»."""
    wrong = wrong.strip().lower()
    right = right.strip()
    if not wrong or not right:
        return False
    if wrong == right.lower():
        return False

    corrections = profile.get("corrections", {}) or {}
    corrections[wrong] = right
    ok = profile.set("corrections", corrections)
    if ok:
        log.info("Коррекция: %r → %r", wrong, right)
    return ok


def find_correction(cmd: str, threshold: float = 0.85) -> str | None:
    """Ищет коррекцию для команды.

    Сначала точное совпадение, потом — нечёткое (SequenceMatcher).
    """
    corrections = profile.get("corrections", {}) or {}
    if not corrections:
        return None

    cmd_low = cmd.strip().lower()
    # Точное
    if cmd_low in corrections:
        return corrections[cmd_low]

    # Нечёткое
    best, best_ratio = None, threshold
    for wrong, right in corrections.items():
        ratio = SequenceMatcher(None, cmd_low, wrong).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, right
    if best:
        log.info("Коррекция (нечётко): %r → %r (ratio %.2f)", cmd, best, best_ratio)
    return best


def all_corrections() -> dict:
    return profile.get("corrections", {}) or {}


def forget_correction(wrong: str) -> bool:
    corrections = profile.get("corrections", {}) or {}
    wrong = wrong.strip().lower()
    if wrong not in corrections:
        return False
    del corrections[wrong]
    return profile.set("corrections", corrections)


# ---------------------------------------------------------------
# Сборка контекста для промпта
# ---------------------------------------------------------------

def build_context(include_facts: bool = True) -> str:
    """Собирает блок для промпта из профиля, фактов и коррекций.

    include_facts=False — когда релевантные факты уже отобрала векторная
    память (vectormem): иначе они попадут в промпт дважды.

    Возвращает пустую строку, если нечего добавить.
    """
    parts = []

    # Базовые поля профиля — name, default_city.
    # Без них LLM не знает, как зовут пользователя и где он живёт,
    # хотя _small_talk и профиль-команды это знают.
    name = profile.get("name")
    city = profile.get("default_city")
    profile_lines = []
    if name:
        profile_lines.append(f"- Имя пользователя: {name}")
    if city:
        profile_lines.append(f"- Город по умолчанию: {city}")
    if profile_lines:
        parts.append("Данные профиля пользователя:\n" + "\n".join(profile_lines))

    facts = all_facts() if include_facts else {}
    if facts:
        lines = [f"- {k}: {v}" for k, v in facts.items()]
        parts.append("Известные факты о пользователе:\n" + "\n".join(lines))

    corrections = all_corrections()
    if corrections:
        lines = [f"- «{wrong}» → «{right}»" for wrong, right in corrections.items()]
        parts.append("Известные исправления (если пользователь говорит первое, делай второе):\n"
                     + "\n".join(lines))

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts) + "\n"