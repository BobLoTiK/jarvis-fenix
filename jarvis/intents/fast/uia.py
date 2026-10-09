"""UIA-команды голосом: «прочитай окно», «закрой вкладку ютуб», «какой сайт».

Быстрые правила — БЕЗ LLM. Если фраза явно про окно/вкладку/браузер —
обрабатываем здесь. Иначе None → идём дальше.

В реестре ставится ВЫШЕ open_fast — иначе «закрой вкладку ютуб»
перехватится как «закрой окно».
"""

import logging
import re

from jarvis import uia

log = logging.getLogger("jarvis.intents")


def uia_fast(handler, cmd: str) -> str | None:
    """Быстрые команды UIA. None, если не наша."""

    # === Активное окно — что открыто ===
    if re.search(r"(что|какое)\s+(у\s+меня\s+)?(открыто|окно|приложение)", cmd) \
            or cmd in {"что открыто", "какое окно", "активное окно"}:
        return uia.describe_active_window()

    # === Прочитать текст активного окна ===
    if re.search(r"(прочитай|что\s+написано|что\s+в)\s+(в\s+)?(окн|блокнот|текст|документ)",
                 cmd) \
            or cmd in {"прочитай окно", "прочитай блокнот", "что в блокноте",
                       "что написано в окне"}:
        text = uia.read_active_text_stripped(max_chars=1500)
        if not text:
            return "В активном окне не вижу текста."
        # Ограничим озвучку — читать 4000 символов вслух долго.
        if len(text) > 400:
            text = text[:400] + "... (ещё много)"
        return f"Читаю: {text}"

    # === URL активной вкладки ===
    if re.search(r"(какой|какая)\s+(сайт|url|адрес|ссылка)", cmd) \
            or cmd in {"какой сайт", "какой сайт открыт", "какая ссылка"}:
        url = uia.read_browser_url()
        if not url:
            return "Активное окно — не браузер, или не вижу URL."
        return f"Открыт сайт: {url}"

    # === Заголовок активной вкладки ===
    if re.search(r"(что|какая)\s+(за\s+)?(вкладка|страница)", cmd) \
            or cmd in {"какая вкладка", "что за вкладка"}:
        title = uia.read_browser_tab_title()
        if not title:
            return "Активное окно — не браузер."
        return f"Активная вкладка: {title}"

    # === Список вкладок ===
    if re.search(r"(какие|список|покажи)\s+вкладк", cmd) \
            or cmd in {"какие вкладки", "список вкладок", "покажи вкладки"}:
        tabs = uia.read_browser_tabs()
        if not tabs:
            return "Не вижу открытых вкладок. Возможно, активное окно — не браузер."
        short = tabs[:10]
        return "Открыты: " + "; ".join(short) + "."

    # === Закрыть вкладку ===
    m = re.search(r"закр\w+\s+вкладк\w*\s+(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        if target in ("эту", "текущую", "это"):
            # «закрой эту вкладку» — просто Ctrl+W, безопаснее.
            from jarvis import actions
            actions.hotkey(["ctrl", "w"])
            return "Закрыл текущую вкладку."
        ok = uia.close_browser_tab(target)
        return f"Закрыл вкладку {target}." if ok else f"Вкладку «{target}» не нашёл."

    # === Переключиться на вкладку ===
    m = re.search(r"переключ\w*\s+(?:на\s+)?вкладк\w*\s+(.+)", cmd) \
        or re.search(r"перейди\s+на\s+вкладк\w*\s+(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        ok = uia.switch_browser_tab(target)
        return f"Переключился на {target}." if ok else f"Вкладку «{target}» не нашёл."

    # === Нажать кнопку ===
    m = re.search(r"нажми\s+(?:кнопку\s+)?(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        # «нажми enter» / «нажми tab» — это клавиши, не кнопки.
        if target.lower() in ("enter", "escape", "esc", "tab", "space",
                              "пробел", "энтер", "эскейп"):
            from jarvis import actions
            key = {"пробел": "space", "энтер": "enter", "эскейп": "escape"}.get(
                target.lower(), target.lower()
            )
            actions.key_press(key)
            return f"Нажал {target}."
        ok = uia.click_button(target)
        return f"Нажал «{target}»." if ok else f"Кнопку «{target}» не нашёл."

    return None