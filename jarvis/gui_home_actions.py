"""Three real Home actions. Native controls, finite transitions, no extra frame loop."""
import asyncio
from functools import partial

import flet as ft


def entered(event):
    value = getattr(event, "data", False)
    return value is True or str(value).lower() == "true"


class PhoenixActions(ft.Container):
    """Same 300px footprint as the aura; one shared pointer zone bridges buttons."""
    def __init__(self, gui, aura):
        from jarvis import gui as ui
        self.gui, self.aura = gui, aura
        self.opened = False
        self._inside = False
        self._focused = None
        self._keyboard = False
        self._mounted = False
        self._host = None
        self._close_task = None
        self._epoch = 0
        p = ui.P
        self.guide = ft.Container(width=252, height=252, left=24, top=24,
            border_radius=126, border=ft.Border.all(1, ft.Colors.with_opacity(.22, p.brand)),
            opacity=0, ignore_interactions=True)
        self.hint = ft.Text("", size=11, color=p.text_dim, text_align=ft.TextAlign.CENTER)
        self.caption = ft.Container(self.hint, left=44, right=44, bottom=10,
            alignment=ft.Alignment.CENTER, opacity=0, ignore_interactions=True)
        # A normal focusable button overlays only the bird, not its animated canvas.
        self.center = ft.IconButton(icon=ft.Container(width=1, height=1), icon_color=ft.Colors.TRANSPARENT,
            width=120, height=120, padding=0,
            style=ft.ButtonStyle(shape=ft.CircleBorder(), overlay_color=ft.Colors.TRANSPARENT),
            focus_color=ft.Colors.with_opacity(.10, p.brand),
            hover_color=ft.Colors.TRANSPARENT, splash_color=ft.Colors.TRANSPARENT,
            on_hover=self._center_hover, on_click=self._toggle,
            on_focus=partial(self._focus, "center"), on_blur=partial(self._blur, "center"))
        trigger = ft.Container(ft.Semantics(content=self.center, label="Действия Феникса", button=True),
                               width=120, height=120, left=90, top=90)
        self.buttons, self.slots, self.semantics = {}, {}, {}
        placements = (("dialog", ft.Icons.CHAT_BUBBLE_OUTLINE, 126, 4),
                      ("mic", ft.Icons.MIC_NONE, 14, 184),
                      ("stop", ft.Icons.STOP_ROUNDED, 238, 184))
        for key, icon, x, y in placements:
            button = ft.IconButton(icon=icon, width=48, height=48, icon_size=22,
                icon_color=p.brand, bgcolor=p.bg_card,
                disabled_color=p.text_dim, hover_color=p.selected, focus_color=p.selected,
                style=ft.ButtonStyle(shape=ft.CircleBorder(), side=ft.BorderSide(1, p.border)),
                on_click=partial(self._act, key),
                on_focus=partial(self._focus, key), on_blur=partial(self._blur, key))
            self.buttons[key] = button
            self.semantics[key] = ft.Semantics(content=button, button=True, hidden=True)
            self.slots[key] = ft.Container(self.semantics[key], width=48, height=48, left=x, top=y,
                border_radius=24, opacity=0, scale=.86, ignore_interactions=True,
                on_hover=partial(self._action_hover, key),
                shadow=ft.BoxShadow(blur_radius=16, color=ft.Colors.with_opacity(.12, p.brand)))
        super().__init__(ft.Stack([aura, self.guide, trigger, *self.slots.values(), self.caption],
            width=300, height=300), width=300, height=300, on_hover=self._zone_hover)
        self._sync_motion()
        self.sync_state()

    def _sync_motion(self):
        motion = self.aura.motion_allowed()
        fade = ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC) if motion else None
        for item in (self.guide, self.caption, *self.slots.values()):
            item.animate_opacity = fade
        for item in self.slots.values():
            item.animate_scale = fade

    def _update(self):
        if self._mounted and self._host is not None:
            try:
                self._host.update(self)
            except RuntimeError:
                self.dispose()

    def _labels(self):
        core = self.gui.jarvis
        listening = bool(getattr(core, "listening_enabled", False))
        return {"dialog": "Открыть диалог",
                "mic": "Выключить микрофон" if listening else "Включить микрофон",
                "stop": "Остановить речь" if self.gui._state == "speaking" else "Сейчас нет озвучки"}

    def sync_state(self):
        from jarvis import gui as ui
        core = self.gui.jarvis
        labels = self._labels()
        snapshot = (self.opened, core is not None, bool(getattr(core, "listening_enabled", False)),
                    self.gui._state == "speaking")
        if getattr(self, "_state_snapshot", None) == snapshot:
            return
        self._state_snapshot = snapshot
        for key, button in self.buttons.items():
            self.semantics[key].label = labels[key] if core is not None or key == "dialog" else "Ядро ещё не готово"
            self.semantics[key].hidden = not self.opened
            self.semantics[key].toggled = snapshot[2] if key == "mic" else None
            button.disabled = (not self.opened or (key != "dialog" and core is None)
                               or (key == "stop" and self.gui._state != "speaking"))
            button.icon_color = ui.P.text_dim if button.disabled else ui.P.brand
        self.buttons["mic"].icon = ft.Icons.MIC_NONE if snapshot[2] else ft.Icons.MIC_OFF_OUTLINED
        self.buttons["mic"].icon_color = (ui.P.text_dim if self.buttons["mic"].disabled
                                          else ui.P.brand if snapshot[2] else ui.P.error)
        if self._focused in labels:
            self.hint.value = labels[self._focused]
        self._update()

    def set_open(self, value):
        self._cancel_close()
        value = bool(value)
        if self.opened == value:
            return
        self._sync_motion()
        self.opened = value
        for item in (self.guide, self.caption, *self.slots.values()):
            item.opacity = 1 if value else 0
        for item in self.slots.values():
            item.scale = 1 if value else .86
            item.ignore_interactions = not value
        if value:
            self.hint.value = "Выбери действие"
        self.sync_state()

    def _toggle(self, e=None):
        # Pointer hover may already have opened it before the click arrives.
        self.set_open(True)

    def _center_hover(self, e):
        self._keyboard = False
        if entered(e):
            self._inside = True
            self.set_open(True)

    def _zone_hover(self, e):
        self._keyboard = False
        self._inside = entered(e)
        if self._inside:
            self._cancel_close()
        else:
            self._schedule_close()

    def _action_hover(self, key, e):
        self._keyboard = False
        if entered(e):
            self._cancel_close()
            self.hint.value = self.semantics[key].label
        else:
            self.hint.value = "Выбери действие"
        self._update()

    def _focus(self, key, e=None):
        self._focused = key
        self._cancel_close()
        if self._keyboard:
            self.set_open(True)
        if self.opened:
            self.hint.value = self._labels().get(key, "Выбери действие")
            self._update()

    def _blur(self, key, e=None):
        if self._focused == key:
            self._focused = None
        self._schedule_close()

    async def on_key(self, e):
        if e.key == "Tab":
            self._keyboard = True
        elif e.key == "Escape" and self.opened:
            self.set_open(False)
            self._keyboard = False  # focusing the trigger must not reopen it
            if self._mounted:
                await self.center.focus()
            return True
        return False

    def _act(self, key, e=None):
        # Handler guard too: stale clicks after state changes must do nothing.
        if not self.opened or self.buttons[key].disabled:
            return
        if key == "dialog":
            self.set_open(False)
            self.gui._select_tab(0)
        elif key == "mic":
            self.gui._on_mic_toggle(e)
            self.sync_state()
            self.hint.value = "Микрофон включён" if self.gui.jarvis.listening_enabled else "Микрофон на паузе"
            self._update()
        elif key == "stop" and self.gui._state == "speaking":
            self.gui._on_stop_speech(e)
            self.hint.value = "Озвучка остановлена"
            self._update()

    def _cancel_close(self):
        self._epoch += 1
        if self._close_task is not None:
            self._close_task.cancel()
            self._close_task = None

    def _schedule_close(self):
        self._cancel_close()
        if self._mounted and self.opened:
            self._close_task = self._host.run_task(self._close_later, self._epoch)

    async def _close_later(self, epoch):
        await asyncio.sleep(.24)
        if epoch == self._epoch and not self._inside and not (self._keyboard and self._focused):
            self._close_task = None
            self.set_open(False)

    def did_mount(self):
        self._mounted, self._host = True, self.page

    def will_unmount(self):
        self.dispose()

    def dispose(self):
        self._mounted = False
        self.set_open(False)
        self._cancel_close()
        self._inside = False
        self._focused = None
        self._keyboard = False
        self._host = None
