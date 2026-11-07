"""Решение по распознанной фразе: чёткая команда, нечёткая или не команда.

Заказчик сформулировал правило так: уверенное распознавание — действуем,
неуверенное — не угадываем, а переспрашиваем. Здесь только **решение**, без
действий, без GUI, без аудио и без сети: одна чистая функция, которую можно
проверить таблицей и корпусом фраз.

Три исхода:

- ``clear`` — есть совпадение с известной командой и канал ASR не возражает;
- ``unclear`` — данных мало или каналы расходятся: нужен повтор/уточнение,
  **никогда** не выполнение действия;
- ``not_a_command`` — текст разобрали, но команды в нём нет: обычный диалог.

Семантический слой (шаг 1, ``semantic=True``) — нормализация и словарь синонимов
поверх ``jarvis.matching``: «вруби музыку плз» и «включи музыку» дают одно и то
же. Модельных эмбеддингов здесь нет: нет файла модели — нет и «умного» шага,
честный откат к словарю (см. docs/USER_GUIDE.md).

Модуль сознательно не знает про пароли, pending-вопросы и опасные действия:
сомнение всегда решается в сторону «спросить», а решения safety принимаются
раньше и остаются в силе.
"""

import logging
from dataclasses import dataclass, field

from jarvis.text_utils import normalize

log = logging.getLogger("jarvis.decision")

CLEAR = "clear"
UNCLEAR = "unclear"
NOT_A_COMMAND = "not_a_command"
KINDS = (CLEAR, UNCLEAR, NOT_A_COMMAND)

FILLERS = ("плиз", "пожалуйста", "пожалуста", "плз", "будь добр", "будьте добры")

# Словарь синонимов: что человек говорит → что написано в команде.
# Только то, в чём мы уверены: «поставь» и «вруби» в разных контекстах значат
# разное, поэтому их тут нет — пусть решает исходный матчинг.
SYNONYMS = {
    "врубай": "включи", "вруби": "включи", "врубайте": "включи",
    "включай": "включи", "запускай": "включи", "запусти": "включи",
    "включать": "включи", "врубите": "включи",
    "вырубай": "выключи", "выруби": "выключи", "вырубайте": "выключи",
    "отключай": "выключи", "отключи": "выключи", "погаси": "выключи",
    "заверши": "выключи", "выключать": "выключи",
    "открывай": "открой", "открыть": "открой", "открывай-ка": "открой",
    "закрывай": "закрой", "закрыть": "закрой",
    "остановись": "стоп", "прекрати": "стоп", "хватит": "стоп",
}

_NEGATIONS = ("не",)


@dataclass(frozen=True)
class Thresholds:
    """Пороги решения; из ``config.json`` их достаёт ``from_config``."""

    clear_score: float = 0.85
    unclear_score: float = 0.62
    asr_min: float = 0.55
    agreement: float = 0.80

    @classmethod
    def from_config(cls, config) -> "Thresholds":
        return cls(
            clear_score=_threshold(config, "decision_clear_score", cls.clear_score),
            unclear_score=_threshold(config, "decision_unclear_score", cls.unclear_score),
            asr_min=_threshold(config, "decision_asr_min_confidence", cls.asr_min),
            agreement=_threshold(config, "decision_agreement_min", cls.agreement),
        ).validated()

    def validated(self) -> "Thresholds":
        """Приводит пороги в согласованный вид: 0..1 и unclear <= clear.

        Битое значение (строка, None, бесконечность) заменяется стартовым
        дефолтом, а не превращается в ноль: ноль порога ASR означал бы
        «доверять любому шуму».
        """
        clear = _clamp_or(self.clear_score, 0.85)
        unclear = _clamp_or(self.unclear_score, 0.62)
        unclear = min(unclear, clear)
        return Thresholds(clear, unclear, _clamp_or(self.asr_min, 0.55),
                          _clamp_or(self.agreement, 0.80))


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    score: float
    evidence: dict = field(default_factory=dict)

    @property
    def is_clear(self) -> bool:
        return self.kind == CLEAR

    @property
    def needs_repeat(self) -> bool:
        return self.kind == UNCLEAR


