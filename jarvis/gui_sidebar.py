"""Native, persistent hover rail. Bounded UI-loop animation; no WebView or threads.

Expanded panels reserve space on hover at every window width; never overlay.
The copper stroke is a sampled rounded-rectangle path on a native Flet Canvas.
"""
import asyncio
from functools import partial
import logging
import math
import time

import flet as ft
import flet.canvas as cv

log = logging.getLogger(__name__)
COMPACT = 76
EXPANDED = 252
HEIGHT = 48


def _ui():
    from jarvis import gui
    return gui


def mix(first, second, weight=.65):
    """Same-hue hover: selected surface mixed with card, never a copper fill."""
    rgb = [round(int(first[i:i + 2], 16) * weight +
                 int(second[i:i + 2], 16) * (1 - weight)) for i in (1, 3, 5)]
    return "#" + "".join(f"{v:02x}" for v in rgb)


def rounded_outline(width, height=HEIGHT, radius=10):
    """Evenly sample straight edges and quarter-circles inside a one-pixel inset."""
    x0, y0, x1, y1 = 1.5, 1.5, width - 1.5, height - 1.5
    r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
    points = []
    def edge(a, b):
        steps = max(1, math.ceil(math.dist(a, b) / 3))
        points.extend((a[0] + (b[0] - a[0]) * j / steps,
                       a[1] + (b[1] - a[1]) * j / steps) for j in range(steps))
    def arc(cx, cy, angle):
        steps = max(4, math.ceil(math.pi * r / 6))
        points.extend((cx + r * math.cos(angle + math.pi / 2 * j / steps),
                       cy + r * math.sin(angle + math.pi / 2 * j / steps))
                      for j in range(steps))
    edge((x0 + r, y0), (x1 - r, y0)); arc(x1 - r, y0 + r, -math.pi / 2)
    edge((x1, y0 + r), (x1, y1 - r)); arc(x1 - r, y1 - r, 0)
    edge((x1 - r, y1), (x0 + r, y1)); arc(x0 + r, y1 - r, math.pi / 2)
    edge((x0, y1 - r), (x0, y0 + r)); arc(x0 + r, y0 + r, math.pi)
    return points


def stroke_shapes(width, progress, color):
    """A finite short head with a soft tail, moving once around the perimeter."""
    pts = rounded_outline(max(48, width))
    head = int(progress * len(pts))
    shapes = []
    length = max(5, round(len(pts) * .115))
    fade = min(1, progress / .1, (1 - progress) / .12)
    if fade <= 0:
        return shapes
    for part in range(3):
        lo = head - length + part * length // 3
        hi = head - length + (part + 1) * length // 3
        segment = [pts[j % len(pts)] for j in range(lo, hi + 1)]
        alpha = min(1, max(0, fade * (.22, .50, 1)[part]))
        shapes.append(cv.Path([
            cv.Path.MoveTo(*segment[0]), *[cv.Path.LineTo(*p) for p in segment[1:]]],
            paint=ft.Paint(color=ft.Colors.with_opacity(alpha, color),
                style=ft.PaintingStyle.STROKE, stroke_width=1.7,
                stroke_cap=ft.StrokeCap.ROUND, stroke_join=ft.StrokeJoin.ROUND)))
    return shapes


def entered(event):
    return getattr(event, "data", False) in (True, "true", "True")


