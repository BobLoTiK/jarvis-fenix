# -*- coding: utf-8 -*-
"""Дизайн-токены GUI: отступы, радиусы, типографика, поверхности, контраст.

Числа, которые раньше писались по месту (11/12/13 px, 8/9/11/12/16 px), живут
здесь одним набором. Шкала короткая намеренно: пять шагов воздуха, три радиуса
и шесть ролей текста — этого достаточно, чтобы экраны выглядели одинаково.
"""
from __future__ import annotations

import flet as ft

# --- шкала -----------------------------------------------------------------

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 8, "md": 12, "lg": 18, "pill": 999}
STROKE = 1

# Роли текста: размер и вес по роли, а не «на глаз». Межстрочный оставляем
# рендереру: у ft.Text нет межстрочного интервала, а height — высота виджета.
TYPE = {
    "display": {"size": 30, "weight": ft.FontWeight.BOLD},
    "title": {"size": 21, "weight": ft.FontWeight.W_600},
    "subtitle": {"size": 15, "weight": ft.FontWeight.W_500},
    "body": {"size": 14, "weight": ft.FontWeight.NORMAL},
    "label": {"size": 13, "weight": ft.FontWeight.NORMAL},
    "caption": {"size": 11, "weight": ft.FontWeight.NORMAL},
}


def text(kind: str, value, *, color, **overrides) -> ft.Text:
    """Текст нужной роли: `text("title", "Привет", color=P.text)`."""
    spec = dict(TYPE.get(kind, TYPE["body"]))
    spec.update(overrides)
    return ft.Text(value, color=color, **spec)


# --- поверхности -----------------------------------------------------------


def shadow(palette, *, raised: bool = False) -> ft.BoxShadow:
    """Тень под поверхностью: обычная и «приподнятая» для акцентов."""
    if raised:
        return ft.BoxShadow(blur_radius=32, spread_radius=-4, offset=ft.Offset(0, 10),
                            color=ft.Colors.with_opacity(.28, "#000000"))
    return ft.BoxShadow(blur_radius=18, spread_radius=-6, offset=ft.Offset(0, 4),
                        color=ft.Colors.with_opacity(.16, "#000000"))


def card(palette, *, padding=None, radius: int | None = None, raised: bool = False,
         border: bool = True) -> ft.Container:
    """Карточка-поверхность: фон, тонкая рамка и тень одного уровня."""
    space = RADIUS["md"] if radius is None else radius
    return ft.Container(
        bgcolor=palette.bg_card,
        border_radius=space,
        border=(ft.Border.all(STROKE, ft.Colors.with_opacity(.45, palette.border))
                if border else None),
        shadow=shadow(palette, raised=raised),
        padding=padding)


def pill(palette, *, padding=None) -> ft.Container:
    """Пилюля-контейнер для групп контролов (тема, чипы статуса)."""
    return ft.Container(
        content=None,
        padding=padding if padding is not None else ft.Padding.symmetric(horizontal=6, vertical=4),
        border_radius=RADIUS["pill"],
        bgcolor=palette.sidebar,
        border=ft.Border.all(STROKE, ft.Colors.with_opacity(.5, palette.border)))


# --- контраст --------------------------------------------------------------


def _channels(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    if len(value) == 8:  # ARGB из FtColors.with_opacity
        value = value[2:]
    if len(value) != 6:
        raise ValueError(f"ожидался цвет #rrggbb, получено {color!r}")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def relative_luminance(color: str) -> float:
    """Относительная яркость по WCAG 2.1."""
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= .03928 else ((channel + .055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in _channels(color))
    return .2126 * r + .7152 * g + .0722 * b


def contrast(color_a: str, color_b: str) -> float:
    """Коэффициент контраста текста к фону (WCAG): 4.5 — порог обычного текста."""
    la, lb = relative_luminance(color_a), relative_luminance(color_b)
    high, low = max(la, lb), min(la, lb)
    return (high + .05) / (low + .05)
