"""Вертикальный режим окна: узкая полоса-шторка у правого края экрана.

Это не второй интерфейс и не второй индикатор состояния:
- состояние рисует та же аура (`jarvis.gui_home_fx.PhoenixAura`), просто меньше;
- сообщения берутся из того же `Gui._messages`;
- переключение режима не создаёт второй `ft.run` и не пересобирает приложение.

Полоса ведёт себя как боковая панель Феникса: у края остаётся узкая «ручка»
(`TAB_WIDTH`), при наведении шторка выезжает целиком, уходит сама, когда
курсор ушёл, и остаётся открытой, если её закрепили (`ui_vertical_pinned`).

Чистые функции (настройки, геометрия, кадры анимации, состояние шторки,
документы заметок и плана) вынесены наверх модуля: их проверяют тесты без
окна, микрофона и сети.
"""
import logging
import os
import sys
import time
from pathlib import Path

import flet as ft

log = logging.getLogger("jarvis.gui_vertical")

PANELS = {"log": "Лог", "notes": "Заметки", "plan": "План"}
PANEL_DEFAULT = "log"
WIDTH_MIN = 220
WIDTH_MAX = 320
WIDTH_DEFAULT = 240
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 760
WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 600
AURA_SIZE = 140
AURA_RING = 104
TAB_WIDTH = 18
TAB_MIN = 12
TAB_MAX = 28
LEVEL_TRACK = 44
LEVEL_MS = 200
SLIDE_MS = 170
SLIDE_STEPS = 11
AUTOHIDE_MS = 900
REVEAL_MS = 2600
LOG_LIMIT = 60
TEXT_LIMIT = 260

NOTES_FILE = "vertical_notes.txt"
PLAN_FILE = "vertical_plan.txt"

_TRUE = {"1", "true", "yes", "on", "да", "y", "t"}
_FALSE = {"0", "false", "no", "off", "нет", "n", "f", ""}


def normalize_enabled(value) -> bool:
    """Флаг режима: строка/число/None → bool без исключений."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return False


def normalize_pinned(value) -> bool:
    """Закрепление полосы — тот же терпимый разбор, что и у режима."""
    return normalize_enabled(value)


def normalize_width(value, default: int = WIDTH_DEFAULT) -> int:
    """Ширина полосы в пикселях: битое значение → дефолт, число → в границы."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    if number <= 0:
        return default
    return max(WIDTH_MIN, min(WIDTH_MAX, number))


def normalize_tab(value, default: int = TAB_WIDTH) -> int:
    """Ширина «ручки», которая остаётся на экране у спрятанной шторки."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    if number <= 0:
        return default
    return max(TAB_MIN, min(TAB_MAX, number))


def normalize_delay(value, default: int = AUTOHIDE_MS) -> int:
    """Пауза перед автоскрытием в миллисекундах: 0..10000."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, min(10000, number))


