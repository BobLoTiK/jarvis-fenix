"""UIA-команды голосом: «прочитай окно», «закрой вкладку ютуб», «какой сайт».

Быстрые правила — БЕЗ LLM. Если фраза явно про окно/вкладку/браузер —
обрабатываем здесь. Иначе None → идём дальше.

В реестре ставится ВЫШЕ open_fast — иначе «закрой вкладку ютуб»
перехватится как «закрой окно».

Если библиотеки `uiautomation` нет (CI-раннер, «голая» Windows) — отвечаем
понятным отказом «UI Automation недоступна...», а не падаем в LLM.

Проверяемся ПЕРЕД каждым действием, которое UIA требует (`_require_uia`),
а не на входе: «нажми enter» и «закрой вкладку эту» (Ctrl+W) — это клавиши,
они работают и без библиотеки.
"""

import logging
import re

from jarvis import uia

log = logging.getLogger("jarvis.intents")

# Что ответить, если библиотеки нет (CI-раннер, «голая» Windows).
# Раньше в этом случае обработчик падал, стадия глотала исключение,
# и человек получал «LLM недоступна» — то есть вообще непонятно, что случилось.
UIA_MISSING_REPLY = (
    "UI Automation недоступна: не установлена библиотека uiautomation. "
    f"Установите её: {uia.UIA_PIP_HINT}"
)


def _tabs_unreadable() -> bool:
    """Браузер не отдаёт список вкладок? (видна только активная — и всё)

    Это случай Яндекса с группировкой вкладок: по вкладкам UIA видит
    одну активную, выбрать вкладку нельзя, и остаётся только Ctrl+W.
    """
    try:
        return len(uia.read_browser_tabs()) <= 1
    except Exception:
        log.debug("read_browser_tabs не сработал", exc_info=True)
        return True


def _require_uia() -> None:
    """Нет библиотеки `uiautomation` → бросаем `UIAUnavailable`.

    Так команда честно скажет «UI Automation недоступна», вместо того
    чтобы вернуть вводящее в заблуждение «не вижу вкладок…». Именно так
    вело себя CI: там библиотеки нет И браузер не запущен, поэтому поиск
    окна (`find_browser_window`) отдавал None ещё до обращения к UIA —
    и причина отказа терялась.
    """
    if not uia.is_supported():
        raise uia.UIAUnavailable(f"нет библиотеки ({uia.UIA_PIP_HINT})")


def uia_fast(handler, cmd: str) -> str | None:
    """Быстрые команды UIA. None, если не наша.

    Ветки, которым UIA не нужна («нажми enter», «закрой вкладку эту»),
    работают и без библиотеки — поэтому проверяем не вход, а именно вызов
    UIA: исключение ловим здесь, а не в стадии.
    """
    try:
        return _uia_fast_impl(handler, cmd)
    except uia.UIAUnavailable:
        log.warning("UIA недоступна, отвечаю отказом: %r", cmd)
        return UIA_MISSING_REPLY


def _uia_fast_impl(handler, cmd: str) -> str | None:
    """Тело быстрых UIA-команд (см. `uia_fast`)."""

    # === Активное окно — что открыто ===
    if re.search(r"(что|какое)\s+(у\s+меня\s+)?(открыто|окно|приложение)", cmd) \
            or cmd in {"что открыто", "какое окно", "активное окно"}:
        _require_uia()
        return uia.describe_active_window()

    # === Прочитать текст активного окна ===
    if re.search(r"(прочитай|что\s+написано|что\s+в)\s+(в\s+)?(окн|блокнот|текст|документ)",
                 cmd) \
            or cmd in {"прочитай окно", "прочитай блокнот", "что в блокноте",
                       "что написано в окне"}:
        _require_uia()
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
        _require_uia()
        url = uia.read_browser_url()
        if not url:
            return "Активное окно — не браузер, или не вижу URL."
        return f"Открыт сайт: {url}"

    # === Заголовок активной вкладки ===
    if re.search(r"(что|какая)\s+(за\s+)?(вкладка|страница)", cmd) \
            or cmd in {"какая вкладка", "что за вкладка"}:
        _require_uia()
        title = uia.read_browser_tab_title()
        if not title:
            return "Активное окно — не браузер."
        return f"Активная вкладка: {title}"

    # === Список вкладок ===
    if re.search(r"(какие|список|покажи)\s+вкладк", cmd) \
            or cmd in {"какие вкладки", "список вкладок", "покажи вкладки"}:
        _require_uia()
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
            # Закрытие текущей вкладки — просто Ctrl+W, UIA не нужна.
            from jarvis import actions
            actions.hotkey(["ctrl", "w"])
            return "Закрыл текущую вкладку."
        # Остальные вкладки ищем через UIA.
        _require_uia()
        ok = uia.close_browser_tab(target)
        if not ok and _tabs_unreadable() and uia.active_tab_matches(target):
            # Вкладки через UIA не видны (Яндекс группирует их), но нужная
            # вкладка активна — значит хватит Ctrl+W.
            #
            # Когда список вкладок читается, `close_browser_tab` сам выбирает
            # вкладку и жмёт Ctrl+W (`_close_tab_by_hotkey`). Жать второй раз
            # нельзя: закрылась бы следующая вкладка с тем же названием —
            # «ютуб» часто открыт не в одном экземпляре.
            from jarvis import actions
            actions.hotkey(["ctrl", "w"])
            log.info("Вкладка %r активна — закрыл через Ctrl+W", target)
            ok = True
        return f"Закрыл вкладку {target}." if ok else f"Вкладку «{target}» не нашёл."

    # === Переключиться на вкладку ===
    m = re.search(r"переключ\w*\s+(?:на\s+)?вкладк\w*\s+(.+)", cmd) \
        or re.search(r"перейди\s+на\s+вкладк\w*\s+(.+)", cmd)
    if m:
        target = m.group(1).strip().rstrip(".,!?")
        _require_uia()
        ok = uia.switch_browser_tab(target)
        if not ok and uia.active_tab_matches(target):
            # Вкладки через UIA не видно, но нужная уже активна.
            ok = True
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
        # Остальные кнопки ищем через UIA.
        _require_uia()
        ok = uia.click_button(target)
        return f"Нажал «{target}»." if ok else f"Кнопку «{target}» не нашёл."

    return None