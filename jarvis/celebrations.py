"""Праздничные триггеры — поздравление с ДР + двойной салют.

Триггеры и текст ПОЗДРАВЛЕНИЯ настраиваются в config.json:

    "celebration_enabled": false,
    "celebration_triggers": ["я папа", "я александр"],
    "celebration_short_text": "Поздравляю! С днём рождения!",
    "celebration_long_text": "Дорогой Папа! Поздравляю тебя...",
    "celebration_sound_1_plays": 2,
    "celebration_sound_2_plays": 3,
    "celebration_duration_1": 6.0,
    "celebration_duration_2": 10.0,

По умолчанию — ВЫКЛЮЧЕНО. Пользователь сам включает и пишет свои
триггеры. Иначе получается «поздравь моего батю Александра» на
чужой машине.

Если enabled=false или triggers пустой — функция не срабатывает.
"""

import logging
import threading
import time
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.celebrations")


# Значения по умолчанию (если config не передан).
DEFAULTS = {
    "enabled": False,
    "triggers": [],
    "short_text": "Поздравляю! С днём рождения!",
    "long_text": "Поздравляю с днём рождения! Здоровья, счастья и удачи!",
    "sound_1_plays": 2,
    "sound_2_plays": 3,
    "duration_1": 6.0,
    "duration_2": 10.0,
}


def _get_config():
    """Возвращает текущий Config или None."""
    try:
        from jarvis.config import get_global
        return get_global()
    except Exception:
        return None


def _cfg(key: str, default):
    """Читает значение из config.json → celebration_*."""
    cfg = _get_config()
    if cfg is None:
        return DEFAULTS.get(key, default)
    return cfg.get(f"celebration_{key}", DEFAULTS.get(key, default))


def match_celebration(cmd: str) -> bool:
    """Проверяет, триггер ли это.

    Возвращает False, если:
        - celebration_enabled = false
        - celebration_triggers пустой
        - ни один триггер не найден в cmd
    """
    if not _cfg("enabled", False):
        return False

    triggers = _cfg("triggers", []) or []
    if not triggers:
        return False

    cmd_low = cmd.lower().strip()
    for trigger in triggers:
        trigger_low = str(trigger).lower().strip()
        if trigger_low and trigger_low in cmd_low:
            log.info("Праздничный триггер: %r (найден %r)", cmd, trigger)
            return True
    return False


def start_celebration(jarvis, gui) -> None:
    """Запускает праздничную цепочку в отдельном потоке.

    jarvis — объект Jarvis (для say).
    gui    — объект FenixGUI (для анимации). Может быть None.
    """
    from jarvis.reply import Reply

    short_text = _cfg("short_text", DEFAULTS["short_text"])
    long_text = _cfg("long_text", DEFAULTS["long_text"])
    plays_1 = int(_cfg("sound_1_plays", DEFAULTS["sound_1_plays"]))
    plays_2 = int(_cfg("sound_2_plays", DEFAULTS["sound_2_plays"]))
    dur_1 = float(_cfg("duration_1", DEFAULTS["duration_1"]))
    dur_2 = float(_cfg("duration_2", DEFAULTS["duration_2"]))

    def _run():
        try:
            # === АКТ 1: короткая фраза + салют ===
            log.info("Celebration: TTS #1 (короткая)")
            jarvis.say(Reply(text=short_text))

            log.info("Celebration: анимация #1 (%.1f сек)", dur_1)
            if gui is not None:
                gui.launch_fireworks(duration=dur_1)

            _play_sound_series(plays_1, max(1.0, dur_1 / max(plays_1, 1)))

            # === АКТ 2: полное поздравление ===
            log.info("Celebration: TTS #2 (длинная)")
            jarvis.say(Reply(text=long_text))

            # === АКТ 3: финальный салют ===
            log.info("Celebration: анимация #2 (финал, %.1f сек)", dur_2)
            if gui is not None:
                gui.launch_fireworks(duration=dur_2)

            _play_sound_series(plays_2, max(1.0, dur_2 / max(plays_2, 1)))

            log.info("Celebration: завершено")
        except Exception:
            log.exception("Celebration: ошибка")

    threading.Thread(target=_run, daemon=True, name="celebration").start()


def _play_sound_series(plays: int, gap_sec: float) -> None:
    """Играет звук салюта N раз с паузой gap_sec."""
    for i in range(max(1, plays)):
        log.info("Celebration: звук %d/%d", i + 1, plays)
        _play_fireworks_sound()
        time.sleep(gap_sec)
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


def _play_fireworks_sound() -> None:
    """Играет fireworks.wav, если есть. Иначе — Beep-и."""
    sound_path = Path(__file__).parent / "sounds" / "fireworks.wav"

    if sound_path.exists():
        try:
            winsound.PlaySound(
                str(sound_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC,
            )
            log.info("Celebration: звук из %s", sound_path.name)
            return
        except Exception:
            log.exception("Celebration: не удалось воспроизвести .wav")

    # Fallback — серия Beep-ов, имитирующих залпы.
    log.info("Celebration: fallback — Beep-и")
    try:
        for _ in range(8):
            winsound.Beep(1200, 80)
            winsound.Beep(900, 60)
            winsound.Beep(1500, 100)
            time.sleep(0.15)
    except Exception:
        log.exception("Celebration: Beep не сработал")