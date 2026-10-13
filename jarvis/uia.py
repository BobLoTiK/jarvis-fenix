"""UI Automation — видим окна и элементы интерфейса.

Обёртка над `uiautomation` (Windows UIA через COM).

Что умеем:
    - Найти окно по части заголовка.
    - Прочитать весь видимый текст активного окна.
    - Прочитать URL активной вкладки браузера.
    - Нажать кнопку по имени.
    - Закрыть вкладку браузера.
    - Переключиться на вкладку по имени.
    - Понимать русские названия сайтов: «ютуб» находит вкладку «YouTube»
      (алиасы + транслитерация, `title_matches`).

Всё через `uiautomation`, thread-safe через RLock (COM не любит
многопоточность без инициализации).

ВАЖНО: UIA требует STA (Single-Threaded Apartment). Первый вызов
в потоке инициализирует COM. Не дёргать из разных потоков без
`uiautomation.InitializeUIAutomationInCurrentThread()`.
"""

import logging
import re
import threading
import time

log = logging.getLogger("jarvis.uia")

_lock = threading.RLock()

# Ленивая инициализация uiautomation.
_uia = None

# Подсказка человеку: что делать, если библиотеки нет.
UIA_PIP_HINT = "pip install uiautomation"


class UIAUnavailable(ImportError):
    """Нет библиотеки `uiautomation` — Windows UI Automation недоступна.

    Наследник ImportError: старый код (и тесты) продолжают ловить именно
    ImportError, а быстрые команды (`jarvis/intents/fast/uia.py`) ловят
    `UIAUnavailable` и отвечают понятной фразой вместо падения в LLM.

    Типичный случай — CI-раннер: в `requirements-ci.txt` библиотеки нет.
    """


def _ensure_init():
    """Ленивая инициализация UIA в текущем потоке."""
    global _uia
    if _uia is None:
        try:
            import uiautomation as auto
            _uia = auto
            log.info("UIA инициализирован")
        except ImportError as exc:
            log.error("uiautomation не установлен. %s", UIA_PIP_HINT)
            raise UIAUnavailable(
                f"не установлена библиотека uiautomation ({UIA_PIP_HINT})"
            ) from exc
    return _uia


# =================================================================
# Типы контролов UIA
# =================================================================
# Внимание: у модуля `uiautomation` НЕТ атрибута `ControlTypeName`
# (есть `ControlTypes`, `ControlTypeNames` и числовой `ControlType`).
# Обращение `uia.ControlTypeName.ButtonControl` бросало AttributeError,
# а он глотался `except Exception` внутри обходов дерева — из-за этого
# «закрой вкладку ютуб» не находила НИ ОДНОЙ вкладки: всегда «не нашёл».
# Сравниваем по имени типа у самого контрола: оно строковое и стабильное.

def _is_control_type(ctrl, type_name: str) -> bool:
    """Контрол нужного типа? («TabItemControl», «ButtonControl», ...)"""
    try:
        return (ctrl.ControlTypeName or "") == type_name
    except Exception:
        return False


def _is_tab_item(ctrl) -> bool:
    """Это вкладка браузера?"""
    return _is_control_type(ctrl, "TabItemControl")


def _is_button(ctrl) -> bool:
    """Это кнопка?"""
    return _is_control_type(ctrl, "ButtonControl")


def _is_menu_item(ctrl) -> bool:
    """Это пункт меню?"""
    return _is_control_type(ctrl, "MenuItemControl")


# =================================================================
# Поиск окна
# =================================================================

def find_window(title_part: str, timeout: float = 2.0):
    """Находит окно по части заголовка. None, если не нашёл."""
    uia = _ensure_init()
    title_low = title_part.lower()

    with _lock:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for w in uia.GetRootControl().GetChildren():
                    try:
                        name = (w.Name or "").strip()
                        if name and title_low in name.lower():
                            return w
                    except Exception:
                        continue
            except Exception:
                log.exception("find_window: обход окон упал")
                return None
            time.sleep(0.1)
    return None


def get_active_window():
    """Возвращает активное окно или None."""
    uia = _ensure_init()
    try:
        with _lock:
            return uia.GetForegroundControl()
    except Exception:
        log.exception("get_active_window упал")
        return None


def get_active_window_title() -> str:
    """Заголовок активного окна."""
    w = get_active_window()
    if w is None:
        return ""
    try:
        return (w.Name or "").strip()
    except Exception:
        return ""


