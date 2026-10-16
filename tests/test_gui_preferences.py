"""Real imported Flet controls / real disk writes / explicit network fake only.

No Windows desktop, audio or inference. Local inventory server tests use stdlib.
"""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import pytest
import flet as ft

from jarvis import config_manager, gui as module, gui_preferences as ui, mood, profile
from jarvis.config import Config


def ev(value):
    return NS(control=NS(value=value))


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, 'PROFILES_DIR', tmp_path / 'profiles')
    monkeypatch.setattr(profile, '_current', 'test')
    monkeypatch.setattr(profile, '_cache', {})
    monkeypatch.setattr(profile, '_listeners', [])
    cfg = Config(tmp_path / 'config.json')
    window = module.FenixGUI(None, cfg)
    screen = window._preferences()
    window._build_persona_tab()
    window._build_settings_tab()
    yield screen
    if screen.probe_thread:
        screen.probe_thread.join(6)
    profile.unsubscribe(window._on_profile_switch)
    mood.unsubscribe(window._on_mood_change)
    module._apply_palette('dark')


def drain(editor):
    editor.probe_thread.join(6)
    assert not editor.probe_thread.is_alive()
    events = []
    while not editor.gui._queue.empty():
        kind, value = editor.gui._queue.get_nowait()
        events.append(kind)
        if kind == 'preferences_result':
            editor.apply_probe(value)
    return events


def test_persona_controls_stage_then_save_to_one_current_profile(editor):
    editor.persona_fields['name'].on_change(ev('Маша'))
    editor.persona_fields['assistant_name'].on_change(ev('Искра'))
    editor.persona_fields['tone'].on_select(ev('polite'))
    editor.choose_style('brief')
    assert profile.get('name') is None
    assert profile.get('persona') is None
    editor.save_persona()
    assert profile.get('name') == 'Маша'
    assert profile.get('persona')['assistant_name'] == 'Искра'
    assert profile.get('persona')['tone'] == 'polite'
    assert profile.get('persona')['speech_style'] == 'brief'
    assert editor.gui.config.get('name') != 'Маша'  # not a global name / other profile leak
    assert not editor.persona_error


def test_persona_batch_is_one_write_and_keeps_other_profile_fields(editor, monkeypatch):
    profile.set('facts', {'city': 'Тест'})
    profile.set('persona', {'onboarding_done': True, 'onboarding_at': 100, 'legacy': 'keep'})
    editor.cancel_persona()
    editor._change('persona', 'backstory', 'Новый контекст')
    original = config_manager.save
    writes = []
    def save(data, path=None):
        writes.append(path)
        return original(data, path)
    monkeypatch.setattr(config_manager, 'save', save)
    editor.save_persona()
    assert len(writes) == 1
    assert profile.get('facts') == {'city': 'Тест'}
    assert profile.get('persona')['onboarding_at'] == 100
    assert profile.get('persona')['legacy'] == 'keep'


@pytest.mark.parametrize('key,value', [('assistant_name',''), ('assistant_name','a'*61),
    ('name','a'*61), ('backstory','a'*2001), ('tone','bogus'), ('speech_style','bogus'),
    ('traits', ['a']*13), ('traits',[None]), ('traits',['a'*41])])
def test_persona_validation_never_writes(editor, key, value):
    editor.persona_draft[key] = value
    editor.save_persona()
    assert editor.persona_error
    assert profile.get('persona') is None


def test_persona_save_failure_retains_draft_and_never_reports_success(editor, monkeypatch):
    editor._change('persona', 'name', 'Черновик')
    monkeypatch.setattr(config_manager, 'save', lambda *a, **kw: False)
    editor.save_persona()
    assert editor.persona_error
    assert editor.persona_draft['name'] == 'Черновик'
    assert profile.get('name') is None


def test_newer_persona_is_not_overwritten(editor):
    editor._change('persona', 'name', 'Черновик')
    profile.set('persona', {'assistant_name': 'Новая'})
    editor.save_persona()
    assert editor.persona_error
    assert profile.get('name') is None
    assert profile.get('persona')['assistant_name'] == 'Новая'


