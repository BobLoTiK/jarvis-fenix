"""GUI Феникса — интерактивное окно на Flet 1.0.3.

Архитектура:
    Jarvis → очередь (queue.Queue) → Flet worker (page.run_task) → обновление UI.
    Обратно: UI → callback → Jarvis.

Flet 1.0 API:
    - ft.run(main) вместо ft.app()
    - Button(content=...) вместо text=
    - Dropdown(on_select=...) вместо on_change=
    - page.run_task() для фоновых задач
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

# Состояния: (цвет, название, подпись)
STATES = {
    "idle":      (ft.Colors.GREY_500, "Спит", "Жду «Феникс»"),
    "listening": (ft.Colors.AMBER_400, "Слушаю", "Слушаю команду"),
    "speaking":  (ft.Colors.GREEN_400, "Говорю", "Отвечаю"),
    "error":     (ft.Colors.RED_400, "Ошибка", "Проверь логи"),
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

        # Текущее состояние
        self._state = "idle"
        self._stream_bubble = None
        self._stream_text = ""
        self._stream_label = None

        # Текущий раздел
        self._current_tab = 0

        # Ссылки на контролы
        self._status_icon = None
        self._status_text = None
        self._status_sub = None
        self._history_list = None
        self._input_field = None
        self._mic_btn = None
        self._content_area = None

        self._page = None

    # ---------------------------------------------------------------
    # Публичный API — из любого потока
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
    # Внутри Flet
    # ---------------------------------------------------------------

    def _run(self) -> None:
        try:
            ft.run(self._main)
        except Exception:
            log.exception("GUI (Flet) упал")
        finally:
            self._running = False

    def _main(self, page: ft.Page) -> None:
        """Точка входа Flet."""
        self._page = page
        page.title = "Феникс"
        page.window.width = 1000
        page.window.height = 720
        page.window.min_width = 800
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE)

        # Восстанавливаем позицию
        x = self.config.get("gui_x")
        y = self.config.get("gui_y")
        if x is not None and y is not None:
            page.window.left = x
            page.window.top = y

        self._build_ui(page)

        # Запускаем обработку очереди
        page.run_task(self._process_queue)

    def _build_ui(self, page: ft.Page) -> None:
        """Строит интерфейс."""
        # NavigationRail слева
        self._rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=80,
            min_extended_width=200,
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

        # Контент-область (переключается)
        # ВАЖНО: разделы создаются ОДИН РАЗ и кешируются.
        # Иначе при переключении теряется история чата.
        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_settings_tab(),
        }
        self._content_area = ft.Container(
            content=self._tabs[0],
            expand=True,
            padding=0,
        )

        # Основной layout
        page.add(
            ft.Row(
                controls=[
                    self._rail,
                    ft.VerticalDivider(width=1),
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            )
        )

    # ---------------------------------------------------------------
    # Разделы
    # ---------------------------------------------------------------

    def _build_main_tab(self) -> ft.Control:
        """Главная: статус, контролы, история, ввод."""
        # Статус
        status_bar = ft.Container(
            content=ft.Row(
                controls=[
                    self._status_icon if self._status_icon else ft.Icon(
                        ft.Icons.CIRCLE, color=ft.Colors.GREY_500, size=40,
                    ),
                    ft.Column(
                        controls=[
                            self._status_text if self._status_text else ft.Text(
                                "Спит", size=24, weight=ft.FontWeight.BOLD,
                            ),
                            self._status_sub if self._status_sub else ft.Text(
                                "Жду «Феникс»", size=14, color=ft.Colors.GREY_500,
                            ),
                        ],
                        spacing=0,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=15,
            ),
            padding=ft.Padding(left=20, top=20, right=20, bottom=20),
        )

        # Контролы
        controls_bar = self._build_controls()

        # История — растягивается
        self._history_list = ft.ListView(
            spacing=8,
            auto_scroll=True,
            expand=True,
        )
        history_container = ft.Container(
            content=self._history_list,
            expand=True,
            padding=ft.Padding(left=20, right=20, top=10, bottom=10),
        )

        # Ввод
        input_bar = self._build_input()

        # Колонка с expand
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

    def _build_mic_tab(self) -> ft.Control:
        """Раздел «Микрофон» — выбор устройства."""
        name = "—"
        if self.jarvis and self.jarvis.listener:
            name = self.jarvis.listener.device_name

        # Собираем список устройств
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

        # Текущее устройство
        current = self.config.get("input_device") or "по умолчанию"
        if current not in devices:
            devices.append(current)

        self._mic_dropdown = ft.Dropdown(
            value=current,
            options=[ft.dropdown.Option(d) for d in devices],
            width=400,
            on_select=self._on_mic_change,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("🎤 Микрофон", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(height=20),
                    ft.Text(f"Текущее устройство: {name}", size=14),
                    ft.Container(height=20),
                    ft.Text("Выбрать устройство:", size=14),
                    self._mic_dropdown,
                    ft.Container(height=10),
                    ft.Text(
                        "⚠ После смены устройства перезапусти Феникса, "
                        "чтобы микрофон переключился.",
                        size=12,
                        color=ft.Colors.AMBER_400,
                    ),
                    ft.Container(height=20),
                    ft.Text(
                        "Проверить микрофон: python scripts/mics.py",
                        size=12,
                        color=ft.Colors.GREY_500,
                    ),
                ],
                spacing=5,
            ),
            padding=ft.Padding(left=30, top=30, right=30, bottom=30),
            expand=True,
        )

    def _on_mic_change(self, e) -> None:
        """Сохраняет выбранное устройство в config."""
        value = e.control.value
        if value == "по умолчанию":
            value = None
        self.config.set("input_device", value)
        log.info("Микрофон сохранён: %r (перезапусти Феникса)", value)

    def _build_settings_tab(self) -> ft.Control:
        """Настройки."""
        llm_dropdown = ft.Dropdown(
            value=self.config.get("llm_model", "qwen2.5:7b-instruct"),
            options=[ft.dropdown.Option(m) for m in LLM_MODELS],
            width=300,
            on_select=self._on_llm_change,
        )

        ollama_field = ft.TextField(
            value=self.config.get("ollama_url", "http://127.0.0.1:11434"),
            width=400,
            on_submit=self._on_ollama_change,
        )

        tts_dropdown = ft.Dropdown(
            value=self.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(b) for b in TTS_BACKENDS],
            width=200,
            on_select=self._on_tts_change,
        )

        rate_slider = ft.Slider(
            min=0.5,
            max=2.0,
            divisions=30,
            value=float(self.config.get("voice_rate", 1.15)),
            label="{value}",
            on_change_end=self._on_rate_change,
        )

        theme_dropdown = ft.Dropdown(
            value="Тёмная",
            options=[ft.dropdown.Option(t) for t in THEMES.keys()],
            width=200,
            on_select=self._on_theme_change,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("⚙️ Настройки", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(height=20),

                    ft.Text("🤖 LLM", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Модель:"),
                    llm_dropdown,
                    ft.Text("Ollama URL:"),
                    ollama_field,
                    ft.Container(height=20),

                    ft.Text("🔊 TTS", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Бэкенд:"),
                    tts_dropdown,
                    ft.Text("Скорость речи:"),
                    rate_slider,
                    ft.Container(height=20),

                    ft.Text("🎨 Внешний вид", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Тема:"),
                    theme_dropdown,
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=30, top=30, right=30, bottom=30),
            expand=True,
        )

    # ---------------------------------------------------------------
    # Контролы главной
    # ---------------------------------------------------------------

    def _build_controls(self) -> ft.Container:
        """Режим / голос / память."""
        # Режим
        mode_row = ft.Row(
            controls=[
                ft.Text("Режим:", width=80),
                ft.RadioGroup(
                    value=self.config.get("mode", "combo"),
                    on_change=self._on_mode_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="commands", label="Команды"),
                            ft.Radio(value="llm", label="ИИ"),
                            ft.Radio(value="combo", label="Комбо"),
                        ],
                        spacing=5,
                    ),
                ),
            ],
            spacing=10,
        )

        # Голос
        voice_row = ft.Row(
            controls=[
                ft.Text("Голос:", width=80),
                ft.Dropdown(
                    value=self.config.get("tts_voice", "ruslan"),
                    options=[
                        ft.dropdown.Option("ruslan"),
                        ft.dropdown.Option("dmitri"),
                        ft.dropdown.Option("irina"),
                        ft.dropdown.Option("denis"),
                    ],
                    width=150,
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
                ft.Text("Память:", width=80),
                ft.RadioGroup(
                    value=mem_value,
                    on_change=self._on_memory_change,
                    content=ft.Row(
                        controls=[
                            ft.Radio(value="short", label="Короткая"),
                            ft.Radio(value="normal", label="Обычная"),
                            ft.Radio(value="long", label="Долгая"),
                        ],
                        spacing=5,
                    ),
                ),
            ],
            spacing=10,
        )

        return ft.Container(
            content=ft.Column(controls=[mode_row, voice_row, mem_row], spacing=10),
            padding=ft.Padding(left=20, right=20, top=10, bottom=10),
        )

    def _build_input(self) -> ft.Container:
        """Поле ввода."""
        self._input_field = ft.TextField(
            hint_text="Напишите команду...",
            expand=True,
            on_submit=self._on_send,
        )

        self._mic_btn = ft.IconButton(
            icon=ft.Icons.MIC,
            on_click=self._on_mic_toggle,
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    self._input_field,
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        on_click=self._on_send,
                    ),
                    self._mic_btn,
                ],
                spacing=10,
            ),
            padding=ft.Padding(left=20, right=20, top=10, bottom=20),
        )

    # ---------------------------------------------------------------
    # Обработка очереди (async)
    # ---------------------------------------------------------------

    async def _process_queue(self) -> None:
        """Читает очередь и обновляет UI."""
        while self._running:
            try:
                try:
                    kind, value = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
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
        try:
            if self._status_icon:
                self._status_icon.color = color
            if self._status_text:
                self._status_text.value = text
            if self._status_sub:
                self._status_sub.value = sub
        except Exception:
            pass

    def _apply_message(self, role: str, text: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M")
            is_user = (role == "user")

            bubble = ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(
                            f"{'Вы' if is_user else '🦅'} • {ts}",
                            size=10,
                            color=ft.Colors.GREY_500,
                        ),
                        ft.Text(text, size=13, selectable=True),
                    ],
                    spacing=2,
                    horizontal_alignment=(
                        ft.CrossAxisAlignment.END if is_user else ft.CrossAxisAlignment.START
                    ),
                ),
                bgcolor=ft.Colors.BLUE_700 if is_user else ft.Colors.GREY_800,
                padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                border_radius=12,
                margin=ft.Margin(
                    left=200 if is_user else 0,
                    right=0 if is_user else 200,
                    top=0,
                    bottom=0,
                ),
            )

            self._history_list.controls.append(bubble)
        except Exception:
            log.exception("Ошибка добавления сообщения")

    def _apply_stream_chunk(self, chunk: str) -> None:
        try:
            if self._stream_bubble is None:
                ts = datetime.now().strftime("%H:%M")
                self._stream_text = ""
                self._stream_label = ft.Text("", size=13, selectable=True)

                self._stream_bubble = ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text(f"🦅 • {ts}", size=10, color=ft.Colors.GREY_500),
                            self._stream_label,
                        ],
                        spacing=2,
                    ),
                    bgcolor=ft.Colors.GREY_800,
                    padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                    border_radius=12,
                    margin=ft.Margin(left=0, right=200, top=0, bottom=0),
                )
                self._history_list.controls.append(self._stream_bubble)

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
        """Переключение раздела (без пересоздания — история сохраняется)."""
        idx = e.control.selected_index
        self._current_tab = idx
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