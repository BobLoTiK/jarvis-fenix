"""Ручная проверка UIA в браузере — без хардкода конкретного браузера."""

import time
from jarvis import uia

print("=" * 60)
print("UIA — ручная проверка")
print("=" * 60)

# 1. Список всех видимых окон.
print()
print("[1] Видимые окна системы:")
windows = uia.list_windows()
for i, w in enumerate(windows[:20], 1):
    print(f"    {i:2}. {w}")

# 2. Запущенные браузеры.
print()
print("[2] Запущенные браузеры:")
browsers = uia.list_browsers()
for exe, human in browsers:
    print(f"    - {human} ({exe})")

# 3. Найти окно браузера.
print()
print("[3] Ищу окно браузера...")
browser = uia.find_browser_window()
if browser is None:
    print("    НЕ найдено.")
else:
    print(f"    нашёл: {browser.Name}")

    # 4. Активировать и ждать.
    print()
    print("[4] Активирую + жду 1.0 сек...")
    try:
        browser.SetActive()
        browser.SetFocus()
        time.sleep(1.0)  # ← было 0.5, увеличили
        print("    ок")
    except Exception as e:
        print(f"    ошибка: {e}")

    # 5. Данные.
    print()
    print("[5] Читаю данные:")
    print("    URL:  ", uia.read_browser_url() or "(пусто)")
    print("    TAB:  ", uia.read_browser_tab_title() or "(пусто)")
    print("    TABS: ", uia.read_browser_tabs() or "(пусто)")

print()
print("=" * 60)