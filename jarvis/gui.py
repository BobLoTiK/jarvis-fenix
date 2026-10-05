"""GUI Феникса — интерактивное окно на Flet 1.0.3.

Архитектура:
    Jarvis → очередь (queue.Queue) → Flet worker (page.run_task) → обновление UI.
    Обратно: UI → callback → Jarvis.

Связь с Jarvis:
    GUI → Jarvis: callbacks (on_mode_change, on_voice_change, ...)
    Jarvis → GUI: gui.add_message(...), gui.set_state(...), gui.add_stream_chunk(...)
"""

import asyncio
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import flet as ft

log = logging.getLogger("jarvis.gui")

# --- Палитра (глубокая тёмная) ---
BG_DARK = "#0e1116"
BG_CARD = "#161b22"
BG_BUBBLE_USER = "#1f6feb"
BG_BUBBLE_AI = "#21262d"
ACCENT = "#58a6ff"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"

# --- Состояния: (цвет, название, подпись) ---
STATES = {
    "idle":      ("#484f58", "Спит",   "Жду «Феникс»"),
    "listening": ("#d29922", "Слушаю", "Слушаю команду"),
    "speaking":  ("#3fb950", "Говорю", "Отвечаю"),
    "error":     ("#f85149", "Ошибка", "Проверь логи"),
}

THEMES = {
    "Тёмная": ft.ThemeMode.DARK,
    "Светлая": ft.ThemeMode.LIGHT,
    "Системная": ft.ThemeMode.SYSTEM,
}

LLM_MODELS = [
    "qwen2.5:0.5b", "qwen2.5:1.5b-instruct", "qwen2.5:3b-instruct",
    "qwen2.5:7b-instruct", "qwen2.5:14b-instruct", "qwen2.5:32b-instruct",
    "gemma2:2b", "gemma2:9b", "llama3.1:8b", "mistral:7b",
]

TTS_BACKENDS = ["auto", "piper", "xtts", "winrt", "sapi"]


