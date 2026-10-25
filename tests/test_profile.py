"""Профили: защита активного профиля и границы удаления.

Этих тестов не было вообще, поэтому дефект «удали профиль Максим стирает
свой же профиль» дожил до аудита: `delete()` сравнивал `_sanitize(name)` с
`current()`, а тот после `init()` возвращает СЫРОЕ имя Windows-пользователя
(«Максим»), тогда как папка называется `_sanitize(...)` («maksim»).

Проверяем на временной папке: реальные профили в %APPDATA% не трогаем.
`send2trash` подменяем на «не установлен», чтобы временные каталоги
удалялись сразу и не копились в корзине пользователя.
"""

import json
import sys
from pathlib import Path

import pytest

from jarvis import profile


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Профили — во временной папке; активный пользователь — «Максим»."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(profile, "PROFILES_DIR", profiles)
    monkeypatch.setattr(profile, "_cache", {}, raising=False)
    # Кириллица с заглавной буквы — ровно тот случай, который ломал guard.
    monkeypatch.setattr(profile, "_current", "Максим", raising=False)
    # Имитируем отсутствие send2trash: удаление идёт через shutil.rmtree.
    monkeypatch.setitem(sys.modules, "send2trash", None)
    return profiles


def _make(profiles: Path, folder: str) -> Path:
    path = profiles / folder
    path.mkdir()
    (path / "profile.json").write_text(
        json.dumps({"facts": {"city": "Тест"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_active_profile_is_not_deleted_when_name_has_uppercase(sandbox):
    """«удали профиль Максим» не должен стирать активный профиль."""
    active = _make(sandbox, "maksim")

    assert profile.delete("Максим") is False

    assert active.is_dir(), "активный профиль удалён — guard не работает"
    assert json.loads((active / "profile.json").read_text(encoding="utf-8"))


def test_active_profile_guard_works_for_every_spelling(sandbox):
    """Транслит, регистр и уже безопасное имя — всё это один профиль."""
    active = _make(sandbox, "maksim")

    for name in ("максим", "МАКСИМ", "maksim", "Maxim", " максим "):
        assert profile.delete(name) is False, name

    assert active.is_dir()


def test_other_profile_is_deleted(sandbox):
    """Неактивный профиль по-прежнему удаляется."""
    _make(sandbox, "maksim")
    other = _make(sandbox, "test")

    assert profile.delete("test") is True

    assert not other.exists()
    assert (sandbox / "maksim").is_dir()


def test_delete_missing_profile_returns_false(sandbox):
    _make(sandbox, "maksim")

    assert profile.delete("нет_такого") is False


def test_delete_cannot_escape_profiles_dir(sandbox, tmp_path):
    """«../evil» санитизируется в «evil» и не выходит из PROFILES_DIR."""
    outside = tmp_path / "evil"
    outside.mkdir()
    (outside / "keep.txt").write_text("важно", encoding="utf-8")
    _make(sandbox, "evil")

    assert profile.delete("../evil") is True

    assert not (sandbox / "evil").exists()
    assert (outside / "keep.txt").exists(), "удаление вышло за пределы профилей"


def test_profile_dir_uses_sanitized_name(sandbox):
    """Папка текущего профиля — ровно то имя, которое сравнивает delete()."""
    path = profile.profile_dir()

    assert path.name == profile._sanitize("Максим") == "maksim"
