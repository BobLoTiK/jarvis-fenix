"""Версии установщика, поиск Inno и совпадение с версией пакета."""

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


def test_inno_override(tmp_path, monkeypatch):
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"test")
    monkeypatch.setenv("INNO_SETUP", str(tmp_path))
    assert build_setup.find_iscc() == str(compiler)


def test_versions_reject_injection():
    import pytest
    for value in ('1.0\n/Dfoo', '1.0"', '../1.0', '', 'v1.0'):
        with pytest.raises(ValueError):
            build_setup.validate_version(value)
    assert build_setup.validate_version('1.0.2-ci.1') == '1.0.2-ci.1'


def test_installer_version_is_overridable_and_matches_package():
    """installer.iss: версия по умолчанию = jarvis.__version__, но с #ifndef."""
    from jarvis import __version__

    text = (build_setup.BASE / "installer.iss").read_text(encoding="utf-8")
    assert "#ifndef MyAppVersion" in text, "версия должна переопределяться /D"
    assert f'#define MyAppVersion "{__version__}"' in text, "рассинхрон версий"