# =================================================================
# Чтение текста
# =================================================================

def read_active_text(max_chars: int = 4000) -> str:
    """Читает весь видимый текст активного окна.

    Обходим дерево через _walk_controls (рекурсия по GetChildren).
    """
    uia = _ensure_init()
    w = get_active_window()
    if w is None:
        return ""

    texts: list[str] = []
    total = 0

    with _lock:
        for ctrl in _walk_controls(w, depth=20):
            if total >= max_chars:
                break
            try:
                ct = ctrl.ControlType
                if ct not in (uia.ControlType.EditControl,
                              uia.ControlType.DocumentControl,
                              uia.ControlType.TextControl):
                    continue
                if ctrl.IsValuePatternAvailable():
                    val = ctrl.GetValuePattern().Value
                else:
                    val = ctrl.Name
                if val:
                    val = val.strip()
                    if val and val not in texts:
                        texts.append(val)
                        total += len(val)
            except Exception:
                continue

    result = "\n".join(texts)
    if len(result) > max_chars:
        result = result[:max_chars] + "..."
    return result


def read_active_text_stripped(max_chars: int = 2000) -> str:
    """read_active_text + склеивание пробелов."""
    text = read_active_text(max_chars=max_chars)
    return re.sub(r"\s+", " ", text).strip()


# =================================================================
# Кнопки
# =================================================================

def click_button(name_part: str, window_title: str | None = None,
                 timeout: float = 2.0) -> bool:
    """Нажимает кнопку по части имени.

    window_title — если задан, ищем кнопку только в этом окне.
    Иначе — в активном.
    """
    uia = _ensure_init()
    name_low = name_part.lower()

    with _lock:
        window = (find_window(window_title) if window_title
                  else get_active_window())
        if window is None:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for ctrl in window.GetChildren():
                    for c in _walk_controls(ctrl, depth=10):
                        try:
                            if not _is_button(c):
                                continue
                            cname = (c.Name or "").strip().lower()
                            if name_low in cname:
                                c.GetInvokePattern().Invoke()
                                log.info("Нажал кнопку %r", c.Name)
                                return True
                        except Exception:
                            continue
            except Exception:
                pass
            time.sleep(0.1)
    return False


def _walk_controls(root, depth: int = 15):
    """Рекурсивно обходит контролы. Ловит исключения на каждом уровне."""
    if depth <= 0:
        return
    try:
        children = root.GetChildren()
    except Exception:
        return
    for c in children:
        yield c
        yield from _walk_controls(c, depth=depth - 1)


# =================================================================
# Браузеры — определяем по процессам, а не по заголовку окна.
# Так работает и в Chrome, и в Edge, Opera, Brave, Vivaldi, Arc, ...
# =================================================================

# Известные браузерные процессы (имя .exe в нижнем регистре).
_BROWSER_PROCESSES = {
    "chrome.exe":              "Chrome",
    "msedge.exe":              "Edge",
    "firefox.exe":             "Firefox",
    "opera.exe":               "Opera",
    "opera_gx.exe":            "Opera GX",
    "brave.exe":               "Brave",
    "yandex.exe":              "Яндекс",
    "browser.exe":             "Яндекс",     # старый Яндекс.Браузер
    "vivaldi.exe":             "Vivaldi",
    "arc.exe":                 "Arc",
    "chromium.exe":            "Chromium",
    "librewolf.exe":           "LibreWolf",
    "waterfox.exe":            "Waterfox",
    "tor.exe":                 "Tor Browser",
    "thorium.exe":             "Thorium",
    "slimjet.exe":             "Slimjet",
    "epic.exe":                "Epic",
    "maxthon.exe":             "Maxthon",
    "sleipnir.exe":            "Sleipnir",
    "palemoon.exe":            "Pale Moon",
    "basilisk.exe":            "Basilisk",
}


def list_windows() -> list[str]:
    """Список заголовков всех видимых окон. Для отладки."""
    uia = _ensure_init()
    result = []
    with _lock:
        try:
            for w in uia.GetRootControl().GetChildren():
                try:
                    name = (w.Name or "").strip()
                    if name:
                        result.append(name)
                except Exception:
                    continue
        except Exception:
            log.exception("list_windows упал")
    return result


