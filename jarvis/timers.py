"""Таймеры и напоминания.

Голосом:
    «напомни через 10 минут выпить чай»      → через 10 минут скажет голосом
    «напомни в 18:30 позвонить маме»          → скажет в указанное время
    «напомни через полчаса»                   → без текста
    «какие напоминания»                       → список
    «отмени все напоминания»                  → очистка
    «таймер на 5 минут»                       → обратный отсчёт

Хранение: %APPDATA%\Phoenix\timers.json (USER_DIR — не папка кода).
При старте Феникса: загружает, проверяет, ставит threading.Timer на каждое.
"""

import datetime
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from jarvis import paths as _paths

log = logging.getLogger("jarvis.timers")

_lock = threading.RLock()
_scheduled: dict[int, threading.Timer] = {}  # id → Timer
_on_fire_callback = None  # функция, которая вызывается при срабатывании


# ---------------------------------------------------------------
# Пути
# ---------------------------------------------------------------

def _timers_file() -> Path:
    """Путь к timers.json в USER_DIR.

    Раньше файл лежал в BASE_DIR (папка кода) — баг:
    после установки туда писать нельзя, а на dev-машине
    файл мусорил в репозитории.
    """
    return _paths.user_dir() / "timers.json"


# ---------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------

def _load() -> list:
    path = _timers_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("Не удалось прочитать %s", path)
        return []


