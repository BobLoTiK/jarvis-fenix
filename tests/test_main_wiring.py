"""config → живое ядро: подписчик make_config_listener.

Раньше этот код жил внутри main() и проверялся только руками — из-за
этого смена настроек из GUI частично не доходила до работающих
компонентов. Теперь это отдельная функция, и здесь видно, что каждый
ключ доходит до своего метода:

    vad_threshold / vad_adaptive / vad_hangover_ms → listener.reload_vad()
    vad_enabled                                   → listener.set_vad_enabled()
    input_device                                  → listener.set_input_device()
    wake_word_required                            → jarvis._wake_word_required
    barge_enabled                                 → jarvis + listener
    tts_backend                                   → speaker.switch_backend()
    tts_voice                                     → speaker.set_voice()
    voice_rate                                    → speaker.set_rate()
    mode                                          → handler.mode
    memory_rag_enabled / memory_rag_model         → vectormem.on_config_change()

Компоненты — заглушки: микрофон не открывается, модели не грузятся.
"""

import importlib.util

import pytest

missing = [m for m in ("vosk", "sounddevice", "flet")
           if importlib.util.find_spec(m) is None]
if missing:
    pytest.skip(f"нет {', '.join(missing)} — тест пропущен",
                allow_module_level=True)

from jarvis import vectormem  # noqa: E402
from jarvis.main import make_config_listener  # noqa: E402


class Spy:
    """Заглушка компонента: помнит, какие методы и с чем вызывали."""

    def __init__(self, name="spy"):
        self.name = name
        self.calls = []

    def __getattr__(self, item):
        def _rec(*args, **kwargs):
            self.calls.append((item, args))
            return None

        return _rec

    def called(self, method):
        return [args for name, args in self.calls if name == method]


class FakeJarvis:
    def __init__(self):
        self.barge_enabled = True
        self._wake_word_required = True


@pytest.fixture()
def wiring():
    """Собирает подписчик + заглушки и отдаёт их одним кортежем."""
    jarvis = FakeJarvis()
    listener = Spy("listener")
    speaker = Spy("speaker")
    handler = Spy("handler")
    callback = make_config_listener(jarvis, None, listener, speaker, handler)
    return jarvis, listener, speaker, handler, callback


# =================================================================
# VAD — живое применение
# =================================================================

def test_vad_threshold_reloads_vad(wiring):
    _, listener, _, _, callback = wiring
    callback("vad_threshold", 0.2)
    assert listener.called("reload_vad") == [()]


def test_vad_adaptive_reloads_vad(wiring):
    _, listener, _, _, callback = wiring
    callback("vad_adaptive", False)
    assert listener.called("reload_vad") == [()]


def test_vad_hangover_reloads_vad(wiring):
    _, listener, _, _, callback = wiring
    callback("vad_hangover_ms", 500)
    assert listener.called("reload_vad") == [()]


def test_vad_auto_download_reloads_vad(wiring):
    """Чекбокс «качать модель VAD» пересоздаёт VAD (модель читается там)."""
    _, listener, _, _, callback = wiring
    callback("vad_auto_download", False)
    assert listener.called("reload_vad") == [()]


def test_vad_enabled_toggles_vad(wiring):
    _, listener, _, _, callback = wiring
    callback("vad_enabled", False)
    assert listener.called("set_vad_enabled") == [(False,)]


# =================================================================
# Трей (иконку поднимает/снимает main._apply_tray)
# =================================================================

def test_tray_enabled_calls_apply_tray():
    """Чекбокс «Иконка в трее» дёргает подъём/снятие иконки."""
    calls = []
    callback = make_config_listener(FakeJarvis(), None, Spy(), Spy(), Spy(),
                                    apply_tray=calls.append)

    callback("tray_enabled", True)
    callback("tray_enabled", False)

    assert calls == [True, False]


def test_tray_enabled_without_handler_is_safe(wiring):
    """Без apply_tray ключ просто игнорируется (тесты, headless-режим)."""
    *_, callback = wiring
    callback("tray_enabled", True)


def test_input_device_switches_microphone(wiring):
    _, listener, _, _, callback = wiring
    callback("input_device", "USB Headset")
    assert listener.called("set_input_device") == [("USB Headset",)]


# =================================================================
# Остальные ключи
# =================================================================

def test_wake_word_required_flag(wiring):
    jarvis, _, _, _, callback = wiring
    callback("wake_word_required", False)
    assert jarvis._wake_word_required is False


def test_barge_enabled_both_sides(wiring):
    jarvis, listener, _, _, callback = wiring
    callback("barge_enabled", False)
    assert jarvis.barge_enabled is False
    assert listener.barge_enabled is False


def test_tts_backend_switches_speaker(wiring):
    _, _, speaker, _, callback = wiring
    callback("tts_backend", "piper")
    assert speaker.called("switch_backend") == [("piper",)]


def test_tts_voice_and_rate(wiring):
    _, _, speaker, _, callback = wiring
    callback("tts_voice", "irina")
    callback("voice_rate", 1.5)
    assert speaker.called("set_voice") == [("irina",)]
    assert speaker.called("set_rate") == [(1.5,)]


def test_mode_goes_to_handler(wiring):
    _, _, _, handler, callback = wiring
    callback("mode", "llm")
    assert handler.mode == "llm"


def test_unknown_key_is_ignored(wiring):
    _, listener, speaker, _, callback = wiring
    callback("совсем_не_тот_ключ", 1)
    assert listener.calls == []
    assert speaker.calls == []


def test_memory_rag_reaches_vectormem(wiring, monkeypatch):
    """Галочка векторной памяти применяется сразу, без перезапуска."""
    _, _, _, _, callback = wiring
    seen = []
    monkeypatch.setattr(vectormem, "on_config_change",
                        lambda key, value: seen.append((key, value)))

    callback("memory_rag_enabled", True)
    callback("memory_rag_model", "bge-m3")

    assert seen == [("memory_rag_enabled", True), ("memory_rag_model", "bge-m3")]


def test_missing_listener_is_safe(wiring):
    """listener=None (GUI без микрофона) — подписчик не падает."""
    jarvis, _, speaker, handler, _ = wiring
    callback = make_config_listener(jarvis, None, None, speaker, handler)

    callback("vad_enabled", False)
    callback("vad_threshold", 0.3)
    callback("vad_hangover_ms", 1000)
    callback("input_device", "нет такого")
    callback("barge_enabled", False)

    assert jarvis.barge_enabled is False
