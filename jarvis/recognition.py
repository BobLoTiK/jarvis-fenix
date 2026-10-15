"""Measurable ASR acceptance policy, not a blacklist of 'strange' words.

Scores are recognizer evidence, not a guarantee of understanding. All thresholds
are conservative defaults and should be calibrated on real microphone recordings.
No rejected transcript is saved here; metadata contains no recognized text.
"""

from array import array
from dataclasses import dataclass
from math import isfinite, sqrt
import sys


@dataclass(frozen=True)
class Quality:
    accepted: bool
    reason: str
    score: float | None = None
    metrics: tuple = ()


def _setting(config, key, default, low, high):
    try:
        value = float(config.get(key, default)) if config is not None else default
        return min(high, max(low, value)) if isfinite(value) else default
    except (TypeError, ValueError):
        return default


def assess_pcm(pcm, sample_rate=16000):
    if (
        not isinstance(sample_rate, (int, float))
        or not isfinite(sample_rate)
        or sample_rate <= 0
    ):
        return Quality(False, "invalid_sample_rate")
    if not pcm or len(pcm) % 2:
        return Quality(False, "invalid_audio")
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) / sample_rate < 0.12:
        return Quality(False, "audio_too_short")
    rms = sqrt(sum(v * v for v in samples) / len(samples))
    clipped = sum(abs(v) >= 32760 for v in samples) / len(samples)
    metrics = (("rms", rms), ("clipped_fraction", clipped))
    if rms < 8:
        return Quality(False, "near_silence", metrics=metrics)
    if clipped > 0.25:
        return Quality(False, "severe_clipping", metrics=metrics)
    return Quality(True, "signal_present", metrics=metrics)


def assess_vosk(result, config=None):
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("text"), str)
        or not result["text"].strip()
    ):
        return Quality(False, "empty_transcript")
    words = result.get("result")
    if not isinstance(words, list) or not words:
        return Quality(False, "missing_word_confidence")
    try:
        scores = [float(word["conf"]) for word in words]
    except (KeyError, TypeError, ValueError):
        return Quality(False, "missing_word_confidence")
    if any(not isfinite(v) or not 0 <= v <= 1 for v in scores):
        return Quality(False, "invalid_word_confidence")
    mean = sum(scores) / len(scores)
    minimum = min(scores)
    threshold = _setting(config, "stt_min_word_confidence", 0.65, 0, 1)
    metrics = (("mean_word_confidence", mean), ("min_word_confidence", minimum))
    if mean < threshold or minimum < max(0, threshold - 0.15):
        return Quality(False, "uncertain_words", mean, metrics)
    return Quality(True, "reliable_words", mean, metrics)


def assess_whisper(segments, config=None):
    if not segments:
        return Quality(False, "empty_transcript")
    low = _setting(config, "stt_min_avg_logprob", -1.0, -5, 0)
    silence = _setting(config, "stt_max_no_speech_prob", 0.6, 0, 1)
    compression = _setting(config, "stt_max_compression_ratio", 2.4, 1, 10)
    probabilities = []
    for segment in segments:
        if not getattr(segment, "text", "").strip():
            continue
        try:
            logprob = float(segment.avg_logprob)
            no_speech = float(segment.no_speech_prob)
            ratio = float(segment.compression_ratio)
        except (AttributeError, TypeError, ValueError):
            return Quality(False, "missing_segment_confidence")
        if (
            not all(isfinite(v) for v in (logprob, no_speech, ratio))
            or not 0 <= no_speech <= 1
        ):
            return Quality(False, "invalid_segment_confidence")
        probabilities.append(logprob)
        # Never remove just a low-confidence fragment: it may contain «не» or a number.
        if no_speech > silence:
            return Quality(False, "likely_non_speech", logprob)
        if logprob < low:
            return Quality(False, "uncertain_segment", logprob)
        if ratio > compression:
            return Quality(False, "repetitive_decoding", logprob)
    if not probabilities:
        return Quality(False, "empty_transcript")
    return Quality(True, "reliable_segments", sum(probabilities) / len(probabilities))


def transcripts_agree(primary, secondary):
    """Corroborate critical command details; don't require identical ASR spelling."""
    from jarvis.language import analyze_command
    from jarvis.text_utils import normalize
    from jarvis.matching import match_score

    a, b = analyze_command(primary), analyze_command(secondary)
    if a.issue or b.issue:
        return False
    av = [n.value for n in analyze_command(a.command).numbers]
    bv = [n.value for n in analyze_command(b.command).numbers]
    if av != bv:
        return False
    left, right = normalize(a.command).split(), normalize(b.command).split()
    if ("не" in left) != ("не" in right):
        return False
    families = {
        **dict.fromkeys(("открой", "открывай", "запусти", "включи", "врубай"), "open"),
        **dict.fromkeys(("закрой", "закрывай", "выключи"), "close"),
        "сверни": "minimize",
        "разверни": "maximize",
        "удали": "delete",
        "очисти": "clear",
    }

    def action(tokens):
        return next(
            ((i, families[t]) for i, t in enumerate(tokens[:3]) if t in families), None
        )

    first, second = action(left), action(right)
    if first or second:
        if not first or not second or first[1] != second[1]:
            return False
        target_a = " ".join(left[first[0] + 1 :])
        target_b = " ".join(right[second[0] + 1 :])
        if bool(target_a) != bool(target_b):
            return False
        if target_a and match_score(target_a, target_b) < 0.6:
            return False
    return True
