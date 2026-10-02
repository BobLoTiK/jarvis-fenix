"""Действия: запуск приложений, открытие сайтов, скриншоты, медиа, печать, окна."""

import logging
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

log = logging.getLogger("jarvis.actions")


# --- запуск приложений и файлов -------------------------------------------

def spec_from_string(s: str):
    """Превращает строку из конфига в spec-кортеж для run_spec."""
    s = s.strip()
    if s.startswith(("http://", "https://")):
        return ("url", s)
    if s.startswith("steam://"):
        return ("uri", s)
    if s.lower().endswith((".bat", ".cmd")):
        return ("path", s)
    if os.path.exists(s):
        return ("path", s)
    return ("path", s)


def run_spec(spec) -> bool:
    """Выполняет spec: ('url', ...), ('uri', ...), ('path', ...), ('exe', ...)."""
    if not spec:
        return False
    kind, value = spec
    try:
        if kind == "url":
            open_url(value)
            return True
        if kind == "uri":
            os.startfile(value)
            return True
        if kind in ("path", "exe"):
            os.startfile(value)
            return True
    except Exception:
        log.exception("run_spec не удался: %s", spec)
    return False


def open_path(path, minimized: bool = False) -> bool:
    """Открывает файл или папку. minimized — для .lnk запускает свёрнутым."""
    try:
        if minimized and str(path).lower().endswith(".lnk"):
            subprocess.Popen(["cmd", "/c", "start", "/min", "", str(path)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        os.startfile(str(path))
        return True
    except Exception:
        log.exception("open_path не удался: %s", path)
        return False


def open_url(url: str) -> bool:
    try:
        os.startfile(url)
        return True
    except Exception:
        log.exception("open_url не удался: %s", url)
        return False


def open_browser() -> bool:
    try:
        os.startfile("https://www.google.com")
        return True
    except Exception:
        log.exception("open_browser не удался")
        return False


# --- поиск и сайты ---------------------------------------------------------

def open_search(engine: str, query: str) -> bool:
    """Открывает поиск в нужном движке."""
    q = urllib.parse.quote(query)
    if engine == "youtube":
        url = f"https://www.youtube.com/results?search_query={q}"
    elif engine == "wiki":
        url = f"https://ru.wikipedia.org/w/index.php?search={q}"
    else:
        url = f"https://www.google.com/search?q={q}"
    return open_url(url)


def google_search(query: str) -> bool:
    return open_search("google", query)


def open_site_lucky(name: str) -> bool:
    """DuckDuckGo «мне повезёт» — открывает первый результат."""
    q = urllib.parse.quote(name)
    return open_url(f"https://duckduckgo.com/?q=!ducky+{q}")


def spoken_domain(name: str):
    """«хабр точка ру» -> https://habr.ru. Возвращает URL или None."""
    text = name.lower().replace("точка", ".").replace(" точка ", ".").strip()
    text = re.sub(r"\s+", "", text)
    if "." in text and " " not in text:
        return "https://" + text
    return None


def guess_site(name: str):
    """Пробует угадать домен: habr -> habr.ru / habr.com и т.п."""
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not slug:
        return None
    for zone in (".ru", ".com", ".org", ".net"):
        return f"https://{slug}{zone}"
    return None


# --- скриншоты -------------------------------------------------------------

def take_screenshot():
    """Делает скриншот и сохраняет в Изображения\\Screenshots."""
    try:
        from PIL import ImageGrab
        folder = Path.home() / "Pictures" / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        img = ImageGrab.grab()
        img.save(path)
        return path
    except Exception:
        log.exception("take_screenshot не удался")
        raise


# --- медиа -----------------------------------------------------------------

def media_key(key: str, times: int = 1) -> bool:
    """Нажимает медиа-клавишу через WinRT Media Control."""
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )
    except ImportError:
        log.warning("WinRT Media Control недоступен")
        return False
    try:
        import asyncio

        async def _press():
            mgr = await Manager.request_async()
            session = mgr.get_current_session()
            if not session:
                return False
            for _ in range(max(1, times)):
                if key == "play":
                    await session.try_toggle_play_pause_async()
                elif key == "next":
                    await session.try_skip_next_async()
                elif key == "prev":
                    await session.try_skip_previous_async()
                elif key == "vol_up":
                    _volume_up()
                elif key == "vol_down":
                    _volume_down()
                elif key == "mute":
                    _volume_mute()
                time.sleep(0.05)
            return True

        return asyncio.run(_press())
    except Exception:
        log.exception("media_key не удался: %s", key)
        return False


def _volume_up():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)


