"""Заглушка движка TTS (factory._probe_engine).

Зачем: список голосов для GUI и список доступных движков ходят в
фабрику со служебным voice="" . Раньше это создавало НАСТОЯЩИЙ движок:
Piper тянул модель с HF Hub (~3 с), Silero грузил torch. Открытие
вкладки «Главная» и смена backend'а в GUI ждали эти секунды.
Теперь должен вернуться лёгкий объект с голосами.

Тесты без тяжёлых зависимостей — идут и в CI.
"""

import pytest

from jarvis.tts_engines import factory


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch):
    """Свой кэш заглушек на каждый тест — чтобы не было протечек."""
    monkeypatch.setattr(factory, "_PROBE_CACHE", {})


def test_probe_has_voices():
    probe = factory._try_create("piper", "", "medium", 1.15)
    assert probe is not None
    assert "ruslan" in probe.voices
    assert "irina" in probe.voices


def test_probe_is_not_real_engine():
    from jarvis.tts_engines.piper import PiperEngine

    probe = factory._try_create("piper", "", "medium", 1.15)
    assert not isinstance(probe, PiperEngine)


def test_probe_unknown_backend_is_none():
    assert factory._try_create("не_движок", "", "medium", 1.15) is None


def test_probe_none_without_dependency(monkeypatch):
    monkeypatch.setattr(factory, "_dependency_present", lambda name: False)
    assert factory._probe_engine("piper") is None


def test_probe_dependency_check_is_used(monkeypatch):
    """Заглушка не появляется, если нужного пакета нет."""
    seen = []

    def _fake_present(name):
        seen.append(name)
        return False

    monkeypatch.setattr(factory, "_dependency_present", _fake_present)
    factory._probe_engine("silero")
    assert seen == ["torch"]


def test_probe_result_is_cached(monkeypatch):
    calls = []
    real_import = factory.importlib.import_module

    def _counting_import(name):
        calls.append(name)
        return real_import(name)

    monkeypatch.setattr(factory.importlib, "import_module", _counting_import)
    factory._probe_engine("piper")
    factory._probe_engine("piper")
    assert calls.count("jarvis.tts_engines.piper") == 1


def test_real_voice_does_not_use_probe(monkeypatch):
    """С непустым голосом заглушка не подставляется — нужен реальный синтез."""
    probes = []
    monkeypatch.setattr(factory, "_probe_engine",
                        lambda name: probes.append(name) or None)
    monkeypatch.setattr(factory, "_ENGINE_CACHE", {})

    factory._try_create("не_движок", "ruslan", "medium", 1.15)

    assert probes == []


def test_list_engines_matches_probes():
    engines = factory.list_engines()
    expected = [name for name in ("silero", "piper", "winrt", "sapi")
                if factory._probe_engine(name) is not None]
    assert engines == expected
