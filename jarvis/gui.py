"""GUI Феникса — интерактивное окно на Flet 1.0.3.

Архитектура:
    Jarvis → очередь (queue.Queue) → Flet worker (page.run_task) → обновление UI.
    Обратно: UI → callback → Jarvis.

Связь с Jarvis:
    GUI → Jarvis: callbacks (on_mode_change, on_voice_change, ...)
    Jarvis → GUI: gui.add_message(...), gui.set_state(...), gui.add_stream_chunk(...)

Профиль:
    Подписка на profile.subscribe — при смене профиля пересобираем _tabs.

launch_mode=tray:
    GUI запускается всегда (Flet в главном потоке), но окно скрыто.
    show_window() / open_settings_tab() — вызываются из трея.
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

PALETTES = {
    "dark": {
        "bg_main": "#0e1116",
        "bg_card": "#161b22",
        "bg_bubble_user": "#1f6feb",
        "bg_bubble_ai": "#21262d",
        "accent": "#58a6ff",
        "text": "#e6edf3",
        "text_dim": "#8b949e",
        "border": "#30363d",
        "error": "#f85149",
        "success": "#3fb950",
        "warning": "#d29922",
    },
    "light": {
        "bg_main": "#f6f8fa",
        "bg_card": "#ffffff",
        "bg_bubble_user": "#0969da",
        "bg_bubble_ai": "#eaeef2",
        "accent": "#0969da",
        "text": "#1f2328",
        "text_dim": "#656d76",
        "border": "#d0d7de",
        "error": "#cf222e",
        "success": "#1a7f37",
        "warning": "#9a6700",
    },
}


def _detect_system_theme() -> str:
    """Определяет тему Windows: 'dark' или 'light'."""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value == 1 else "dark"
    except Exception:
        log.exception("Не удалось определить тему Windows — беру тёмную")
        return "dark"


class _Palette:
    def __init__(self):
        self._data = PALETTES["dark"]

    def set(self, name: str):
        self._data = PALETTES.get(name, PALETTES["dark"])

    def __getattr__(self, key):
        return self._data.get(key, "")


P = _Palette()

BG_DARK = "#0e1116"
BG_CARD = "#161b22"
BG_BUBBLE_USER = "#1f6feb"
BG_BUBBLE_AI = "#21262d"
ACCENT = "#58a6ff"
TEXT = "#e6edf3"
TEXT_DIM = "#8b949e"


def _apply_palette(name: str) -> None:
    global BG_DARK, BG_CARD, BG_BUBBLE_USER, BG_BUBBLE_AI, ACCENT, TEXT, TEXT_DIM
    P.set(name)
    BG_DARK = P.bg_main
    BG_CARD = P.bg_card
    BG_BUBBLE_USER = P.bg_bubble_user
    BG_BUBBLE_AI = P.bg_bubble_ai
    ACCENT = P.accent
    TEXT = P.text
    TEXT_DIM = P.text_dim


STATES = {
    "idle":      ("#484f58", "Спит",   "Жду «Феникс»"),
    "listening": ("#d29922", "Слушаю", "Слушаю команду"),
    "speaking":  ("#3fb950", "Говорю", "Отвечаю"),
    "error":     ("#f85149", "Ошибка", "Проверь логи"),
}

THEMES = {
    "Системная": ft.ThemeMode.SYSTEM,
    "Тёмная": ft.ThemeMode.DARK,
    "Светлая": ft.ThemeMode.LIGHT,
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

        # launch_mode=tray — окно скрыто при старте
        self.start_hidden = False

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
        self._tabs = {}

        # Контролы вкладки «Микрофон»
        self._mic_dropdown = None
        self._mic_level_bar = None
        self._mic_level_text = None
        self._mic_status_text = None
        self._mic_peak_text = None
        self._mic_utt_text = None
        self._mic_test_result = None

        self._page = None

        # №92: подписка на смену профиля
        try:
            from jarvis import profile as _profile
            _profile.subscribe(self._on_profile_switch)
        except Exception:
            log.exception("Не удалось подписаться на смену профиля в GUI")

        # Mood: подписка на смену настроения.
        try:
            from jarvis import mood as _mood
            _mood.subscribe(self._on_mood_change)
        except Exception:
            log.exception("Не удалось подписаться на mood в GUI")

    def _on_mood_change(self, old_state: str, new_state: str) -> None:
        """Mood сменился — обновляем цвет статус-сферы."""
        if old_state == new_state:
            return
        log.info("GUI: mood %s → %s", old_state, new_state)
        self._queue.put(("mood", new_state))

    def _on_profile_switch(self, old_name: str, new_name: str) -> None:
        """Профиль сменился — пересобираем UI через очередь.

        Без этого метода profile.subscribe(self._on_profile_switch)
        в __init__ падал с AttributeError на каждом старте: GUI
        оставался неподписанным, и вкладка «Персона» после «я — Маша»
        показывала данные прошлого профиля до перезапуска.

        Через очередь, а не напрямую: profile.switch() зовёт колбэк
        из чужого потока, а Flet-контролы трогать можно только
        из главного.
        """
        if old_name == new_name:
            return
        log.info("GUI: профиль %s → %s, пересборка UI", old_name, new_name)
        self._queue.put(("rebuild_ui", None))

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

    def show_window(self) -> None:
        """Показать окно (для launch_mode=tray)."""
        self._queue.put(("show_window", None))

    def open_settings_tab(self) -> None:
        """Открыть GUI на вкладке «Настройки»."""
        self._queue.put(("open_settings_tab", None))

    def add_message(self, role: str, text: str) -> None:
        self._queue.put(("message", (role, text)))

    def add_stream_chunk(self, chunk: str) -> None:
        self._queue.put(("stream_chunk", chunk))

    def end_stream(self) -> None:
        self._queue.put(("stream_end", None))

    def set_state(self, state: str) -> None:
        self._queue.put(("state", state))

    def set_mic_test_result(self, text: str, color: str) -> None:
        """Обновляет результат mic-теста через очередь GUI.

        Раньше _on_mic_test дёргал self._page.update() прямо из
        своего потока — это нарушает правило Flet «UI только в главном
        потоке» и иногда ломает рендер.
        """
        self._queue.put(("mic_test", (text, color)))

    def launch_fireworks(self, duration: float = 6.0) -> None:
        """Запускает анимацию салюта (через очередь GUI)."""
        self._queue.put(("fireworks", duration))

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

        theme_name = self.config.get("gui_theme", "Системная")
        if theme_name not in THEMES:
            theme_name = "Системная"
        theme_mode = THEMES[theme_name]

        if theme_mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif theme_mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        page.title = "Феникс"

        # Иконка окна — из jarvis/icon.ico
        icon_path = Path(__file__).resolve().parent / "icon.ico"
        if icon_path.exists():
            try:
                page.window.icon = str(icon_path)
                log.info("GUI: иконка загружена из %s", icon_path.name)
            except Exception:
                log.exception("Не удалось загрузить иконку окна")
        else:
            log.warning("GUI: иконки нет — %s", icon_path)

        page.window.width = 1100
        page.window.height = 760
        page.window.min_width = 900
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.bgcolor = BG_DARK
        page.theme_mode = theme_mode
        page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            font_family="Segoe UI",
        )

        x = self.config.get("gui_x")
        y = self.config.get("gui_y")
        if x is not None and y is not None:
            page.window.left = x
            page.window.top = y

        # launch_mode=tray — окно скрыто
        if self.start_hidden:
            page.window.visible = False
            log.info("GUI: окно скрыто при старте (launch_mode=tray)")

        self._build_ui(page)
        page.run_task(self._process_queue)
        page.run_task(self._mic_level_loop)

    def _build_ui(self, page: ft.Page) -> None:
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
                    icon=ft.Icons.FACE_OUTLINED,
                    selected_icon=ft.Icons.FACE,
                    label="Персона",
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Настройки",
                ),
            ],
            on_change=self._on_nav_change,
        )

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_persona_tab(),
            3: self._build_settings_tab(),
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

    def _build_main_tab(self) -> ft.Control:
        self._status_circle = ft.Container(
            width=80,
            height=80,
            border_radius=40,
            bgcolor="#484f58",
            animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
            shadow=ft.BoxShadow(
                blur_radius=24,
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

        controls_bar = self._build_controls()

        self._history_list = ft.ListView(
            spacing=12,
            auto_scroll=True,
            expand=True,
        )
        history_container = ft.Container(
            content=self._history_list,
            expand=True,
            padding=ft.Padding(left=30, right=30, top=10, bottom=10),
        )

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
        def _label(text):
            return ft.Text(text, width=80, color=TEXT_DIM, size=13)

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

        self._mic_level_bar = ft.ProgressBar(
            value=0.0,
            width=400,
            color=ACCENT,
            bgcolor="#21262d",
        )
        self._mic_level_text = ft.Text("Уровень сигнала: —", size=13, color=TEXT_DIM)
        self._mic_status_text = ft.Text("Статус: ожидание проверки", size=13, color=TEXT_DIM)
        self._mic_peak_text = ft.Text("Пик за сессию: 0", size=13, color=TEXT_DIM)
        self._mic_utt_text = ft.Text("Распознано фраз: 0", size=13, color=TEXT_DIM)
        self._mic_test_result = ft.Text("", size=13, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Микрофон", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=25),
                    ft.Text(f"Текущее устройство: {name}", size=14, color=TEXT),
                    ft.Container(height=20),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._mic_level_text,
                                self._mic_level_bar,
                                ft.Container(height=8),
                                self._mic_peak_text,
                                self._mic_utt_text,
                                self._mic_status_text,
                                self._mic_test_result,
                            ],
                            spacing=6,
                        ),
                        padding=16,
                        bgcolor=BG_CARD,
                        border_radius=12,
                    ),
                    ft.Container(height=15),
                    ft.Button(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.MIC, color=BG_DARK),
                                ft.Text("Проверить микрофон (3 сек)", color=BG_DARK),
                            ],
                            spacing=8,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        on_click=self._on_mic_test,
                        style=ft.ButtonStyle(
                            bgcolor=ACCENT,
                            shape=ft.RoundedRectangleBorder(radius=10),
                            padding=ft.Padding(left=20, right=20, top=12, bottom=12),
                        ),
                    ),
                    ft.Container(height=20),
                    ft.Text("Выбрать устройство:", size=13, color=TEXT_DIM),
                    self._mic_dropdown,
                    ft.Container(height=15),
                    ft.Container(
                        content=ft.Text(
                            "После смены устройства перезапусти Феникса",
                            size=12,
                            color="#d29922",
                        ),
                        padding=12,
                        bgcolor="#2d2210",
                        border_radius=8,
                    ),
                ],
                spacing=5,
                scroll=ft.ScrollMode.AUTO,
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

    def _on_mic_test(self, e) -> None:
        """Кнопка «Проверить микрофон».

        ВАЖНО: раньше этот метод дёргал self._page.update() из рабочего
        потока — нарушение Flet. Теперь все обновления UI идут через
        очередь (set_mic_test_result).
        """
        if self.jarvis is None or self.jarvis.listener is None:
            # Этот case уже в главном потоке — можно обновить напрямую.
            if self._mic_test_result is not None:
                self._mic_test_result.value = "Listener не запущен"
                self._mic_test_result.color = "#f85149"
            return

        def _run():
            listener = self.jarvis.listener
            listener.reset_stats()
            # Первое сообщение — через очередь
            self.set_mic_test_result("Слушаю 3 секунды... говори!", ACCENT)

            time.sleep(3.0)
            peak = listener.peak
            if peak >= 500:
                self.set_mic_test_result(
                    f"Микрофон работает (пик {peak})", "#3fb950"
                )
            elif peak >= 100:
                self.set_mic_test_result(
                    f"Микрофон очень тихий (пик {peak}).", "#d29922"
                )
            else:
                self.set_mic_test_result(
                    f"Микрофон молчит (пик {peak}).", "#f85149"
                )

        threading.Thread(target=_run, daemon=True, name="mic-test").start()

    def _update_mic_level(self) -> None:
        if self.jarvis is None or self.jarvis.listener is None:
            return
        listener = self.jarvis.listener
        rms = listener.current_rms
        level = min(1.0, rms / 2000.0)

        try:
            if self._mic_level_bar is not None:
                self._mic_level_bar.value = level
            if self._mic_level_text is not None:
                pct = int(level * 100)
                self._mic_level_text.value = f"Уровень сигнала: {pct}%"
            if self._mic_peak_text is not None:
                self._mic_peak_text.value = f"Пик за сессию: {listener.peak}"
            if self._mic_utt_text is not None:
                self._mic_utt_text.value = f"Распознано фраз: {listener.utterances}"
            if self._mic_status_text is not None:
                if listener.peak >= 500:
                    self._mic_status_text.value = "Статус: Работает"
                    self._mic_status_text.color = "#3fb950"
                elif listener.peak >= 100:
                    self._mic_status_text.value = "Статус: Тихий сигнал"
                    self._mic_status_text.color = "#d29922"
                else:
                    self._mic_status_text.value = "Статус: Ожидание звука"
                    self._mic_status_text.color = TEXT_DIM
        except Exception:
            log.exception("_update_mic_level упал")

    def _build_persona_tab(self) -> ft.Control:
        """Вкладка «Персона» — имя, стиль, черты, backstory."""
        from jarvis import persona

        p = persona.get()

        name_field = ft.TextField(
            label="Имя пользователя",
            value=self.config.get("name", "") or "",
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_name,
        )

        assistant_name_field = ft.TextField(
            label="Имя ассистента",
            value=p.get("assistant_name") or "Феникс",
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_assistant_name,
        )

        style_dropdown = ft.Dropdown(
            label="Стиль общения",
            value=p.get("speech_style") or "friendly",
            options=[
                ft.dropdown.Option("formal", "Формальный (на «вы»)"),
                ft.dropdown.Option("friendly", "Дружеский (на «ты»)"),
                ft.dropdown.Option("sarcastic", "Саркастичный"),
                ft.dropdown.Option("brief", "Краткий"),
            ],
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_select=self._on_persona_style,
        )

        traits_field = ft.TextField(
            label="Черты (через запятую)",
            value=", ".join(p.get("traits") or []),
            width=400,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_traits,
        )

        backstory_field = ft.TextField(
            label="Контекст (backstory)",
            value=p.get("backstory") or "",
            width=400,
            multiline=True,
            min_lines=3,
            max_lines=6,
            border_color="#30363d",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_backstory,
        )

        reset_btn = ft.Button(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.REFRESH, color=BG_DARK),
                    ft.Text("Сбросить онбординг", color=BG_DARK),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_click=self._on_persona_reset,
            style=ft.ButtonStyle(
                bgcolor=ACCENT,
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.Padding(left=20, right=20, top=10, bottom=10),
            ),
        )

        def _label(t):
            return ft.Text(t, size=12, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Персона", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),
                    _label("Как тебя зовут (пользователь):"),
                    name_field,
                    ft.Container(height=12),
                    _label("Как зовут ассистента:"),
                    assistant_name_field,
                    ft.Container(height=12),
                    _label("Стиль общения:"),
                    style_dropdown,
                    ft.Container(height=12),
                    _label("Черты характера (через запятую):"),
                    traits_field,
                    ft.Container(height=12),
                    _label("Контекст (backstory):"),
                    backstory_field,
                    ft.Container(height=20),
                    reset_btn,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _on_persona_name(self, e) -> None:
        self.config.set("name", e.control.value.strip())

    def _on_persona_assistant_name(self, e) -> None:
        from jarvis import persona
        persona.set_field("assistant_name", e.control.value.strip() or "Феникс")

    def _on_persona_style(self, e) -> None:
        from jarvis import persona
        persona.set_field("speech_style", e.control.value)

    def _on_persona_traits(self, e) -> None:
        from jarvis import persona
        raw = e.control.value.strip()
        traits = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        persona.set_field("traits", traits)

    def _on_persona_backstory(self, e) -> None:
        from jarvis import persona
        persona.set_field("backstory", e.control.value.strip())

    def _on_persona_reset(self, e) -> None:
        from jarvis import persona
        persona.reset_onboarding()
        log.info("GUI: онбординг сброшен")
        try:
            snack = ft.SnackBar(ft.Text("Онбординг сброшен. Перезапусти Феникса."))
            self._page.overlay.append(snack)
            snack.open = True
            self._page.update()
        except Exception:
            log.exception("Не удалось показать SnackBar")


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
            value=self.config.get("gui_theme", "Системная"),
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
                    ft.Text("Настройки", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),
                    _section("LLM"),
                    _label("Модель:"),
                    llm_dropdown,
                    ft.Container(height=8),
                    _label("Ollama URL:"),
                    ollama_field,
                    ft.Container(height=25),
                    _section("TTS"),
                    _label("Бэкенд:"),
                    tts_dropdown,
                    ft.Container(height=8),
                    _label("Качество голоса:"),
                    self._build_voice_quality_row(),
                    ft.Container(height=8),
                    _label("Скорость речи:"),
                    rate_slider,
                    ft.Container(height=25),
                    _section("Внешний вид"),
                    _label("Тема:"),
                    theme_dropdown,
                ],
                spacing=6,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _build_voice_quality_row(self) -> ft.Control:
        current = self.config.get("tts_voice_quality", "medium")
        recommended = "medium"
        try:
            import json
            caps_path = Path(__file__).resolve().parent.parent / "system_caps.json"
            if caps_path.exists():
                caps = json.loads(caps_path.read_text(encoding="utf-8"))
                recommended = caps.get("cpu", {}).get("recommended_piper", "medium")
        except Exception:
            log.exception("Не удалось прочитать рекомендацию Piper")

        radio = ft.RadioGroup(
            value=current,
            on_change=self._on_voice_quality_change,
            content=ft.Row(
                controls=[
                    ft.Radio(value="medium", label="medium (быстрее)", active_color=ACCENT),
                    ft.Radio(value="high", label="high (лучше)", active_color=ACCENT),
                ],
                spacing=15,
            ),
        )

        hint = ft.Text(
            f"Рекомендация по CPU: {recommended}. "
            f"Для русских голосов high пока недоступен — используется medium.",
            size=11,
            color=TEXT_DIM,
        )

        return ft.Column(controls=[radio, hint], spacing=4)

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
                elif kind == "open_mic_tab":
                    self._open_mic_tab()
                elif kind == "open_settings_tab":
                    self._open_settings_tab()
                elif kind == "show_window":
                    self._show_window_now()
                elif kind == "mic_level":
                    self._update_mic_level()
                elif kind == "mic_test":
                    self._apply_mic_test_result(*value)
                elif kind == "rebuild_theme":
                    self._rebuild_ui_for_theme()
                elif kind == "rebuild_ui":
                    self._rebuild_ui_for_theme()
                elif kind == "mood":
                    self._apply_mood_color(value)
                elif kind == "fireworks":
                    self._page.run_task(
                        self._launch_fireworks_async, float(value or 6.0)
                    )

                try:
                    self._page.update()
                except Exception:
                    pass
            except Exception:
                log.exception("Ошибка в _process_queue")

    def _apply_mic_test_result(self, text: str, color: str) -> None:
        """Обновляет результат mic-теста — уже в главном потоке."""
        try:
            if self._mic_test_result is not None:
                self._mic_test_result.value = text
                self._mic_test_result.color = color
        except Exception:
            log.exception("_apply_mic_test_result упал")

    async def _launch_fireworks_async(self, duration: float = 6.0) -> None:
        """Анимация салюта — duration секунд, через Stack + Container.

        Используем Stack и Container вместо Canvas — в Flet 1.0.3
        Canvas API капризный, а Container.top/left анимируется стабильно.

        duration — длительность в секундах.
        """
        import random
        import math

        try:
            w = self._page.window.width or 1100
            h = self._page.window.height or 760

            # Stack — слой поверх всего окна
            stack = ft.Stack(width=w, height=h)

            # Тёмная подложка
            backdrop = ft.Container(
                width=w,
                height=h,
                bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
            )
            stack.controls.append(backdrop)

            particles: list[dict] = []

            # Количество взрывов — пропорционально длительности
            n_bursts = max(4, int(duration * 1.2))
            bursts = []
            for i in range(n_bursts):
                cx = random.randint(150, w - 150)
                cy = random.randint(100, h - 250)
                color = random.choice([
                    "#ff1744", "#ffea00", "#00e5ff",
                    "#00e676", "#d500f9", "#ff6d00",
                ])
                # Интервал между взрывами
                spawn_time = (duration / max(1, n_bursts - 1)) * i * 0.6
                bursts.append((spawn_time, cx, cy, color))

            overlay = ft.Container(
                width=w, height=h, left=0, top=0,
                content=stack,
            )

            self._page.overlay.append(overlay)
            self._page.update()

            total_time = max(3.0, float(duration))
            frame_time = 0.05
            elapsed = 0.0
            spawned = [False] * len(bursts)

            while elapsed < total_time:
                # Спавн новых взрывов
                for i, (spawn_time, cx, cy, color) in enumerate(bursts):
                    if not spawned[i] and elapsed >= spawn_time:
                        spawned[i] = True
                        for _ in range(25):
                            angle = random.uniform(0, 2 * math.pi)
                            speed = random.uniform(2.5, 5.0)
                            container = ft.Container(
                                width=5, height=5,
                                border_radius=3,
                                bgcolor=color,
                                left=cx, top=cy,
                            )
                            stack.controls.append(container)
                            particles.append({
                                "ctrl": container,
                                "x": cx, "y": cy,
                                "vx": math.cos(angle) * speed,
                                "vy": math.sin(angle) * speed,
                                "life": 50,
                            })

                # Обновляем позиции
                for p in particles:
                    if p["life"] <= 0:
                        continue
                    p["x"] += p["vx"]
                    p["y"] += p["vy"]
                    p["vy"] += 0.15
                    p["life"] -= 1
                    try:
                        p["ctrl"].left = p["x"]
                        p["ctrl"].top = p["y"]
                        p["ctrl"].opacity = max(0.0, p["life"] / 50.0)
                    except Exception:
                        pass

                # Убираем мёртвые
                dead = [p for p in particles if p["life"] <= 0]
                for p in dead:
                    try:
                        stack.controls.remove(p["ctrl"])
                    except Exception:
                        pass
                particles = [p for p in particles if p["life"] > 0]

                try:
                    self._page.update()
                except Exception:
                    pass

                await asyncio.sleep(frame_time)
                elapsed += frame_time

            try:
                self._page.overlay.remove(overlay)
                self._page.update()
            except Exception:
                pass

        except Exception:
            log.exception("Fireworks: ошибка анимации")

    async def _mic_level_loop(self) -> None:
        """Обновляет уровень микрофона и следит за сменой системной темы.

        Уровень микрофона — 5 раз в секунду (0.2 с).
        Системная тема — раз в 5 секунд (25 итераций × 0.2 с).
        """
        last_system_theme = _detect_system_theme()
        counter = 0

        while self._running:
            try:
                if self._rail and self._rail.selected_index == 1:
                    self._queue.put(("mic_level", None))

                counter += 1
                if counter >= 25:
                    counter = 0
                    if self.config.get("gui_theme") == "Системная":
                        current = _detect_system_theme()
                        if current != last_system_theme:
                            log.info("Системная тема Windows изменилась: %s → %s",
                                     last_system_theme, current)
                            last_system_theme = current
                            _apply_palette(current)
                            self._queue.put(("rebuild_theme", current))

                await asyncio.sleep(0.2)
            except Exception:
                log.exception("_mic_level_loop упал")
                await asyncio.sleep(1.0)

    def _apply_state(self, state: str) -> None:
        if state not in STATES:
            return
        self._state = state
        color, text, sub = STATES[state]

        size = {"idle": 80, "listening": 90, "speaking": 95, "error": 85}.get(state, 80)

        try:
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.width = size
                self._status_circle.height = size
                self._status_circle.border_radius = size // 2
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=32, color=color, spread_radius=3,
                )
            if self._status_text:
                self._status_text.value = text
            if self._status_sub:
                self._status_sub.value = sub
        except Exception:
            log.exception("Ошибка в _apply_state")

    def _apply_mood_color(self, mood_state: str) -> None:
        """Обновляет свечение статус-сферы по mood (только в idle)."""
        try:
            from jarvis import mood as _mood
            if self._state != "idle":
                return  # во время listening/speaking цвет другой
            color = _mood.color()
            if self._status_circle:
                self._status_circle.bgcolor = color
                self._status_circle.shadow = ft.BoxShadow(
                    blur_radius=32, color=color, spread_radius=3,
                )
            log.info("GUI: статус-сфера перекрашена под mood=%s", mood_state)
        except Exception:
            log.exception("_apply_mood_color упал")

    def _avatar(self, is_user: bool) -> ft.Container:
        if is_user:
            bg = BG_BUBBLE_USER
            icon = ft.Icons.PERSON
            icon_color = "#ffffff"
        else:
            bg = BG_CARD
            icon = ft.Icons.SMART_TOY
            icon_color = ACCENT

        return ft.Container(
            content=ft.Icon(icon, size=20, color=icon_color),
            width=40,
            height=40,
            border_radius=20,
            bgcolor=bg,
            alignment=ft.Alignment.CENTER,
        )

    def _apply_message(self, role: str, text: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M")
            is_user = (role == "user")
            avatar = self._avatar(is_user)

            text_col = ft.Column(
                controls=[
                    ft.Text(
                        f"{'Вы' if is_user else 'Феникс'} • {ts}",
                        size=11, color=TEXT_DIM,
                    ),
                    ft.Text(text, size=14,
                            color="#ffffff" if is_user else TEXT,
                            selectable=True),
                ],
                spacing=2, expand=True,
            )

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
                    blur_radius=10, color="#000000",
                    offset=ft.Offset(0, 2),
                ),
                animate_opacity=ft.Animation(300, ft.AnimationCurve.EASE_IN),
                opacity=1.0,
            )

            wrapper = ft.Container(
                content=bubble,
                alignment=ft.Alignment.CENTER_RIGHT if is_user else ft.Alignment.CENTER_LEFT,
                margin=ft.Margin(
                    left=80 if is_user else 0,
                    right=0 if is_user else 80,
                    top=0, bottom=0,
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

                avatar = self._avatar(is_user=False)

                text_col = ft.Column(
                    controls=[
                        ft.Text(f"Феникс • {ts}", size=11, color=TEXT_DIM),
                        self._stream_label,
                    ],
                    spacing=2, expand=True,
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
                        blur_radius=10, color="#000000",
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

    def _open_mic_tab(self) -> None:
        try:
            self._rail.selected_index = 1
            self._content_area.content = self._tabs[1]
            log.info("GUI: открыл вкладку «Микрофон»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Микрофон»")

    def _open_settings_tab(self) -> None:
        try:
            self._rail.selected_index = 3
            self._content_area.content = self._tabs[3]
            log.info("GUI: открыл вкладку «Настройки»")
        except Exception:
            log.exception("Не удалось открыть вкладку «Настройки»")

    def _show_window_now(self) -> None:
        """Показывает окно — для launch_mode=tray."""
        try:
            if self._page is not None:
                self._page.window.visible = True
                self._page.window.minimized = False
                self._page.update()
                log.info("GUI: окно показано")
        except Exception:
            log.exception("Не удалось показать окно")

    # ---------------------------------------------------------------
    # Действия
    # ---------------------------------------------------------------

    def _on_nav_change(self, e) -> None:
        idx = e.control.selected_index
        log.info("Навигация: %d", idx)
        # Через get, а не [idx]: если _tabs и destinations рельса
        # разъехались, раньше здесь летел KeyError и вкладка
        # молча не переключалась.
        tab = self._tabs.get(idx)
        if tab is not None:
            self._content_area.content = tab
        else:
            log.warning("Навигация: вкладки %d нет в _tabs — игнорирую", idx)
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

    def _on_voice_quality_change(self, e) -> None:
        quality = e.control.value
        if quality not in ("medium", "high"):
            quality = "medium"

        self.config.set("tts_voice_quality", quality)

        if self.jarvis is not None and self.jarvis.speaker is not None:
            voice = self.config.get("tts_voice", "ruslan")
            try:
                self.jarvis.speaker._init_piper(voice)
                actual = getattr(self.jarvis.speaker, "_piper_quality", quality)
                if actual != quality:
                    log.warning("Piper: %s/%s не найден, использован %s/%s",
                                voice, quality, voice, actual)
                log.info("Piper переключён на %s/%s", voice, actual)
            except Exception:
                log.exception("Не удалось переключить качество голоса")

    def _on_rate_change(self, e) -> None:
        self.config.set("voice_rate", round(float(e.control.value), 2))

    def _on_theme_change(self, e) -> None:
        theme_name = e.control.value
        if theme_name not in THEMES:
            theme_name = "Системная"
        mode = THEMES[theme_name]
        self.config.set("gui_theme", theme_name)

        if mode == ft.ThemeMode.SYSTEM:
            palette_name = _detect_system_theme()
            log.info("Системная тема: %s", palette_name)
            _apply_palette(palette_name)
        elif mode == ft.ThemeMode.LIGHT:
            _apply_palette("light")
        else:
            _apply_palette("dark")

        try:
            self._page.theme_mode = mode
            self._page.bgcolor = BG_DARK
            self._rebuild_ui_for_theme()
            self._page.update()
        except Exception:
            log.exception("Ошибка в _on_theme_change")

    def _rebuild_ui_for_theme(self) -> None:
        """Пересобирает UI с новой палитрой.

        Вызывается при смене темы И при смене профиля (№92).

        №92-fix: сохраняем историю чата перед пересборкой, чтобы
        не терять сообщения при смене темы/профиля.
        """
        current_index = self._rail.selected_index if self._rail else 0

        saved_history = []
        if self._history_list is not None:
            saved_history = list(self._history_list.controls)

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_persona_tab(),
            3: self._build_settings_tab(),
        }

        if saved_history and self._history_list is not None:
            self._history_list.controls = saved_history

        if self._content_area is not None:
            self._content_area.bgcolor = BG_DARK
            self._content_area.content = self._tabs.get(current_index, self._tabs[0])

        if self._rail is not None:
            self._rail.bgcolor = BG_CARD
            self._rail.indicator_color = ACCENT

        log.info("UI пересобран (тема/профиль), история сохранена: %d",
                 len(saved_history))

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
        """Запускает команду из GUI (текстовый ввод).

        Берёт тот же cmd_lock, что и голосовой поток — иначе два
        одновременных handle+say ломают stateful-поля IntentHandler
        и накладывают TTS.
        """
        if self.jarvis is None:
            return

        def _run():
            try:
                self.set_state("listening")
                self.add_message("user", cmd)
                self.jarvis.speaker.stop()
                self.jarvis.speaker.wait_end(timeout=1.0)
                with self.jarvis.cmd_lock:
                    reply = self.jarvis.handler.handle(cmd)
                    if not reply.is_stream:
                        self.add_message("assistant", reply.text or "")
                    self.jarvis.say(reply)
            except Exception:
                log.exception("Ошибка команды %r", cmd)
                self.set_state("error")

        threading.Thread(target=_run, daemon=True, name="gui-cmd").start()