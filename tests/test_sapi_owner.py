"""COM ownership and cooperative cancellation without Windows/audio hardware."""
import sys
import threading
from types import SimpleNamespace as NS

from jarvis.tts_engines import sapi


class Native:
    def __init__(self):
        self.calls = []
        self.started = threading.Event()
        self.busy = False
        self.loop = False

    def record(self, name):
        self.calls.append((name, threading.get_ident()))

    def getProperty(self, key):
        self.record("getProperty")
        return [NS(id="Russian", name="Microsoft Irina")]

    def setProperty(self, key, value):
        self.record("setProperty")

    def say(self, text):
        self.record("say")
        self.busy = True
        self.started.set()

    def startLoop(self, driver):
        self.record("startLoop")
        assert driver is False
        assert not self.loop
        self.loop = True

    def iterate(self):
        self.record("iterate")

    def isBusy(self):
        self.record("isBusy")
        return self.busy

    def stop(self):
        self.record("stop")
        self.busy = False

    def endLoop(self):
        self.record("endLoop")
        assert self.loop
        self.loop = False


def test_sapi_init_speech_and_stop_share_owner_not_gui_thread(monkeypatch):
    native = Native()
    created = []
    def construct():
        created.append(threading.get_ident())
        return native
    monkeypatch.setitem(sys.modules, "pyttsx3", NS(Engine=construct))
    monkeypatch.setattr(sapi.sys, "platform", "linux")
    engine = sapi.SAPIEngine()
    token = threading.Event()
    play = threading.Thread(target=lambda: engine.speak_stream(iter(["Проба."]), "auto", 1.0, token))
    play.start()
    try:
        assert native.started.wait(2)
        gui_thread = threading.get_ident()
        engine.set_voice("Irina")
        engine.set_rate(1.2)
        token.set()
        engine.stop()
        play.join(2)
        assert not play.is_alive()
        assert not native.loop
        assert {ident for _, ident in native.calls} == set(created)
        assert created[0] != gui_thread
        # A second preview must be possible after stopping the first loop.
        native.started.clear()
        token2 = threading.Event()
        play2 = threading.Thread(target=lambda: engine.speak_stream(iter(["Ещё проба."]), "Irina", 1.2, token2))
        play2.start()
        assert native.started.wait(2)
        token2.set()
        engine.stop()
        play2.join(2)
        assert not play2.is_alive()
        assert len([x for x in native.calls if x[0] == "say"]) == 2
    finally:
        token.set()
        engine.stop()
        play.join(2)
        engine._requests.put(None)
        engine._thread.join(2)


def test_stop_is_signal_only_and_waits_for_native_owner_ack(monkeypatch):
    native = Native()
    entered, release = threading.Event(), threading.Event()
    def iterate():
        native.record("iterate")
        entered.set()
        assert release.wait(3)
    native.iterate = iterate
    monkeypatch.setitem(sys.modules, "pyttsx3", NS(Engine=lambda: native))
    monkeypatch.setattr(sapi.sys, "platform", "linux")
    engine = sapi.SAPIEngine()
    token = threading.Event()
    play = threading.Thread(target=lambda: engine.speak_stream(iter(["Проба."]), "auto", 1.0, token))
    play.start()
    try:
        assert entered.wait(2)
        token.set()
        engine.stop()  # must return even with a stalled native iterate()
        assert play.is_alive()  # no fake completion before native owner confirms
        assert not any(name == "stop" for name, _ in native.calls)
    finally:
        release.set()
        play.join(2)
        engine._requests.put(None)
        engine._thread.join(2)
    assert not play.is_alive()
    assert any(name == "stop" for name, _ in native.calls)
