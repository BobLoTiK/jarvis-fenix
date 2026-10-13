"""Тесты jarvis.uia — логика обёртки. С моками.

CI не имеет браузера, поэтому все внешние вызовы замоканы.
Проверяем:
    - Как разбираются результаты FindAll/FindAllControls.
    - Как работают fallback'и (заголовок окна → URL).
    - Как ведёт себя describe_active_window.
    - Как русские названия вкладок сопоставляются с латинскими заголовками
      («ютуб» ↔ «(2) YouTube»): из-за этого не закрывалась вкладка.
    - Что закрытие вкладки подтверждается СПИСКОМ вкладок, а не возвратом
      `Invoke()`: кнопка закрытия в Яндексе скрыта до наведения, и нажатие
      «успешно» ничего не делает — тогда закрываем средним кликом по
      вкладке, а если и он не сработал — выбор вкладки + Ctrl+W.
    - Что бывает, когда библиотеки `uiautomation` вообще нет (CI-раннер):
      тогда UIAUnavailable + is_supported() == False, а не голый ImportError.
    - Что запасной ход Ctrl+W один на оба пути (fast-фраза и интент
      `uia_close_tab`), и что «закрой браузер» знает все 20+ браузеров.
"""

from unittest.mock import patch, MagicMock

import pytest

from jarvis import actions, uia


# =================================================================
# list_windows
# =================================================================

def test_list_windows_empty():
    """Пустое дерево → пустой список."""
    fake_root = MagicMock()
    fake_root.GetChildren.return_value = []
    fake_auto = MagicMock()
    fake_auto.GetRootControl.return_value = fake_root

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto):
        result = uia.list_windows()

    assert result == []


def test_list_windows_names():
    """Имена окон собираются, пустые — пропускаются."""
    w1 = MagicMock()
    w1.Name = "Chrome"
    w2 = MagicMock()
    w2.Name = ""
    w3 = MagicMock()
    w3.Name = "VS Code"

    fake_root = MagicMock()
    fake_root.GetChildren.return_value = [w1, w2, w3]
    fake_auto = MagicMock()
    fake_auto.GetRootControl.return_value = fake_root

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto):
        result = uia.list_windows()

    assert result == ["Chrome", "VS Code"]


# =================================================================
# describe_active_window
# =================================================================

def test_describe_active_window_ok():
    """Заголовок есть → возвращаем фразу."""
    fake_w = MagicMock()
    fake_w.Name = "Chrome"
    with patch.object(uia, "get_active_window", return_value=fake_w):
        result = uia.describe_active_window()
    assert "Chrome" in result


def test_describe_active_window_none():
    """Окна нет → сообщение."""
    with patch.object(uia, "get_active_window", return_value=None):
        result = uia.describe_active_window()
    assert "Не вижу" in result


# =================================================================
# describe_browsers
# =================================================================

def test_describe_browsers_empty():
    with patch.object(uia, "list_browsers", return_value=[]):
        result = uia.describe_browsers()
    assert "не вижу" in result.lower()


def test_describe_browsers_found():
    fake = [("chrome.exe", "Chrome"), ("msedge.exe", "Edge")]
    with patch.object(uia, "list_browsers", return_value=fake):
        result = uia.describe_browsers()
    assert "Chrome" in result
    assert "Edge" in result


# =================================================================
# read_browser_tab_title
# =================================================================

def test_read_browser_tab_title_no_browser():
    """Нет браузера → пустая строка."""
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_tab_title() == ""


def test_read_browser_tab_title_strips_suffix():
    """«Страница — Яндекс Браузер» → «Страница»."""
    fake_w = MagicMock()
    fake_w.Name = "YouTube — Яндекс Браузер"
    with patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tab_title()
    assert result == "YouTube"


def test_read_browser_tab_title_no_suffix():
    """Без разделителя — возвращаем как есть."""
    fake_w = MagicMock()
    fake_w.Name = "YouTube"
    with patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tab_title()
    assert result == "YouTube"


# =================================================================
# read_browser_tabs
# =================================================================

def test_read_browser_tabs_no_browser():
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_tabs() == []


