"""Отбор фактов в system-промпт (jarvis.brain._system_with_context).

Векторная память подмешивает только релевантные запросу факты. Если она
выключена или не уверена — в промпт идут ВСЕ факты, как раньше: фича не
должна ухудшать ответы. Проверяем развилку без сети и без Ollama.

Проверяем:
    - выключено → блок памяти пуст, факты идут целиком (как до фичи);
    - включено и есть отбор → в промпте только отобранные факты;
    - build_context получает include_facts=False, чтобы факты не дублировались;
    - нет запроса (query=None) → отбора нет, факты целиком.
"""

import pytest

from jarvis import learning, profile, vectormem
from jarvis.brain import CHAT_SYSTEM, Brain
from jarvis.config import Config

FACTS = {"город": "Казань", "работа": "программист",
         "любимая игра": "Дота", "любимый фильм": "Матрица"}


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


def test_disabled_keeps_all_facts(brain, cfg):
    """Фича выключена (дефолт) — промпт не отличается от того, что был до неё."""
    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")

    for value in FACTS.values():
        assert value in prompt


def test_no_query_keeps_all_facts(brain):
    """Запроса нет (онбординг, разбор команды) — отбирать нечего."""
    prompt = brain._system_with_context(CHAT_SYSTEM)

    for value in FACTS.values():
        assert value in prompt


def test_rag_block_replaces_full_fact_list(brain, cfg, monkeypatch):
    """Память отобрала факты — остальные в промпт не идут."""
    cfg.set("memory_rag_enabled", True)
    seen = {}

    def _fake_block(query, k=None):
        seen["query"] = query
        return "Факты о пользователе (отобраны по смыслу запроса):\n- город: Казань\n"

    monkeypatch.setattr(vectormem, "build_prompt_block", _fake_block)

    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")

    assert seen["query"] == "какой у меня город"
    assert "Казань" in prompt
    assert "Матрица" not in prompt
    assert "программист" not in prompt


def test_facts_are_not_duplicated(brain, cfg, monkeypatch):
    """Когда память отобрала факты, build_context их уже не добавляет."""
    cfg.set("memory_rag_enabled", True)
    monkeypatch.setattr(vectormem, "build_prompt_block",
                        lambda query, k=None: "Факты о пользователе:\n- город: Казань\n")

    calls = []
    original = learning.build_context
    monkeypatch.setattr(learning, "build_context",
                        lambda include_facts=True: calls.append(include_facts) or original(include_facts))

    brain._system_with_context(CHAT_SYSTEM, "какой у меня город")

    assert calls == [False]


def test_build_context_include_facts_flag(cfg):
    """include_facts=False убирает блок фактов, но профиль и коррекции остаются."""
    vectormem.set_config(cfg)
    for key, value in FACTS.items():
        learning.add_fact(key, value)

    with_facts = learning.build_context()
    without = learning.build_context(include_facts=False)

    assert "Казань" in with_facts
    assert "Казань" not in without


def test_broken_memory_does_not_break_prompt(brain, cfg, monkeypatch):
    """Падение памяти не должно ломать диалог — факты просто идут как раньше."""
    cfg.set("memory_rag_enabled", True)

    def _boom(query, k=None):
        raise RuntimeError("память сломалась")

    monkeypatch.setattr(vectormem, "build_prompt_block", _boom)

    prompt = brain._system_with_context(CHAT_SYSTEM, "какой у меня город")

    assert "Казань" in prompt
    assert "Матрица" in prompt
