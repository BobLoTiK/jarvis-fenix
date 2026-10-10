"""UI Automation — видим окна и элементы интерфейса.

Обёртка над `uiautomation` (Windows UIA через COM).

Что умеем:
    - Найти окно по части заголовка.
    - Прочитать весь видимый текст активного окна.
    - Прочитать URL активной вкладки браузера.
    - Нажать кнопку по имени.
    - Закрыть вкладку браузера.
    - Переключиться на вкладку по имени.

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


def _ensure_init():
    """Ленивая инициализация UIA в текущем потоке."""
    global _uia
    if _uia is None:
        try:
            import uiautomation as auto
            _uia = auto
            log.info("UIA инициализирован")
        except ImportError:
            log.error("uiautomation не установлен. pip install uiautomation")
            raise
    return _uia


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
                            if c.ControlType != uia.ControlTypeName.ButtonControl:
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
                        if child.ControlType != uia.ControlType.TabItemControl:
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
                                if sub.ControlType != uia.ControlType.TabItemControl:
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


def close_browser_tab(tab_title_part: str) -> bool:
    """Закрывает вкладку браузера по части заголовка."""
    uia = _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    tab_low = tab_title_part.lower()
    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if ctrl.ControlType != uia.ControlTypeName.TabItemControl:
                        continue
                    name = (ctrl.Name or "").lower()
                    if tab_low not in name:
                        continue
                    # Ищем кнопку закрытия внутри вкладки.
                    for child in ctrl.GetChildren():
                        try:
                            if child.ControlType == uia.ControlTypeName.ButtonControl:
                                cname = (child.Name or "").lower()
                                if "close" in cname or "закры" in cname or not cname:
                                    child.GetInvokePattern().Invoke()
                                    log.info("Закрыл вкладку %r", ctrl.Name)
                                    return True
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            log.exception("close_browser_tab упал")
    return False


def switch_browser_tab(tab_title_part: str) -> bool:
    """Переключается на вкладку по части заголовка."""
    uia = _ensure_init()
    w = _get_browser_window()
    if w is None:
        return False

    tab_low = tab_title_part.lower()
    with _lock:
        try:
            for ctrl in _walk_controls(w, depth=15):
                try:
                    if ctrl.ControlType != uia.ControlTypeName.TabItemControl:
                        continue
                    name = (ctrl.Name or "").lower()
                    if tab_low in name:
                        ctrl.GetSelectionItemPattern().Select()
                        log.info("Переключился на вкладку %r", ctrl.Name)
                        return True
                except Exception:
                    continue
        except Exception:
            log.exception("switch_browser_tab упал")
    return False


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
                    if ctrl.ControlType != uia.ControlTypeName.MenuItemControl:
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
                                if sub.ControlType != uia.ControlTypeName.MenuItemControl:
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