def test_profile_switch_cannot_write_old_draft_to_new_person(editor):
    editor._change('persona','name','Чужой черновик')
    profile.switch('Другой')
    editor.save_persona()
    assert profile.get('name') == 'Другой'
    assert profile.get('persona') is None
    assert editor.profile_id == profile.current()
    assert editor.persona_draft['name'] == 'Другой'


def test_profile_switch_invalidates_draft_on_build(editor):
    editor._change('persona','backstory','Старый профиль')
    profile.switch('Новый')
    editor.build_persona()
    assert editor.persona_draft['backstory'] == ''


def test_drafts_survive_theme_build_and_navigation(editor):
    editor._change('persona','backstory','Не теряй')
    editor.pending_trait = 'Новая черта'
    editor._change('settings','ollama_url','http://localhost:8888')
    module._apply_palette('light')
    editor.build_persona(); editor.build_settings()
    assert editor.persona_fields['backstory'].value == 'Не теряй'
    assert editor.pending_trait == 'Новая черта'
    assert editor.settings_fields['ollama_url'].value == 'http://localhost:8888'
    assert editor.settings_fields['llm_model'].value


def test_trait_chips_and_preview_are_pure_draft(editor):
    editor.add_trait(ev('Спокойный'))
    editor.add_trait(ev('Спокойный'))
    assert editor.persona_draft['traits'] == ['Спокойный']
    assert 'Спокойный' in editor.preview_details.value
    editor.remove_trait('Спокойный')
    assert editor.persona_draft['traits'] == []
    editor.choose_style('formal')
    assert 'Уточните' in editor.preview_quote.value
    assert editor.gui._messages == []
    assert profile.get('persona') is None


def test_cancel_persona_reloads_saved_values(editor):
    editor._change('persona','name','Черновик')
    editor.cancel_persona()
    assert editor.persona_draft['name'] == ''


def test_reset_is_confirmed_and_preserves_facts_history_draft(editor):
    profile.set('facts', {'key':'value'})
    profile.set('persona', {'onboarding_done': True, 'backstory': 'Сохранённое'})
    editor.cancel_persona()
    editor._change('persona','backstory','Черновик')
    editor.ask_reset()
    assert profile.get('persona')['onboarding_done']
    editor.confirm_reset(False)
    assert profile.get('persona')['onboarding_done']
    editor.ask_reset(); editor.confirm_reset(True)
    assert not profile.get('persona')['onboarding_done']
    assert profile.get('persona')['backstory'] == 'Сохранённое'
    assert editor.persona_draft['backstory'] == 'Черновик'
    assert profile.get('facts') == {'key':'value'}
    editor.save_persona()
    assert profile.get('persona')['backstory'] == 'Черновик'


def test_corrupt_profile_is_shown_not_overwritten(editor):
    profile.profile_path().write_text('{broken', encoding='utf-8')
    profile._cache_invalidate()
    editor.cancel_persona()
    assert editor.persona_read_error
    editor.save_persona()
    assert profile.profile_path().read_text(encoding='utf-8') == '{broken'


def test_settings_batch_apply_not_staged_per_control(editor):
    cfg = editor.gui.config
    events=[]
    cfg.subscribe(lambda k,v: events.append(k))
    editor.settings_fields['llm_model'].on_select(ev('gemma2:9b'))
    editor.settings_fields['observer_enabled'].on_change(ev(True))
    assert cfg.get('observer_enabled') is False
    assert cfg.get('llm_model') != 'gemma2:9b'
    editor.save_settings()
    assert cfg.get('llm_model') == 'gemma2:9b'
    assert cfg.get('observer_enabled') is True
    assert sorted(events) == ['llm_model','observer_enabled']
    assert 'перезапуск' in editor.settings_notice


