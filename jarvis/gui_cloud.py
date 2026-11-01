"""Вкладка «Облако»: провайдер, ключ, приватность и проверка ключа.

Отдельная вкладка, потому что здесь больше текста, чем полей: что именно
уходит провайдеру, где лежит ключ, чем проверка отличается от «работает».
Настройки те же, что и раньше (cloud_*), пишутся одним сохранением через
config.update(expected_values=...), а ключ — в DPAPI, не в config.json.
"""

from __future__ import annotations

import logging
import threading

import flet as ft

from jarvis import cloud_llm
from jarvis.gui_preferences import (
    _palette,
    _secrets,
    button,
    card,
    cloud_providers,
    consent_summary,
    divider,
    input_border,
    probe_cloud,
    record_cloud_consent,
    text,
    validated_cloud_settings,
)

log = logging.getLogger("jarvis.gui_cloud")

CLOUD_KEYS = ("cloud_enabled", "cloud_provider", "cloud_base_url", "cloud_model",
              "cloud_timeout", "cloud_max_tokens", "cloud_send_profile")
TIMEOUTS = {"30": 30.0, "60": 60.0, "120": 120.0, "180": 180.0}
SENT_ALWAYS = ("Уходит провайдеру: текст реплики, недавние реплики этого диалога "
               "и системная инструкция. Через HTTPS — открытый http разрешён "
               "только для localhost.")
SENT_PROFILE = ("При включённом переключателе ниже дополнительно уходят персона, "
                "настроение и найденные факты памяти: это личные данные.")


def _timeout_key(value):
    for key, seconds in TIMEOUTS.items():
        if abs(float(value or 0) - seconds) < 0.01:
            return key
    return "60"