def test_read_browser_tabs_from_toolbar():
    """Toolbar 'Вкладки' содержит TabItem-детей."""
    fake_tab1 = MagicMock()
    fake_tab1.ControlTypeName = "TabItemControl"
    fake_tab1.Name = "YouTube"
    fake_tab2 = MagicMock()
    fake_tab2.ControlTypeName = "TabItemControl"
    fake_tab2.Name = "GitHub"
    fake_tab3 = MagicMock()
    fake_tab3.ControlTypeName = "ButtonControl"
    fake_tab3.Name = "Новая вкладка"

    fake_toolbar = MagicMock()
    fake_toolbar.Exists.return_value = True
    fake_toolbar.GetChildren.return_value = [fake_tab3, fake_tab1, fake_tab2]

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.ToolBarControl.return_value = fake_toolbar
    # Тип контрола сравнивается по имени (`ControlTypeName`) — как в
    # настоящем uiautomation. Модульные константы тут не нужны.

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tabs()

    assert result == ["YouTube", "GitHub"]


def test_read_browser_tabs_fallback():
    """Пусто → fallback на активную вкладку."""
    fake_toolbar = MagicMock()
    fake_toolbar.Exists.return_value = False

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.ToolBarControl.return_value = fake_toolbar

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_tabs()

    assert result == ["YouTube"]


# =================================================================
# Сопоставление имён вкладок: «ютуб» ↔ «(2) YouTube»
#
# Из-за этого не закрывалась вкладка: человек говорит «ютуб», а заголовок
# вкладки — латиницей, и «ютуб» in «(2) youtube» давало False.
# =================================================================

def test_title_matches_same_alphabet_substring():
    """Обычное вхождение подстроки — как было до сопоставления."""
    assert uia.title_matches("YouTube — Яндекс Браузер", "youtube") is True
    assert uia.title_matches("Моддинг для Minecraft", "моддинг") is True
    assert uia.title_matches("ЮТУБ — Яндекс Браузер", "ютуб") is True


def test_title_matches_russian_name_of_latin_tab():
    """«ютуб» находит вкладку «(2) YouTube»."""
    assert uia.title_matches("(2) YouTube", "ютуб") is True
    assert uia.title_matches(
        "(2) Forge Modding Tutorial - Minecraft 1.20.1 #39 - YouTube", "ютуб"
    ) is True
    assert uia.title_matches("YouTube Music", "ютуб") is True


def test_title_matches_alias_and_translit():
    """Алиасы (вк → vk) и транслитерация (хабр → habr)."""
    assert uia.title_matches("vk.com — Chrome", "вк") is True
    assert uia.title_matches("ВКонтакте", "вк") is True
    assert uia.title_matches("habr.com — Chrome", "хабр") is True
    assert uia.title_matches("GitHub — Chrome", "гитхаб") is True
    assert uia.title_matches("ru.wikipedia.org", "википедия") is True


def test_title_matches_latin_query_russian_title():
    """И обратно: сказали «youtube», а вкладка называется «Ютуб»."""
    assert uia.title_matches("Ютуб", "youtube") is True


def test_title_matches_no_false_positive():
    """Ложных срабатываний быть не должно.

    «вк» → «vk» совпадало с «vkhoda» («без входа») — так ловилась чужая
    вкладка. Поэтому разные алфавиты сравниваем пословно.
    """
    assert uia.title_matches(
        'Заказ "24/7(Без входа) DeepSeek API | Пополнение баланса"', "вк"
    ) is False
    assert uia.title_matches("DeepSeek Platform", "ютуб") is False
    assert uia.title_matches("moodle.nntc.nnov.ru", "ютуб") is False
    assert uia.title_matches("", "ютуб") is False
    assert uia.title_matches("YouTube", "") is False


def _fake_tab(name: str, control_type: str = "TabItemControl"):
    """Вкладка-заглушка. Тип — строкой, как у настоящего uiautomation."""
    tab = MagicMock()
    tab.ControlTypeName = control_type
    tab.Name = name
    return tab


def _fake_close_button(name: str = "Закрыть"):
    """Кнопка закрытия внутри вкладки."""
    btn = MagicMock()
    btn.ControlTypeName = "ButtonControl"
    btn.Name = name
    return btn


