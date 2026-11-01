"""Вкладка «Движки»: что скачано, что включено и установка по кнопке.

Правила те же, что у остальных экранов: UI меняется только в GUI-потоке,
установка идёт в отдельном потоке и общается с экраном через очередь FenixGUI.
Никакой автозагрузки при построении вкладки: статус читается с диска,
Ollama проверяется отдельным фоновым запросом, скачивание — только кнопкой.
"""

from __future__ import annotations

import logging
import threading

import flet as ft

from jarvis import engines
from jarvis.gui_preferences import _palette, button, card, divider, text

log = logging.getLogger("jarvis.gui_engines")

GROUP_TITLES = {
    engines.GROUP_STT: ("Распознавание речи", "Звук превращается в текст."),
    engines.GROUP_TTS: ("Синтез речи", "Ответ озвучивается."),
    engines.GROUP_LLM: ("Языковые модели", "Модель отвечает и разбирает команды."),
}


class EnginesScreen(ft.Container):
    def __init__(self, gui):
        super().__init__(expand=True)
        self.gui = gui
        self.items = []
        self.progress = {}     # key -> (доля | None, сообщение)
        self.messages = {}     # key -> (текст, ошибка: bool)
        self.bars = {}         # key -> ft.ProgressBar
        self.texts = {}        # key -> ft.Text
        self._busy = set()
        self._install_lock = threading.Lock()
        self._ollama_thread = None
        self.ollama_status = None
        self.reload()

    # --- построение ---------------------------------------------------
    def _config(self):
        return self.gui.config

    def _update(self, *controls):
        page = getattr(self.gui, "_page", None)
        if page is None:
            return
        try:
            page.update(*(controls or (self,)))
        except Exception:
            log.debug("Движки: update пропущен", exc_info=True)

    def reload(self):
        """Пересобирает экран по текущему состоянию диска и конфига."""
        names = None
        if isinstance(self.ollama_status, dict) and self.ollama_status.get("local"):
            names = self.ollama_status.get("names")
        self.items = engines.catalog(self._config(), ollama_names=names)
        self.bars, self.texts = {}, {}
        p = _palette()
        groups = []
        for group in (engines.GROUP_STT, engines.GROUP_TTS, engines.GROUP_LLM):
            rows = [self._row(item) for item in self.items if item.group == group]
            if not rows:
                continue
            title, subtitle = GROUP_TITLES[group]
            groups.append(card(title, subtitle, rows))
        self.content = ft.Container(bgcolor=p.bg, padding=28, content=ft.Column([
            ft.Text("УСТАНОВЛЕННОЕ И ВКЛЮЧЁННОЕ", size=12, color=p.accent),
            text("Движки", 32, weight=ft.FontWeight.W_600),
            text("Что уже на диске, что включено сейчас и что можно скачать здесь же.", 16,
                 muted=True),
            ft.Row([button("Обновить список", lambda e: self.reload()),
                    button("Проверить Ollama", lambda e: self.check_ollama_async())],
                   wrap=True, spacing=8, run_spacing=8),
            ft.Container(height=4), *groups, divider(),
            text("Скачивание запускается только кнопкой и идёт в фоне — окно не "
                 "замирает. Источники: alphacephei.com (Vosk), Hugging Face "
                 "(Whisper, Piper), torch.hub (Silero), сервер Ollama.", 13, muted=True),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True))

    def _row(self, item):
        p = _palette()
        installed = item.installed
        chip_text = "АКТИВНО" if item.active else ("СКАЧАНО" if installed else "НЕТ")
        chip_color = p.button_text if item.active else p.dim
        # Пустой фон у неактивного чипа сливался с карточкой: у "НЕТ" был только
        # текст. Второй фон + рамка делают состояние читаемым без цвета статуса.
        chip = ft.Container(
            ft.Text(chip_text, size=11, color=chip_color),
            bgcolor=p.accent if item.active else p.bg,
            border=None if item.active else ft.Border.all(1, p.border),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4))
        header = ft.Row([text(item.title, 16, weight=ft.FontWeight.W_600),
                         chip], spacing=10)
        detail = text(item.detail or "", 13, muted=True)
        message_text, is_error = self.messages.get(item.key, ("", False))
        message = text(message_text, 13, muted=True)
        if is_error:
            message.color = p.error
        self.texts[item.key] = message
        fraction, _ = self.progress.get(item.key, (None, ""))
        bar = ft.ProgressBar(value=fraction, visible=item.key in self._busy,
                             color=p.accent, bgcolor=p.field, bar_height=4)
        self.bars[item.key] = bar
        controls = [header, text(item.description, 13), detail,
                    bar, message]
        busy_elsewhere = bool(self._busy - {item.key})
        if item.key in self._busy:
            controls.append(text("Устанавливаю…", 13, muted=True))
        elif item.installable and not installed:
            controls.append(button(item.install_label or "Установить",
                                   lambda e, key=item.key: self.start_install(key),
                                   primary=True, disabled=busy_elsewhere))
        elif not item.installable:
            hint = item.hint or ("Системный движок: скачивать нечего." if not item.size_hint else item.size_hint)
            controls.append(text(hint, 12, muted=True))
        return ft.Column(controls, spacing=6)

    # --- действия -----------------------------------------------------
    def start_install(self, key):
        if key in self._busy or not self._install_lock.acquire(blocking=False):
            self.messages[key] = ("Дождитесь окончания текущей установки.", True)
            self.reload()
            self._update()
            return
        self._busy.add(key)
        self.progress[key] = (None, "Начинаю…")
        self.reload()
        self._update()
        config = self._config()

        def progress(fraction, message):
            self.gui._queue.put(("engines_progress", (key, fraction, message)))

        def work():
            try:
                ok, message = engines.install(key, progress, config)
            except Exception as error:  # поток не должен умирать молча
                log.exception("Движки: установка %s упала", key)
                ok, message = False, f"Установка не удалась: {type(error).__name__}"
            self.gui._queue.put(("engines_done", (key, ok, message)))

        threading.Thread(target=work, daemon=True, name=f"engine-install-{key}").start()

    def on_progress(self, value):
        key, fraction, message = value
        self.progress[key] = (fraction, message)
        bar = self.bars.get(key)
        if bar is not None:
            bar.value = fraction
            bar.visible = True
        control = self.texts.get(key)
        if control is not None:
            control.value = message
        self._update()

    def on_done(self, value):
        key, ok, message = value
        self._busy.discard(key)
        self.progress.pop(key, None)
        self.messages[key] = (message, not ok)
        if self._install_lock.locked():
            try:
                self._install_lock.release()
            except RuntimeError:
                log.debug("Движки: замок установки уже свободен")
        self.reload()
        self._update()

    def check_ollama_async(self):
        """Ollama опрашивается в фоне: при построении экрана сети не ждём."""
        if self._ollama_thread is not None and self._ollama_thread.is_alive():
            return
        config = self._config()
        url = "http://127.0.0.1:11434"
        try:
            url = str(config.get("ollama_url") or url)
        except Exception:
            log.debug("Движки: адрес Ollama из конфига не прочитан", exc_info=True)

        def work():
            names = engines.ollama_inventory(url)
            self.gui._queue.put(("engines_status", (url, names,
                                                    bool(engines.local_ollama_url(url)))))

        self._ollama_thread = threading.Thread(target=work, daemon=True,
                                               name="engines-ollama-status")
        self._ollama_thread.start()

    def on_status(self, value):
        url, names, local = value
        self.ollama_status = {"url": url, "names": names, "local": local}
        self.reload()
        self._update()

    def is_busy(self) -> bool:
        """Идёт установка: экран нельзя пересобирать, иначе прогресс потеряется."""
        return bool(self._busy)

    def dispose(self):
        pass
