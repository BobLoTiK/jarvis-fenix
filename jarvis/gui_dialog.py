# -*- coding: utf-8 -*-
"""Детали диалога: разделители дней и черновик записи. Без окна и сети."""
from __future__ import annotations

import flet as ft

from jarvis import gui_tokens as T

TODAY = "Сегодня"
YESTERDAY = "Вчера"
MONTHS_GENITIVE = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                   "августа", "сентября", "октября", "ноября", "декабря")


def day_label(record, today=None) -> str:
    """Подпись дня сообщения: «Сегодня», «Вчера» или «8 ноября»."""
    from datetime import date

    raw = (record or {}).get("date")
    try:
        day = date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return ""
    current = today or date.today()
    if day == current:
        return TODAY
    if day == date.fromordinal(current.toordinal() - 1):
        return YESTERDAY
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"


def needs_separator(previous, current, today=None) -> bool:
    """Разделитель нужен, когда день у сообщений разный (или это первое)."""
    now = day_label(current, today)
    if not now:
        return False
    if not previous:
        return True
    return day_label(previous, today) != now


def next_day(today=None):
    """ISO-дата для записи сообщения."""
    from datetime import date

    return (today or date.today()).isoformat()


def typing_bubble(palette) -> ft.Control:
    """Плашка «Феникс печатает…» до первого куска ответа."""
    return ft.Container(
        ft.Row([
            ft.ProgressRing(width=14, height=14, stroke_width=2,
                            color=palette.brand),
            T.text("caption", "Феникс печатает…", color=palette.text_dim),
        ], spacing=8),
        padding=ft.Padding(left=16, right=16, top=6, bottom=6),
        border_radius=T.RADIUS["md"],
        bgcolor=palette.bg_card,
        border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.45, palette.border)),
        margin=ft.Margin(right=32))


def day_separator(palette, label: str) -> ft.Control:
    """Тонкая линия с подписью дня между блоками истории."""
    def line():
        return ft.Container(height=1, expand=True,
                            bgcolor=ft.Colors.with_opacity(.35, palette.border))

    return ft.Row([
        line(),
        ft.Container(T.text("caption", label, color=palette.text_dim),
                     padding=ft.Padding.symmetric(horizontal=10)),
        line(),
    ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)
