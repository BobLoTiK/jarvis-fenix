"""One bootstrap window. Presentation only: no downloads, pip or process control.

Tk is lazy-imported and bundled by PyInstaller; Flet is not needed for setup.
The worker owns downloads/processes; UI only presents questions and model choices.
"""
from __future__ import annotations
import os
import logging
from pathlib import Path
import queue
import threading
import time


class PreparationFailed(Exception):
    pass


class Question:
    def __init__(self, text, title, yes, no):
        self.text, self.title, self.yes, self.no = text, title, yes, no
        self.ready = threading.Event()
        self.answer = False

    def resolve(self, answer):
        self.answer = bool(answer)
        self.ready.set()


class ModelQuestion:
    """Choice data only; worker waits, Tk thread resolves a model name or None."""
    def __init__(self, title, text, options):
        self.title, self.text = title, text
        self.options = tuple(dict(o) for o in options)
        if not self.options or len({o['value'] for o in self.options}) != len(self.options):
            raise ValueError('Invalid model options')
        self.ready = threading.Event()
        self.answer = None

    def resolve(self, value):
        if value is not None and value not in {o['value'] for o in self.options}:
            raise ValueError('Unknown model choice')
        self.answer = value
        self.ready.set()


class Session:
    """A queue boundary, not an installer engine. No widget access from workers."""
    def __init__(self):
        self.events = queue.Queue()
        self.last_error = ''
        self.declined = False
        self.notice = ''
        self._last_progress = 0.0

    def emit(self, kind, **data):
        self.events.put((kind, data))

    def stage(self, title, detail='', show=False):
        self.emit('stage', title=title, detail=detail, show=show)

    def detail(self, text):
        self.emit('detail', text=str(text))

    def ask(self, text, title, yes='Продолжить', no='Не сейчас'):
        question = Question(text, title, yes, no)
        self.emit('question', question=question)
        question.ready.wait()
        return question.answer

    def choose_model(self, title, text, options):
        question = ModelQuestion(title, text, options)
        self.emit('model_choice', question=question)
        question.ready.wait()
        return question.answer

    def progress_update(self, value, text):
        now = time.monotonic()
        if value not in (None, 0, 1) and now - self._last_progress < .1:
            return
        if value is None and getattr(self, '_last_progress_text', None) == text and now - self._last_progress < .1:
            return
        self._last_progress, self._last_progress_text = now, text
        self.emit('progress', value=value, text=text)

    def download_progress(self, block, block_size, total):
        received = max(0, block*block_size)
        if total > 0:
            received = min(received,total)
        now = time.monotonic()
        complete = total > 0 and received >= total
        if block and not complete and now-self._last_progress < .1:
            return
        self._last_progress = now
        self.emit('progress', value=received/total if total > 0 else None,
                  text=f'{received/1048576:.1f} МБ' +
                  (f' из {total/1048576:.1f} МБ' if total > 0 else ' загружено'))


class StageLogHandler(logging.Handler):
    """Translate existing launcher logs to stage labels without changing its work."""
    STAGES = (
        ('Лаунчер стартует', 'Проверяем установку', 'Ищем Python 3.11 и проверяем окружение.', False),
        ('Создаю venv:', 'Создаём окружение', 'Изолированная .venv311 для этой установки Феникса.', True),
        ('pip install -r', 'Устанавливаем зависимости', 'pip загружает и устанавливает недостающие пакеты. Общий процент неизвестен; подготовка может занять несколько минут.', True),
        ('Скачиваю installer:', 'Загружаем Python', 'Официальный установщик Python 3.11.', True),
        ('Запускаю installer:', 'Установка Python', 'Заверши или отмени установку в отдельном окне официального установщика.', True),
        ('Скачиваю Vosk:', 'Загружаем распознавание', 'Модель Vosk для русской речи.', True),
        ('Распаковываю Vosk', 'Распаковываем модель', 'Подготавливаем файлы распознавания.', True),
        ('Запускаю Феникс:', 'Запускаем Феникса', 'Передаём управление приложению.', False),
    )

    def __init__(self, session):
        super().__init__()
        self.session = session

    def emit(self, record):
        try:
            message = record.getMessage()
            for prefix, title, detail, show in self.STAGES:
                if message.startswith(prefix):
                    self.session.stage(title, detail, show=show)
                    break
        except Exception:
            self.handleError(record)


