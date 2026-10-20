"""Optional model setup + real loopback HTTP protocol. No models/inference/Windows install."""
import base64
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import launcher
import launcher_ollama as module
from launcher_ui import ModelQuestion, PreparationWindow, Session

LOG = logging.getLogger('ollama-bootstrap-test')
SMALL = module.MODEL_OPTIONS[0][0]
DEFAULT = module.MODEL_OPTIONS[-1][0]


def settings(**overrides):
    return {'llm_model': DEFAULT, 'ollama_url': module.DEFAULT_URL, 'mode': 'combo', **overrides}


@pytest.fixture
def flow(tmp_path):
    api = SimpleNamespace(url=module.DEFAULT_URL, inventory=Mock(return_value=[]),
                          pull=Mock(), check_completion=Mock())
    bridge = SimpleNamespace(read=Mock(return_value=settings()), select=Mock())
    session = SimpleNamespace(ask=Mock(return_value=False), choose_model=Mock(return_value=None),
                              stage=Mock(), detail=Mock(), progress_update=Mock())
    find_exe, start_server, open_site = Mock(return_value=None), Mock(), Mock()
    def run():
        return module.prepare_models(tmp_path, session, LOG, find_exe, start_server,
                                     open_site, bridge=bridge, api_factory=lambda _: api)
    return SimpleNamespace(api=api, bridge=bridge, session=session, run=run,
                           find=find_exe, start=start_server, site=open_site)


def test_configured_installed_model_is_not_changed_or_downloaded(flow):
    flow.api.inventory.return_value = [DEFAULT]
    flow.run()
    flow.session.choose_model.assert_not_called()
    flow.bridge.select.assert_not_called()
    flow.api.pull.assert_not_called()
    flow.api.check_completion.assert_not_called()  # no new work on every launch


def test_skip_model_is_not_global_decline_and_has_no_side_effect(flow):
    flow.run()
    flow.session.choose_model.assert_called_once()
    flow.api.pull.assert_not_called()
    flow.bridge.select.assert_not_called()


def test_successful_pull_is_verified_before_saving_explicit_choice(flow):
    installed = []
    flow.api.inventory.side_effect = lambda: list(installed)
    flow.api.pull.side_effect = lambda name, progress: installed.append(name)
    flow.session.choose_model.return_value = SMALL
    flow.run()
    flow.api.pull.assert_called_once_with(SMALL, flow.session.progress_update)
    flow.api.check_completion.assert_called_once_with(SMALL)
    flow.bridge.select.assert_called_once_with(SMALL, settings())


def test_existing_alternative_does_not_download(flow):
    flow.api.inventory.return_value = ['my-local-model:latest']
    flow.session.choose_model.return_value = 'my-local-model:latest'
    flow.run()
    flow.api.pull.assert_not_called()
    flow.api.check_completion.assert_called_once()
    flow.bridge.select.assert_called_once_with('my-local-model:latest', settings())


def test_failed_pull_never_changes_config_and_can_skip(flow):
    flow.session.choose_model.return_value = SMALL
    flow.api.pull.side_effect = module.SetupError('pull')
    flow.run()
    flow.bridge.select.assert_not_called()
    flow.session.ask.assert_called_once()
    assert flow.session.ask.call_args.args[-1] == 'Продолжить без ИИ'


def test_success_status_without_inventory_cannot_change_config(flow):
    flow.session.choose_model.return_value = SMALL
    flow.run()
    flow.api.pull.assert_called_once()
    flow.bridge.select.assert_not_called()


def test_embedding_only_model_is_rejected_before_save(flow):
    flow.api.inventory.return_value = ['nomic-embed-text:latest']
    flow.session.choose_model.return_value = 'nomic-embed-text:latest'
    flow.api.check_completion.side_effect = module.SetupError('capabilities')
    flow.run()
    flow.bridge.select.assert_not_called()
    assert 'генерации текста' in flow.session.ask.call_args.args[0]


def test_write_conflict_is_not_reported_as_ready(flow):
    flow.api.inventory.return_value = [SMALL]
    flow.session.choose_model.return_value = SMALL
    flow.bridge.select.side_effect = module.SetupError('configuration')
    flow.run()
    assert not any(c.args[0] == 'Модель подготовлена' for c in flow.session.stage.call_args_list)
    flow.session.ask.assert_called_once()


def test_command_only_mode_does_not_offer_or_download_models(flow):
    flow.bridge.read.return_value = settings(mode='commands')
    flow.run()
    flow.api.inventory.assert_not_called()
    flow.site.assert_not_called()
    flow.session.choose_model.assert_not_called()


@pytest.mark.parametrize('url', ['https://example.com', 'http://192.168.1.2:11434',
    'http://user:password@localhost:11434', 'http://localhost:11434/path'])
