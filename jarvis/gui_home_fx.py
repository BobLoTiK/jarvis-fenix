"""Bounded native solar aura. Decorative state motion, never a fake waveform."""
import asyncio
import logging
import math
import time

import flet as ft
import flet.canvas as cv

log = logging.getLogger(__name__)
FPS = 24
IDLE_FPS = 16
MODES = ("idle", "listening", "speaking", "thinking")
SIZE = 300
CENTER = SIZE / 2


def transition_weights(current, target, dt):
    """Time-based easing; an interrupted transition continues from the current mix."""
    tau = .50 if target == "idle" else .28
    alpha = -math.expm1(-max(0, min(.1, dt)) / tau)
    return {mode: value + ((1.0 if mode == target else 0.0) - value) * alpha
            for mode, value in current.items()}


def solar_shapes(mode, seconds, energy, color, *, weights=None, phase=None):
    """Fixed topology: all layers persist and fade, rather than popping in/out."""
    if mode not in MODES:
        return []
    w = weights if weights is not None else {m: float(m == mode) for m in MODES}
    listening, speaking = w["listening"], w["speaking"]
    speed = sum(w[m] * v for m,v in zip(MODES, (.85, 2.1, 2.8, 1.35)))
    phase = seconds * speed if phase is None else phase
    pulse = .5 + .5 * math.sin(phase)
    strength = sum(w[m] * v for m,v in zip(MODES, (.32, .66, .84, .37))) + .10*pulse + .10*energy*listening
    amplitude = sum(w[m] * v for m,v in zip(MODES, (3.0, 6.5, 9.0, 3.8))) + 1.2*energy*listening
    shapes = []
    def paint(alpha, width=1, fill=False):
        return ft.Paint(color=ft.Colors.with_opacity(max(0, min(1, alpha)), color),
            style=ft.PaintingStyle.FILL if fill else ft.PaintingStyle.STROKE,
            stroke_width=width, stroke_cap=ft.StrokeCap.ROUND, stroke_join=ft.StrokeJoin.ROUND)
    radius = 116 + 2.2*pulse
    for width, alpha in ((29, .03), (17, .05), (7, .08), (1.2, .25)):
        shapes.append(cv.Circle(CENTER, CENTER, radius, paint(strength * alpha, width)))
    # Stronger travelling waves; geometry, brightness and extra layers all ease.
    for layer, visibility in enumerate((1.0, listening + speaking, speaking)):
        points = []
        for i in range(121):
            a = 2*math.pi*i/120
            wave = (.65*math.sin(5*a - phase*.65 + layer)
                    + .30*math.sin(8*a + phase*.85 + layer*.7)
                    + .18*math.sin(3*a - phase*1.15))
            swell = .85 + .15*math.sin(phase*.6 + layer)
            r = radius + 4 + layer*3 + wave*amplitude*swell
            points.append((CENTER + r*math.cos(a), CENTER + r*math.sin(a)))
        elements = [cv.Path.MoveTo(*points[0]), *[cv.Path.LineTo(*q) for q in points[1:]]]
        for width, alpha in ((9, .04), (3, .12), (.9, .46)):
            shapes.append(cv.Path(elements, paint(strength*alpha*visibility/(1 + layer*.55), width)))
    for j, visibility in enumerate((1.0, 1.0, speaking)):
        r = radius - 3 + j*6
        shapes.append(cv.Arc(CENTER-r, CENTER-r, 2*r, 2*r,
            phase*.20 + j*2*math.pi/3, .50 + pulse*.18,
            paint=paint(strength*.55*visibility, 1.4)))
    # Waves also continue during speech, fading gently into the idle sun.
    for j in range(3):
        life = (phase*.16 + j/3) % 1
        r = 122 + life*21
        alpha = math.sin(math.pi*life)**2 * (.18*listening + .16*speaking)
        shapes.append(cv.Circle(CENTER, CENTER, r, paint(alpha, .95)))
    for i in range(16):
        life = (phase*.10 + i/16) % 1
        angle = i*2.39996
        r = 121 + 15*life
        x = CENTER + r*math.cos(angle) + 1.6*math.sin(phase*.4 + i)
        y = CENTER + r*math.sin(angle) - 9*life
        alpha = math.sin(math.pi*life)**2 * (.60*speaking + (.08*listening if i < 6 else 0))
        shapes.append(cv.Circle(x, y, .7 + .55*(1-life), paint(alpha, fill=True)))
    return shapes