class PreparationWindow:
    BG='#12121c'; CARD='#1d1e2d'; TEXT='#eeedf7'; DIM='#abaac1'; GOLD='#d8a786'
    def __init__(self, project_dir, log_file):
        self.project_dir, self.log_file = Path(project_dir), Path(log_file)
        self.worker = None
        self.session = None
        self.question = None
        self.state = 'idle'
        self.progress = None
        self.phase = 0
        self.shown = False

    def _button(self, parent, text, command, primary=False):
        bg = self.GOLD if primary else '#343149'
        fg = '#282b30' if primary else self.TEXT
        return self.tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
            activebackground='#e4b995' if primary else '#45405c', activeforeground=fg,
            relief='flat', borderwidth=0, highlightthickness=1,
            highlightbackground=self.BG, highlightcolor=self.GOLD,
            padx=18, pady=10, cursor='hand2', font=('Segoe UI',10), takefocus=True)

    def _build(self):
        import tkinter as tk
        self.tk = tk
        if os.name == 'nt':
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (OSError, AttributeError):
                pass
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Phoenix.Bootstrap')
            except (OSError, AttributeError):
                pass
        root = self.root = tk.Tk()
        root.withdraw()
        root.title('Феникс — подготовка')
        root.configure(bg=self.BG)
        root.resizable(False, False)
        icon = self.project_dir/'jarvis/icon.ico'
        if icon.is_file():
            try:
                root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        shell = tk.Frame(root, bg=self.BG, padx=30, pady=24)
        shell.pack(fill='both', expand=True)
        header = tk.Frame(shell, bg=self.BG)
        header.pack(fill='x')
        tk.Label(header, text='ФЕНИКС / ПОДГОТОВКА', bg=self.BG, fg=self.GOLD,
                 font=('Segoe UI',10,'bold'), anchor='w').pack(side='left')
        mark = self.project_dir/'jarvis/assets/brand/phoenix-dark.png'
        if mark.is_file():
            try:
                image = tk.PhotoImage(file=str(mark))
                self.mark_image = image.subsample(max(1,(image.width()+47)//48))
                tk.Label(header,image=self.mark_image,bg=self.BG).pack(side='right')
            except tk.TclError:
                pass
        tk.Label(shell, text='Всё начинается здесь.', bg=self.BG, fg=self.TEXT,
                 font=('Segoe UI',24,'bold'), anchor='w').pack(fill='x', pady=(16,6))
        tk.Label(shell, text='Подготовим компоненты — и откроем приложение.',
                 bg=self.BG, fg=self.DIM, font=('Segoe UI',10), anchor='w').pack(fill='x')
        card = tk.Frame(shell, bg=self.CARD, padx=18, pady=16)
        card.pack(fill='x', pady=(20,16))
        self.stage_label = tk.Label(card, text='Проверяем установку…', bg=self.CARD,
            fg=self.TEXT, font=('Segoe UI',13,'bold'), anchor='w', wraplength=540, justify='left')
        self.stage_label.pack(fill='x')
        self.detail_text = tk.Text(card, width=66, height=8, bg=self.CARD, fg=self.DIM,
            font=('Segoe UI',10), wrap='word', relief='flat', borderwidth=0,
            highlightthickness=0, state='disabled', takefocus=True)
        self.detail_text.pack(fill='x', pady=(10,12))
        self.choice_frame = tk.Frame(card, bg=self.CARD)
        self.model_choice = None
        self.bar = tk.Canvas(card, bg=self.CARD, height=6, highlightthickness=0, width=540)
        self.bar.pack(fill='x')
        self.progress_label = tk.Label(card, text='Проверка компонентов', bg=self.CARD,
            fg=self.DIM, font=('Segoe UI',9), anchor='w')
        self.progress_label.pack(fill='x', pady=(8,0))
        controls = tk.Frame(shell, bg=self.BG)
        controls.pack(fill='x')
        self.cancel_button = self._button(controls, 'Дождись завершения', self._secondary)
        self.cancel_button.pack(side='right')
        self.primary_button = self._button(controls, 'Продолжить', self._primary, True)
        self.primary_button.pack(side='right', padx=(0,8))
        self.primary_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled')
        self.log_button = self._button(controls, 'Журнал', self._open_log)
        self.log_button.pack(side='left')
        tk.Label(shell, text='Активная установка не прерывается. Отказ — до начала этапа.',
                 bg=self.BG, fg=self.DIM, font=('Segoe UI',9), anchor='w').pack(fill='x', pady=(12,0))
        root.protocol('WM_DELETE_WINDOW', self._secondary)
        root.bind('<Escape>', lambda _: self._secondary())
        def enter(_):
            button = root.focus_get()
            if isinstance(button, tk.Button):
                button.invoke()
            else:
                self.primary_button.invoke()
        root.bind('<Return>', enter)
        root.update_idletasks()
        width, height = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry(f'+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2)}')
        root.after(40,self._tick)

    def _detail(self, text):
        self.detail_text.configure(state='normal')
        self.detail_text.delete('1.0','end')
        self.detail_text.insert('1.0',str(text))
        self.detail_text.configure(state='disabled')

    def _show(self):
        if not self.shown:
            self.shown = True
            self.root.deiconify()
            self.root.lift()

    def _open_log(self):
        try:
            os.startfile(self.log_file)
        except (OSError,AttributeError):
            self._detail(f'Журнал: {self.log_file}')

    def _clear_choices(self):
        frame = getattr(self, 'choice_frame', None)
        if frame is not None:
            for child in frame.winfo_children():
                child.destroy()
            frame.pack_forget()
        self.model_choice = None

    def _build_model_choices(self):
        from tkinter import ttk
        self._clear_choices()
        options = self.question.options
        self.model_choice = ttk.Combobox(
            self.choice_frame, state='readonly', height=8,
            values=[o['label'] for o in options], font=('Segoe UI', 10))
        self.model_choice.current(0)
        self.model_choice.pack(fill='x', pady=(0, 12))
        self.model_choice.bind('<<ComboboxSelected>>', self._choice_changed)
        self.choice_frame.pack(fill='x', before=self.bar)
        self._choice_changed()

    def _choice_changed(self, _=None):
        index = self.model_choice.current()
        installed = self.question.options[index].get('installed', False)
        self.primary_button.configure(text='Использовать модель' if installed else 'Скачать и использовать')

    def _busy(self):
        self._clear_choices()
        self.state = 'busy'
        self.primary_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled', text='Дождись завершения')
        self.progress = None
        self.progress_label.configure(text='Выполняется…')

    def _primary(self):
        if self.state == 'model_choice' and self.question is not None:
            index = self.model_choice.current()
            question, self.question = self.question, None
            value = question.options[index]['value']
            self._busy()
            question.resolve(value)
        elif self.state == 'question' and self.question is not None:
            question, self.question = self.question, None
            self._busy()
            question.resolve(True)
        elif self.state == 'failed':
            self.state = 'retry_pending'
            self.primary_button.configure(state='disabled')
            self.cancel_button.configure(state='disabled')
            self._start()

    def _secondary(self):
        if self.state == 'model_choice' and self.question is not None:
            question, self.question = self.question, None
            self._busy()
            question.resolve(None)
        elif self.state == 'question' and self.question is not None:
            question, self.question = self.question, None
            self._busy()
            question.resolve(False)
        elif self.state in ('failed','notice','idle'):
            self.root.destroy()
        else:
            self._detail('Этот этап уже выполняется. Дождись его завершения; принудительная остановка здесь отключена.')

    def _start(self):
        if self.worker is not None and self.worker.is_alive():
            self.root.after(80,self._start)
            return
        self.session = Session()
        self.question = None
        self._busy()
        def work():
            try:
                self.job(self.session)
                if self.session.last_error:
                    raise PreparationFailed(self.session.last_error)
            except Exception as exc:
                import logging
                logging.getLogger('launcher').exception('Подготовка не завершена')
                self.session.emit('finished',status='failed',text=str(exc) or 'Подробности в журнале.')
            else:
                self.session.emit('finished',status='notice' if self.session.notice else 'ok',text=self.session.notice)
        self.worker = threading.Thread(target=work,name='phoenix-bootstrap',daemon=False)
        self.worker.start()

    def _event(self, kind, data):
        if kind == 'finished':
            self._clear_choices()
            self.question = None
            self.state = data['status']
            if self.state == 'ok':
                self.root.destroy()
                return False
            self._show()
            self.progress = 0
            self.stage_label.configure(text='Не удалось завершить подготовку' if self.state=='failed' else 'Феникс уже работает')
            self._detail(data.get('text',''))
            self.progress_label.configure(text='Подробности доступны в журнале')
            self.primary_button.configure(text='Повторить',state='normal' if self.state=='failed' else 'disabled')
            self.cancel_button.configure(text='Закрыть',state='normal')
        elif kind == 'stage':
            self.stage_label.configure(text=data['title'])
            self._detail(data['detail'])
            self.progress = None
            self.progress_label.configure(text='Выполняется…')
            if data['show']:
                self._show()
        elif kind == 'detail':
            self._detail(data['text'])
        elif kind == 'progress':
            self.progress = data['value']
            self.progress_label.configure(text=data['text'])
        elif kind == 'model_choice':
            self.question = data['question']
            self.state = 'model_choice'
            self._show()
            self.stage_label.configure(text=self.question.title)
            self._detail(self.question.text)
            self.progress = 0
            self.progress_label.configure(text='Загрузка — только после нажатия кнопки. Размеры примерные.')
            self.primary_button.configure(state='normal')
            self.cancel_button.configure(text='Продолжить без ИИ', state='normal')
            self._build_model_choices()
            self.primary_button.focus_set()
        elif kind == 'question':
            self.question = data['question']
            self.state = 'question'
            self._show()
            self.stage_label.configure(text=self.question.title)
            self._detail(self.question.text)
            self.progress = 0
            self.progress_label.configure(text='Продолжение только с твоего согласия')
            self.primary_button.configure(text=self.question.yes,state='normal')
            self.cancel_button.configure(text=self.question.no,state='normal')
            self.primary_button.focus_set()
        return True

    def _tick(self):
        for _ in range(60):
            try:
                kind,data = self.session.events.get_nowait()
            except queue.Empty:
                break
            if not self._event(kind,data):
                return
        width = max(1,self.bar.winfo_width())
        self.bar.delete('all')
        self.bar.create_rectangle(0,0,width,6,fill='#343149',outline='')
        if self.progress is None and self.state == 'busy':
            self.phase = (self.phase+.018)%1
            span = width*.24
            left = self.phase*(width+span)-span
            self.bar.create_rectangle(max(0,left),0,min(width,left+span),6,fill=self.GOLD,outline='')
        elif self.progress is not None:
            self.bar.create_rectangle(0,0,width*max(0,min(1,self.progress)),6,fill=self.GOLD,outline='')
        self.root.after(40,self._tick)

    def run(self, job):
        self.job = job
        self._build()
        self._start()
        self.root.after(1200,lambda: self._show() if self.state=='busy' else None)
        self.root.mainloop()
        if self.worker is not None:
            self.worker.join()
