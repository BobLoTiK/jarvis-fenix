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
    """Сохраняет факт. Ключ нормализуется (нижний регистр).

    Пишем через profile.mutate: get → правка → set в два вызова
    не атомарен, и «запомни» параллельно с observer теряло факты.
    """
    key = key.strip().lower()
    value = value.strip()
    if not key or not value:
        return False

    def _apply(facts):
        facts = dict(facts or {})
        facts[key] = value
        return facts

    ok = profile.mutate("facts", _apply)
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
    key = key.strip().lower()

    def _apply(facts):
        facts = dict(facts or {})
        if key not in facts:
            raise KeyError(key)  # «менять нечего» — mutate вернёт False
        del facts[key]
        return facts

    ok = profile.mutate("facts", _apply)
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

def select_context(query=None):
    """Профиль и факты, действительно нужные текущему запросу."""
    from jarvis.memory_context import select_memory
    return select_memory(query, {
        "name": profile.get("name"),
        "default_city": profile.get("default_city"),
    }, all_facts())


def build_context(include_facts: bool = True, *, query=None) -> str:
    """Контекст по запросу. Нет запроса/релевантности — нет личных данных.

    Коррекции команд применяет pipeline; они не становятся инструкциями
    для свободного диалога. Сохранённые данные на диске не удаляются.
    """
    selection = select_context(query)
    parts = []
    labels = {"name": "Имя пользователя", "default_city": "Город по умолчанию"}
    lines = [f"- {labels[k]}: {v}" for k, v in selection.profile.items()]
    if lines:
        parts.append("Сведения профиля, необходимые текущему запросу:\n" + "\n".join(lines))
    if include_facts and selection.facts:
        lines = [f"- {k}: {v}" for k, v in selection.facts.items()]
        parts.append("Сведения, относящиеся к текущему запросу:\n" + "\n".join(lines))
    return "\n\n" + "\n\n".join(parts) + "\n" if parts else ""
