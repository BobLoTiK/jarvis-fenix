"""Праздничные триггеры — поздравление с ДР + двойной салют.

Единоразово: батя говорит «я папа» / «я Александр» —
Феникс запускает праздничную цепочку:

    1. TTS: «Поздравляю! С днём рождения!»
    2. Анимация #1 + звук ×2 (короткая, ~6 сек).
    3. TTS: полное поздравление.
    4. Анимация #2 + звук ×3 (длинная, ~10 сек).
"""

import logging
import threading
import time
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.celebrations")

# Триггеры: пользователь называет себя.
TRIGGERS = (
    "я папа",
    "я александр",
    "я саша",
    "я отец",
    "я батя",
    "александр",
)

SHORT_TEXT = "Поздравляю! С днём рождения!"

# ⚠️ Текст поздравления — НЕ МЕНЯТЬ (авторский)
LONG_TEXT = (
    "Дорогой Папа! Поздравляю тебя с днём рождения! "
    "Желаю крепкого здоровья, счастья, удачи и всего самого афигенского. "
    "Пусть каждый день приносит радость, а все мечты сбываются. "
    "Спасибо, что ты рядом. Ты — самый лучший папа на свете! С днем рождения!!!"
)

# Первая серия (перед поздравлением) — короткая
SOUND_PLAYS_1 = 2
SOUND_DURATION_SEC_1 = 3.0

# Вторая серия (после поздравления) — длинная
SOUND_PLAYS_2 = 3
SOUND_DURATION_SEC_2 = 3.5


def match_celebration(cmd: str) -> bool:
    """Проверяет, триггер ли это."""
    cmd_low = cmd.lower().strip()
    for trigger in TRIGGERS:
        if trigger in cmd_low:
            log.info("Праздничный триггер: %r", cmd)
            return True
    return False


def start_celebration(jarvis, gui) -> None:
    """Запускает праздничную цепочку в отдельном потоке.

    jarvis — объект Jarvis (для say).
    gui    — объект FenixGUI (для анимации). Может быть None.
    """
    from jarvis.reply import Reply

    def _run():
        try:
            # === АКТ 1: короткая фраза + салют ===
            log.info("Celebration: TTS #1 (короткая)")
            jarvis.say(Reply(text=SHORT_TEXT))

            log.info("Celebration: анимация #1")
            if gui is not None:
                gui.launch_fireworks(duration=6.0)

            _play_sound_series(SOUND_PLAYS_1, SOUND_DURATION_SEC_1)

            # === АКТ 2: полное поздравление ===
            log.info("Celebration: TTS #2 (длинная)")
            jarvis.say(Reply(text=LONG_TEXT))

            # === АКТ 3: финальный салют, подольше ===
            log.info("Celebration: анимация #2 (финал)")
            if gui is not None:
                gui.launch_fireworks(duration=10.0)

            _play_sound_series(SOUND_PLAYS_2, SOUND_DURATION_SEC_2)

            log.info("Celebration: завершено")
        except Exception:
            log.exception("Celebration: ошибка")

    threading.Thread(target=_run, daemon=True, name="celebration").start()


def _play_sound_series(plays: int, duration_sec: float) -> None:
    """Играет звук салюта N раз по duration_sec секунд."""
    for i in range(plays):
        log.info("Celebration: звук %d/%d", i + 1, plays)
        _play_fireworks_sound()
        time.sleep(duration_sec)
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

    # Fallback — серия Beep-ов, имитирующих залпы
    log.info("Celebration: fallback — Beep-и")
    try:
        for _ in range(8):
            winsound.Beep(1200, 80)
            winsound.Beep(900, 60)
            winsound.Beep(1500, 100)
            time.sleep(0.15)
    except Exception:
        log.exception("Celebration: Beep не сработал")