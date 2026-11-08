# -*- coding: utf-8 -*-
"""Палитра команд (Ctrl+K): поиск по вкладкам и частым действиям.

Тут нет второй навигации: команды зовут обычные методы `FenixGUI`
(`_select_tab`, `_on_mic_toggle`, `set_vertical_mode`, темы), поэтому палитра —
это только быстрый ввод, а не новый слой состояния. Чистые функции
(`default_commands`, `filter_commands`, `describe`) проверяются без окна.
"""
from __future__ import annotations

from types import SimpleNamespace

import flet as ft

from jarvis import gui_tokens as T

TYPE_LIMIT = 6


def _call(gui, name, *args):
    method = getattr(gui, name, None)
    if method is None:
        return False
    method(*args)
    return True


def default_commands():
    """Команды палитры в порядке групп: вкладки, действия, темы."""
    from jarvis import gui as ui

    commands = []
    for tab in ui.NAV_ORDER:
        name, icon = ui.NAV_ITEMS[tab]
        commands.append({
            "key": f"tab:{tab}", "group": "Вкладки", "title": name, "icon": icon,
            "run": lambda gui, t=tab: _call(gui, "_select_tab", t),
        })
    commands += [
        {"key": "mic", "group": "Действия", "title": "Микрофон: пауза или продолжить",
         "icon": ft.Icons.MIC,
         "run": lambda gui: _call(gui, "_on_mic_toggle", None)},
        {"key": "vertical", "group": "Действия", "title": "Полоса у края экрана",
         "icon": ft.Icons.SPLITSCREEN,
         "run": lambda gui: _call(gui, "set_vertical_mode", True)},
        {"key": "focus", "group": "Действия", "title": "Фокус-режим: спрятать всё лишнее",
         "icon": ft.Icons.CENTER_FOCUS_STRONG_OUTLINED,
         "run": lambda gui: _call(gui, "toggle_focus_mode")},
        {"key": "pipette", "group": "Действия", "title": "Пипетка: свернуть в кружок 56 px",
         "icon": ft.Icons.CIRCLE_OUTLINED,
         "run": lambda gui: _call(gui, "set_pipette_mode", True)},
        {"key": "stop", "group": "Действия", "title": "Остановить речь",
         "icon": ft.Icons.STOP_ROUNDED,
         "run": lambda gui: _call(gui, "_palette_stop_speech")},
        {"key": "dark", "group": "Темы", "title": "Тема «Сумерки»",
         "icon": ft.Icons.DARK_MODE_OUTLINED,
         "run": lambda gui: _call(gui, "_on_theme_change",
                                  SimpleNamespace(control=SimpleNamespace(value="Тёмная")))},
        {"key": "light", "group": "Темы", "title": "Тема «Фарфор»",
         "icon": ft.Icons.LIGHT_MODE_OUTLINED,
         "run": lambda gui: _call(gui, "_on_theme_change",
                                  SimpleNamespace(control=SimpleNamespace(value="Светлая")))},
    ]
    return commands


def filter_commands(commands, query, limit: int = TYPE_LIMIT):
    """Отбор по подстроке: начало названия важнее вхождения, группа — запасной."""
    text = str(query or "").strip().lower()
    if not text:
        return list(commands)[:limit]
    scored = []
    for order, command in enumerate(commands):
        title = str(command.get("title", "")).lower()
        group = str(command.get("group", "")).lower()
        if title.startswith(text):
            rank = 0
        elif text in title:
            rank = 1
        elif text in group:
            rank = 2
        else:
            continue
        scored.append((rank, order, command))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [command for _, _, command in scored[:limit]]


def describe(command) -> str:
    """Подпись команды: группа и название — для тестов и подсказки."""
    return f"{command.get('group', '')} · {command.get('title', '')}"