class _TabList:
    """Список вкладок, который меняется после действия.

    Так же ведёт себя настоящий браузер: закрытие видно только по тому,
    что вкладок стало меньше.
    """

    def __init__(self, before, after=None):
        self.before = before
        self.after = after if after is not None else before
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.before if self.calls == 1 else self.after


def test_close_browser_tab_closes_and_verifies_by_tab_list():
    """«закрой вкладку ютуб» закрывает «(2) YouTube» и ПРОВЕРЯЕТ результат."""
    btn = _fake_close_button()
    tab = _fake_tab("(2) YouTube")
    tab.GetChildren.return_value = [btn]

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    tabs = _TabList(["(2) YouTube", "Почта"], ["Почта"])

    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs", side_effect=tabs), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.05):
        assert uia.close_browser_tab("ютуб") is True

    btn.GetInvokePattern().Invoke.assert_called_once_with()
    tab.MiddleClick.assert_not_called()


def test_close_browser_tab_middle_click_when_button_is_inert():
    """Кнопка закрытия «нажалась», но вкладка жива → средний клик по вкладке.

    Так ведёт себя Яндекс: кнопка закрытия скрыта до наведения, и
    `Invoke()` отдаёт True, ничего не сделав.
    """
    btn = _fake_close_button()
    tab = _fake_tab("YouTube")
    tab.GetChildren.return_value = [btn]

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    state = {"clicked": False}

    def tabs_now():
        return ["Почта"] if state["clicked"] else ["YouTube", "Почта"]

    def middle_click(x=None, y=None):
        state["clicked"] = True

    tab.MiddleClick.side_effect = middle_click

    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs", side_effect=tabs_now), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.02):
        assert uia.close_browser_tab("ютуб") is True

    btn.GetInvokePattern().Invoke.assert_called_once_with()
    tab.MiddleClick.assert_called_once()


class _DeadTab:
    """Вкладка, чей UIA-элемент «умирает» сразу после закрытия.

    Живой случай: после закрытия вкладки обращение к `Name` бросает
    COMError «элемент больше не доступен» — и ответ на команду падал
    вместо «закрыл»/«не нашёл».
    """

    def __init__(self, title: str, children: list):
        self.ControlTypeName = "TabItemControl"
        self._title = title
        self._children = children
        self.closed = False

    @property
    def Name(self):
        if self.closed:
            raise RuntimeError("COMError: элемент больше не доступен")
        return self._title

    def GetChildren(self):
        return self._children


def test_close_browser_tab_survives_vanished_element():
    """Закрыли — и элемент умер: имя уже прочитано, падать не на чем."""
    btn = _fake_close_button()
    tab = _DeadTab("YouTube", [btn])
    btn.GetInvokePattern.return_value.Invoke.side_effect = \
        lambda: setattr(tab, "closed", True)

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    tabs = _TabList(["YouTube", "Почта"], ["Почта"])

    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs", side_effect=tabs), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.05):
        assert uia.close_browser_tab("ютуб") is True


def test_close_browser_tab_other_tab_not_touched():
    """Ничего похожего нет → не закрываем, не жмём горячие клавиши."""
    btn = _fake_close_button()
    tab = _fake_tab("DeepSeek Platform")
    tab.GetChildren.return_value = [btn]

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    hotkeys = []
    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab("ютуб") is False

    btn.GetInvokePattern().Invoke.assert_not_called()
    assert hotkeys == []


def test_close_browser_tab_falls_back_to_ctrl_w():
    """Кнопка «нажалась», но вкладка не закрылась → выбираем и Ctrl+W.

    Так ведёт себя Яндекс: кнопка закрытия внутри вкладки скрыта до
    наведения, `Invoke()` возвращает True и ничего не делает.
    """
    btn = _fake_close_button()
    tab = _fake_tab("YouTube")
    tab.GetChildren.return_value = [btn]

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    state = {"pressed": False}

    def tabs_now():
        return ["Почта"] if state["pressed"] else ["YouTube", "Почта"]

    def hotkey(keys):
        state["pressed"] = True
        return True

    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs", side_effect=tabs_now), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.02), \
         patch.object(actions, "hotkey", side_effect=hotkey):
        assert uia.close_browser_tab("ютуб") is True

    tab.GetSelectionItemPattern().Select.assert_called_once_with()
    fake_w.SetActive.assert_called_once_with()


