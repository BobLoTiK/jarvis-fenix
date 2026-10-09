"""Тесты jarvis.mood — состояние, детекция, decay, влияние."""

import time
from unittest.mock import patch

from jarvis import mood


# =================================================================
# get / set / get_state
# =================================================================

def test_get_default_neutral():
    """Свежий профиль → neutral."""
    # Подменяем profile.get, чтобы не трогать реальный profile.json
    with patch("jarvis.profile.get", return_value=None):
        m = mood.get()
    assert m["state"] == "neutral"
    assert m["reason"] == ""


def test_set_mood_valid():
    """set_mood с валидным состоянием сохраняет."""
    saved = {}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        ok = mood.set_mood("happy", reason="test")
        assert ok
        assert saved["mood"]["state"] == "happy"
        assert saved["mood"]["reason"] == "test"


def test_set_mood_invalid():
    """Невалидное состояние → False, ничего не сохраняется."""
    with patch("jarvis.profile.set") as mock_set:
        ok = mood.set_mood("ecstatic", reason="test")
        assert not ok
        mock_set.assert_not_called()


def test_set_mood_no_change():
    """Повторная установка того же состояния с тем же reason → no-op."""
    saved = {
        "mood": {"state": "happy", "since": 100.0, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        ok = mood.set_mood("happy", reason="test")
        assert ok
        mock_set.assert_not_called()


# =================================================================
# Подписки
# =================================================================

def test_subscribe_and_notify():
    """Подписчик вызывается при смене состояния."""
    calls = []

    def cb(old, new):
        calls.append((old, new))

    mood.subscribe(cb)
    try:
        saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

        def fake_get(key, default=None):
            return saved.get(key, default)

        def fake_set(key, value):
            saved[key] = value
            return True

        with patch("jarvis.profile.get", side_effect=fake_get), \
             patch("jarvis.profile.set", side_effect=fake_set):
            mood.set_mood("happy", reason="test")
    finally:
        mood.unsubscribe(cb)

    assert calls == [("neutral", "happy")]


def test_unsubscribe():
    """После unsubscribe подписчик не вызывается."""
    calls = []

    def cb(old, new):
        calls.append((old, new))

    mood.subscribe(cb)
    mood.unsubscribe(cb)

    saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        mood.set_mood("happy", reason="test")

    assert calls == []


# =================================================================
# Детекция из текста
# =================================================================

def test_detect_praise():
    assert mood.detect("спасибо, ты лучший") == "happy"
    assert mood.detect("молодец!") == "happy"
    assert mood.detect("отлично справился") == "happy"


def test_detect_excited():
    assert mood.detect("ура, получилось!") == "excited"
    assert mood.detect("вау, круто") == "excited"


def test_detect_rude():
    assert mood.detect("ты тупой") == "annoyed"
    assert mood.detect("идиот какой-то") == "annoyed"
    assert mood.detect("дурак") == "annoyed"


def test_detect_tired():
    assert mood.detect("я устал") == "tired"
    assert mood.detect("спать хочу") == "tired"


def test_detect_none():
    assert mood.detect("открой стим") is None
    assert mood.detect("") is None
    assert mood.detect("какая погода") is None


def test_detect_rude_beats_praise():
    """«спасибо, ты тупой» → annoyed, а не happy."""
    assert mood.detect("спасибо, ты тупой") == "annoyed"


# =================================================================
# apply_from_text
# =================================================================

def test_apply_from_text_changes():
    """apply_from_text меняет mood и возвращает True."""
    saved = {"mood": {"state": "neutral", "since": 100.0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        changed = mood.apply_from_text("спасибо!")

    assert changed
    assert saved["mood"]["state"] == "happy"


def test_apply_from_text_no_change():
    """Без триггеров → False, mood не меняется."""
    with patch("jarvis.profile.set") as mock_set:
        changed = mood.apply_from_text("открой стим")
        assert not changed
        mock_set.assert_not_called()


# =================================================================
# Decay
# =================================================================

def test_decay_old_state():
    """Старое состояние (>5 мин) → neutral."""
    saved = {
        "mood": {"state": "happy", "since": time.time() - 600, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        changed = mood.decay(max_age_sec=300)

    assert changed
    assert saved["mood"]["state"] == "neutral"


def test_decay_fresh_state():
    """Свежее состояние → не трогаем."""
    saved = {
        "mood": {"state": "happy", "since": time.time() - 60, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        changed = mood.decay(max_age_sec=300)

    assert not changed
    mock_set.assert_not_called()


def test_decay_neutral():
    """neutral не трогаем никогда."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set") as mock_set:
        changed = mood.decay()

    assert not changed
    mock_set.assert_not_called()


# =================================================================
# Влияние на систему
# =================================================================

def test_effective_rate_excited():
    """excited → +10%."""
    with patch("jarvis.mood.get_state", return_value="excited"):
        assert mood.effective_rate(1.0) == 1.1


def test_effective_rate_tired():
    """tired → -10%."""
    with patch("jarvis.mood.get_state", return_value="tired"):
        assert mood.effective_rate(1.0) == 0.9


def test_effective_rate_neutral():
    """neutral → без изменений."""
    with patch("jarvis.mood.get_state", return_value="neutral"):
        assert mood.effective_rate(1.15) == 1.15


def test_color_all_states():
    """Каждое состояние имеет цвет."""
    for state in mood.STATES:
        with patch("jarvis.mood.get_state", return_value=state):
            c = mood.color()
            assert c.startswith("#")
            assert len(c) == 7


# =================================================================
# Prompt block
# =================================================================

def test_build_prompt_block_neutral():
    """neutral → пустая строка (не засоряем промпт)."""
    with patch("jarvis.mood.get_state", return_value="neutral"):
        assert mood.build_prompt_block() == ""


def test_build_prompt_block_annoyed():
    """annoyed → есть блок с подсказкой."""
    with patch("jarvis.mood.get_state", return_value="annoyed"):
        block = mood.build_prompt_block()
        assert "annoyed" in block
        assert "не извиняйся" in block.lower() or "ирони" in block.lower()


# =================================================================
# Описание
# =================================================================

def test_describe_neutral():
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        desc = mood.describe()

    assert "Спокойное" in desc


def test_describe_with_time():
    saved = {
        "mood": {"state": "happy", "since": time.time() - 120, "reason": "test"},
    }

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        desc = mood.describe()

    assert "Хорошее" in desc
    assert "2 минут" in desc


# =================================================================
# Команды
# =================================================================

def test_handle_mood_command_query():
    """«как настроение» → describe()."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    with patch("jarvis.profile.get", side_effect=fake_get):
        reply = mood.handle_mood_command("как настроение")

    assert reply is not None
    assert "Спокойное" in reply or "Настроение" in reply


def test_handle_mood_command_cheer_up():
    """«не грусти» → happy."""
    saved = {"mood": {"state": "neutral", "since": 0, "reason": ""}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        reply = mood.handle_mood_command("не грусти")

    assert reply is not None
    assert saved["mood"]["state"] == "happy"


def test_handle_mood_command_calm_down():
    """«успокойся» → neutral."""
    saved = {"mood": {"state": "annoyed", "since": 100.0, "reason": "rude"}}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        reply = mood.handle_mood_command("успокойся")

    assert reply is not None
    assert saved["mood"]["state"] == "neutral"


def test_handle_mood_command_none():
    """Не наша команда → None."""
    assert mood.handle_mood_command("открой стим") is None
    assert mood.handle_mood_command("какая погода") is None