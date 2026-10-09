"""Mood — эмоциональное состояние ассистента.

Persona = "кто я" (стиль, черты, backstory). Стабильное.
Mood    = "как я реагирую сейчас" (настроение). Меняется.

Хранится в profile.json → mood:
    {
        "state": "happy",
        "since": 1791626400.0,
        "reason": "похвала"
    }

Состояния:
    neutral  — по умолчанию
    happy    — похвала, благодарность
    excited  — радость, восторг
    annoyed  — грубость в адрес ассистента
    bored    — долгое молчание
    tired    — юзер сказал «устал»

Влияние:
    - TTS: скорость речи (excited +10%, tired -10%).
    - GUI: цвет статус-сферы.
    - System prompt: LLM отвечает с учётом настроения.

Подписки: subscribe(callback(old_state, new_state)).
"""

import logging
import re
import time
from threading import RLock

from jarvis import profile

log = logging.getLogger("jarvis.mood")

# Все допустимые состояния.
STATES = ("neutral", "happy", "excited", "annoyed", "bored", "tired")

# Значение по умолчанию.
DEFAULT_MOOD = {
    "state": "neutral",
    "since": 0.0,
    "reason": "",
}

# Подписки и лок.
_lock = RLock()
_listeners: list = []

# Время «жизни» состояния до возврата к neutral.
DEFAULT_DECAY_SEC = 300  # 5 минут


# =================================================================
# Чтение / запись
# =================================================================

def get() -> dict:
    """Текущее настроение (с дефолтами)."""
    raw = profile.get("mood", {}) or {}
    result = dict(DEFAULT_MOOD)
    if isinstance(raw, dict):
        for k in DEFAULT_MOOD:
            if raw.get(k) is not None:
                result[k] = raw[k]
    return result


def get_state() -> str:
    """Только state — для быстрых проверок."""
    return get().get("state", "neutral")


def set_mood(state: str, reason: str = "") -> bool:
    """Устанавливает настроение + оповещает подписчиков.

    Если state совпадает с текущим — ничего не делает (кроме reason).
    """
    if state not in STATES:
        log.warning("mood.set_mood: неизвестное состояние %r", state)
        return False

    current = get_state()
    current_reason = get().get("reason", "")

    # Если ничего не изменилось — выходим.
    if current == state and current_reason == reason:
        return True

    ok = profile.set("mood", {
        "state": state,
        "since": time.time(),
        "reason": reason,
    })
    if not ok:
        log.error("mood.set_mood: не удалось сохранить %r", state)
        return False

    log.info("Mood: %s → %s (%s)", current, state, reason)

    with _lock:
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(current, state)
        except Exception:
            log.exception("Подписчик mood упал на %s → %s", current, state)

    return True


# =================================================================
# Подписки
# =================================================================

def subscribe(callback) -> None:
    """callback(old_state, new_state) — вызывается при смене настроения."""
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)


def unsubscribe(callback) -> None:
    """Удаляет подписку."""
    with _lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


# =================================================================
# Детекция из текста
# =================================================================

# Регулярки для быстрой эвристики.
_PRAISE = re.compile(
    r"\b(спасибо|благодар\w*|молодец|умниц\w*|круто|отлично|"
    r"супер|класс|здорово|хорош\w*|правильно|верно)\b",
    flags=re.IGNORECASE,
)

_EXCITED = re.compile(
    r"\b(ура|ура-ура|получилось|вау|ого|ничего себе|невероятно|"
    r"офигенно|офигеть|обалдеть|кайф)\b",
    flags=re.IGNORECASE,
)

_RUDE = re.compile(
    r"\b(тупой|тупая|тупица|дурак|дура|идиот|идиотка|дебил|дебилка|"
    r"кретин|кретинка|бестолочь|ничего не понимаешь|"
    r"туп\w* ты|идиот\w*)\b",
    flags=re.IGNORECASE,
)

_TIRED = re.compile(
    r"\b(устал\w*|засыпаю|спать хочу|вымотан\w*|без сил|"
    r"не могу больше|замучил\w*)\b",
    flags=re.IGNORECASE,
)


def detect(cmd: str) -> str | None:
    """Быстрая эвристика: какое настроение вызвать?

    Возвращает state или None (не менять).
    """
    if not cmd:
        return None

    # Порядок важен — грубость выше похвалы.
    # Иначе «спасибо, ты тупой» уйдёт в happy.
    if _RUDE.search(cmd):
        return "annoyed"
    if _TIRED.search(cmd):
        return "tired"
    if _EXCITED.search(cmd):
        return "excited"
    if _PRAISE.search(cmd):
        return "happy"
    return None


