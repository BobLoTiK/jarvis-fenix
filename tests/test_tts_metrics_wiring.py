"""Связка Speaker→Timeline: метки появляются, поведение озвучки не меняется."""

from jarvis import audio_metrics, audio_output, tts


class FakeEngine:
    name = "piper"
    voice = "ruslan"

    def __init__(self):
        self._wav_player = None

    def set_wav_player(self, player):
        self._wav_player = player

    def set_rate(self, rate):
        pass

    def stop(self):
        pass

    def synthesize(self, text, voice=None, rate=None):
        return b"wav"

    def speak_stream(self, text_iter, voice, rate, token):
        parts = []
        for chunk in text_iter:
            parts.append(chunk)
        self._wav_player(b"wav", token)
        return "".join(parts).strip()


def _speaker(monkeypatch, engine):
    monkeypatch.setattr(tts, "get_engine", lambda *args, **kwargs: engine)
    return tts.Speaker({"tts_backend": "piper", "tts_voice": "ruslan"})


def test_speak_stream_marks_pcm_and_audio(monkeypatch):
    audio_metrics.reset()
    engine = FakeEngine()
    calls = []

    def fake_play_wav(wav, token, reaction=None, *, echo=None, timeline=None):
        calls.append(echo)
        if timeline is not None:
            timeline.mark("first_audio")

    monkeypatch.setattr(audio_output, "play_wav", fake_play_wav)
    speaker = _speaker(monkeypatch, engine)
    timeline = audio_metrics.Timeline()

    text = speaker.speak_stream(iter(["Один.", " Два."]), timeline=timeline)

    assert text == "Один. Два."
    assert calls
    marks = timeline.durations()
    assert "first_pcm" in marks
    assert "first_audio" in marks
    record = timeline.finish()
    assert record["pcm_ms"] is not None
    assert record["audio_ms"] is not None


def test_play_async_marks_pcm(monkeypatch):
    audio_metrics.reset()
    monkeypatch.setattr(audio_output, "play_wav", lambda *args, **kwargs: None)
    speaker = _speaker(monkeypatch, FakeEngine())
    timeline = audio_metrics.Timeline()

    assert speaker.play_async("Привет", timeline=timeline)
    assert speaker.wait_end(3.0)
    assert "first_pcm" in timeline.durations()