class Sidebar(ft.Container):
    def __init__(self, on_select, config=None):
        super().__init__(width=COMPACT, padding=ft.Padding.symmetric(horizontal=12, vertical=20),
                         clip_behavior=ft.ClipBehavior.HARD_EDGE)
        self._on_select = on_select
        self.config = config
        self.pinned = bool(config and config.get("gui_sidebar_pinned", False) is True)
        self.expanded = self.pinned
        self.motion_enabled = not config or config.get("gui_motion_enabled", True) is not False
        self._selected_index = 0
        self._hovered = None
        self._focused = None
        self._keyboard_navigation = False
        self._pointer_inside = False
        self._mounted = False
        self._host = None
        self._tasks = {}
        self._epoch = 0
        self._reserve = None
        self._canvas_widths = {}
        self._service = None
        self.on_hover = self._on_panel_hover
        self.refresh_palette()

    def layout(self, content):
        self._reserve = ft.Container(width=self._content_width(),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT_CUBIC) if self.motion_enabled else None)
        self.left = self.top = self.bottom = 0
        return ft.Stack([
            ft.Row([self._reserve, content], spacing=0, expand=True), self,
        ], expand=True, fit=ft.StackFit.EXPAND)

    def _content_width(self):
        return EXPANDED if self.expanded else COMPACT

    def _sync_reserve(self):
        if self._reserve is not None:
            self._reserve.width = self._content_width()
            self._reserve.animate = ft.Animation(200, ft.AnimationCurve.EASE_OUT_CUBIC) if self.motion_enabled else None

    def did_mount(self):
        self._mounted = True
        self._host = self.page
        self._schedule("accessibility", self._read_accessibility)

    def will_unmount(self):
        self.dispose()

    def dispose(self):
        self._mounted = False
        self._epoch += 1
        for future in self._tasks.values():
            future.cancel()
        self._tasks.clear()
        self._host = None

    def _cancel(self, key):
        future = self._tasks.pop(key, None)
        if future is not None:
            future.cancel()

    def _schedule(self, key, handler, *args):
        self._cancel(key)
        if self._mounted and self._host is not None:
            self._tasks[key] = self._host.run_task(handler, *args)

    def _update(self, *controls):
        if self._mounted:
            try:
                self._host.update(*(controls or (self,)))
            except RuntimeError:
                if self._mounted:
                    log.exception("Sidebar update failed")

    async def _read_accessibility(self):
        # Supported Flet service; no Windows registry probing or polling loop.
        try:
            self._service = ft.SemanticsService()
            flags = await asyncio.wait_for(self._service.get_accessibility_features(), 2)
            if flags.disable_animations or flags.reduce_motion:
                self.set_motion(False)
        except Exception:
            log.debug("Sidebar: accessibility flags unavailable", exc_info=True)

    def set_motion(self, enabled):
        self.motion_enabled = bool(enabled)
        self.animate = ft.Animation(200, ft.AnimationCurve.EASE_OUT_CUBIC) if enabled else None
        if not enabled:
            self._cancel("stroke")
            for canvas in self.canvases:
                canvas.shapes = []
        for icon in self.icon_controls:
            icon.animate_scale = 160 if enabled else None
            if not enabled:
                icon.scale = 1
        self._sync_reserve()
        self._update(self, *([self._reserve] if self._reserve is not None else []))

    @property
    def selected_index(self):
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value):
        if not 0 <= value < len(self.nav_buttons):
            return
        self._selected_index = value
        self._sync_buttons()

    def refresh_palette(self):
        self._epoch += 1
        self._cancel("stroke")
        self._cancel("open")
        self._cancel("close")
        self._keyboard_navigation = False
        self._hovered = None
        self._focused = None
        ui, p = _ui(), _ui().P
        self.bgcolor = p.sidebar
        self.border = ft.Border(right=ft.BorderSide(1, p.border))
        self.width = EXPANDED if self.expanded else COMPACT
        self.animate = ft.Animation(200, ft.AnimationCurve.EASE_OUT_CUBIC) if self.motion_enabled else None
        self.nav_buttons, self.canvases, self.icon_controls = [], [], []
        self.labels, self.dots, self.markers = [], [], []
        self._canvas_widths = {}
        for index, (label, _) in enumerate(ui.NAV_ITEMS):
            image = (ft.Icon(ft.Icons.HOME_OUTLINED, size=24, color=p.brand) if index == ui.HOME_TAB else
                     ui._brand_image(("dialog", "microphone", "audio", "persona", "settings", "commands")[index], 24))
            icon = ft.Container(image, width=24, height=24, animate_scale=160 if self.motion_enabled else None)
            caption = ft.Text(label, size=14, color=p.text, expand=True, no_wrap=True)
            dot = ft.Container(width=5, height=5, border_radius=3, bgcolor=p.brand)
            marker = ft.Container(left=0, top=16, height=16, width=3, border_radius=2, bgcolor=p.brand,
                                  ignore_interactions=True)
            canvas = cv.Canvas([], expand=True,
                               on_resize=partial(self._on_canvas_resize, index), resize_interval=40)
            content = ft.Stack([
                ft.Container(ft.Row([icon, caption, dot], spacing=14), height=HEIGHT,
                             padding=ft.Padding.symmetric(horizontal=13)),
                marker, ft.Container(canvas, left=0, right=0, top=0, bottom=0,
                                     ignore_interactions=True),
            ], height=HEIGHT, fit=ft.StackFit.EXPAND)
            button = ft.Button(content=content, height=HEIGHT,
                width=self.width - 24, elevation=0, tooltip=label,
                on_click=partial(self._click, index),
                on_hover=partial(self._on_nav_hover, index),
                on_focus=partial(self._on_focus, index), on_blur=partial(self._on_blur, index))
            self.nav_buttons.append(button); self.canvases.append(canvas)
            self.icon_controls.append(icon); self.labels.append(caption)
            self.dots.append(dot); self.markers.append(marker)
        self.title_block = ft.Column([
            ft.Text("Феникс", size=21, weight=ft.FontWeight.BOLD, color=p.text, no_wrap=True),
            ft.Text("Локальный ассистент", size=12, color=p.text_dim, no_wrap=True),
        ], spacing=2, expand=True)
        self.logo_button = ft.Button(content=ft.Row([
            ui._brand_image("phoenix", 38, "Феникс"), self.title_block], spacing=12),
            width=self.width - 24, height=64, elevation=0,
            style=ft.ButtonStyle(padding=6, bgcolor=ft.Colors.TRANSPARENT,
                overlay_color=ft.Colors.TRANSPARENT, shape=ft.RoundedRectangleBorder(radius=10)),
            on_click=self._toggle, on_focus=partial(self._on_focus, -1),
            on_blur=partial(self._on_blur, -1))
        self.pin_label = ft.Text("Открепить панель" if self.pinned else "Закрепить панель",
                                  size=14, color=p.text_dim, no_wrap=True)
        self.pin_icon = ft.Icon(ft.Icons.PUSH_PIN if self.pinned else ft.Icons.PUSH_PIN_OUTLINED,
                               size=22, color=p.brand if self.pinned else p.text_dim)
        self.pin_button = ft.Button(content=ft.Row([self.pin_icon, self.pin_label], spacing=14),
            width=self.width - 24, height=44, elevation=0,
            style=ft.ButtonStyle(padding=13, bgcolor=ft.Colors.TRANSPARENT,
                overlay_color=ft.Colors.with_opacity(.07, p.text),
                shape=ft.RoundedRectangleBorder(radius=8)),
            tooltip=self.pin_label.value, on_click=self._toggle_pin,
            on_focus=partial(self._on_focus, -2), on_blur=partial(self._on_blur, -2))
        from jarvis import profile
        name = str(profile.current())
        self.profile_label = ft.Text(name, size=14, color=p.text, max_lines=1, no_wrap=True,
                                     overflow=ft.TextOverflow.ELLIPSIS)
        self.profile_details = ft.Column([self.profile_label,
            ft.Text("Профиль и настройки", size=12, color=p.text_dim, no_wrap=True)], spacing=4, expand=True)
        avatar = ft.Container(ft.Text(name[:1].upper(), color=p.brand, size=14),
            width=46, height=46, border=ft.Border.all(1, p.border),
            border_radius=12, alignment=ft.Alignment.CENTER, tooltip=name)
        self.profile_block = ft.Container(ft.Row([avatar, self.profile_details], spacing=14),
                                          padding=ft.Padding.only(top=12))
        # Positioned fixed-width inner column is clipped by the animated outer rail.
        self.navigation = ft.Column([self.nav_buttons[i] for i in ui.NAV_ORDER], spacing=8, expand=True,
                                    scroll=ft.ScrollMode.AUTO)
        column = ft.Column([
            self.logo_button, ft.Container(height=20), self.navigation, self.pin_button,
            ft.Divider(color=p.border, height=12), self.profile_block,
        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.START, expand=True)
        self.content = ft.Stack([ft.Container(column, left=0, top=0, bottom=0,
                                               width=EXPANDED - 24)], expand=True)
        self._sync_expansion()
        self._sync_buttons()

    def _sync_buttons(self):
        p = _ui().P
        for index, button in enumerate(self.nav_buttons):
            active, hovered = index == self._selected_index, index == self._hovered
            fill = p.selected if active else mix(p.selected, p.bg_card) if hovered else p.sidebar
            button.bgcolor = fill
            button.style = ft.ButtonStyle(
                padding=0, animation_duration=140 if self.motion_enabled else 0,
                overlay_color=ft.Colors.TRANSPARENT,
                bgcolor={ft.ControlState.DEFAULT: fill, ft.ControlState.HOVERED:
                         p.selected if active else mix(p.selected, p.bg_card)},
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, p.border if hovered else ft.Colors.TRANSPARENT),
                      ft.ControlState.HOVERED: ft.BorderSide(1, p.border),
                      ft.ControlState.FOCUSED: ft.BorderSide(2, p.accent)},
                shape=ft.RoundedRectangleBorder(radius=10))
            self.labels[index].color = p.text if active or hovered else p.text_dim
            self.markers[index].visible = active
            self.dots[index].visible = active and self.expanded
            self.icon_controls[index].scale = 1.06 if hovered and self.motion_enabled else 1

    def _sync_expansion(self):
        width = EXPANDED if self.expanded else COMPACT
        self.width = width
        for button in [self.logo_button, self.pin_button, *self.nav_buttons]:
            button.width = width - 24
        for label in [self.title_block, self.pin_label, self.profile_details, *self.labels]:
            label.visible = self.expanded
        self.logo_button.tooltip = "Свернуть панель" if self.expanded else "Раскрыть панель"
        self._sync_buttons()

    def _set_expanded(self, expanded):
        expanded = bool(expanded or self.pinned)
        if expanded == self.expanded:
            return
        self._cancel("stroke")
        for canvas in self.canvases:
            canvas.shapes = []
        self.expanded = expanded
        self._sync_expansion()
        self._sync_reserve()
        self._update(self, *([self._reserve] if self._reserve is not None else []))
        if self._hovered is not None and self.motion_enabled:
            self._schedule("stroke", self._stroke_once, self._hovered, self._epoch)

    def _click(self, index, e=None):
        self._keyboard_navigation = False
        self._on_select(index)

    async def _toggle(self, e=None):
        self._keyboard_navigation = False
        self._cancel("open"); self._cancel("close")
        self._set_expanded(not self.expanded)

    async def _toggle_pin(self, e=None):
        desired = not self.pinned
        if self.config and self.config.set("gui_sidebar_pinned", desired) is False:
            self.pin_button.tooltip = "Не удалось сохранить закрепление. Попробуйте ещё раз."
            self._update(self.pin_button)
            return
        self.pinned = desired
        self._keyboard_navigation = False
        self._cancel("open"); self._cancel("close")
        self.pin_label.value = "Открепить панель" if desired else "Закрепить панель"
        self.pin_button.tooltip = self.pin_label.value
        p = _ui().P
        self.pin_icon.name = ft.Icons.PUSH_PIN if desired else ft.Icons.PUSH_PIN_OUTLINED
        self.pin_icon.color = p.brand if desired else p.text_dim
        self._sync_reserve()
        self._set_expanded(True)
        self._update(self, *([self._reserve] if self._reserve is not None else []))
        if not desired and not self._pointer_inside:
            self._schedule("close", self._close_later)

    async def _on_panel_hover(self, e):
        self._pointer_inside = entered(e)
        self._keyboard_navigation = False
        self._cancel("open"); self._cancel("close")
        if self._pointer_inside:
            self._schedule("open", self._open_later)
        elif not self.pinned:
            self._schedule("close", self._close_later)

    async def _open_later(self):
        await asyncio.sleep(.1)
        if self._pointer_inside:
            self._set_expanded(True)

    async def _close_later(self):
        await asyncio.sleep(.32)
        if not self.pinned and not self._pointer_inside and not (
                self._keyboard_navigation and self._focused is not None):
            self._set_expanded(False)

    async def _on_focus(self, index, e=None):
        self._focused = index
        if self._keyboard_navigation:
            self._cancel("close")
            self._set_expanded(True)

    async def _on_blur(self, index, e=None):
        if self._focused == index:
            self._focused = None
        if not self._pointer_inside:
            self._schedule("close", self._close_later)

    async def on_key(self, e):
        if e.key == "Tab":
            self._keyboard_navigation = True
        elif e.key == "Escape" and not self.pinned and self.expanded:
            self._keyboard_navigation = False
            self._cancel("open"); self._cancel("close")
            self._set_expanded(False)

    async def _on_canvas_resize(self, index, e):
        self._canvas_widths[index] = e.width

    async def _on_nav_hover(self, index, e):
        if not entered(e) and self._hovered != index:
            return
        self._keyboard_navigation = False
        self._cancel("stroke")
        for canvas in self.canvases:
            canvas.shapes = []
        if entered(e):
            self._hovered = index
            if self.motion_enabled:
                self._schedule("stroke", self._stroke_once, index, self._epoch)
        elif self._hovered == index:
            self._hovered = None
        self._sync_buttons()
        self._update()

    async def _stroke_once(self, index, epoch):
        # Wait for the expansion to settle so the stroke follows the final outline.
        await asyncio.sleep(.32)
        if not self._stroke_valid(index, epoch):
            return
        canvas = self.canvases[index]
        started = time.monotonic()
        try:
            while self._stroke_valid(index, epoch):
                progress = min(1, (time.monotonic() - started) / .85)
                width = self._canvas_widths.get(index, self.width - 24)
                canvas.shapes = stroke_shapes(width, progress, _ui().P.brand)
                self._update(canvas)
                if progress >= 1:
                    break
                await asyncio.sleep(1 / 30)
        finally:
            if self._mounted and epoch == self._epoch:
                canvas.shapes = []
                self._update(canvas)

    def _stroke_valid(self, index, epoch):
        return (self._mounted and self.motion_enabled and self._hovered == index
                and epoch == self._epoch)
