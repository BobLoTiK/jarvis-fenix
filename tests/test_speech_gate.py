"""Тесты jarvis.vad.SpeechHangover — «хвост» тишины после речи.

Почему это критично: Vosk завершает фразу по тишине
(`KaldiRecognizer.AcceptWaveform` -> True). Если VAD вырежет тишину
целиком, Vosk не отдаст финальный текст и Феникс ответит поздно или
не ответит вовсе. SpeechHangover решает, какие блоки отдать в Vosk.

Модуль НЕ требует onnxruntime/sounddevice — тесты идут и в CI.
"""

from jarvis.vad import DEFAULT_HANGOVER_MS, SpeechHangover


def test_blocks_for_ms_rounds():
    """1500 мс при блоке 500 мс → 3 блока."""
    assert SpeechHangover.blocks_for_ms(1500, 500) == 3


def test_blocks_for_ms_zero_block():
    """Нулевой/отрицательный блок не делим на ноль."""
    assert SpeechHangover.blocks_for_ms(1500, 0) == 0
    assert SpeechHangover.blocks_for_ms(1500, -5) == 0


def test_blocks_for_ms_negative_ms():
    """Отрицательный хвост — это «без хвоста»."""
    assert SpeechHangover.blocks_for_ms(-100, 500) == 0


def test_default_hangover_is_1500ms():
    assert DEFAULT_HANGOVER_MS == 1500


def test_speech_block_always_passed():
    """Речевой блок отдаётся в Vosk всегда."""
    gate = SpeechHangover(blocks=3)
    assert gate.feed(True) is True


def test_silence_before_speech_is_dropped():
    """До речи тишина не гоняется в Vosk (экономия CPU)."""
    gate = SpeechHangover(blocks=3)
    for _ in range(10):
        assert gate.feed(False) is False


def test_hangover_passes_exactly_n_silence_blocks():
    """После речи проходит ровно N блоков тишины, дальше — стоп."""
    gate = SpeechHangover(blocks=3)
    assert gate.feed(True) is True

    assert [gate.feed(False) for _ in range(5)] == [True, True, True,
                                                    False, False]


def test_hangover_refreshed_by_new_speech():
    """Каждый речевой блок продлевает хвост заново."""
    gate = SpeechHangover(blocks=2)
    gate.feed(True)
    assert gate.feed(False) is True
    assert gate.feed(True) is True          # хвост продлён
    assert [gate.feed(False) for _ in range(3)] == [True, True, False]


def test_zero_blocks_behaves_like_plain_gate():
    """blocks=0 — чистый гейт без хвоста (старое поведение)."""
    gate = SpeechHangover(blocks=0)
    assert gate.feed(True) is True
    assert gate.feed(False) is False


def test_negative_blocks_clamped_to_zero():
    assert SpeechHangover(blocks=-3).max_blocks == 0


def test_reset_clears_hangover():
    """reset() (flush/barge) обнуляет хвост — тишина не утечёт в Vosk."""
    gate = SpeechHangover(blocks=3)
    gate.feed(True)
    assert gate.feed(False) is True
    gate.reset()
    assert gate.feed(False) is False


def test_max_blocks_property():
    assert SpeechHangover(blocks=4).max_blocks == 4
