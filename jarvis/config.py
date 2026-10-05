"""Загрузка конфигурации и объект Config в памяти.

Раньше: каждый модуль читал config.json с диска.
Сейчас: Config живёт в памяти, читается один раз, изменения рассылаются подписчикам.

Запись — через config_manager (единый FileLock).

Совместимость: Config поддерживает config["key"] и config.get("key"),
поэтому старый код, который работал с dict, продолжит работать.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from jarvis import config_manager

log = logging.getLogger("jarvis.config")

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = {
    "wake_words": ["феникс", "финикс", "феникса", "fenix", "phoenix",
                   "джарвис", "jarvis"],
    "tts_backend": "auto",
    "xtts_ref": "voices/jarvis.wav",
    "tts_voice": "ruslan",
    "voice_rate": 1.15,
    "voice": "Pavel",
    "sample_rate": 16000,
    "input_device": None,
    "mic_check_sec": 20,
    "command_window_sec": 8,
    "dialog_window_sec": 20,
    "use_whisper": True,
    "whisper_model": "auto",
    "whisper_device": "auto",
    "mode": "combo",
    "barge_enabled": True,
    "use_llm": True,
    "llm_model": "qwen2.5:7b-instruct",
    "ollama_url": "http://127.0.0.1:11434",
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
    "danger_password": "",
    "gui_enabled": True,
    "gui_theme": "dark-blue",
    "gui_x": None,
    "gui_y": None,
    "tray_enabled": True,
}


class Config:
    """Конфиг в памяти с подписками на изменения."""

    def __init__(self, path: Path | None = None):
        self.path = path or (BASE_DIR / "config.json")
        self._data: dict = {}
        self._listeners: list[Callable[[str, Any], None]] = []
        self.reload()

    def reload(self) -> None:
        """Перечитывает config.json с диска. Вызывается при старте.

        Если файла нет — создаёт с DEFAULT_CONFIG.
        """
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
        """Ставит значение, сохраняет на диск, оповещает подписчиков."""
        if self._data.get(key) == value:
            return True
        self._data[key] = value
        ok = config_manager.save(self._data, path=self.path)
        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                log.exception("Подписчик Config упал на ключе %s", key)
        return ok

    def update(self, data: dict) -> bool:
        """Массовое обновление. Оповещает по каждому ключу."""
        changed = {k: v for k, v in data.items() if self._data.get(k) != v}
        if not changed:
            return True
        self._data.update(changed)
        ok = config_manager.save(self._data, path=self.path)
        for key, value in changed.items():
            for cb in list(self._listeners):
                try:
                    cb(key, value)
                except Exception:
                    log.exception("Подписчик Config упал на ключе %s", key)
        return ok

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Регистрирует callback(key, value), вызываемый при set/update."""
        self._listeners.append(callback)

    # --- совместимость с dict --------------------------------------------

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        return f"Config({len(self._data)} keys)"


# --- Совместимость со старым API -----------------------------------------

_GLOBAL: Config | None = None


def load_config(base_dir: Path | None = None) -> Config:
    """Создаёт глобальный Config. Старый API сохранён, но возвращает Config,
    а не dict. Код, использующий config["x"] или config.get("x"), продолжит
    работать, потому что Config поддерживает __getitem__ и .get().
    """
    global _GLOBAL
    if _GLOBAL is None:
        path = (base_dir / "config.json") if base_dir else None
        _GLOBAL = Config(path)
    return _GLOBAL


def get_global() -> Config:
    if _GLOBAL is None:
        raise RuntimeError("Config не создан. Вызови load_config() при старте.")
    return _GLOBAL