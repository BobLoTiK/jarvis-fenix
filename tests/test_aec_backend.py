"""Выбор backend'а AEC: native по умолчанию, честный отказ от webrtc."""
from jarvis.aec_backend import BACKENDS, BackendChoice, resolve


class FakeConfig:
    def __init__(self, **data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)


def config_with(**data):
    return FakeConfig(**data)


def test_native_is_the_default():
    choice = resolve(config_with())
    assert choice.name == "native" and choice.fallback is False
    assert "RenderTap" in choice.reason


def test_unknown_backend_falls_back_to_native_with_reason():
    choice = resolve(config_with(aec_backend="какой-то"))
    assert choice.name == "native" and choice.requested == "native"
    assert "неизвестный" in choice.reason
    assert resolve(config_with(aec_backend=None)).name == "native"


def test_webrtc_requested_but_package_missing_stays_native():
    def importer(name):
        raise ImportError(name)

    choice = resolve(config_with(aec_backend="webrtc"), importer=importer)
    assert choice.name == "native" and choice.requested == "webrtc"
    assert choice.fallback is True
    assert "не установлен" in choice.reason


def test_webrtc_used_only_when_package_really_imports():
    seen = []

    def importer(name):
        seen.append(name)
        if name != "pywebrtc_audio":
            raise ImportError(name)
        return object()

    choice = resolve(config_with(aec_backend="webrtc"), importer=importer)
    assert choice.name == "webrtc" and choice.fallback is False
    assert "pywebrtc_audio" in choice.reason
    assert seen == ["webrtc_audio_processing", "pywebrtc_audio"]


def test_backend_names_are_stable():
    assert BACKENDS == ("native", "webrtc")
    assert BackendChoice("native", "webrtc", "").fallback is True