def test_custom_remote_endpoint_is_not_contacted_or_overwritten(flow, url):
    flow.bridge.read.return_value = settings(ollama_url=url)
    flow.run()
    flow.api.inventory.assert_not_called()
    flow.bridge.select.assert_not_called()
    flow.site.assert_not_called()


def test_absent_ollama_can_be_skipped_without_browser(flow):
    flow.api.inventory.side_effect = module.SetupError('inventory')
    flow.run()
    flow.site.assert_not_called()
    flow.session.choose_model.assert_not_called()
    flow.bridge.select.assert_not_called()


def test_site_install_then_recheck_continues_to_model_choice(flow):
    flow.api.inventory.side_effect = [module.SetupError('inventory'), []]
    flow.session.ask.side_effect = [True, True]
    flow.run()
    flow.site.assert_called_once_with(module.DOWNLOAD_PAGE)
    flow.session.choose_model.assert_called_once()


def test_server_start_waits_for_readiness_before_model_choice(flow, monkeypatch):
    flow.api.inventory.side_effect = module.SetupError('inventory')
    flow.find.return_value = Path('ollama.exe')
    monkeypatch.setattr(module, '_wait_inventory', lambda _: [])
    flow.run()
    flow.start.assert_called_once()
    flow.session.choose_model.assert_called_once()


def test_explicit_retry_uses_refreshed_settings_not_stale_snapshot(flow):
    installed = []
    flow.api.inventory.side_effect = lambda: list(installed)
    attempts = []
    def pull(name, progress):
        attempts.append(name)
        if len(attempts) == 1: raise module.SetupError('pull')
        installed.append(name)
    flow.api.pull.side_effect = pull
    flow.session.ask.return_value = True
    flow.session.choose_model.return_value = SMALL
    newer = settings(llm_model='new-setting:latest')
    flow.bridge.read.side_effect = [settings(), newer]
    flow.run()
    assert len(attempts) == 2
    flow.bridge.select.assert_called_once_with(SMALL, newer)


def test_invalid_ui_choice_is_never_pulled(flow):
    flow.session.choose_model.return_value = 'not-in-options'
    with pytest.raises(module.SetupError): flow.run()
    flow.api.pull.assert_not_called()
    flow.bridge.select.assert_not_called()


def test_choices_preserve_installed_but_exclude_cloud_and_command_strings():
    options = module.choices(['my-local:latest', 'x:cloud', 'x:7b-cloud', 'bad;command'])
    assert options[0] == {'value': 'my-local:latest', 'label': 'my-local:latest — уже скачана', 'installed': True}
    assert len(options) == 4
    assert [o['value'] for o in options[1:]] == [name for name, _ in module.MODEL_OPTIONS]


@pytest.mark.parametrize('url', ['http://example.com', 'http://localhost@evil.com',
    'https://localhost', 'file:///tmp/x', 'http://localhost:bad',
    'http://localhost:11434?q=1', 'http://localhost:11434/#x'])
def test_endpoint_validator_rejects_remote_or_ambiguous_url(url):
    with pytest.raises(module.SetupError): module.OllamaAPI(url)


@pytest.fixture
def server():
    state = SimpleNamespace(names=[], records=[], events=[{'status':'success'}],
                            tags_override=None, show={'capabilities':['completion']}, redirect=None)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            state.records.append(('GET', self.path, None))
            if state.redirect:
                self.send_response(302); self.send_header('Location', state.redirect); self.end_headers(); return
            data = state.tags_override if state.tags_override is not None else {'models':[{'name':n} for n in state.names]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state.records.append(('POST', self.path, body))
            self.send_response(200); self.end_headers()
            if self.path == '/api/show':
                self.wfile.write(json.dumps(state.show).encode()); return
            for event in state.events:
                if isinstance(event, dict) and event.get('status') == 'success':
                    state.names.append(body['model'])
                self.wfile.write(event if isinstance(event, bytes) else json.dumps(event).encode()+b'\n')
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True);thread.start()
    state.url = f'http://127.0.0.1:{http.server_port}'
    yield state
    http.shutdown();http.server_close();thread.join(3)


