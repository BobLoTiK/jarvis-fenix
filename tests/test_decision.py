"""Решение «чёткая команда / нечёткая / не команда»: таблица, корпус, синонимы."""
import json
from pathlib import Path

import pytest

from jarvis import decision
from jarvis.decision import CLEAR, NOT_A_COMMAND, UNCLEAR, Decision, Thresholds
from jarvis.intents.fast.custom import find_custom
from jarvis.recognition import Quality

FIXTURE = Path(__file__).with_name("fixtures") / "decision_cases.json"
CORPUS = json.loads(FIXTURE.read_text(encoding="utf-8"))
CANDIDATES = [tuple(pair) for pair in CORPUS["candidates"]]


def run(text, **kwargs):
    kwargs.setdefault("quality", 0.9)
    kwargs.setdefault("candidates", CANDIDATES)
    return decision.decide(text, **kwargs)


@pytest.mark.parametrize("text,expected", [
    ("", NOT_A_COMMAND),
    ("   ", NOT_A_COMMAND),
    (None, NOT_A_COMMAND),
    ("...", NOT_A_COMMAND),
])
def test_empty_phrases_are_not_commands(text, expected):
    assert run(text).kind == expected


def test_short_alias_and_similar_commands_are_distinguished():
    assert run("стоп").kind == CLEAR
    opened = run("открой блокнот")
    closed = run("закрой блокнот")
    assert opened.kind == CLEAR and closed.kind == CLEAR
    assert opened.evidence["intent"] == "open_notepad"
    assert closed.evidence["intent"] == "close_notepad"


def test_negation_never_turns_into_execution():
    verdict = run("не выключай музыку")
    assert verdict.kind == UNCLEAR and verdict.reason == "negation"
    assert verdict.needs_repeat is True


def test_missing_asr_confidence_is_not_punished():
    """Нет данных о качестве — не выдумываем провал, но и «чётко» не обещаем."""
    assert run("включи музыку", quality=None).kind == CLEAR
    weak = run("включи музыку", quality=Quality(True, "reliable_words", 0.2))
    assert weak.kind == UNCLEAR and weak.reason == "asr_weak"


def test_rejected_quality_always_asks_again():
    verdict = run("включи музыку", quality=Quality(False, "near_silence"))
    assert verdict.kind == UNCLEAR and verdict.reason == "asr_weak"


def test_no_match_channel_reacts_to_asr_only():
    assert decision.decide("включи музыку", quality=0.9).kind == CLEAR
    assert decision.decide("включи музыку", quality=0.1).kind == UNCLEAR


def test_second_transcript_must_agree_on_intent():
    agree = run("включи музыку", secondary="включи музыку пожалуйста")
    assert agree.kind == CLEAR and agree.reason == "consensus"
    disagree = run("открой блокнот", secondary="закрой блокнот")
    assert disagree.kind == UNCLEAR and disagree.reason == "disagreement"
    negated = run("выключи музыку", secondary="не выключай музыку")
    assert negated.kind == UNCLEAR


def test_two_hypotheses_of_nonsense_never_become_a_command():
    verdict = run("расскажи анекдот", secondary="расскажи анекдот про кота")
    assert verdict.kind != CLEAR
    assert verdict.kind in (NOT_A_COMMAND, UNCLEAR)
    assert verdict.evidence["score"] < 0.62


def test_match_object_is_accepted():
    verdict = decision.decide("включи музыку", quality=0.9,
                              match={"score": 0.95, "intent": "music_on"})
    assert verdict.kind == CLEAR and verdict.evidence["intent"] == "music_on"
    low = decision.decide("включи музыку", quality=0.9, match=0.3)
    assert low.kind == NOT_A_COMMAND


def test_thresholds_are_clamped_and_ordered():
    thresholds = Thresholds(clear_score=3, unclear_score=-2, asr_min="x", agreement=None)
    fixed = thresholds.validated()
    assert fixed.clear_score == 1.0 and fixed.unclear_score == 0.0
    assert fixed.asr_min == 0.55 and fixed.agreement == 0.80
    config = {"decision_clear_score": 0.4, "decision_unclear_score": 0.9,
              "decision_asr_min_confidence": 2, "decision_agreement_min": "bad"}
    from_config = Thresholds.from_config(config)
    assert from_config.clear_score == 0.4 and from_config.unclear_score == 0.4
    assert from_config.asr_min == 1.0 and from_config.agreement == 0.80
    assert Thresholds.from_config(None) == Thresholds()


def test_decision_is_immutable_snapshot():
    verdict = run("включи музыку")
    assert isinstance(verdict, Decision)
    assert verdict.is_clear and not verdict.needs_repeat
    with pytest.raises(Exception):
        verdict.kind = "clear"


def test_semantic_layer_off_keeps_raw_matching():
    assert run("вруби музыку").kind == UNCLEAR
    assert run("вруби музыку", semantic=False).kind == UNCLEAR
    assert decision.semantic_normalize("вруби музыку плиз") == "включи музыку"
    assert decision.semantic_normalize("Погаси, МУЗЫКУ!") == "выключи музыку"


def test_semantic_layer_on_resolves_synonyms():
    for case in CORPUS["semantic_cases"]:
        verdict = run(case["text"], semantic=True)
        assert verdict.kind == case["expected"], (case["text"], verdict.reason, verdict.score)


def test_corpus_accuracy_does_not_regress():
    """Корпус маленький и ручной — это защита от регрессии, а не статистика."""
    total = len(CORPUS["cases"])
    correct = 0
    mistakes = []
    for case in CORPUS["cases"]:
        verdict = run(case["text"], quality=case.get("quality", 0.9))
        if verdict.kind == case["expected"]:
            correct += 1
        else:
            mistakes.append((case["text"], case["expected"], verdict.kind, verdict.reason))
    accuracy = correct / total
    assert accuracy >= 0.92, f"точность {accuracy:.2f} на {total} фразах: {mistakes}"


def test_semantic_corpus_is_clear_only_with_the_flag():
    for case in CORPUS["semantic_cases"]:
        assert run(case["text"], semantic=True).kind == CLEAR
    unresolved = [case["text"] for case in CORPUS["semantic_cases"]
                  if run(case["text"], semantic=False).kind != CLEAR]
    assert unresolved, "часть синонимов обязана требовать семантику, иначе флаг бессмысленен"


def test_custom_commands_use_semantics_only_behind_the_flag():
    custom = [(["включи музыку"], "music.exe", "Включаю.")]
    assert find_custom(custom, "вруби музыку плиз") is None
    assert find_custom(custom, "вруби музыку плиз", semantic=True) is not None
    assert find_custom(custom, "включи музыку") is not None