def test_settings_failure_retains_every_old_value(editor, monkeypatch):
    cfg=editor.gui.config
    before=cfg.all_data()
    editor._change('settings','llm_model','gemma2:9b')
    editor._change('settings','observer_enabled',True)
    monkeypatch.setattr(config_manager,'save',lambda *a,**kw:False)
    editor.save_settings()
    assert editor.settings_error
    assert cfg.all_data() == before
    assert editor.settings_draft['llm_model'] == 'gemma2:9b'


def test_settings_do_not_clobber_newer_values(editor):
    editor._change('settings','llm_model','gemma2:9b')
    editor.gui.config.set('llm_model','llama3.1:8b')
    editor.save_settings()
    assert editor.settings_error
    assert editor.gui.config.get('llm_model') == 'llama3.1:8b'


def test_unrelated_setting_changed_elsewhere_is_not_overwritten(editor):
    editor._change('settings','llm_model','gemma2:9b')
    editor.gui.config.set('tray_enabled',False)
    editor.save_settings()
    assert not editor.settings_error
    assert editor.gui.config.get('tray_enabled') is False


def test_hidden_tray_launch_is_rejected(editor):
    editor._change('settings','launch_mode','tray')
    editor._change('settings','tray_enabled',False)
    editor.save_settings()
    assert editor.settings_error
    assert editor.gui.config.get('tray_enabled') is True


def test_model_change_during_command_is_rejected(editor):
    editor.gui._command_busy=True
    editor._change('settings','llm_model','gemma2:9b')
    editor.save_settings()
    assert editor.settings_error


def test_cancel_settings_does_not_revert_theme(editor):
    editor.gui.config.set('gui_theme','Светлая')
    editor._change('settings','ollama_url','http://localhost:9000')
    editor.cancel_settings()
    assert editor.gui.config.get('gui_theme') == 'Светлая'
    assert editor.settings_draft['ollama_url'] != 'http://localhost:9000'


@pytest.mark.parametrize('value', ['', 'ftp://localhost', 'http://u:p@localhost:11434',
    'http://localhost:99999', 'http://localhost:0', 'http://localhost/?token=secret',
    'http://localhost/#x', 'http://local host', 'http://localhost\\@evil', 'http://'])
def test_bad_url_is_rejected(value):
    with pytest.raises(ValueError): ui.validated_url(value)


@pytest.mark.parametrize('value,expected', [('http://localhost:11434/', 'http://localhost:11434'),
    ('https://example.com/ollama/', 'https://example.com/ollama'),
    ('http://[::1]:11434','http://[::1]:11434')])
def test_url_normalization(value,expected):
    assert ui.validated_url(value)==expected


def test_probe_worker_only_enqueues_until_completion_applied(editor, monkeypatch):
    entered,release=threading.Event(),threading.Event()
    def probe(url):
        entered.set(); assert release.wait(3)
        return frozenset({'qwen2.5:7b-instruct','nomic-embed-text:latest'})
    monkeypatch.setattr(ui,'probe_ollama',probe)
    assert editor.start_probe()
    try:
        assert entered.wait(2)
        assert not editor.start_probe()
        assert editor.inventory is None
    finally: release.set()
    editor.probe_thread.join(4)
    assert editor.probe_busy  # completion still on queue
    assert editor.inventory is None
    assert 'preferences_result' in drain(editor)
    assert not editor.probe_busy
    assert editor.inventory
    assert 'Генерация' in editor.probe_status


def test_stale_probe_does_not_mark_new_address_ready(editor, monkeypatch):
    monkeypatch.setattr(ui,'probe_ollama',lambda url:frozenset({'nomic-embed-text:latest'}))
    editor.start_probe(); editor.probe_thread.join(4)
    editor._change('settings','ollama_url','http://localhost:9999')
    drain(editor)
    assert editor.inventory is None
    assert 'заново' in editor.probe_status


def test_probe_error_is_sanitized(editor, monkeypatch):
    def bad(url):raise RuntimeError('PASSWORD raw payload SECRET')
    monkeypatch.setattr(ui,'probe_ollama',bad)
    editor.start_probe();drain(editor)
    assert 'SECRET' not in editor.probe_status
    assert 'не удалась' in editor.probe_status
    assert not editor.probe_busy