def _clamp(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return max(0.0, min(1.0, number))


def _clamp_or(value, fallback: float) -> float:
    """Число в 0..1; всё, что не число, — стартовый дефолт, а не ноль."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number in (float("inf"), float("-inf")):
        return fallback
    return max(0.0, min(1.0, number))


def _threshold(config, key, default: float) -> float:
    if config is None:
        return default
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def semantic_normalize(text: str) -> str:
    """Шаг 1 семантики: мусор прочь, синонимы к виду команды, «не» на месте."""
    base = normalize(text if isinstance(text, str) else "")
    if not base:
        return ""
    for filler in FILLERS:
        base = base.replace(filler, " ")
    words = []
    for word in base.split():
        words.append(SYNONYMS.get(word, word))
    return " ".join(words).strip()


def has_negation(text: str) -> bool:
    """«не» меняет смысл команды: «не выключай» — это не «выключи»."""
    tokens = normalize(text if isinstance(text, str) else "").split()
    return any(token in _NEGATIONS for token in tokens)


def _score(spoken: str, candidate: str, semantic: bool) -> float:
    from jarvis import matching

    if not spoken or not candidate:
        return 0.0
    if semantic:
        return matching.match_score(semantic_normalize(spoken),
                                    semantic_normalize(candidate))
    return matching.match_score(normalize(spoken), normalize(candidate))


def best_match(text: str, candidates, semantic: bool = False):
    """Лучшее совпадение с кандидатами: (score, intent, phrase) или (0.0, None, None).

    ``candidates`` — пары ``(фраза, имя_интента)`` или просто фразы: тогда
    интентом считается сама фраза. Точное совпадение — сразу 1.0.
    """
    if not isinstance(text, str) or not text.strip():
        return 0.0, None, None
    best = (0.0, None, None)
    for item in candidates or ():
        if isinstance(item, str):
            phrase, intent = item, item
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            phrase, intent = item[0], item[1]
        else:
            continue
        if not isinstance(phrase, str) or not phrase.strip():
            continue
        score = _score(text, phrase, semantic)
        if score > best[0]:
            best = (score, intent, phrase)
    return best


def _asr_confidence(quality) -> float | None:
    """Уверенность ASR из ``recognition.Quality`` / dict / числа; None — нет данных."""
    if quality is None:
        return None
    if isinstance(quality, bool):
        return 1.0 if quality else 0.0
    if isinstance(quality, (int, float)):
        return _clamp(quality)
    if isinstance(quality, dict):
        value = quality.get("score", quality.get("confidence"))
    else:
        value = getattr(quality, "score", None)
    if value is None:
        accepted = quality.get("accepted") if isinstance(quality, dict) else getattr(
            quality, "accepted", None)
        if accepted is None:
            return None
        return 1.0 if accepted else 0.0
    return _clamp(value)


def _match_score(match):
    """Совпадение из вызывающего кода; поддерживает dict и объект с score/intent."""
    if match is None:
        return None, None
    if isinstance(match, (int, float)) and not isinstance(match, bool):
        return _clamp(match), None
    if isinstance(match, dict):
        score = _clamp(match.get("score", 0.0))
        return score, match.get("intent") or match.get("matched") or None
    score = _clamp(getattr(match, "score", 0.0))
    return score, getattr(match, "intent", None)


def decide(text, *, quality=None, match=None, secondary=None, candidates=None,
           thresholds: Thresholds | None = None, semantic: bool = False) -> Decision:
    """Чистое решение по фразе: clear / unclear / not_a_command.

    Каналы-доказательства:
    - ``quality`` — уверенность ASR (``recognition.Quality`` или число);
    - ``match`` — готовое совпадение (score, intent) от вызывающего кода;
    - ``candidates`` — список известных команд, если совпадение ещё не считали;
    - ``secondary`` — вторая гипотеза текста (Whisper против Vosk): её совпадение
      считается теми же кандидатами, и интенты должны сойтись.
    """
    th = (thresholds or Thresholds()).validated()
    evidence = {"semantic": bool(semantic)}
    phrase = text if isinstance(text, str) else ""
    evidence["text"] = normalize(phrase)
    if not evidence["text"]:
        return Decision(NOT_A_COMMAND, "empty", 0.0, evidence)
    if candidates is not None:
        candidates = list(candidates)
        evidence["candidates"] = len(candidates)

    asr = _asr_confidence(quality)
    asr_ok = True if asr is None else asr >= th.asr_min
    evidence["asr"] = asr
    evidence["asr_ok"] = asr_ok

    score, intent = _match_score(match)
    if score is None and candidates is not None:
        score, intent, phrase_hit = best_match(phrase, candidates, semantic)
        if phrase_hit:
            evidence["matched_phrase"] = phrase_hit

    if score is None:
        # Канала совпадения нет — это проверка только распознавания.
        # Не выдумываем «команду»: просто говорим, можно ли понять текст.
        if asr_ok:
            return Decision(CLEAR, "asr_only", 0.0, evidence)
        return Decision(UNCLEAR, "asr_weak", 0.0, evidence)

    evidence["score"] = round(score, 4)
    evidence["intent"] = intent

    # «не выключай музыку» похоже на «выключи музыку», но значит обратное:
    # пока команда с «не» не нашлась буквально, выполнять её нельзя.
    matched_phrase = evidence.get("matched_phrase") or ""
    if has_negation(phrase) and not has_negation(matched_phrase) and score >= th.unclear_score:
        return Decision(UNCLEAR, "negation", score, evidence)

    secondary_text = secondary if isinstance(secondary, str) else ""
    second_score = None
    second_intent = None
    if secondary_text.strip():
        if candidates is not None:
            second_score, second_intent, _ = best_match(secondary_text, candidates, semantic)
        elif match is not None and isinstance(match, dict):
            second_score = _clamp(match.get("secondary_score", score))
            second_intent = match.get("secondary_intent", intent)
        evidence["secondary_score"] = round(second_score, 4) if second_score is not None else None
        evidence["secondary_intent"] = second_intent
        evidence["negation_mismatch"] = has_negation(phrase) != has_negation(secondary_text)

    # --- два канала: согласие ASR-транскриптов -------------------------
    if second_score is not None:
        disagree = (second_intent != intent
                    or abs(score - second_score) > (1.0 - th.agreement))
        if evidence.get("negation_mismatch"):
            return Decision(UNCLEAR, "negation_mismatch", score, evidence)
        if disagree:
            return Decision(UNCLEAR, "disagreement", score, evidence)
        if not asr_ok:
            return Decision(UNCLEAR, "asr_weak", score, evidence)
        if score >= th.clear_score and second_score >= th.clear_score:
            return Decision(CLEAR, "consensus", score, evidence)
        if score < th.unclear_score and second_score < th.unclear_score:
            return Decision(NOT_A_COMMAND, "no_candidate", score, evidence)
        return Decision(UNCLEAR, "ambiguous", score, evidence)

    # --- один канал: совпадение + уверенность ASR ----------------------
    if not asr_ok:
        return Decision(UNCLEAR, "asr_weak", score, evidence)
    if score >= th.clear_score:
        return Decision(CLEAR, "matched", score, evidence)
    if score >= th.unclear_score:
        return Decision(UNCLEAR, "ambiguous", score, evidence)
    return Decision(NOT_A_COMMAND, "no_candidate", score, evidence)
