"""Быстрый интент «расскажи шутку»: свои реплики вместо импровизации LLM."""

from jarvis import jokes
from jarvis.intents.fast import build_registry
from jarvis.intents.fast.jokes import joke_fast


def test_generic_joke_requests_are_answered_from_bank():
    for cmd in ("расскажи шутку", "пошути", "анекдот", "рассмеши меня"):
        reply = joke_fast(None, cmd)
        assert reply in jokes.JOKES


def test_themed_joke_goes_to_llm():
    assert joke_fast(None, "расскажи шутку про кота") is None
    assert joke_fast(None, "анекдот про программиста") is None


def test_unrelated_commands_are_ignored():
    assert joke_fast(None, "как дела") is None
    assert joke_fast(None, "который час") is None


def test_registry_answers_jokes_before_small_talk():
    names = [name for name, _ in build_registry(None)]
    assert names.index("joke") < names.index("small_talk")
