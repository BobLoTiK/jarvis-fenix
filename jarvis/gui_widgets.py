"""Opt-in Home widgets: responsive order/size editor, real tasks and guarded shortcuts."""
from copy import deepcopy
from functools import partial

import flet as ft

KINDS = {"tasks": ("Задачи", ft.Icons.CHECKLIST_ROUNDED),
         "shortcuts": ("Быстрые действия", ft.Icons.BOLT_OUTLINED)}
LAYOUT_KEY = "gui_home_widgets"
SHORTCUTS_KEY = "gui_home_shortcuts"


def normalize_layout(value):
    result = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if isinstance(kind, str) and kind in KINDS and not any(w["kind"] == kind for w in result):
                result.append({"kind": kind, "size": "wide" if item.get("size") == "wide" else "compact"})
    return result


def normalize_shortcuts(value):
    result = []
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            label, command = item.get("label"), item.get("command")
            if not isinstance(label, str) or not isinstance(command, str):
                continue
            label, command = label.strip()[:40], command.strip()[:300]
            if label and command and not any(s == {"label": label, "command": command} for s in result):
                result.append({"label": label, "command": command})
            if len(result) == 6:
                break
    return result


class WidgetBoard(ft.Column):
    """No polling task: task-file changes use the existing Home 1 Hz clock tick."""
    def __init__(self, gui, on_layout):
        super().__init__(spacing=12, visible=False)
        self.gui, self.on_layout = gui, on_layout
        self.editing = False
        self._mounted, self._host = False, None
        self._snapshot = None
        self._task_stamp = None
        self._rendering = False
        self._task_draft = ""
        self.layout = normalize_layout(gui.config.get(LAYOUT_KEY, []))
        self.shortcuts = normalize_shortcuts(gui.config.get(SHORTCUTS_KEY, []))
        self.notice = ft.Text("", size=11, visible=False)
        self.task_rows = None
        self.task_summary = None
        self.task_input = None
        self.shortcut_label = ft.TextField(label="Название", max_length=40, dense=True, on_change=self._text_changed)
        self.shortcut_command = ft.TextField(label="Команда Фениксу", max_length=300, dense=True, on_change=self._text_changed,
            hint_text="Например: открой калькулятор")
        self._render()

    def _text_changed(self, e):
        # Subscribe to native TextField changes so Flet syncs values before Save.
        if e.control is self.task_input:
            self._task_draft = e.control.value or ""

    def _palette(self):
        from jarvis import gui
        return gui.P

    def _update(self):
        if self._mounted and self._host is not None and not self._rendering:
            try:
                self._host.update(self)
            except RuntimeError:
                self.dispose()

    def _say(self, message, error=False):
        p = self._palette()
        self.notice.value, self.notice.visible = message, True
        self.notice.color = p.error if error else p.text_dim
        self._update()

    def begin(self):
        if self.editing:
            return
        self._snapshot = {key: deepcopy(self.gui.config.get(key, [])) for key in (LAYOUT_KEY, SHORTCUTS_KEY)}
        self.layout = normalize_layout(self._snapshot[LAYOUT_KEY])
        self.shortcuts = normalize_shortcuts(self._snapshot[SHORTCUTS_KEY])
        self.editing = True
        self.notice.visible = False
        self._render()
        self.on_layout()

    def save(self, e=None):
        if not self.editing:
            return False
        if (self.shortcut_label.value or "").strip() or (self.shortcut_command.value or "").strip():
            self.add_shortcut()
            if (self.shortcut_label.value or "").strip() or (self.shortcut_command.value or "").strip():
                return False
        try:
            ok = self.gui.config.update({LAYOUT_KEY: deepcopy(self.layout), SHORTCUTS_KEY: deepcopy(self.shortcuts)},
                                        expected_values=self._snapshot)
        except Exception:
            ok = False
        if not ok:
            self._say("Не удалось сохранить или настройки изменились в другом месте. Черновик сохранён на экране.", True)
            return False
        self.editing = False
        self._snapshot = None
        self._render()
        self.on_layout()
        return True

    def cancel(self, e=None):
        self.layout = normalize_layout(self.gui.config.get(LAYOUT_KEY, []))
        self.shortcuts = normalize_shortcuts(self.gui.config.get(SHORTCUTS_KEY, []))
        self.editing = False
        self._snapshot = None
        self.notice.visible = False
        self.shortcut_label.value = self.shortcut_command.value = ""
        self._render()
        self.on_layout()

    def add_widget(self, kind, e=None):
        if self.editing and kind in KINDS and not any(w["kind"] == kind for w in self.layout):
            self.layout.append({"kind": kind, "size": "compact"})
            self._render(); self.on_layout()

    def remove_widget(self, kind, e=None):
        if self.editing:
            self.layout = [w for w in self.layout if w["kind"] != kind]
            self._render(); self.on_layout()  # hiding a widget never deletes its data

    def resize_widget(self, kind, e=None):
        if not self.editing:
            return
        for widget in self.layout:
            if widget["kind"] == kind:
                widget["size"] = "compact" if widget["size"] == "wide" else "wide"
        self._render(); self.on_layout()

    def move_widget(self, kind, delta):
        if not self.editing:
            return
        index = next((i for i,w in enumerate(self.layout) if w["kind"] == kind), -1)
        dest = index + delta
        if index >= 0 and 0 <= dest < len(self.layout):
            self.layout.insert(dest, self.layout.pop(index))
            self._render(); self.on_layout()

    def drop(self, target, e):
        source = getattr(getattr(e, "src", None), "data", None)
        if not self.editing or not isinstance(source, str) or source == target or source not in KINDS:
            return
        order = [w["kind"] for w in self.layout]
        if source not in order or target not in order:
            return
        item = self.layout.pop(order.index(source))
        self.layout.insert(order.index(target), item)
        self._render(); self.on_layout()

    def add_shortcut(self, e=None):
        if not self.editing:
            return
        label, command = (self.shortcut_label.value or "").strip(), (self.shortcut_command.value or "").strip()
        if not label or not command or len(label) > 40 or len(command) > 300 or len(self.shortcuts) >= 6:
            self._say("Укажи название и команду. Можно добавить до 6 действий.", True)
            return
        item = {"label": label, "command": command}
        if item in self.shortcuts:
            self._say("Такое действие уже есть.", True)
            return
        self.shortcuts.append(item)
        self.shortcut_label.value = self.shortcut_command.value = ""
        self.notice.visible = False
        self._render(); self.on_layout()

    def remove_shortcut(self, index, e=None):
        if self.editing and 0 <= index < len(self.shortcuts):
            self.shortcuts.pop(index)
            self._render(); self.on_layout()

    def launch(self, index, e=None):
        if self.editing or not (0 <= index < len(self.shortcuts)):
            return False
        core = self.gui.jarvis
        if core is None:
            self._say("Ядро ещё не готово — действие не запущено.", True)
            return False
        handler = getattr(core, "handler", None)
        if getattr(handler, "_pending_password", None) or getattr(handler, "_pending_question", None):
            self._say("Сначала заверши подтверждение в Диалоге.", True)
            return False
        if getattr(self.gui, "_command_busy", False):
            self._say("Феникс ещё выполняет запрос. Дождись завершения.")
            return False
        # Same safety gates/lock/confirmation pipeline as Chat, never shell/exec.
        self.gui._select_tab(0)
        return self.gui._run_command(self.shortcuts[index]["command"])

    def add_task(self, e=None):
        if self.editing or self.task_input is None:
            return False
        text = (self.task_input.value or "").strip()
        if not text or len(text) > 300:
            self._say("Введи задачу длиной от 1 до 300 символов.", True)
            return False
        try:
            from jarvis import tasks
            tasks.add(text)
        except Exception:
            self._say("Не удалось записать задачу. Текст оставлен в поле.", True)
            return False
        self.task_input.value = self._task_draft = ""
        self.notice.visible = False
        self.refresh_tasks(force=True)
        self._update()
        return True

    def set_task_done(self, task_id, e):
        if self.editing:
            return
        try:
            from jarvis import tasks
            if tasks.set_done(task_id, bool(e.control.value)) is None:
                self._say("Эту задачу уже удалили. Список обновлён.")
        except Exception:
            self._say("Не удалось сохранить отметку задачи.", True)
        self.refresh_tasks(force=True)

    def refresh_tasks(self, force=False):
        if self.task_rows is None or not any(w["kind"] == "tasks" for w in self.layout):
            return False
        from jarvis import tasks
        try:
            path = tasks._tasks_file()
            stat = path.stat() if path.exists() else None
            stamp = (stat.st_mtime_ns, stat.st_size) if stat else (None, 0)
            if not force and stamp == self._task_stamp:
                return False
            items = tasks.list_items()
            self._task_stamp = stamp
            p = self._palette()
            items = [t for t in items if isinstance(t,dict) and isinstance(t.get("id"),int)
                     and isinstance(t.get("text"),str)]
            items.sort(key=lambda t:bool(t.get("done")))
            self.task_rows.controls = [ft.Checkbox(label=t["text"], value=bool(t.get("done")),
                disabled=self.editing, on_change=partial(self.set_task_done,t["id"]),
                label_style=ft.TextStyle(size=13,color=p.text_dim if t.get("done") else p.text)) for t in items[:100]]
            if not items:
                self.task_rows.controls = [ft.Text("Пока пусто. Добавь первое дело.",size=12,color=p.text_dim)]
            done = sum(bool(t.get("done")) for t in items)
            self.task_summary.value = f"{done} из {len(items)} завершено" if items else "Одно дело за раз."
            if len(items)>100:
                self.task_summary.value += " · показаны первые 100"
            self._update()
            return True
        except Exception:
            self._say("Не удалось прочитать задачи.", True)
            return False

    def _tasks_card(self, widget):
        p = self._palette()
        self.task_rows = ft.Column(spacing=2,scroll=ft.ScrollMode.AUTO)
        self.task_summary = ft.Text(size=11,color=p.text_dim)
        self.task_input = ft.TextField(value=self._task_draft,hint_text="Добавить задачу…",max_length=300,dense=True,
            expand=True,color=p.text,disabled=self.editing,on_submit=self.add_task,on_change=self._text_changed,
            border_color=p.border,text_size=13)
        content = ft.Column([self.task_summary,
            ft.Container(self.task_rows,height=180 if widget["size"]=="compact" else 240),
            ft.Row([self.task_input,ft.IconButton(icon=ft.Icons.ADD,tooltip="Добавить задачу",
                icon_color=p.brand,disabled=self.editing,on_click=self.add_task)])],spacing=10)
        self.refresh_tasks(force=True)
        return content

    def _shortcuts_card(self):
        p=self._palette()
        rows=[]
        for i, action in enumerate(self.shortcuts):
            if self.editing:
                rows.append(ft.Row([ft.Column([ft.Text(action["label"],size=13,color=p.text),
                    ft.Text(action["command"],size=11,color=p.text_dim,max_lines=2)],expand=True),
                    ft.IconButton(icon=ft.Icons.CLOSE,tooltip="Убрать действие",icon_color=p.text_dim,
                                  on_click=partial(self.remove_shortcut,i))]))
            else:
                rows.append(ft.Button(action["label"],icon=ft.Icons.NORTH_EAST_ROUNDED,
                    tooltip=action["command"],on_click=partial(self.launch,i),color=p.text,bgcolor=p.selected,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=9)),height=42))
        if not rows:
            rows=[ft.Text("Добавь свои команды в режиме настройки.",size=12,color=p.text_dim)]
        if self.editing:
            for field in (self.shortcut_label,self.shortcut_command):
                field.color=p.text;field.border_color=p.border;field.text_size=13
            rows.extend([self.shortcut_label,self.shortcut_command,
                ft.Button("Добавить действие",icon=ft.Icons.ADD,on_click=self.add_shortcut,
                          color=p.brand,disabled=len(self.shortcuts)>=6),
                ft.Text("Запуск — через Диалог с обычными проверками безопасности.",size=11,color=p.text_dim)])
        return ft.Column(rows,spacing=10)

    def capture(self):
        return dict(layout=deepcopy(self.layout), shortcuts=deepcopy(self.shortcuts), editing=self.editing,
            snapshot=deepcopy(self._snapshot), task_draft=self.task_input.value if self.task_input else self._task_draft,
            label=self.shortcut_label.value, command=self.shortcut_command.value)

    def restore(self, state):
        self.layout=normalize_layout(state["layout"])
        self.shortcuts=normalize_shortcuts(state["shortcuts"])
        self.editing=bool(state["editing"])
        self._snapshot=deepcopy(state["snapshot"])
        self._task_draft=state.get("task_draft") or ""
        if self.task_input is not None:
            self.task_input.value=self._task_draft
        self.shortcut_label.value=state.get("label") or ""
        self.shortcut_command.value=state.get("command") or ""
        self._render()
        self.on_layout()

    def _render(self):
        self._rendering = True
        if self.task_input is not None:
            self._task_draft = self.task_input.value or ""
        p=self._palette()
        self.visible = bool(self.layout) or self.editing
        self.task_rows = None
        cards=[]
        for index, widget in enumerate(self.layout):
            kind=widget["kind"]; title,icon=KINDS[kind]
            heading=[ft.Icon(icon,size=19,color=p.brand),ft.Text(title,size=15,weight=ft.FontWeight.W_600,color=p.text,expand=True)]
            if self.editing:
                handle=ft.Draggable(group="phoenix-home-widgets",data=kind,
                    content=ft.Icon(ft.Icons.DRAG_INDICATOR,size=19,color=p.text_dim),
                    content_feedback=ft.Container(ft.Text(title,color=p.text),bgcolor=p.selected,padding=14,border_radius=10))
                heading.insert(0,handle)
                heading.extend([ft.IconButton(icon=ft.Icons.ARROW_UPWARD,tooltip="Передвинуть раньше",icon_size=16,
                    disabled=index==0,on_click=lambda e,k=kind:self.move_widget(k,-1)),
                    ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD,tooltip="Передвинуть дальше",icon_size=16,
                    disabled=index==len(self.layout)-1,on_click=lambda e,k=kind:self.move_widget(k,1))])
            body=self._tasks_card(widget) if kind=="tasks" else self._shortcuts_card()
            controls=[ft.Row(heading,spacing=7),body]
            if self.editing:
                controls.append(ft.Row([
                    ft.Button("Компактнее" if widget["size"]=="wide" else "Расширить",icon=ft.Icons.ASPECT_RATIO,
                        on_click=partial(self.resize_widget,kind),color=p.brand),
                    ft.IconButton(icon=ft.Icons.CLOSE,tooltip="Убрать виджет, не удаляя данные",
                        icon_color=p.text_dim,on_click=partial(self.remove_widget,kind))],alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
            card=ft.Container(ft.Column(controls,spacing=16),padding=18,bgcolor=p.bg_card,border_radius=14,
                border=ft.Border.all(1,p.border))
            target=ft.DragTarget(content=card,group="phoenix-home-widgets",on_accept=partial(self.drop,kind)) if self.editing else card
            cards.append(ft.Container(target,col=12 if widget["size"]=="wide" else {"xs":12,"lg":6}))
        toolbar=[]
        if self.editing:
            toolbar=[ft.Row([ft.Text("Твоё пространство",size=17,weight=ft.FontWeight.W_600,color=p.text,expand=True),
                ft.Button("Отмена",on_click=self.cancel,color=p.text_dim),
                ft.Button("Сохранить",on_click=self.save,color=p.bg_main,bgcolor=p.brand)]),
                ft.Text("Добавь виджеты. Перетащи за ручку или поменяй порядок стрелками.",size=12,color=p.text_dim),
                ft.Row([ft.Button(title,icon=icon,on_click=partial(self.add_widget,kind),color=p.brand,
                    disabled=any(w["kind"]==kind for w in self.layout)) for kind,(title,icon) in KINDS.items()],wrap=True)]
        self.controls=[*toolbar,self.notice,ft.ResponsiveRow(cards,spacing=16,run_spacing=16)]
        self._rendering = False
        self._update()

    def did_mount(self):
        self._mounted,self._host=True,self.page

    def will_unmount(self):
        self.dispose()

    def dispose(self):
        self._mounted=False;self._host=None