def test_real_loopback_pull_streams_actual_layer_progress_and_checks_tags(server, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://invalid-proxy.invalid:1')
    monkeypatch.setenv('NO_PROXY', '')
    server.events = [{'status':'pulling manifest'}, {'status':'pulling abc', 'total':100, 'completed':40},
                     {'status':'verifying sha256 digest'}, {'status':'success'}]
    api = module.OllamaAPI(server.url)
    progress = Mock()
    api.pull(SMALL, progress)
    api.check_completion(SMALL)
    assert ('POST','/api/pull',{'model':SMALL,'stream':True,'insecure':False}) in server.records
    assert ('GET','/api/tags',None) in server.records
    assert ('POST','/api/show',{'model':SMALL,'verbose':False}) in server.records
    assert any(call.args[0] == .4 for call in progress.call_args_list)
    assert all(call.args[0] in (None,.4) for call in progress.call_args_list)
    assert 'Текущий слой' in progress.call_args_list[1].args[1]


@pytest.mark.parametrize('events', [[{'error':'private-server-error'}], [{'status':'pulling manifest'}],
    [b'not json\n'], [b'x'*(module.MAX_LINE+1)], [{'total':100,'completed':40}], [b'[]\n']])
def test_real_loopback_pull_rejects_errors_incomplete_and_bad_data(server, events):
    server.events = events
    with pytest.raises(module.SetupError):
        module.OllamaAPI(server.url).pull(SMALL, Mock())


def test_pull_rejects_success_without_installed_tag(server, monkeypatch):
    api = module.OllamaAPI(server.url)
    monkeypatch.setattr(api, 'inventory', lambda: [])
    with pytest.raises(module.SetupError, match='not installed'):
        api.pull(SMALL, Mock())


@pytest.mark.parametrize('data', [[], {'models':'bad'}, {'models':[1]}])
def test_real_loopback_inventory_rejects_invalid_shape(server, data):
    server.tags_override = data
    with pytest.raises(module.SetupError): module.OllamaAPI(server.url).inventory()


def test_loopback_cannot_redirect_to_remote_server(server):
    server.redirect = 'https://example.com/private'
    with pytest.raises(module.SetupError): module.OllamaAPI(server.url).inventory()
    assert len(server.records) == 1


@pytest.mark.parametrize('data', [{'capabilities':['embedding']}, {'capabilities':['completion'],'remote_host':'cloud'}, {}])
def test_completion_check_rejects_embedding_cloud_and_unknown(server, data):
    server.show = data
    with pytest.raises(module.SetupError, match='capabilities'):
        module.OllamaAPI(server.url).check_completion('installed:latest')


def test_arbitrary_model_cannot_be_pulled(server):
    with pytest.raises(module.SetupError): module.OllamaAPI(server.url).pull('arbitrary/model:latest', Mock())
    assert server.records == []


def test_model_choice_queue_waits_for_explicit_answer_and_skip_is_optional():
    session = Session();answers=[]
    thread = threading.Thread(target=lambda: answers.append(session.choose_model('title','text',module.choices([]))))
    thread.start()
    kind, data = session.events.get(timeout=2)
    assert kind == 'model_choice' and thread.is_alive()
    data['question'].resolve(None)
    thread.join(2)
    assert answers == [None] and not session.declined


def test_model_question_rejects_values_outside_options():
    question = ModelQuestion('title','text',module.choices([]))
    with pytest.raises(ValueError): question.resolve('arbitrary')
    assert not question.ready.is_set()
    question.resolve(SMALL)
    assert question.answer == SMALL and question.ready.is_set()


@pytest.fixture
def window():
    w = PreparationWindow(Path('.'), Path('launcher.log'))
    for name in ('primary_button','cancel_button','stage_label','progress_label','root'):
        setattr(w,name,Mock())
    w._show = Mock();w._detail=Mock();w._build_model_choices=Mock()
    return w


def test_window_choice_confirm_routes_exact_model_not_boolean(window):
    question = ModelQuestion('title','text',module.choices([]))
    window._event('model_choice',{'question':question})
    window.model_choice = SimpleNamespace(current=lambda:1)
    window._primary()
    assert window.state == 'busy' and question.answer == module.MODEL_OPTIONS[1][0]
    assert question.ready.is_set() and window.question is None
    window._primary()  # double click cannot resolve another question


def test_window_choice_close_skips_without_closing_live_worker(window):
    question = ModelQuestion('title','text',module.choices([]))
    window._event('model_choice',{'question':question})
    window._secondary()
    assert question.ready.is_set() and question.answer is None
    assert window.state == 'busy'
    window.root.destroy.assert_not_called()


def test_progress_updates_use_supplied_value_and_are_throttled(monkeypatch):
    session=Session()
    monkeypatch.setattr('launcher_ui.time.monotonic', lambda: 100.)
    session.progress_update(.25,'Текущий слой')
    session.progress_update(.26,'Текущий слой')
    session.progress_update(None,'Проверяем…')
    assert session.events.qsize() == 2
    assert session.events.get()[1]['value'] == .25
    assert session.events.get()[1]['value'] is None


def test_bootstrap_helper_is_in_payload_and_entrypoint_imports_it():
    import ast
    from scripts.release_payload import collect_payload
    root=Path(__file__).resolve().parents[1]
    files=collect_payload(root,False)
    assert 'launcher_ollama.py' in files and 'scripts/bootstrap_ollama_config.py' in files
    tree=ast.parse((root/'launcher.py').read_text(encoding='utf-8'))
    assert any(isinstance(n,ast.ImportFrom) and n.module=='launcher_ollama' for n in tree.body)


def test_bad_config_skips_setup_without_network_or_write(flow):
    flow.bridge.read.side_effect = module.SetupError('configuration')
    flow.run()
    flow.api.inventory.assert_not_called()
    flow.bridge.select.assert_not_called()


def test_loopback_inventory_omits_cloud_metadata(server):
    server.tags_override = {'models': [{'name':'local:latest'},
        {'name':'custom:latest','remote_host':'https://cloud.invalid'}, {'name':'x:cloud'}]}
    assert module.OllamaAPI(server.url).inventory() == ['local:latest']


def test_pull_has_an_overall_deadline(server, monkeypatch):
    monkeypatch.setattr(module, 'PULL_DEADLINE', -1)
    with pytest.raises(module.SetupError, match='timeout'):
        module.OllamaAPI(server.url).pull(SMALL, Mock())


def test_wait_inventory_accepts_empty_ready_server():
    api = SimpleNamespace(inventory=Mock(return_value=[]))
    assert module._wait_inventory(api, seconds=0) == []


def test_wait_inventory_timeout_is_not_ready():
    api = SimpleNamespace(inventory=Mock(side_effect=module.SetupError('inventory')))
    assert module._wait_inventory(api, seconds=0) is None


def test_handle_ollama_keeps_session_and_project_context(monkeypatch, tmp_path):
    session = Session()
    monkeypatch.setattr(launcher, '_PREPARATION', session)
    prepare = Mock()
    monkeypatch.setattr(launcher, 'prepare_models', prepare)
    launcher.handle_ollama(LOG, tmp_path)
    assert prepare.call_args.args[:3] == (tmp_path, session, LOG)


def test_bad_config_skips_setup_without_network_or_write(flow):
    flow.bridge.read.side_effect = module.SetupError('configuration')
    flow.run()
    flow.api.inventory.assert_not_called()
    flow.bridge.select.assert_not_called()


def test_loopback_inventory_omits_cloud_metadata(server):
    server.tags_override = {'models': [{'name':'local:latest'},
        {'name':'custom:latest','remote_host':'https://cloud.invalid'}, {'name':'x:cloud'}]}
    assert module.OllamaAPI(server.url).inventory() == ['local:latest']


def test_pull_has_an_overall_deadline(server, monkeypatch):
    monkeypatch.setattr(module, 'PULL_DEADLINE', -1)
    with pytest.raises(module.SetupError, match='timeout'):
        module.OllamaAPI(server.url).pull(SMALL, Mock())


def test_wait_inventory_accepts_empty_ready_server():
    api = SimpleNamespace(inventory=Mock(return_value=[]))
    assert module._wait_inventory(api, seconds=0) == []


def test_wait_inventory_timeout_is_not_ready():
    api = SimpleNamespace(inventory=Mock(side_effect=module.SetupError('inventory')))
    assert module._wait_inventory(api, seconds=0) is None


def test_handle_ollama_keeps_session_and_project_context(monkeypatch, tmp_path):
    session = Session()
    monkeypatch.setattr(launcher, '_PREPARATION', session)
    prepare = Mock()
    monkeypatch.setattr(launcher, 'prepare_models', prepare)
    launcher.handle_ollama(LOG, tmp_path)
    assert prepare.call_args.args[:3] == (tmp_path, session, LOG)


def test_model_dropdown_is_readonly_bounded_and_has_no_download_side_effect(window, monkeypatch):
    import sys
    combo = Mock()
    combo.current.return_value = 0
    constructor = Mock(return_value=combo)
    monkeypatch.setitem(sys.modules, 'tkinter', SimpleNamespace(ttk=SimpleNamespace(Combobox=constructor)))
    window.question = ModelQuestion('title','text',module.choices([]))
    window.choice_frame = Mock()
    window.choice_frame.winfo_children.return_value = []
    window.bar = object()
    PreparationWindow._build_model_choices(window)
    assert constructor.call_args.kwargs['state'] == 'readonly'
    assert constructor.call_args.kwargs['height'] == 8
    combo.current.assert_any_call(0)
    window.choice_frame.pack.assert_called_once_with(fill='x', before=window.bar)
    window.primary_button.configure.assert_called_with(text='Скачать и использовать')
    assert not window.question.ready.is_set()  # viewing choices is not consent