class FenixGUI:
    """Окно Феникса на Flet."""

    def __init__(self, jarvis, config):
        self.jarvis = jarvis
        self.config = config
        self._queue = queue.Queue()
        self._thread = None
        self._running = False

        # Состояние
        self._state = "idle"
        self._stream_bubble = None
        self._stream_text = ""
        self._stream_label = None

        # Ссылки на контролы
        self._status_circle = None
        self._status_text = None
        self._status_sub = None
        self._history_list = None
        self._input_field = None
        self._mic_btn = None
        self._content_area = None
        self._rail = None

        self._page = None

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gui")
        self._thread.start()
        log.info("GUI (Flet) запущен в потоке")

    def run_main(self) -> None:
        """Запускает Flet в ТЕКУЩЕМ (главном) потоке."""
        if self._running:
            return
        self._running = True
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        self._queue.put(("stop", None))

    def add_message(self, role: str, text: str) -> None:
        self._queue.put(("message", (role, text)))

    def add_stream_chunk(self, chunk: str) -> None:
        self._queue.put(("stream_chunk", chunk))

    def end_stream(self) -> None:
        self._queue.put(("stream_end", None))

    def set_state(self, state: str) -> None:
        self._queue.put(("state", state))

    # ---------------------------------------------------------------
    # Flet
    # ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def _main(self, page: ft.Page) -> None:
        self._page = page
        page.title = "Феникс"
        page.window.width = 1100
        page.window.height = 760
        page.window.min_width = 900
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.bgcolor = BG_DARK
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            font_family="Segoe UI",
        )

        x = self.config.get("gui_x")
        y = self.config.get("gui_y")
        if x is not None and y is not None:
            page.window.left = x
            page.window.top = y

        self._build_ui(page)
        page.run_task(self._process_queue)

    def _build_ui(self, page: ft.Page) -> None:
        # --- NavigationRail ---
        self._rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=90,
            min_extended_width=200,
            bgcolor=BG_CARD,
            indicator_color=ACCENT,
            group_alignment=-1.0,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME,
                    label="Главная",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.MIC_NONE,
                    selected_icon=ft.Icons.MIC,
                    label="Микрофон",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Настройки",
                ),
            ],
            on_change=self._on_nav_change,
        )

        # --- Кешированные разделы ---
        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_settings_tab(),
        }

        self._content_area = ft.Container(
            content=self._tabs[0],
            expand=True,
            padding=0,
            bgcolor=BG_DARK,
        )

        page.add(
            ft.Row(
                controls=[
                    self._rail,
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            )
        )

    # ---------------------------------------------------------------
    # Главная
    # ---------------------------------------------------------------

    def _build_main_tab(self) -> ft.Control:
        # --- Статус ---
        # Сфера с анимацией
        self._status_circle = ft.Container(
            width=80,
            height=80,
            border_radius=40,
            bgcolor="#484f58",
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            shadow=ft.BoxShadow(
                blur_radius=20,
                color="#484f58",
                spread_radius=2,
            ),
        )

        self._status_text = ft.Text(
            "Спит", size=24, weight=ft.FontWeight.BOLD, color=TEXT,
        )
        self._status_sub = ft.Text(
            "Жду «Феникс»", size=13, color=TEXT_DIM,
        )

        status_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self._status_circle,
                    ft.Column(
                        controls=[self._status_text, self._status_sub],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=20,
            ),
            padding=ft.Padding(left=30, top=25, right=30, bottom=20),
        )

        # --- Контролы ---
        controls_bar = self._build_controls()

        # --- История ---
        self._history_list = ft.ListView(
            spacing=10,
            auto_scroll=True,
            expand=True,
        )
        history_container = ft.Container(
            content=self._history_list,
            expand=True,
            padding=ft.Padding(left=30, right=30, top=10, bottom=10),
        )

        # --- Ввод ---
        input_bar = self._build_input()

        return ft.Column(
            controls=[
                status_bar,
                controls_bar,
                history_container,
                input_bar,
            ],
            spacing=0,
            expand=True,
        )

    def _build_controls(self) -> ft.Container:
        """Режим / голос / память."""

        def _label(text):
            return ft.Text(text, width=80, color=TEXT_DIM, size=13)

        # Режим
        mode_row = ft.Row(
            controls=[
                _label("Режим:"),
                ft.RadioGroup(
                    value=self.config.get("mode", "combo"),
                    on_change=self._on_mode_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="commands", label="Команды", active_color=ACCENT),
                            ft.Radio(value="llm", label="ИИ", active_color=ACCENT),
                            ft.Radio(value="combo", label="Комбо", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        # Голос
        voice_row = ft.Row(
            controls=[
                _label("Голос:"),
                ft.Dropdown(
                    value=self.config.get("tts_voice", "ruslan"),
                    options=[
                        ft.dropdown.Option("ruslan"),
                        ft.dropdown.Option("dmitri"),
                        ft.dropdown.Option("irina"),
                        ft.dropdown.Option("denis"),
                    ],
                    width=160,
                    border_color="#30363d",
                    focused_border_color=ACCENT,
                    text_size=13,
                    on_select=self._on_voice_change,
                ),
            ],
            spacing=10,
        )

        # Память
        mm = self.config.get("memory_max", 100)
        mem_value = {40: "short", 100: "normal", 200: "long"}.get(mm, "normal")
        mem_row = ft.Row(
            controls=[
                _label("Память:"),
                ft.RadioGroup(
                    value=mem_value,
                    on_change=self._on_memory_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="short", label="Короткая", active_color=ACCENT),
                            ft.Radio(value="normal", label="Обычная", active_color=ACCENT),
                            ft.Radio(value="long", label="Долгая", active_color=ACCENT),
                        ],
                        spacing=10,
                    ),
                ),
            ],
            spacing=10,
        )

        return ft.Container(
            content=ft.Column(
                controls=[mode_row, voice_row, mem_row],
                spacing=12,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=15),
        )

    def _build_input(self) -> ft.Container:
        self._input_field = ft.TextField(
            hint_text="Напишите команду...",
            expand=True,
            border_radius=24,
            border_color="#30363d",
            focused_border_color=ACCENT,
            bgcolor=BG_CARD,
            text_size=14,
            content_padding=ft.Padding(left=20, right=20, top=14, bottom=14),
            on_submit=self._on_send,
        )

        self._mic_btn = ft.IconButton(
            icon=ft.Icons.MIC,
            icon_color=TEXT_DIM,
            icon_size=24,
            tooltip="Пауза/возобновить микрофон",
            on_click=self._on_mic_toggle,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    self._input_field,
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        icon_color=ACCENT,
                        icon_size=24,
                        tooltip="Отправить",
                        on_click=self._on_send,
                    ),
                    self._mic_btn,
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=30, right=30, top=10, bottom=25),
        )

    # ---------------------------------------------------------------
    # Микрофон
    # ---------------------------------------------------------------

    def _build_mic_tab(self) -> ft.Control:
        name = "—"
        if self.jarvis and self.jarvis.listener:
            name = self.jarvis.listener.device_name

        devices = ["по умолчанию"]
        try:
            import sounddevice as sd
            for d in sd.query_devices():
                if d["max_input_channels"] > 0:
                    n = d["name"][:50]
                    if n not in devices:
                        devices.append(n)
        except Exception:
            log.exception("Не удалось получить список устройств")

        current = self.config.get("input_device") or "по умолчанию"
        if current not in devices:
            devices.append(current)

        self._mic_dropdown = ft.Dropdown(
            value=current,
            options=[ft.dropdown.Option(d) for d in devices],
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_mic_change,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("🎤 Микрофон", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=25),
                    ft.Text(f"Текущее устройство: {name}", size=14, color=TEXT),
                    ft.Container(height=20),
                    ft.Text("Выбрать устройство:", size=13, color=TEXT_DIM),
                    self._mic_dropdown,
                    ft.Container(height=15),
                    ft.Container(
                        content=ft.Text(
                            "⚠ После смены устройства перезапусти Феникса",
                            size=12,
                            color="#d29922",
                        ),
                        padding=12,
                        bgcolor="#2d2210",
                        border_radius=8,
                    ),
                    ft.Container(height=20),
                    ft.Text(
                        "Проверить микрофон: python scripts/mics.py",
                        size=12,
                        color=TEXT_DIM,
                    ),
                ],
                spacing=5,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _on_mic_change(self, e) -> None:
        value = e.control.value
        if value == "по умолчанию":
            value = None
        self.config.set("input_device", value)
        log.info("Микрофон сохранён: %r (перезапусти Феникса)", value)

    # ---------------------------------------------------------------
    # Настройки
    # ---------------------------------------------------------------

    def _build_settings_tab(self) -> ft.Control:
        llm_dropdown = ft.Dropdown(
            value=self.config.get("llm_model", "qwen2.5:7b-instruct"),
            options=[ft.dropdown.Option(m) for m in LLM_MODELS],
            width=350,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_llm_change,
        )

        ollama_field = ft.TextField(
            value=self.config.get("ollama_url", "http://127.0.0.1:11434"),
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_ollama_change,
        )

        tts_dropdown = ft.Dropdown(
            value=self.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(b) for b in TTS_BACKENDS],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_tts_change,
        )

        rate_slider = ft.Slider(
            min=0.5,
            max=2.0,
            divisions=30,
            value=float(self.config.get("voice_rate", 1.15)),
            label="{value}",
            active_color=ACCENT,
            on_change_end=self._on_rate_change,
        )

        theme_dropdown = ft.Dropdown(
            value=self.config.get("gui_theme", "Тёмная"),
            options=[ft.dropdown.Option(t) for t in THEMES.keys()],
            width=250,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_theme_change,
        )

        def _section(title):
            return ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ACCENT)

        def _label(text):
            return ft.Text(text, size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("⚙️ Настройки", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),

                    _section("🤖 LLM"),
                    _label("Модель:"),
                    llm_dropdown,
                    ft.Container(height=8),
                    _label("Ollama URL:"),
                    ollama_field,
                    ft.Container(height=25),

                    _section("🔊 TTS"),
                    _label("Бэкенд:"),
                    tts_dropdown,
                    ft.Container(height=8),
                    _label("Скорость речи:"),
                    rate_slider,
                    ft.Container(height=25),

                    _section("🎨 Внешний вид"),
                    _label("Тема:"),
                    theme_dropdown,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    # ---------------------------------------------------------------
    # Очередь
    # ---------------------------------------------------------------

    async def _process_queue(self) -> None:
        while self._running:
            try:
                try:
                    kind, value = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if kind == "stop":
                    break
                elif kind == "state":
                    self._apply_state(value)
                elif kind == "message":
                    self._apply_message(*value)
                elif kind == "stream_chunk":
                    self._apply_stream_chunk(value)
                elif kind == "stream_end":
                    self._apply_stream_end()

                try:
                    self._page.update()
                except Exception:
                    pass
            except Exception:
                log.exception("Ошибка в _process_queue")

    def _apply_state(self, state: str) -> None:
        if state not in STATES:
            return
        self._state = state
        color, text, sub = STATES[state]

        # Размер сферы — разный для состояний
        size = {
            "idle": 80,
            "listening": 90,
            "speaking": 95,
            "error": 85,
        }.get(state, 80)

        try:
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.width = size
                self._status_circle.height = size
                self._status_circle.border_radius = size // 2
                # Тень — тот же цвет, что и сфера
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=30,
                    color=color,
                    spread_radius=3,
                )
            if self._status_text:
                self._status_text.value = text
            if self._status_sub:
                self._status_sub.value = sub
        except Exception:
            log.exception("Ошибка в _apply_state")

    def _apply_message(self, role: str, text: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M")
            is_user = (role == "user")

            # Аватар
            avatar = ft.Container(
                content=ft.Text(
                    "👤" if is_user else "🦅",
                    size=18,
                ),
                width=40,
                height=40,
                border_radius=20,
                bgcolor=BG_BUBBLE_USER if is_user else "#30363d",
                alignment=ft.Alignment.CENTER,
            )

            # Текст
            text_col = ft.Column(
                controls=[
                    ft.Text(
                        f"{'Вы' if is_user else 'Феникс'} • {ts}",
                        size=11,
                        color=TEXT_DIM,
                    ),
                    ft.Text(text, size=14, color=TEXT, selectable=True),
                ],
                spacing=2,
                expand=True,
            )

            # Пузырь с тенью
            bubble = ft.Container(
                content=ft.Row(
                    controls=[avatar, text_col] if not is_user else [text_col, avatar],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                bgcolor=BG_BUBBLE_USER if is_user else BG_BUBBLE_AI,
                padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                border_radius=14,
                shadow=ft.BoxShadow(
                    blur_radius=8,
                    color="#000000",
                    offset=ft.Offset(0, 2),
                ),
                animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_IN),
                opacity=1.0,
            )

            # Обёртка с выравниванием
            wrapper = ft.Container(
                content=bubble,
                alignment=ft.Alignment.CENTER_RIGHT if is_user else ft.Alignment.CENTER_LEFT,
                margin=ft.Margin(
                    left=80 if is_user else 0,
                    right=0 if is_user else 80,
                    top=0,
                    bottom=0,
                ),
            )

            self._history_list.controls.append(wrapper)
        except Exception:
            log.exception("Ошибка в _apply_message")

    def _apply_stream_chunk(self, chunk: str) -> None:
        try:
            if self._stream_bubble is None:
                ts = datetime.now().strftime("%H:%M")
                self._stream_text = ""
                self._stream_label = ft.Text("", size=14, color=TEXT, selectable=True)

                avatar = ft.Container(
                    content=ft.Text("🦅", size=18),
                    width=40,
                    height=40,
                    border_radius=20,
                    bgcolor="#30363d",
                    alignment=ft.Alignment.CENTER,
                )

                text_col = ft.Column(
                    controls=[
                        ft.Text(f"Феникс • {ts}", size=11, color=TEXT_DIM),
                        self._stream_label,
                    ],
                    spacing=2,
                    expand=True,
                )

                bubble = ft.Container(
                    content=ft.Row(
                        controls=[avatar, text_col],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    bgcolor=BG_BUBBLE_AI,
                    padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                    border_radius=14,
                    shadow=ft.BoxShadow(
                        blur_radius=8,
                        color="#000000",
                        offset=ft.Offset(0, 2),
                    ),
                )

                wrapper = ft.Container(
                    content=bubble,
                    alignment=ft.Alignment.CENTER_LEFT,
                    margin=ft.Margin(left=0, right=80, top=0, bottom=0),
                )

                self._stream_bubble = wrapper
                self._history_list.controls.append(wrapper)

            self._stream_text += chunk
            self._stream_label.value = self._stream_text
        except Exception:
            log.exception("Ошибка в _apply_stream_chunk")

    def _apply_stream_end(self) -> None:
        self._stream_bubble = None
        self._stream_label = None
        self._stream_text = ""

    # ---------------------------------------------------------------
    # Действия
    # ---------------------------------------------------------------

    def _on_nav_change(self, e) -> None:
        idx = e.control.selected_index
        log.info("Навигация: %d", idx)
        if idx in self._tabs:
            self._content_area.content = self._tabs[idx]
        try:
            self._page.update()
        except Exception:
            pass

    def _on_mode_change(self, e) -> None:
        mode = e.control.value
        self.config.set("mode", mode)
        if self.jarvis is not None:
            self.jarvis.handler.mode = mode

    def _on_voice_change(self, e) -> None:
        self.config.set("tts_voice", e.control.value)

    def _on_memory_change(self, e) -> None:
        mem = e.control.value
        preset = {"short": (40, 10), "normal": (100, 20), "long": (200, 40)}.get(mem, (100, 20))
        self.config.update({
            "memory_max": preset[0],
            "llm_context_messages": preset[1],
        })

    def _on_llm_change(self, e) -> None:
        self.config.set("llm_model", e.control.value)

    def _on_ollama_change(self, e) -> None:
        self.config.set("ollama_url", e.control.value)

    def _on_tts_change(self, e) -> None:
        self.config.set("tts_backend", e.control.value)

    def _on_rate_change(self, e) -> None:
        self.config.set("voice_rate", round(float(e.control.value), 2))

    def _on_theme_change(self, e) -> None:
        theme_name = e.control.value
        mode = THEMES.get(theme_name, ft.ThemeMode.DARK)
        self.config.set("gui_theme", theme_name)
        try:
            self._page.theme_mode = mode
            self._page.update()
        except Exception:
            pass

    def _on_send(self, e) -> None:
        text = self._input_field.value.strip()
        if not text:
            return
        self._input_field.value = ""
        self._run_command(text)

    def _on_mic_toggle(self, e) -> None:
        if self.jarvis is None:
            return
        self.jarvis.listening_enabled = not self.jarvis.listening_enabled
        self._mic_btn.icon = ft.Icons.MIC if self.jarvis.listening_enabled else ft.Icons.MIC_OFF
        self._mic_btn.icon_color = ACCENT if self.jarvis.listening_enabled else "#f85149"
        try:
            self._page.update()
        except Exception:
            pass

    def _run_command(self, cmd: str) -> None:
        if self.jarvis is None:
            return

        def _run():
            try:
                self.set_state("listening")
                self.add_message("user", cmd)
                reply = self.jarvis.handler.handle(cmd)

                if not reply.is_stream:
                    self.add_message("assistant", reply.text or "")

                self.jarvis.say(reply)
            except Exception:
                log.exception("Ошибка команды %r", cmd)
                self.set_state("error")

        threading.Thread(target=_run, daemon=True, name="gui-cmd").start()