def test_close_browser_tab_no_hotkey_when_tab_not_selected():
    """Вкладку выбрать не удалось и активна не она → Ctrl+W запрещён.

    Иначе Ctrl+W закрыл бы соседнюю вкладку — не ту, которую просили.
    """
    btn = _fake_close_button()
    tab = _fake_tab("YouTube")
    tab.GetChildren.return_value = [btn]
    tab.GetSelectionItemPattern.return_value.Select.side_effect = \
        RuntimeError("нет паттерна SelectionItem")

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    hotkeys = []
    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs",
                      return_value=["YouTube", "Почта"]), \
         patch.object(uia, "read_browser_tab_title", return_value="DeepSeek"), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.02), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab("ютуб") is False

    assert hotkeys == []


def test_close_browser_tab_honest_false_when_nothing_closes():
    """Ни кнопка, ни Ctrl+W не помогли → честное False, а не «закрыл»."""
    btn = _fake_close_button()
    tab = _fake_tab("YouTube")
    tab.GetChildren.return_value = [btn]

    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    hotkeys = []
    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w), \
         patch.object(uia, "read_browser_tabs",
                      return_value=["YouTube", "Почта"]), \
         patch.object(uia, "_CLOSE_POLL", 0.001), \
         patch.object(uia, "_CLOSE_WAIT", 0.02), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab("ютуб") is False

    assert hotkeys == [["ctrl", "w"]]


def test_switch_browser_tab_russian_name():
    """«переключись на вкладку ютуб» находит «YouTube Music»."""
    tab = _fake_tab("YouTube Music")
    fake_w = MagicMock()
    fake_w.GetChildren.return_value = [tab]

    with patch.object(uia, "_ensure_init", return_value=MagicMock()), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        assert uia.switch_browser_tab("ютуб") is True

    tab.GetSelectionItemPattern().Select.assert_called_once_with()


def test_active_tab_matches_russian_query():
    """Запасной ход: активная «YouTube» — это «ютуб»."""
    fake_w = MagicMock()
    fake_w.Name = "YouTube — Яндекс Браузер"

    with patch.object(uia, "_get_browser_window", return_value=fake_w):
        assert uia.active_tab_matches("ютуб") is True
        assert uia.active_tab_matches("вк") is False


def test_active_tab_matches_no_browser():
    """Браузера нет → запасной ход не срабатывает."""
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.active_tab_matches("ютуб") is False


# =================================================================
# Единый список браузеров: UIA и «закрой браузер» — из одного места
# =================================================================

def test_browser_process_names_is_a_single_list():
    """Имена для «закрой браузер» берутся из того же списка, что и поиск окна.

    В `actions.close_browser` был свой короткий список из шести имён, и
    команда молча не трогала Vivaldi, Arc, Opera GX, Chromium, LibreWolf,
    Tor и других — хотя окно такого браузера UIA находит.
    """
    names = uia.browser_process_names()

    assert names == sorted(uia._BROWSER_PROCESSES)
    for exe in ("vivaldi.exe", "arc.exe", "opera_gx.exe", "chromium.exe",
                "librewolf.exe", "waterfox.exe", "tor.exe"):
        assert exe in names


def test_close_browser_tries_every_known_browser():
    """«закрой браузер» пробует ВСЕ известные браузеры, и закрывает все.

    №89: ранний выход закрывал только первый найденный браузер.
    """
    killed = []

    def fake_kill(name):
        killed.append(name)
        return True

    with patch.object(actions, "kill_process", side_effect=fake_kill):
        assert actions.close_browser() is True

    assert killed == uia.browser_process_names()


def test_close_browser_false_when_nothing_is_running():
    """Ни одного браузера → честное False (ответ «не запущен»)."""
    with patch.object(actions, "kill_process", return_value=False):
        assert actions.close_browser() is False