def list_browsers() -> list[tuple[str, str]]:
    """Список запущенных браузеров: [(exe, human_name), ...].

    Ищем по процессам — не по заголовкам окон. Работает для любых
    браузеров, даже если окно сейчас не в фокусе.
    """
    try:
        import psutil
    except ImportError:
        log.warning("psutil не установлен — не могу определить процессы браузеров")
        return []

    found: dict[str, str] = {}
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname in _BROWSER_PROCESSES:
                found[pname] = _BROWSER_PROCESSES[pname]
        except Exception:
            continue
    return sorted(found.items())


def _find_window_by_process(process_names: set[str], timeout: float = 2.0):
    """Ищет видимое окно, чей PID принадлежит процессу из process_names."""
    try:
        import psutil
    except ImportError:
        return None

    # Собираем PID-ы процессов с нужными именами.
    pids = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info.get("name") or "").lower() in process_names:
                pids.add(proc.info["pid"])
        except Exception:
            continue

    if not pids:
        return None

    # UIA нужен ТОЛЬКО когда есть процессы — иначе не инициализируем.
    uia = _ensure_init()

    with _lock:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                for w in uia.GetRootControl().GetChildren():
                    try:
                        if not w.Name:
                            continue
                        pid = w.ProcessId
                        if pid in pids:
                            return w
                    except Exception:
                        continue
            except Exception:
                log.exception("_find_window_by_process: обход упал")
                return None
            time.sleep(0.1)
    return None


def find_browser_window():
    """Находит окно ЛЮБОГО запущенного браузера.

    Возвращает uiautomation.WindowControl или None.
    Порядок: сначала активное окно (если это браузер) → потом по процессам.
    """
    # 1. Активное окно — а вдруг это уже браузер?
    #    Оборачиваем в try: UIA может не работать, а процессы — видны.
    try:
        active = get_active_window()
        if active is not None:
            try:
                active_pid = active.ProcessId
                import psutil
                try:
                    pname = psutil.Process(active_pid).name().lower()
                    if pname in _BROWSER_PROCESSES:
                        return active
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        # UIA не работает — не страшно, идём к процессам.
        pass

    # 2. Ищем по процессам.
    return _find_window_by_process(set(_BROWSER_PROCESSES.keys()))


def _get_browser_window():
    """Совместимость: обёртка над find_browser_window."""
    return find_browser_window()


def read_browser_url() -> str:
    """Читает URL активной вкладки. Пусто, если не браузер.

    На Chromium-браузерах адресная строка — EditControl с именем
    «Адресная строка и строка поиска» или пустым.
    """
    # Сначала окно — если браузера нет, UIA не нужен.
    w = _get_browser_window()
    if w is None:
        return ""

    uia = _ensure_init()

    with _lock:
        # Ищем EditControl внутри окна.
        try:
            edit = uia.EditControl(searchFromControl=w, searchDepth=20)
            if edit.Exists(2):
                try:
                    value = edit.GetValuePattern().Value
                    if value:
                        value = value.strip()
                        if re.match(r"^https?://", value, re.I):
                            return value
                        if re.match(r"^[a-z0-9-]+\.[a-z]{2,}(/|$)", value, re.I):
                            return "https://" + value
                except Exception:
                    log.exception("read_browser_url: чтение Edit упало")
        except Exception:
            log.exception("read_browser_url: поиск Edit упал")

        # Fallback: домен из заголовка окна.
        try:
            title = (w.Name or "").strip()
            for sep in (" — ", " - ", " | "):
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break
            m = re.search(r"([a-z0-9-]+\.(ru|com|org|net|io|dev|me|рф))",
                          title, re.I)
            if m:
                return "https://" + m.group(1)
        except Exception:
            pass

    return ""


def read_browser_tab_title() -> str:
    """Заголовок активной вкладки (без имени браузера)."""
    w = _get_browser_window()
    if w is None:
        return ""
    try:
        title = (w.Name or "").strip()
        # Формат: «Имя страницы — Chrome» → «Имя страницы»
        for sep in (" - ", " — ", " | "):
            if sep in title:
                return title.split(sep)[0].strip()
        return title
    except Exception:
        return ""


