"""Очерёдность разговора при перебивании: чей это голос и можно ли вклиниться.

Barge-in уже есть (`jarvis/stt.py`): микрофон не выключается во время речи, а
уровень сравнивается с порогом эха. Здесь только правило «пора ли считать это
перебиванием» — отдельной чистой функцией, чтобы пороги можно было проверить
таблицей, не подключая микрофон.

Три причины не считать перебиванием:

- `too_soon` — мы ещё договариваем начало фразы: в первые доли секунды после
  начала речи микрофон слышит собственный хвост из колонок;
- `quiet` — уровень не превысил порог с запасом (это фон/эхо, а не человек);
- `short` — всплеск короче минимума (кашель, щелчок, стук).

По умолчанию поведение не меняется: `barge_policy_enabled=false`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BargePolicy:
    """Пороги перебивания. Значения — секунды и доли, не «на глаз»."""

    min_after_tts_sec: float = 0.35
    min_speech_ms: int = 150
    level_margin: float = 1.15

    @classmethod
    def from_config(cls, config) -> "BargePolicy":
        return cls(
            min_after_tts_sec=_clamp_or(config.get("barge_min_after_tts_sec"), 0.35, 0.0, 3.0),
            min_speech_ms=int(_clamp_or(config.get("barge_min_speech_ms"), 150, 50, 2000)),
            level_margin=_clamp_or(config.get("barge_level_margin"), 1.15, 1.0, 5.0),
        )

    def evaluate(self, *, rms: float, threshold: float, speech_ms: float,
                 tts_elapsed: float | None) -> str:
        """`barge` — можно перебивать; иначе причина отказа."""
        if tts_elapsed is not None and tts_elapsed < self.min_after_tts_sec:
            return "too_soon"
        if rms <= threshold * self.level_margin:
            return "quiet"
        if speech_ms < self.min_speech_ms:
            return "short"
        return "barge"


def _clamp_or(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return max(low, min(high, number))
