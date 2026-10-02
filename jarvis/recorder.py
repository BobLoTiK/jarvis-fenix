"""Запись действий: клавиши, клики, паузы."""

import logging
import threading
import time

log = logging.getLogger("jarvis.recorder")

_recording = False
_events = []
_start_time = 0.0
_last_event_time = 0.0
_lock = threading.Lock()

MAX_DURATION_SEC = 60
MIN_WAIT_SEC = 0.05
MAX_WAIT_SEC = 5.0


def is_recording() -> bool:
    return _recording


def start() -> bool:
    global _recording, _events, _start_time, _last_event_time
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены. pip install keyboard mouse")
        return False

    with _lock:
        if _recording:
            return False
        _events = []
        _recording = True
        _start_time = time.time()
        _last_event_time = _start_time

    try:
        keyboard.hook(_on_key)
        mouse.hook(_on_mouse)
    except Exception:
        log.exception("Не удалось повесить хуки (нужны права администратора)")
        with _lock:
            _recording = False
        return False

    log.info("Запись действий начата")
    return True


def stop() -> dict | None:
    global _recording
    try:
        import keyboard
        import mouse
        keyboard.unhook_all()
        mouse.unhook_all()
    except Exception:
        pass

    with _lock:
        if not _recording:
            return None
        _recording = False
        events = list(_events)

    log.info("Запись действий остановлена: %d событий", len(events))
    return {"events": events, "duration": time.time() - _start_time}


def _add_wait_if_needed():
    global _last_event_time
    now = time.time()
    delta = now - _last_event_time
    if delta >= MIN_WAIT_SEC:
        _events.append({"type": "wait", "seconds": min(delta, MAX_WAIT_SEC)})
    _last_event_time = now


def _check_limits() -> bool:
    if time.time() - _start_time > MAX_DURATION_SEC:
        log.info("Запись остановлена: превышена максимальная длина")
        return False
    return True


def _on_key(event):
    if not _recording or not _check_limits():
        return
    _add_wait_if_needed()
    _events.append({
        "type": "key",
        "name": event.name,
        "event": "down" if event.event_type == "down" else "up",
    })


def _on_mouse(event):
    if not _recording or not _check_limits():
        return
    import mouse
    if isinstance(event, mouse.ButtonEvent):
        _add_wait_if_needed()
        _events.append({
            "type": "click",
            "x": mouse.get_position()[0],
            "y": mouse.get_position()[1],
            "button": event.button,
            "event": "down" if event.event_type == "down" else "up",
        })


def play(macro: dict, speed: float = 1.0) -> bool:
    if not macro or not macro.get("events"):
        return False
    try:
        import keyboard
        import mouse
    except ImportError:
        log.error("Библиотеки keyboard/mouse не установлены")
        return False

    events = macro["events"]
    log.info("Воспроизведение макроса: %d событий", len(events))
    try:
        for ev in events:
            t = ev.get("type")
            if t == "wait":
                time.sleep(float(ev.get("seconds", 0)) / max(speed, 0.1))
            elif t == "key":
                if ev.get("event") == "down":
                    keyboard.press(ev["name"])
                else:
                    keyboard.release(ev["name"])
            elif t == "click":
                mouse.move(ev["x"], ev["y"], absolute=True, duration=0)
                if ev.get("event") == "down":
                    mouse.press(button=ev.get("button", "left"))
                else:
                    mouse.release(button=ev.get("button", "left"))
        return True
    except Exception:
        log.exception("Ошибка воспроизведения макроса")
        return False


def describe(macro: dict) -> str:
    if not macro:
        return "Запись пустая."
    events = macro.get("events", [])
    keys = sum(1 for e in events if e.get("type") == "key" and e.get("event") == "down")
    clicks = sum(1 for e in events if e.get("type") == "click" and e.get("event") == "down")
    duration = macro.get("duration", 0)
    return f"Макрос: {keys} нажатий, {clicks} кликов, длительность {duration:.1f} секунд."