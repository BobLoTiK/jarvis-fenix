"""Эскалация распознавания: если первому движку не поверили — спросить второй.

Заказчик сказал так: Vosk не лучший распознаватель; когда уверенность ниже
порога, надо звать «тяжёлую артиллерию», а не угадывать. Здесь только решение
«звать/не звать» и сверка двух текстов — сам звук и модели остаются у своих
владельцев (`jarvis/stt.py`, `jarvis/main.py`).

Правила:

- по умолчанию эскалации нет (`asr_escalate_enabled=false`): поведение как
  раньше, и Vosk никуда не девается — он же и wake-слово, и запасной движок;
- эскалация — только при сомнении (`decision.unclear` или «команда не нашли»),
  не на каждую фразу; есть бюджет и кэш повторных текстов;
- второй движок упал или промолчал — пользователь получает «не расслышал»,
  а не падение и не «выполнить хоть что-нибудь»;
- тексты разошлись по критичным деталям (`transcripts_agree`) — это `unclear`,
  вопрос/повтор, никогда не действие;
- отмена (Stop, barge-in) проверяется до и после тяжёлого вызова: тяжёлая
  расшифровка не должна держать перебивание.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from jarvis.recognition import Quality, transcripts_agree

log = logging.getLogger("jarvis.asr_router")


@dataclass(frozen=True)
class Transcript:
    """Результат одного движка: текст, качество, имя и время."""

    text: str
    quality: Quality | None = None
    engine: str = ""
    latency: float | None = None


@dataclass(frozen=True)
class RouteResult:
    """Что решил роутер: итоговый текст, была ли эскалация и почему."""

    transcript: Transcript | None
    escalated: bool
    reason: str
    primary: Transcript | None = None
    secondary: Transcript | None = None
    decision_kind: str = ""

    @property
    def text(self) -> str:
        return self.transcript.text if self.transcript is not None else ""

    @property
    def needs_repeat(self) -> bool:
        """Нужен повтор: движок упал, разошлись или итог всё ещё нечёткий."""
        return self.reason in {
            "primary_failed", "fallback_failed", "fallback_empty",
            "disagreement", "unclear", "cancelled",
        }


class CallableEngine:
    """Адаптер: любой `fn(pcm, rate) -> Transcript|str|dict` как движок."""

    def __init__(self, name: str, fn: Callable):
        self.name = name
        self.fn = fn

    def transcribe(self, pcm: bytes, rate: int) -> Transcript:
        started = time.monotonic()
        result = self.fn(pcm, rate)
        if isinstance(result, Transcript):
            transcript = result
        elif isinstance(result, str):
            transcript = Transcript(result, None, self.name)
        elif isinstance(result, dict):
            transcript = Transcript(
                str(result.get("text") or ""), result.get("quality"),
                str(result.get("engine") or self.name), result.get("latency"))
        else:
            raise TypeError("Движок должен вернуть Transcript, строку или dict")
        latency = transcript.latency
        if latency is None:
            latency = time.monotonic() - started
        return Transcript(transcript.text or "", transcript.quality,
                          transcript.engine or self.name, latency)


class Budget:
    """Сколько раз в минуту разрешено звать тяжёлый движок."""

    def __init__(self, limit: int = 3, window_sec: float = 60.0):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 3
        self.limit = max(0, limit)
        try:
            self.window = max(1.0, float(window_sec))
        except (TypeError, ValueError):
            self.window = 60.0
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def allow(self, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        with self._lock:
            self._calls = [t for t in self._calls if moment - t < self.window]
            if len(self._calls) >= self.limit:
                return False
            self._calls.append(moment)
            return True

    @property
    def used(self) -> int:
        with self._lock:
            return len(self._calls)


class Cache:
    """Кэш «первый текст → второй текст»: одинаковую фразу не гоняем дважды."""

    def __init__(self, ttl: float = 60.0, limit: int = 32):
        self.ttl = 60.0
        try:
            self.ttl = max(1.0, float(ttl))
        except (TypeError, ValueError):
            self.ttl = 60.0
        try:
            self.limit = max(1, int(limit))
        except (TypeError, ValueError):
            self.limit = 32
        self._items: dict = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(text: str, rate: int) -> tuple:
        return " ".join((text or "").lower().split()), int(rate or 0)

    def get(self, text: str, rate: int, now: float | None = None) -> Transcript | None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            item = self._items.get(self.key(text, rate))
            if item is None:
                return None
            value, stamp = item
            if moment - stamp > self.ttl:
                self._items.pop(self.key(text, rate), None)
                return None
            return value

    def put(self, text: str, rate: int, value: Transcript,
            now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        with self._lock:
            if len(self._items) >= self.limit:
                oldest = min(self._items, key=lambda k: self._items[k][1])
                self._items.pop(oldest, None)
            self._items[self.key(text, rate)] = (value, moment)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class Router:
    """Основной движок → при сомнении второй → сверка текстов."""

    def __init__(self, primary, fallback=None, *, enabled: bool = False,
                 budget: Budget | None = None, cache: Cache | None = None,
                 thresholds=None, semantic: bool = False):
        self.primary = primary
        self.fallback = fallback
        self.enabled = bool(enabled)
        self.budget = budget
        self.cache = cache
        self.thresholds = thresholds
        self.semantic = bool(semantic)

    # --- служебное -------------------------------------------------

    def _call(self, engine, pcm: bytes, rate: int, *, allow_empty: bool = False) -> Transcript | None:
        try:
            transcript = engine.transcribe(pcm, rate)
        except Exception:
            log.exception("ASR: движок %s упал", getattr(engine, "name", "?"))
            return None
        if transcript is None:
            return None
        if not allow_empty and not transcript.text.strip():
            return None
        return transcript

    def _decide(self, transcript: Transcript, candidates, match):
        from jarvis import decision

        return decision.decide(
            transcript.text,
            quality=transcript.quality,
            match=match,
            candidates=candidates,
            thresholds=self.thresholds,
            semantic=self.semantic,
        )

    # --- основной путь ---------------------------------------------

    def run(self, pcm: bytes, rate: int, *, candidates=None, match=None,
            matched: bool | None = None, cancel_event=None) -> RouteResult:
        """Один проход: сначала основной движок, второй — только при сомнении."""
        primary = self._call(self.primary, pcm, rate)
        if primary is None:
            return RouteResult(None, False, "primary_failed")
        if not self.enabled or self.fallback is None:
            verdict = self._decide(primary, candidates, match)
            return RouteResult(primary, False,
                               "confident" if verdict.kind == "clear" else "no_fallback",
                               primary=primary, decision_kind=verdict.kind)

        decision_kind = ""
        reason = ""
        if matched is False:
            reason = "no_match"
        else:
            verdict = self._decide(primary, candidates, match)
            decision_kind = verdict.kind
            if verdict.kind == "unclear":
                reason = "unclear"
        if not reason:
            return RouteResult(primary, False, "confident",
                               primary=primary, decision_kind=decision_kind)

        if cancel_event is not None and cancel_event.is_set():
            return RouteResult(primary, False, "cancelled", primary=primary,
                               decision_kind=decision_kind)
        cached = self.cache.get(primary.text, rate) if self.cache is not None else None
        if cached is not None:
            verdict = self._decide(cached, candidates, match)
            return RouteResult(cached, True, "cache", primary=primary,
                               secondary=cached, decision_kind=verdict.kind)
        if self.budget is not None and not self.budget.allow():
            log.info("ASR: эскалация отложена — бюджет на минуту израсходован")
            return RouteResult(primary, False, "budget", primary=primary,
                               decision_kind=decision_kind)

        secondary = self._call(self.fallback, pcm, rate, allow_empty=True)
        if secondary is None:
            return RouteResult(primary, True, "fallback_failed", primary=primary,
                               decision_kind=decision_kind)
        if not secondary.text.strip():
            return RouteResult(primary, True, "fallback_empty", primary=primary,
                               secondary=secondary, decision_kind=decision_kind)
        if cancel_event is not None and cancel_event.is_set():
            return RouteResult(primary, True, "cancelled", primary=primary,
                               secondary=secondary, decision_kind=decision_kind)
        if not transcripts_agree(primary.text, secondary.text):
            log.info("ASR: тексты движков разошлись — переспрошу, не выполнять")
            return RouteResult(secondary, True, "disagreement", primary=primary,
                               secondary=secondary, decision_kind="unclear")
        if self.cache is not None:
            self.cache.put(primary.text, rate, secondary)
        verdict = self._decide(secondary, candidates, match)
        return RouteResult(secondary, True,
                           "confident" if verdict.kind == "clear" else "unclear",
                           primary=primary, secondary=secondary,
                           decision_kind=verdict.kind)
