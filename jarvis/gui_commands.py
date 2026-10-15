"""Flet editor for the existing custom_commands pipeline. Never executes a preview."""
from copy import deepcopy
import flet as ft
from jarvis import command_builder as model


def _button(*args, **kwargs):
    from jarvis.gui import P, TEXT
    kwargs.setdefault("height", 44)
    kwargs.setdefault("color", TEXT)
    kwargs.setdefault("bgcolor", P.selected)
    kwargs.setdefault("elevation", 0)
    kwargs.setdefault("style", ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8),
                                             side=ft.BorderSide(1, P.border)))
    return ft.Button(*args, **kwargs)


def _field(*args, **kwargs):
    # Flet 1.x sends editable values back when the change event is subscribed.
    kwargs.setdefault("on_change", lambda e: None)
    return ft.TextField(*args, **kwargs)


class CommandBuilder:
    def __init__(self, gui):
        self.gui = gui
        self.draft = None
        self.fields = None
        self.step_fields = []
        self.notice = ""
        self.confirm_delete = None

    def capture(self):
        if self.draft is not None and self.fields:
            self.draft.update(name=self.fields["name"].value or "",
                              phrases=(self.fields["phrases"].value or "").splitlines(),
                              enabled=bool(self.fields["enabled"].value))
            steps = []
            for action, parameter in self.step_fields:
                key = model.ACTIONS[action.value][2]
                step = {"action": action.value}
                if key:
                    step[key] = parameter.value or ""
                steps.append(step)
            self.draft["steps"] = steps

    def refresh(self):
        control = self.build()
        self.gui._tabs[5] = control
        if self.gui._content_area is not None and self.gui._rail.selected_index == 5:
            self.gui._content_area.content = control
        if self.gui._page is not None:
            self.gui._page.update()

    def new(self, template=None):
        self.draft = deepcopy(template) if template else {
            "name": "", "phrases": [], "enabled": True,
            "steps": [{"action": "open_app", "target": ""}]}
        self.fields = None
        self.step_fields = []
        self.notice = ""
        self.refresh()

    def edit(self, entry):
        try:
            self.draft = model.validate_entry(entry, self.gui.config.get("wake_words", []))
        except ValueError as error:
            self.notice = str(error)
        else:
            self.fields = None
            self.step_fields = []
            self.notice = ""
        self.refresh()

    def back(self, e=None):
        self.draft = None
        self.fields = None
        self.notice = ""
        self.refresh()

    def change_step(self, index, action):
        self.capture()
        defaults = {"set_volume": 20, "set_timer": 1500, "shutdown_pc": 30, "reboot_pc": 30}
        key = model.ACTIONS[action][2]
        self.draft["steps"][index] = {"action": action}
        if key:
            self.draft["steps"][index][key] = defaults.get(action, "")
        self.fields = None
        self.refresh()

    def move_step(self, index, direction):
        self.capture()
        dest = index + direction
        if 0 <= dest < len(self.draft["steps"]):
            steps = self.draft["steps"]
            steps[index], steps[dest] = steps[dest], steps[index]
        self.fields = None
        self.refresh()

    def add_step(self, e=None):
        self.capture()
        if len(self.draft["steps"]) < 6:
            self.draft["steps"].append({"action": "open_app", "target": ""})
        self.fields = None
        self.refresh()

    def remove_step(self, index):
        self.capture()
        if len(self.draft["steps"]) > 1:
            self.draft["steps"].pop(index)
        self.fields = None
        self.refresh()

    def save(self, e=None):
        self.capture()
        try:
            entry = model.save_entry(self.gui.config, self.draft)
        except (ValueError, OSError) as error:
            self.notice = str(error)
            self.fields = None
        else:
            self.draft = None
            self.fields = None
            self.notice = f'Сохранено: {entry["name"]}. Применяется без перезапуска.'
        self.refresh()

    def toggle(self, entry, enabled):
        try:
            model.save_entry(self.gui.config, {**entry, "enabled": enabled})
            self.notice = "Команда включена." if enabled else "Команда выключена."
        except (ValueError, OSError) as error:
            self.notice = str(error)
        self.refresh()

    def delete(self, entry_id, confirmed=False):
        if not confirmed:
            self.confirm_delete = entry_id
        else:
            try:
                model.delete_entry(self.gui.config, entry_id)
                self.notice = "Команда удалена."
            except (ValueError, OSError) as error:
                self.notice = str(error)
            self.confirm_delete = None
        self.refresh()

    def check(self, e=None):
        self.capture()
        try:
            entry = model.validate_entry(self.draft, self.gui.config.get("wake_words", []))
            text = model.clean_phrase(self.test_field.value or "", self.gui.config.get("wake_words", []))
            from jarvis.intents.fast.custom import load_custom, find_custom
            # Same pure matcher as the live pipeline, isolated to this draft.
            match = find_custom(load_custom({"custom_commands": [entry]}, include_packs=False), text)
            self.notice = ("Фраза совпала. " + model.describe_steps(entry["steps"]) + ". Ничего не выполнено." if match
                           else "Точного совпадения нет. Ничего не выполнено.")
        except ValueError as error:
            self.notice = str(error)
        self.fields = None
        self.refresh()

    def set_password(self, e=None):
        # Password controls are never captured in draft and are not prefilled from config.
        value, confirm = self.password_field.value or "", self.password_confirm.value or ""
        self.password_field.value = self.password_confirm.value = ""
        self.capture()
        if len(value) < 4 or len(value) > 128 or value != confirm or value != value.strip():
            self.notice = "Пароли должны совпадать: 4–128 символов, без пробелов по краям."
        else:
            from jarvis.intents.password import hash_password
            self.notice = ("Пароль сохранён. Системные команды будут запрашивать его перед исполнением."
                           if self.gui.config.set("danger_password", hash_password(value))
                           else "Пароль не сохранён: ошибка записи конфигурации.")
        self.fields = None
        self.refresh()

    def build(self):
        from jarvis.gui import P, TEXT, TEXT_DIM, BG_CARD, BG_DARK, ACCENT
        self.notice_text = ft.Text(self.notice, color=TEXT, size=14, selectable=True)
        header = ft.Row([
            ft.Column([ft.Text("Мои команды", size=28, weight=ft.FontWeight.BOLD, color=TEXT),
                       ft.Text("Своя фраза. Свои действия. Без кода и LLM.", size=14, color=TEXT_DIM)],
                      expand=True, spacing=6),
            _button("Новая команда", icon=ft.Icons.ADD, height=44,
                      on_click=lambda e: self.new()),
        ], spacing=16)
        controls = [header]
        if self.notice and self.draft is None:
            controls.append(ft.Container(self.notice_text, padding=12, bgcolor=P.selected, border_radius=8))
        if self.draft is None:
            try:
                entries = model.entries(self.gui.config)
            except ValueError as error:
                entries = []
                controls.append(ft.Text(str(error), color=P.error))
            controls.append(ft.Text("НАЧАТЬ С ПРИМЕРА", size=12, color=P.brand))
            templates = [
                ("Фокус · 25 минут", {"name": "Сосредоточиться", "phrases": ["время сосредоточиться"],
                                      "steps": [{"action": "set_timer", "seconds": 1500}]}),
                ("Тихий вечер", {"name": "Тихий вечер", "phrases": ["тихий вечер"],
                                "steps": [{"action": "set_volume", "percent": 20}]}),
                ("Спокойной ночи", {"name": "Спокойной ночи", "phrases": ["спокойной ночи"],
                                    "steps": [{"action": "shutdown_pc", "seconds": 30}]}),
            ]
            controls.append(ft.Row([_button(label, height=44, on_click=lambda e, t=t: self.new(t))
                                    for label, t in templates], wrap=True, spacing=8))
            controls.append(ft.Text(f"Сохранено: {len(entries)} · команды общие для профилей", size=13, color=TEXT_DIM))
            if not entries:
                controls.append(ft.Container(ft.Column([
                    ft.Icon(ft.Icons.ACCOUNT_TREE_OUTLINED, size=32, color=P.brand),
                    ft.Text("Пусть Феникс понимает твои привычки", size=21, color=TEXT),
                    ft.Text("Например: «спокойной ночи» — выключить ПК через 30 секунд.\n"
                            "Выбери пример или создай команду с нуля. Сохранение не запускает действия.",
                            size=14, color=TEXT_DIM)], spacing=12),
                    padding=24, bgcolor=BG_CARD, border_radius=12, border=ft.Border.all(1, P.border)))
            for entry in entries:
                managed = entry.get("builder_version") == 1
                title = str(entry.get("name") or "Команда из config.json")
                phrases = entry.get("phrases", [])
                description = model.describe_steps(entry.get("steps", [])) if managed else "Старый формат · редактирование в config.json"
                row = [ft.Column([ft.Text(title, size=17, weight=ft.FontWeight.W_600, color=TEXT),
                                  ft.Text(" / ".join(str(x) for x in phrases), size=14, color=P.brand),
                                  ft.Text(description, size=13, color=TEXT_DIM)], spacing=6, expand=True)]
                if managed:
                    row += [ft.Switch(value=entry.get("enabled", True), tooltip="Включить команду",
                                      on_change=lambda e, x=entry: self.toggle(x, e.control.value)),
                            ft.IconButton(icon_color=TEXT_DIM, icon=ft.Icons.EDIT_OUTLINED, tooltip="Редактировать команду",
                                          on_click=lambda e, x=entry: self.edit(x)),
                            ft.IconButton(icon_color=TEXT_DIM, icon=ft.Icons.DELETE_OUTLINE, tooltip="Удалить команду",
                                          on_click=lambda e, i=entry.get("id"): self.delete(i))]
                content = [ft.Row(row, spacing=8)]
                if self.confirm_delete == entry.get("id") and managed:
                    content.append(ft.Row([ft.Text("Удалить без возможности восстановления?", color=P.warning, expand=True),
                                           _button("Удалить", on_click=lambda e, i=entry["id"]: self.delete(i, True)),
                                           _button("Оставить", on_click=lambda e: self._keep())], wrap=True))
                controls.append(ft.Container(ft.Column(content), padding=16, bgcolor=BG_CARD,
                                             border=ft.Border.all(1, P.border), border_radius=12))
        else:
            controls.append(_button("К списку (без сохранения)", on_click=self.back))
            name = _field(label="Название", value=self.draft.get("name", ""), expand=True, max_length=80)
            phrases = _field(expand=True, label="Фразы запуска · каждая с новой строки", multiline=True, min_lines=2, max_lines=5,
                                   value="\n".join(self.draft.get("phrases", [])),
                                   helper=ft.Text("Обращение «Феникс» можно не писать. Совпадение точное, без догадок.", color=TEXT_DIM, size=12))
            enabled = ft.Switch(label="Включена", value=self.draft.get("enabled", True))
            self.fields = {"name": name, "phrases": phrases, "enabled": enabled}
            controls += [ft.Row([name, enabled], spacing=16), ft.Row([phrases]),
                         ft.Text("ДЕЙСТВИЯ · ДО 6 ШАГОВ", size=12, color=P.brand)]
            self.step_fields = []
            for index, step in enumerate(self.draft["steps"]):
                action = step["action"]
                dropdown = ft.Dropdown(label=f"Шаг {index + 1}", value=action, width=245, text_size=14,
                                       options=[ft.dropdown.Option(k, v[0]) for k, v in model.ACTIONS.items()],
                                       on_select=lambda e, i=index: self.change_step(i, e.control.value))
                _, hint, key = model.ACTIONS[action]
                parameter = _field(label=hint or "Без параметров", width=245,
                                         value=str(step.get(key, "")) if key else "", disabled=key is None,
                                         on_change=lambda e: None)
                self.step_fields.append((dropdown, parameter))
                controls.append(ft.Container(ft.Row([
                    dropdown, parameter,
                    ft.Row([ft.IconButton(icon_color=TEXT_DIM, icon=ft.Icons.ARROW_UPWARD, tooltip="Выше", disabled=index == 0,
                                          on_click=lambda e, i=index: self.move_step(i, -1)),
                            ft.IconButton(icon_color=TEXT_DIM, icon=ft.Icons.ARROW_DOWNWARD, tooltip="Ниже", disabled=index == len(self.draft["steps"])-1,
                                          on_click=lambda e, i=index: self.move_step(i, 1)),
                            ft.IconButton(icon_color=TEXT_DIM, icon=ft.Icons.CLOSE, tooltip="Удалить шаг", disabled=len(self.draft["steps"]) == 1,
                                          on_click=lambda e, i=index: self.remove_step(i))], spacing=0),
                ], wrap=True, spacing=12, run_spacing=12), padding=16, bgcolor=BG_CARD,
                    border_radius=12, border=ft.Border.all(1, P.border)))
            controls.append(_button("Добавить действие", icon=ft.Icons.ADD, height=44,
                                      disabled=len(self.draft["steps"]) >= 6, on_click=self.add_step))
            if any(s.get("action") in model.POWER_ACTIONS for s in self.draft["steps"]):
                controls.append(ft.Text("Системное действие требует пароля перед запуском. Проверяется весь сценарий ДО первого шага.\n"
                                        "Выключение / перезагрузка — только последним шагом, с задержкой. Отмена: «отмени выключение».",
                                        color=P.warning, size=14))
            self.test_field = _field(expand=True, label="Проверить фразу без исполнения", hint_text="Феникс, моя фраза")
            controls += [ft.Divider(color=P.border), ft.Row([self.test_field]),
                         ft.Row([_button("Проверить фразу", icon=ft.Icons.RULE, on_click=self.check)], wrap=True),
                         ft.Text("Параметры фиксированы. Шаги идут по порядку; это не транзакция с откатом.\n"
                                 "Не назначай существующие встроенные команды: они могут иметь приоритет в pipeline.",
                                 size=13, color=TEXT_DIM)]
        # Same protection in both views, so a power-action template is usable without leaving the draft.
        self.password_field = _field(label="Новый пароль опасных действий", password=True,
                                           can_reveal_password=False, autocorrect=False, enable_suggestions=False)
        self.password_confirm = _field(label="Повтори пароль", password=True,
                                             can_reveal_password=False, autocorrect=False, enable_suggestions=False)
        controls.append(ft.ExpansionTile(title=ft.Text("Защита системных действий", color=TEXT),
            subtitle=ft.Text("Пароль задан" if self.gui.config.get("danger_password") else "Пароль не задан · выключение недоступно", color=TEXT_DIM),
            controls=[ft.Container(ft.Column([self.password_field, self.password_confirm,
                _button("Сохранить пароль", on_click=self.set_password),
                ft.Text("Хранится SHA-256, как в существующем механизме. В сценарий и историю пароль не попадает.", size=12, color=TEXT_DIM)], spacing=12), padding=16)]))
        scroll = ft.Column(controls, spacing=20, scroll=ft.ScrollMode.AUTO, expand=True)
        body = scroll
        if self.draft is not None:
            self.notice_text.max_lines = 3
            self.notice_text.tooltip = self.notice
            self.notice_text.visible = bool(self.notice)
            body = ft.Column([scroll, ft.Divider(color=P.border), self.notice_text,
                ft.Row([_button("Сохранить команду", icon=ft.Icons.SAVE_OUTLINED,
                                bgcolor="#e9ad79", color="#241b14", on_click=self.save),
                        _button("Отменить правки", on_click=self.back)], wrap=True)], spacing=12, expand=True)
        return ft.Container(body, padding=28, bgcolor=BG_DARK, expand=True)

    def _keep(self):
        self.confirm_delete = None
        self.refresh()
