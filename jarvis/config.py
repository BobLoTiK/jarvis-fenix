"""Загрузка конфигурации и объект Config в памяти.

Раньше: каждый модуль читал config.json с диска.
Сейчас: Config живёт в памяти, читается один раз, изменения рассылаются подписчикам.

Запись — через config_manager (единый FileLock).

Совместимость: Config поддерживает config["key"] и config.get("key").
"""

import logging
import threading
from pathlib import Path
from typing import Any, Callable

from jarvis import config_manager

log = logging.getLogger("jarvis.config")

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "wake_words": ["феникс", "финикс", "феникса", "fenix", "phoenix",
                   "джарвис", "jarvis"],
    # Observer — фоновый анализ диалога через LLM: раз в ~30 сек история
    # уходит в Ollama, оттуда извлекаются факты о пользователе (имя,
    # город, привычки) и пишутся в profile.json.
    # По умолчанию ВЫКЛЮЧЕН: это сбор данных о пользователе, включать
    # только с его согласия. Чекбокс — вкладка «Настройки» →
    # «Приватность»; ход извлечения — в logs/observer.log.
    "observer_enabled": False,
    # TTS backend: "auto" | "piper" | "silero" | "winrt" | "sapi"
    # auto — Silero → Piper → WinRT → SAPI (первый доступный).
    # ВАЖНО: при смене backend голос тоже надо менять — они не пересекаются.
    "tts_backend": "auto",
    "tts_voice": "ruslan",
    "tts_voice_quality": "medium",
    "voice_rate": 1.15,
    "nonverbal_enabled": False,
    "nonverbal_cooldown_sec": 45.0,
    "nonverbal_gain_db": -15.0,
    "nonverbal_probability": 0.2,
    "sample_rate": 16000,
    "input_device": None,
    "mic_check_sec": 20,
    "mic_watchdog_enabled": True,
    "command_window_sec": 8,
    "dialog_window_sec": 20,
    "use_whisper": True,
    # Пороги принятия ASR; требуют калибровки на реальном микрофоне.
    "stt_min_word_confidence": 0.65,
    "stt_min_avg_logprob": -1.0,
    "stt_max_no_speech_prob": 0.6,
    "stt_max_compression_ratio": 2.4,
    # Правильная рабочая модель — как в config.example.json.
    # Раньше тут был "coriollon/..." — сломанная репа на HF.
    "whisper_model": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "whisper_device": "auto",
    "mode": "combo",
    "barge_enabled": True,

    # VAD (Silero ONNX, ~2.3 МБ). Отсекает тишину/шум ДО Vosk.
    # Wake-слово работает как раньше — VAD только фильтрует вход.
    # wake_word_required=false — VAD ловит речь, wake не нужен.
    "vad_enabled": True,
    "vad_threshold": 0.5,
    "vad_adaptive": True,
    "vad_debug": False,  # True → логировать каждый чанк VAD (для отладки)
    # Модель silero_vad.onnx в репозиторий не входит, поэтому Феникс
    # качает её сам (фоном, в PROGRAM_DIR/vad) — иначе VAD молча
    # выключался бы на чистой установке.
    "vad_auto_download": True,
    # «Хвост» тишины после речи, мс. Vosk завершает фразу по тишине:
    # если VAD вырежет её всю, Vosk не отдаст финальный текст и Феникс
    # ответит поздно или не ответит вовсе. 1500 мс = как без VAD.
    "vad_hangover_ms": 1500,
    "wake_word_required": True,

    # Prosody — эмоции из голоса (RMS + pitch + ZCR).
    # prosody_priority:
    #   "prosody"  — эмоция из голоса важнее текста (рекомендую)
    #   "text"     — только текст (как было)
    #   "both"     — оба применяются (prosody первым, текст может перебить)
    "prosody_enabled": True,
    "prosody_priority": "prosody",

    "use_llm": True,
    "llm_model": "qwen2.5:7b-instruct",
    "ollama_url": "http://127.0.0.1:11434",
    "prompt_level": "auto",
    "llm_temperature": 0.7,
    # Таймаут ответа Ollama. Захардкожен был 20 с в Brain.__init__ —
    # на 14b холодный parse() с num_predict=300 в него не всегда
    # укладывается, и команда молча падала в «Я не понял команду».
    "llm_timeout": 45.0,

    # Праздничные триггеры. По умолчанию ВЫКЛЮЧЕНО.
    # Пользователь сам пишет триггеры и текст в config.json.
    "celebration_enabled": False,
    "celebration_triggers": [],
    "celebration_short_text": "Поздравляю! С днём рождения!",
    "celebration_long_text": "Поздравляю с днём рождения! Здоровья, счастья и удачи!",
    "celebration_sound_1_plays": 2,
    "celebration_sound_2_plays": 3,
    "celebration_duration_1": 6.0,
    "celebration_duration_2": 10.0,

    "music_app": "яндекс музыка",
    "music_wait_sec": 6,
    "active_packs": [],
    "app_paths": {},
    "custom_commands": [],
    "timers_file": "timers.json",
    "tasks_file": "tasks.json",
    "memory_file": "dialog.json",
    "memory_max": 100,
    "llm_context_messages": 20,
    # Векторная память фактов (RAG). ВЫКЛЮЧЕНА по умолчанию — как Observer:
    # включается только галочкой «Настройки → Приватность». Подбирает факты
    # по смыслу запроса вместо «все факты всегда». Нужна модель эмбеддингов
    # в Ollama («ollama pull nomic-embed-text»); без неё всё работает как раньше.
    # Индекс: profiles/<профиль>/memory_index.json.
    "memory_rag_enabled": False,
    "memory_rag_model": "nomic-embed-text",
    "memory_rag_top_k": 3,
    # Порог косинуса. Замерено на живых nomic-embed-text (14.10.2026):
    # релевантный факт даёт 0.63–0.74, случайный — 0.58–0.63. Шкалы
    # ПЕРЕКРЫВАЮТСЯ, поэтому одного порога мало — нужен ещё отрыв лидера.
    "memory_rag_min_score": 0.6,
    # Отрыв лидера от второго места: меньше — считаем, что «явного
    # победителя нет», и отдаём в промпт все факты (как до фичи).
    # Так фича никогда не может стать хуже, чем было.
    "memory_rag_margin": 0.04,
    # У лексического поиска (без эмбеддингов) своя шкала: совпадение
    # по словам даёт ~0.43, шум — ниже 0.3.
    "memory_rag_lexical_min_score": 0.35,
    "memory_rag_timeout": 2.5,
    "memory_rag_max_items": 500,
    "memory_rag_lexical_fallback": True,
    "weather_cache_ttl_sec": 600,
    "danger_password": "",
    "gui_enabled": True,
    # Системная — валидное значение (в gui.py THEMES).
    # Раньше было "dark-blue" — такого ключа в THEMES нет.
    "gui_theme": "Системная",
    "gui_sidebar_pinned": False,
    # False disables sidebar motion even when the OS does not expose accessibility flags.
    "gui_motion_enabled": True,
    "gui_x": None,
    "gui_y": None,
    "tray_enabled": True,
    "launch_mode": "gui",
}


