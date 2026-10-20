"""Python bootstrap: no network/install in default tests; native Windows checks explicit."""
import base64
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import launcher
import launcher_download as module

LOG = logging.getLogger('bootstrap-test')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(module, '_powershell_path', lambda: Path('trusted/powershell.exe'))
    run = Mock()
    monkeypatch.setattr(module.subprocess, 'run', run)
    return run


def success():
    return SimpleNamespace(returncode=0, stdout=b'PHOENIX_PYTHON_VERIFIED\r\n', stderr=b'')


def test_native_download_is_verified_before_atomic_publish(tmp_path, monkeypatch, native):
    monkeypatch.setenv('TEMP', str(tmp_path))
    progress = Mock()
    def fetch(cmd, **kwargs):
        part = Path(kwargs['env']['PHOENIX_PYTHON_FILE'])
        assert part.name.endswith('.part.exe')
        assert not part.with_name(module.PYTHON_FILE).exists()
        part.write_bytes(b'test fixture, not an actual executable')
        script = base64.b64decode(cmd[-1]).decode('utf-16le')
        assert script.index('Invoke-WebRequest') < script.index('Get-AuthenticodeSignature')
        assert "-ne 'Valid'" in script
        assert "-cne 'Python Software Foundation'" in script
        assert '-MaximumRedirection 0' in script
        assert kwargs['env']['PHOENIX_PYTHON_URL'] == module.PYTHON_URL
        assert kwargs['timeout'] == module.DOWNLOAD_TIMEOUT
        assert kwargs['creationflags'] == 0x08000000
        assert cmd[1:-1] == ['-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand']
        assert not kwargs.get('shell', False)
        return success()
    native.side_effect = fetch
    path = module.download_python(module.PYTHON_URL, LOG, progress)
    assert path.read_bytes().startswith(b'test fixture')
    assert path.parent.parent == tmp_path
    assert path.parent.name.startswith('phoenix-python-')
    assert list(path.parent.iterdir()) == [path]
    progress.assert_any_call(0, 1, -1)
    progress.assert_called_with(path.stat().st_size, 1, path.stat().st_size)
    module.cleanup_download(path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('kind', ['signature', 'certificate', 'dns', 'network'])
def test_failed_download_or_signature_is_removed(tmp_path, monkeypatch, native, kind):
    monkeypatch.setenv('TEMP', str(tmp_path))
    def fail(cmd, **kwargs):
        Path(kwargs['env']['PHOENIX_PYTHON_FILE']).write_bytes(b'partial/untrusted')
        return SimpleNamespace(returncode=1, stdout=b'', stderr=f'PHOENIX_FAILURE:{kind}'.encode())
    native.side_effect = fail
    with pytest.raises(module.DownloadError) as caught:
        module.download_python(module.PYTHON_URL, LOG, Mock())
    assert caught.value.kind == kind
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('failure', ['empty', 'missing', 'no-marker', 'exit-with-marker'])
def test_process_exit_alone_does_not_prove_verified_download(tmp_path, monkeypatch, native, failure):
    monkeypatch.setenv('TEMP', str(tmp_path))
    def bad(cmd, **kwargs):
        file = Path(kwargs['env']['PHOENIX_PYTHON_FILE'])
        if failure != 'missing': file.write_bytes(b'' if failure == 'empty' else b'fixture')
        return SimpleNamespace(returncode=1 if failure == 'exit-with-marker' else 0,
                               stdout=b'other text' if failure == 'no-marker' else b'PHOENIX_PYTHON_VERIFIED\n',
                               stderr=b'')
    native.side_effect = bad
    with pytest.raises(module.DownloadError):
        module.download_python(module.PYTHON_URL, LOG, Mock())
    assert list(tmp_path.iterdir()) == []


def test_timed_out_native_process_cannot_publish_file(tmp_path, monkeypatch, native):
    monkeypatch.setenv('TEMP', str(tmp_path))
    native.side_effect = subprocess.TimeoutExpired('powershell', 240)
    with pytest.raises(module.DownloadError) as caught:
        module.download_python(module.PYTHON_URL, LOG, Mock())
    assert caught.value.kind == 'timeout'
    assert list(tmp_path.iterdir()) == []


def test_missing_powershell_fails_closed(tmp_path, monkeypatch, native):
    monkeypatch.setenv('TEMP', str(tmp_path))
    native.side_effect = FileNotFoundError('missing')
    with pytest.raises(module.DownloadError) as caught:
        module.download_python(module.PYTHON_URL, LOG, Mock())
    assert caught.value.kind == 'unavailable'
    assert list(tmp_path.iterdir()) == []


def test_untrusted_cached_temp_exe_is_never_reused(tmp_path, monkeypatch, native):
    monkeypatch.setenv('TEMP', str(tmp_path))
    old = tmp_path / module.PYTHON_FILE
    old.write_bytes(b'untrusted old cache')
    def fetch(cmd, **kwargs):
        part = Path(kwargs['env']['PHOENIX_PYTHON_FILE'])
        assert part.parent != old.parent
        part.write_bytes(b'new verified fixture')
        return success()
    native.side_effect = fetch
    path = module.download_python(module.PYTHON_URL, LOG, Mock())
    assert path != old and path.read_bytes() == b'new verified fixture'
    module.cleanup_download(path)
    assert old.read_bytes() == b'untrusted old cache'


@pytest.mark.parametrize('url', ['http://www.python.org/file.exe', 'https://example.com/a.exe',
                                 module.PYTHON_URL + "'; bad-command"])
def test_only_fixed_official_url_is_accepted(tmp_path, monkeypatch, native, url):
    monkeypatch.setenv('TEMP', str(tmp_path))
    with pytest.raises(module.DownloadError):
        module.download_python(url, LOG, Mock())
    native.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_paths_and_urls_are_not_powershell_source(tmp_path, native):
    file = tmp_path / "тест ' $() & установщик.exe"
    file.write_bytes(b'fixture')
    native.return_value = success()
    module.verify_python_installer(file, LOG)
    cmd, = native.call_args.args
    kwargs = native.call_args.kwargs
    script = base64.b64decode(cmd[-1]).decode('utf-16le')
    assert str(file) not in script
    assert kwargs['env']['PHOENIX_PYTHON_FILE'] == str(file.resolve())
    assert kwargs['timeout'] == module.VERIFY_TIMEOUT
    assert 'Invoke-WebRequest' not in script


def test_cleanup_does_not_remove_arbitrary_directory(tmp_path):
    file = tmp_path / module.PYTHON_FILE
    file.write_bytes(b'keep')
    module.cleanup_download(file)
    assert file.read_bytes() == b'keep'


def test_second_signature_check_blocks_installer_execution(monkeypatch, tmp_path):
    file = tmp_path / module.PYTHON_FILE
    file.write_bytes(b'unsigned')
    monkeypatch.setattr(launcher, 'verify_python_installer', Mock(side_effect=module.DownloadError('signature')))
    run = Mock(); monkeypatch.setattr(launcher.subprocess, 'run', run)
    error = Mock(); monkeypatch.setattr(launcher, 'error', error)
    assert not launcher.run_python_installer(file, LOG)
    run.assert_not_called()
    error.assert_called_once()


def test_verified_installer_preserves_interactive_command_and_find(monkeypatch, tmp_path):
    file = tmp_path / module.PYTHON_FILE
    verify = Mock(); run = Mock(); cleanup = Mock()
    monkeypatch.setattr(launcher, 'verify_python_installer', verify)
    monkeypatch.setattr(launcher.subprocess, 'run', run)
    monkeypatch.setattr(launcher, 'cleanup_download', cleanup)
    monkeypatch.setattr(launcher.time, 'sleep', lambda _: None)
    monkeypatch.setattr(launcher, 'find_python', lambda _: 'Python311/python.exe')
    assert launcher.run_python_installer(file, LOG)
    verify.assert_called_once_with(file, LOG)
    run.assert_called_once_with([str(file)], check=False)
    cleanup.assert_called_once_with(file)


def test_installer_cancel_or_not_installed_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, 'verify_python_installer', Mock())
    monkeypatch.setattr(launcher.subprocess, 'run', Mock())
    monkeypatch.setattr(launcher.time, 'sleep', lambda _: None)
    monkeypatch.setattr(launcher, 'find_python', lambda _: None)
    assert not launcher.run_python_installer(tmp_path / module.PYTHON_FILE, LOG)


