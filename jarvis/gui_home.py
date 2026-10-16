"""Minimal native Home: local clock and the real assistant state, no chat/widgets."""
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


from jarvis.gui_home_fx import PhoenixAura
from jarvis.gui_home_actions import PhoenixActions


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
        self.date = ft.Text(size=11, color=p.text_dim)
        self.clock = ft.Text(size=11, color=p.text_dim)
        self.refresh_clock()
        self.status = ft.Text(size=11, color=p.text_dim, text_align=ft.TextAlign.CENTER)
        self.dot = ft.Container(width=5, height=5, border_radius=3, bgcolor=p.brand)
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
        self.header = ft.Container(ft.Row([
            ft.Text("Рабочее пространство  /  Главная", size=12, color=p.text_dim, expand=True),
            ft.Container(ft.Row(self.theme_buttons, spacing=3), padding=4, border_radius=11,
                         bgcolor=p.sidebar, border=ft.Border.all(1, ft.Colors.with_opacity(.5, p.border)))
        ], spacing=12), padding=ft.Padding(left=28, right=28, top=16, bottom=16),
            border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.with_opacity(.5, p.border))))
        self.controls = [self.header, ft.Container(ft.Column([
            ft.Row([ft.Row([ft.Icon(ft.Icons.WB_SUNNY_OUTLINED, size=14, color=p.text_dim), self.date], spacing=8),
                    self.clock], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(ft.Column([self.actions,
                ft.Row([self.dot, self.status], spacing=8, alignment=ft.MainAxisAlignment.CENTER)
            ], spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.Alignment.CENTER, expand=True),
            ft.Text("Просто твоё пространство.", size=10, color=p.text_dim),
        ], expand=True, spacing=20), padding=ft.Padding(left=28, right=28, top=26, bottom=24), expand=True)]
        self.apply_state(gui._state)

    def _theme(self, name):
        self.gui._on_theme_change(SimpleNamespace(control=SimpleNamespace(value=name)))

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
        date, clock = clock_labels(now or datetime.now())
        changed = self.date.value != date or self.clock.value != clock
        self.date.value, self.clock.value = date, clock
        return changed

    def did_mount(self):
        self._mounted = True
        self._host = self.page
        self._epoch += 1
        self._future = self._host.run_task(self._clock_loop, self._epoch)

    def will_unmount(self):
        self.dispose()

    def dispose(self):
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
            if self.refresh_clock():
                try:
                    self._host.update(self.date, self.clock)
                except RuntimeError:
                    return  # Detached renderer: never keep polling an old page.
            await asyncio.sleep(1)
