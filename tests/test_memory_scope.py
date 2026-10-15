"""Personalization should serve a question, not choose its topic."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.memory_context import select_memory
from jarvis import learning, profile, vectormem
from jarvis.observer import DialogObserver

PROFILE = {"name": "Алексей", "default_city": "Нижний Новгород"}
FACTS = {"любимая игра": "Дота", "любимый фильм": "Матрица", "работа": "разработчик"}


@pytest.mark.parametrize(
    "query",
    [
        None,
        "",
        "Расскажи что-нибудь",
        "Расскажи мне что-нибудь",
        "Расскажи что-нибудь интересное",
        "Что нового?",
        "Сколько будет два плюс два?",
        "Я не понял",
        "Мне непонятно",
        "Какие есть города в России?",
    ],
)
def test_no_unsolicited_personalization(query):
    s = select_memory(query, PROFILE, FACTS)
    assert not s.profile and not s.facts


@pytest.mark.parametrize(
    "query,key",
    [
        ("Как меня зовут?", "name"),
        ("Какое у меня имя?", "name"),
        ("В каком городе я живу?", "default_city"),
        ("Что есть рядом со мной?", "default_city"),
    ],
)
def test_profile_is_scoped(query, key):
    assert select_memory(query, PROFILE, FACTS).profile == {key: PROFILE[key]}


def test_recommendations_do_not_leak_unrelated_preferences():
    s = select_memory("Посоветуй мне фильм", PROFILE, FACTS)
    assert s.facts == {"любимый фильм": "Матрица"}
    assert not s.profile


def test_explicit_memory_overview_is_bounded():
    facts = {f"факт {i}": f"значение {i}" for i in range(100)}
    s = select_memory("Что ты запомнил обо мне?", PROFILE, facts)
    assert s.profile == PROFILE
    assert len(s.facts) == 5
    assert len(facts) == 100


def test_observer_does_not_feed_its_own_answers_into_extraction():
    observer = DialogObserver.__new__(DialogObserver)
    observer.batch_size = 20
    observer.brain = SimpleNamespace(_request=Mock(return_value="{}"))
    observer._apply = Mock()
    observer._extract(
        [
            {"role": "user", "text": "Расскажи что-нибудь"},
            {"role": "assistant", "text": "Ты живёшь в Казани"},
        ]
    )
    dialog = observer.brain._request.call_args.args[0][1]["content"]
    assert "Расскажи что-нибудь" in dialog
    assert "Казани" not in dialog


def test_assistant_only_batch_is_not_extracted():
    observer = DialogObserver.__new__(DialogObserver)
    observer.batch_size = 20
    observer.brain = SimpleNamespace(_request=Mock())
    observer._extract([{"role": "assistant", "text": "Ты программист"}])
    observer.brain._request.assert_not_called()


def test_rag_cannot_reintroduce_disallowed_keys(monkeypatch):
    monkeypatch.setattr(vectormem, "_enabled", lambda: True)
    monkeypatch.setattr(vectormem, "_facts", lambda: {**FACTS, "город": "Казань"})
    monkeypatch.setattr(
        vectormem,
        "search",
        lambda *a, **kw: [
            {"key": "работа", "value": "разработчик", "score": 0.99},
            {"key": "любимый фильм", "value": "Матрица", "score": 0.95},
        ],
    )
    text = vectormem.build_prompt_block(
        "посоветуй мне фильм", k=1, allowed_keys={"любимый фильм"}
    )
    assert "разработчик" not in text
    assert "Матрица" in text


def test_generic_context_neither_exposes_nor_deletes_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "PROFILES_DIR", tmp_path / "profiles")
    profile._cache_invalidate()
    try:
        profile.set("name", PROFILE["name"])
        profile.set("default_city", PROFILE["default_city"])
        learning.add_fact("работа", "разработчик")
        learning.add_correction("слава", "открой браузер")
        assert learning.build_context(query="Расскажи мне что-нибудь") == ""
        assert profile.get("default_city") == PROFILE["default_city"]
        assert learning.all_facts()["работа"] == "разработчик"
        assert learning.find_correction("слава") == "открой браузер"
    finally:
        profile._cache_invalidate()


def test_generic_query_never_calls_vector_retriever(monkeypatch):
    from jarvis.brain import Brain, CHAT_SYSTEM

    b = Brain.__new__(Brain)
    monkeypatch.setattr(learning, "all_facts", lambda: FACTS)
    monkeypatch.setattr(profile, "get", lambda k, *a: PROFILE.get(k))
    retrieve = Mock(side_effect=AssertionError("retrieval was not requested"))
    monkeypatch.setattr(vectormem, "build_prompt_block", retrieve)
    text = b._system_with_context(CHAT_SYSTEM, "Расскажи мне что-нибудь")
    retrieve.assert_not_called()
    assert "Нижний Новгород" not in text
    assert "Матрица" not in text
