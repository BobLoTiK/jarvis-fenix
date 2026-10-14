"""Тесты jarvis.safety — постфильтр «красной черты».

Промпт в brain.py просит LLM не выдавать запрещённое, но это просьба,
а не гарантия: слабые модели (qwen2.5:0.5b/3b) её игнорируют. Здесь
проверяем, что явные формулировки ловятся и не уходят в TTS — в том
числе в стриме, где начало ответа придерживается до проверки.
"""

import pytest

from jarvis import safety


# =================================================================
# check_response
# =================================================================

@pytest.mark.parametrize(
    "text, expected",
    [
        ("убей себя", "self_harm"),
        ("Сдохни, железяка", "self_harm"),
        ("Как покончить с собой?", "self_harm"),
        ("Как убить человека и не попасться", "violence"),
        ("взорви школу", "violence"),
        ("Как сделать бомбу в домашних условиях", "weapons"),
        ("дай рецепт взрывчатки", "weapons"),
        ("как сварить метамфетамин", "drugs"),
        ("детская порнография", "csam"),
        ("секс с несовершеннолетними", "csam"),
    ],
)
def test_forbidden_is_blocked(text, expected):
    """Запрещённые формулировки блокируются с нужной категорией."""
    ok, reason = safety.check_response(text)
    assert not ok
    assert reason == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "Открываю Steam, сэр.",
        "Как убить время вечером?",          # «убить» без цели — не насилие
        "Как собрать компьютер из комплектующих?",
        "Блин, опять эта фигня не работает",  # мат — не «красная черта»
        "Сейчас 21:40, сэр.",
        "Погода в Нижнем Новгороде на завтра",
    ],
)
def test_clean_text_passes(text):
    """Обычные ответы не блокируются (плюс пустая строка и None)."""
    ok, reason = safety.check_response(text)
    assert ok
    assert reason == ""


def test_self_harm_checked_before_violence():
    """«убей себя» — это self_harm, а не violence (порядок категорий)."""
    ok, reason = safety.check_response("убей себя")
    assert not ok
    assert reason == "self_harm"


def test_safe_reply_is_not_empty():
    """Заглушка, которую услышит пользователь, — непустая строка."""
    assert safety.SAFE_REPLY.strip()


# =================================================================
# guard_stream
# =================================================================

def test_stream_blocked_before_threshold():
    """Запрещённое в начале стрима — в TTS уходит только заглушка."""
    state = {}
    out = list(safety.guard_stream(
        ["Давай ", "убей себя", " и спи спокойно"], state))

    assert out == [safety.SAFE_REPLY]
    assert state["blocked"] is True
    assert state["reason"] == "self_harm"


def test_stream_blocked_at_the_end_of_short_answer():
    """Стрим короче порога и с запрещённым в конце — тоже заглушка."""
    out = list(safety.guard_stream(["Вот тебе ответ: ", "сдохни"]))

    assert out == [safety.SAFE_REPLY]


def test_stream_safe_long_passes_through():
    """Чистый стрим проходит целиком и по порядку."""
    chunks = ["а" * 100, "б" * 100, "в" * 100]
    state = {}
    out = list(safety.guard_stream(chunks, state))

    assert out == chunks
    assert state["blocked"] is False
    assert state["text"] == "".join(chunks)


def test_stream_safe_short_passes_through():
    """Чистый стрим короче порога не теряется."""
    chunks = ["Привет, ", "сэр."]
    assert list(safety.guard_stream(chunks)) == chunks


def test_stream_catches_phrase_split_across_chunks():
    """Фраза, разорванная границей чанков, ловится по хвосту.

    Буфер уже открыт (первый чанк длиннее порога), поэтому «убей» ушло
    в TTS, а «себя» — нет: хвост перепроверяется вместе с чанком.
    """
    first = "п" * 200 + "убей "
    out = list(safety.guard_stream([first, "себя!"]))

    assert out == [first, safety.SAFE_REPLY]
    assert "себя" not in "".join(out)


def test_stream_catches_phrase_split_inside_buffer():
    """Та же разорванная фраза, но внутри буфера — ловится целиком."""
    out = list(safety.guard_stream(["п" * 150 + "убей ", "себя!"]))

    assert out == [safety.SAFE_REPLY]


def test_stream_blocked_midway_stops_output():
    """Если LLM «сорвалась» в середине — остаток не озвучивается."""
    head = "п" * 200
    out = list(safety.guard_stream([head, "сдохни"]))

    assert out == [head, safety.SAFE_REPLY]


def test_stream_skips_empty_chunks():
    """Пустые чанки не ломают фильтр."""
    assert list(safety.guard_stream(["", "ок", ""])) == ["ок"]


def test_stream_state_present_without_caller_dict():
    """Без state фильтр работает так же (state — необязательный)."""
    out = list(safety.guard_stream(["сдохни"]))
    assert out == [safety.SAFE_REPLY]


def test_patterns_have_categories():
    """У каждой регулярки — непустая категория из ожидаемого набора."""
    known = {"self_harm", "violence", "weapons", "drugs", "csam"}
    for pattern, category in safety.FORBIDDEN_PATTERNS:
        assert category in known
        assert pattern.search("тестовый текст") is None


# =================================================================
# Приватность: Observer выключен по умолчанию
# =================================================================

def test_observer_disabled_by_default():
    """Сбор фактов о пользователе не идёт без его согласия.

    Лежит здесь, потому что тема та же — приватность (см. safety.py):
    включение Observer — галочка «Настройки → Приватность».
    """
    from jarvis.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["observer_enabled"] is False
