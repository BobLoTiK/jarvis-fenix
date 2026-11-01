"""Яркость: опрос DDC/CI не должен подвешивать голосовой ответ.

На внешнем мониторе без DDC/CI `screen_brightness_control.get_brightness()`
висит секундами (замер: 7 с на BenQ GW2270), и пользователь всё это время
ждёт «Не смог узнать». Опрос ограничен BRIGHTNESS_TIMEOUT.
"""
import sys
import time
import types

import pytest

from jarvis import actions


@pytest.fixture
def caps(monkeypatch):
    monkeypatch.setattr(actions, "_CAPS", {"brightness": {"available": True, "method": "ddc"}})


def _fake_sbc(monkeypatch, behaviour):
    module = types.ModuleType("screen_brightness_control")
    module.get_brightness = behaviour
    monkeypatch.setitem(sys.modules, "screen_brightness_control", module)


def test_brightness_returns_percent(caps, monkeypatch):
    _fake_sbc(monkeypatch, lambda: [57])
    assert actions.get_brightness() == 57


def test_silent_monitor_does_not_block(caps, monkeypatch):
    def slow():
        time.sleep(5)
        return [40]

    _fake_sbc(monkeypatch, slow)
    started = time.monotonic()
    assert actions.get_brightness() is None
    assert time.monotonic() - started < actions.BRIGHTNESS_TIMEOUT + 1.0


def test_probe_error_is_not_a_crash(caps, monkeypatch):
    def boom():
        raise OSError("DDC/CI не поддерживается")

    _fake_sbc(monkeypatch, boom)
    assert actions.get_brightness() is None


def test_unavailable_caps_skips_the_probe(monkeypatch):
    monkeypatch.setattr(actions, "_caps_available", lambda name: False)
    calls = []

    def behaviour():
        calls.append(1)
        return [50]

    _fake_sbc(monkeypatch, behaviour)
    assert actions.get_brightness() is None
    assert calls == []
