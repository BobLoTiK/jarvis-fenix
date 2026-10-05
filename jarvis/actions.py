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
    if s.startswith("open_app:"):
        return ("open_app", s[len("open_app:"):])
    if s.startswith(("http://", "https://")):
        return ("url", s)
    if s.startswith("steam://"):
        return ("uri", s)
    if s.lower().endswith((".bat", ".cmd")):
        return ("path", s)
    if s.lower() in ("browser", "браузер"):
        return ("browser", None)
    if os.path.exists(s):
        return ("path", s)
    return ("path", s)


def run_spec(spec) -> bool:
    if not spec:
        return False
    kind, value = spec
    log.info("Запуск: %s %s", kind, value)
    try:
        if kind == "open_app":
            from jarvis.installed import scan_start_menu, find_installed
            apps = scan_start_menu()
            hit = find_installed(apps, value)
            if hit:
                os.startfile(str(hit[1]))
                _schedule_activation(value, hit[0])
                return True
            log.warning("Приложение '%s' не найдено в меню Пуск", value)
            return False
        if kind == "browser":
            open_browser()
            return True
        if kind == "url":
            open_url(value)
            return True
        if kind == "uri":
            os.startfile(value)
            return True
        if kind == "cmd":
            args = value if isinstance(value, list) else [value]
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        if kind in ("path", "exe"):
            os.startfile(value)
            return True
    except Exception:
        log.exception("run_spec не удался: %s", spec)
    return False


def _schedule_activation(name: str, app_title: str | None = None) -> None:
    """Через 2 сек после запуска пытается активировать окно приложения."""
    import threading
    targets = [name]
    if app_title and app_title.lower() != name.lower():
        targets.append(app_title)

    def _run():
        time.sleep(2.0)
        try:
            import pygetwindow as gw
            for t in targets:
                t_low = t.lower()
                for w in gw.getAllWindows():
                    if not w.title:
                        continue
                    if t_low in w.title.lower():
                        try:
                            if getattr(w, "isMinimized", False):
                                w.restore()
                                time.sleep(0.1)
                            w.activate()
                            log.info("Активировал окно: %s", w.title)
                        except Exception:
                            pass
                        return
        except Exception:
            log.exception("Не удалось активировать окно %r", name)

    threading.Thread(target=_run, daemon=True, name=f"activate-{name}").start()


def open_path(path, minimized: bool = False) -> bool:
    log.info("Открываю путь: %s (minimized=%s)", path, minimized)
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
    log.info("Открываю URL: %s", url)
    try:
        os.startfile(url)
        return True
    except Exception:
        log.exception("open_url не удался: %s", url)
        return False


def open_browser() -> bool:
    log.info("Открываю браузер")
    try:
        os.startfile("https://www.google.com")
        return True
    except Exception:
        log.exception("open_browser не удался")
        return False


# --- поиск и сайты ---------------------------------------------------------

def open_search(engine: str, query: str) -> bool:
    log.info("Поиск: %s, запрос=%r", engine, query)
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
        log.info("Скриншот: %s", path)
        return path
    except Exception:
        log.exception("take_screenshot не удался")
        raise


# --- медиа -----------------------------------------------------------------

def media_key(key: str, times: int = 1) -> bool:
    log.info("Медиа-клавиша: %s x%d", key, times)
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


# --- раскладка клавиатуры --------------------------------------------------

def switch_layout() -> bool:
    """Переключает раскладку через Alt+Shift (SendInput).

    keybd_event не работает для системных сочетаний — используем SendInput
    с задержкой между нажатиями.
    """
    log.info("Переключаю раскладку (Alt+Shift)")
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        # Структуры для SendInput
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("ki", KEYBDINPUT),
                ("padding", ctypes.c_ubyte * 8),
            ]

        VK_MENU = 0x12       # Alt
        VK_SHIFT = 0x10      # Shift
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1

        def _key(vk, up=False):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.wScan = 0
            inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
            inp.ki.time = 0
            inp.ki.dwExtraInfo = None
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        # Alt down
        _key(VK_MENU)
        import time as _t
        _t.sleep(0.05)
        # Shift down + up
        _key(VK_SHIFT)
        _t.sleep(0.05)
        _key(VK_SHIFT, up=True)
        _t.sleep(0.05)
        # Alt up
        _key(VK_MENU, up=True)
        return True
    except Exception:
        log.exception("switch_layout не удался")
        return False