def normalize_panel(value, default: str = PANEL_DEFAULT) -> str:
    """Панель полосы: неизвестное имя → дефолт, регистр не важен."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in PANELS:
            return key
    return default


def aura_mode(state) -> str:
    """Состояние ассистента → режим ауры (у ауры их четыре)."""
    return {
        "listening": "listening",
        "recognizing": "listening",
        "thinking": "thinking",
        "speaking": "speaking",
    }.get(state if isinstance(state, str) else "", "idle")


def aura_label(state) -> str:
    """Подпись состояния в полосе; неизвестное состояние не выдумываем."""
    from jarvis import gui as ui

    known = ui.STATES.get(state if isinstance(state, str) else "")
    if known is None:
        return ui.STATES["idle"][1]
    return known[1]


def vertical_window_spec(width, workarea=None) -> dict:
    """Свойства окна для вертикального режима.

    workarea — (left, top, right, bottom) рабочей области без панели задач.
    Без него высоту не трогаем: клиент Flet не отдаёт размер экрана, и
    придумывать «1080 по умолчанию» нельзя — окно уедет за край.
    """
    bar = normalize_width(width)
    spec = {
        "width": bar,
        "min_width": WIDTH_MIN,
        "max_width": WIDTH_MAX,
        "frameless": True,
        "always_on_top": True,
        "movable": True,
        "resizable": True,
        # Тень Windows вокруг окна без рамки: полоса читается как отдельная
        # панель, а не как обрезанный кусок чужого приложения.
        "shadow": True,
    }
    area = _work_area_tuple(workarea)
    if area is not None:
        left, top, right, bottom = area
        spec["height"] = bottom - top
        spec["left"] = right - bar
        spec["top"] = top
    return spec


def horizontal_window_spec() -> dict:
    """Свойства окна для обычного режима — те же, что при старте."""
    return {
        "width": WINDOW_WIDTH,
        "height": WINDOW_HEIGHT,
        "min_width": WINDOW_MIN_WIDTH,
        "min_height": WINDOW_MIN_HEIGHT,
        "max_width": None,
        "max_height": None,
        "frameless": False,
        "always_on_top": False,
        "movable": True,
        "resizable": True,
        "shadow": False,
    }


def curtain_geometry(width, workarea=None, tab=None) -> dict:
    """Позиции окна для шторки: открытая и спрятанная за край экрана.

    `hidden` оставляет на экране только «ручку» `tab` пикселей: остальное
    окно уезжает за правую границу рабочей области. Без рабочей области
    позиции неизвестны (None) — выдумывать координаты нельзя.
    """
    bar = normalize_width(width)
    handle = normalize_tab(tab)
    positions = {"shown": None, "hidden": None, "tab": handle, "width": bar,
                 "height": None, "top": None}
    area = _work_area_tuple(workarea)
    if area is None:
        return positions
    left, top, right, bottom = area
    positions["shown"] = right - bar
    positions["hidden"] = right - handle
    positions["height"] = bottom - top
    positions["top"] = top
    return positions


def slide_frames(start, end, steps: int = SLIDE_STEPS) -> list:
    """Кадры выезда/уезда: последний кадр всегда ровно `end`."""
    try:
        begin = int(start)
        finish = int(end)
    except (TypeError, ValueError):
        return []
    if begin == finish:
        return [finish]
    try:
        count = max(1, int(steps))
    except (TypeError, ValueError):
        count = SLIDE_STEPS
    frames = [int(round(begin + (finish - begin) * i / count)) for i in range(1, count + 1)]
    frames[-1] = finish
    return frames


class Curtain:
    """Состояние шторки без окна: открыта ли, закреплена ли, где курсор.

    Правила простые и проверяемые: закреплённая шторка не закрывается сама,
    курсор внутри держит её открытой. Уход курсора не двигает окно сам по
    себе — он только снимает «держать открытой»; фактическое скрытие делает
    `hide()` по таймеру, чтобы окно не дёргалось на каждый пиксель.
    """

    def __init__(self, pinned=False, never_hide=False):
        self.pinned = bool(pinned)
        self.never_hide = bool(never_hide)
        self.pointer_inside = False
        self.open = True

    def enter(self) -> bool:
        """Курсор на полосе: открываем. True — позиция изменилась."""
        self.pointer_inside = True
        changed = not self.open
        self.open = True
        return changed

    def leave(self) -> bool:
        """Курсор ушёл: снимаем «держать открытой»; окно двигает таймер."""
        self.pointer_inside = False
        return False

    def hide(self) -> bool:
        """Закрыть с учётом закрепления и курсора. True — позиция изменилась."""
        if self.pinned or self.never_hide or self.pointer_inside or not self.open:
            return False
        self.open = False
        return True

    def show(self) -> bool:
        changed = not self.open
        self.open = True
        return changed

    def set_pinned(self, value) -> bool:
        """Закрепление: закреплённая полоса сразу открывается."""
        self.pinned = bool(value)
        if self.pinned:
            self.open = True
        return self.pinned

    def set_never_hide(self, value) -> bool:
        """«Не прятать»: полоса остаётся открытой, пока режим включён.

        True — состояние действительно изменилось (нужно перерисовать).
        """
        value = bool(value)
        changed = value != self.never_hide
        self.never_hide = value
        if self.never_hide:
            self.open = True
        return changed

    def wants_autohide(self) -> bool:
        """Пора планировать скрытие: открыта, не закреплена, курсора нет."""
        return self.open and not self.pinned and not self.never_hide \
            and not self.pointer_inside


def _work_area_tuple(value):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        left, top, right, bottom = (int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def work_area():
    """Рабочая область экрана (без панели задач) или None.

    Windows-only: SPI_GETWORKAREA через ctypes, без новых зависимостей.
    На других ОС None — вертикальный режим останется без высоты и позиции,
    размер окна задаст клиент.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        if not ok:
            return None
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        log.warning("Вертикальный режим: рабочая область недоступна", exc_info=True)
        return None


