# -*- coding: utf-8 -*-
"""Короткие тосты вместо модальных SnackBar: стек снизу, сами уходят.

Тосты не блокируют ввод и не перекрывают историю: три штуки максимум,
`error` живёт дольше и выделяется цветом. Всё это — обычные контролы Flet в
`page.overlay`, поэтому ни нового потока, ни второго окна нет.
"""
from __future__ import annotations

import asyncio

import flet as ft

from jarvis import gui_tokens as T

LIMIT = 3
DURATION_MS = {"info": 2800, "success": 2600, "error": 6000}
ICONS = {"info": ft.Icons.INFO_OUTLINE, "success": ft.Icons.CHECK_CIRCLE_OUTLINE,
         "error": ft.Icons.ERROR_OUTLINE}


def normalize_kind(kind) -> str:
    return kind if kind in DURATION_MS else "info"


def toast_colors(palette, kind) -> dict:
    """Цвета тоста: рамка/иконка по смыслу, поверхность — карточка."""
    kind = normalize_kind(kind)
    accent = {"info": palette.brand, "success": palette.success,
              "error": palette.error}[kind]
    return {"accent": accent, "surface": palette.bg_card}


class Toasts:
    """Стек тостов внизу окна; устаревшие убираются сами."""

    def __init__(self, gui, limit: int = LIMIT):
        self.gui = gui
        self.limit = max(1, int(limit))
        self.entries: list[ft.Container] = []

    def _page(self):
        return getattr(self.gui, "_page", None)

    def show(self, text: str, kind: str = "info") -> bool:
        """Показать тост. False — если окна/слоя ещё нет (тогда останется _show_status)."""
        page = self._page()
        if page is None or not text:
            return False
        if getattr(page, "overlay", None) is None:
            return False
        from jarvis import gui as ui

        palette = ui.P
        kind = normalize_kind(kind)
        colors = toast_colors(palette, kind)
        entry = ft.Container(
            ft.Row([
                ft.Icon(ICONS[kind], size=16, color=colors["accent"]),
                T.text("label", str(text), color=palette.text),
            ], spacing=10, tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=9),
            border_radius=T.RADIUS["pill"],
            bgcolor=colors["surface"],
            border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.55, colors["accent"])),
            shadow=T.shadow(palette, raised=True))
        entry.width = 320
        self.entries.append(entry)
        while len(self.entries) > self.limit:
            old = self.entries.pop(0)
            self._remove(old)
        page.overlay.append(entry)
        self._place()
        try:
            page.update()
        except Exception:
            pass
        try:
            page.run_task(self._later, entry, DURATION_MS[kind] / 1000)
        except Exception:
            pass
        return True

    def _place(self) -> None:
        """Держит стек по центру снизу, даже если окно поменяло размер."""
        page = self._page()
        window = getattr(page, "window", None)
        width = getattr(window, "width", None) or 1100
        height = getattr(window, "height", None) or 760
        # В полосе у края экрана окно уже 320 px: тост подстраивается, иначе
        # он вылезал за границу и обрезался.
        fit = min(320, max(160, int(width) - 16))
        down = 84
        for entry in self.entries:
            entry.width = fit
            entry.left = max(0, (int(width) - fit) // 2)
        # Позиция по низу считается от последнего: старые выше новых. Отступ
        # больше высоты статус-бара Главной, чтобы тост не наезжал на чипы.
        offset = down
        for entry in reversed(self.entries):
            entry.top = height - offset - 40
            offset += 52

    def _remove(self, entry) -> None:
        page = self._page()
        if page is None:
            return
        try:
            if entry in page.overlay:
                page.overlay.remove(entry)
        except Exception:
            return

    async def _later(self, entry, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        self.entries = [item for item in self.entries if item is not entry]
        self._remove(entry)
        self._place()
        page = self._page()
        if page is not None:
            try:
                page.update()
            except Exception:
                pass

    def clear(self) -> None:
        for entry in list(self.entries):
            self._remove(entry)
        self.entries.clear()
