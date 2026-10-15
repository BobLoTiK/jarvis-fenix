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
from functools import lru_cache
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import flet as ft

from jarvis.vad import DEFAULT_HANGOVER_MS

log = logging.getLogger("jarvis.gui")

PALETTES = {
    "dark": {
        "sidebar": "#10161e", "selected": "#263447",
        "brand": "#e7ad7b", "composer": "#17212d",
        "bg_main": "#0b1016",
        "bg_card": "#131c26",
        "bg_bubble_user": "#23364b",
        "bg_bubble_ai": "#17212d",
        "accent": "#8bb7ee",
        "text": "#eaf0f6",
        "text_dim": "#a1b0c1",
        "border": "#3f5266",
        "error": "#f85149",
        "success": "#3fb950",
        "warning": "#d29922",
    },
    "light": {
        "sidebar": "#eeeae4", "selected": "#dce5f0",
        "brand": "#8b512a", "composer": "#ffffff",
        "bg_main": "#f5f3ef",
        "bg_card": "#ffffff",
        "bg_bubble_user": "#e4eaf0",
        "bg_bubble_ai": "#eeeae4",
        "accent": "#245d99",
        "text": "#23272f",
        "text_dim": "#606b78",
        "border": "#b6b0a6",
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

BG_DARK = "#0b1016"
BG_CARD = "#131c26"
BG_BUBBLE_USER = "#23364b"
BG_BUBBLE_AI = "#17212d"
ACCENT = "#8bb7ee"
TEXT = "#eaf0f6"
TEXT_DIM = "#a1b0c1"


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
    "idle": ("#8bb7ee", "Готов", "Скажите «Феникс» или напишите сообщение"),
    "listening": ("#d29922", "Слушаю", "Можно говорить"),
    "recognizing": ("#d29922", "Распознаю", "Проверяю услышанное"),
    "thinking": ("#8bb7ee", "Обрабатываю", "Ответ появится здесь"),
    "speaking": ("#3fb950", "Говорю", "Озвучку можно остановить"),
    "awaiting": ("#d29922", "Жду уточнения", "Ответьте на вопрос или напишите «отмена»"),
    "password": ("#d29922", "Нужен пароль", "Ввод скрыт и не попадёт в чат"),
    "error": ("#f85149", "Ошибка", "Подробности — в сообщении об ошибке"),
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

TTS_BACKENDS = ["auto", "piper", "silero", "winrt", "sapi"]


@lru_cache(maxsize=32)
def _brand_bytes(name: str, theme: str) -> bytes:
    return (Path(__file__).resolve().parent / "assets" / "brand" / f"{name}-{theme}.png").read_bytes()


def _brand_image(name: str, size: int, label: str = ""):
    theme = "light" if P.sidebar == PALETTES["light"]["sidebar"] else "dark"
    return ft.Image(src=_brand_bytes(name, theme), width=size, height=size,
                    fit=ft.BoxFit.CONTAIN, filter_quality=ft.FilterQuality.HIGH, anti_alias=True,
                    semantics_label=label, exclude_from_semantics=not bool(label))


NAV_ITEMS = (
    ("Диалог", ft.Icons.CHAT_BUBBLE_OUTLINE),
    ("Микрофон", ft.Icons.MIC_NONE),
    ("Голос и звук", ft.Icons.GRAPHIC_EQ),
    ("Персона", ft.Icons.PERSON_OUTLINE),
    ("Настройки", ft.Icons.TUNE),
    ("Мои команды", ft.Icons.ACCOUNT_TREE_OUTLINED),
)


class _Sidebar(ft.Container):
    """Native sidebar; selection is shared by mouse navigation and tray actions."""

    def __init__(self, on_select):
        super().__init__(width=208, padding=16)
        self._selected_index = 0
        self._on_select = on_select
        self.refresh_palette()

    @property
    def selected_index(self):
        return self._selected_index

    @selected_index.setter
    def selected_index(self, value):
        if not 0 <= value < len(NAV_ITEMS):
            return
        self._selected_index = value
        # Preserve button IDs/focus during quick navigation. Rebuild only for a theme/profile.
        for index, button in enumerate(self.nav_buttons):
            active = index == value
            button.bgcolor = P.selected if active else P.sidebar
            button.content.controls[1].color = TEXT if active else TEXT_DIM
            button.content.controls[2].visible = active

    def refresh_palette(self):
        from jarvis import profile
        self.bgcolor = P.sidebar
        self.border = ft.Border(right=ft.BorderSide(1, P.border))
        self.nav_buttons = []
        for index, (label, icon) in enumerate(NAV_ITEMS):
            active = index == self._selected_index
            self.nav_buttons.append(ft.Button(
                content=ft.Row([_brand_image(("dialog", "microphone", "audio", "persona", "settings", "commands")[index], 24),
                                ft.Text(label, size=14, color=TEXT if active else TEXT_DIM,
                                        expand=True),
                                ft.Container(width=5, height=5, border_radius=3,
                                             bgcolor=ACCENT, visible=active)], spacing=10),
                height=48, bgcolor=P.selected if active else P.sidebar, elevation=0,
                style=ft.ButtonStyle(padding=10, shape=ft.RoundedRectangleBorder(radius=10)),
                tooltip=label,
                on_click=lambda e, i=index: self._on_select(i)))
        self.content = ft.Column([
            ft.Container(content=ft.Row([
                _brand_image("phoenix", 38, "Феникс"),
                ft.Column([ft.Text("Феникс", size=21, weight=ft.FontWeight.BOLD, color=TEXT),
                           ft.Text("Локальный ассистент", size=12, color=TEXT_DIM)],
                          spacing=2, expand=True)], spacing=12), padding=ft.Padding(top=12, bottom=28)),
            *self.nav_buttons,
            ft.Container(expand=True),
            ft.Divider(color=P.border),
            ft.Container(ft.Column([
                ft.Text(str(profile.current()), size=14, color=TEXT, max_lines=2),
                ft.Text("Профиль и настройки", size=12, color=TEXT_DIM)], spacing=4),
                padding=ft.Padding(top=12, bottom=12)),
        ], spacing=8, expand=True)


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

        # Трей: если иконка поднялась (jarvis.tray.start_tray), закрытие
        # окна крестиком сворачивает Феникса в трей, а не убивает процесс.
        self.tray_active = False

        # Состояние
        self._state = "idle"
        self._stream_bubble = None
        self._stream_text = ""
        self._stream_label = None
        self._messages = []
        self._draft = ""
        self._follow_chat = True
        self._command_lock = threading.Lock()
        self._command_busy = False
        self._command_thread = None
        self._send_btn = None
        self._stop_btn = None
        self._empty_chat = None
        self._error_banner = None
        self._error_text = None
        self._latest_btn = None
        self._input_hint = None

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
        self._command_builder = None

        # Контролы вкладки «Микрофон»
        self._mic_dropdown = None
        self._mic_level_bar = None
        self._mic_level_text = None
        self._mic_status_text = None
        self._mic_peak_text = None
        self._mic_utt_text = None
        self._mic_test_result = None
        self._mic_device_text = None
        self._vad_threshold_label = None
        self._vad_hangover_label = None

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

    def set_tray_active(self, active: bool) -> None:
        """Включает/выключает режим «закрытие окна сворачивает в трей».

        Зовётся из main.py, когда иконку подняли или сняли (в т.ч. на
        лету по чекбоксу «Иконка в трее»). prevent_close ставим заранее:
        в обработчике CLOSE флаг уже опаздывает.
        """
        self.tray_active = bool(active)
        try:
            if self._page is not None:
                self._page.window.prevent_close = self.tray_active
                self._page.update()
            log.info(
                "GUI: трей %s — закрытие окна %s",
                "включён" if self.tray_active else "выключен",
                "свернёт Феникса" if self.tray_active else "закроет его",
            )
        except Exception:
            log.exception("GUI: не удалось применить режим трея")

    def open_settings_tab(self) -> None:
        """Открыть GUI на вкладке «Настройки»."""
        self._queue.put(("open_settings_tab", None))

    def quit(self) -> None:
        """Закрывает Феникса целиком — для пункта «Выход» в трее.

        stop() останавливает только очередь GUI: окно Flet остаётся
        жить, а вместе с ним и процесс (ft.run не возвращается). Чтобы
        выход реально работал, снимаем prevent_close и закрываем окно.
        """
        self._queue.put(("stop", None))
        try:
            if self._page is not None:
                self._page.window.prevent_close = False
                self._page.window.close()
                log.info("GUI: окно закрыто (выход)")
        except Exception:
            log.exception("GUI: не удалось закрыть окно")

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

        # Позиция окна запоминается: gui_x / gui_y раньше только читались,
        # а сохранять их было некому — окно всегда открывалось по умолчанию.
        page.window.on_event = self._on_window_event

        # Трей к этому моменту уже поднят (main.py выставляет tray_active
        # ДО ft.run): если он есть, закрывать окно нельзя — Феникс умер бы
        # вместе с ним. prevent_close применяем ЗАРАНЕЕ, в обработчике
        # CLOSE флаг уже опаздывает.
        if self.tray_active:
            self.set_tray_active(True)

        # launch_mode=tray — окно скрыто
        if self.start_hidden:
            page.window.visible = False
            log.info("GUI: окно скрыто при старте (launch_mode=tray)")

        self._build_ui(page)
        page.run_task(self._process_queue)
        page.run_task(self._mic_level_loop)

    def _build_ui(self, page: ft.Page) -> None:
        self._rail = _Sidebar(self._select_tab)

        self._tabs = {
            0: self._build_main_tab(),
            1: self._build_mic_tab(),
            2: self._build_audio_tab(),
            3: self._build_persona_tab(),
            4: self._build_settings_tab(),
            5: self._build_commands_tab(),
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
        self._status_circle = ft.Container(width=6, height=6, border_radius=3, bgcolor=ACCENT)
        self._status_text = ft.Text(size=13, color=TEXT)
        self._status_sub = ft.Text(size=12, color=TEXT_DIM)
        self._mood_text = ft.Text("", size=12, color=TEXT_DIM, visible=False)
        header = ft.Container(
            content=ft.Row([
                ft.Text("Рабочее пространство  /  Диалог", size=14, color=TEXT_DIM, expand=True),
                ft.Container(ft.Row([self._status_circle, self._status_text], spacing=8),
                             padding=10, bgcolor=P.sidebar, border_radius=8,
                             border=ft.Border.all(1, P.border)),
                ft.IconButton(icon=ft.Icons.INFO_OUTLINE, icon_color=TEXT_DIM,
                              tooltip="Настройки и диагностика", on_click=lambda e: self._select_tab(4)),
            ], spacing=12), padding=ft.Padding(left=28, right=24, top=16, bottom=16),
            border=ft.Border(bottom=ft.BorderSide(1, P.border)))
        self._error_text = ft.Text("", size=14, color=P.error, selectable=True, expand=True)
        self._error_banner = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, color=P.error), self._error_text,
                           ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Скрыть сообщение",
                                         on_click=self._dismiss_error)]),
            bgcolor=BG_CARD, border=ft.Border.all(1, P.error), border_radius=8,
            padding=12, margin=ft.Margin(left=24, right=24, top=12), visible=False)
        self._brand_mark = ft.Container(
            _brand_image("phoenix", 88, "Феникс — птица"),
            width=100, height=100, border_radius=24, alignment=ft.Alignment.CENTER,
            bgcolor=P.sidebar, border=ft.Border.all(1, P.brand))
        scenarios = (
            ("Сосредоточиться", "Поставить таймер", ft.Icons.TIMER_OUTLINED, "Поставь таймер"),
            ("Открыть приложение", "Перейти к делу", ft.Icons.WINDOW_OUTLINED, "Открой"),
            ("Просто поговорить", "Начать с интересного", ft.Icons.CHAT_OUTLINED, "Расскажи что-нибудь"),
        )
        self._scenario_cards = []
        for title, subtitle, icon, command in scenarios:
            self._scenario_cards.append(ft.Button(
                content=ft.Column([
                    ft.Row([_brand_image({ft.Icons.TIMER_OUTLINED: "timer", ft.Icons.WINDOW_OUTLINED: "app", ft.Icons.CHAT_OUTLINED: "dialog"}[icon], 24),
                            ft.Container(expand=True), ft.Icon(ft.Icons.NORTH_EAST, size=16, color=TEXT_DIM)]),
                    ft.Text(title, size=14, color=TEXT),
                    ft.Text(subtitle, size=12, color=TEXT_DIM),
                ], spacing=8, tight=True), expand=True, height=108,
                bgcolor=BG_CARD, elevation=0,
                style=ft.ButtonStyle(padding=16, side=ft.BorderSide(1, P.border),
                                     shape=ft.RoundedRectangleBorder(radius=12)),
                tooltip=title, on_click=lambda e, text=command: self._fill_input(text)))
        self._empty_chat = ft.Container(
            content=ft.Column([
                self._brand_mark,
                ft.Text("Твой голос. Начало действия.", size=32, weight=ft.FontWeight.BOLD,
                        color=TEXT, text_align=ft.TextAlign.CENTER),
                ft.Container(ft.Text("Открою нужное, помогу с делами или просто побуду собеседником. С чего начнём?",
                                    size=15, color=TEXT_DIM, text_align=ft.TextAlign.CENTER), width=540),
                ft.Container(ft.Row(self._scenario_cards, spacing=12), padding=ft.Padding(top=16)),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20),
            padding=ft.Padding(left=8, right=8, top=32, bottom=24), alignment=ft.Alignment.CENTER)
        self._history_list = ft.ListView(spacing=16, auto_scroll=self._follow_chat,
                                         on_scroll=self._on_chat_scroll, expand=True)
        self._render_history()
        self._latest_btn = ft.Button("К последнему сообщению", height=44, visible=not self._follow_chat,
                                     on_click=self._scroll_latest)
        body = ft.Container(content=self._history_list, expand=True,
                            padding=ft.Padding(left=28, right=28, top=12, bottom=8))
        view = ft.Column([header, self._error_banner, body,
                          ft.Row([self._latest_btn], alignment=ft.MainAxisAlignment.CENTER),
                          self._build_controls(), self._build_input()], spacing=0, expand=True)
        from jarvis import mood as _mood
        self._apply_mood_color(_mood.get_state())
        self._apply_state(self._state)
        self._apply_busy(self._command_busy)
        return view

    def _build_controls(self) -> ft.Container:
        mode = ft.Dropdown(
            label="Режим", value=self.config.get("mode", "combo"), width=110,
            options=[ft.dropdown.Option("commands", "Команды"), ft.dropdown.Option("llm", "ИИ"),
                     ft.dropdown.Option("combo", "Комбо")], on_select=self._on_mode_change,
            text_size=13, dense=True, border_color=P.border, focused_border_color=ACCENT)
        voice = ft.Dropdown(label="Голос", value=self.config.get("tts_voice", "ruslan"),
                            options=self._get_voice_options(), width=125, text_size=13, dense=True,
                            on_select=self._on_voice_change, border_color=P.border,
                            focused_border_color=ACCENT)
        mm = self.config.get("memory_max", 100)
        memory = ft.Dropdown(label="История", width=135, dense=True,
                             value={40: "short", 100: "normal", 200: "long"}.get(mm, "normal"),
                             options=[ft.dropdown.Option("short", "Короткая"),
                                      ft.dropdown.Option("normal", "Обычная"),
                                      ft.dropdown.Option("long", "Долгая")],
                             on_select=self._on_memory_change, text_size=13,
                             border_color=P.border, focused_border_color=ACCENT)
        self._model_label = ft.Text(self._model_caption(), size=12, color=TEXT_DIM,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                    tooltip="Выбранная модель, не проверка доступности сервера")
        return ft.Container(content=ft.Row([
            mode, voice, memory,
            ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Обновить голоса",
                          icon_color=TEXT_DIM, on_click=self._on_refresh_voices),
            ft.Container(content=self._model_label, expand=True, alignment=ft.Alignment.CENTER_RIGHT),
        ], spacing=8), padding=ft.Padding(left=28, right=28, top=8, bottom=12))

    def _model_caption(self) -> str:
        if self.config.get("mode", "combo") == "commands":
            return "Команды · без LLM"
        return "Модель: " + str(self.config.get("llm_model", "не выбрана"))

    def _build_input(self) -> ft.Container:
        self._input_field = ft.TextField(
            value=self._draft, hint_text="Напиши, что нужно сделать…",
            multiline=True, min_lines=1, max_lines=4, shift_enter=True,
            border=ft.InputBorder.NONE, text_size=15, color=TEXT,
            content_padding=ft.Padding(left=4, right=4, top=8, bottom=8),
            on_submit=self._on_send, on_change=self._on_input_change)
        listening = self.jarvis is None or getattr(self.jarvis, "listening_enabled", True)
        self._mic_btn = ft.IconButton(
            icon=ft.Icons.MIC if listening else ft.Icons.MIC_OFF,
            icon_color=TEXT_DIM if listening else P.error, icon_size=22,
            width=44, height=44, tooltip="Приостановить / включить микрофон",
            on_click=self._on_mic_toggle)
        self._send_btn = ft.IconButton(icon=ft.Icons.ARROW_UPWARD, icon_color="#241b14",
                                       bgcolor="#e9ad79", style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=11)),
                                       width=44, height=44, tooltip="Отправить · Enter", on_click=self._on_send)
        self._stop_btn = ft.IconButton(icon=ft.Icons.STOP_ROUNDED, icon_color=P.error,
                                       width=44, height=44, tooltip="Остановить озвучку (не отменяет действие)",
                                       on_click=self._on_stop_speech)
        self._input_hint = ft.Text("Enter — отправить · Shift+Enter — новая строка", size=12, color=TEXT_DIM)
        composer = ft.Container(ft.Column([
            self._input_field,
            ft.Row([self._mic_btn, ft.Column([self._status_sub, self._mood_text], spacing=2, expand=True),
                    self._stop_btn, self._send_btn], spacing=8),
        ], spacing=4), padding=12, bgcolor=P.composer, border_radius=16,
            border=ft.Border.all(1, P.border))
        return ft.Container(content=ft.Column([
            composer, ft.Row([self._input_hint, ft.Text("Подсказки не запускают действия", size=11, color=TEXT_DIM)],
                             alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
        ], spacing=8), padding=ft.Padding(left=28, right=28, top=0, bottom=16))

    def _on_input_change(self, e) -> None:
        self._draft = "" if self._input_field.password else (e.control.value or "")

    def _fill_input(self, text: str) -> None:
        if self._input_field is not None and not self._input_field.password:
            self._input_field.value = text
            if self._page is not None:
                self._page.update()

    def _dismiss_error(self, e=None) -> None:
        if self._error_banner is not None:
            self._error_banner.visible = False
        if self._state == "error":
            self._apply_state("idle")
        if self._page is not None:
            try:
                self._page.update()
            except Exception:
                log.debug("Страница уже закрыта")

    def _apply_error(self, text: str) -> None:
        if self._error_text is not None:
            self._error_text.value = text
            self._error_banner.visible = True
        self._apply_state("error")

    def _apply_busy(self, busy: bool) -> None:
        if self._send_btn is not None:
            self._send_btn.disabled = busy
        # Keep a draft editable; do not queue another action behind the current one.
        if self._stop_btn is not None:
            self._stop_btn.disabled = self._state != "speaking"
            self._stop_btn.icon_color = P.error if self._state == "speaking" else TEXT_DIM

    def _on_stop_speech(self, e=None) -> None:
        if self.jarvis is None:
            return
        self.jarvis.speaker.stop()
        # Do not pretend to cancel handle(), a network request or an OS action.
        self._show_status("Озвучка остановлена. Выполненные действия не отменяются.")

    def _on_chat_scroll(self, e) -> None:
        if self._follow_chat:
            # Layout/auto-scroll updates must not be mistaken for a reader scrolling up.
            if e.event_type != ft.ScrollType.USER or e.direction != ft.ScrollDirection.FORWARD:
                return
            self._follow_chat = False
        else:
            self._follow_chat = e.max_scroll_extent - e.pixels < 48
        self._history_list.auto_scroll = self._follow_chat
        self._latest_btn.visible = not self._follow_chat
        if self._page is not None:
            self._page.update()

    async def _scroll_latest(self, e=None) -> None:
        self._history_list.auto_scroll = False
        await self._history_list.scroll_to(offset=-1, duration=0)
        self._follow_chat = True
        self._history_list.auto_scroll = True
        self._latest_btn.visible = False
        if self._page is not None:
            self._page.update()

    async def _copy_message(self, record) -> None:
        try:
            await ft.Clipboard().set(record["text"])
            self._show_status("Сообщение скопировано")
        except Exception:
            log.exception("Не удалось скопировать сообщение")
            self._show_status("Не удалось скопировать. Выделите текст вручную.")

    def _build_commands_tab(self):
        from jarvis.gui_commands import CommandBuilder
        if self._command_builder is None:
            self._command_builder = CommandBuilder(self)
        return self._command_builder.build()

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
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_mic_change,
        )

        self._mic_level_bar = ft.ProgressBar(
            value=0.0,
            width=400,
            color=ACCENT,
            bgcolor="#17212d",
        )
        self._mic_level_text = ft.Text("Уровень сигнала: —", size=13, color=TEXT_DIM)
        self._mic_status_text = ft.Text("Статус: ожидание проверки", size=13, color=TEXT_DIM)
        self._mic_peak_text = ft.Text("Пик за сессию: 0", size=13, color=TEXT_DIM)
        self._mic_utt_text = ft.Text("Распознано фраз: 0", size=13, color=TEXT_DIM)
        self._mic_emotion_text = ft.Text(
            "Эмоция: —", size=13, color=TEXT_DIM,
        )
        self._mic_test_result = ft.Text("", size=13, color=TEXT_DIM)
        # «Текущее устройство» — вынесено в поле, чтобы текст обновлялся
        # сразу после смены микрофона, а не только при пересборке вкладки.
        self._mic_device_text = ft.Text(
            f"Текущее устройство: {name}", size=14, color=TEXT,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Микрофон", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=25),
                    self._mic_device_text,
                    ft.Container(height=20),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                self._mic_level_text,
                                self._mic_level_bar,
                                ft.Container(height=8),
                                self._mic_peak_text,
                                self._mic_utt_text,
                                self._mic_emotion_text,
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
        """Смена микрофона применяется на лету (без перезапуска).

        Раньше здесь только писался config, а в лог шло «перезапусти
        Феникса». Теперь подписчик в main.py зовёт
        listener.set_input_device(), а поток слушателя переоткрывает
        RawInputStream на новом устройстве.
        """
        value = e.control.value
        if value == "по умолчанию":
            value = None
        self.config.set("input_device", value)
        if getattr(self, "_mic_device_text", None) is not None:
            listener = self.jarvis.listener if self.jarvis is not None else None
            shown = listener.device_name if listener is not None else (
                value or "по умолчанию")
            self._mic_device_text.value = f"Текущее устройство: {shown}"
        self._show_status(
            "Микрофон переключён. Скажите «Феникс» — проверю, что слышу."
        )
        log.info("GUI: input_device → %r (применяю на лету)", value)

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

            if getattr(self, "_mic_emotion_text", None):
                if listener.peak > 2500:
                    emo = "excited / annoyed"
                elif listener.peak > 200:
                    emo = "neutral / happy"
                else:
                    emo = "tired / тишина"
                self._mic_emotion_text.value = f"Эмоция: ~{emo}"
        except Exception:
            log.exception("_update_mic_level упал")

    def _build_audio_tab(self) -> ft.Control:
        """Вкладка «Аудио» — Non-verbal, VAD и Prosody."""

        nonverbal_enabled = ft.Checkbox(
            label="Звуковые реакции (смех, вздохи, хм, зевок)",
            value=bool(self.config.get("nonverbal_enabled", False)),
            on_change=self._on_nonverbal_enabled,
        )
        nonverbal_hint = ft.Text(
            "Только в диалоге, не чаще раза в 45 секунд по умолчанию. "
            "Тише речи на 15 дБ. Silero, Piper и WinRT; SAPI — без реакций.",
            size=11, color=TEXT_DIM,
        )

        # === Prosody ===
        prosody_enabled = ft.Checkbox(
            label="Эмоции из голоса (Prosody)",
            value=bool(self.config.get("prosody_enabled", True)),
            on_change=self._on_prosody_enabled,
        )

        prosody_priority = ft.Dropdown(
            label="Приоритет эмоций",
            value=self.config.get("prosody_priority", "prosody"),
            options=[
                ft.dropdown.Option("prosody", "Голос важнее текста"),
                ft.dropdown.Option("text", "Текст важнее голоса"),
                ft.dropdown.Option("both", "Оба (голос первым)"),
            ],
            width=400,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_prosody_priority,
        )

        prosody_hint = ft.Text(
            "Prosody определяет эмоцию из громкости, высоты и «шумности» "
            "голоса (RMS + pitch + ZCR). Точность ~60–70%.",
            size=11,
            color=TEXT_DIM,
        )

        # === VAD ===
        vad_enabled = ft.Checkbox(
            label="VAD (Silero) — фильтр тишины до распознавания",
            value=bool(self.config.get("vad_enabled", True)),
            on_change=self._on_vad_enabled,
        )

        vad_adaptive = ft.Checkbox(
            label="Адаптивный порог (подстраивается под микрофон)",
            value=bool(self.config.get("vad_adaptive", True)),
            on_change=self._on_vad_adaptive,
        )

        # Модель silero_vad.onnx в комплект не входит (в репозитории её
        # нет) — Феникс качает её сам. Флаг нужен для машин без сети.
        vad_auto_download = ft.Checkbox(
            label="Скачивать модель VAD (2.3 МБ), если её ещё нет",
            value=bool(self.config.get("vad_auto_download", True)),
            on_change=self._on_vad_auto_download,
        )

        auto_download_hint = ft.Text(
            "Модель silero_vad.onnx качается фоном при первом запуске и "
            "включается без перезапуска. Без неё VAD молча не работает.",
            size=11,
            color=TEXT_DIM,
        )

        self._vad_threshold_label = ft.Text(
            f"Порог VAD: {self.config.get('vad_threshold', 0.5):.2f}",
            size=13,
            color=TEXT,
        )

        self._vad_threshold_slider = ft.Slider(
            min=0.1,
            max=0.9,
            divisions=16,
            value=float(self.config.get("vad_threshold", 0.5)),
            label="{value:.2f}",
            active_color=ACCENT,
            on_change=self._on_vad_threshold_change,
            on_change_end=self._on_vad_threshold_end,
        )

        vad_hint = ft.Text(
            "VAD отсекает тишину и шум — Vosk не получает пустые чанки. "
            "Порог 0.3 — ловит тихую речь, 0.7 — только громкую.",
            size=11,
            color=TEXT_DIM,
        )

        # «Хвост» тишины. Без него VAD вырезает всю тишину, Vosk не видит
        # паузу (`AcceptWaveform` -> False) и не отдаёт финальный текст:
        # Феникс отвечает поздно или не отвечает вовсе. См. jarvis/vad.py.
        self._vad_hangover_label = ft.Text(
            f"Хвост тишины для Vosk: "
            f"{int(self.config.get('vad_hangover_ms', DEFAULT_HANGOVER_MS))} мс",
            size=13,
            color=TEXT,
        )

        self._vad_hangover_slider = ft.Slider(
            min=0,
            max=3000,
            divisions=12,
            value=float(self.config.get("vad_hangover_ms", DEFAULT_HANGOVER_MS)),
            label="{value:.0f}",
            active_color=ACCENT,
            on_change=self._on_vad_hangover_change,
            on_change_end=self._on_vad_hangover_end,
        )

        hangover_hint = ft.Text(
            "1500 мс — как без VAD. Меньше — ответ раньше, но Vosk может "
            "не успеть закрыть фразу. Применяется сразу.",
            size=11,
            color=TEXT_DIM,
        )

        # === Распознавание ===
        barge_enabled = ft.Checkbox(
            label="Прерывать Феникса голосом (barge-in)",
            value=bool(self.config.get("barge_enabled", True)),
            on_change=self._on_barge_enabled,
        )

        wake_required = ft.Checkbox(
            label="Ждать wake-слово «Феникс» (выкл — любая речь = команда)",
            value=bool(self.config.get("wake_word_required", True)),
            on_change=self._on_wake_required,
        )

        def _section(title):
            return ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=ACCENT)

        def _label(text):
            return ft.Text(text, size=12, color=TEXT_DIM)

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text("Аудио", size=26, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(height=20),

                    _section("Звуковые реакции"),
                    nonverbal_enabled,
                    nonverbal_hint,
                    ft.Container(height=25),
                    _section("Эмоции из голоса (Prosody)"),
                    prosody_enabled,
                    prosody_hint,
                    ft.Container(height=10),
                    _label("Как определять эмоцию:"),
                    prosody_priority,
                    ft.Container(height=25),

                    _section("VAD — фильтр тишины"),
                    vad_enabled,
                    vad_adaptive,
                    vad_auto_download,
                    auto_download_hint,
                    ft.Container(height=8),
                    self._vad_threshold_label,
                    self._vad_threshold_slider,
                    vad_hint,
                    ft.Container(height=8),
                    self._vad_hangover_label,
                    self._vad_hangover_slider,
                    hangover_hint,
                    ft.Container(height=25),

                    _section("Распознавание"),
                    barge_enabled,
                    wake_required,
                    ft.Container(height=8),
                    _label("Всё на этой вкладке применяется сразу, "
                           "перезапуск не нужен."),
                ],
                spacing=8,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.Padding(left=40, top=40, right=40, bottom=40),
            expand=True,
        )

    def _build_persona_tab(self) -> ft.Control:
        """Вкладка «Персона» — имя, стиль, черты, backstory."""
        from jarvis import persona

        p = persona.get()

        name_field = ft.TextField(
            label="Имя пользователя",
            value=self.config.get("name", "") or "",
            width=400,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_submit=self._on_persona_name,
        )

        assistant_name_field = ft.TextField(
            label="Имя ассистента",
            value=p.get("assistant_name") or "Феникс",
            width=400,
            border_color="#3f5266",
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
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_persona_style,
        )

        tone_dropdown = ft.Dropdown(
            label="Тон общения",
            value=p.get("tone") or "auto",
            options=[
                ft.dropdown.Option("auto", "Авто (подстраивается)"),
                ft.dropdown.Option("polite", "Вежливый (без мата)"),
                ft.dropdown.Option("unrestricted", "Без цензуры (если юзер сам)"),
            ],
            width=400,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_persona_tone,
        )

        tone_hint = ft.Text(
            "Авто — Феникс сам подстраивается под ваш стиль. "
            "Вежливый — всегда без мата. Без цензуры — можно вставить, если вы сами.",
            size=11,
            color=TEXT_DIM,
        )

        traits_field = ft.TextField(
            label="Черты (через запятую)",
            value=", ".join(p.get("traits") or []),
            width=400,
            border_color="#3f5266",
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
            border_color="#3f5266",
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
                    _label("Тон общения:"),
                    tone_dropdown,
                    tone_hint,
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

    def _on_persona_tone(self, e) -> None:
        from jarvis import persona
        tone = e.control.value
        if tone not in persona.VALID_TONES:
            tone = "auto"
        persona.set_field("tone", tone)
        log.info("GUI: persona.tone → %s", tone)

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

    def _on_nonverbal_enabled(self, e) -> None:
        self.config.set("nonverbal_enabled", bool(e.control.value))

    def _on_prosody_enabled(self, e) -> None:
        value = bool(e.control.value)
        self.config.set("prosody_enabled", value)
        log.info("GUI: prosody_enabled → %s", value)

    def _on_prosody_priority(self, e) -> None:
        value = e.control.value
        if value not in ("prosody", "text", "both"):
            value = "prosody"
        self.config.set("prosody_priority", value)
        log.info("GUI: prosody_priority → %s", value)

    def _on_vad_enabled(self, e) -> None:
        value = bool(e.control.value)
        self.config.set("vad_enabled", value)
        log.info("GUI: vad_enabled → %s", value)

    def _on_vad_adaptive(self, e) -> None:
        value = bool(e.control.value)
        self.config.set("vad_adaptive", value)
        log.info("GUI: vad_adaptive → %s", value)

    def _on_vad_auto_download(self, e) -> None:
        """Вкл/выкл авто-скачивание модели VAD (применяется на лету)."""
        value = bool(e.control.value)
        self.config.set("vad_auto_download", value)
        log.info("GUI: vad_auto_download → %s (применяю на лету)", value)

    def _on_tray_enabled(self, e) -> None:
        """Вкл/выкл иконку в трее (применяется на лету, см. main._apply_tray)."""
        value = bool(e.control.value)
        self.config.set("tray_enabled", value)
        log.info("GUI: tray_enabled → %s (применяю на лету)", value)

    def _on_observer_enabled(self, e) -> None:
        """Observer — согласие на фоновый анализ диалога.

        Выключен по умолчанию (DEFAULT_CONFIG): галочка = согласие
        пользователя. Поток поднимается на старте, поэтому эффект —
        после перезапуска (как у режима запуска).
        """
        value = bool(e.control.value)
        self.config.set("observer_enabled", value)
        log.info("GUI: observer_enabled → %s (применится после перезапуска)", value)
        if value:
            self._show_status(
                "Observer включён: последние сообщения диалога уйдут "
                "локальной LLM, извлечённые факты — в profile.json, "
                "ход извлечения — в logs/observer.log. "
                "Заработает после перезапуска Феникса."
            )
        else:
            self._show_status(
                "Observer выключен. Перезапусти Феникса, чтобы фоновый "
                "анализ диалога остановился."
            )

    def _on_memory_rag_enabled(self, e) -> None:
        """Векторная память — отбор фактов по смыслу запроса.

        В отличие от Observer, перезапуск не нужен: vectormem читает
        конфиг на каждый вызов, а подписчик в main.py будит индексацию.
        """
        value = bool(e.control.value)
        self.config.set("memory_rag_enabled", value)
        log.info("GUI: memory_rag_enabled → %s (применяется сразу)", value)
        if value:
            self._show_status(
                "Векторная память включена: Феникс будет подбирать факты "
                "под запрос. Нужна модель эмбеддингов — если её нет, "
                "выполни «ollama pull nomic-embed-text» (~274 МБ). "
                "Индекс: %APPDATA%\\Phoenix\\profiles\\<профиль>\\memory_index.json"
            )
        else:
            self._show_status(
                "Векторная память выключена: в промпт снова уходят все "
                "факты о тебе, как раньше. Индекс остаётся на диске."
            )

    def _on_launch_mode(self, e) -> None:
        """Режим запуска (gui/tray) — применится при следующем старте."""
        value = e.control.value
        if value not in ("gui", "tray"):
            value = "gui"
        self.config.set("launch_mode", value)
        log.info("GUI: launch_mode → %s (применится после перезапуска)", value)

    def _on_vad_threshold_change(self, e) -> None:
        value = float(e.control.value)
        if hasattr(self, "_vad_threshold_label") and self._vad_threshold_label:
            self._vad_threshold_label.value = f"Порог VAD: {value:.2f}"

    def _on_vad_threshold_end(self, e) -> None:
        value = round(float(e.control.value), 2)
        self.config.set("vad_threshold", value)
        log.info("GUI: vad_threshold → %.2f (применяю на лету)", value)

    def _on_vad_hangover_change(self, e) -> None:
        value = float(e.control.value)
        if getattr(self, "_vad_hangover_label", None):
            self._vad_hangover_label.value = f"Хвост тишины для Vosk: {int(value)} мс"

    def _on_vad_hangover_end(self, e) -> None:
        value = int(round(float(e.control.value)))
        self.config.set("vad_hangover_ms", value)
        log.info("GUI: vad_hangover_ms → %d (применяю на лету)", value)

    def _on_barge_enabled(self, e) -> None:
        value = bool(e.control.value)
        self.config.set("barge_enabled", value)
        log.info("GUI: barge_enabled → %s", value)

    def _on_wake_required(self, e) -> None:
        value = bool(e.control.value)
        self.config.set("wake_word_required", value)
        log.info("GUI: wake_word_required → %s", value)

    def _build_settings_tab(self) -> ft.Control:
        llm_dropdown = ft.Dropdown(
            value=self.config.get("llm_model", "qwen2.5:7b-instruct"),
            options=[ft.dropdown.Option(m) for m in LLM_MODELS],
            width=350,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_llm_change,
        )

        ollama_field = ft.TextField(
            value=self.config.get("ollama_url", "http://127.0.0.1:11434"),
            width=400,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_submit=self._on_ollama_change,
        )

        tts_dropdown = ft.Dropdown(
            value=self.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(b) for b in TTS_BACKENDS],
            width=250,
            border_color="#3f5266",
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
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_theme_change,
        )

        # Трей: ключи были в config, но контролов не было вообще —
        # включить иконку можно было только правкой config.json.
        tray_checkbox = ft.Checkbox(
            label="Иконка в трее (закрытие окна сворачивает Феникса)",
            value=bool(self.config.get("tray_enabled", True)),
            on_change=self._on_tray_enabled,
        )

        launch_dropdown = ft.Dropdown(
            value=str(self.config.get("launch_mode", "gui") or "gui"),
            options=[
                ft.dropdown.Option("gui", "Обычный — окно при старте"),
                ft.dropdown.Option("tray", "Только трей — окно скрыто"),
            ],
            width=300,
            border_color="#3f5266",
            focused_border_color=ACCENT,
            on_select=self._on_launch_mode,
        )

        launch_hint = ft.Text(
            "Режим запуска применяется при следующем запуске Феникса.",
            size=11,
            color=TEXT_DIM,
        )

        # Observer — фоновая отправка истории диалога в LLM. По умолчанию
        # выключен: включение галочки = согласие пользователя.
        observer_checkbox = ft.Checkbox(
            label="Фоновый анализ диалога (Observer) — запоминать факты о тебе",
            value=bool(self.config.get("observer_enabled", False)),
            on_change=self._on_observer_enabled,
        )

        observer_hint = ft.Text(
            "Раз в ~30 секунд последние сообщения диалога уходят в "
            "локальную LLM (Ollama) — из них извлекаются факты: имя, "
            "город, работа. Факты пишутся в profile.json (%APPDATA%\\Phoenix), "
            "ход извлечения — в logs/observer.log. Выключено по умолчанию, "
            "применяется после перезапуска.",
            size=11,
            color=TEXT_DIM,
        )

        # Векторная память фактов (RAG). Тоже по умолчанию выключена:
        # это производная обработка данных о пользователе. Новых данных
        # не собирает — только отбирает уже сохранённые факты.
        rag_checkbox = ft.Checkbox(
            label="Подбирать факты по смыслу (векторная память, RAG)",
            value=bool(self.config.get("memory_rag_enabled", False)),
            on_change=self._on_memory_rag_enabled,
        )

        rag_hint = ft.Text(
            "Когда фактов много, в промпт уходят только релевантные "
            "запросу — остальные не мешают. Нужна модель эмбеддингов: "
            "«ollama pull nomic-embed-text» (~274 МБ). Всё локально: "
            "запросы идут только в Ollama на этом же компьютере, "
            "индекс лежит в memory_index.json рядом с profile.json. "
            "Выключено по умолчанию, применяется сразу.",
            size=11,
            color=TEXT_DIM,
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
                    ft.Container(height=25),
                    _section("Приложение"),
                    tray_checkbox,
                    ft.Container(height=8),
                    _label("Режим запуска:"),
                    launch_dropdown,
                    launch_hint,
                    ft.Container(height=25),
                    _section("Приватность"),
                    observer_checkbox,
                    ft.Container(height=8),
                    observer_hint,
                    ft.Container(height=12),
                    rag_checkbox,
                    ft.Container(height=8),
                    rag_hint,
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
                elif kind == "busy":
                    self._apply_busy(self._command_busy)
                elif kind == "clear_error":
                    self._dismiss_error()
                elif kind == "command_error":
                    self._apply_error(value)
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

                if self._state == "awaiting":
                    self._queue.put(("state", "idle"))
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
        if state == "idle":
            handler = getattr(self.jarvis, "handler", None)
            if getattr(handler, "_pending_password", None):
                state = "password"
            else:
                from jarvis.intents.clarification import pending_alive
                if pending_alive(getattr(handler, "_pending_question", None)):
                    state = "awaiting"
        self._state = state
        color, text, sub = STATES[state]
        if P is not None:
            color = {"idle": ACCENT, "thinking": ACCENT, "speaking": P.success,
                     "error": P.error}.get(state, P.warning)
        if state == "idle" and not getattr(self.jarvis, "listening_enabled", True):
            text, sub = "Микрофон на паузе", "Текстовый чат доступен"
        if self._status_circle is not None:
            self._status_circle.bgcolor = color
        if self._status_text is not None:
            self._status_text.value = text
        if self._status_sub is not None:
            self._status_sub.value = sub
        if self._input_field is not None:
            sensitive = bool(getattr(getattr(self.jarvis, "handler", None), "_pending_password", None))
            self._input_field.password = sensitive or state == "password"
            self._input_field.multiline = not self._input_field.password
            self._input_field.max_lines = 1 if self._input_field.password else 4
            self._input_field.autocorrect = not self._input_field.password
            self._input_field.enable_suggestions = not self._input_field.password
            self._input_field.hint_text = "Пароль (скрыт)" if self._input_field.password else "Напиши, что нужно сделать…"
            if self._input_hint is not None:
                self._input_hint.value = ("Пароль скрыт · Enter — подтвердить" if self._input_field.password
                                          else "Enter — отправить · Shift+Enter — новая строка")
        if getattr(self, "_brand_mark", None) is not None:
            self._brand_mark.border = ft.Border.all(1, P.brand if state == "idle" else color)
        self._apply_busy(self._command_busy)

    def _apply_mood_color(self, mood_state: str) -> None:
        labels = {"happy": "Настроение: хорошее", "excited": "Настроение: восторженное",
                  "annoyed": "Настроение: раздражённое", "bored": "Настроение: скучающее",
                  "tired": "Настроение: уставшее"}
        if self._mood_text is not None:
            self._mood_text.value = labels.get(mood_state, "")
            self._mood_text.visible = bool(self._mood_text.value)

    def _message_control(self, record) -> ft.Container:
        is_user = record["role"] == "user"
        label = ft.Text(record["text"], size=15, color=TEXT, selectable=True)
        if record is getattr(self, "_stream_record", None):
            self._stream_label = label
        async def copy(e):
            await self._copy_message(record)
        header = ft.Row([
            ft.Icon(ft.Icons.PERSON_OUTLINE if is_user else ft.Icons.GRAPHIC_EQ,
                    size=18, color=ACCENT),
            ft.Text("Вы" if is_user else "Феникс", size=14,
                    color=TEXT, weight=ft.FontWeight.W_600),
            ft.Text(record["time"], size=13, color=TEXT_DIM, expand=True),
            ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_size=17,
                          width=44, height=44, icon_color=TEXT_DIM,
                          tooltip="Копировать сообщение", on_click=copy),
        ], spacing=8)
        return ft.Container(
            content=ft.Column([header, label], spacing=4),
            bgcolor=BG_BUBBLE_USER if is_user else BG_CARD,
            border=ft.Border.all(1, P.border), border_radius=12,
            padding=ft.Padding(left=16, right=16, top=4, bottom=16),
            margin=ft.Margin(left=32 if is_user else 0, right=0 if is_user else 32),
        )

    def _render_history(self) -> None:
        self._history_list.controls = [self._message_control(m) for m in self._messages]
        if not self._messages:
            self._history_list.controls = [self._empty_chat]
        if getattr(self, "_stream_record", None) is not None:
            self._stream_bubble = self._history_list.controls[-1]

    def _apply_message(self, role: str, text: str) -> None:
        if not text:
            return
        record = {"role": role, "text": text, "time": datetime.now().strftime("%H:%M")}
        if not self._messages:
            self._history_list.controls.clear()
        self._messages.append(record)
        self._history_list.controls.append(self._message_control(record))

    def _apply_stream_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        if self._stream_bubble is None:
            self._stream_record = {"role": "assistant", "text": "", "time": datetime.now().strftime("%H:%M")}
            if not self._messages:
                self._history_list.controls.clear()
            self._messages.append(self._stream_record)
            self._stream_bubble = self._message_control(self._stream_record)
            self._history_list.controls.append(self._stream_bubble)
        self._stream_record["text"] += chunk
        self._stream_label.value = self._stream_record["text"]
        self._stream_text = self._stream_record["text"]

    def _apply_stream_end(self) -> None:
        self._stream_bubble = None
        self._stream_label = None
        self._stream_record = None
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
            self._rail.selected_index = 4
            self._content_area.content = self._tabs[4]
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

    def _on_window_event(self, e) -> None:
        """События окна: позиция (MOVED) и «закрыть в трей» (CLOSE).

        MOVED, а не MOVE: MOVED приходит один раз, когда перетаскивание
        закончилось, поэтому config.json не переписывается на каждый
        пиксель. Ошибки глушим — позиция окна не критична.
        """
        try:
            if e.type == ft.WindowEventType.CLOSE:
                self._on_window_close(e)
                return
            if e.type != ft.WindowEventType.MOVED:
                return
            if self._page is None:
                return
            left = self._page.window.left
            top = self._page.window.top
            if left is None or top is None:
                return
            self.config.update({"gui_x": int(left), "gui_y": int(top)})
            log.info("GUI: позиция окна сохранена (%s, %s)", left, top)
        except Exception:
            log.exception("Не удалось обработать событие окна")

    def _on_window_close(self, e) -> None:
        """Крестик в заголовке: с треем — свернуть туда, без трея — выйти.

        Сворачивание, а не выход: иконка в трее уже есть, и голосовой
        ассистент должен продолжать слушать (иначе зачем трей).
        """
        if not self.tray_active:
            log.info("GUI: трея нет — окно закрывается штатно (выход)")
            return
        try:
            page = getattr(e, "page", None) or self._page
            page.window.prevent_close = True
            page.window.visible = False
            page.update()
            log.info("GUI: окно свёрнуто в трей (Феникс продолжает слушать)")
        except Exception:
            log.exception("Не удалось свернуть окно в трей")


    # ---------------------------------------------------------------
    # Действия
    # ---------------------------------------------------------------

    def _select_tab(self, index: int) -> None:
        if index not in self._tabs:
            return
        if self._command_builder is not None:
            self._command_builder.capture()
        if index == 5:
            self._tabs[5] = self._build_commands_tab()
        self._rail.selected_index = index
        if index == 0 and getattr(self, "_model_label", None) is not None:
            self._model_label.value = self._model_caption()
        self._content_area.content = self._tabs[index]
        if self._page is not None:
            self._page.update()

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
        if getattr(self, "_model_label", None) is not None:
            self._model_label.value = self._model_caption()
        if self.jarvis is not None:
            self.jarvis.handler.mode = mode

    def _on_voice_change(self, e) -> None:
        self.config.set("tts_voice", e.control.value)

    def _get_voice_options(self) -> list:
        """Список голосов под текущий tts_backend."""
        try:
            from jarvis import voices as _voices
            backend = self.config.get("tts_backend", "auto")
            voice_dict = _voices._voices_for_backend(backend)
            if not voice_dict:
                return [
                    ft.dropdown.Option("ruslan"),
                    ft.dropdown.Option("dmitri"),
                    ft.dropdown.Option("irina"),
                    ft.dropdown.Option("denis"),
                ]
            return [
                ft.dropdown.Option(k, v.split("—")[0].strip() if "—" in v else k)
                for k, v in voice_dict.items()
            ]
        except Exception:
            log.exception("Не удалось получить список голосов")
            return [ft.dropdown.Option("ruslan")]

    def _on_refresh_voices(self, e) -> None:
        try:
            from jarvis import voices as _voices
            _voices.reset_cache()
            self._rebuild_ui_for_theme()
            if self._page is not None:
                self._page.update()
        except Exception:
            log.exception("Не удалось обновить голоса")

    def _show_status(self, text: str) -> None:
        """Показать уведомление в GUI (SnackBar). Безопасен из главного потока."""
        try:
            if self._page is None:
                return
            snack = ft.SnackBar(
                content=ft.Text(text, size=13, color="#eaf0f6"),
                bgcolor="#131c26",
                duration=10000,
            )
            self._page.overlay.append(snack)
            snack.open = True
            self._page.update()
        except Exception:
            log.exception("_show_status упал")

    def _on_memory_change(self, e) -> None:
        mem = e.control.value
        preset = {"short": (40, 10), "normal": (100, 20), "long": (200, 40)}.get(mem, (100, 20))
        self.config.update({
            "memory_max": preset[0],
            "llm_context_messages": preset[1],
        })

    def _on_llm_change(self, e) -> None:
        self.config.set("llm_model", e.control.value)
        if getattr(self, "_model_label", None) is not None:
            self._model_label.value = self._model_caption()

    def _on_ollama_change(self, e) -> None:
        # Пустое поле раньше сохранялось как есть и роняло старт:
        # urlopen('') даёт ValueError при инициализации Brain.
        value = (e.control.value or "").strip() or "http://127.0.0.1:11434"
        self.config.set("ollama_url", value)

    def _on_tts_change(self, e) -> None:
        backend = e.control.value
        self.config.set("tts_backend", backend)
        try:
            from jarvis import voices as _voices
            _voices.reset_cache()
        except Exception:
            pass
        log.info("GUI: tts_backend → %s, обновляю голоса", backend)

        # Показываем уведомление — что происходит
        if backend == "silero":
            self._show_status(
                "Silero: загрузка модели (~150 МБ + torch.hub). "
                "Первый раз — 1–3 минуты. В консоли видно прогресс."
            )
        elif backend == "auto":
            self._show_status(
                "auto: выбираю движок по приоритету silero → piper → winrt → sapi. "
                "Если silero не установлен — уйдёт на piper."
            )
        elif backend == "piper":
            self._show_status("Piper: голоса ruslan/dmitri/irina/denis, ~60 МБ.")
        elif backend == "winrt":
            self._show_status("WinRT: системные голоса Windows (Pavel, Irina).")
        elif backend == "sapi":
            self._show_status("SAPI: старые системные голоса Windows.")

        try:
            self._rebuild_ui_for_theme()
            if self._page is not None:
                self._page.update()
        except Exception:
            log.exception("Не удалось пересобрать вкладки")

    def _on_voice_quality_change(self, e) -> None:
        quality = e.control.value
        if quality not in ("medium", "high"):
            quality = "medium"

        # set() рассылает подписчикам — движок пересоздаст
        # make_config_listener (ветка tts_voice_quality). Прежний ручной
        # switch_backend(текущий backend) выходил по раннему return
        # и был no-op: настройка не применялась до перезапуска.
        self.config.set("tts_voice_quality", quality)

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
        current_index = self._rail.selected_index if self._rail else 0
        if self._command_builder is not None:
            self._command_builder.capture()
        if self._input_field is not None:
            # A password must not become a visible draft after a rebuild.
            self._draft = "" if self._input_field.password else (self._input_field.value or "")
        error = self._error_text.value if self._error_banner is not None and self._error_banner.visible else ""
        self._tabs = {
            0: self._build_main_tab(), 1: self._build_mic_tab(),
            2: self._build_audio_tab(), 3: self._build_persona_tab(),
            4: self._build_settings_tab(), 5: self._build_commands_tab(),
        }
        if error and self._error_text is not None:
            self._error_text.value = error
            self._error_banner.visible = True
        if self._content_area is not None:
            self._content_area.bgcolor = BG_DARK
            self._content_area.content = self._tabs.get(current_index, self._tabs[0])
        if self._rail is not None:
            self._rail.refresh_palette()

    def _on_send(self, e) -> None:
        text = (self._input_field.value or "").strip()
        if not text or self._command_busy:
            return
        if self._run_command(text) is not False:
            self._input_field.value = ""
            self._draft = ""
        if self._page is not None:
            self._page.update()

    def _on_mic_toggle(self, e) -> None:
        if self.jarvis is None:
            return
        self.jarvis.listening_enabled = not self.jarvis.listening_enabled
        self._mic_btn.icon = ft.Icons.MIC if self.jarvis.listening_enabled else ft.Icons.MIC_OFF
        self._mic_btn.icon_color = ACCENT if self.jarvis.listening_enabled else P.error
        if self._state in ("idle", "awaiting", "password"):
            self._apply_state("idle")
        try:
            self._page.update()
        except Exception:
            pass

    def _run_command(self, cmd: str) -> bool:
        """One GUI request at a time; same core lock as voice, UI only via queue."""
        if self.jarvis is None:
            self._queue.put(("command_error", "Ядро ещё не готово. Дождитесь запуска и повторите."))
            return False
        if not self._command_lock.acquire(blocking=False):
            return False
        self._command_busy = True
        self._apply_busy(True)
        self._dismiss_error()
        self._queue.put(("clear_error", None))

        def _run():
            try:
                self.set_state("thinking")
                self.jarvis.speaker.stop()
                if self.jarvis.speaker.wait_end(timeout=1.0) is False:
                    raise RuntimeError("Previous speech has not stopped")
                with self.jarvis.cmd_lock:
                    sensitive = bool(getattr(self.jarvis.handler, "_pending_password", None))
                    self.add_message("user", "[Ввод пароля скрыт]" if sensitive else cmd)
                    reply = self.jarvis.handler.handle(cmd)
                    if not reply.is_stream:
                        self.add_message("assistant", reply.text or "")
                    self.jarvis.say(reply)
                self.set_state("idle")
            except Exception as error:
                # Exception text may contain a password, prompt or server payload.
                log.error("Ошибка команды из GUI (%s); содержимое запроса не записывается",
                          type(error).__name__)
                self._queue.put(("command_error", "Не удалось завершить запрос. Проверьте модель, звук и доступность сервера. Повтор не выполняется автоматически."))
            finally:
                self._command_busy = False
                self._command_lock.release()
                self._queue.put(("busy", False))
        try:
            self._command_thread = threading.Thread(target=_run, daemon=True, name="gui-cmd")
            self._command_thread.start()
        except Exception:
            self._command_busy = False
            self._command_lock.release()
            self._queue.put(("command_error", "Не удалось запустить обработку. Сообщение осталось в поле ввода."))
            self._apply_busy(False)
            return False
        return True