def _save(timers: list) -> None:
    """Атомарная запись timers.json.

    Уникальный .tmp через tempfile.mkstemp, os.replace для подмены.
    Иначе два параллельных вызова _save могут пересечься и оставить
    полупустой файл.
    """
    path = _timers_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=path.stem + "."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(timers, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception:
        log.exception("Не удалось сохранить %s", path)


# ---------------------------------------------------------------
# Разбор времени из фразы
# ---------------------------------------------------------------

_NUM_WORDS = {
    "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "пятнадцать": 15, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "полтора": 1.5,
}


def _parse_duration(text: str) -> int | None:
    """«через 10 минут» → 600 секунд. Возвращает int или None."""
    # «через X единица»
    m = re.search(r"через\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)?", text)
    if not m:
        # «на X минут» / «таймер на X»
        m = re.search(r"(?:на|таймер)\s+(\d+|[а-яё]+)\s*(секунд|мин|минут|час|часов|ч|с|м)",
                      text)
    if not m:
        # «полчаса», «час», «минуту»
        if "полчаса" in text or "пол часа" in text:
            return 30 * 60
        if re.search(r"\bчас\b", text):
            return 60 * 60
        if re.search(r"\bминуту\b", text):
            return 60
        return None

    raw = m.group(1)
    unit = m.group(2) or "мин"

    # число
    if raw.isdigit():
        num = int(raw)
    else:
        num = _NUM_WORDS.get(raw.lower())
        if num is None:
            return None

    # единица
    if unit.startswith("сек") or unit == "с":
        return int(num)
    if unit.startswith("мин") or unit == "м":
        return int(num * 60)
    if unit.startswith("час") or unit == "ч":
        return int(num * 3600)
    return int(num * 60)


def _parse_absolute_time(text: str) -> float | None:
    """«в 18:30» → timestamp. Возвращает float (unix) или None."""
    m = re.search(r"\bв\s+(\d{1,2})[:.](\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\bв\s+(\d{1,2})\s+час", text)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        # время уже прошло — значит, на завтра
        target += datetime.timedelta(days=1)
    return target.timestamp()


def _extract_reminder_text(cmd: str) -> str:
    """Вырезает из фразы текст напоминания (после времени)."""
    # убираем всё до времени (включительно)
    text = re.sub(r"^.*?(?:напомни|напоминание|таймер)\s*", "", cmd, count=1)
    text = re.sub(r"через\s+(\d+|[а-яё]+)\s*\S+", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}[:.]\d{2}", "", text, count=1)
    text = re.sub(r"\bв\s+\d{1,2}\s+час\w*", "", text, count=1)
    text = text.strip(" ,.:!?")
    return text


# ---------------------------------------------------------------
# Планирование
# ---------------------------------------------------------------

def set_on_fire(callback) -> None:
    """Регистрирует callback(timer_dict) — вызывается при срабатывании."""
    global _on_fire_callback
    _on_fire_callback = callback


def _fire(timer_id: int) -> None:
    """Срабатывание таймера."""
    with _lock:
        timers = _load()
        timer = next((t for t in timers if t["id"] == timer_id), None)
        if not timer:
            _scheduled.pop(timer_id, None)
            return
        # удаляем из файла
        timers = [t for t in timers if t["id"] != timer_id]
        _save(timers)
        _scheduled.pop(timer_id, None)

    log.info("Таймер #%d сработал: %s", timer_id, timer.get("text") or "(без текста)")
    if _on_fire_callback:
        try:
            _on_fire_callback(timer)
        except Exception:
            log.exception("Ошибка в callback таймера")


def _schedule_one(timer: dict) -> None:
    """Ставит threading.Timer на конкретное напоминание."""
    delay = timer["fire_at"] - time.time()
    if delay <= 0:
        # уже прошло — срабатываем сразу
        delay = 0.1
    t = threading.Timer(delay, _fire, args=(timer["id"],))
    t.daemon = True
    t.start()
    _scheduled[timer["id"]] = t


def _next_id(timers: list) -> int:
    if not timers:
        return 1
    return max(t["id"] for t in timers) + 1


def add(text: str, fire_at: float) -> dict:
    """Добавляет напоминание. Возвращает dict таймера."""
    with _lock:
        timers = _load()
        tid = _next_id(timers)
        timer = {
            "id": tid,
            "text": text.strip(),
            "fire_at": float(fire_at),
            "created_at": time.time(),
        }
        timers.append(timer)
        _save(timers)
    _schedule_one(timer)
    return timer


def remove_all() -> int:
    """Отменяет все напоминания. Возвращает количество."""
    with _lock:
        timers = _load()
        count = len(timers)
        for t in _scheduled.values():
            t.cancel()
        _scheduled.clear()
        _save([])
    return count


def list_all() -> list:
    """Возвращает список активных напоминаний."""
    return _load()


def format_list(timers: list) -> str:
    """Человекочитаемый список для озвучки."""
    if not timers:
        return "Напоминаний нет."
    now = time.time()
    parts = []
    for t in timers[:10]:
        left = int(t["fire_at"] - now)
        if left < 0:
            left = 0
        m, s = divmod(left, 60)
        h, m = divmod(m, 60)
        if h:
            when = f"через {h} ч {m} мин"
        elif m:
            when = f"через {m} мин"
        else:
            when = f"через {s} сек"
        text = t.get("text") or "без текста"
        parts.append(f"{when} — {text}")
    return "Напоминания: " + "; ".join(parts) + "."


def restore_all() -> int:
    """Восстанавливает таймеры при старте. Возвращает количество."""
    timers = _load()
    for t in timers:
        _schedule_one(t)
    if timers:
        log.info("Восстановлено напоминаний: %d", len(timers))
    return len(timers)


# ---------------------------------------------------------------
# Обработка команд
# ---------------------------------------------------------------

def handle_timer_command(cmd: str) -> str | None:
    """Разбирает команды таймеров. Возвращает ответ или None."""
    # список
    if re.search(r"(какие|список|покажи)\s*(напоминани|таймер)", cmd) \
            or cmd in {"какие напоминания", "список напоминаний", "мои напоминания"}:
        return format_list(list_all())

    # отмена
    if re.search(r"(отмени|удали|очисти|сбрось)\s*(все\s+)?(напоминани|таймер)", cmd) \
            or cmd in {"отмени все напоминания", "удали все напоминания"}:
        n = remove_all()
        return f"Отменено напоминаний: {n}." if n else "Напоминаний не было."

    # добавить напоминание
    if re.search(r"(напомни|напоминание|таймер|напоминай)", cmd):
        # абсолютное время
        abs_ts = _parse_absolute_time(cmd)
        if abs_ts:
            text = _extract_reminder_text(cmd)
            t = add(text, abs_ts)
            when = datetime.datetime.fromtimestamp(abs_ts).strftime("%H:%M")
            if text:
                return f"Напомню в {when}: {text}."
            return f"Напомню в {when}."

        # относительное время
        dur = _parse_duration(cmd)
        if dur and dur > 0:
            text = _extract_reminder_text(cmd)
            fire_at = time.time() + dur
            t = add(text, fire_at)
            # озвучка длительности
            if dur >= 3600:
                h = dur // 3600
                m = (dur % 3600) // 60
                when = f"через {h} ч {m} мин" if m else f"через {h} ч"
            elif dur >= 60:
                m = dur // 60
                when = f"через {m} мин"
            else:
                when = f"через {dur} сек"
            if text:
                return f"Хорошо, напомню {when}: {text}."
            return f"Хорошо, напомню {when}."

    return None