def _volume_down():
    import ctypes
    for _ in range(2):
        ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)


def _volume_mute():
    import ctypes
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0xAD, 0, 2, 0)


def ensure_music_playing() -> bool:
    """Жмёт play в текущей медиа-сессии."""
    return media_key("play")


# --- процессы --------------------------------------------------------------

def find_process(name: str, threshold: float = 0.7):
    """Ищет запущенный процесс по имени (нечёткое совпадение)."""
    try:
        import psutil
    except ImportError:
        return None
    from difflib import SequenceMatcher
    name_low = name.lower()
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info.get("name") or "").lower()
        if not pname:
            continue
        base = pname.removesuffix(".exe")
        if name_low in base or SequenceMatcher(None, name_low, base).ratio() >= threshold:
            return proc.info["name"]
    return None


def kill_process(name: str) -> bool:
    """Убивает процесс по имени. Системные защищены."""
    protected = {"system", "svchost.exe", "csrss.exe", "wininit.exe",
                 "services.exe", "lsass.exe", "explorer.exe"}
    if name.lower() in protected:
        return False
    try:
        import psutil
        killed = False
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower() == name.lower():
                proc.kill()
                killed = True
        return killed
    except Exception:
        log.exception("kill_process не удался: %s", name)
        return False


def close_browser() -> bool:
    """Закрывает основные браузеры."""
    for name in ("chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"):
        if find_process(name.removesuffix(".exe")) and kill_process(name):
            return True
    return False


def minimize_window(name: str) -> bool:
    """Сворачивает окно по заголовку (для таймера после запуска музыки)."""
    return minimize_window_by_title(name)


# --- НОВОЕ: печать и окна --------------------------------------------------

def type_text(text: str) -> bool:
    """Печатает текст в активное окно."""
    if not text:
        return False
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=0.02)
        return True
    except Exception:
        log.exception("type_text не удался")
        return False


def minimize_all() -> bool:
    """Свернуть все окна (Win+D)."""
    try:
        import pyautogui
        pyautogui.hotkey("win", "d")
        return True
    except Exception:
        log.exception("minimize_all не удался")
        return False


def _find_window(name: str):
    """Ищет окно по подстроке в заголовке (регистронезависимо)."""
    try:
        import pygetwindow as gw
    except ImportError:
        return None
    name_low = name.lower()
    candidates = []
    for w in gw.getAllWindows():
        if not w.title:
            continue
        if name_low in w.title.lower():
            candidates.append(w)
    if not candidates:
        return None
    # приоритет — активное или видимое окно
    for w in candidates:
        try:
            if w.visible and not w.isMinimized:
                return w
        except Exception:
            pass
    return candidates[0]


def minimize_window_by_title(name: str) -> bool:
    """Сворачивает окно, в заголовке которого есть name."""
    w = _find_window(name)
    if not w:
        return False
    try:
        w.minimize()
        return True
    except Exception:
        log.exception("minimize_window_by_title не удался")
        return False


def maximize_window_by_title(name: str) -> bool:
    """Разворачивает окно, в заголовке которого есть name."""
    w = _find_window(name)
    if not w:
        return False
    try:
        # если окно свёрнуто — сначала восстановить, иначе maximize не сработает
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.maximize()
        try:
            w.activate()
        except Exception:
            pass
        return True
    except Exception:
        log.exception("maximize_window_by_title не удался")
        return False


# --- папки пользователя ----------------------------------------------------

_USER_FOLDERS = {
    "загрузки": Path.home() / "Downloads",
    "скачанное": Path.home() / "Downloads",
    "документы": Path.home() / "Documents",
    "рабочий стол": Path.home() / "Desktop",
    "изображения": Path.home() / "Pictures",
    "картинки": Path.home() / "Pictures",
    "музыка": Path.home() / "Music",
    "видео": Path.home() / "Videos",
    "скриншоты": Path.home() / "Pictures" / "Screenshots",
}


def resolve_user_folder(name: str):
    """Возвращает Path для папки пользователя по названию или None."""
    name = name.lower().strip()
    for key, path in _USER_FOLDERS.items():
        if key in name:
            return path
    return None