def _set_layout_hkl(hkl_hex: str) -> bool:
    """Устанавливает раскладку по HKL через PostMessage с фокусом."""
    log.info("Установка раскладки: %s", hkl_hex)
    try:
        import ctypes
        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            log.warning("Нет foreground-окна")
            return False

        # Форсируем фокус — иначе Windows блокирует смену
        user32.SetForegroundWindow(hwnd)
        hkl = user32.LoadKeyboardLayoutW(hkl_hex, 1)
        # 0x50 = WM_INPUTLANGCHANGEREQUEST
        user32.PostMessageW(hwnd, 0x50, 0, hkl)
        return True
    except Exception:
        log.exception("_set_layout_hkl не удался: %s", hkl_hex)
        return False


def set_layout_ru() -> bool:
    """Переключает на русскую раскладку."""
    return _set_layout_hkl("00000419")


def set_layout_en() -> bool:
    """Переключает на английскую раскладку."""
    return _set_layout_hkl("00000409")


def get_layout() -> str | None:
    """Возвращает 'ru', 'en' или None."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        hkl = ctypes.windll.user32.GetKeyboardLayout(thread_id)
        lang_id = hkl & 0xFFFF
        return {0x0419: "ru", 0x0409: "en"}.get(lang_id)
    except Exception:
        log.exception("get_layout не удался")
        return None

# --- громкость -------------------------------------------------------------

def get_volume() -> int | None:
    """Возвращает громкость в процентах (0..100)."""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        device = AudioUtilities.GetSpeakers()
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return round(volume.GetMasterVolumeLevelScalar() * 100)
    except Exception:
        log.exception("get_volume не удался")
        return None


def set_volume(percent: int) -> bool:
    """Ставит громкость в процентах (0..100)."""
    percent = max(0, min(100, int(percent)))
    log.info("Громкость: %d%%", percent)
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL

        device = AudioUtilities.GetSpeakers()
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return True
    except Exception:
        log.exception("set_volume не удался")
        return False


# --- яркость ---------------------------------------------------------------

def get_brightness() -> int | None:
    """Возвращает яркость в процентах (0..100)."""
    try:
        import screen_brightness_control as sbc
        values = sbc.get_brightness()
        if values:
            return int(values[0])
        return None
    except Exception:
        log.exception("get_brightness не удался")
        return None


def set_brightness(percent: int) -> bool:
    """Ставит яркость в процентах (0..100)."""
    percent = max(0, min(100, int(percent)))
    log.info("Яркость: %d%%", percent)
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(percent)
        return True
    except Exception:
        log.exception("set_brightness не удался")
        return False


# --- процессы --------------------------------------------------------------

def find_process(name: str, threshold: float = 0.7):
    """Находит имя процесса по неточному имени."""
    try:
        import psutil
    except ImportError:
        return None
    from jarvis.matching import match_score
    name_low = name.lower()
    best_name, best_score = None, 0.0
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info.get("name") or "").lower()
        if not pname:
            continue
        base = pname.removesuffix(".exe")
        if name_low in base or base in name_low:
            return proc.info["name"]
        score = match_score(name_low, base)
        if score > best_score:
            best_name, best_score = proc.info["name"], score
    if best_name and best_score >= threshold:
        log.info("Процесс %r -> %s (score %.2f)", name, best_name, best_score)
        return best_name
    log.info("Процесс для %r не найден (лучший score %.2f)", name, best_score)
    return None


def kill_process(name: str) -> bool:
    protected = {"system", "svchost.exe", "csrss.exe", "wininit.exe",
                 "services.exe", "lsass.exe", "explorer.exe"}
    if name.lower() in protected:
        log.warning("Запрещено убивать защищённый процесс: %s", name)
        return False
    log.info("Убиваю процесс: %s", name)
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
    log.info("Печатаю: %r", text)
    try:
        import pyautogui
        try:
            import pyperclip
            old = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.15)
            pyperclip.copy(old)
            return True
        except Exception:
            log.debug("pyperclip не сработал, пробую pyautogui.typewrite")
        pyautogui.typewrite(text, interval=0.02)
        return True
    except Exception:
        log.exception("type_text не удался")
        return False


def minimize_all() -> bool:
    try:
        import pygetwindow as gw
        count = 0
        for w in gw.getAllWindows():
            try:
                if w.title and w.visible and not w.isMinimized:
                    w.minimize()
                    count += 1
            except Exception:
                pass
        log.info("Свёрнуто окон: %d", count)
        return True
    except Exception:
        try:
            import pyautogui
            pyautogui.hotkey("win", "d")
            return True
        except Exception:
            log.exception("minimize_all не удался")
            return False


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
    try:
        import pygetwindow as gw
    except ImportError:
        return None

    windows = [w for w in gw.getAllWindows() if w.title]
    name_low = name.lower().strip()

    for noise in (" музыка", " browser", " браузер"):
        if name_low.endswith(noise):
            name_low = name_low[: -len(noise)].strip()

    direct = [w for w in windows if name_low in w.title.lower()]
    if direct:
        for w in direct:
            try:
                if w.visible and not w.isMinimized:
                    return w
            except Exception:
                pass
        return direct[0]

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
        for sub in subs:
            sub_low = sub.lower()
            for w in windows:
                if sub_low in w.title.lower():
                    return w

    from jarvis.matching import match_score
    best = None
    best_score = 0.6
    for w in windows:
        title = w.title.lower()
        score = match_score(name_low, title[:40])
        if score > best_score:
            best_score, best = score, w
    if best:
        log.info("Окно %r -> %s (score %.2f)", name, best.title, best_score)
    return best


def minimize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для сворачивания: %s", name)
        return False
    try:
        w.minimize()
        log.info("Свернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("minimize_window_by_title не удался")
        return False


def maximize_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для разворачивания: %s", name)
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
        log.info("Развернул окно: %s", w.title)
        return True
    except Exception:
        log.exception("maximize_window_by_title не удался")
        return False


def activate_window_by_title(name: str) -> bool:
    w = _find_window(name)
    if not w:
        log.warning("Окно не найдено для активации: %s", name)
        return False
    try:
        if getattr(w, "isMinimized", False):
            w.restore()
            time.sleep(0.15)
        w.activate()
        log.info("Активировал окно: %s", w.title)
        return True
    except Exception:
        log.exception("activate_window_by_title не удался")
        return False


def minimize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "down")
        log.info("Свернул активное окно")
        return True
    except Exception:
        log.exception("minimize_active не удался")
        return False


def maximize_active() -> bool:
    try:
        import pyautogui
        pyautogui.hotkey("win", "up")
        log.info("Развернул активное окно")
        return True
    except Exception:
        log.exception("maximize_active не удался")
        return False


def switch_window(back: bool = False) -> bool:
    try:
        import pyautogui
        if back:
            pyautogui.hotkey("alt", "shift", "tab")
            log.info("Переключил окно назад")
        else:
            pyautogui.hotkey("alt", "tab")
            log.info("Переключил окно")
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


# --- буфер обмена -----------------------------------------------------------

def copy_selection() -> bool:
    """Нажимает Ctrl+C, чтобы скопировать выделенное в активном окне."""
    log.info("Копирую выделенное (Ctrl+C)")
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "c")
        return True
    except Exception:
        log.exception("copy_selection не удался")
        return False


def clipboard_read() -> str:
    log.info("Читаю буфер обмена")
    try:
        import pyperclip
        text = pyperclip.paste() or ""
        log.info("Буфер обмена: %r", text[:80])
        return text
    except Exception:
        log.exception("clipboard_read не удался")
        return ""


def clipboard_write(text: str) -> bool:
    log.info("Пишу в буфер обмена: %r", text[:80])
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard_write не удался")
        return False


def clipboard_clear() -> bool:
    log.info("Очищаю буфер обмена")
    return clipboard_write("")