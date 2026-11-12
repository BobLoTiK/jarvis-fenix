"""Native persona/settings editors. Drafts are not configuration or a second memory.

UI callbacks and completion application run on Flet's GUI path. Two workers live
here: an explicit, user-triggered Ollama model inventory and the updater (проверка
релиза и скачивание установщика). Both send plain data to FenixGUI's existing
queue, and no request is made while a screen is built or on import; no inference,
microphone or TTS here. Установка обновления — не из GUI-потока: помощник
запускается и приложение выходит (jarvis/updater.py). Облачная модель и ключ —
на отдельной вкладке (jarvis/gui_cloud.py): общий модуль cloud_llm, отдельный
черновик, ключ только в DPAPI-хранилище.
"""
import json
import logging
import threading
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import flet as ft

from jarvis import cloud_llm, persona, profile

log = logging.getLogger(__name__)
STYLES = {"formal": "Формальный", "friendly": "Дружеский",
          "sarcastic": "Саркастичный", "brief": "Краткий"}
TONES = {"auto": "Авто — подстраиваться", "polite": "Вежливый — без мата",
         "unrestricted": "Без цензуры — если вы сами"}
EXAMPLES = {
    "formal": "Уточните, пожалуйста, какую задачу нужно выполнить в первую очередь.",
    "friendly": "Давай разберёмся. Что нужно сделать в первую очередь?",
    "sarcastic": "Планов много. Начнём с одного — что делаем первым?",
    "brief": "Что сделать первым?",
}
SETTING_KEYS = ("llm_model", "ollama_url", "observer_enabled", "memory_rag_enabled",
                "tray_enabled", "launch_mode")
# Облачные настройки (cloud_*) живут на вкладке «Облако»: второй черновик того же
# набора ключей в «Настройках» гарантированно разъезжался бы с первым.


def validated_url(value):
    """Ollama base URL only; never permit embedded credentials or redirect auth."""
    value = value.strip()
    if not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Укажите адрес Ollama без пробелов.")
    try:
        u = urlsplit(value)
        port = u.port
        if (u.scheme not in ("http", "https") or not u.hostname
                or u.username is not None or u.password is not None
                or u.query or u.fragment or "\\" in value):
            raise ValueError
    except ValueError:
        raise ValueError("Нужен HTTP/HTTPS-адрес без логина, пароля, query и fragment.") from None
    if port == 0:
        raise ValueError("Порт должен быть от 1 до 65535.")
    return urlunsplit((u.scheme, u.netloc, u.path.rstrip("/"), "", ""))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_ollama(url):
    """List installed models, not a generation/readiness/quality benchmark."""
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(Request(url + "/api/tags", headers={"Accept": "application/json"}),
                     timeout=4) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError("Oversized inventory")
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Invalid inventory")
    names = set()
    for entry in data["models"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid model entry")
        name = entry.get("name", entry.get("model"))
        if not isinstance(name, str) or len(name) > 256:
            raise ValueError("Invalid model name")
        names.add(name)
    return frozenset(names)


def has_model(names, value):
    return value in names or (":" not in value and value + ":latest" in names)


def _secrets():
    """DPAPI-хранилище импортируется при первом обращении, не на уровне модуля.

    secrets_store тянет ctypes.wintypes: на другой ОС импорт модуля уронил бы
    весь диалог настроек, поэтому локальный импорт и есть граница переносимости.
    """
    from jarvis import secrets_store
    return secrets_store


def cloud_providers():
    """Ключи и подписи провайдеров берутся из cloud_llm: второй список не нужен."""
    return {key: str(entry.get("label") or key) for key, entry in cloud_llm.PROVIDERS.items()}


def validated_cloud_settings(provider, base_url, model):
    """Нормализует облачные параметры перед записью. Сети не касается.

    Пустой адрес допустим только у провайдера с пресетом: у custom пресета нет.
    """
    if provider not in cloud_llm.PROVIDERS:
        raise ValueError("Выберите провайдера облака из списка.")
    base_url = str(base_url or "").strip()
    if base_url:
        base_url = cloud_llm.validated_base_url(base_url)
    elif provider == "custom":
        raise ValueError("Для своего адреса укажите адрес API: пресета у него нет.")
    model = str(model or "").strip()
    if not model or len(model) > 256:
        raise ValueError("Укажите модель облака — до 256 символов.")
    return base_url, model


def probe_cloud(provider, base_url, model, key):
    """Один запрос списка моделей. Ключ приходит аргументом и в UI не попадает."""
    client = cloud_llm.CloudLLM(provider=provider, api_key=key, model=model,
                                base_url=(base_url or None))
    return client.probe()


CLOUD_CONSENT_KEY = "cloud_consent"
CLOUD_CONSENT_VERSION = 1


def consent_payload(enabled, now=None):
    """Запись о согласии: что разрешено, по какой редакции текста и когда."""
    moment = now or datetime.now(timezone.utc)
    return {"cloud_send_profile": bool(enabled),
            "version": CLOUD_CONSENT_VERSION,
            "at": moment.isoformat(timespec="seconds")}


def record_cloud_consent(enabled, now=None):
    """Пишет след согласия в профиль пользователя, а не в config.json.

    Это след, а не гейт: решает по-прежнему cloud_send_profile в конфиге.
    След нужен, чтобы через месяц можно было ответить, когда и в какой
    редакции текста человек разрешил отправку персоны и памяти наружу.
    """
    try:
        return bool(profile.set(CLOUD_CONSENT_KEY, consent_payload(enabled, now)))
    except Exception:
        log.exception("Согласие облака не записано в профиль")
        return False


def consent_summary():
    """Строка для карточки настроек. Ничего не пишет и в сеть не ходит."""
    try:
        data = profile.get(CLOUD_CONSENT_KEY)
    except Exception:
        return "Согласие: профиль недоступен."
    if not isinstance(data, dict) or not data.get("at"):
        return "Согласие: не записано."
    state = ("отправка разрешена" if data.get("cloud_send_profile")
             else "согласие отозвано")
    version = data.get("version")
    suffix = f", редакция {version}" if isinstance(version, int) else ""
    return f"Согласие: {state}, {data['at']}{suffix}."


def _palette():
    # Use the same live theme tokens as Voice and Sound, not a parallel palette.
    from jarvis.gui import P
    return SimpleNamespace(
        bg=P.bg_main,
        card=P.bg_card,
        field=P.bg_card,
        text=P.text,
        dim=P.text_dim,
        border=P.border,
        accent=P.brand,
        tint=P.selected,
        button_text=P.bg_main,
        error=P.error)


def text(value, size=14, muted=False, **kwargs):
    p = _palette()
    return ft.Text(value, size=size, color=p.dim if muted else p.text, **kwargs)


def button(label, handler, primary=False, **kwargs):
    p = _palette()
    if label.endswith(" →"):
        label = ft.Row([text(label[:-2]), ft.Icon(ft.Icons.ARROW_FORWARD, size=17, color=p.accent)],
                       tight=True, spacing=8)
    return ft.Button(content=label, on_click=handler, height=44,
        style=ft.ButtonStyle(bgcolor=p.accent if primary else p.field,
            color=p.button_text if primary else p.text,
            side=ft.BorderSide(1, p.accent if primary else p.border),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=18)), **kwargs)


