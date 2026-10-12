"""Замер старта Феникса по этапам — что именно тормозит запуск.

Зачем:
    На старте Феникс грузит модель Vosk, модель Whisper
    (large-v3-turbo), TTS-движок и прогревает WMI-яркость. Когда
    «запускается долго», надо видеть цифры по каждому этапу, а не
    угадывать. Скрипт повторяет порядок main() БЕЗ GUI и без открытия
    микрофона.

Запуск:
    python scripts/startup_probe.py
    python scripts/startup_probe.py --no-tts
    python scripts/startup_probe.py --no-mic
    python scripts/startup_probe.py --with-brain
    python scripts/startup_probe.py --whisper-wait 30

Как читать:
    Строка «Whisper: фоновая загрузка» — это время, которое БОЛЬШЕ НЕ
    блокирует показ окна: модель грузится в фоне (lazy=True в main.py).
    Остальные этапы — то, что реально ждёт пользователь до появления GUI.
"""

import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# Русский текст в консоли Windows (cp1251/cp866) — иначе UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RESULTS: list[tuple[str, float, str]] = []


def measure(label: str, func, note: str = ""):
    """Замеряет один этап. Ошибку не роняем — пишем в таблицу."""
    t0 = time.perf_counter()
    try:
        value = func()
    except Exception as exc:  # noqa: BLE001 — скрипт диагностический
        RESULTS.append((label, time.perf_counter() - t0,
                        f"ОШИБКА {type(exc).__name__}: {exc}"))
        return None
    RESULTS.append((label, time.perf_counter() - t0, note or "ok"))
    return value


def print_table() -> float:
    width = max(len(label) for label, _, _ in RESULTS)
    print()
    print(f"{'этап':<{width}}  {'сек':>7}  статус")
    print("-" * (width + 34))
    for label, secs, status in RESULTS:
        print(f"{label:<{width}}  {secs:>7.2f}  {status}")
    print("-" * (width + 34))
    total = sum(secs for _, secs, _ in RESULTS)
    print(f"{'ИТОГО (сумма этапов)':<{width}}  {total:>7.2f}")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер старта Феникса")
    parser.add_argument("--no-whisper", action="store_true",
                        help="не создавать WhisperTranscriber")
    parser.add_argument("--no-tts", action="store_true",
                        help="не создавать Speaker")
    parser.add_argument("--no-mic", action="store_true",
                        help="не создавать Listener (Vosk)")
    parser.add_argument("--with-brain", action="store_true",
                        help="создать Brain (пинг Ollama)")
    parser.add_argument("--bg-wait", type=float, default=60.0,
                        help="сколько ждать фоновую загрузку моделей, сек")
    args = parser.parse_args()

    # 1. Импорт главного модуля: тянет flet, vosk, sounddevice, gui.
    measure("import jarvis.main (flet/vosk/gui)",
            lambda: __import__("jarvis.main", fromlist=["main"]))

    from jarvis import APP_NAME, __version__
    from jarvis.actions import get_brightness
    from jarvis.apps import build_apps
    from jarvis.config import load_config
    from jarvis.intents import IntentHandler
    from jarvis.model import ensure_model
    from jarvis.stt import Listener
    from jarvis.tts import Speaker

    config = measure("load_config", lambda: load_config(BASE))
    if config is None:
        print_table()
        return 1

    print(f"{APP_NAME} v{__version__}: tts_backend="
          f"{config.get('tts_backend')!r}, use_whisper={config.get('use_whisper')}, "
          f"vad_enabled={config.get('vad_enabled')}")

    profile_mod = __import__("jarvis.profile", fromlist=["init"])
    measure("profile.init()", profile_mod.init)
    weather = __import__("jarvis.weather", fromlist=["set_config"])
    measure("weather.set_config()", lambda: weather.set_config(config))

    local_models = BASE / "models"
    if not local_models.exists():
        local_models = None
    model_dir = measure("ensure_model (Vosk-модель)",
                        lambda: ensure_model(local_models))

    whisper = None
    if not args.no_whisper and config.get("use_whisper", True):
        from jarvis.stt import WhisperTranscriber

        def _create_whisper():
            nonlocal whisper
            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"),
                config.get("whisper_device", "auto"),
                lazy=True,
            )
            whisper.preload_async()
            return whisper

        measure("Whisper: создание (lazy=True)", _create_whisper)
        if whisper is not None:
            measure(
                "Whisper: фоновая загрузка (фон)",
                lambda: whisper.wait_ready(args.bg_wait),
                note="фон — показ окна НЕ ждёт",
            )

    brain = None
    if args.with_brain and config.get("use_llm", True):
        from jarvis.brain import Brain

        def _create_brain():
            nonlocal brain
            brain = Brain(
                config.get("llm_model", "qwen2.5:7b-instruct"),
                config.get("ollama_url", "http://127.0.0.1:11434"),
                prompt_level=config.get("prompt_level", "auto"),
                temperature=config.get("llm_temperature", 0.7),
                config=config,
            )
            return brain

        measure("Brain (Ollama ping)", _create_brain)

    speaker = None
    if not args.no_tts:
        def _create_speaker():
            nonlocal speaker
            speaker = Speaker(config, lazy=True)
            return speaker

        measure("Speaker: создание (lazy=True)", _create_speaker)
        if speaker is not None:
            measure(
                "Speaker: фоновая загрузка движка (фон)",
                lambda: speaker._ensure_engine(args.bg_wait),
                note="фон — показ окна НЕ ждёт",
            )

    listener = None
    if not args.no_mic and model_dir is not None:
        def _create_listener():
            nonlocal listener
            listener = Listener(
                model_dir,
                config["sample_rate"],
                config.get("input_device"),
                config=config,
            )
            return listener

        measure("Listener (Vosk + VAD)", _create_listener)

    measure("actions.get_brightness() (прогрев WMI)", get_brightness)

    def _create_handler():
        return IntentHandler(config, build_apps(config), brain,
                             listener=listener, gui=None)

    measure("IntentHandler + build_apps", _create_handler)

    print_table()
    print()
    print("Подсказка: строки «фон» в блокировку старта не входят — "
          "окно Flet показывается сразу, модель догружается параллельно.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