def test_probe_thread_start_failure_unlocks(editor, monkeypatch):
    class Broken:
        def __init__(self,**kwargs):pass
        def start(self):raise RuntimeError('SECRET')
        def join(self,*args):pass
    monkeypatch.setattr(ui.threading,'Thread',Broken)
    assert not editor.start_probe()
    assert not editor.probe_busy
    assert 'SECRET' not in editor.probe_status


def test_rag_enabling_requires_verified_embedding_inventory(editor, monkeypatch):
    editor._change('settings','memory_rag_enabled',True)
    editor.save_settings()
    assert editor.settings_error
    assert not editor.gui.config.get('memory_rag_enabled')
    monkeypatch.setattr(ui,'probe_ollama',lambda url:frozenset({'nomic-embed-text:latest'}))
    editor.start_probe();drain(editor)
    editor.save_settings()
    assert not editor.settings_error
    assert editor.gui.config.get('memory_rag_enabled')


def test_profile_compare_write_never_changes_new_profile(editor):
    identity,baseline=profile.read_fields('name','persona')
    profile.switch('Другой')
    assert not profile.update_fields({'name':'Неверное'},expected_profile=identity,expected_values=baseline)
    assert profile.get('name')=='Другой'


def test_config_compare_and_swap_keeps_memory_disk_notifications(editor):
    cfg=editor.gui.config
    events=[];cfg.subscribe(lambda *x:events.append(x))
    before=cfg.path.read_bytes()
    assert not cfg.update({'llm_model':'other'},expected_values={'llm_model':'stale'})
    assert cfg.path.read_bytes()==before
    assert not events


def test_config_serializes_concurrent_writes(editor):
    cfg=editor.gui.config
    barrier=threading.Barrier(8)
    def write(i):
        barrier.wait();assert cfg.set('parallel_'+str(i),i)
    threads=[threading.Thread(target=write,args=(i,)) for i in range(8)]
    for t in threads:t.start()
    for t in threads:t.join(3)
    saved=json.loads(cfg.path.read_text(encoding='utf-8'))
    for i in range(8):assert saved['parallel_'+str(i)]==cfg.get('parallel_'+str(i))==i


@pytest.mark.parametrize('mode',['ok','redirect','invalid','oversize'])
def test_probe_http_contract_real_local_server(mode):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path=='/api/tags'
            if mode=='redirect':
                self.send_response(302);self.send_header('Location','/elsewhere');self.end_headers();return
            self.send_response(200);self.end_headers()
            payload=(json.dumps({'models':[{'name':'test:latest'}]}).encode() if mode=='ok'
                     else b'not json' if mode=='invalid' else b'x'*(1024*1024+1))
            self.wfile.write(payload)
        def log_message(self,*a):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url='http://127.0.0.1:'+str(server.server_port)
        if mode=='ok': assert ui.probe_ollama(url)==frozenset({'test:latest'})
        else:
            with pytest.raises(Exception):ui.probe_ollama(url)
    finally:server.shutdown();server.server_close();thread.join(2)


def test_pending_trait_is_included_by_explicit_save(editor):
    editor.pending_trait = "Внимательный"
    editor.save_persona()
    assert profile.get("persona")["traits"] == ["Внимательный"]
    assert not editor.pending_trait


def test_invalid_pending_trait_is_retained_on_validation_failure(editor):
    editor.pending_trait = "a" * 41
    editor.save_persona()
    assert editor.persona_error
    assert editor.pending_trait == "a" * 41
    assert profile.get("persona") is None


def test_new_endpoint_is_notified_before_model_warmup(editor):
    events = []
    editor.gui.config.subscribe(lambda k, v: events.append(k))
    editor._change("settings", "llm_model", "gemma2:9b")
    editor._change("settings", "ollama_url", "http://localhost:11435")
    editor.save_settings()
    assert events[:2] == ["ollama_url", "llm_model"]