def notes_path() -> Path:
    from jarvis import paths

    return paths.user_dir() / NOTES_FILE


def plan_path() -> Path:
    from jarvis import paths

    return paths.user_dir() / PLAN_FILE


def read_doc(path) -> str:
    """Читает текстовый документ полосы; отсутствие файла — пустая строка."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError):
        log.warning("Вертикальный режим: не удалось прочитать %s", path, exc_info=True)
        return ""


def write_doc(path, text) -> bool:
    """Пишет документ атомарно (временный файл + replace), возвращает успех."""
    target = Path(path)
    body = text if isinstance(text, str) else ""
    tmp = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, target)
        return True
    except OSError:
        log.warning("Вертикальный режим: не удалось записать %s", target, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        return False


def shorten(text, limit: int = TEXT_LIMIT) -> str:
    body = " ".join(str(text or "").split())
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def log_lines(messages, limit: int = LOG_LIMIT) -> list:
    """Хвост диалога для полосы: список {role, text, time}, старые сверху."""
    rows = []
    for message in list(messages or [])[-limit:] if limit > 0 else []:
        if not isinstance(message, dict):
            continue
        text = shorten(message.get("text", ""))
        if not text:
            continue
        role = "user" if message.get("role") == "user" else "assistant"
        rows.append({"role": role, "text": text, "time": str(message.get("time", ""))})
    return rows


def _entered(event) -> bool:
    return getattr(event, "data", False) in (True, "true", "True")


class VerticalBar(ft.Container):
    """Полоса-шторка: ручка у края, аура со статусом, панель и закрепление."""

    def __init__(self, gui, width=None, panel=None):
        from jarvis.gui_home_fx import PhoenixAura
        from jarvis import gui as ui

        super().__init__(expand=True, bgcolor=ft.Colors.TRANSPARENT)
        self.gui = gui
        self.width = normalize_width(width if width is not None
                                     else gui.config.get("ui_vertical_width", WIDTH_DEFAULT))
        self.panel = normalize_panel(panel if panel is not None
                                     else gui.config.get("ui_vertical_panel", PANEL_DEFAULT))
        self.pinned = normalize_pinned(gui.config.get("ui_vertical_pinned", False))
        self.never_hide = normalize_pinned(gui.config.get("ui_vertical_never_hide", False))
        self.unread = 0
        self._dot_touch = 0.0
        self._level_height = 2
        self._docs = {}
        self._notes_field = None
        self._plan_field = None
        p = ui.P

        # --- ручка у края: единственное, что видно у спрятанной шторки ----
        self.tab_icon = ft.Icon(ft.Icons.CHEVRON_LEFT, size=14,
                                color=ft.Colors.with_opacity(.80, p.brand))
        self.tab_line = ft.Container(
            width=2, height=46, border_radius=1,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                colors=[ft.Colors.with_opacity(.0, p.brand),
                        ft.Colors.with_opacity(.75, p.brand),
                        ft.Colors.with_opacity(.0, p.brand)],
                stops=[.0, .5, 1.0]))
        # Бейдж непрочитанного: точка у верха ручки, пока полоса спрятана.
        self.badge = ft.Container(width=6, height=6, border_radius=3,
                                  bgcolor=p.error, visible=False)
        self.badge_zone = ft.Container(self.badge, height=14,
                                       alignment=ft.Alignment.CENTER, visible=False)
        # Уровень микрофона: тонкая колонка, растущая снизу вверх.
        self.level_fill = ft.Container(width=3, height=2, border_radius=2,
                                       bgcolor=ft.Colors.with_opacity(.85, p.brand))
        self.level = ft.Container(
            ft.Container(self.level_fill, width=3, height=LEVEL_TRACK,
                         alignment=ft.Alignment.BOTTOM_CENTER),
            height=LEVEL_TRACK, bgcolor=ft.Colors.with_opacity(.14, p.brand),
            border_radius=2, tooltip="Уровень микрофона")
        # Три точки панелей: листать без раскрытия шторки.
        self.panel_dots = {}
        self.dots_column = ft.Column([], spacing=5, tight=True,
                                     horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        for key in PANELS:
            self.panel_dots[key] = ft.Container(
                ft.Container(width=4, height=4, border_radius=2,
                             bgcolor=ft.Colors.with_opacity(.45, p.text_dim)),
                width=14, height=10, alignment=ft.Alignment.CENTER,
                on_click=lambda e, name=key: self._on_dot(name),
                tooltip=PANELS[key])
            self.dots_column.controls.append(self.panel_dots[key])
        self.tab = ft.Container(
            width=TAB_WIDTH, alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Container(self.badge_zone, height=18, alignment=ft.Alignment.TOP_CENTER),
                ft.Container(
                    ft.Column([self.tab_line, self.level, self.tab_icon], spacing=8,
                              tight=True, alignment=ft.MainAxisAlignment.CENTER,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    expand=True, alignment=ft.Alignment.CENTER),
                ft.Container(self.dots_column, height=22, alignment=ft.Alignment.BOTTOM_CENTER),
            ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True),
            on_click=self._on_tab_click, bgcolor=ft.Colors.TRANSPARENT,
            animate=ft.Animation(SLIDE_MS, ft.AnimationCurve.EASE_OUT_CUBIC),
            tooltip="Открыть полосу" if not self.pinned else "Полоса закреплена")

        # --- шапка: аура и статус ----------------------------------------
        self.dot = ft.Container(width=6, height=6, border_radius=3, bgcolor=p.brand)
        self.status = ft.Text("", size=11, color=p.text_dim,
                              max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.status_pill = ft.Container(
            ft.Row([self.dot, self.status], spacing=7, tight=True,
                   alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.Padding.only(left=11, right=11, top=5, bottom=5),
            border_radius=99, bgcolor=ft.Colors.with_opacity(.45, p.bg_card),
            border=ft.Border.all(1, ft.Colors.with_opacity(.30, p.border)))
        self.ring = ft.Container(
            ui._brand_image("phoenix", 72, "Феникс"), width=AURA_RING, height=AURA_RING,
            border_radius=AURA_RING // 2, alignment=ft.Alignment.CENTER,
            border=ft.Border.all(1, ft.Colors.with_opacity(.35, p.border)),
            bgcolor=ft.Colors.with_opacity(.12, p.sidebar))
        self.aura = PhoenixAura(gui, self.ring, size=AURA_SIZE,
                                foreground=lambda: bool(getattr(gui, "_vertical_mode", False)))
        self.head = ft.Container(
            ft.Column([
                ft.Container(self.aura, alignment=ft.Alignment.CENTER, height=AURA_SIZE),
                ft.Container(self.status_pill, alignment=ft.Alignment.CENTER),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.only(left=8, right=8, top=10, bottom=8))

        # --- переключатель панелей: три пилюли вместо выпадающего списка --
        self.panel_buttons = {}
        for key, label in PANELS.items():
            self.panel_buttons[key] = ft.Button(
                content=ft.Text(label, size=11, no_wrap=True),
                on_click=lambda e, name=key: self._on_panel_click(name),
                style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=0, vertical=7),
                                     elevation=0, shape=ft.RoundedRectangleBorder(radius=9)),
                expand=True, height=30)
        self.panel_row = ft.Container(
            ft.Row(list(self.panel_buttons.values()), spacing=4),
            padding=ft.Padding.only(left=8, right=8))

        self.log_list = ft.ListView(spacing=10, auto_scroll=True, expand=True)
        self.body = ft.Container(content=self._panel_body(self.panel), expand=True,
                                 padding=ft.Padding.only(left=10, right=10, top=8, bottom=4))
        self.divider_top = ft.Container(
            ft.Container(height=1, bgcolor=ft.Colors.with_opacity(.45, p.border)), height=1)
        self.divider_bottom = ft.Container(
            ft.Container(height=1, bgcolor=ft.Colors.with_opacity(.45, p.border)), height=1)

        # --- подвал: закрепление и выход в обычное окно -------------------
        self.pin_btn = ft.IconButton(icon=ft.Icons.PUSH_PIN if self.pinned
                                     else ft.Icons.PUSH_PIN_OUTLINED,
                                     icon_size=18, on_click=self._on_pin,
                                     icon_color=p.brand if self.pinned else p.text_dim,
                                     tooltip=self._pin_tooltip())
        self.never_btn = ft.IconButton(
            icon=ft.Icons.VISIBILITY if self.never_hide else ft.Icons.VISIBILITY_OFF,
            icon_size=18, on_click=self._on_never_hide,
            icon_color=p.brand if self.never_hide else p.text_dim,
            tooltip=self._never_tooltip())
        self.exit_btn = ft.IconButton(
            icon=ft.Icons.CLOSE_FULLSCREEN, tooltip="Вернуть обычное окно",
            icon_color=p.text_dim, icon_size=18, on_click=self._on_exit)
        self.foot = ft.Container(
            ft.Row([
                ft.Text("Поверх окон", size=10, color=ft.Colors.with_opacity(.75, p.text_dim),
                        no_wrap=True, expand=True),
                self.never_btn, self.pin_btn, self.exit_btn,
            ], spacing=0, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.Padding.only(left=12, right=4, top=4, bottom=4))

        self.card = ft.Container(
            expand=True,
            margin=ft.Margin(left=6, top=6, bottom=6, right=0),
            padding=ft.Padding.only(left=4, right=4, top=2, bottom=2),
            border_radius=ft.BorderRadius(top_left=16, bottom_left=16, top_right=0, bottom_right=0),
            gradient=ft.LinearGradient(
                begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                colors=[ft.Colors.with_opacity(.96, p.sidebar),
                        ft.Colors.with_opacity(.94, p.bg_card)]),
            border=ft.Border.only(left=ft.BorderSide(1, ft.Colors.with_opacity(.45, p.border)),
                                  top=ft.BorderSide(1, ft.Colors.with_opacity(.45, p.border)),
                                  bottom=ft.BorderSide(1, ft.Colors.with_opacity(.45, p.border))),
            shadow=ft.BoxShadow(blur_radius=26, spread_radius=-4,
                                color=ft.Colors.with_opacity(.42, "#000000"),
                                offset=ft.Offset(-7, 0)),
            content=ft.Column([self.head, self.panel_row, self.divider_top, self.body,
                               self.divider_bottom, self.foot], spacing=0, expand=True))
        self.content = ft.Row([self.tab, self.card], spacing=0, expand=True,
                              vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.on_hover = self._on_hover
        self._sync_panel_tabs()
        self.set_open_state(True)
        self._render_log()
        self.apply_state(getattr(gui, "_state", "idle"))

    # --- вид и состояния ----------------------------------------------

    def _pin_tooltip(self) -> str:
        return "Открепить полосу" if self.pinned else "Закрепить полосу"

    def _never_tooltip(self) -> str:
        return ("Прятать снова, когда курсор ушёл" if self.never_hide
                else "Не прятать полосу")

    def set_level(self, energy) -> float:
        """Уровень микрофона 0..1: высота колонки на ручке. Без окна — тихо."""
        try:
            value = max(0.0, min(1.0, float(energy)))
        except (TypeError, ValueError):
            value = 0.0
        height = max(2, int(round(LEVEL_TRACK * value)))
        if height == self._level_height:
            return value
        self._level_height = height
        self.level_fill.height = height
        self._refresh(self.level_fill)
        return value

    def set_unread(self, count) -> int:
        """Непрочитанное: точка на ручке спрятанной полосы."""
        try:
            value = max(0, int(count))
        except (TypeError, ValueError):
            value = 0
        self.unread = value
        visible = value > 0
        changed = self.badge.visible != visible
        self.badge.visible = self.badge_zone.visible = visible
        if changed:
            self._refresh(self.badge_zone, self.badge)
        return value

    def set_never_hide(self, value) -> bool:
        """Опция «не прятать»: состояние кнопки в подвале полосы."""
        from jarvis import gui as ui

        value = normalize_pinned(value)
        if value == self.never_hide:
            return False
        self.never_hide = value
        self.never_btn.icon = ft.Icons.VISIBILITY if value else ft.Icons.VISIBILITY_OFF
        self.never_btn.icon_color = ui.P.brand if value else ui.P.text_dim
        self.never_btn.tooltip = self._never_tooltip()
        self._refresh(self.never_btn)
        return True

    def set_open_state(self, open_: bool) -> None:
        """Иконка ручки смотрит туда, куда поедет шторка."""
        from jarvis import gui as ui

        p = ui.P
        self.tab_icon.name = ft.Icons.CHEVRON_LEFT if not open_ else ft.Icons.CHEVRON_RIGHT
        self.tab.tooltip = ("Свернуть полосу" if open_ else "Открыть полосу") if not self.pinned \
            else "Полоса закреплена"
        self.tab_icon.color = p.brand if open_ else p.text_dim
        self._refresh(self.tab_icon)

    def set_pinned(self, pinned) -> bool:
        """Закрепление: меняет иконку, подсказку и вид ручки."""
        from jarvis import gui as ui

        pinned = normalize_pinned(pinned)
        if pinned == self.pinned:
            return False
        self.pinned = pinned
        self.pin_btn.icon = ft.Icons.PUSH_PIN if pinned else ft.Icons.PUSH_PIN_OUTLINED
        self.pin_btn.icon_color = ui.P.brand if pinned else ui.P.text_dim
        self.pin_btn.tooltip = self._pin_tooltip()
        self.set_open_state(True)
        self._refresh(self.pin_btn, self.tab)
        return True

    def _sync_panel_tabs(self) -> None:
        from jarvis import gui as ui

        p = ui.P
        for key, button in self.panel_buttons.items():
            active = key == self.panel
            fill = ft.Colors.with_opacity(.18, p.brand) if active else ft.Colors.TRANSPARENT
            button.content.color = p.brand if active else p.text_dim
            button.style = ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=0, vertical=7), elevation=0,
                bgcolor=fill, overlay_color=ft.Colors.with_opacity(.08, p.text),
                side={ft.ControlState.DEFAULT: ft.BorderSide(
                    1, ft.Colors.with_opacity(.22, p.brand) if active
                    else ft.Colors.with_opacity(.10, p.border))},
                shape=ft.RoundedRectangleBorder(radius=9))
            button.tooltip = PANELS[key]
        for key, dot in getattr(self, "panel_dots", {}).items():
            dot.content.bgcolor = (ft.Colors.with_opacity(.95, p.brand)
                                   if key == self.panel
                                   else ft.Colors.with_opacity(.45, p.text_dim))
        self._refresh(*getattr(self, "panel_dots", {}).values())

    def _refresh(self, *controls) -> None:
        """Обновление без исключений: тесты и закрытое окно — не повод падать."""
        if not controls:
            return
        try:
            if getattr(self, "_mounted_hint", True) and self.page is not None:
                self.update(*controls)
        except Exception:
            log.debug("Полоса: не удалось обновить вид", exc_info=True)

    def _on_hover(self, e) -> None:
        entered = _entered(e)
        try:
            from jarvis import gui as ui

            self.tab.bgcolor = (ft.Colors.with_opacity(.10, ui.P.brand) if entered
                                else ft.Colors.TRANSPARENT)
            self._refresh(self.tab)
        except Exception:
            log.debug("Полоса: подсветка ручки не применилась", exc_info=True)
        hook = getattr(self.gui, "_vertical_hover", None)
        if hook is not None:
            try:
                hook(entered)
            except Exception:
                log.exception("Полоса: ошибка обработки наведения")

    def _on_tab_click(self, e=None) -> None:
        # Точка панели внутри ручки: её клик уже обработан, шторку не трогаем.
        if time.monotonic() - self._dot_touch < .35:
            return
        hook = getattr(self.gui, "_vertical_tab_click", None)
        if hook is not None:
            try:
                hook()
            except Exception:
                log.exception("Полоса: не удалось переключить шторку")

    def _on_dot(self, name) -> None:
        """Точка панели на ручке: переключить панель, не раскрывая шторку."""
        self._dot_touch = time.monotonic()
        self._on_panel_click(name)

    def _on_pin(self, e=None) -> None:
        try:
            self.gui.set_vertical_pinned(not self.pinned)
        except Exception:
            log.exception("Полоса: не удалось сохранить закрепление")

    def _on_never_hide(self, e=None) -> None:
        try:
            self.gui.set_vertical_never_hide(not self.never_hide)
        except Exception:
            log.exception("Полоса: не удалось сохранить «не прятать»")

    # --- панели -------------------------------------------------------

    def _panel_body(self, panel):
        if panel == "log":
            return self.log_list
        return self._doc_field("notes" if panel == "notes" else "plan")

    def _doc_field(self, name):
        cached = getattr(self, f"_{name}_field", None)
        if cached is not None:
            return cached
        from jarvis import gui as ui

        p = ui.P
        path = notes_path() if name == "notes" else plan_path()
        text = self._docs.get(name)
        if text is None:
            text = read_doc(path)
            self._docs[name] = text
        field = ft.TextField(
            value=text, multiline=True, expand=True, text_size=12, border=ft.NoInputBorder(),
            color=p.text, bgcolor=ft.Colors.TRANSPARENT,
            hint_text=("Заметки: пиши что угодно, сохраняется на диск"
                       if name == "notes" else "План: по строке на пункт"),
            shift_enter=True, on_blur=lambda e, key=name: self.save_doc(key))
        if name == "notes":
            self._notes_field = field
        else:
            self._plan_field = field
        return field

    def save_doc(self, name) -> bool:
        """Сохраняет заметки/план на диск; ошибка записи не выдаётся за успех."""
        field = getattr(self, f"_{name}_field", None)
        if field is None:
            return True
        text = field.value or ""
        self._docs[name] = text
        path = notes_path() if name == "notes" else plan_path()
        return write_doc(path, text)

    def flush(self) -> None:
        for name in ("notes", "plan"):
            self.save_doc(name)

    def set_panel(self, panel) -> bool:
        value = normalize_panel(panel)
        if value == self.panel:
            return False
        self.flush()
        self.panel = value
        self.body.content = self._panel_body(value)
        self._sync_panel_tabs()
        if value == "log":
            self._render_log()
        return True

    def _on_panel_click(self, name) -> None:
        try:
            self.gui.set_vertical_panel(name)
        except Exception:
            log.exception("Полоса: не удалось переключить панель")

    def _on_exit(self, e=None) -> None:
        try:
            self.gui.set_vertical_mode(False)
        except Exception:
            log.exception("Полоса: не удалось вернуть обычное окно")

    # --- данные -------------------------------------------------------

    def _render_log(self) -> None:
        from jarvis import gui as ui

        p = ui.P
        rows = []
        for line in log_lines(getattr(self.gui, "_messages", [])):
            who = "Вы" if line["role"] == "user" else "Феникс"
            rows.append(ft.Column([
                ft.Row([ft.Text(who, size=10, color=ft.Colors.with_opacity(.8, p.text_dim)),
                        ft.Text(line["time"], size=10, color=ft.Colors.with_opacity(.8, p.text_dim))]),
                ft.Text(line["text"], size=12, color=p.text),
            ], spacing=2))
        self.log_list.controls = rows or [ft.Text("Пока пусто", size=12, color=p.text_dim)]

    def on_message(self, record) -> None:
        """Новое сообщение в диалоге: обновляем лог (панель могла быть любой)."""
        if self.panel != "log":
            return
        self._render_log()

    def apply_state(self, state) -> None:
        from jarvis import gui as ui

        p = ui.P
        color = {"error": p.error, "speaking": p.success}.get(
            state, p.brand if state in ("idle",) else p.accent)
        self.status.value = aura_label(state)
        self.dot.bgcolor = color
        self.aura.set_mode(aura_mode(state))

    def dispose(self) -> None:
        try:
            self.flush()
        except Exception:
            log.exception("Полоса: не удалось сохранить заметки при закрытии")
        try:
            self.aura.dispose()
        except Exception:
            log.debug("Полоса: аура уже освобождена", exc_info=True)