def card(title, subtitle, controls):
    p = _palette()
    return ft.Container(bgcolor=p.card, border=ft.Border.all(1, p.border),
        border_radius=12, padding=24, content=ft.Column([
            text(title, 19, weight=ft.FontWeight.W_600), text(subtitle, muted=True),
            ft.Container(height=4), *controls], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH))


def input_border():
    p = _palette()
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(
            side=ft.BorderSide(1, p.border), border_radius=8),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(
            side=ft.BorderSide(2, p.accent), border_radius=8),
    }


def divider():
    return ft.Divider(height=12, thickness=1, color=_palette().border)


class PreferenceScreens:
    def __init__(self, gui):
        self.gui = gui
        self.persona_draft = None
        self.persona_baseline = None
        self.profile_id = None
        self.persona_fields = {}
        self.persona_notice = ""
        self.persona_error = False
        self.reset_confirm = False
        self.pending_trait = ""
        self.persona_read_error = False
        self.settings_draft = None
        self.settings_baseline = None
        self.settings_fields = {}
        self.settings_notice = ""
        self.settings_error = False
        self.probe_busy = False
        self._probe_lock = threading.Lock()
        self.probe_thread = None
        self.probe_generation = 0
        self.inventory = None
        self.probe_status = "Доступность ещё не проверялась."
        self.probe_label = None
        self.probe_button = None
        self.preview_title = self.preview_quote = self.preview_details = None
        self._api_status_label = None
        self._api_token_label = None
        self.update_status = "Обновления ещё не проверялись."
        self.update_notes = ""
        self.update_release = None
        self.update_file = None
        self.update_busy = False
        self.update_generation = 0
        self.update_progress = None
        self.update_phase = ""
        self.update_cancel = None
        self.update_label = None
        self.update_notes_label = None
        self.update_button = None
        self.update_check_button = None
        self.update_cancel_button = None
        self.update_bar = None

    def _update(self):
        if self.gui._page is not None:
            self.gui._page.update()

    def _refresh(self, index):
        control = self.build_persona() if index == 3 else self.build_settings()
        self.gui._tabs[index] = control
        if self.gui._content_area is not None and self.gui._rail.selected_index == index:
            self.gui._content_area.content = control
        self._update()

    def _load_persona(self):
        self.persona_read_error = False
        try:
            identity, fields = profile.read_fields("name", "persona")
        except (ValueError, OSError):
            identity, fields = profile.current(), {"name": None, "persona": None}
            self.persona_read_error = True
        self.profile_id, self.persona_baseline = identity, fields
        p = dict(persona.DEFAULT_PERSONA)
        if isinstance(fields["persona"], dict):
            p.update({k: v for k, v in fields["persona"].items()
                      if k in p and v is not None})
        self.persona_draft = {
            "name": str(fields["name"] or ""),
            "assistant_name": str(p["assistant_name"]),
            "speech_style": p["speech_style"] if p["speech_style"] in STYLES else "friendly",
            "tone": p["tone"] if p["tone"] in TONES else "auto",
            "traits": list(p["traits"]) if isinstance(p["traits"], list) else [],
            "backstory": str(p["backstory"]),
        }
        self.persona_notice, self.persona_error = "", False
        self.reset_confirm = False
        self.pending_trait = ""
        if self.persona_read_error:
            self.persona_notice = "Профиль не читается. Запись заблокирована, чтобы не потерять данные."
            self.persona_error = True

    def _ensure_persona(self):
        if self.persona_draft is None or self.profile_id != profile.current():
            self._load_persona()

    def _load_settings(self):
        self.settings_baseline = {k: self.gui.config.get(k) for k in SETTING_KEYS}
        self.settings_draft = deepcopy(self.settings_baseline)

    def _field(self, scope, key, label, multiline=False, max_length=None):
        p = _palette()
        draft = self.persona_draft if scope == "persona" else self.settings_draft
        field = ft.TextField(label=label, value=draft[key] or "",
            on_change=lambda e: self._change(scope, key, e.control.value),
            border=input_border(), color=p.text,
            label_style=ft.TextStyle(color=p.dim), bgcolor=p.field,
            text_size=15, multiline=multiline,
            min_lines=3 if multiline else 1, max_lines=5 if multiline else 1,
            max_length=max_length, counter="")
        (self.persona_fields if scope == "persona" else self.settings_fields)[key] = field
        return field

    def _select(self, scope, key, label, options):
        p = _palette()
        draft = self.persona_draft if scope == "persona" else self.settings_draft
        current = draft[key]
        if current not in options:
            options = {str(current): str(current), **options}
        control = ft.Dropdown(label=label, value=current,
            options=[ft.dropdown.Option(k, v) for k, v in options.items()],
            on_select=lambda e: self._change(scope, key, e.control.value),
            border=input_border(),
            color=p.text, bgcolor=p.field, text_size=15,
            label_style=ft.TextStyle(color=p.dim))
        (self.persona_fields if scope == "persona" else self.settings_fields)[key] = control
        return control

    def _change(self, scope, key, value):
        if scope == "persona":
            if self.profile_id != profile.current():
                self._load_persona()
                self._refresh(3)
                return
            self.persona_draft[key] = value
            self.persona_notice = "Есть несохранённые изменения."
            self.persona_error = False
            self._sync_portrait()
        else:
            self.settings_draft[key] = value
            self.settings_notice = "Есть несохранённые изменения."
            self.settings_error = False
            if key in ("llm_model", "ollama_url"):
                self.probe_generation += 1
                self.inventory = None
                self.probe_status = "Параметры изменены. Проверьте подключение заново."
                self._sync_probe()
        notice = getattr(self, scope + "_notice_control", None)
        if notice is not None:
            notice.value = getattr(self, scope + "_notice")
            notice.color = _palette().dim
        # Do not echo TextField.value back on each keystroke: an entire-page
        # patch can overwrite characters already typed ahead in the client.
        # Update only dependent presentation controls, never the editing field.
        if self.gui._page is not None:
            targets = [notice] if notice is not None else []
            if scope == "persona":
                targets += [self.preview_title, self.preview_quote, self.preview_details]
            else:
                targets += [self.probe_label]
            self.gui._page.update(*[c for c in targets if c is not None])

    def _trait_change(self, e):
        self.pending_trait = e.control.value
        self.persona_notice, self.persona_error = "Есть несохранённые изменения.", False
        if getattr(self, "persona_notice_control", None) is not None:
            self.persona_notice_control.value = self.persona_notice
            self.persona_notice_control.color = _palette().dim
            if self.gui._page is not None:
                self.gui._page.update(self.persona_notice_control)

    def _sync_portrait(self):
        if self.preview_title is None:
            return
        p = self.persona_draft
        self.preview_title.value = p["assistant_name"].strip() or "Феникс"
        self.preview_quote.value = "«" + EXAMPLES.get(p["speech_style"], EXAMPLES["friendly"]) + "»"
        traits = [v for v in p["traits"] if isinstance(v, str)]
        self.preview_details.value = (persona.STYLE_DESCRIPTIONS.get(p["speech_style"], "")
            + "\n" + persona.TONE_DESCRIPTIONS.get(p["tone"], "")
            + ("\n" + ", ".join(traits) if traits else ""))

    def _notice(self, scope):
        p = _palette()
        control = text(getattr(self, scope + "_notice") or
            "Изменения применятся после сохранения.", muted=True)
        if getattr(self, scope + "_error"):
            control.color = p.error
        setattr(self, scope + "_notice_control", control)
        return control

    def _screen(self, title, subtitle, content, footer):
        p = _palette()
        return ft.Container(expand=True, bgcolor=p.bg, padding=28,
            content=ft.Column([
                ft.Text("ХАРАКТЕР И ОБЩЕНИЕ" if title == "Персона" else
                        "ПРИЛОЖЕНИЕ И ПРИВАТНОСТЬ", size=12, color=p.accent),
                text(title, 32, weight=ft.FontWeight.W_600),
                text(subtitle, 16, muted=True), ft.Container(height=8),
                content, *footer], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True))

    def add_trait(self, e):
        value = (self.pending_trait or e.control.value or "").strip()
        if not value:
            return
        if len(value) > 40 or len(self.persona_draft["traits"]) >= 12:
            self.persona_notice, self.persona_error = "До 12 черт, каждая до 40 символов.", True
        elif value not in self.persona_draft["traits"]:
            self._change("persona", "traits", self.persona_draft["traits"] + [value])
            self.pending_trait = ""
        self._refresh(3)

    def remove_trait(self, value):
        self._change("persona", "traits", [t for t in self.persona_draft["traits"] if t != value])
        self._refresh(3)

    def build_persona(self):
        self._ensure_persona()
        self.persona_fields = {}
        p = _palette()
        names = ft.ResponsiveRow([
            ft.Container(self._field("persona", "name", "Ваше имя", max_length=60), col={"xs": 12, "md": 6}),
            ft.Container(self._field("persona", "assistant_name", "Имя ассистента", max_length=60), col={"xs": 12, "md": 6}),
        ], spacing=16, run_spacing=16)
        style_buttons = ft.Row([button(label,
            lambda e, key=key: self.choose_style(key),
            primary=self.persona_draft["speech_style"] == key,
            icon=ft.Icons.CHECK if self.persona_draft["speech_style"] == key else None,
            tooltip=label + (" — выбран" if self.persona_draft["speech_style"] == key else ""))
            for key, label in STYLES.items()], wrap=True, spacing=8, run_spacing=8)
        traits = [ft.Chip(label=text(str(t)), on_delete=lambda e, t=t: self.remove_trait(t),
                         bgcolor=p.tint) for t in self.persona_draft["traits"]]
        add = ft.TextField(label="Добавить черту · Enter", value=self.pending_trait, on_submit=self.add_trait,
            on_change=self._trait_change, max_length=40, counter="", text_size=14,
            border=input_border(), color=p.text,
            label_style=ft.TextStyle(color=p.dim), bgcolor=p.field)
        from jarvis.gui import _brand_image
        self.preview_title = text("", 25, weight=ft.FontWeight.W_600)
        self.preview_details = text("", muted=True)
        self.preview_quote = text("", 18)
        self._sync_portrait()
        portrait = card("Портрет персоны", "Профиль: " + self.profile_id, [
            _brand_image("phoenix", 72), self.preview_title, self.preview_details,
            divider(), text("ПРИМЕР МАНЕРЫ", 12, muted=True),
            ft.Container(self.preview_quote, border=ft.Border(left=ft.BorderSide(2, p.accent)),
                         padding=ft.Padding.only(left=16)),
            text("Иллюстрация выбранного стиля, не ответ модели. LLM не запускается, история не меняется.", muted=True),
            divider(), text("Персона задаёт общение. Голос и темп — в отдельном разделе.", muted=True),
            button("Голос и звук →", lambda e: self.gui._select_tab(2))])
        columns = ft.ResponsiveRow([
            ft.Container(ft.Column([
                card("Как обращаться друг к другу", "Имена для диалога, не команда активации.", [names]),
                card("Манера общения", "Выберите стиль, который ощущается вашим.", [
                    style_buttons, divider(), self._select("persona", "tone", "Тон разговора", TONES)]),
                card("Детали характера", "Дополняют стиль, не меняя правила безопасных действий.", [
                    ft.Row(traits, wrap=True, spacing=8, run_spacing=8), add,
                    self._field("persona", "backstory", "Контекст общения", multiline=True, max_length=2000)]),
            ], spacing=18), col={"xs": 12, "lg": 8}),
            ft.Container(portrait, col={"xs": 12, "lg": 4}),
        ], spacing=20, run_spacing=20)
        reset = [button("Отмена", lambda e: self.confirm_reset(False)),
                 button("Повторить знакомство", lambda e: self.confirm_reset(True))] if self.reset_confirm else [
                 button("Повторить знакомство…", self.ask_reset)]
        return self._screen("Персона", "Знакомый голос. Ваш стиль общения.", columns, [
            self._notice("persona"), ft.Row([button("Отменить изменения", self.cancel_persona),
                button("Сохранить персону", self.save_persona, primary=True)], wrap=True),
            *([text("Сбросится только знакомство. Факты и история останутся; черновик не сохраняется.", muted=True)]
              if self.reset_confirm else []), ft.Row(reset, wrap=True)])

    def choose_style(self, key):
        self._change("persona", "speech_style", key)
        self._refresh(3)

    def cancel_persona(self, e=None):
        self._load_persona()
        self.persona_notice = "Черновик отменён. Показаны сохранённые значения."
        self._refresh(3)

    def save_persona(self, e=None):
        d = deepcopy(self.persona_draft)
        pending = self.pending_trait.strip()
        if pending and pending not in d["traits"]:
            d["traits"].append(pending)
        if self.persona_read_error:
            self.persona_notice, self.persona_error = "Профиль не читается. Сохранение заблокировано.", True
        elif self.profile_id != profile.current():
            self._load_persona()
            self.persona_notice, self.persona_error = "Профиль сменился. Старый черновик не сохранён.", True
        elif (not d["assistant_name"].strip() or len(d["assistant_name"].strip()) > 60
              or len(d["name"].strip()) > 60 or len(d["backstory"]) > 2000
              or d["speech_style"] not in STYLES or d["tone"] not in TONES
              or len(d["traits"]) > 12
              or any(not isinstance(t, str) or not t.strip() or len(t) > 40 for t in d["traits"])):
            self.persona_notice, self.persona_error = "Проверьте поля: имя ассистента обязательно; имена до 60, контекст до 2000 символов, до 12 черт по 40 символов.", True
        else:
            # Merge supported fields into the baseline; onboarding and future/legacy keys survive.
            merged = dict(self.persona_baseline["persona"]) if isinstance(self.persona_baseline["persona"], dict) else {}
            merged.update({k: (v.strip() if isinstance(v, str) else deepcopy(v))
                           for k, v in d.items() if k != "name"})
            if profile.update_fields({"name": d["name"].strip(), "persona": merged},
                    expected_profile=self.profile_id, expected_values=self.persona_baseline):
                self._load_persona()
                self.persona_notice = "Персона сохранена в текущем профиле."
            else:
                self.persona_notice, self.persona_error = "Не удалось сохранить: профиль изменён другим действием или запись недоступна. Черновик сохранён на экране. Для загрузки актуальных данных нажмите «Отменить изменения».", True
        self._refresh(3)

    def ask_reset(self, e=None):
        self.reset_confirm = True
        self._refresh(3)

    def confirm_reset(self, confirm):
        if confirm and not self.persona_read_error:
            baseline = self.persona_baseline
            merged = dict(baseline["persona"]) if isinstance(baseline["persona"], dict) else {}
            merged.update(onboarding_done=False, onboarding_at=0.0)
            ok = profile.update_fields({"persona": merged}, expected_profile=self.profile_id,
                                       expected_values=baseline)
            if ok:
                self.persona_baseline["persona"] = merged
            self.persona_notice = ("Знакомство сброшено. Факты, история и черновик сохранены."
                if ok else "Сброс не выполнен: профиль изменён или запись недоступна.")
            self.persona_error = not ok
        self.reset_confirm = False
        self._refresh(3)

    def _toggle(self, key, title, description):
        p = _palette()
        control = ft.Switch(value=bool(self.settings_draft[key]), active_color=p.accent,
            on_change=lambda e: self._change("settings", key, bool(e.control.value)),
            tooltip=title)
        self.settings_fields[key] = control
        return ft.Row([ft.Column([text(title, 15), text(description, 13, muted=True)],
                                  spacing=5, expand=True), control], spacing=16)

    def build_settings(self):
        if self.settings_draft is None:
            self._load_settings()
        self.settings_fields = {}
        from jarvis.gui import LLM_MODELS, THEMES
        self.probe_label = text(self.probe_status, muted=True)
        self.probe_button = button("Проверяю…" if self.probe_busy else "Проверить подключение",
                                   self.start_probe, disabled=self.probe_busy)
        model = card("Локальная модель", "Ollama для ответов и обработки контекста.", [
            self._select("settings", "llm_model", "Модель", {m: m for m in LLM_MODELS}),
            self._field("settings", "ollama_url", "Адрес Ollama", max_length=2048),
            self.probe_label, self.probe_button,
            text("Проверка читает только список моделей. Не запускает генерацию и не скачивает файлы.", muted=True),
            divider(), text("При удалённом адресе запросы и включённый анализ диалога уходят на выбранный сервер. Слово «локальная» не гарантирует приватность удалённого сервера.", muted=True)])
        cloud = card("Облачная модель", "Провайдер, ключ и приватность — на отдельной вкладке.", [
            text("Здесь только локальная модель. Облако не смешивается с этими настройками: "
                 "у него свой черновик, своя проверка ключа и своя запись согласия.", muted=True),
            button("Открыть «Облако» →", lambda e: self.gui._select_tab(7))])
        privacy = card("Приватность и память", "По умолчанию оба способа обработки выключены.", [
            self._toggle("observer_enabled", "Запоминать факты из диалога",
                "Observer отправляет недавние сообщения в выбранную Ollama. Факты сохраняются в профиле, диагностика — в observer.log."),
            text("После перезапуска — и включение, и отключение.", 13, muted=True), divider(),
            self._toggle("memory_rag_enabled", "Подбирать факты по смыслу",
                "RAG отбирает уже сохранённые факты. После применения — сразу. Новые факты не собирает."),
            text("Для включения проверьте наличие настроенной embedding-модели через «Проверить подключение». Автозагрузки здесь нет.", muted=True)])
        theme = ft.Dropdown(label="Тема", value=self.gui.config.get("gui_theme", "Системная"),
            options=[ft.dropdown.Option(t) for t in THEMES],
            on_select=self.gui._on_theme_change, color=_palette().text,
            bgcolor=_palette().field, border=input_border(),
            label_style=ft.TextStyle(color=_palette().dim))
        hints = ft.Switch(label="Показывать подсказки на Главной",
            value=not bool(self.gui.config.get("ui_home_hints_seen", False)),
            on_change=lambda e: self.gui.set_home_hints(bool(e.control.value)))
        appearance = card("Внешний вид", "Тот же Феникс, в комфортном свете.", [
            theme, hints,
            text("Тема применяется сразу. Черновики других настроек сохраняются.", muted=True)])
        vertical = self._vertical_card()
        launch = card("Запуск и окно", "Поведение на рабочем столе.", [
            self._toggle("tray_enabled", "Оставаться в трее", "При закрытии окна продолжать работу. Применяется сразу после сохранения."),
            divider(), self._select("settings", "launch_mode", "При запуске приложения",
                {"gui": "Показывать окно", "tray": "Только трей"}),
            text("Режим запуска — со следующего старта приложения.", muted=True)])
        audio = card("Голос — в своём разделе", "Без повторяющихся настроек в разных местах.", [
            text("Движок, голос, темп, реакции и проба речи.", muted=True),
            button("Открыть «Голос и звук» →", lambda e: self.gui._select_tab(2))])
        content = ft.ResponsiveRow([
            ft.Container(ft.Column([model, cloud, privacy], spacing=18), col={"xs": 12, "lg": 6}),
            ft.Container(ft.Column([appearance, vertical, launch, audio, self._api_card(),
                                    self._update_card()],
                                   spacing=18), col={"xs": 12, "lg": 6}),
        ], spacing=20, run_spacing=20)
        return self._screen("Настройки", "Всё важное — на своих местах.", content, [
            self._notice("settings"), ft.Row([button("Отменить изменения", self.cancel_settings),
                button("Применить изменения", self.save_settings, primary=True)], wrap=True)])

    def _vertical_card(self):
        """Карточка вертикального режима: переключается сразу, без «Применить»."""
        from jarvis.gui_vertical import PANELS, WIDTH_DEFAULT, normalize_panel, normalize_width

        p = _palette()
        gui = self.gui
        width = normalize_width(gui.config.get("ui_vertical_width", WIDTH_DEFAULT))
        panel = normalize_panel(gui.config.get("ui_vertical_panel", "log"))
        widths = ["220", "240", "260", "280", "300", "320"]
        if str(width) not in widths:
            widths.append(str(width))
            widths.sort(key=int)
        switch = ft.Switch(value=bool(gui.config.get("ui_vertical_enabled", False)),
            active_color=p.accent, tooltip="Вертикальная полоса",
            on_change=lambda e: gui.set_vertical_mode(bool(e.control.value)))
        width_select = ft.Dropdown(label="Ширина", value=str(width),
            options=[ft.dropdown.Option(v, f"{v} px") for v in widths],
            on_select=lambda e: gui.set_vertical_width(int(e.control.value)),
            color=p.text, bgcolor=p.field, border=input_border(),
            label_style=ft.TextStyle(color=p.dim))
        panel_select = ft.Dropdown(label="Под светяшкой", value=panel,
            options=[ft.dropdown.Option(key, label) for key, label in PANELS.items()],
            on_select=lambda e: gui.set_vertical_panel(e.control.value),
            color=p.text, bgcolor=p.field, border=input_border(),
            label_style=ft.TextStyle(color=p.dim))
        never_switch = ft.Switch(
            value=gui.config.get("ui_vertical_never_hide", False) is True,
            active_color=p.accent, tooltip="Не прятать полосу",
            on_change=lambda e: gui.set_vertical_never_hide(bool(e.control.value)))
        return card("Полоса на краю экрана", "Ассистент всегда перед глазами.", [
            ft.Row([ft.Column([text("Вертикальный режим", 15),
                    text("Узкая полоса без рамки поверх других окон, у правого края.", 13, muted=True)],
                    spacing=5, expand=True), switch], spacing=16),
            divider(), width_select, panel_select,
            ft.Row([ft.Column([text("Не прятать полосу", 15),
                    text("Остаётся открытой, пока режим включён: без автоскрытия.", 13, muted=True)],
                    spacing=5, expand=True), never_switch], spacing=16),
            text("Переключается сразу, черновик остальных настроек не трогается. "
                 "Заметки и план лежат в %APPDATA%\\Phoenix и сохраняются при уходе из поля ввода.", muted=True)])

    # --- локальный API -------------------------------------------------

    def _api_card(self):
        """Карточка локального стыка: галочка, порт, токен, состояние."""
        from jarvis.api_server import normalize_port

        p = _palette()
        gui = self.gui
        enabled = gui.config.get("api_enabled", False) is True
        port = normalize_port(gui.config.get("api_port", 8765))
        switch = ft.Switch(value=enabled, active_color=p.accent, tooltip="Локальный API",
                           on_change=self._on_api_toggle)
        port_field = ft.TextField(value=str(port), label="Порт", width=110, dense=True,
                                  text_size=13, on_submit=self._on_api_port,
                                  on_blur=self._on_api_port, color=p.text,
                                  bgcolor=p.field, border=input_border(),
                                  label_style=ft.TextStyle(color=p.dim))
        self._api_status_label = text(getattr(gui, "_api_status", "API выключен."), 13, muted=True)
        self._api_token_label = text(self._api_token_text(), 13, muted=True)
        return card("Локальный API", "Стык с другими проектами: health, capabilities, turn.", [
            ft.Row([ft.Column([text("Локальный API", 15),
                    text("Только 127.0.0.1, вход по токену. Для стыков между проектами.",
                         13, muted=True)], spacing=5, expand=True), switch], spacing=16),
            divider(), ft.Row([port_field, button("Новый токен", self._on_api_token)],
                              spacing=12, wrap=True),
            self._api_token_label, self._api_status_label, divider(),
            text("Пароль через API запрещён. Профиль, история и память наружу не уходят: "
                 "только ответ на присланный текст. Токен хранится в зашифрованном "
                 "хранилище Windows, а не в config.json.", muted=True)])

    def _api_token_text(self):
        fingerprint = ""
        try:
            fingerprint = self.gui._api_fingerprint()
        except Exception:
            fingerprint = ""
        if fingerprint:
            return f"Токен: {fingerprint}… (отпечаток, не сам токен)"
        return "Токен ещё не создан — он появится при включении."

    def _api_refresh_labels(self):
        if self._api_status_label is not None:
            self._api_status_label.value = getattr(self.gui, "_api_status", "API выключен.")
        if self._api_token_label is not None:
            self._api_token_label.value = self._api_token_text()
        self._update()

    def _on_api_toggle(self, e):
        self.gui.set_api_enabled(bool(e.control.value))
        e.control.value = self.gui.config.get("api_enabled", False) is True
        self._api_refresh_labels()

    def _on_api_port(self, e):
        from jarvis.api_server import normalize_port

        raw = (e.control.value or "").strip()
        try:
            port = int(raw)
        except (TypeError, ValueError):
            port = normalize_port(self.gui.config.get("api_port", 8765))
        self.gui.set_api_port(port)
        e.control.value = str(normalize_port(self.gui.config.get("api_port", 8765)))
        self._api_refresh_labels()

    def _on_api_token(self, e=None):
        self.gui.regenerate_api_token()
        self._api_refresh_labels()

    # --- обновления ----------------------------------------------------

    def _update_card(self):
        """Обновления: галочка стартовой проверки, статус, скачивание, установка."""
        from jarvis import updater

        p = _palette()
        gui = self.gui
        kind = updater.install_kind()
        enabled = gui.config.get("update_check_enabled", True) is True
        switch = ft.Switch(value=enabled, active_color=p.accent, tooltip="Проверять обновления",
                           on_change=self._on_update_toggle)
        self.update_label = text(self.update_status, 13, muted=True)
        self.update_notes_label = text(self.update_notes, 12, muted=True,
                                       visible=bool(self.update_notes))
        self.update_bar = ft.ProgressBar(value=0, height=6, color=p.accent, visible=False)
        self.update_check_button = button("Проверить обновления", self.start_update_check)
        self.update_button = button("Скачать обновление", self.start_update_download,
                                    primary=True, visible=False)
        self.update_cancel_button = button("Отменить скачивание", self.cancel_update_download,
                                           visible=False)
        if kind == "source":
            note = ("Это запуск из папки проекта: обновление ставится только у "
                    "установленной копии Феникса.")
        else:
            note = ("Установщики не подписаны — UAC спросит про неизвестного издателя. "
                    "SHA-256 сверяется с SHA256SUMS.txt релиза: это защита от битого или "
                    "подменённого при скачивании файла, а не подпись автора.")
            if kind == "standalone":
                note += " Автономная сборка ставится с повышением прав."
            note += (" Феникс закроется, помощник обновления поставит версию поверх "
                     "текущей и запустит Феникс снова.")
        return card("Обновления", f"GitHub Releases · {updater.KIND_TITLES.get(kind, kind)}.", [
            ft.Row([ft.Column([text("Проверять при запуске", 15),
                    text("Один фоновый запрос к api.github.com. Установка — только по кнопке.",
                         13, muted=True)], spacing=5, expand=True), switch], spacing=16),
            divider(), self.update_label, self.update_notes_label, self.update_bar,
            ft.Row([self.update_check_button, self.update_button,
                    self.update_cancel_button,
                    button("Страница релизов →", self._open_releases)], spacing=12, wrap=True),
            text(note, muted=True)])

    def _sync_update(self):
        if self.update_label is not None:
            self.update_label.value = self.update_status
        if self.update_notes_label is not None:
            self.update_notes_label.value = self.update_notes
            self.update_notes_label.visible = bool(self.update_notes)
        if self.update_check_button is not None:
            self.update_check_button.disabled = self.update_busy
            busy_check = self.update_busy and self.update_phase == "check"
            self.update_check_button.content = "Проверяю…" if busy_check else "Проверить обновления"
        if self.update_bar is not None:
            value = self.update_progress
            self.update_bar.visible = value is not None
            self.update_bar.value = 0 if value is None else max(0.0, min(1.0, float(value)))
        if self.update_button is not None:
            from jarvis import updater

            installable = (self.update_release is not None
                           and updater.install_kind() != "source")
            self.update_button.visible = installable
            self.update_button.disabled = self.update_busy or not installable
            if self.update_file is not None:
                label = "Установить и перезапустить"
            elif self.update_busy and self.update_phase == "download":
                label = "Скачиваю…"
            else:
                label = "Скачать обновление"
            self.update_button.content = label
        if self.update_cancel_button is not None:
            downloading = self.update_busy and self.update_phase == "download"
            self.update_cancel_button.visible = downloading
            # После нажатия кнопка гаснет: повторное нажатие всё равно не нужно.
            self.update_cancel_button.disabled = not downloading or self.update_cancel is None

    def _on_update_toggle(self, e):
        self.gui.set_update_check(bool(e.control.value))
        e.control.value = self.gui.config.get("update_check_enabled", True) is True
        self._update()

    def _open_releases(self, e=None):
        import os

        from jarvis import updater

        url = self.update_release.page if self.update_release is not None else updater.RELEASE_PAGE
        try:
            os.startfile(url)
            return True
        except Exception:
            log.exception("Обновление: не удалось открыть страницу релизов")
            self.update_status = f"Откройте страницу вручную: {url}"
            self._sync_update()
            self._update()
            return False

    def start_update_check(self, e=None, background=False):
        """Фоновая проверка релиза; результат приходит через очередь GUI."""
        from jarvis import updater

        if self.update_busy:
            # Молчаливый отказ выглядел как «кнопка не работает»: говорим, что идёт.
            phase = {"check": "проверка", "download": "скачивание"}.get(self.update_phase, "действие")
            self.update_status = f"Уже идёт {phase} — дождитесь конца или отмените скачивание."
            self._sync_update()
            self._update()
            return False
        self.update_generation += 1
        token = self.update_generation
        self.update_busy = True
        self.update_phase = "check"
        self.update_status = "Проверяю GitHub…"
        self.update_progress = None
        self._sync_update()
        self._update()

        def run():
            try:
                value = updater.check()
            except Exception:
                log.exception("Обновление: проверка упала вне ожидаемых ошибок")
                value = None
            self.gui._queue.put(("update_result", ("check", token, value)))

        try:
            threading.Thread(target=run, daemon=True, name="gui-update-check").start()
        except Exception:
            log.exception("Обновление: не удалось запустить поток проверки")
            self.update_busy = False
            self.update_phase = ""
            self.update_status = "Не удалось запустить проверку обновлений."
            self._sync_update()
            self._update()
            return False
        return True

    def start_update_download(self, e=None):
        """Скачать установщик (или перейти к установке, если он уже скачан)."""
        from jarvis import updater

        if self.update_busy or self.update_release is None:
            return False
        if self.update_file is not None:
            return self.start_update_apply()
        kind = updater.install_kind()
        if kind == "source":
            self.update_status = "Обновление ставится только у установленной копии Феникса."
            self._sync_update()
            self._update()
            return False
        release = self.update_release
        asset = release.installer(kind)
        if asset is None:
            self.update_status = ("В релизе нет установщика для этой сборки — скачайте его "
                                  "вручную со страницы релизов.")
            self._sync_update()
            self._update()
            return False
        sums_asset = release.sums()
        self.update_generation += 1
        token = self.update_generation
        cancel = threading.Event()
        self.update_cancel = cancel
        self.update_busy = True
        self.update_phase = "download"
        self.update_progress = 0
        self.update_status = f"Скачиваю {asset.name}…"
        self._sync_update()
        self._update()

        def progress(done, total):
            self.gui._queue.put(("update_result", ("progress", token, (done, int(total or 0)))))

        def run():
            error = ""
            path = None
            try:
                # Прошлые установщики не копим: папка обновления живёт между версиями.
                updater.cleanup_installers()
                sums = updater.fetch_sums(sums_asset) if sums_asset is not None else {}
                path = updater.download(asset, sums=sums, progress=progress, cancel=cancel)
            except updater.UpdateError as failure:
                error = str(failure)
            except Exception:
                # Никаких путей и трейсбеков в интерфейс — только понятный текст.
                log.exception("Обновление: скачивание упало")
                error = "Скачивание не удалось. Повторите позже."
            self.gui._queue.put(("update_result", ("download", token, (path, error))))

        try:
            threading.Thread(target=run, daemon=True, name="gui-update-download").start()
        except Exception:
            log.exception("Обновление: не удалось запустить поток скачивания")
            self.update_busy = False
            self.update_phase = ""
            self.update_progress = None
            self.update_status = "Не удалось начать скачивание обновления."
            self._sync_update()
            self._update()
            return False
        return True

    def cancel_update_download(self, e=None):
        """Попросить поток скачивания остановиться: файл .part будет убран."""
        if not self.update_busy or self.update_phase != "download":
            return False
        event = self.update_cancel
        if event is not None:
            event.set()
            self.update_cancel = None
        self.update_status = "Отменяю скачивание…"
        self._sync_update()
        self._update()
        return True

    def start_update_apply(self):
        """Запустить помощника и попросить приложение выйти — Феникс вернётся сам."""
        from jarvis import updater

        if self.update_busy or self.update_file is None or self.update_release is None:
            return False
        try:
            updater.spawn_installer(self.update_file, self.update_release.version)
        except updater.UpdateError as failure:
            self.update_status = str(failure)
            self._sync_update()
            self._update()
            return False
        except Exception:
            log.exception("Обновление: не удалось запустить помощника")
            self.update_status = "Не удалось запустить установку обновления."
            self._sync_update()
            self._update()
            return False
        self.update_status = ("Устанавливаю. Феникс закроется и вернётся сам. "
                              "Если UAC спросит — разрешите установку.")
        self._sync_update()
        self._update()
        self.gui._queue.put(("update_quit", None))
        return True

    def apply_update_result(self, payload):
        """Единственное место, где результат работника попадает в контролы."""
        from jarvis import updater

        try:
            kind, token, value = payload
        except (TypeError, ValueError):
            return
        if not isinstance(token, int) or token != self.update_generation:
            return
        if kind == "progress":
            done, total = value if isinstance(value, tuple) else (0, 0)
            self.update_progress = (done / total) if total else None
            if self.update_bar is not None and self.gui._page is not None:
                self.update_bar.visible = self.update_progress is not None
                self.update_bar.value = self.update_progress or 0
                try:
                    self.gui._page.update(self.update_bar)
                except Exception:
                    pass
            return
        if kind == "check":
            self.update_busy = False
            self.update_phase = ""
            self.update_progress = None
            self.update_release = None
            self.update_file = None
            self.update_notes = ""
            if value is not None and getattr(value, "status", "") == "update":
                self.update_release = value.release
                self.update_notes = value.release.notes if value.release else ""
            self.update_status = (updater.describe(value) if value is not None
                                  else "Проверка обновлений не удалась.")
            self._sync_update()
            self._update()
            if self.update_release is not None:
                self.gui.toast(f"Доступно обновление {self.update_release.version}", "info")
            return
        if kind == "download":
            path, error = value if isinstance(value, tuple) else (None, "Скачивание не удалось.")
            self.update_busy = False
            self.update_phase = ""
            self.update_progress = None
            self.update_cancel = None
            if error or path is None:
                self.update_file = None
                self.update_status = error or "Скачивание не удалось."
            else:
                self.update_file = path
                self.update_status = (f"Установщик {path.name} скачан. Кнопка ниже поставит "
                                      "версию и перезапустит Феникс.")
                self.gui.toast("Обновление скачано — можно устанавливать", "success")
            self._sync_update()
            self._update()

    def cancel_settings(self, e=None):
        self._load_settings()
        self.probe_generation += 1
        self.inventory = None
        self.probe_status = "Доступность ещё не проверялась."
        self.settings_notice, self.settings_error = "Черновик отменён. Тема не изменена.", False
        self._refresh(4)

    def _sync_probe(self):
        if self.probe_label is not None:
            self.probe_label.value = self.probe_status
        if self.probe_button is not None:
            self.probe_button.disabled = self.probe_busy
            self.probe_button.content = "Проверяю…" if self.probe_busy else "Проверить подключение"

    def start_probe(self, e=None):
        if self.probe_busy:
            return False
        try:
            url = validated_url(self.settings_draft["ollama_url"])
        except ValueError as error:
            self.probe_status = str(error)
            self._sync_probe()
            self._update()
            return False
        if not self._probe_lock.acquire(blocking=False):
            return False
        self.probe_generation += 1
        token = self.probe_generation
        self.probe_busy = True
        self.inventory = None
        self.probe_status = "Проверяю список установленных моделей…"
        self._sync_probe()
        self._update()
        def run():
            try:
                result = (token, url, probe_ollama(url), None)
            except Exception:
                # Never expose/log URL credentials, raw response or exception payload.
                result = (token, url, None, "Проверка не удалась. Проверьте адрес, запуск Ollama и доступность сервера. Настройки не изменены.")
            self.gui._queue.put(("preferences_result", result))
        try:
            self.probe_thread = threading.Thread(target=run, daemon=True, name="gui-ollama-probe")
            self.probe_thread.start()
        except Exception:
            self.probe_busy = False
            self._probe_lock.release()
            self.probe_status = "Не удалось запустить проверку. Настройки не изменены."
            self._sync_probe()
            self._update()
            return False
        return True

    def apply_probe(self, result):
        token, url, names, error = result
        self.probe_busy = False
        if self._probe_lock.locked():
            self._probe_lock.release()
        if token == self.probe_generation:
            if error:
                self.probe_status = error
            else:
                self.inventory = (url, names)
                model = self.settings_draft["llm_model"]
                embed = self.gui.config.get("memory_rag_model", "nomic-embed-text")
                self.probe_status = ("Ollama доступна. Модель " + ("найдена." if has_model(names, model) else "не найдена.")
                    + " Embedding-модель " + ("найдена." if has_model(names, embed) else "не найдена.")
                    + " Генерация и качество не проверялись.")
        self._sync_probe()
        if self.gui._page is not None:
            self.gui._page.update(self.probe_label, self.probe_button)

    def save_settings(self, e=None):
        self.settings_error = True
        try:
            d = deepcopy(self.settings_draft)
            d["ollama_url"] = validated_url(d["ollama_url"])
            if not isinstance(d["llm_model"], str) or not d["llm_model"].strip() or len(d["llm_model"]) > 256:
                raise ValueError("Выберите непустое имя модели до 256 символов.")
            if d["launch_mode"] not in ("gui", "tray"):
                raise ValueError("Выберите режим запуска.")
            if d["launch_mode"] == "tray" and not d["tray_enabled"]:
                raise ValueError("Для запуска только в трее сначала включите «Оставаться в трее».")
            for key in ("observer_enabled", "memory_rag_enabled", "tray_enabled"):
                if type(d[key]) is not bool:
                    raise ValueError("Проверьте переключатели настроек.")
            # Notify the new endpoint before model warmup in the existing Brain subscriber.
            ordered_keys = ("ollama_url", "llm_model", "observer_enabled", "memory_rag_enabled",
                            "tray_enabled", "launch_mode")
            changes = {k: d[k] for k in ordered_keys if d[k] != self.settings_baseline[k]}
            if any(self.gui.config.get(k) != self.settings_baseline[k] for k in changes):
                raise ValueError("Эти настройки изменены другим действием. Черновик не записан. Отмените изменения, чтобы загрузить актуальные данные.")
            if "llm_model" in changes or "ollama_url" in changes:
                if getattr(self.gui, "_command_busy", False):
                    raise ValueError("Дождитесь окончания текущей команды перед сменой модели или адреса.")
            if d["memory_rag_enabled"] and ("memory_rag_enabled" in changes or "ollama_url" in changes):
                embed = self.gui.config.get("memory_rag_model", "nomic-embed-text")
                if not self.inventory or self.inventory[0] != d["ollama_url"] or not has_model(self.inventory[1], embed):
                    raise ValueError("Для RAG сначала проверьте подключение и наличие embedding-модели. Автозагрузка не выполняется.")
            if not self.gui.config.update(changes, expected_values={k: self.settings_baseline[k] for k in changes}):
                raise ValueError("Не удалось записать настройки. Черновик сохранён; прежние значения не изменены.")
            self._load_settings()
            self.settings_error = False
            self.settings_notice = "Изменений нет." if not changes else "Настройки сохранены."
            if "observer_enabled" in changes or "launch_mode" in changes:
                self.settings_notice += " Для Observer и режима запуска нужен перезапуск."
            if getattr(self.gui, "_model_label", None) is not None:
                self.gui._model_label.value = self.gui._model_caption()
        except ValueError as error:
            self.settings_notice = str(error)
        self._refresh(4)
