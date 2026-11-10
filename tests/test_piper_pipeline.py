"""Piper-стрим: синтез идёт внахлёст с проигрыванием, отмена честная."""

import threading
import time

from jarvis.tts_engines.piper import PiperEngine

TEXT = "Альфа. Бета. Гамма."


def _engine(events, synth_delay=0.15, play_delay=0.30, on_play=None):
    engine = PiperEngine.__new__(PiperEngine)
    engine._synth_lock = threading.Lock()

    def synthesize(text, voice=None, rate=None):
        events.append(("synth_start", text, time.monotonic()))
        time.sleep(synth_delay)
        events.append(("synth_end", text, time.monotonic()))
        return ("wav:" + text).encode("utf-8")

    def play(wav, token):
        events.append(("play_start", wav, time.monotonic()))
        if on_play is not None:
            on_play(token)
        time.sleep(play_delay)
        events.append(("play_end", wav, time.monotonic()))

    engine.synthesize = synthesize
    engine.set_wav_player(play)
    return engine


def test_stream_returns_text_and_plays_in_order():
    events = []
    engine = _engine(events)
    token = threading.Event()

    result = engine.speak_stream(iter([TEXT]), "ruslan", 1.0, token)

    assert result == TEXT
    played = [payload for kind, payload, _ in events if kind == "play_start"]
    expected = [("wav:" + sentence).encode("utf-8")
                for sentence in ("Альфа.", "Бета.", "Гамма.")]
    assert played == expected


def test_second_sentence_is_synthesized_while_first_plays():
    events = []
    engine = _engine(events)
    token = threading.Event()

    engine.speak_stream(iter([TEXT]), "ruslan", 1.0, token)

    first_play_end = next(at for kind, _, at in events if kind == "play_end")
    starts = [at for kind, payload, at in events
              if kind == "synth_start" and payload == "Бета."]
    assert starts and starts[0] < first_play_end


def test_cancel_stops_playback_and_returns_promptly():
    events = []
    token = threading.Event()

    def cancel(_token):
        token.set()

    engine = _engine(events, synth_delay=0.02, play_delay=0.2,
                     on_play=cancel)
    started = time.monotonic()
    engine.speak_stream(iter([TEXT]), "ruslan", 1.0, token)
    elapsed = time.monotonic() - started

    played = [payload for kind, payload, _ in events if kind == "play_start"]
    assert played == [("wav:Альфа.").encode("utf-8")]
    assert elapsed < 2.0
