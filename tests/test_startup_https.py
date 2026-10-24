"""Process-local CA and native-client prep without network/GUI."""
import ast
import importlib.util
from pathlib import Path
import ssl
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import launcher
from jarvis import https_trust

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def clean_ca(monkeypatch):
    monkeypatch.delenv('SSL_CERT_FILE',raising=False)
    monkeypatch.delenv('SSL_CERT_DIR',raising=False)

@pytest.mark.parametrize('key',['SSL_CERT_FILE','SSL_CERT_DIR'])
def test_explicit_ca_is_preserved(monkeypatch,clean_ca,key):
    monkeypatch.setenv(key,'private-enterprise-ca')
    assert https_trust.configure_https_trust()=='explicit'
    assert https_trust.os.environ[key]=='private-enterprise-ca'


def test_certifi_enables_verified_default_context(monkeypatch,clean_ca):
    import certifi
    assert https_trust.configure_https_trust()=='certifi'
    assert Path(https_trust.os.environ['SSL_CERT_FILE'])==Path(certifi.where()).resolve()
    context=ssl.create_default_context()
    assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED


def test_missing_bundle_does_not_disable_tls(monkeypatch,tmp_path,clean_ca):
    monkeypatch.setitem(sys.modules,'certifi',NS(where=lambda:str(tmp_path/'missing')))
    assert https_trust.configure_https_trust()=='system'
    assert 'SSL_CERT_FILE' not in https_trust.os.environ


def test_entry_sets_ca_before_main_import():
    tree=ast.parse((ROOT/'jarvis/__main__.py').read_text(encoding="utf-8"))
    calls=[n for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
    main=next(n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='jarvis.main')
    assert calls[0].value.func.id=='configure_https_trust'
    assert calls[0].lineno<main.lineno


def helper():
    spec=importlib.util.spec_from_file_location('prepare_client_test',ROOT/'scripts/prepare_flet_client.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

@pytest.mark.parametrize('present',[True,False])
def test_flet_marker_requires_native_exe(monkeypatch,tmp_path,capsys,present):
    monkeypatch.setattr(https_trust,'configure_https_trust',lambda:'test')
    (tmp_path/'flet').mkdir()
    if present:(tmp_path/'flet/flet.exe').write_bytes(b'test')
    monkeypatch.setitem(sys.modules,'flet_desktop',NS(ensure_client_cached=lambda:tmp_path))
    assert helper().main()==(0 if present else 1)
    out=capsys.readouterr()
    assert ('FLET_CLIENT_READY' in out.out)==present
    if not present: assert 'FLET_CLIENT_FAILED:RuntimeError' in out.err


@pytest.mark.parametrize('result,expected',[(NS(returncode=0,stdout='FLET_CLIENT_READY\n',stderr=''),True),(NS(returncode=0,stdout='not ready',stderr=''),False),(NS(returncode=1,stdout='',stderr='tls error'),False)])
def test_launcher_checks_complete_client(monkeypatch,tmp_path,result,expected):
    monkeypatch.setattr(launcher,'_PREPARATION',None)
    run=Mock(return_value=result);error=Mock()
    monkeypatch.setattr(launcher.subprocess,'run',run);monkeypatch.setattr(launcher,'error',error)
    assert launcher.prepare_flet_client(tmp_path,Mock()) is expected
    argv=run.call_args.args[0];kw=run.call_args.kwargs
    assert argv==[str(tmp_path/'.venv311/Scripts/python.exe'),str(tmp_path/'scripts/prepare_flet_client.py')]
    assert kw['timeout']==240 and not kw.get('shell')
    assert error.called is (not expected)


def test_bootstrap_timeout_reports_failure(monkeypatch,tmp_path):
    monkeypatch.setattr(launcher,'_PREPARATION',None)
    monkeypatch.setattr(launcher.subprocess,'run',Mock(side_effect=launcher.subprocess.TimeoutExpired('flet',240)))
    error=Mock();monkeypatch.setattr(launcher,'error',error)
    assert not launcher.prepare_flet_client(tmp_path,Mock())
    error.assert_called_once()


@pytest.mark.parametrize('vc,flet,expected',[(False,True,False),(True,False,False),(True,True,True)])
def test_main_requires_prerequisites_before_launch(monkeypatch,tmp_path,vc,flet,expected):
    (tmp_path/'jarvis').mkdir();(tmp_path/'jarvis/__init__.py').write_text('', encoding="utf-8")
    monkeypatch.setattr(launcher,'_PREPARATION',None)
    monkeypatch.setattr(launcher,'_setup_logging',lambda *a:tmp_path/'launcher.log')
    for name,result in [('already_running',False),('find_project_dir',tmp_path),('find_python','python.exe'),('ensure_vc_runtime',vc),('find_venv_pythonw',tmp_path/'pythonw.exe'),('check_dependencies',True),('check_vosk_model',True),('prepare_flet_client',flet),('ensure_local_caps',None),('handle_ollama',None)]:
        monkeypatch.setattr(launcher,name,Mock(return_value=result))
    launch=Mock();monkeypatch.setattr(launcher,'run_jarvis',launch)
    launcher._main()
    assert launch.called is expected
    if not vc:launcher.find_venv_pythonw.assert_not_called()
    if not flet and vc:launcher.handle_ollama.assert_not_called()
