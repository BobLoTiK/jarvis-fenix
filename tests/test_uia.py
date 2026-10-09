"""Тесты jarvis.uia — логика обёртки. С моками.

CI не имеет браузера, поэтому все внешние вызовы замоканы.
Проверяем:
    - Как разбираются результаты FindAll/FindAllControls.
    - Как работают fallback'и (заголовок окна → URL).
    - Как ведёт себя describe_active_window.
"""

from unittest.mock import patch, MagicMock

from jarvis import uia


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
    fake_tab1.ControlType = "TabItemControl"
    fake_tab1.Name = "YouTube"
    fake_tab2 = MagicMock()
    fake_tab2.ControlType = "TabItemControl"
    fake_tab2.Name = "GitHub"
    fake_tab3 = MagicMock()
    fake_tab3.ControlType = "ButtonControl"
    fake_tab3.Name = "Новая вкладка"

    fake_toolbar = MagicMock()
    fake_toolbar.Exists.return_value = True
    fake_toolbar.GetChildren.return_value = [fake_tab3, fake_tab1, fake_tab2]

    fake_w = MagicMock()
    fake_w.Name = "YouTube — Chrome"

    fake_auto = MagicMock()
    fake_auto.ToolBarControl.return_value = fake_toolbar
    # Настраиваем ControlType — иначе MagicMock вернёт MagicMock,
    # и сравнение ctrl.ControlType != fake_auto.ControlType.TabItemControl
    # всегда даст True.
    fake_auto.ControlType.TabItemControl = "TabItemControl"

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