class CommandPalette(ft.Container):
    """Оверлей Ctrl+K: поле ввода сверху и список подходящих команд."""

    def __init__(self, gui, commands=None):
        from jarvis import gui as ui

        super().__init__()
        self.gui = gui
        self.commands = list(commands) if commands is not None else default_commands()
        self.visible_rows = []
        self.opened = False
        p = ui.P
        self.field = ft.TextField(
            value="", autofocus=True, dense=True, text_size=15, color=p.text,
            bgcolor=ft.Colors.TRANSPARENT, border=ft.NoInputBorder(),
            hint_text="Вкладка, действие или тема…", on_change=self._on_change,
            on_submit=self._on_submit, shift_enter=False)
        self.rows = ft.ListView(spacing=2, height=300)
        self.hint = T.text("caption", "Enter — выполнить · Esc — закрыть", color=p.text_dim)
        card = ft.Container(
            ft.Column([
                ft.Row([ft.Icon(ft.Icons.SEARCH, size=18, color=p.text_dim), self.field],
                       spacing=8),
                ft.Container(height=1, bgcolor=ft.Colors.with_opacity(.35, p.border)),
                self.rows, self.hint,
            ], spacing=8, tight=True),
            width=520, padding=ft.Padding(left=16, right=16, top=12, bottom=12),
            bgcolor=p.bg_card, border_radius=T.RADIUS["lg"],
            border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.5, p.border)),
            shadow=T.shadow(p, raised=True))
        # Подложка закрывает окно и ловит клик мимо карточки.
        self.backdrop = ft.Container(
            expand=True, bgcolor=ft.Colors.with_opacity(.45, "#000000"),
            on_click=lambda e: self.close())
        self.content = ft.Stack(
            [self.backdrop, ft.Container(card, alignment=ft.Alignment.TOP_CENTER,
                                         padding=ft.Padding.only(top=90))],
            expand=True)
        self._render("")

    def _on_change(self, e) -> None:
        self._render(e.control.value)

    def _mounted_page(self):
        try:
            return self.page
        except RuntimeError:
            return None

    def _render(self, query) -> None:
        from jarvis import gui as ui

        p = ui.P
        self.visible_rows = filter_commands(self.commands, query)
        self.rows.controls = [self._row(command) for command in self.visible_rows] or [
            T.text("label", "Ничего не нашлось", color=p.text_dim)]
        # Карточка не тащит пустую высоту: список растёт по числу строк
        # (48 px на строку — сама плашка и её отступы).
        self.rows.height = min(300, 48 * max(1, len(self.visible_rows)))
        page = self._mounted_page()
        if page is not None:
            try:
                self.update()
            except Exception:
                pass

    def _row(self, command):
        from jarvis import gui as ui

        p = ui.P
        return ft.Container(
            ft.Row([
                ft.Icon(command.get("icon", ft.Icons.CHEVRON_RIGHT), size=16, color=p.brand),
                ft.Column([
                    T.text("label", command.get("title", ""), color=p.text),
                    T.text("caption", command.get("group", ""), color=p.text_dim),
                ], spacing=0, tight=True, expand=True),
            ], spacing=10),
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            border_radius=T.RADIUS["sm"],
            on_click=lambda e, c=command: self.run(c),
            tooltip=describe(command))

    def run(self, command) -> bool:
        """Выполняет команду и закрывает палитру."""
        runner = command.get("run")
        if runner is None:
            return False
        try:
            runner(self.gui)
        except Exception:
            import logging
            logging.getLogger("jarvis.gui_palette").exception(
                "Палитра: команда %s упала", command.get("key"))
            return False
        self.close()
        return True

    def _on_submit(self, e=None) -> None:
        if self.visible_rows:
            self.run(self.visible_rows[0])

    def open(self) -> None:
        page = self.gui._page
        if page is None or self in page.overlay:
            return
        page.overlay.append(self)
        self.opened = True
        self.field.value = ""
        self.field.autofocus = True
        self._render("")
        page.update()

    def close(self) -> None:
        page = self.gui._page
        if page is None or self not in page.overlay:
            self.opened = False
            return
        page.overlay.remove(self)
        self.opened = False
        page.update()