class PhoenixAura(ft.Container):
    """A quiet ambient sun; one task only on visible Home, louder during activity."""
    def __init__(self, gui, ring):
        self.gui = gui
        self.ring = ring
        self.canvas = cv.Canvas([], width=SIZE, height=SIZE)
        super().__init__(ft.Stack([
            ft.Container(self.canvas, alignment=ft.Alignment.CENTER),
            ft.Container(ring, alignment=ft.Alignment.CENTER),
        ], width=SIZE, height=SIZE, fit=ft.StackFit.EXPAND),
            width=SIZE, height=SIZE, ignore_interactions=True)
        self.mode = "idle"
        self.energy = 0
        self._time_origin = time.monotonic()
        self._last_frame = self._time_origin
        self._phase = 0.0
        self._weights = {mode: float(mode == "idle") for mode in MODES}
        self._visual_energy = 0.0
        self._mounted = False
        self._host = None
        self._future = None
        self._accessibility_future = None
        self._epoch = 0
        self._os_reduced = False
        self._service = None

    def foreground(self):
        from jarvis.gui import HOME_TAB
        rail = getattr(self.gui, "_rail", None)
        window = getattr(getattr(self.gui, "_page", None), "window", None)
        return (getattr(self.gui, "_home_window_visible", True)
                and rail is not None and rail.selected_index == HOME_TAB
                and getattr(window, "visible", True) is not False
                and getattr(window, "minimized", False) is not True)

    def motion_allowed(self):
        rail = getattr(self.gui, "_rail", None)
        return (not self._os_reduced and self.gui.config.get("gui_motion_enabled", True) is not False
                and getattr(rail, "motion_enabled", True))

    def set_mode(self, mode, energy=0):
        self.mode = mode if mode in MODES else "idle"
        self.energy = max(0, min(1, energy))
        # A target change never redraws a mounted animated scene immediately.
        # The single frame loop eases from its current mixture, even on reversal.
        if not self._mounted or not self.motion_allowed():
            self._weights = {m: float(m == self.mode) for m in MODES}
            self._visual_energy = self.energy
            self._draw(0)
        self.sync_motion()

    def sync_motion(self):
        active = self.mode in MODES
        if not (self._mounted and self.foreground() and active and self.motion_allowed()):
            self._stop_motion()
            return
        if self._future is None or self._future.done():
            self._epoch += 1
            self._last_frame = time.monotonic()
            self._future = self._host.run_task(self._animate, self._epoch)

    def _stop_motion(self):
        self._epoch += 1
        if self._future is not None:
            self._future.cancel()
            self._future = None

    def _draw(self, seconds):
        from jarvis import gui as ui
        p = ui.P
        now = time.monotonic()
        dt = max(0, min(.1, now - self._last_frame))
        self._last_frame = now
        if self.motion_allowed():
            self._weights = transition_weights(self._weights, self.mode, dt)
            self._visual_energy += (self.energy-self._visual_energy)*(-math.expm1(-dt/.30))
            speed = sum(self._weights[m]*v for m,v in zip(MODES, (.85, 2.1, 2.8, 1.35)))
            self._phase += speed*dt
        else:
            self._weights = {m: float(m == self.mode) for m in MODES}
            self._visual_energy = self.energy
        self.canvas.shapes = solar_shapes(self.mode, seconds, self._visual_energy, p.brand,
            weights=self._weights, phase=self._phase)
        if self._mounted and self._host is not None:
            try:
                self._host.update(self.canvas)
            except RuntimeError:
                self._stop_motion()

    async def _animate(self, epoch):
        while (self._mounted and epoch == self._epoch and self.foreground()
               and self.motion_allowed() and self.mode in MODES):
            tick = time.monotonic()
            self._draw(tick - self._time_origin)
            settled_idle = self.mode == "idle" and self._weights["idle"] > .995
            fps = IDLE_FPS if settled_idle else FPS
            await asyncio.sleep(max(0, 1 / fps - (time.monotonic() - tick)))

    async def _read_accessibility(self, host):
        try:
            self._service = ft.SemanticsService()
            flags = await asyncio.wait_for(self._service.get_accessibility_features(), 2)
            if self._mounted and host is self._host and (flags.disable_animations or flags.reduce_motion):
                self._os_reduced = True
                self._stop_motion()
                self._draw(0)  # State remains legible, but completely still.
        except Exception:
            log.debug("Home aura: accessibility flags unavailable", exc_info=True)

    def did_mount(self):
        self._mounted, self._host = True, self.page
        self._last_frame = time.monotonic()
        self._draw(time.monotonic() - self._time_origin if self.motion_allowed() else 0)
        self.sync_motion()
        self._accessibility_future = self._host.run_task(self._read_accessibility, self._host)

    def will_unmount(self):
        self.dispose()

    def dispose(self):
        self._mounted = False
        self._stop_motion()
        if self._accessibility_future is not None:
            self._accessibility_future.cancel()
            self._accessibility_future = None
        self._host = None
