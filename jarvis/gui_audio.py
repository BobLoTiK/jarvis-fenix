"""Native sound settings. Diagnostics use the existing listener/Speaker, not new streams."""
import logging
import math
import threading
import time

import flet as ft

from jarvis.vad import DEFAULT_HANGOVER_MS

log = logging.getLogger(__name__)
TEST_PHRASE = "Привет! Это голос Феникса. Проверим, удобно ли меня слушать."


def _ui():
    from jarvis import gui
    return gui


def note(text):
    return ft.Text(text, size=13, color=_ui().P.text_dim)


def button(text, handler, icon=None, primary=False, disabled=False):
    p = _ui().P
    return ft.Button(content=ft.Row([
        *([ft.Icon(icon, size=18)] if icon else []), ft.Text(text, size=14),
    ], tight=True, spacing=8), on_click=handler, disabled=disabled,
        height=44, style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: p.brand if primary else p.selected,
                     ft.ControlState.DISABLED: p.selected},
            color={ft.ControlState.DEFAULT: p.bg_main if primary else p.text,
                   ft.ControlState.DISABLED: p.text_dim},
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=16)))


def card(title, subtitle, controls, icon):
    p = _ui().P
    return ft.Container(content=ft.Column([
        ft.Row([_ui()._brand_image(icon, 24), ft.Text(title, size=18,
            weight=ft.FontWeight.W_600, color=p.text)], spacing=12),
        note(subtitle), ft.Container(height=4), *controls,
    ], spacing=12), bgcolor=p.bg_card, border=ft.Border.all(1, p.border),
        border_radius=12, padding=20)


