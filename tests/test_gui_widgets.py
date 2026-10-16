"""Opt-in layouts, exact task IDs, safe command path, atomic saves and lifecycle."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from jarvis import gui as ui, tasks, profile, mood
from jarvis.config import Config
from jarvis.gui_widgets import normalize_layout, normalize_shortcuts, LAYOUT_KEY, SHORTCUTS_KEY


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setattr(tasks,'_tasks_file',lambda:tmp_path/'tasks.json')
    g=ui.FenixGUI(None,Config(tmp_path/'config.json'))
    g._page=NS(add=Mock(),update=Mock(),window=NS(visible=True,minimized=False))
    g._build_ui(g._page)
    yield g
    g.stop();g._rail.dispose()
    profile.unsubscribe(g._on_profile_switch);mood.unsubscribe(g._on_mood_change)
    ui._apply_palette('dark')


def prepare(gui):
    b=gui._home.widgets;b.begin();b.add_widget('tasks');b.add_widget('shortcuts')
    return b


@pytest.mark.parametrize('raw',[None,False,{},'tasks',42,[None,{}, {'kind':[]}]])
def test_layout_normalization_rejects_invalid_shapes(raw):
    assert normalize_layout(raw)==[]


def test_layout_normalizes_order_sizes_and_duplicate_without_mutation():
    raw=[{'kind':'tasks','size':'wide','evil':True},{'kind':'tasks'},{'kind':'shortcuts','size':'x'},{'kind':'unknown'}]
    copy=deepcopy(raw)
    assert normalize_layout(raw)==[{'kind':'tasks','size':'wide'},{'kind':'shortcuts','size':'compact'}]
    assert raw==copy


@pytest.mark.parametrize('raw',[None,{},'bad',[None,{}, {'label':3,'command':[]} ]])
def test_shortcut_schema_rejects_invalid_values(raw):assert normalize_shortcuts(raw)==[]


def test_shortcut_limit_and_trim():
    values=[{'label':f' {i} ','command':' открой калькулятор '} for i in range(10)]
    assert len(normalize_shortcuts(values))==6
    assert normalize_shortcuts(values)[0]=={'label':'0','command':'открой калькулятор'}


def test_home_empty_by_default_without_task_disk_reads(gui,monkeypatch):
    b=gui._home.widgets
    monkeypatch.setattr(tasks,'list_items',Mock(side_effect=AssertionError('should not read')))
    assert b.layout==[] and not b.visible and not b.editing
    assert not b.refresh_tasks()
    assert gui._home.center_region.expand is True and gui._home.workspace.scroll is None


def test_add_resize_reorder_remove_and_cancel_do_not_persist(gui):
    b=prepare(gui)
    b.resize_widget('tasks');b.move_widget('shortcuts',-1)
    assert b.layout==[{'kind':'shortcuts','size':'compact'},{'kind':'tasks','size':'wide'}]
    assert gui.config.get(LAYOUT_KEY)==[]
    b.remove_widget('tasks');b.cancel()
    assert not b.layout and not b.visible and not b.editing
    assert gui._home.center_region.expand is True


def test_save_persists_and_new_home_loads_layout(gui):
    b=prepare(gui);b.resize_widget('tasks');assert b.save()
    cfg=Config(gui.config.path)
    assert cfg.get(LAYOUT_KEY)==[{'kind':'tasks','size':'wide'},{'kind':'shortcuts','size':'compact'}]
    assert not b.editing and b.visible and gui._home.center_region.height==340


def test_save_failure_and_conflict_keep_editor_and_draft(gui,monkeypatch):
    b=prepare(gui)
    monkeypatch.setattr(gui.config,'update',Mock(return_value=False))
    assert b.save() is False
    assert b.editing and len(b.layout)==2 and b.notice.visible
    assert gui.config.get(LAYOUT_KEY)==[]


def test_conflict_against_real_config_is_detected(gui):
    b=prepare(gui)
    gui.config.set(LAYOUT_KEY,[{'kind':'shortcuts','size':'wide'}])
    assert not b.save() and b.editing
    assert gui.config.get(LAYOUT_KEY)==[{'kind':'shortcuts','size':'wide'}]


def test_drop_order_only_in_edit_and_valid_source(gui):
    b=prepare(gui)
    b.drop('tasks',NS(src=NS(data='shortcuts')))
    assert [x['kind'] for x in b.layout]==['shortcuts','tasks']
    for value in (None,[],{},'foreign'):
        b.drop('tasks',NS(src=NS(data=value)))
    b.save();b.drop('shortcuts',NS(src=NS(data='tasks')))
    assert [x['kind'] for x in b.layout]==['shortcuts','tasks']


def test_exact_task_ids_and_reversible_checkboxes(gui):
    a=tasks.add('одинаково');b=tasks.add('одинаково')
    tasks.set_done(b['id'],True)
    assert tasks.list_items()[0]['done'] is False
    assert tasks.list_items()[1]['done'] is True
    tasks.set_done(b['id'],False)
    assert all(not t['done'] for t in tasks.list_items())
    assert tasks.set_done(999,True) is None
    snap=tasks.list_items();snap[0]['text']='changed'
    assert tasks.list_items()[0]['text']=='одинаково'


@pytest.mark.parametrize('id,done',[(True,True),(1,1),('1',False),(None,True)])
def test_exact_task_set_validates_types(gui,id,done):
    with pytest.raises(ValueError):tasks.set_done(id,done)


def test_add_task_and_mark_share_voice_store_and_empty_guard(gui):
    b=prepare(gui);b.save()
    b.task_input.value=' Купить хлеб '
    assert b.add_task()
    item=tasks.list_items()[0];assert item['text']=='Купить хлеб' and b.task_input.value==''
    b.set_task_done(item['id'],NS(control=NS(value=True)))
    assert tasks.find('хлеб')['done'] is True
    assert not b.add_task()


def test_task_write_failure_keeps_input(gui,monkeypatch):
    b=prepare(gui);b.save();b.task_input.value='не потерять'
    monkeypatch.setattr(tasks,'add',Mock(side_effect=PermissionError()))
    assert not b.add_task() and b.task_input.value=='не потерять'


def test_remove_widget_never_deletes_tasks(gui):
    tasks.add('важное')
    b=prepare(gui);b.remove_widget('tasks');b.save()
    assert tasks.list_items()[0]['text']=='важное'


def test_existing_clock_refresh_reads_only_when_file_changed_and_preserves_draft(gui,monkeypatch):
    b=prepare(gui);b.save();b.task_input.value='недописанное'
    read=Mock(wraps=tasks.list_items);monkeypatch.setattr(tasks,'list_items',read)
    assert not b.refresh_tasks();read.assert_not_called()
    tasks.add('голосом')
    assert b.refresh_tasks();read.assert_called_once()
    assert b.task_input.value=='недописанное'
    assert not b.refresh_tasks()


def test_shortcut_setup_does_not_execute_and_save_accepts_pending_complete_input(gui):
    b=prepare(gui);gui._run_command=Mock()
    b.shortcut_label.value='Калькулятор';b.shortcut_command.value='открой калькулятор'
    assert b.save()
    gui._run_command.assert_not_called()
    assert gui.config.get(SHORTCUTS_KEY)==[{'label':'Калькулятор','command':'открой калькулятор'}]


def test_incomplete_shortcut_prevents_silent_data_loss(gui):
    b=prepare(gui);b.shortcut_label.value='Без команды'
    assert not b.save() and b.editing
    assert b.shortcut_label.value=='Без команды'


def shortcut(gui):
    b=prepare(gui);b.shortcut_label.value='Тест';b.shortcut_command.value='открой калькулятор';b.save()
    return b


def test_shortcut_requires_core_and_pending_confirmation_is_not_bypassed(gui):
    b=shortcut(gui);gui._run_command=Mock(return_value=True)
    assert not b.launch(0);gui._run_command.assert_not_called()
    gui.jarvis=NS(handler=NS(_pending_password={'action':'clear_tasks'},_pending_question=None))
    assert not b.launch(0);gui._run_command.assert_not_called()
    gui.jarvis.handler._pending_password=None;gui.jarvis.handler._pending_question={'text':'yes?'}
    assert not b.launch(0);gui._run_command.assert_not_called()


def test_shortcut_uses_chat_pipeline_and_busy_guard(gui):
    b=shortcut(gui);gui.jarvis=NS(handler=NS(_pending_password=None,_pending_question=None))
    gui._run_command=Mock(return_value=True)
    gui._command_busy=True;assert not b.launch(0);gui._run_command.assert_not_called()
    gui._command_busy=False
    assert b.launch(0)
    assert gui._rail.selected_index==0
    gui._run_command.assert_called_once_with('открой калькулятор')


def test_edit_mode_shortcut_click_never_runs(gui):
    b=shortcut(gui);b.begin();gui._run_command=Mock()
    assert not b.launch(0);gui._run_command.assert_not_called()


def test_theme_preserves_unsaved_layout_shortcuts_and_task_input(gui):
    b=prepare(gui);b.task_input.value='черновик дела'
    b.shortcut_label.value='Браузер';b.shortcut_command.value='открой браузер'
    b.resize_widget('tasks')
    gui._home._theme('Светлая')
    n=gui._home.widgets
    assert n is not b and n.editing and n.layout[0]['size']=='wide'
    assert n.task_input.value=='черновик дела'
    assert n.shortcut_label.value=='Браузер' and n.shortcut_command.value=='открой браузер'
    assert gui.config.get(LAYOUT_KEY)==[]


def test_widget_does_not_create_background_task(gui):
    b=prepare(gui)
    assert not hasattr(b,'_future')
    b.dispose();assert not b._mounted and b._host is None


def test_saved_task_widget_draft_survives_theme_rebuild(gui):
    b=prepare(gui);b.save();b.task_input.value='сохранить черновик'
    gui._home._theme('Светлая')
    assert gui._home.widgets.task_input.value=='сохранить черновик'


def test_large_task_list_caps_rendered_controls(gui,monkeypatch):
    b=prepare(gui);b.save()
    monkeypatch.setattr(tasks,'list_items',lambda:[{'id':i,'text':str(i),'done':False} for i in range(150)])
    b.refresh_tasks(force=True)
    assert len(b.task_rows.controls)==100 and 'первые 100' in b.task_summary.value


def test_drop_moves_down_as_well_as_up(gui):
    b=prepare(gui)
    b.drop('shortcuts',NS(src=NS(data='tasks')))
    assert [x['kind'] for x in b.layout]==['shortcuts','tasks']
    b.drop('shortcuts',NS(src=NS(data='tasks')))
    assert [x['kind'] for x in b.layout]==['tasks','shortcuts']


def test_editor_toolbar_never_wraps_expanded_children(gui):
    # Flutter Wrap cannot own Expanded: invalid ParentData makes the board grey.
    b=prepare(gui)
    toolbar=b.controls[0]
    assert not toolbar.wrap


@pytest.mark.asyncio
async def test_open_widgets_does_not_scroll_before_scrollview_exists(gui):
    from unittest.mock import AsyncMock
    home=gui._home
    home.workspace.scroll_to=AsyncMock()
    await home._open_widgets()
    assert home.widgets.editing
    home.workspace.scroll_to.assert_not_called()


def test_native_text_fields_subscribe_for_value_sync(gui):
    b=prepare(gui)
    assert all(field.on_change is not None for field in (b.task_input,b.shortcut_label,b.shortcut_command))


def test_compact_cards_stack_below_large_breakpoint(gui):
    b=prepare(gui)
    row=b.controls[-1]
    assert all(card.col=={'xs':12,'lg':6} for card in row.controls)
    b.resize_widget('tasks')
    assert b.controls[-1].controls[0].col==12
