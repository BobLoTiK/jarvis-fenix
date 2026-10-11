"""Тесты jarvis.persona — стиль, tone, prompt-блок."""

import time
from unittest.mock import patch

from jarvis import persona


# =================================================================
# get / set / defaults
# =================================================================

def test_get_default_persona():
    """Пустой профиль → дефолт с tone=auto."""
    with patch("jarvis.profile.get", return_value=None):
        p = persona.get()
    assert p["assistant_name"] == "Феникс"
    assert p["speech_style"] == "friendly"
    assert p["tone"] == "auto"


def test_get_invalid_tone_falls_back():
    """Мусор в tone → auto."""
    with patch("jarvis.profile.get", return_value={"tone": "banana"}):
        p = persona.get()
    assert p["tone"] == "auto"


def test_set_field_valid():
    saved = {}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        ok = persona.set_field("tone", "unrestricted")
        assert ok
        assert saved["persona"]["tone"] == "unrestricted"


def test_set_field_invalid():
    """Неизвестный ключ → False."""
    ok = persona.set_field("banana", "x")
    assert not ok


# =================================================================
# normalize_tone
# =================================================================

def test_normalize_tone_direct():
    assert persona.normalize_tone("auto") == "auto"
    assert persona.normalize_tone("polite") == "polite"
    assert persona.normalize_tone("unrestricted") == "unrestricted"


def test_normalize_tone_aliases():
    assert persona.normalize_tone("говори проще") == "auto"
    assert persona.normalize_tone("верни цензуру") == "polite"
    assert persona.normalize_tone("без тормозов") == "unrestricted"
    assert persona.normalize_tone("можно материться") == "unrestricted"


def test_normalize_tone_unknown():
    assert persona.normalize_tone("банан") is None


# =================================================================
# set_tone
# =================================================================

def test_set_tone_valid():
    saved = {}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        reply = persona.set_tone("unrestricted")
    assert "не стесняется" in reply
    assert saved["persona"]["tone"] == "unrestricted"


def test_set_tone_fallback():
    """Мусор → auto."""
    saved = {}

    def fake_get(key, default=None):
        return saved.get(key, default)

    def fake_set(key, value):
        saved[key] = value
        return True

    with patch("jarvis.profile.get", side_effect=fake_get), \
         patch("jarvis.profile.set", side_effect=fake_set):
        persona.set_tone("банан")
    assert saved["persona"]["tone"] == "auto"


# =================================================================
# build_prompt_block
# =================================================================

def test_build_prompt_block_auto():
    """auto → есть инструкция «подстраивайся»."""
    with patch("jarvis.profile.get", return_value={"tone": "auto"}):
        block = persona.build_prompt_block()
    assert "подстраивайся" in block.lower()
    assert "матерится" in block.lower()


def test_build_prompt_block_polite():
    """polite → явно без мата."""
    with patch("jarvis.profile.get", return_value={"tone": "polite"}):
        block = persona.build_prompt_block()
    assert "вежливый" in block.lower()
    assert "без мата" in block.lower()


def test_build_prompt_block_unrestricted():
    """unrestricted → можно мат."""
    with patch("jarvis.profile.get", return_value={"tone": "unrestricted"}):
        block = persona.build_prompt_block()
    assert "не стесняйся" in block.lower()
    assert "матерится" in block.lower()


def test_build_prompt_block_empty():
    """Пустой профиль — блок всё равно непустой (стиль + tone)."""
    with patch("jarvis.profile.get", return_value=None):
        block = persona.build_prompt_block()
    assert block
    assert "Персона" in block


# =================================================================
# describe
# =================================================================

def test_describe():
    with patch("jarvis.profile.get", return_value={"tone": "auto"}):
        desc = persona.describe()
    assert "феникс" in desc.lower()
    assert "подстраивается" in desc.lower()