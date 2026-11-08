"""Minimal native Home: local clock, real assistant state and opt-in widgets, no chat."""
import asyncio
import math
import time
from datetime import datetime
from types import SimpleNamespace

import flet as ft

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def clock_labels(now):
    return f"{WEEKDAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]}", now.strftime("%H:%M")


def greeting(now):
    """Приветствие по местному времени: утро, день, вечер, ночь."""
    hour = now.hour
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 17:
        return "Добрый день"
    if 17 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


from jarvis import gui_tokens as T
from jarvis.gui_home_fx import PhoenixAura
from jarvis.gui_home_actions import PhoenixActions
from jarvis.gui_widgets import WidgetBoard


class HomeScreen(ft.Column):
    """Minimal Home with real-state solar aura; quiet ambient motion, no fake audio."""
    def __init__(self, gui):
        from jarvis import gui as ui
        super().__init__(spacing=0, expand=True)
        self.gui = gui
        self._host = None
        self._future = None
        self._mounted = False
        self._epoch = 0
        p = ui.P
        self.date = T.text("caption", "", color=p.text_dim)
        self.clock = T.text("caption", "", color=p.text_dim, weight=ft.FontWeight.W_500)
        self.refresh_clock()
        self.status = T.text("label", "Ядро ещё не готово", color=p.text_dim,
                             text_align=ft.TextAlign.CENTER)
        self.dot = ft.Container(width=6, height=6, border_radius=3, bgcolor=p.brand)
        self.greeting = T.text("title", greeting(datetime.now()), color=p.text)
        self.dot_sep = T.text("caption", "·", color=p.text_dim)
        self.meta = ft.Row([self.date, self.dot_sep, self.clock], spacing=T.SPACE["sm"],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.status_pill = ft.Container(
            ft.Row([self.dot, self.status], spacing=T.SPACE["sm"], tight=True,
                   alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=T.SPACE["md"], vertical=T.SPACE["sm"]),
            border_radius=T.RADIUS["pill"], bgcolor=p.bg_card,
            border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.45, p.border)))
        self.ring = ft.Container(
            ui._brand_image("phoenix", 112, "Феникс"), width=240, height=240,
            border_radius=120, alignment=ft.Alignment.CENTER,
            border=ft.Border.all(1, ft.Colors.with_opacity(.35, p.border)),
            bgcolor=ft.Colors.with_opacity(.12, p.sidebar),
            shadow=ft.BoxShadow(blur_radius=75, spread_radius=12,
                                color=ft.Colors.with_opacity(.035, p.accent)))
        self.aura = PhoenixAura(gui, self.ring)
        self.actions = PhoenixActions(gui, self.aura)
        self._signal_until = 0
        self._signal_energy = 0
        self.theme_buttons = []
        for title, value in (("Сумерки", "Тёмная"), ("Фарфор", "Светлая")):
            active = (value == "Светлая") == (p.bg_main == ui.PALETTES["light"]["bg_main"])
            fill = p.selected if active else ft.Colors.TRANSPARENT
            self.theme_buttons.append(ft.Button(title, height=34, elevation=0, bgcolor=fill,
                tooltip=f"Тема: {title}", on_click=lambda e, name=value: self._theme(name),
                style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=12),
                    bgcolor={ft.ControlState.DEFAULT: fill, ft.ControlState.HOVERED: p.selected},
                    overlay_color=ft.Colors.TRANSPARENT,
                    color=p.text if active else p.text_dim,
                    shape=ft.RoundedRectangleBorder(radius=8))))
        self.widgets_btn = ft.Button("Виджеты", icon=ft.Icons.ADD, tooltip="Настроить Главную",
            height=32, on_click=self._open_widgets, color=p.text_dim,
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=10)))
        self.vertical_btn = ft.Button("Полоса", icon=ft.Icons.SPLITSCREEN, height=32,
            tooltip="Перейти в полосу у края экрана", color=p.brand,
            on_click=self._open_vertical,
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=10),
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.with_opacity(.10, p.brand),
                         ft.ControlState.HOVERED: ft.Colors.with_opacity(.18, p.brand)},
                side=ft.BorderSide(T.STROKE, ft.Colors.with_opacity(.35, p.brand)),
                overlay_color=ft.Colors.TRANSPARENT))
        self.header = ft.Container(ft.Row([
            ft.Column([self.greeting, self.meta], spacing=2, tight=True, expand=True),
            ft.Container(ft.Row(self.theme_buttons, spacing=3), padding=4,
                         border_radius=T.RADIUS["pill"], bgcolor=p.sidebar,
                         border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.5, p.border))),
            self.widgets_btn, self.vertical_btn,
        ], spacing=T.SPACE["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=T.SPACE["xxl"], right=T.SPACE["xxl"],
                               top=T.SPACE["lg"], bottom=T.SPACE["lg"]),
            border=ft.Border(bottom=ft.BorderSide(T.STROKE, ft.Colors.with_opacity(.45, p.border))))
        self.center_region = ft.Container(ft.Column([self.actions, self.status_pill],
            spacing=T.SPACE["md"], tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            alignment=ft.Alignment.CENTER, expand=True)
        self.widgets = WidgetBoard(gui, self._layout_widgets)
        self.chips = {}
        self.mic_chip = self._chip("mic", ft.Icons.MIC_NONE)
        self.api_chip = self._chip("api", ft.Icons.LAN_OUTLINED)
        self.model_chip = self._chip("model", ft.Icons.MEMORY)
        self.version_chip = self._chip("version", ft.Icons.TAG_OUTLINED)
        self.status_bar = ft.Row([self.mic_chip, self.api_chip, self.model_chip, self.version_chip],
                                 spacing=T.SPACE["sm"], alignment=ft.MainAxisAlignment.CENTER)
        self.workspace = ft.Column([self.center_region, self.widgets], spacing=T.SPACE["xl"],
                                   expand=True)
        self.controls = [self.header, ft.Container(ft.Column([
            self.workspace,
            self.status_bar,
        ], expand=True, spacing=T.SPACE["xl"]),
            padding=ft.Padding(left=T.SPACE["xxl"], right=T.SPACE["xxl"],
                               top=T.SPACE["xl"], bottom=T.SPACE["lg"]),
            expand=True)]
        self._layout_widgets(update=False)
        self.apply_state(gui._state)
        self.sync_status_bar()

    def _chip(self, key, icon):
        """Маленькая пилюля статуса внизу Главной: иконка + значение."""
        from jarvis import gui as ui
        p = ui.P
        label = T.text("caption", "", color=p.text_dim)
        self.chips[key] = label
        return ft.Container(
            ft.Row([ft.Icon(icon, size=13, color=p.text_dim), label], spacing=5, tight=True),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            border_radius=T.RADIUS["pill"],
            border=ft.Border.all(T.STROKE, ft.Colors.with_opacity(.3, p.border)))

    def sync_status_bar(self):
        """Статус-бар Главной: микрофон, локальный API, модель и версия."""
        from jarvis import __version__
        config = getattr(self.gui, "config", None)
        core = self.gui.jarvis
        listening = core is not None and getattr(core, "listening_enabled", True)
        self.chips["mic"].value = "Микрофон вкл" if listening else "Микрофон пауза"
        enabled = bool(config is not None and config.get("api_enabled", False) is True)
        port = config.get("api_port", 8765) if config is not None else 8765
        self.chips["api"].value = f"API :{port}" if enabled else "API выкл"
        model = (config.get("llm_model", "") if config is not None else "") or "модель не выбрана"
        self.chips["model"].value = model
        self.chips["version"].value = __version__

    def _layout_widgets(self, update=True):
        populated = bool(self.widgets.layout) or self.widgets.editing
        self.center_region.expand = False if populated else True
        self.center_region.height = 340 if populated else None
        self.workspace.scroll = ft.ScrollMode.AUTO if populated else None
        if update and self._mounted and self._host is not None:
            self._host.update(self.workspace)

    async def _open_widgets(self, e=None):
        self.widgets.begin()

    def _theme(self, name):
        self.gui._on_theme_change(SimpleNamespace(control=SimpleNamespace(value=name)))

    def _open_vertical(self, e=None):
        """«Полоса» на Главной: тот же переход, что из настроек."""
        return self.gui.set_vertical_mode(True)

    def apply_state(self, state):
        from jarvis import gui as ui
        p = ui.P
        if self.gui.jarvis is None:
            text, color = "Ядро ещё не готово", p.text_dim
        elif state == "idle":
            text = "Рядом, когда нужен" if getattr(self.gui.jarvis, "listening_enabled", True) else "Микрофон на паузе"
            color = p.brand
        else:
            text = ui.STATES.get(state, ui.STATES["idle"])[1]
            color = {"error": p.error, "speaking": p.success}.get(state, p.brand)
        self.status.value = text
        self.dot.bgcolor = color
        self._sync_aura()
        self.actions.sync_state()
        self.sync_status_bar()

    def _sync_aura(self):
        state = self.gui._state
        mode = "idle"
        if self.gui.jarvis is not None:
            if state == "speaking":
                mode = "speaking"
            elif state in ("thinking", "recognizing"):
                mode = "thinking"
            elif getattr(self.gui.jarvis, "listening_enabled", True):
                if state == "listening" or (state == "idle" and time.monotonic() < self._signal_until):
                    mode = "listening"
        self.aura.set_mode(mode, self._signal_energy)

    def poll_signal(self):
        """Reuse existing fresh RMS at 5 Hz. No stream, recording or recognition here."""
        core = self.gui.jarvis
        listener = getattr(core, "listener", None)
        now = time.monotonic()
        valid = False
        fresh = False
        try:
            stamp = float(listener.level_updated_at)
            rms = float(listener.current_rms)
            fresh = 0 <= now - stamp <= 1 and math.isfinite(rms)
            valid = (getattr(core, "listening_enabled", True) and not listener.muted
                     and fresh and rms >= 150)
        except (AttributeError, TypeError, ValueError):
            pass
        if valid and self.gui._state == "idle":
            self._signal_until = now + .35
            self._signal_energy = min(1, rms / 2000)
        elif not valid:
            # A paused/muted/stale input must not keep a residual listening glow.
            paused = (core is None or not getattr(core, "listening_enabled", True)
                      or getattr(listener, "muted", False))
            if paused or not fresh:
                self._signal_until = 0
            if now >= self._signal_until:
                self._signal_energy = 0
        self._sync_aura()
        self.actions.sync_state()

    def refresh_clock(self, now=None):
        moment = now or datetime.now()
        date, clock = clock_labels(moment)
        phrase = greeting(moment)
        changed = self.date.value != date or self.clock.value != clock
        self.date.value, self.clock.value = date, clock
        if getattr(self, "greeting", None) is not None and self.greeting.value != phrase:
            self.greeting.value = phrase
            changed = True
        return changed

    def did_mount(self):
        self._mounted = True
        self._host = self.page
        self._epoch += 1
        self._future = self._host.run_task(self._clock_loop, self._epoch)

    def will_unmount(self):
        self.dispose()

    def dispose(self):
        self.widgets.dispose()
        self.actions.dispose()
        self.aura.dispose()
        self._mounted = False
        self._epoch += 1
        if self._future is not None:
            self._future.cancel()
            self._future = None
        self._host = None

    async def _clock_loop(self, epoch):
        while self._mounted and epoch == self._epoch:
            self.widgets.refresh_tasks()
            if self.refresh_clock():
                try:
                    self._host.update(self.greeting, self.date, self.clock)
                except RuntimeError:
                    return  # Detached renderer: never keep polling an old page.
            await asyncio.sleep(1)
