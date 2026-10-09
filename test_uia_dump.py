"""Дамп дерева UIA активного окна браузера.

Показывает, какие контролы видит UIA. По нему видно,
есть ли EditControl (адресная строка), TabItem (вкладки).
"""

from jarvis import uia
import uiautomation as auto


def dump_tree(ctrl, depth=0, max_depth=8):
    if depth > max_depth:
        return
    try:
        ctype = ctrl.ControlTypeName
        cname = (ctrl.Name or "").strip()
        # Показываем только «интересное»: Edit, Document, Tab, Button.
        if ctype in ("EditControl", "DocumentControl", "TabItemControl",
                     "TabControl", "ButtonControl", "ToolBarControl"):
            name_short = cname[:80] if cname else ""
            print(f"{'  ' * depth}[{ctype}] {name_short!r}")
        for child in ctrl.GetChildren():
            dump_tree(child, depth + 1, max_depth)
    except Exception:
        pass


print("Ищу браузер...")
browser = uia.find_browser_window()
if browser is None:
    print("Браузер не найден.")
    raise SystemExit(1)

print(f"Окно: {browser.Name}")
print()
print("Дерево UIA (только Edit/Document/Tab/Button):")
print("-" * 60)
dump_tree(browser)
print("-" * 60)