def apply_from_text(cmd: str) -> bool:
    """Определяет и устанавливает mood. Возвращает True, если изменил."""
    detected = detect(cmd)
    if not detected:
        return False
    return set_mood(detected, reason="dialog")


# =================================================================
# Decay — возврат к neutral
# =================================================================

def decay(max_age_sec: int = DEFAULT_DECAY_SEC) -> bool:
    """Возвращает к neutral, если состояние «старое».

    Вызывается периодически (раз в минуту) из фонового потока.
    """
    m = get()
    if m["state"] == "neutral":
        return False

    age = time.time() - m.get("since", 0)
    if age < max_age_sec:
        return False

    log.info("Mood: %s устарел (%.0f сек) → neutral",
             m["state"], age)
    set_mood("neutral", reason="decay")
    return True


# =================================================================
# Влияние на систему
# =================================================================

# Множители скорости речи для TTS.
_RATE_MULTIPLIERS = {
    "neutral": 1.0,
    "happy":   1.0,
    "excited": 1.1,
    "annoyed": 1.0,
    "bored":   0.95,
    "tired":   0.9,
}


def effective_rate(base_rate: float) -> float:
    """Скорость речи с учётом mood."""
    mult = _RATE_MULTIPLIERS.get(get_state(), 1.0)
    return round(base_rate * mult, 3)


# Цвета для GUI — статус-сфера.
_COLORS = {
    "neutral": "#484f58",
    "happy":   "#3fb950",
    "excited": "#d29922",
    "annoyed": "#f85149",
    "bored":   "#8b949e",
    "tired":   "#6e7681",
}


def color() -> str:
    """Цвет статус-сферы для текущего настроения."""
    return _COLORS.get(get_state(), _COLORS["neutral"])


# =================================================================
# System prompt
# =================================================================

_PROMPT_HINTS = {
    "happy":   "Пользователь тебя похвалил или поблагодарил — "
               "отвечай теплее, бодрее, можно слегка самодовольно.",
    "excited": "Пользователь в восторге — поддержи его энергию, "
               "отвечай эмоциональнее.",
    "annoyed": "Пользователь грубит — НЕ извиняйся, ответь сухо, "
               "с лёгкой иронией, но не хами. Осади спокойно.",
    "bored":   "Давно молчание или скучный диалог — отвечай коротко, "
               "с ленцой, не разворачивайся.",
    "tired":   "Пользователь устал — отвечай мягко, чуть медленнее, "
               "без лишних слов.",
}


def build_prompt_block() -> str:
    """Блок для system prompt на основе текущего настроения."""
    state = get_state()
    hint = _PROMPT_HINTS.get(state)
    if not hint:
        return ""
    return f"\n\nТекущее настроение диалога: {state}.\n{hint}\n"


# =================================================================
# Описание для озвучки
# =================================================================

_DESCRIPTIONS = {
    "neutral": "Спокойное, ровное.",
    "happy":   "Хорошее, тёплое.",
    "excited": "Восторженное, бодрое.",
    "annoyed": "Раздражённое.",
    "bored":   "Скучающее.",
    "tired":   "Уставшее.",
}


def describe() -> str:
    """Человеческое описание для озвучки."""
    state = get_state()
    desc = _DESCRIPTIONS.get(state, "Спокойное.")
    since = get().get("since", 0)
    if since:
        age = int(time.time() - since)
        if age < 60:
            when = f"{age} секунд назад"
        elif age < 3600:
            when = f"{age // 60} минут назад"
        else:
            when = f"{age // 3600} часов назад"
        return f"Настроение: {desc} Установлено {when}."
    return f"Настроение: {desc}"


# =================================================================
# Команды (для fast/persona.py)
# =================================================================

def handle_mood_command(cmd: str) -> str | None:
    """Голосовые команды настроения. Возвращает ответ или None."""
    low = cmd.lower()

    # «как настроение» / «какое у тебя настроение»
    if (re.search(r"(какое|как)\s+(у\s+тебя\s+)?настроение", low)
            or low in {"настроение", "как настроение"}):
        return describe()

    # «не грусти» / «взбодрись»
    if re.search(r"(не\s+грусти|взбодрись|улыбнись|повеселей)", low):
        set_mood("happy", reason="user_request")
        return "Стараюсь."

    # «успокойся»
    if re.search(r"(успокойся|не\s+злись|не\s+сердись)", low):
        set_mood("neutral", reason="user_request")
        return "Уже спокоен."

    return None