def read_browser_tabs() -> list[str]:
    """Список заголовков вкладок.

    Работает для Chromium-браузеров (Chrome, Edge, Яндекс):
        - Ищем ToolBarControl с именем 'Вкладки'.
        - Внутри него — TabItemControl с именами.
    """
    # Сначала окно — если браузера нет, UIA не нужен.
    w = _get_browser_window()
    if w is None:
        return []

    uia = _ensure_init()

    tabs: list[str] = []
    with _lock:
        try:
            # Ищем тулбар «Вкладки» внутри окна браузера.
            # auto.ToolBarControl(searchFromControl=..., searchDepth=...)
            # возвращает ПЕРВЫЙ найденный тулбар.
            toolbar = uia.ToolBarControl(
                searchFromControl=w,
                Name="Вкладки",
                searchDepth=15,
            )
            if toolbar.Exists(2):
                # Обходим прямых детей тулбара — это TabItemControl.
                for child in toolbar.GetChildren():
                    try:
                        if not _is_tab_item(child):
                            continue
                        name = (child.Name or "").strip()
                        if name and name not in tabs:
                            tabs.append(name)
                    except Exception:
                        continue

                # Если прямые дети — кнопки (Новая вкладка и т.п.),
                # обходим на один уровень глубже.
                if not tabs:
                    for child in toolbar.GetChildren():
                        for sub in child.GetChildren():
                            try:
                                if not _is_tab_item(sub):
                                    continue
                                name = (sub.Name or "").strip()
                                if name and name not in tabs:
                                    tabs.append(name)
                            except Exception:
                                continue

            log.info("read_browser_tabs: %d вкладок", len(tabs))
        except Exception:
            log.exception("read_browser_tabs упал")

    # Fallback — хотя бы активная.
    if not tabs:
        title = read_browser_tab_title()
        if title:
            tabs = [title]

    return tabs


# =================================================================
# Сопоставление имён вкладок: «ютуб» ↔ «YouTube»
# =================================================================
#
# Человек называет сайт по-русски, а в заголовке вкладки — латиница
# ((2) YouTube, GitHub, vk.com). Простое «"ютуб" in "(2) youtube"» не
# срабатывает, и «закрой вкладку ютуб» отвечала «не нашёл». Поэтому
# сравниваем не строки, а варианты написания: алиасы дают бренд
# (ютуб → youtube), транслитерация — «как слышится» (хабр → habr).

# Русское название сайта → латинское (как в заголовке вкладки/домене).
_SITE_ALIASES = {
    "ютуб": "youtube", "ютюб": "youtube", "ютьюб": "youtube",
    "вк": "vk", "вконтакте": "vk",
    "телеграм": "telegram", "телега": "telegram",
    "инстаграм": "instagram", "инста": "instagram",
    "фейсбук": "facebook", "фб": "facebook",
    "гитхаб": "github", "гит": "git",
    "википедия": "wikipedia", "вики": "wiki",
    "гугл": "google", "яндекс": "yandex", "почта": "mail",
    "дискорд": "discord", "тикток": "tiktok", "твиттер": "twitter",
    "спотифай": "spotify", "реддит": "reddit",
    "озон": "ozon", "авито": "avito", "вб": "wildberries",
    "вайлдберриз": "wildberries", "кинопоиск": "kinopoisk",
    "хабр": "habr", "гигачат": "gigachat",
}

# Русские буквы → латинские (транслитерация «как слышится»).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _norm_text(text: str) -> str:
    """Нижний регистр, пунктуация → пробел, кратные пробелы убраны."""
    text = (text or "").casefold()
    for ch in "«»\"'“”.,!?;:()[]—–-|/\\+":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _translit(text: str) -> str:
    """«хабр» → «habr»: латиница «как слышится»."""
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


def _word_variants(word: str) -> set[str]:
    """Написания одного слова: как есть, алиас в обе стороны, транслит."""
    out = {word, _translit(word)}
    alias = _SITE_ALIASES.get(word)
    if alias:
        out.add(alias)
    # Обратно: «vk» → «вк», «youtube» → «ютуб».
    for ru, latin in _SITE_ALIASES.items():
        if word == latin:
            out.add(ru)
    return {w for w in out if len(w) >= 2}


def title_matches(name: str, query: str) -> bool:
    """Похожа ли вкладка/окно на то, что просят? («ютуб» ≈ «(2) YouTube»).

    Два шага, чтобы не ловить ложные срабатывания:

    1. Как есть — вхождение подстроки (русский запрос против русского
       заголовка, латиница против латиницы).
    2. Разные алфавиты — сравниваем СЛОВА: «ютуб» → youtube, «хабр» →
       habr. Пословно, а не подстрокой: иначе «вк» → «vk» прилипает
       к «vkhoda» («без входа»).
    """
    name_norm = _norm_text(name)
    query_norm = _norm_text(query)
    if not name_norm or not query_norm:
        return False

    if query_norm in name_norm:
        return True

    asked: set[str] = set()
    for word in query_norm.split():
        asked |= _word_variants(word)
    have = set(name_norm.split()) | set(_translit(name_norm).split())
    return bool(asked & have)