# =================================================================
# Запасные ходы закрытия/переключения вкладки — один код на оба пути
# =================================================================

def test_close_tab_with_fallback_uses_ctrl_w_when_tabs_unreadable():
    """Список вкладок не читается, нужная активна → Ctrl+W."""
    hotkeys = []
    with patch.object(uia, "close_browser_tab", return_value=False), \
         patch.object(uia, "read_browser_tabs", return_value=["DeepSeek"]), \
         patch.object(uia, "active_tab_matches", return_value=True), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab_with_fallback("ютуб") is True

    assert hotkeys == [["ctrl", "w"]]


def test_close_tab_with_fallback_no_second_ctrl_w_when_list_is_readable():
    """Список вкладок виден → второе Ctrl+W закрыло бы соседнюю вкладку."""
    hotkeys = []
    with patch.object(uia, "close_browser_tab", return_value=False), \
         patch.object(uia, "read_browser_tabs",
                      return_value=["YouTube", "Почта"]), \
         patch.object(uia, "active_tab_matches", return_value=True), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab_with_fallback("ютуб") is False

    assert hotkeys == []


def test_close_tab_with_fallback_is_honest_when_nothing_matches():
    """Ни по имени, ни в активной → False, Ctrl+W не жмём."""
    hotkeys = []
    with patch.object(uia, "close_browser_tab", return_value=False), \
         patch.object(uia, "read_browser_tabs", return_value=["DeepSeek"]), \
         patch.object(uia, "active_tab_matches", return_value=False), \
         patch.object(actions, "hotkey", side_effect=hotkeys.append):
        assert uia.close_browser_tab_with_fallback("ютуб") is False

    assert hotkeys == []


def test_switch_tab_with_fallback_counts_active_tab_as_success():
    """Переключаться некуда, но вкладка уже активна → это успех."""
    with patch.object(uia, "switch_browser_tab", return_value=False), \
         patch.object(uia, "active_tab_matches", return_value=True):
        assert uia.switch_browser_tab_with_fallback("ютуб") is True


def test_switch_tab_with_fallback_false_when_nowhere_to_switch():
    with patch.object(uia, "switch_browser_tab", return_value=False), \
         patch.object(uia, "active_tab_matches", return_value=False):
        assert uia.switch_browser_tab_with_fallback("ютуб") is False


def test_intent_close_tab_uses_the_same_fallback():
    """Интент-путь (`uia_close_tab`) получает тот же запасной ход Ctrl+W.

    Раньше запасной ход жил только в `fast/uia.py`, и на Яндексе (список
    вкладок не читается) интент отвечал «Вкладку «ютуб» не нашёл».
    """
    from jarvis.intents.execute import _do_uia_close_tab

    with patch.object(uia, "close_browser_tab", return_value=False), \
         patch.object(uia, "read_browser_tabs", return_value=["DeepSeek"]), \
         patch.object(uia, "active_tab_matches", return_value=True), \
         patch.object(actions, "hotkey") as hotkey:
        reply = _do_uia_close_tab(None, None, "ютуб", None)

    assert reply == "Закрыл вкладку ютуб."
    hotkey.assert_called_once_with(["ctrl", "w"])


def test_intent_switch_to_current_tab_says_already_open():
    """«переключись на эту вкладку» через интент — не поход в UIA."""
    from jarvis.intents.execute import _do_uia_switch_tab

    with patch.object(uia, "switch_browser_tab") as switch:
        reply = _do_uia_switch_tab(None, None, "эту", None)

    assert reply == "Эта вкладка уже открыта."
    switch.assert_not_called()


# =================================================================
# read_browser_url
# =================================================================

def test_read_browser_url_no_browser():
    with patch.object(uia, "_get_browser_window", return_value=None):
        assert uia.read_browser_url() == ""


def test_read_browser_url_from_edit():
    """EditControl с http URL → возвращаем."""
    fake_edit = MagicMock()
    fake_edit.Exists.return_value = True
    value_pattern = MagicMock()
    value_pattern.Value = "https://youtube.com/watch?v=abc"
    fake_edit.GetValuePattern.return_value = value_pattern

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.EditControl.return_value = fake_edit

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_url()

    assert result == "https://youtube.com/watch?v=abc"


