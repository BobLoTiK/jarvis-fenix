"""Живая проверка «закрой вкладку ютуб» (без моков).

Показывает, что видит UIA: список вкладок, какие матчатся по «ютуб»,
есть ли внутри вкладки кнопка закрытия.

Ручной прогон (нужен открытый браузер):
    python tests/manual/uia_close_probe.py            # dry-run, ничего не нажимает
    python tests/manual/uia_close_probe.py --close    # реально закрывает вкладку
"""

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Корень проекта: tests/manual/../.. — иначе `import jarvis` не найдётся.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis import uia  # noqa: E402

QUERY = "ютуб"


def find_hits(window):
    """TabItem-попадания: [(имя вкладки, [имена кнопок внутри]), ...]."""
    hits = []
    for ctrl in uia._walk_controls(window, depth=15):
        try:
            if not uia._is_tab_item(ctrl):
                continue
            if not uia.title_matches(ctrl.Name or "", QUERY):
                continue
            buttons = []
            for child in ctrl.GetChildren():
                try:
                    if uia._is_button(child):
                        buttons.append((child.Name or "").strip())
                except Exception:
                    continue
            hits.append(((ctrl.Name or "").strip(), buttons))
        except Exception:
            continue
    return hits


print(f"UIA доступен: {uia.is_supported()}")
window = uia.find_browser_window()
if window is None:
    print("Браузер не найден.")
    raise SystemExit(1)
print(f"Окно: {window.Name}")

tabs = uia.read_browser_tabs()
print(f"\nread_browser_tabs(): {len(tabs)} вкладок")
for name in tabs:
    mark = "   <-- ютуб" if uia.title_matches(name, QUERY) else ""
    print(f"  - {name!r}{mark}")

hits = find_hits(window)
print(f"\nTabItem-попаданий по {QUERY!r}: {len(hits)}")
for name, buttons in hits:
    print(f"  - {name!r}   кнопки внутри: {buttons}")

active = uia.read_browser_tab_title()
print(f"\nАктивная вкладка: {active!r}")
print(f"active_tab_matches({QUERY!r}): {uia.active_tab_matches(QUERY)}")

if "--close" not in sys.argv:
    print("\nDry-run: ничего не нажимаю (реально закрыть — с флагом --close).")
    raise SystemExit(0)

before = len(tabs)
ok = uia.close_browser_tab(QUERY)
time.sleep(1.5)
after = uia.read_browser_tabs()
print(f"\nclose_browser_tab({QUERY!r}) → {ok}")
print(f"Вкладок: {before} → {len(after)}")
print("Закрылось." if len(after) < before else "!! Число вкладок не изменилось")
