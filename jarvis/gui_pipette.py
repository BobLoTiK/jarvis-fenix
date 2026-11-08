# -*- coding: utf-8 -*-
"""Мини-режим «пипетка»: окно 56×56 с птицей, клик разворачивает обратно.

Это не второе окно и не второй процесс: FenixGUI меняет свойства того же окна
и содержимое корня страницы, как вертикальная полоса. Состояние ауры то же
самое (`PhoenixAura`), поэтому показывать «примерно то же» не приходится.
"""
from __future__ import annotations

import flet as ft

from jarvis import gui_tokens as T
from jarvis.gui_vertical import _work_area_tuple

PIP_H = 56
PIP_W = 136  # клиент Flet не даёт окну стать уже ~136 px — делаем пилюлю
PIP_SIZE = PIP_H
PIP_RING = 40


def pipette_window_spec(width=PIP_W, height=PIP_H, workarea=None) -> dict:
    """Свойства мини-окна: без рамки, поверх всех, в правом нижнем углу."""
    w = max(120, min(int(width), 240))
    h = max(48, min(int(height), 120))
    spec = {
        "max_width": w,
        "max_height": h,
        "min_width": w,
        "min_height": h,
        "width": w,
        "height": h,
        "frameless": True,
        "always_on_top": True,
        "movable": True,
        "resizable": False,
        "shadow": True,
    }
    area = _work_area_tuple(workarea)
    if area is not None:
        left, top, right, bottom = area
        spec["left"] = right - w - 12
        spec["top"] = bottom - h - 12
    return spec


def saved_window_spec(window) -> dict:
    """Что запомнить из обычного окна, чтобы вернуть его после пипетки."""
    keys = ("max_width", "max_height", "min_width", "min_height",
            "width", "height", "left", "top", "resizable", "movable",
            "frameless", "always_on_top", "shadow")
    saved = {}
    for key in keys:
        try:
            saved[key] = getattr(window, key, None)
        except Exception:
            saved[key] = None
    return saved


# Порядок важен: клиент Flet применяет размер под текущие ограничения, поэтому
# сначала снимаем/ставим max и min, и только потом width/height. Иначе окно
# остаётся 900×600 (минимум обычного окна), хотя просили 56×56.
SPEC_ORDER = ("max_width", "max_height", "min_width", "min_height",
              "width", "height", "left", "top",
              "frameless", "always_on_top", "movable", "resizable", "shadow")


def apply_window_spec(window, spec: dict) -> dict:
    """Применяет свойства окна в безопасном порядке; None значит «без предела»."""
    applied = {}
    merged = dict(spec or {})
    for key in SPEC_ORDER:
        if key not in merged:
            continue
        value = merged[key]
        if value is None and key not in ("max_width", "max_height"):
            continue
        try:
            setattr(window, key, value)
            applied[key] = value
        except Exception:
            continue
    return applied


def restore_window_spec(window, saved: dict) -> dict:
    """Возвращает сохранённые свойства в правильном порядке."""
    return apply_window_spec(window, saved)


class Pipette(ft.Container):
    """Пилюля с птицей: клик — обратно в обычное окно."""

    def __init__(self, gui):
        from jarvis import gui as ui
        from jarvis.gui_home_fx import PhoenixAura

        super().__init__()
        p = ui.P
        self.gui = gui
        self.ring = ft.Container(
            ui._brand_image("phoenix", 26, "Феникс"), width=PIP_RING, height=PIP_RING,
            border_radius=PIP_RING // 2, alignment=ft.Alignment.CENTER,
            border=ft.Border.all(1, ft.Colors.with_opacity(.35, p.border)),
            bgcolor=ft.Colors.with_opacity(.14, p.sidebar))
        self.aura = PhoenixAura(gui, self.ring, size=PIP_RING,
                                foreground=lambda: bool(getattr(gui, "_pipette_mode", False)))
        self.dot = ft.Container(width=7, height=7, border_radius=4, bgcolor=p.brand)
        self.width = PIP_W
        self.height = PIP_H
        self.border_radius = PIP_H // 2
        self.bgcolor = p.bg_card
        self.border = ft.Border.all(T.STROKE, ft.Colors.with_opacity(.45, p.border))
        self.shadow = T.shadow(p, raised=True)
        self.tooltip = "Феникс: нажмите, чтобы развернуть"
        self.content = ft.Row(
            [ft.Container(self.aura, alignment=ft.Alignment.CENTER), self.dot],
            spacing=6, alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.on_click = lambda e: self.gui.set_pipette_mode(False)

    def apply_state(self, state) -> None:
        try:
            self.aura.set_mode(state)
        except Exception:
            pass