class CloudScreen(ft.Container):
    def __init__(self, gui):
        super().__init__(expand=True)
        self.gui = gui
        self.draft = {}
        self.baseline = {}
        self.fields = {}
        self.key_field = None
        self.key_status = None
        self.probe_status = "Ключ ещё не проверялся."
        self.probe_label = None
        self.probe_button = None
        self.notice = ""
        self.notice_control = None
        self.error = False
        self.probe_busy = False
        self.probe_lock = threading.Lock()
        self.probe_generation = 0
        self.load()
        self.content = self.build()

    # --- данные -------------------------------------------------------
    def load(self):
        self.draft = {key: self.gui.config.get(key) for key in CLOUD_KEYS}
        self.draft["cloud_timeout"] = float(self.draft.get("cloud_timeout") or 60.0)
        self.draft["cloud_max_tokens"] = int(self.draft.get("cloud_max_tokens") or 600)
        if self.draft.get("cloud_provider") not in cloud_llm.PROVIDERS:
            self.draft["cloud_provider"] = "openai"
        self.baseline = dict(self.draft)

    def _update(self, *controls):
        page = getattr(self.gui, "_page", None)
        if page is None:
            return
        try:
            page.update(*controls)
        except Exception:
            log.debug("Облако: update пропущен", exc_info=True)

    # --- построение ---------------------------------------------------
    def build(self):
        self.fields = {}
        p = _palette()
        mode_text = text(self._mode_summary(), 14, muted=True)
        self.mode_label = mode_text
        intro = card("Кто отвечает", "Облако включается переключателем и работает только с сохранённым ключом.", [
            self._toggle("cloud_enabled", "Отвечать через облако",
                         "Выключено — отвечает локальная Ollama. Включено — текст реплики уходит провайдеру."),
            mode_text, divider(),
            self._select("cloud_provider", "Провайдер", cloud_providers()),
            self._field("cloud_base_url", "Адрес API", max_length=2048),
            self._field("cloud_model", "Модель", max_length=256),
            ft.Row([self._timeout_select(), self._field("cloud_max_tokens", "Лимит токенов ответа",
                                                        max_length=5)], spacing=12),
        ])
        key_card = card("Ключ доступа", "Ключ API не попадает в config.json и в черновик.", [
            self._key_field(p), self._key_status_text(),
            ft.Row([button("Сохранить ключ", self.save_key, primary=True),
                    button("Удалить ключ", self.delete_key)], wrap=True, spacing=8,
                   run_spacing=8),
            self._probe_label_text(), self._probe_button(),
            divider(),
            text("Ключ шифруется Windows DPAPI и лежит в %APPDATA%\\Phoenix\\secrets. "
                 "Проверка ключа запрашивает только список моделей: она не отправляет "
                 "ваш текст и не доказывает качество ответа.", 13, muted=True),
        ])
        privacy = card("Приватность", "Что именно уходит наружу.", [
            text(SENT_ALWAYS, 13, muted=True),
            self._toggle("cloud_send_profile", "Отправлять персону и память",
                         "По умолчанию наружу идёт только реплика. Включение добавит "
                         "характер, настроение и факты из памяти."),
            text(SENT_PROFILE, 13, muted=True),
            self._consent_text(),
        ])
        diagnostics = card("Проверка", "Факты вместо обещаний.", [
            text(self._diagnostics(), 13, muted=True),
            ft.Row([button("Открыть «Движки»", self.open_engines),
                    button("Перечитать настройки", lambda e: self.reload())],
                   wrap=True, spacing=8, run_spacing=8),
        ])
        self.notice_control = text(self.notice or "Изменения применятся после сохранения.", 13,
                                   muted=True)
        if self.error:
            self.notice_control.color = p.error
        footer = ft.Row([button("Сохранить", self.save, primary=True),
                         button("Отменить изменения", self.cancel),
                         button("Проверить ключ", self.start_probe)], wrap=True,
                        spacing=8, run_spacing=8)
        return ft.Container(bgcolor=p.bg, padding=28, content=ft.Column([
            ft.Text("ОБЛАЧНАЯ МОДЕЛЬ", size=12, color=p.accent),
            text("Облако", 32, weight=ft.FontWeight.W_600),
            text("Ответы через провайдера API. Локальная Ollama остаётся запасным "
                 "вариантом и продолжает работать для команд.", 16, muted=True),
            ft.Container(height=4), intro, key_card, privacy, diagnostics,
            divider(), footer, self.notice_control,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True))

    # --- мелкие контролы ----------------------------------------------
    def _toggle(self, key, title, description):
        p = _palette()
        control = ft.Switch(value=bool(self.draft.get(key)), active_color=p.accent,
                            on_change=lambda e, k=key: self.change(k, bool(e.control.value)))
        self.fields[key] = control
        return ft.Row([ft.Column([text(title, 15), text(description, 13, muted=True)],
                                 spacing=2, expand=True), control],
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _field(self, key, label, max_length=None):
        p = _palette()
        control = ft.TextField(label=label, value=str(self.draft.get(key) or ""),
                               on_change=lambda e, k=key: self.change(k, e.control.value),
                               border=input_border(), color=p.text, text_size=15,
                               label_style=ft.TextStyle(color=p.dim), bgcolor=p.field,
                               max_length=max_length, counter="")
        self.fields[key] = control
        return control

    def _select(self, key, label, options):
        p = _palette()
        current = self.draft.get(key)
        if current not in options:
            options = {**options, str(current): str(current)}
        control = ft.Dropdown(label=label, value=current,
                              options=[ft.dropdown.Option(k, v) for k, v in options.items()],
                              on_select=lambda e, k=key: self.change(k, e.control.value),
                              border=input_border(), color=p.text, bgcolor=p.field,
                              text_size=15, label_style=ft.TextStyle(color=p.dim))
        self.fields[key] = control
        return control

    def _timeout_select(self):
        p = _palette()
        labels = {"30": "30 секунд", "60": "60 секунд", "120": "2 минуты",
                  "180": "3 минуты"}
        current = _timeout_key(self.draft.get("cloud_timeout"))
        control = ft.Dropdown(
            label="Таймаут ответа", value=current,
            options=[ft.dropdown.Option(key, labels[key]) for key in TIMEOUTS],
            on_select=lambda e: self.change("cloud_timeout", TIMEOUTS[e.control.value]),
            border=input_border(), color=p.text, bgcolor=p.field, text_size=15,
            label_style=ft.TextStyle(color=p.dim))
        self.fields["cloud_timeout"] = control
        return control

    def _key_field(self, p):
        self.key_field = ft.TextField(
            label="Ключ API", hint_text="sk-…", password=True, can_reveal_password=True,
            max_length=4096, counter="", text_size=15, border=input_border(),
            color=p.text, label_style=ft.TextStyle(color=p.dim), bgcolor=p.field)
        return self.key_field

    def _key_status_text(self):
        try:
            from jarvis import secrets_store

            present = secrets_store.has_secret(secrets_store.CLOUD_LLM_KEY)
            label = (secrets_store.secret_fingerprint(secrets_store.CLOUD_LLM_KEY)
                     or "") if present else ""
        except Exception:
            present, label = False, ""
        value = (f"Ключ сохранён (отпечаток {label})." if present
                 else "Ключ не сохранён.")
        self.key_status = text(value, 13, muted=True)
        return self.key_status

    def _probe_label_text(self):
        self.probe_label = text(self.probe_status, 13, muted=True)
        return self.probe_label

    def _probe_button(self):
        self.probe_button = button("Проверяю…" if self.probe_busy else "Проверить ключ",
                                   self.start_probe, disabled=self.probe_busy)
        return self.probe_button

    def _consent_text(self):
        self.consent_label = text(consent_summary(), 13, muted=True)
        return self.consent_label

    def _mode_summary(self):
        config = self.gui.config
        local = str(config.get("llm_model") or "модель не выбрана")
        try:
            from jarvis import secrets_store

            has_key = secrets_store.has_secret(secrets_store.CLOUD_LLM_KEY)
        except Exception:
            has_key = False
        if self.draft.get("cloud_enabled") and has_key:
            provider = cloud_llm.provider_label(str(self.draft.get("cloud_provider")))
            return f"Сейчас отвечает облако: {provider}, {self.draft.get('cloud_model') or 'модель не выбрана'}."
        if self.draft.get("cloud_enabled"):
            return "Облако включено, но ключа нет: Феникс ответит локальной Ollama."
        return f"Сейчас отвечает локальная Ollama: {local}."

    def _diagnostics(self):
        lines = [self._mode_summary()]
        pending = [key for key in CLOUD_KEYS if self._normalized(key) != self.baseline.get(key)]
        lines.append("Несохранённых изменений нет." if not pending
                     else "Не сохранено: " + ", ".join(sorted(pending)) + ".")
        try:
            from jarvis import secrets_store

            if secrets_store.has_secret(secrets_store.CLOUD_LLM_KEY):
                lines.append("Отпечаток сохранённого ключа: "
                             + (secrets_store.secret_fingerprint(secrets_store.CLOUD_LLM_KEY) or "?")
                             + ". Весь ключ не показывается и не логируется.")
        except Exception:
            lines.append("Хранилище ключа недоступно в этом окружении.")
        lines.append("Проверка ключа = один запрос списка моделей. Генерация не проверялась.")
        return " ".join(lines)

    # --- изменения черновика -----------------------------------------
    def _normalized(self, key):
        value = self.draft.get(key)
        if key == "cloud_timeout":
            return float(value or 60.0)
        if key == "cloud_max_tokens":
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        return value

    def change(self, key, value):
        previous = self.draft.get(key)
        self.draft[key] = value
        self.notice, self.error = "Есть несохранённые изменения.", False
        if key == "cloud_provider" and previous != value:
            self._apply_preset(previous, value)
        if key in ("cloud_provider", "cloud_base_url", "cloud_model"):
            # Старый результат относился к другим параметрам: он больше не факт.
            self.probe_generation += 1
            self.probe_status = "Параметры изменены. Проверьте ключ заново."
        self._sync_presentation()

    def _apply_preset(self, previous, provider):
        """Адрес и модель нового провайдера — только если человек их не менял."""
        old = cloud_llm.PROVIDERS.get(str(previous), {}) or {}
        new = cloud_llm.PROVIDERS.get(str(provider), {}) or {}
        for key, field in (("cloud_base_url", "base_url"), ("cloud_model", "model")):
            current = str(self.draft.get(key) or "")
            old_preset = str(old.get(field) or "")
            new_preset = str(new.get(field) or "")
            if not new_preset or (current and current != old_preset):
                continue
            self.draft[key] = new_preset
            control = self.fields.get(key)
            if control is not None:
                control.value = new_preset

    def _sync_presentation(self):
        """Обновляет подписи, но не поле ввода: оно набирается пользователем."""
        targets = [self.notice_control]
        if self.notice_control is not None:
            self.notice_control.value = self.notice
            self.notice_control.color = _palette().error if self.error else _palette().dim
        if getattr(self, "mode_label", None) is not None:
            self.mode_label.value = self._mode_summary()
            targets.append(self.mode_label)
        if self.probe_label is not None:
            self.probe_label.value = self.probe_status
            targets.append(self.probe_label)
        self._update(*[c for c in targets if c is not None])

    # --- сохранение ---------------------------------------------------
    def save(self, e=None):
        self.error = True
        try:
            provider = str(self.draft.get("cloud_provider") or "")
            base_url, model = validated_cloud_settings(
                provider, self.draft.get("cloud_base_url"), self.draft.get("cloud_model"))
            if type(self.draft.get("cloud_enabled")) is not bool or \
                    type(self.draft.get("cloud_send_profile")) is not bool:
                raise ValueError("Проверьте переключатели облака.")
            try:
                timeout = float(self.draft.get("cloud_timeout") or 60.0)
                tokens = int(self.draft.get("cloud_max_tokens"))
            except (TypeError, ValueError):
                raise ValueError("Таймаут и лимит токенов должны быть числами.") from None
            if not 5.0 <= timeout <= 600.0:
                raise ValueError("Таймаут облака: от 5 до 600 секунд.")
            if not 50 <= tokens <= 8192:
                raise ValueError("Лимит токенов ответа: от 50 до 8192.")
            normalized = {
                "cloud_enabled": self.draft["cloud_enabled"],
                "cloud_provider": provider,
                "cloud_base_url": base_url,
                "cloud_model": model,
                "cloud_timeout": timeout,
                "cloud_max_tokens": tokens,
                "cloud_send_profile": self.draft["cloud_send_profile"],
            }
            changes = {key: value for key, value in normalized.items()
                       if value != self.baseline.get(key)}
            if any(self.gui.config.get(key) != self.baseline.get(key) for key in changes):
                raise ValueError("Эти настройки изменены другим действием: сохранение "
                                 "отменено, перечитайте значения.")
            if not self.gui.config.update(
                    changes, expected_values={k: self.baseline.get(k) for k in changes}):
                raise ValueError("Не удалось записать настройки: прежние значения "
                                 "не изменены.")
            self.load()
            self.error = False
            self.notice = "Изменений нет." if not changes else "Настройки облака сохранены."
            if normalized["cloud_enabled"] and not self._key_saved():
                self.notice += (" Ключ не сохранён: без него облако не заработает, "
                                "ответы останутся локальными.")
            if "cloud_send_profile" in changes:
                if record_cloud_consent(normalized["cloud_send_profile"]):
                    self.notice += " След согласия записан в профиль."
                else:
                    self.notice += " След согласия записать не удалось: профиль недоступен."
            if "cloud_max_tokens" in changes or "cloud_timeout" in changes:
                self.notice += " Новые лимиты применятся к следующему запросу."
            if getattr(self.gui, "_model_label", None) is not None:
                self.gui._model_label.value = self.gui._model_caption()
        except ValueError as error:
            self.notice, self.error = str(error), True
        self.content = self.build()
        self._update()

    def cancel(self, e=None):
        self.load()
        self.probe_generation += 1
        self.probe_status = "Черновик отменён. Ключ не проверялся."
        self.notice, self.error = "Черновик отменён.", False
        self.content = self.build()
        self._update()

    def reload(self):
        self.load()
        self.content = self.build()
        self._update()

    def open_engines(self, e=None):
        from jarvis.gui import ENGINES_TAB

        if self.gui._page is not None:
            self.gui._select_tab(ENGINES_TAB)

    # --- ключ ---------------------------------------------------------
    def _key_saved(self):
        try:
            from jarvis import secrets_store

            return secrets_store.has_secret(secrets_store.CLOUD_LLM_KEY)
        except Exception:
            return False

    def _key_changed(self, message, error=False, clear=False):
        self.notice, self.error = message, error
        if clear and self.key_field is not None:
            self.key_field.value = ""
        if self.key_status is not None:
            self.key_status.value = ("Ключ сохранён (отпечаток " + _fingerprint() + ")."
                                     if self._key_saved() else "Ключ не сохранён.")
        if self.notice_control is not None:
            self.notice_control.value = message
            self.notice_control.color = _palette().error if error else _palette().dim
        self._update(*[c for c in (self.key_field, self.key_status, self.notice_control,
                                   self.probe_label) if c is not None])

    def save_key(self, e=None):
        value = (self.key_field.value or "").strip() if self.key_field is not None else ""
        if not value:
            self._key_changed("Введите ключ: пустое поле сохранять нечего.", True)
            return False
        try:
            store = _secrets()
            store.save_secret(store.CLOUD_LLM_KEY, value)
        except (ImportError, ValueError, RuntimeError, OSError) as error:
            log.warning("Ключ облака не сохранён: %s", type(error).__name__)
            self._key_changed("Ключ не сохранён: " + str(error), True)
            return False
        self.probe_generation += 1
        self.probe_status = "Ключ сохранён. Проверьте его кнопкой «Проверить ключ»."
        self._key_changed("Ключ сохранён зашифрованным.", False, clear=True)
        return True

    def delete_key(self, e=None):
        try:
            store = _secrets()
            removed = store.delete_secret(store.CLOUD_LLM_KEY)
        except (ImportError, ValueError, RuntimeError, OSError) as error:
            log.warning("Ключ облака не удалён: %s", type(error).__name__)
            self._key_changed("Ключ не удалён: " + str(error), True)
            return False
        if not removed:
            self._key_changed("Ключ удалить не удалось: файл занят или нет прав.", True)
            return False
        self.probe_generation += 1
        self.probe_status = "Ключ удалён. Проверять нечего."
        self._key_changed("Ключ удалён из хранилища Windows.", False, clear=True)
        return True

    def start_probe(self, e=None):
        if self.probe_busy:
            return False
        try:
            provider = str(self.draft.get("cloud_provider") or "")
            base_url, model = validated_cloud_settings(
                provider, self.draft.get("cloud_base_url"), self.draft.get("cloud_model"))
        except ValueError as error:
            self.probe_status = str(error)
            self._key_changed(str(error), True)
            return False
        try:
            store = _secrets()
            key = store.load_secret(store.CLOUD_LLM_KEY)
        except (ImportError, ValueError, RuntimeError, OSError):
            key = None
        if not key:
            self.probe_status = "Ключ не сохранён. Проверять нечего."
            self._key_changed("Сначала сохраните ключ: без него запрос отправлять нечего.", True)
            return False
        if not self.probe_lock.acquire(blocking=False):
            return False
        self.probe_generation += 1
        token = self.probe_generation
        self.probe_busy = True
        self.probe_status = "Проверяю ключ: запрашиваю список моделей…"
        self._sync_probe()
        self._update()
        token = self.probe_generation

        def run():
            try:
                report, error = probe_cloud(provider, base_url, model, key), None
            except cloud_llm.CloudAuthError:
                report, error = None, "Ключ не принят (401/403). Проверьте ключ и провайдера."
            except cloud_llm.CloudLLMError as error_object:
                report, error = None, str(error_object)[:300]
            except ValueError as error_object:
                report, error = None, str(error_object)
            except Exception:
                report, error = None, ("Проверка не удалась. Проверьте адрес, "
                                       "интернет и доступность провайдера.")
            self.gui._queue.put(("cloud_probe", (token, report, error)))

        try:
            threading.Thread(target=run, daemon=True, name="gui-cloud-tab-probe").start()
        except Exception:
            self.probe_busy = False
            if self.probe_lock.locked():
                self.probe_lock.release()
            self.probe_status = "Не удалось запустить проверку. Настройки не изменены."
            self._sync_probe()
            self._update()
            return False
        return True

    def _sync_probe(self):
        if self.probe_label is not None:
            self.probe_label.value = self.probe_status
        if self.probe_button is not None:
            self.probe_button.disabled = self.probe_busy
            self.probe_button.content = "Проверяю…" if self.probe_busy else "Проверить ключ"

    def on_probe(self, value):
        token, report, error = value
        self.probe_busy = False
        if self.probe_lock.locked():
            try:
                self.probe_lock.release()
            except RuntimeError:
                pass
        if token == self.probe_generation:
            if error:
                self.probe_status = str(error)[:300]
            else:
                report = report if isinstance(report, dict) else {}
                label = cloud_llm.provider_label(str(report.get("provider") or ""))
                count = report.get("models")
                found = (f"Список моделей получен: {count} шт." if isinstance(count, int)
                         else "Список моделей получен.")
                self.probe_status = (f"Ключ принят: {label}. {found} Генерация и "
                                     "качество ответа не проверялись.")
        self._sync_probe()
        self._update(self.probe_label, self.probe_button)

    def is_busy(self) -> bool:
        return bool(self.probe_busy)


def _fingerprint():
    try:
        from jarvis import secrets_store

        return secrets_store.secret_fingerprint(secrets_store.CLOUD_LLM_KEY) or "?"
    except Exception:
        return "?"