def test_read_browser_url_fallback_from_title():
    """Edit пустой → берём домен из заголовка."""
    fake_edit = MagicMock()
    fake_edit.Exists.return_value = False

    fake_w = MagicMock()
    fake_w.Name = "youtube.com — Chrome"

    fake_auto = MagicMock()
    fake_auto.EditControl.return_value = fake_edit

    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "_get_browser_window", return_value=fake_w):
        result = uia.read_browser_url()

    assert result == "https://youtube.com"


# =================================================================
# is_available
# =================================================================

def test_is_available_true():
    fake_w = MagicMock()
    fake_auto = MagicMock()
    with patch.object(uia, "_ensure_init", return_value=fake_auto), \
         patch.object(uia, "_uia", fake_auto), \
         patch.object(uia, "get_active_window", return_value=fake_w):
        assert uia.is_available() is True


def test_is_available_false():
    with patch.object(uia, "_ensure_init", side_effect=ImportError("no uia")):
        assert uia.is_available() is False


# =================================================================
# Библиотеки uiautomation нет (CI-раннер, «голая» Windows)
# =================================================================

def _without_uiautomation():
    """Контекст: `import uiautomation` падает, как на CI-раннере."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "uiautomation":
            raise ImportError("No module named 'uiautomation' (CI)")
        return real_import(name, *args, **kwargs)

    return patch.object(builtins, "__import__", fake_import)


def test_uia_unavailable_is_import_error():
    """UIAUnavailable — наследник ImportError: старый код ловит как раньше."""
    assert issubclass(uia.UIAUnavailable, ImportError)


def test_ensure_init_without_library_raises_uia_unavailable():
    """Нет библиотеки → UIAUnavailable (её ловят быстрые команды)."""
    with patch.object(uia, "_uia", None), _without_uiautomation():
        with pytest.raises(uia.UIAUnavailable) as exc:
            uia._ensure_init()
    assert "uiautomation" in str(exc.value)


def test_is_supported_false_without_library():
    """Нет библиотеки → False: стресс-тест смягчает ожидания uia_*."""
    with patch.object(uia, "_uia", None), _without_uiautomation():
        assert uia.is_supported() is False


def test_is_supported_true_when_init_ok():
    """Библиотека есть → True (к COM не обращаемся)."""
    fake_auto = MagicMock()
    with patch.object(uia, "_ensure_init", return_value=fake_auto):
        assert uia.is_supported() is True


# =================================================================
# Капкан: у модуля `uiautomation` нет `ControlTypeName`
# =================================================================

def test_no_module_level_control_type_name():
    """В коде нет `uia.ControlTypeName.X` — только `.ControlTypeName` у контрола.

    См. PROMPT.md #43. У модуля `uiautomation` нет атрибута
    `ControlTypeName` (есть `ControlTypeNames` и числа `ControlType`).
    Обращение `uia.ControlTypeName.ButtonControl` бросало AttributeError,
    он глотался `except Exception` внутри обходов дерева — и «закрой
    вкладку ютуб» молча не находила НИ ОДНОЙ вкладки.
    """
    import inspect
    import re

    # Комментарии (где мина и задокументирована) не считаем кодом.
    src = inspect.getsource(uia)
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    bad = re.findall(r"uia\.ControlTypeName\b", code)
    assert not bad, f"uia.ControlTypeName не существует: {bad}"


def test_is_tab_item_uses_instance_type_name():
    """Тип контрола — по строке `ControlTypeName` у самого контрола."""
    tab = _fake_tab("YouTube")
    btn = _fake_close_button()

    assert uia._is_tab_item(tab) is True
    assert uia._is_tab_item(btn) is False
    assert uia._is_button(btn) is True
    assert uia._is_button(tab) is False


def test_is_control_type_survives_broken_control():
    """Контрол с падающим свойством не роняет обход (UIA — COM, бывает)."""
    class Boom:
        @property
        def ControlTypeName(self):
            raise RuntimeError("COM error")

    assert uia._is_control_type(Boom(), "TabItemControl") is False

