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


def build_icon(jarvis):
    """Создаёт pystray.Icon (message loop не запускает)."""
    import pystray

    return pystray.Icon(
        ICON_NAME,
        _make_icon_image(),
        f"{APP_NAME} v{__version__}",
        build_menu(jarvis),
    )


def start_tray(jarvis, check_after: float = 3.0, on_fail=None):
    """Поднимает иконку в фоне. Возвращает Icon или None (трея не будет).

    Вызывать ДО ft.run(): pystray создаёт собственный message loop, и если
    запускать его после того, как главный поток ушёл в Flet, иконка
    может не появиться вовсе.

    on_fail — callback, если иконка не появилась за check_after: мёртвый
    трей опаснее отсутствия — «крестик» спрятал бы окно навсегда, а
    вернуть его было бы нечем.
    """
    try:
        icon = build_icon(jarvis)
    except Exception:
        log.exception("Трей: pystray/PIL недоступны — работаю без трея")
        return None

    def _run_icon():
        try:
            icon.run()
        except Exception:
            log.exception("Трей: message loop упал — работаю без трея")

    thread = threading.Thread(target=_run_icon, daemon=True, name="tray")
    thread.start()

    def _check_visible():
        """Убеждаемся, что иконка реально появилась (иначе трей молча мёртв)."""
        deadline = time.time() + max(0.0, check_after)
        while time.time() < deadline:
            if getattr(icon, "visible", False):
                log.info("Трей: иконка в системном трее (поток %s)", thread.name)
                return
            time.sleep(0.2)
        if getattr(icon, "visible", False):
            return
        log.warning("Трей: иконка не появилась за %.1f с (поток %s) — "
                    "работаю без трея", check_after,
                    "жив" if thread.is_alive() else "упал")
        try:
            icon.stop()
        except Exception:
            log.debug("Трей: не удалось снять невидимую иконку", exc_info=True)
        if on_fail is not None:
            try:
                on_fail()
            except Exception:
                log.exception("Трей: on_fail упал")

    threading.Thread(target=_check_visible, daemon=True,
                     name="tray-check").start()
    return icon