class Config:
    """Конфиг в памяти с подписками на изменения."""

    def __init__(self, path: Path | None = None):
        if path is None:
            from jarvis import paths as _paths
            path = _paths.config_path()
        self.path = path
        self._write_lock = threading.RLock()
        self._data: dict = {}
        self._listeners: list[Callable[[str, Any], None]] = []
        self.reload()

    def reload(self) -> None:
        """Перечитывает config.json с диска. Вызывается при старте."""
        raw = config_manager.load(path=self.path)
        if not self.path.exists():
            merged = dict(DEFAULT_CONFIG)
            config_manager.save(merged, path=self.path)
            log.info("Создан конфиг по умолчанию: %s", self.path)
        else:
            merged = dict(DEFAULT_CONFIG)
            merged.update(raw)
            log.info("Конфиг загружен: %d ключей из %s", len(merged), self.path.name)
        self._data = merged

    # --- чтение ----------------------------------------------------------

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all_data(self) -> dict:
        return dict(self._data)

    # --- запись ----------------------------------------------------------

    def set(self, key: str, value) -> bool:
        """Persist before publishing the value and notifying subscribers."""
        return self.update({key: value})

    def update(self, data: dict, *, expected_values: dict | None = None) -> bool:
        """One atomic write for a batch, with optional editor conflict detection.

        Concurrent set/update calls are serialized. Callbacks run outside the
        write lock; failed writes never publish temporary in-memory values.
        """
        with self._write_lock:
            if expected_values is not None and any(
                    self._data.get(k) != v for k, v in expected_values.items()):
                return False
            changed = {k: v for k, v in data.items() if self._data.get(k) != v}
            if not changed:
                return True
            updated = {**self._data, **changed}
            if not config_manager.save(updated, path=self.path):
                log.error("Config.update: save failed; previous values retained")
                return False
            self._data = updated
        for key, value in changed.items():
            for cb in list(self._listeners):
                try:
                    cb(key, value)
                except Exception:
                    log.exception("Подписчик Config упал на ключе %s", key)
        return True

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Регистрирует callback(key, value), вызываемый при set/update."""
        if callback in self._listeners:
            return
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Удаляет подписку."""
        try:
            self._listeners.remove(callback)
            log.info("Config: подписка удалена (%s)", callback)
        except ValueError:
            log.debug("Config: подписки %s не было", callback)

    # --- совместимость с dict --------------------------------------------

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"Config({len(self._data)} keys)"


_GLOBAL: Config | None = None


def load_config(base_dir: Path | None = None) -> Config:
    """Создаёт глобальный Config.

    base_dir — оставлен для совместимости, но config.json
    теперь ВСЕГДА в USER_DIR (%APPDATA%\\Phoenix).
    """
    global _GLOBAL
    if _GLOBAL is None:
        from jarvis import paths
        _GLOBAL = Config(paths.config_path())
    return _GLOBAL


def get_global() -> Config:
    if _GLOBAL is None:
        raise RuntimeError("Config не создан. Вызови load_config() при старте.")
    return _GLOBAL