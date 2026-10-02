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
    q = urllib.parse.quote(name)
    return open_url(f"https://duckduckgo.com/?q=!ducky+{q}")


def spoken_domain(name: str):
    text = name.lower().replace("точка", ".").replace(" точка ", ".").strip()
    text = re.sub(r"\s+", "", text)
    if "." in text and " " not in text:
        return "https://" + text
    return None


def guess_site(name: str):
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    if not slug:
        return None
    return f"https://{slug}.ru"


# --- скриншоты -------------------------------------------------------------

def take_screenshot():
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
    return media_key("play")


# --- процессы --------------------------------------------------------------

def find_process(name: str, threshold: float = 0.7):
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
    for name in ("chrome.exe", "firefox.exe", "msedge.exe", "opera.exe", "brave.exe"):
        if find_process(name.removesuffix(".exe")) and kill_process(name):
            return True
    return False


def minimize_window(name: str) -> bool:
    return minimize_window_by_title(name)


# --- печать и окна ---------------------------------------------------------

def type_text(text: str) -> bool:
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
    try:
        import pyautogui
        pyautogui.hotkey("win", "d")
        return True
    except Exception:
        log.exception("minimize_all не удался")
        return False


# Синонимы для окон: что сказать -> подстроки, которые искать в заголовках.
# Регистр не важен. Порядок — от специфичных к общим.
_WINDOW_SYNONYMS = {
    "консоль": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "терминал": ["cmd.exe", "powershell", "command prompt", "c:\\users\\", "c:\\windows\\", "c:\\jarvis"],
    "командную строку": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "командная строка": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "cmd": ["cmd.exe", "command prompt", "c:\\users\\", "c:\\windows\\"],
    "браузер": ["chrome", "firefox", "яндекс", "yandex", "edge", "opera", "brave"],
    "хром": ["chrome"],
    "яндекс браузер": ["яндекс", "yandex"],
    "firefox": ["firefox"],
    "файрфокс": ["firefox"],
    "edge": ["edge"],
    "эдж": ["edge"],
    "телега": ["telegram"],
    "телеграм": ["telegram"],
    "тг": ["telegram"],
    "дискорд": ["discord"],
    "дс": ["discord"],
    "стим": ["steam"],
    "steam": ["steam"],
    "проводник": ["проводник", "explorer"],
    "explorer": ["проводник", "explorer"],
    "папку": ["проводник", "explorer"],
    "настройки": ["настройки", "settings", "параметры"],
    "параметры": ["параметры", "settings", "настройки"],
    "оллама": ["ollama"],
    "ollama": ["ollama"],
    "радмин": ["radmin"],
    "radmin": ["radmin"],
    "овервульф": ["overwolf"],
    "overwolf": ["overwolf"],
}


def _find_window(name: str):
    """Ищет окно по подстроке в заголовке с учётом синонимов."""
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    windows = [w for w in gw.getAllWindows() if w.title]
    name_low = name.lower().strip()

    # 1. Прямое совпадение подстроки
    direct = [w for w in windows if name_low in w.title.lower()]
    if direct:
        for w in direct:
            try:
                if w.visible and not w.isMinimized:
                    return w
            except Exception:
                pass
        return direct[0]

    # 2. Синонимы: ищем по списку подстрок
    subs = None
    for key, values in _WINDOW_SYNONYMS.items():
        if key == name_low or key in name_low or name_low in key:
            subs = values
            break
    if subs:
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    try:
                        if w.visible and not w.isMinimized:
                            return w
                    except Exception:
                        pass
        # второй проход — берём любое, даже свёрнутое
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    return w

    # 3. Нечёткое совпадение (SequenceMatcher) по началу заголовка
    from difflib import SequenceMatcher
    best = None
    best_ratio = 0.6
    for w in windows:
        title_low = w.title.lower()
        # сравниваем с началом заголовка (первые 40 символов) — там обычно имя программы
        ratio = SequenceMatcher(None, name_low, title_low[:40]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = w
    return best


def minimize_window_by_title(name: str) -> bool:
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
    w = _find_window(name)
    if not w:
        return False
    try:
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


def activate_window_by_title(name: str) -> bool:
    """Переключается на окно по имени (активирует его)."""
    w = _find_window(name)
    if not w:
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.activate()
        return True
    except Exception:
        log.exception("activate_window_by_title не удался")
        return False


# --- относительные окна: активное, переключение ---------------------------

def minimize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "down")
        return True
    except Exception:
        log.exception("minimize_active не удался")
        return False


def maximize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "up")
        return True
    except Exception:
        log.exception("maximize_active не удался")
        return False


def switch_window(back: bool = False) -> bool:
    try:
        import pyautogui
        if back:
            pyautogui.hotkey("alt", "shift", "tab")
        else:
            pyautogui.hotkey("alt", "tab")
        return True
    except Exception:
        log.exception("switch_window не удался")
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
    name = name.lower().strip()
    for key, path in _USER_FOLDERS.items():
        if key in name:
            return path
    return None