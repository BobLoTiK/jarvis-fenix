"""Стражи раскладки GUI: правила, которые не видно в юнит-тестах.

Проверяются на собранном дереве вкладок:
- в `Row(wrap=True)` не должно быть детей с `expand` — Flutter падает на
  ParentDataWidget, и вместо содержимого рисуется серый прямоугольник
  (так сломалось подтверждение удаления команды 11.11.2026);
- ни один контрол не должен оказаться в двух местах дерева одновременно —
  Flet-контрол живёт в одном родителе, второй родитель ломает отрисовку.
"""

import importlib.util
from types import SimpleNamespace as NS

import pytest

if importlib.util.find_spec("flet") is None:
    pytest.skip("flet не установлен — тесты GUI пропущены", allow_module_level=True)

import flet as ft  # noqa: E402

from jarvis import gui as module  # noqa: E402
from jarvis import mood, profile  # noqa: E402
from jarvis.config import Config  # noqa: E402


def _walk(control, seen=None):
    if control is None:
        return
    if seen is None:
        seen = set()
    key = id(control)
    if key in seen:
        return
    seen.add(key)
    yield control
    yield from _walk(getattr(control, "content", None), seen)
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child, seen)


@pytest.fixture()
def window(tmp_path):
    gui = module.FenixGUI(None, Config(tmp_path / "config.json"))
    page = NS(add=lambda *a, **k: None, update=lambda *a, **k: None,
              window=NS(width=1100, height=760), run_task=lambda *a, **k: None,
              overlay=[])
    gui._page = page
    gui._build_ui(page)
    yield gui
    gui.close_palette()
    gui.stop()
    gui._rail.dispose()
    profile.unsubscribe(gui._on_profile_switch)
    mood.unsubscribe(gui._on_mood_change)
    module._apply_palette("dark")


def test_no_expand_inside_wrapped_rows(window):
    offenders = []
    for tab, control in window._tabs.items():
        for node in _walk(control):
            if isinstance(node, ft.Row) and node.wrap:
                for child in node.controls:
                    if getattr(child, "expand", None):
                        offenders.append((tab, type(child).__name__,
                                          str(getattr(child, "value", ""))[:40]))
    assert offenders == []


def test_controls_are_not_shared_between_parents(window):
    visited = set()
    repeated = []

    def visit(control):
        if control is None or not isinstance(control, ft.Control):
            return
        key = id(control)
        if key in visited:
            repeated.append(type(control).__name__)
            return
        visited.add(key)
        visit(getattr(control, "content", None))
        for child in getattr(control, "controls", None) or []:
            visit(child)

    for control in window._tabs.values():
        visit(control)
    assert repeated == []


def test_composer_field_is_single_and_focusable(window):
    """Поле ввода одно, не disabled и не read_only: иначе в него не попасть."""
    roots = [window._root, *window._tabs.values()]
    found = [node for root in roots for node in _walk(root)
             if isinstance(node, ft.TextField)]
    assert found.count(window._input_field) == 1
    assert window._input_field.disabled is False
    assert window._input_field.read_only is False
