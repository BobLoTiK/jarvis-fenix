"""Эскалация ASR: табличные тесты роутера на фейковых движках, без моделей и звука."""
import threading
import time

import pytest

from jarvis.asr_router import Budget, Cache, CallableEngine, Router, Transcript
from jarvis.decision import Thresholds
from jarvis.recognition import Quality

OK = Quality(True, "reliable_words", 0.92)
WEAK = Quality(True, "uncertain_words", 0.30)
BAD = Quality(False, "near_silence")


def engine(name, text, quality=OK, calls=None, exc=None, latency=0.01):
    def fn(_pcm, _rate):
        if calls is not None:
            calls.append(name)
        if exc is not None:
            raise exc
        return Transcript(text, quality, name, latency)
    return CallableEngine(name, fn)


def router(primary_text="включи музыку", fallback_text=None, *, primary_quality=OK,
           enabled=True, calls=None, budget=None, cache=None, thresholds=None,
           semantic=False, fallback_exc=None):
    primary = engine("vosk", primary_text, primary_quality, calls)
    fallback = None
    if enabled and (fallback_text is not None or fallback_exc is not None):
        fallback = engine("whisper", fallback_text or "", OK, calls, exc=fallback_exc)
    return Router(primary, fallback, enabled=enabled, budget=budget, cache=cache,
                  thresholds=thresholds, semantic=semantic)


def test_callable_engine_accepts_text_dict_and_transcript():
    plain = CallableEngine("x", lambda pcm, rate: "привет")
    assert plain.transcribe(b"", 16000).text == "привет"
    assert plain.transcribe(b"", 16000).engine == "x"
    mapping = CallableEngine("y", lambda pcm, rate: {"text": "ок", "quality": OK})
    result = mapping.transcribe(b"", 16000)
    assert result.text == "ок" and result.quality is OK and result.engine == "y"
    ready = CallableEngine("z", lambda pcm, rate: Transcript("да", OK, "z", 0.5))
    assert ready.transcribe(b"", 16000).latency == 0.5
    with pytest.raises(TypeError):
        CallableEngine("w", lambda pcm, rate: 42).transcribe(b"", 16000)


def test_escalation_is_off_by_default():
    calls = []
    r = router(fallback_text="включи музыку", enabled=False, calls=calls,
               primary_quality=WEAK)
    result = r.run(b"pcm", 16000)
    assert result.escalated is False and result.reason == "no_fallback"
    assert calls == ["vosk"]


def test_confident_primary_does_not_call_the_heavy_engine():
    calls = []
    r = router(fallback_text="включи музыку", calls=calls)
    result = r.run(b"pcm", 16000, candidates=[("включи музыку", "music_on")])
    assert result.escalated is False and result.reason == "confident"
    assert calls == ["vosk"] and result.decision_kind == "clear"


def test_weak_quality_escalates_and_agreement_adopts_second_text():
    calls = []
    r = router("включи музку", "включи музыку", calls=calls, primary_quality=WEAK)
    result = r.run(b"pcm", 16000)
    assert result.escalated is True and result.reason == "confident"
    assert calls == ["vosk", "whisper"]
    assert result.text == "включи музыку"
    assert result.transcript.engine == "whisper"


def test_disagreement_asks_again_and_never_acts():
    r = router("открой блокнот", "закрой блокнот")
    result = r.run(b"pcm", 16000, matched=False)
    assert result.escalated is True and result.reason == "disagreement"
    assert result.needs_repeat is True and result.decision_kind == "unclear"


def test_number_mismatch_between_engines_is_unclear():
    r = router("громкость 5", "громкость 7", primary_quality=WEAK)
    result = r.run(b"pcm", 16000)
    assert result.reason == "disagreement" and result.needs_repeat is True


def test_missing_dictionary_match_escalates_even_with_good_quality():
    calls = []
    r = router("вруби музыку", "включи музыку", calls=calls)
    result = r.run(b"pcm", 16000, matched=False)
    assert result.escalated is True and calls == ["vosk", "whisper"]
    assert result.text == "включи музыку"