@pytest.mark.parametrize('kind,expected', [('certificate', 'HTTPS-сертификат'), ('dns', 'DNS'),
    ('signature', 'Подпись'), ('timeout', 'время ожидания'), ('unavailable', 'PowerShell')])
def test_launcher_reports_actionable_error(monkeypatch, kind, expected):
    monkeypatch.setattr(launcher, 'info', Mock())
    monkeypatch.setattr(launcher, 'download_python', Mock(side_effect=module.DownloadError(kind)))
    error = Mock(); monkeypatch.setattr(launcher, 'error', error)
    assert launcher.download_python_installer(LOG) is None
    assert expected in error.call_args.args[0]


def test_successful_launcher_download_delegates_without_urllib(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, 'info', Mock())
    file = tmp_path / module.PYTHON_FILE
    download = Mock(return_value=file)
    monkeypatch.setattr(launcher, 'download_python', download)
    monkeypatch.setattr(launcher.urllib.request, 'urlretrieve', Mock(side_effect=AssertionError('old HTTPS path')))
    assert launcher.download_python_installer(LOG) == file
    download.assert_called_once_with(launcher.PYTHON_INSTALLER_URL, LOG, launcher._download_progress)


def test_helper_shipped_in_source_payload_and_imported_by_frozen_entrypoint():
    import ast
    from scripts.release_payload import collect_payload
    assert 'launcher_download.py' in collect_payload(ROOT, include_exe=False)
    tree = ast.parse((ROOT / 'launcher.py').read_text(encoding='utf-8'))
    assert any(isinstance(n, ast.ImportFrom) and n.module == 'launcher_download' for n in tree.body)


@pytest.mark.skipif(sys.platform != 'win32', reason='Requires native Windows PowerShell')
def test_native_powershell_rejects_unsigned_exe(tmp_path):
    file = tmp_path / 'unsigned.exe'
    file.write_bytes(b'MZ unsigned test fixture')
    with pytest.raises(module.DownloadError) as caught:
        module.verify_python_installer(file, LOG)
    assert caught.value.kind == 'signature'


@pytest.mark.skipif(sys.platform != 'win32' or os.environ.get('PHOENIX_TEST_PYTHON_DOWNLOAD') != '1',
                    reason='Opt-in Windows HTTPS download, about 25 MB; no installation')
def test_live_windows_python_download():
    path = module.download_python(module.PYTHON_URL, LOG, lambda *_: None)
    try:
        module.verify_python_installer(path, LOG)
        assert path.stat().st_size > 0
    finally:
        module.cleanup_download(path)
