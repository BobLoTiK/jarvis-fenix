"""Иконка в системном трее (pystray).

ВРЕМЕННО ОТКЛЮЧЕН — см. main.py.
Проблема: pystray требует свой Windows message loop, а главный поток
занят Flet'ом (ft.run блокирует).
Правильное решение — отдельный процесс tray_runner.py (в планах).

Пока этот модуль лежит без дела, но пути здесь уже правильные —
чтобы при включении трея не было сюрпризов.
"""

import logging
import os

import pystray
from PIL import Image, ImageDraw

from jarvis import APP_NAME, __version__, actions

log = logging.getLogger("jarvis.tray")


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=(18, 32, 58, 255), outline=(86, 156, 255, 255), width=3)
    # стилизованная «J»
    d.line((38, 16, 38, 42), fill=(86, 156, 255, 255), width=6)
    d.arc((20, 30, 42, 52), start=20, end=180, fill=(86, 156, 255, 255), width=6)
    return img


def build_tray(jarvis) -> pystray.Icon:
    def on_toggle(icon, item):
        jarvis.listening_enabled = not jarvis.listening_enabled
        log.info("Прослушивание: %s", jarvis.listening_enabled)

    def on_screenshot(icon, item):
        actions.take_screenshot()

    def on_show_window(icon, item):
        """Показать окно GUI (для launch_mode=tray)."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
        else:
            log.warning("GUI не запущен — окно показать нельзя")

    def on_open_settings(icon, item):
        """Открыть GUI и переключиться на вкладку «Настройки»."""
        if getattr(jarvis, "gui", None) is not None:
            jarvis.gui.show_window()
            jarvis.gui.open_settings_tab()
        else:
            log.warning("GUI не запущен — настройки открыть нельзя")

    def on_config(icon, item):
        """Открыть config.json из USER_DIR (%APPDATA%\\Phoenix).

        Раньше было jarvis.base_dir/"config.json" — неверно, потому что
        config теперь живёт в USER_DIR, а не рядом с кодом.
        """
        from jarvis import paths as _paths
        try:
            os.startfile(str(_paths.config_path()))
        except Exception:
            log.exception("Не удалось открыть config.json")

    def on_log(icon, item):
        """Открыть jarvis.log из USER_DIR."""
        from jarvis import paths as _paths
        try:
            os.startfile(str(_paths.logs_dir() / "jarvis.log"))
        except Exception:
            log.exception("Не удалось открыть jarvis.log")

    def on_exit(icon, item):
        jarvis.shutdown()
        icon.stop()

    menu = pystray.Menu(
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
    return pystray.Icon("jarvis", _make_icon_image(), f"{APP_NAME} v{__version__}", menu)