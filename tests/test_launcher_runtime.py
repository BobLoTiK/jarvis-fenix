"""Prerequisite contracts: no real downloads, native installer or system edits."""
import base64
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
import launcher_runtime as rt


def test_system_probe_loads_only_system_dlls(monkeypatch, tmp_path):
    monkeypatch.setattr(rt.sys, 'platform', 'win32')
    monkeypatch.setenv('SystemRoot', str(tmp_path))
    load = Mock(return_value=object())
    monkeypatch.setattr(rt.ctypes, 'WinDLL', load, raising=False)
    assert rt.runtime_present()
    assert [c.args[0] for c in load.call_args_list] == [str(tmp_path/'System32'/n) for n in rt.VC_DLLS]


def test_missing_native_dependency_is_not_ready(monkeypatch):
    monkeypatch.setattr(rt.sys, 'platform', 'win32')
    monkeypatch.setattr(rt.ctypes, 'WinDLL', Mock(side_effect=OSError('126')), raising=False)
    assert not rt.runtime_present()


def test_other_platform_not_misreported(monkeypatch):
    monkeypatch.setattr(rt.sys, 'platform', 'linux')
    with pytest.raises(rt.RuntimePreparationError):
        rt.runtime_present()


@pytest.mark.parametrize('ready,consent', [(True,False),(False,False)])
def test_no_download_without_need_and_consent(monkeypatch,ready,consent):
    monkeypatch.setattr(rt, 'runtime_present', lambda: ready)
    download = Mock(side_effect=AssertionError('download'))
    monkeypatch.setattr(rt, '_verified', download)
    session = NS(ask=Mock(return_value=consent),declined=False)
    assert rt.ensure_vc_runtime(session,Mock()) is ready
    download.assert_not_called()
    if ready: session.ask.assert_not_called()
    else: assert session.declined


def test_no_session_does_not_silently_install(monkeypatch):
    monkeypatch.setattr(rt,'runtime_present',lambda:False)
    with pytest.raises(rt.RuntimePreparationError):
        rt.ensure_vc_runtime(None,Mock())


def test_signed_twice_then_opened_and_rechecked(monkeypatch, tmp_path):
    monkeypatch.setattr(rt.tempfile,'mkdtemp',lambda **k:str(tmp_path))
    monkeypatch.setattr(rt,'runtime_present',Mock(side_effect=[False,False,True]))
    events=[]
    def verified(script,path,timeout):
        assert rt.VERIFY in script
        events.append(('verify',Path(path).name))
        Path(path).write_bytes(b'signed test fixture')
    monkeypatch.setattr(rt,'_verified',verified)
    def opened(path):
        assert Path(path).is_file()
        events.append(('open',Path(path).name))
    s=NS(ask=Mock(side_effect=[True,True,True]),stage=Mock(),detail=Mock())
    assert rt.ensure_vc_runtime(s,Mock(),opener=opened)
    assert [e[0] for e in events]==['verify','verify','open']
    assert s.detail.call_count==1
    assert not (tmp_path/rt.VC_FILE).exists()


@pytest.mark.parametrize('fail_at',[1,2])
def test_failed_signature_never_executes(monkeypatch,tmp_path,fail_at):
    monkeypatch.setattr(rt.tempfile,'mkdtemp',lambda **k:str(tmp_path))
    monkeypatch.setattr(rt,'runtime_present',lambda:False)
    calls=[]
    def verified(script,path,timeout):
        calls.append(path);Path(path).write_bytes(b'not signed')
        if len(calls)==fail_at:raise rt.RuntimePreparationError('signature')
    monkeypatch.setattr(rt,'_verified',verified)
    opener=Mock()
    with pytest.raises(rt.RuntimePreparationError):
        rt.ensure_vc_runtime(NS(ask=Mock(return_value=True),stage=Mock()),Mock(),opener=opener)
    opener.assert_not_called()
    assert not list(tmp_path.glob('*.exe'))


@pytest.mark.parametrize('status,marker,size',[(1,rt.MARKER,1),(0,'wrong',1),(0,rt.MARKER,0)])
def test_verified_requires_exit_exact_marker_and_nonempty_file(monkeypatch,tmp_path,status,marker,size):
    path=tmp_path/'vc.exe';path.write_bytes(b'x'*size)
    monkeypatch.setattr(rt,'_powershell_path',lambda:Path('powershell.exe'))
    monkeypatch.setattr(rt.subprocess,'run',Mock(return_value=NS(returncode=status,stdout=marker.encode())))
    with pytest.raises(rt.RuntimePreparationError):rt._verified(rt.VERIFY,path,60)


def test_powershell_is_fixed_safe_and_tls_is_not_disabled(monkeypatch,tmp_path):
    path=tmp_path/'vc.exe';path.write_bytes(b'x')
    monkeypatch.setattr(rt,'_powershell_path',lambda:Path('powershell.exe'))
    run=Mock(return_value=NS(returncode=0,stdout=(rt.MARKER+'\n').encode()))
    monkeypatch.setattr(rt.subprocess,'run',run)
    rt._verified(rt.DOWNLOAD+rt.VERIFY,path,240)
    argv=run.call_args.args[0];kw=run.call_args.kwargs
    script=base64.b64decode(argv[-1]).decode('utf-16le')
    assert '-NoProfile' in argv and '-NonInteractive' in argv
    assert not kw.get('shell') and kw['timeout']==240
    assert kw['env']['PHOENIX_VC_URL']=='https://aka.ms/vc14/vc_redist.x64.exe'
    assert "'Valid'" in script and 'Microsoft Corporation' in script
    assert 'Tls12' in script and 'SkipCertificateCheck' not in script
    assert 'ServerCertificateValidationCallback' not in script


def test_download_timeout_never_reports_ready(monkeypatch,tmp_path):
    path=tmp_path/'vc.exe'
    monkeypatch.setattr(rt,'_powershell_path',lambda:Path('powershell.exe'))
    monkeypatch.setattr(rt.subprocess,'run',Mock(side_effect=rt.subprocess.TimeoutExpired('powershell',240)))
    with pytest.raises(rt.RuntimePreparationError):rt._verified(rt.DOWNLOAD+rt.VERIFY,path,240)


def test_finishing_native_installer_is_not_assumed_from_open(monkeypatch,tmp_path):
    monkeypatch.setattr(rt.tempfile,'mkdtemp',lambda **k:str(tmp_path))
    monkeypatch.setattr(rt,'runtime_present',lambda:False)
    monkeypatch.setattr(rt,'_verified',lambda script,path,timeout:Path(path).write_bytes(b'fixture'))
    s=NS(ask=Mock(side_effect=[True,False]),stage=Mock(),declined=False)
    opener=Mock()
    assert not rt.ensure_vc_runtime(s,Mock(),opener=opener)
    assert s.declined and opener.call_count==1
