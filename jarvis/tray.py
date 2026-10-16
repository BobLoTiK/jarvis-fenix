"""Иконка в системном трее (pystray).

pystray требует свой Windows message loop, а главный поток занят
Flet'ом (ft.run блокирует). Решение: иконка поднимается ДО ft.run()
в daemon-потоке (см. start_tray), и только потом Flet забирает главный
поток. Если pystray/PIL нет или иконка не появилась — Феникс просто
работает без трея (в логе предупреждение), а не падает.

Модуль импортируется ЛЕНИВО (только при tray_enabled=true): pystray и
PIL тянут заметный импорт, а старт Феникса и так на диете.
"""

import logging
import os
import threading
import time

from jarvis import __version__, APP_NAME

log = logging.getLogger("jarvis.tray")

# Имя иконки для WinAPI (в трее не видно, но должно быть уникальным).
ICON_NAME = "jarvis"

# Пункты меню дёргают GUI так же, как кнопки окна: gui.show_window() и
# gui.open_settings_tab() лишь кладут задачу в очередь GUI (см.
# FenixGUI._process_queue). Значит, поток трея не трогает Flet напрямую.


def _make_icon_image():
    """Same phoenix mark as the desktop app, not the old J fallback."""
    from pathlib import Path
    from PIL import Image
    path = Path(__file__).resolve().parent / "assets" / "brand" / "tray.png"
    with Image.open(path) as image:
        return image.convert("RGBA")


def build_menu(jarvis):
    """Меню трея (отдельно от иконки — так его проще тестировать)."""
    import pystray

    def on_toggle(icon, item):
        jarvis.listening_enabled = not jarvis.listening_enabled
        log.info("Трей: прослушивание → %s", jarvis.listening_enabled)

    def on_screenshot(icon, item):
        from jarvis import actions
        actions.take_screenshot()

    def on_show_window(icon, item):
        """Показать окно GUI (для launch_mode=tray)."""
        gui = getattr(jarvis, "gui", None)
        if gui is not None:
            gui.show_window()
        else:
            log.warning("Трей: GUI не запущен — окно показать нечем")

    def on_open_settings(icon, item):
        """Открыть GUI на вкладке «Настройки»."""
        gui = getattr(jarvis, "gui", None)
        if gui is not None:
            gui.show_window()
            gui.open_settings_tab()
        else:
            log.warning("Трей: GUI не запущен — настройки открыть нечем")

    def on_config(icon, item):
        """Открыть config.json из USER_DIR (%APPDATA%\\Phoenix)."""
        from jarvis import paths
        try:
            os.startfile(str(paths.config_path()))
        except Exception:
            log.exception("Трей: не удалось открыть config.json")

    def on_log(icon, item):
        """Открыть jarvis.log из USER_DIR."""
        from jarvis import paths
        try:
            os.startfile(str(paths.logs_dir() / "jarvis.log"))
        except Exception:
            log.exception("Трей: не удалось открыть jarvis.log")

    def on_exit(icon, item):
        """Выход целиком: микрофон стоп + закрытие окна + снятие иконки.

        Раньше здесь был только jarvis.shutdown(), а окно Flet оставалось
        жить — процесс не завершался, и помогала лишь «Смерть» через
        диспетчер задач.
        """
        log.info("Трей: выход")
        try:
            jarvis.shutdown()
        except Exception:
            log.exception("Трей: shutdown упал")
        gui = getattr(jarvis, "gui", None)
        if gui is not None:
            try:
                gui.quit()
            except Exception:
                log.exception("Трей: не удалось закрыть окно GUI")
        try:
            icon.stop()
        except Exception:
            log.exception("Трей: не удалось снять иконку")

    return pystray.Menu(
        pystray.MenuItem(f"{APP_NAME} v{__version__}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True — двойной клик по иконке открывает окно
        pystray.MenuItem("Открыть окно", on_show_window, default=True),
        pystray.MenuItem("Настройки", on_open_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Слушать микрофон", on_toggle,
                         checked=lambda item: jarvis.listening_enabled),
        pystray.MenuItem("Сделать скриншот", on_screenshot),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть конфиг", on_config),
        pystray.MenuItem("Открыть журнал", on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", on_exit),
    )


def _windows_icon_type(base, win32):
    """pystray 0.19 ignores Shell_NotifyIconW's BOOL; do not fake readiness.

    Keep the adapter local (no monkeypatch to pystray/global WinAPI). Uses the
    same native payload as its Windows backend; Explorer can be late at logon.
    """
    import ctypes

    class CheckedWindowsIcon(base):
        def _show(self):
            self._assert_icon_handle()
            deadline = time.monotonic() + 2.0
            while True:
                accepted = win32.Shell_NotifyIcon(win32.NIM_ADD, win32.NOTIFYICONDATAW(
                    cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW),
                    hWnd=self._hwnd, hID=id(self),
                    uFlags=win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP,
                    uCallbackMessage=win32.WM_NOTIFY, hIcon=self._icon_handle,
                    szTip=self.title))
                if accepted:
                    return
                if time.monotonic() >= deadline:
                    raise OSError("Windows не приняла значок Феникса в область уведомлений")
                time.sleep(0.1)

    return CheckedWindowsIcon


def build_icon(jarvis):
    """Создаёт pystray.Icon (message loop не запускает)."""
    import pystray

    icon_type = pystray.Icon
    if os.name == "nt":
        from pystray._util import win32
        icon_type = _windows_icon_type(icon_type, win32)
    return icon_type(
        ICON_NAME,
        _make_icon_image(),
        f"{APP_NAME} v{__version__}",
        build_menu(jarvis),
    )


def start_tray(jarvis, check_after: float = 3.0, on_fail=None):
    """Return an icon only after Windows accepted its visibility request.

    Windows supports pystray's loop on a dedicated thread. Initial readiness
    is bounded; failures return None, so callers never hide an unreachable UI.
    A monitor also restores the GUI if the message loop dies later.
    """
    try:
        icon = build_icon(jarvis)
    except Exception:
        log.exception("Трей: pystray/PIL недоступны — работаю без трея")
        return None

    exited = threading.Event()

    def _run_icon():
        try:
            icon.run()
        except Exception:
            log.exception("Трей: message loop упал — работаю без трея")
        finally:
            exited.set()

    thread = threading.Thread(target=_run_icon, daemon=True, name="tray")
    thread.start()
    deadline = time.monotonic() + max(0.0, check_after)
    while True:
        if not exited.is_set() and getattr(icon, "visible", False):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0 or exited.is_set():
            log.warning("Трей не готов — окно останется доступным")
            # stop can block in a failed backend, never stall GUI startup.
            def _stop_failed():
                try:
                    icon.stop()
                except Exception:
                    log.debug("Трей: остановка не удалась", exc_info=True)
            threading.Thread(target=_stop_failed, daemon=True, name="tray-cleanup").start()
            return None
        exited.wait(min(0.05, remaining))
    log.info("Трей: значок %s готов (проверьте также скрытые значки Windows)", APP_NAME)

    def _monitor():
        exited.wait()
        # Explicit disable / exit also stops the loop. Caller decides whether
        # this is still the active icon, preventing stale callbacks on replacement.
        if on_fail is not None:
            try:
                on_fail(icon)
            except Exception:
                log.exception("Трей: обработчик остановки упал")

    threading.Thread(target=_monitor, daemon=True, name="tray-check").start()
    return icon