@pytest.mark.parametrize("fallback_kwargs,reason", [
    ({"fallback_exc": RuntimeError("нет модели")}, "fallback_failed"),
    ({"fallback_text": "   "}, "fallback_empty"),
])
def test_broken_fallback_becomes_ask_again_not_crash(fallback_kwargs, reason):
    calls = []
    r = router("включи музку", calls=calls, primary_quality=WEAK, **fallback_kwargs)
    result = r.run(b"pcm", 16000)
    assert result.reason == reason
    assert result.needs_repeat is True
    assert result.text == "включи музку"  # остаётся текст первого движка


def test_broken_primary_is_honest():
    def boom(_pcm, _rate):
        raise RuntimeError("vosk умер")

    r = Router(CallableEngine("vosk", boom), engine("whisper", "привет"), enabled=True)
    result = r.run(b"pcm", 16000)
    assert result.transcript is None and result.reason == "primary_failed"
    assert result.needs_repeat is True


def test_budget_limits_heavy_engine_and_reports_it():
    calls = []
    budget = Budget(limit=1, window_sec=60)
    r = router("включи музку", "включи музыку", calls=calls, budget=budget,
               primary_quality=WEAK)
    first = r.run(b"pcm", 16000)
    second = r.run(b"pcm", 16000, matched=False)
    assert first.escalated is True
    assert second.escalated is False and second.reason == "budget"
    assert calls == ["vosk", "whisper", "vosk"]
    assert budget.used == 1


def test_budget_window_expires():
    budget = Budget(limit=1, window_sec=10)
    assert budget.allow(now=100.0) is True
    assert budget.allow(now=105.0) is False
    assert budget.allow(now=111.0) is True


def test_cache_avoids_second_heavy_call():
    calls = []
    cache = Cache(ttl=60, limit=4)
    r = router("включи музку", "включи музыку", calls=calls, cache=cache,
               primary_quality=WEAK)
    r.run(b"pcm", 16000)
    second = r.run(b"pcm", 16000)
    assert second.escalated is True and second.reason == "cache"
    assert calls == ["vosk", "whisper", "vosk"]
    assert second.text == "включи музыку"


def test_cache_expires_and_respects_rate():
    cache = Cache(ttl=5, limit=2)
    value = Transcript("включи музыку", OK, "whisper")
    cache.put("включи музку", 16000, value, now=100.0)
    assert cache.get("включи музку", 16000, now=104.0) is value
    assert cache.get("включи музку", 16000, now=106.0) is None
    assert cache.get("включи музку", 8000, now=101.0) is None


def test_cancel_before_and_during_heavy_call():
    calls = []
    cancel = threading.Event()
    cancel.set()
    r = router("включи музку", "включи музыку", calls=calls, primary_quality=WEAK)
    result = r.run(b"pcm", 16000, cancel_event=cancel)
    assert result.reason == "cancelled" and calls == ["vosk"]
    assert result.needs_repeat is True

    cancel.clear()

    def slow_fallback(_pcm, _rate):
        cancel.set()
        return Transcript("включи музыку", OK, "whisper", 0.2)

    r2 = Router(engine("vosk", "включи музку", WEAK), CallableEngine("whisper", slow_fallback),
                enabled=True)
    after = r2.run(b"pcm", 16000, cancel_event=cancel)
    assert after.reason == "cancelled" and after.escalated is True


def test_thresholds_from_config_control_escalation():
    # Планка уверенности ASR: 0.7 при планке 0.8 — сомнение, при 0.5 — норма.
    quality = Quality(True, "uncertain_words", 0.70)
    strict = Thresholds(asr_min=0.80)
    r = router("включи музыку", "включи музыку", primary_quality=quality,
               thresholds=strict)
    assert r.run(b"pcm", 16000).escalated is True
    loose = Thresholds(asr_min=0.50)
    r2 = router("включи музыку", "включи музыку", primary_quality=quality,
                thresholds=loose)
    assert r2.run(b"pcm", 16000).escalated is False


def test_semantic_router_resolves_synonyms_instead_of_escalating():
    candidates = [("включи музыку", "music_on")]
    plain = router("вруби музыку", "включи музыку", semantic=False)
    assert plain.run(b"pcm", 16000, candidates=candidates).escalated is True
    smart = router("вруби музыку", "включи музыку", semantic=True)
    result = smart.run(b"pcm", 16000, candidates=candidates)
    assert result.escalated is False and result.decision_kind == "clear"
    assert result.text == "вруби музыку"
