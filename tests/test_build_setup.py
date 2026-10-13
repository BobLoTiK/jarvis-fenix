"""Тесты scripts.build_setup — версия установщика и мягкий пропуск шага caps.

Проверяем то, от чего зависит CI-релиз (см. .github/workflows/release.yml):
версия из тега уходит в Inno Setup через /DMyAppVersion, а шаг
system_caps.json на раннере без pycaw просто пропускается.
"""

import importlib.util

from scripts import build_setup


def test_parse_version_space():
    """`--version 1.0.2` → 1.0.2."""
    assert build_setup.parse_version(["--version", "1.0.2"]) == "1.0.2"


def test_parse_version_equals():
    """`--version=1.0.2` → 1.0.2."""
    assert build_setup.parse_version(["--version=1.0.2"]) == "1.0.2"


def test_parse_version_strips_spaces():
    """Пробелы вокруг версии обрезаются."""
    assert build_setup.parse_version(["--version", "  1.0.2  "]) == "1.0.2"


def test_parse_version_absent():
    """Без --version → None (версия берётся из installer.iss)."""
    assert build_setup.parse_version(["build_setup.py", "--run"]) is None


def test_parse_version_without_value():
    """`--version` последним аргументом → None, не IndexError."""
    assert build_setup.parse_version(["--version"]) is None


def test_caps_available_with_modules(monkeypatch):
    """pycaw и screen_brightness_control есть (локальная сборка) → True."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert build_setup.caps_available() is True


def test_caps_available_without_modules(monkeypatch):
    """Модулей нет (CI-раннер) → False: шаг system_caps.json пропускается."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert build_setup.caps_available() is False


def test_installer_version_is_overridable_and_matches_package():
    """installer.iss: версия по умолчанию = jarvis.__version__, но с #ifndef."""
    from jarvis import __version__

    text = (build_setup.BASE / "installer.iss").read_text(encoding="utf-8")
    assert "#ifndef MyAppVersion" in text, "версия должна переопределяться /D"
    assert f'#define MyAppVersion "{__version__}"' in text, "рассинхрон версий"
