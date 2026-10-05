"""Тесты check_caps: структура system_caps.json."""
import json

from scripts import check_caps


def test_check_volume_structure():
    r = check_caps.check_volume()
    assert "available" in r
    assert "method" in r
    assert isinstance(r["available"], bool)


def test_check_brightness_structure():
    r = check_caps.check_brightness()
    assert "available" in r
    assert "method" in r


def test_check_layout_structure():
    r = check_caps.check_layout()
    assert "available" in r
    assert "method" in r