# Сколько ждём, что вкладка закроется, и как часто смотрим список вкладок.
_CLOSE_WAIT = 2.0
_CLOSE_POLL = 0.15


def _safe_name(ctrl) -> str:
    """Имя контрола без исключений.

    Элемент закрытой вкладки в UIA уже мёртв, и обращение к `Name`
    бросает COMError («элемент больше не доступен»). Имя поэтому читаем
    ДО действий, а в логах берём только строку.
    """
    try:
        return (ctrl.Name or "").strip()
    except Exception:
        return ""


def _tab_close_button(ctrl):
    """Кнопка закрытия ВНУТРИ вкладки (или None)."""
    try:
        for child in ctrl.GetChildren():
            if not _is_button(child):
                continue
            cname = (child.Name or "").lower()
            if "close" in cname or "закры" in cname or not cname:
                return child
    except Exception:
        log.debug("Не прочитал детей вкладки %r", _safe_name(ctrl),
                  exc_info=True)
    return None


def _tabs_shrank(before: list[str], timeout: float | None = None) -> bool:
    """Вкладок стало меньше? Это единственный честный признак закрытия.

    Вызовы вида `Invoke()` возвращают True и когда нажатие ничего не
    сделало (кнопка скрыта до наведения, элемент не «реализован»).
    Поэтому верим не возврату вызова, а списку вкладок.
    """
    if timeout is None:
        timeout = _CLOSE_WAIT
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(_CLOSE_POLL)
        try:
            if before and len(read_browser_tabs()) < len(before):
                return True
        except Exception:
            continue
    return False


def _close_tab_by_hotkey(w, ctrl, tab_title_part: str, name: str,
                         before: list[str]) -> bool:
    """Выбрать вкладку и нажать Ctrl+W — как это сделал бы человек.

    Жмём только когда вкладка точно активна (выбралась сама или уже была):
    иначе Ctrl+W закрыл бы соседнюю.
    """
    selected = False
    try:
        ctrl.GetSelectionItemPattern().Select()
        selected = True
    except Exception:
        log.warning("Не удалось выбрать вкладку %r", name)

    if not selected and not active_tab_matches(tab_title_part):
        return False

    time.sleep(_CLOSE_POLL)
    try:
        w.SetActive()
    except Exception:
        log.debug("SetActive не удался", exc_info=True)
    time.sleep(_CLOSE_POLL)

    from jarvis import actions  # локально: jarvis.actions тянет uia
    actions.hotkey(["ctrl", "w"])

    # Список вкладок браузер может и не отдавать (одна активная) — тогда
    # судить не по чему, но Ctrl+W по выбранной вкладке закрывает её.
    if len(before) <= 1 or _tabs_shrank(before):
        log.info("Закрыл вкладку %r (Ctrl+W)", name)
        return True
    return False


def close_browser_tab(tab_title_part: str) -> bool:
    """Закрывает вкладку браузера по части заголовка.

    Заголовок ищем с учётом русских названий: «закрой вкладку ютуб»
    находит вкладку «(2) YouTube» (см. `title_matches`).

    Три способа, и после каждого проверяем СПИСОК вкладок:
        1. Кнопка закрытия внутри вкладки (`Invoke`) — ничего не двигает.
        2. Средний клик по вкладке — обычный жест «закрыть вкладку».
        3. Выбрать вкладку и нажать Ctrl+W.
    `Invoke()` в браузерах отдаёт True и при впустую нажатой кнопке, так
    что без проверки «закрыл» — враньё (так и было: отвечали «закрыл»,
    а вкладка оставалась).

    True — только если вкладка ДЕЙСТВИТЕЛЬНО исчезла из списка.
    """
    _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    target = None
    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if not _is_tab_item(ctrl):
                        continue
                    if title_matches(ctrl.Name or "", tab_title_part):
                        target = ctrl
                        break
                except Exception:
                    continue
        except Exception:
            log.exception("close_browser_tab упал")

        if target is None:
            log.info("Вкладка %r не найдена", tab_title_part)
            return False

        # Имя читаем ДО действий: закрытая вкладка перестаёт отвечать.
        name = _safe_name(target)
        before = read_browser_tabs()
        log.info("Закрываю вкладку %r (вкладок: %d)", name, len(before))

        # 1. Кнопка закрытия внутри вкладки.
        btn = _tab_close_button(target)
        if btn is not None:
            try:
                btn.GetInvokePattern().Invoke()
            except Exception:
                log.debug("Invoke кнопки закрытия не удался", exc_info=True)
            if _tabs_shrank(before):
                log.info("Закрыл вкладку %r (кнопка закрытия)", name)
                return True

        # 2. Средний клик по вкладке. Так закрывают вкладки руками —
        #    работает и когда кнопка закрытия скрыта до наведения.
        try:
            target.MiddleClick()
        except Exception:
            log.debug("MiddleClick по вкладке не удался", exc_info=True)
        if _tabs_shrank(before):
            log.info("Закрыл вкладку %r (средний клик)", name)
            return True

        # 3. Кнопка и клик не помогли — выбираем вкладку и жмём Ctrl+W.
        return _close_tab_by_hotkey(w, target, tab_title_part, name, before)


