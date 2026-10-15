"""Query-scoped memory: unavailable retrieval never means send all facts."""

import pytest

from jarvis import learning, profile, vectormem
from jarvis.brain import CHAT_SYSTEM, Brain
from jarvis.config import Config

FACTS = {
    "город": "Казань",
    "работа": "программист",
    "любимая игра": "Дота",
    "любимый фильм": "Матрица",
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(vectormem, "_config", None)
    monkeypatch.setattr(vectormem, "warmup_async", lambda: None)
    profile._cache_invalidate()
    vectormem.reset_for_tests()
    yield
    vectormem.reset_for_tests()
    profile._cache_invalidate()


@pytest.fixture()
def cfg(tmp_path):
    return Config(tmp_path / "config.json")


def _brain(cfg, monkeypatch):
    """Brain без сети: сеть не пингуем, ollama serve не поднимаем."""
    monkeypatch.setattr(Brain, "_ping", lambda self: False)
    monkeypatch.setattr(Brain, "_try_start", lambda self: False)
    return Brain(config=cfg)


@pytest.fixture()
def brain(cfg, monkeypatch):
    b = _brain(cfg, monkeypatch)
    vectormem.set_config(cfg)
    for key, value in FACTS.items():
        assert learning.add_fact(key, value)
    return b


@pytest.mark.parametrize(
    "query",
    [
        None,
        "Расскажи что-нибудь",
        "Расскажи мне что-нибудь",
        "Почему небо голубое?",
        "Расскажи о Казани",
    ],
)
def test_generic_queries_do_not_inject_personal_facts(brain, query):
    prompt = brain._system_with_context(CHAT_SYSTEM, query)
    assert all(value not in prompt for value in FACTS.values())


def test_disabled_memory_keeps_only_requested_facts(brain):
    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")
    assert "Казань" in prompt
    assert all(value not in prompt for key, value in FACTS.items() if key != "город")


def test_rag_block_replaces_selected_fact_list(brain, cfg, monkeypatch):
    cfg.set("memory_rag_enabled", True)
    seen = {}

    def fake(query, k=None, allowed_keys=None):
        seen["allowed"] = allowed_keys
        return "Факты о пользователе:\n- город: Казань\n"

    monkeypatch.setattr(vectormem, "build_prompt_block", fake)
    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")
    assert seen["allowed"] == {"город"}
    assert prompt.count("Казань") == 1
    assert "Матрица" not in prompt


def test_facts_are_not_duplicated(brain, cfg, monkeypatch):
    cfg.set("memory_rag_enabled", True)
    monkeypatch.setattr(
        vectormem,
        "build_prompt_block",
        lambda *a, **kw: "Факты о пользователе:\n- город: Казань\n",
    )
    calls = []
    original = learning.build_context

    def spy(include_facts=True, **kw):
        calls.append(include_facts)
        return original(include_facts, **kw)

    monkeypatch.setattr(learning, "build_context", spy)
    brain._system_with_context(CHAT_SYSTEM, "какой у меня город")
    assert calls == [False]


def test_build_context_include_facts_flag(brain):
    assert "Казань" in learning.build_context(query="какой у меня город")
    assert "Казань" not in learning.build_context(False, query="какой у меня город")
    assert learning.build_context() == ""


@pytest.mark.parametrize("broken", [False, True])
def test_failed_or_empty_rag_never_sends_everything(brain, cfg, monkeypatch, broken):
    cfg.set("memory_rag_enabled", True)

    def block(*a, **kw):
        if broken:
            raise RuntimeError("unavailable")
        return ""

    monkeypatch.setattr(vectormem, "build_prompt_block", block)
    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")
    assert "Казань" in prompt
    assert "Матрица" not in prompt
    assert "программист" not in prompt
    assert learning.all_facts() == FACTS