def test_typing_only_patches_dependent_labels_not_the_input(editor):
    calls = []
    editor.gui._page = NS(update=lambda *controls: calls.append(controls))
    field = editor.persona_fields["assistant_name"]
    field.on_change(ev("Новый текст"))
    assert calls and all(field not in call for call in calls)
    calls.clear()
    field = editor.settings_fields["ollama_url"]
    field.on_change(ev("http://localhost:12345"))
    assert calls and all(field not in call for call in calls)
    editor.gui._page = None


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_preferences_outer_background_matches_shared_voice_background(editor, theme):
    module._apply_palette(theme)
    assert ui._palette().bg == module.P.bg_main
    assert editor.build_persona().bgcolor == module.P.bg_main
    assert editor.build_settings().bgcolor == module.P.bg_main
    assert ui._palette().card == module.P.bg_card


def test_preferences_background_follows_palette_not_a_copied_constant(editor, monkeypatch):
    monkeypatch.setattr(module.P, "_data", {**module.P._data, "bg_main": "#010203"})
    assert editor.build_persona().bgcolor == "#010203"
    assert editor.build_settings().bgcolor == "#010203"


PALETTE_ROLES = {
    "bg": "bg_main", "card": "bg_card", "field": "bg_card",
    "text": "text", "dim": "text_dim", "border": "border",
    "accent": "brand", "tint": "selected", "button_text": "bg_main",
    "error": "error",
}


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_preferences_use_shared_voice_palette_for_every_role(editor, theme):
    module._apply_palette(theme)
    palette = ui._palette()
    for role, token in PALETTE_ROLES.items():
        assert getattr(palette, role) == getattr(module.P, token)
    for build in (editor.build_persona, editor.build_settings):
        assert build().bgcolor == module.P.bg_main
    field = editor.persona_fields["name"]
    assert field.bgcolor == module.P.bg_card
    assert field.color == module.P.text
    assert field.label_style.color == module.P.text_dim
    assert field.border[ft.ControlState.DEFAULT].side.color == module.P.border
    assert field.border[ft.ControlState.FOCUSED].side.color == module.P.brand
    panel = ui.card("Title", "Subtitle", [])
    assert panel.bgcolor == module.P.bg_card
    assert panel.border.top.color == module.P.border


def test_all_preference_colors_follow_live_tokens_without_hex_copies(editor, monkeypatch):
    tokens = {token: f"#{index:06x}" for index, token in
              enumerate(dict.fromkeys(PALETTE_ROLES.values()), 1)}
    monkeypatch.setattr(module.P, "_data", {**module.P._data, **tokens})
    palette = ui._palette()
    for role, token in PALETTE_ROLES.items():
        assert getattr(palette, role) == tokens[token]


@pytest.mark.parametrize("theme,expected", [
    ("dark", ("#12121c", "#1d1e2d", "#d8a786", "#eeedf7", "#abaac1")),
    ("light", ("#f5f2ed", "#fffefc", "#92532f", "#282b30", "#5c6570")),
])
def test_selected_twilight_and_porcelain_match_approved_swatches(editor, theme, expected):
    module._apply_palette(theme)
    palette = ui._palette()
    assert (palette.bg, palette.card, palette.accent, palette.text, palette.dim) == expected
    assert module.BG_DARK == palette.bg
    assert module.BG_CARD == palette.card
    assert module.TEXT == palette.text
    assert module.TEXT_DIM == palette.dim
    assert module.ACCENT == module.P.accent


def _contrast(first, second):
    def luminance(value):
        rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        rgb = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb]
        return sum(x * weight for x, weight in zip(rgb, (.2126, .7152, .0722)))
    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_selected_themes_text_and_primary_buttons_have_aa_contrast(editor, theme):
    module._apply_palette(theme)
    p = module.P
    for surface in (p.bg_main, p.bg_card, p.sidebar, p.composer, p.selected,
                    p.bg_bubble_user, p.bg_bubble_ai):
        assert _contrast(p.text, surface) >= 4.5
        assert _contrast(p.text_dim, surface) >= 4.5
    assert _contrast(p.bg_main, p.brand) >= 4.5
    assert _contrast(p.accent, p.bg_card) >= 4.5