def switch_browser_tab(tab_title_part: str) -> bool:
    """Переключается на вкладку по части заголовка.

    Русские названия тоже понимаем: «переключись на вкладку ютуб»
    (см. `title_matches`).
    """
    uia = _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if not _is_tab_item(ctrl):
                        continue
                    if title_matches(ctrl.Name or "", tab_title_part):
                        ctrl.GetSelectionItemPattern().Select()
                        log.info("Переключился на вкладку %r", ctrl.Name)
                        return True
                except Exception:
                    continue
        except Exception:
            log.exception("switch_browser_tab упал")
    return False


def active_tab_matches(query: str) -> bool:
    """Активная вкладка — это та, которую просят?

    Нужно как запасной ход: браузер может не отдавать список вкладок
    через UIA (Яндекс группирует вкладки), но заголовок окна виден
    всегда. Тогда для закрытия хватает Ctrl+W.
    """
    title = read_browser_tab_title()
    return bool(title) and title_matches(title, query)


# =================================================================
# Меню
# =================================================================

def click_menu_item(path: str) -> bool:
    """Кликает пункт меню по пути «Файл > Сохранить как».

    Работает для приложений с классическим меню (Notepad++, старые приложения).
    """
    uia = _ensure_init()
    parts = [p.strip() for p in re.split(r"\s*[>»]\s*", path) if p.strip()]
    if not parts:
        return False

    w = get_active_window()
    if w is None:
        return False

    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=10):
                try:
                    if not _is_menu_item(ctrl):
                        continue
                    name = (ctrl.Name or "").strip().lower()
                    if parts[0].lower() in name:
                        if len(parts) == 1:
                            ctrl.GetInvokePattern().Invoke()
                            return True
                        ctrl.GetExpandCollapsePattern().Expand()
                        time.sleep(0.1)
                        # Дальше — обход подменю.
                        for sub in _walk_controls(ctrl, depth=5):
                            try:
                                if not _is_menu_item(sub):
                                    continue
                                sname = (sub.Name or "").strip().lower()
                                if parts[1].lower() in sname:
                                    sub.GetInvokePattern().Invoke()
                                    return True
                            except Exception:
                                continue
                except Exception:
                    continue
        except Exception:
            log.exception("click_menu_item упал")
    return False


# =================================================================
# Диагностика
# =================================================================

def is_supported() -> bool:
    """Есть ли библиотека `uiautomation` — без обращения к COM.

    Отвечает на вопрос «можно ли вообще пробовать UIA»: на CI-раннере
    библиотеки нет, локально она есть. Тесты (`tests/stress_intents.py`)
    спрашивают ответ отсюда, чтобы ожидания совпадали с поведением команд.
    """
    try:
        _ensure_init()
        return True
    except Exception:
        return False


def is_available() -> bool:
    """Проверяет, работает ли UIA (COM инициализируется)."""
    try:
        _ensure_init()
        w = get_active_window()
        return w is not None
    except Exception:
        return False


def describe_active_window() -> str:
    """Человеческое описание активного окна — для отладки."""
    title = get_active_window_title()
    if not title:
        return "Не вижу активного окна."
    return f"Активное окно: «{title}»."


def describe_browsers() -> str:
    """Человеческое описание запущенных браузеров — для отладки."""
    browsers = list_browsers()
    if not browsers:
        return "Запущенных браузеров не вижу."
    names = [human for _, human in browsers]
    return "Запущены браузеры: " + ", ".join(names) + "."