def screen(title, subtitle, controls):
    p = _ui().P
    return ft.Container(expand=True, padding=ft.Padding.all(28), content=ft.Column([
        ft.Text(title, size=28, weight=ft.FontWeight.BOLD, color=p.text),
        note(subtitle), ft.Container(height=4), *controls,
    ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True))


class SoundSettings:
    """Persistent diagnostic state survives palette/tab rebuilds; controls do not."""
    def __init__(self, gui):
        self.gui = gui
        self.lock = threading.Lock()
        self.busy = None
        self.thread = None
        self.results = {"mic": ("Проверка ещё не запускалась.", "text_dim"),
                        "voice": ("Нажмите «Послушать голос» — фраза не попадёт в чат.", "text_dim")}
        self.engine_label = None
        self.voice_dropdown = None
        self.device_values = {}
        self.voice_result = None
        self.mic_test_button = self.voice_test_button = None
        self.mic_dropdown = self.mic_refresh_button = None
        self.voice_controls = []

    def _result(self, kind, text, color="text_dim", done=False):
        # Workers send plain data only; Flet controls are updated by GUI queue.
        self.gui._queue.put(("sound_result", (kind, text, color, done)))

    def apply_result(self, kind, text, color="text_dim", done=False):
        self.results[kind] = (text, color)
        if done:
            self.busy = None
        self.sync()

    def sync(self):
        p = _ui().P
        if self.gui._mic_test_result is not None:
            text, color = self.results["mic"]
            self.gui._mic_test_result.value = text
            self.gui._mic_test_result.color = getattr(p, color)
        if self.voice_result is not None:
            text, color = self.results["voice"]
            self.voice_result.value = text
            self.voice_result.color = getattr(p, color)
        if self.engine_label is not None:
            engine = getattr(getattr(self.gui.jarvis, "speaker", None), "_engine_name", "none")
            self.engine_label.value = f"Загруженный движок: {engine}" if engine != "none" else "Движок: готовность ещё не подтверждена"
        if self.voice_test_button is not None:
            self.voice_test_button.content.controls[-1].value = "Проба голоса…" if self.busy == "voice" else "Послушать голос"
        if self.mic_test_button is not None:
            self.mic_test_button.content.controls[-1].value = "Измеряю уровень…" if self.busy == "mic" else "Проверить уровень · 3 сек"
        for control in [self.mic_test_button, self.voice_test_button,
                        self.mic_dropdown, self.mic_refresh_button, *self.voice_controls]:
            if control is not None:
                control.disabled = self.busy is not None

    def build_mic(self):
        g, p = self.gui, _ui().P
        devices = ["по умолчанию"]
        error = ""
        try:
            import sounddevice as sd
            for d in sd.query_devices():
                name = str(d["name"])
                if d["max_input_channels"] > 0 and name not in devices:
                    devices.append(name)  # Keep full device name for Listener.resolve_device.
        except Exception:
            error = "Не удалось получить список. Проверьте доступ к микрофону в Windows."
            log.warning("GUI: input device enumeration failed")
        current = g.config.get("input_device")
        if current is None or current == "":
            current = "по умолчанию"
        self.device_values = {str(current): current}
        missing = current not in devices
        if missing:
            devices.append(current)
        g._mic_dropdown = self.mic_dropdown = ft.Dropdown(label="Устройство ввода", value=str(current),
            options=[ft.dropdown.Option(str(d), str(d) + (" · сохранено, не найдено" if missing and d == current else "")) for d in devices],
            expand=True, border_color=p.border, focused_border_color=p.brand, on_select=g._on_mic_change)
        self.mic_refresh_button = button("Обновить", self.refresh_devices, ft.Icons.REFRESH)
        listener = getattr(g.jarvis, "listener", None)
        name = getattr(listener, "device_name", "Слушатель ещё не запущен")
        g._mic_device_text = ft.Text(f"Текущее устройство: {name}", size=13, color=p.text_dim)
        device = card("Откуда слушать", "Выбор применяется без перезапуска. Фактический вход показан ниже.", [
            ft.Row([g._mic_dropdown, self.mic_refresh_button], spacing=12),
            g._mic_device_text, *([note(error)] if error else []),
        ], "microphone")
        g._mic_level_bar = ft.ProgressBar(value=0, color=p.brand, bgcolor=p.selected, height=10, border_radius=5)
        g._mic_level_text = ft.Text("Уровень сигнала: —", size=24, weight=ft.FontWeight.W_600, color=p.text)
        g._mic_status_text = note("Статус: ожидание звука")
        g._mic_peak_text = note("Пик за сессию: —")
        g._mic_utt_text = note("Распознано фраз: —")
        # Loudness is not an emotion classifier. Do not invent emotion labels.
        g._mic_emotion_text = None
        g._mic_test_result = note("")
        self.mic_test_button = button("Проверить уровень · 3 сек", g._on_mic_test, ft.Icons.MIC, True)
        signal = card("Как меня слышно", "Живой уровень с текущего входа. Шкала условная, не измерение точности Vosk.", [
            ft.Row([g._mic_level_text, g._mic_status_text], wrap=True, spacing=16),
            g._mic_level_bar,
            ft.Row([g._mic_peak_text, g._mic_utt_text], wrap=True, spacing=24),
            ft.Row([self.mic_test_button], wrap=True), g._mic_test_result,
            note("Для проверки скажите фразу без обращения к Фениксу. Обычное распознавание остаётся включённым."),
        ], "audio")
        hint = card("Если вас не слышно", "Начните с простого — переустановка обычно не нужна.", [
            note("1. Выберите нужный вход и проверьте разрешение микрофона в Windows."),
            note("2. Посмотрите, двигается ли шкала, когда вы говорите."),
            note("3. Сравните одну команду голосом и в чате: это разделит ошибку распознавания и команды."),
        ], "settings")
        self.sync()
        self.update_level()
        return screen("Микрофон", "Ваш голос — начало действия. Настройте вход и проверьте сигнал.", [device, signal, hint])

    def refresh_devices(self, e=None):
        if self.busy:
            return
        g = self.gui
        g._tabs[1] = self.build_mic()
        if g._content_area is not None and g._rail is not None and g._rail.selected_index == 1:
            g._content_area.content = g._tabs[1]
        if g._page is not None:
            g._page.update()

    def update_level(self):
        g, p = self.gui, _ui().P
        listener = getattr(g.jarvis, "listener", None)
        if g._mic_level_bar is None:
            return
        g._mic_device_text.value = f"Текущее устройство: {getattr(listener, 'device_name', 'слушатель не запущен')}"
        if listener is None:
            g._mic_peak_text.value = "Пик за сессию: —"
            g._mic_utt_text.value = "Распознано фраз: —"
        paused = g.jarvis is not None and not getattr(g.jarvis, "listening_enabled", True)
        if listener is None or paused or getattr(listener, "muted", False):
            g._mic_level_bar.value = 0
            g._mic_level_text.value = "Уровень сигнала: —"
            g._mic_status_text.value = "Статус: пауза" if paused else ("Статус: вход временно приглушён" if listener else "Статус: слушатель не запущен")
            g._mic_status_text.color = p.text_dim
            return
        try:
            if time.monotonic() - getattr(listener, "level_updated_at", 0) > 1:
                g._mic_level_bar.value = 0
                g._mic_level_text.value = "Уровень сигнала: —"
                g._mic_status_text.value = "Статус: нет свежих данных входа"
                g._mic_status_text.color = p.warning
                return
            rms = max(0, float(listener.current_rms))
            if not math.isfinite(rms):
                rms = 0
            level = min(1, rms / 2000)
            g._mic_level_bar.value = level
            g._mic_level_text.value = f"Уровень сигнала: {int(level * 100)}%"
            g._mic_peak_text.value = f"Пик за сессию: {listener.peak}"
            g._mic_utt_text.value = f"Распознано фраз: {listener.utterances}"
            g._mic_device_text.value = f"Текущее устройство: {listener.device_name}"
            g._mic_status_text.value = "Статус: есть сигнал" if rms >= 100 else "Статус: тихо / ожидание звука"
            g._mic_status_text.color = p.success if rms >= 100 else p.text_dim
        except (AttributeError, TypeError, ValueError):
            g._mic_status_text.value = "Статус: нет данных уровня"

    def _launch(self, kind, worker):
        if not self.lock.acquire(blocking=False):
            return False
        # Busy stays set until the completion event is applied, preventing stale events.
        if self.busy is not None:
            self.lock.release()
            return False
        self.busy = kind
        self.results[kind] = ("Слушаю сигнал 3 секунды…" if kind == "mic" else "Подготавливаю голос…", "text_dim")
        self.sync()
        def run():
            try:
                worker()
            except Exception as error:
                log.warning("GUI sound diagnostic failed (%s)", type(error).__name__)
                self._result(kind, "Не удалось выполнить проверку. Проверьте устройство и журнал ошибок.", "error", True)
            finally:
                self.lock.release()
        try:
            self.thread = threading.Thread(target=run, daemon=True, name=f"gui-{kind}-test")
            self.thread.start()
        except Exception:
            self.lock.release()
            self.busy = None
            self.apply_result(kind, "Не удалось запустить проверку. Повторите попытку.", "error")
            return False
        return True

    def test_mic(self, e=None):
        g = self.gui
        listener = getattr(g.jarvis, "listener", None)
        if listener is None or not getattr(g.jarvis, "listening_enabled", True) or getattr(listener, "muted", False):
            self.apply_result("mic", "Включите прослушивание и дождитесь готовности микрофона.", "warning")
            return False
        device = g.config.get("input_device")
        def sample():
            peak_rms = 0
            started = time.monotonic()
            samples = set()
            for _ in range(60):
                if (getattr(g.jarvis, "listener", None) is not listener or
                    g.config.get("input_device") != device or not getattr(g.jarvis, "listening_enabled", True) or
                    getattr(listener, "muted", False)):
                    self._result("mic", "Вход изменился или был приостановлен. Повторите проверку.", "warning", True)
                    return
                rms = float(listener.current_rms)
                stamp = getattr(listener, "level_updated_at", 0)
                if math.isfinite(rms) and stamp > started:
                    samples.add(stamp)
                    peak_rms = max(peak_rms, rms)
                time.sleep(.05)
            if len(samples) < 2:
                self._result("mic", "Нет свежих данных входа. Дождитесь открытия микрофона и повторите проверку.", "warning", True)
                return
            if peak_rms >= 500:
                text, color = "Сигнал заметен. Если речь распознаётся неверно, проверьте команду отдельно.", "success"
            elif peak_rms >= 100:
                text, color = "Сигнал тихий. Приблизьте микрофон или увеличьте входную громкость Windows.", "warning"
            else:
                text, color = "За время проверки заметного сигнала нет. Проверьте вход и разрешения Windows.", "warning"
            self._result("mic", text, color, True)
        return self._launch("mic", sample)

    def test_voice(self, e=None):
        g = self.gui
        if g.jarvis is None or getattr(g.jarvis, "speaker", None) is None:
            self.apply_result("voice", "Звуковое ядро ещё не готово.", "warning")
            return False
        def speak():
            core = g.jarvis
            if not g._command_lock.acquire(blocking=False):
                self._result("voice", "Феникс занят командой. Повторите после ответа.", "warning", True)
                return
            if not core.cmd_lock.acquire(blocking=False):
                g._command_lock.release()
                self._result("voice", "Феникс занят командой. Повторите после ответа.", "warning", True)
                return
            try:
                if (g._command_busy or getattr(core.handler, "_pending_password", None) or
                    getattr(core.handler, "_pending_question", None)):
                    self._result("voice", "Сначала завершите текущую команду или уточнение.", "warning", True)
                    return
                if core.speaker.is_playing():
                    self._result("voice", "Дождитесь окончания речи или нажмите «Остановить речь».", "warning", True)
                    return
                from jarvis.reply import Reply
                g.set_state("speaking")
                # Jarvis.say owns _say_lock, listener mute/barge-in and Speaker.
                interrupted = core.say(Reply(text=TEST_PHRASE, allow_nonverbal=False))
                engine = getattr(core.speaker, "_engine_name", "none")
                if engine == "none":
                    self._result("voice", "Движок не готов. Проверьте выбранный TTS и его модели.", "warning", True)
                else:
                    text = "Проба прервана." if interrupted else "Проба завершена. Если звука нет, проверьте выход и громкость Windows."
                    self._result("voice", text, "text_dim", True)
            finally:
                core.cmd_lock.release()
                g._command_lock.release()
                g.set_state("idle")
        return self._launch("voice", speak)

    def build_audio(self):
        g, p = self.gui, _ui().P
        backend = ft.Dropdown(label="Движок речи", value=g.config.get("tts_backend", "auto"),
            options=[ft.dropdown.Option(k) for k in _ui().TTS_BACKENDS], expand=True,
            border_color=p.border, focused_border_color=p.brand, on_select=g._on_tts_change)
        current = g.config.get("tts_voice", "ruslan")
        options = g._get_voice_options()
        if current not in [o.key for o in options]:
            options.append(ft.dropdown.Option(current, f"{current} · сохранён"))
        voice = self.voice_dropdown = ft.Dropdown(label="Голос", value=current, options=options, expand=True,
            border_color=p.border, focused_border_color=p.brand, on_select=self.change_voice)
        refresh = button("Обновить", g._on_refresh_voices, ft.Icons.REFRESH)
        self.rate_label = note(f"Скорость речи · {float(g.config.get('voice_rate', 1.15)):.2f}×")
        rate = ft.Slider(min=.5, max=2, divisions=30, value=float(g.config.get("voice_rate", 1.15)),
            active_color=p.brand, label="{value}", on_change=self.show_rate, on_change_end=self.change_rate)
        self.voice_result = note("")
        self.voice_test_button = button("Послушать голос", self.test_voice, ft.Icons.PLAY_ARROW, True)
        stop = button("Остановить речь", g._on_stop_speech, ft.Icons.STOP)
        self.voice_controls = [backend, voice, refresh, rate]
        engine = getattr(getattr(g.jarvis, "speaker", None), "_engine_name", "none")
        self.engine_label = note(f"Загруженный движок: {engine}" if engine != "none" else "Движок: готовность ещё не подтверждена")
        voice_card = card("Голос Феникса", "Выберите тембр и темп, затем прослушайте короткую фразу.", [
            ft.Row([backend, voice], spacing=12),
            ft.Row([refresh, self.engine_label], wrap=True),
            self.rate_label, rate, ft.Row([self.voice_test_button, stop], wrap=True, spacing=12),
            self.voice_result,
            note("Голоса в списке могут требовать модели. Проба использует обычный звуковой тракт; первый запуск может занять время."),
        ], "audio")
        reactions = card("Живое звучание", "Необязательные реакции и анализ интонации — настройте под себя.", [
            ft.Checkbox(label="Звуковые реакции (смех, вздохи, хм, зевок)", value=bool(g.config.get("nonverbal_enabled", False)), on_change=g._on_nonverbal_enabled),
            note("Только в помеченном диалоге. Silero, Piper и WinRT; SAPI — без реакций. На голосовую пробу не добавляются."),
            ft.Checkbox(label="Анализировать интонацию голоса (Prosody)", value=bool(g.config.get("prosody_enabled", True)), on_change=g._on_prosody_enabled),
            ft.Dropdown(label="Приоритет оценки интонации", value=g.config.get("prosody_priority", "prosody"), options=[
                ft.dropdown.Option("prosody", "Голос важнее текста"), ft.dropdown.Option("text", "Текст важнее голоса"),
                ft.dropdown.Option("both", "Оба: голос первым")], on_select=g._on_prosody_priority, border_color=p.border),
            note("Это эвристика RMS/pitch/ZCR, а не достоверное определение эмоций человека."),
        ], "persona")
        g._vad_threshold_label = note(f"Порог VAD: {g.config.get('vad_threshold', .5):.2f}")
        g._vad_threshold_slider = ft.Slider(min=.1, max=.9, divisions=16, value=float(g.config.get("vad_threshold", .5)), active_color=p.brand,
            on_change=g._on_vad_threshold_change, on_change_end=g._on_vad_threshold_end)
        g._vad_hangover_label = note(f"Хвост тишины для Vosk: {int(g.config.get('vad_hangover_ms', DEFAULT_HANGOVER_MS))} мс")
        g._vad_hangover_slider = ft.Slider(min=0, max=3000, divisions=12, value=float(g.config.get("vad_hangover_ms", DEFAULT_HANGOVER_MS)),
            active_color=p.brand, on_change=g._on_vad_hangover_change, on_change_end=g._on_vad_hangover_end)
        advanced = ft.ExpansionTile(title=ft.Text("Распознавание и фильтр тишины", color=p.text, size=16),
            subtitle=note("VAD, паузы Vosk, обращение и перебивание"), controls=[ft.Container(padding=16, content=ft.Column([
                ft.Checkbox(label="VAD (Silero) — фильтр тишины", value=bool(g.config.get("vad_enabled", True)), on_change=g._on_vad_enabled),
                ft.Checkbox(label="Адаптивный порог под микрофон", value=bool(g.config.get("vad_adaptive", True)), on_change=g._on_vad_adaptive),
                ft.Checkbox(label="Скачивать модель VAD, если её нет", value=bool(g.config.get("vad_auto_download", True)), on_change=g._on_vad_auto_download),
                note("Без модели фильтр VAD недоступен. Скачивание требует сети; Vosk остаётся основным распознавателем."),
                g._vad_threshold_label, g._vad_threshold_slider,
                note("Меньший порог пропускает больше кандидатов на речь, но также больше шума."),
                g._vad_hangover_label, g._vad_hangover_slider,
                note("Короткий хвост может ускорить ответ, но Vosk должен успеть завершить фразу."),
                ft.Checkbox(label="Прерывать Феникса голосом (barge-in)", value=bool(g.config.get("barge_enabled", True)), on_change=g._on_barge_enabled),
                ft.Checkbox(label="Ждать обращения «Феникс»", value=bool(g.config.get("wake_word_required", True)), on_change=g._on_wake_required),
                note("Без ожидания обращения любая распознанная речь может стать командой. Изменения применяются сразу."),
            ], spacing=12))])
        self.sync()
        return screen("Голос и звук", "Тембр, темп и поведение речи — в одном месте.", [voice_card, reactions, advanced])

    def change_voice(self, e):
        self.gui._on_voice_change(e)

    def show_rate(self, e):
        self.rate_label.value = f"Скорость речи · {float(e.control.value):.2f}×"

    def change_rate(self, e):
        self.show_rate(e)
        self.gui._on_rate_change(e)
        self.apply_result("voice", "Темп изменён. Прослушайте пробу ещё раз.")
