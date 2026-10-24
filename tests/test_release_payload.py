"""Public payload, reproducible manifest and bootstrap regression checks."""
import hashlib
import json
import logging
import shutil
from pathlib import Path

import pytest
from scripts import release_payload as rp, build_setup, check_caps
import launcher

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def release_tree(tmp_path):
    root = tmp_path / 'project'
    for name in rp.collect_payload(ROOT, include_exe=False):
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    return root


def test_only_public_files(release_tree):
    root = release_tree
    for name in ('config.json', 'system_caps.json', 'profiles/alice.json',
                 'jarvis/__pycache__/secret.py', 'models/private.py', 'tasks.json'):
        p = root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('private')
    files = rp.collect_payload(root, False)
    assert 'jarvis/gui_widgets.py' in files
    assert 'jarvis/gui_home_actions.py' in files
    assert not any('private' in p or 'secret' in p or p in ('config.json','system_caps.json','tasks.json') for p in files)



def test_readme_illustrations_are_shipped(release_tree):
    files = rp.collect_payload(release_tree, False)
    for name in ('hero', 'hero-mobile', 'commands', 'commands-mobile',
                 'themes', 'themes-mobile'):
        assert f'assets/readme/{name}.svg' in files


def test_stage_clean_manifest(release_tree):
    root = release_tree
    dest = root/'build/release-payload'
    dest.mkdir(parents=True)
    (dest/'obsolete.txt').write_text('old')
    files = rp.stage_payload(root, dest, False)
    assert not (dest/'obsolete.txt').exists()
    manifest = (dest/'release-manifest.json').read_bytes()
    for entry in json.loads(manifest)['files']:
        assert entry['sha256'] == hashlib.sha256((dest/entry['path']).read_bytes()).hexdigest()
    assert len(files) == len(json.loads(manifest)['files'])
    rp.stage_payload(root, dest, False)
    assert (dest/'release-manifest.json').read_bytes() == manifest


def test_failed_validation_keeps_previous_payload(release_tree):
    dest = release_tree/'build/payload'
    dest.mkdir(parents=True)
    (dest/'previous').write_text('keep')
    (release_tree/'jarvis/gui_widgets.py').unlink()
    with pytest.raises(ValueError, match='Missing'):
        rp.stage_payload(release_tree, dest, False)
    assert (dest/'previous').read_text() == 'keep'


@pytest.mark.parametrize('path', ['..', '.', 'build', 'profiles/payload'])
def test_reject_unsafe_destination(release_tree, path):
    with pytest.raises(ValueError):
        rp.stage_payload(release_tree, release_tree/path, False)


def test_reject_linked_resource(release_tree, tmp_path):
    p = release_tree/'jarvis/gui_widgets.py'
    p.unlink()
    outside = tmp_path/'outside.py'
    outside.write_text('secret')
    try:
        p.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink privilege is unavailable")
    with pytest.raises(ValueError, match='Linked'):
        rp.collect_payload(release_tree, False)


def test_no_default_user_widgets(release_tree):
    p = release_tree/'config.example.json'
    cfg = json.loads(p.read_text())
    cfg['gui_home_widgets'] = ['tasks']
    p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match='empty list'):
        rp.collect_payload(release_tree, False)


def test_preflight_never_compiles(monkeypatch):
    monkeypatch.setattr('sys.argv', ['build_setup.py','--check'])
    monkeypatch.setattr(build_setup, 'run', lambda *_: pytest.fail('external compiler'))
    assert build_setup.main() == 0


def test_preflight_requires_installer(monkeypatch, tmp_path):
    monkeypatch.setattr('sys.argv', ['build_setup.py','--check'])
    monkeypatch.setattr(build_setup, 'ISS', tmp_path/'absent.iss')
    assert build_setup.main() == 1


def test_installer_curated_and_both_mutexes():
    s = (ROOT/'installer.iss').read_text()
    assert '{#PayloadDir}\\*' in s
    assert 'AppMutex=Local\\JarvisPhoenixSingleInstance,Local\\JarvisPhoenixLauncherSetup' in s
    assert 'Source: "system_caps.json"' not in s
    assert 'Source: "jarvis\\*"' not in s


def test_receipt_changed_requirements_and_corrupt_receipt(tmp_path, monkeypatch):
    (tmp_path/'.venv311').mkdir()
    req = tmp_path/'requirements.txt'
    req.write_bytes(b'flet>=1.0.3,<1.1\r\n')
    assert launcher.record_dependency_receipt(tmp_path)
    monkeypatch.setattr(launcher, '_probe_dependencies', lambda *_: True)
    log = logging.getLogger('test')
    assert launcher.check_dependencies(tmp_path, log)
    req.write_bytes(b'flet>=1.0.3,<1.1\n')
    assert launcher.check_dependencies(tmp_path, log)
    req.write_text('changed')
    assert not launcher.check_dependencies(tmp_path, log)
    (tmp_path/'.venv311/phoenix-requirements.sha256').write_bytes(b'\xff')
    assert not launcher.check_dependencies(tmp_path, log)


def test_caps_atomic_failure_preserves_old(tmp_path, monkeypatch):
    p = tmp_path/'system_caps.json'
    p.write_text('previous')
    def fail(*_):
        raise OSError('disk failure')
    monkeypatch.setattr(check_caps.os, 'replace', fail)
    with pytest.raises(OSError):
        check_caps.write_caps({'cpu':{}}, p)
    assert p.read_text() == 'previous'
    assert list(tmp_path.iterdir()) == [p]


def test_caps_skip_valid_only(tmp_path, monkeypatch):
    p = tmp_path/'system_caps.json'
    p.write_text(json.dumps({k:{} for k in ('volume','brightness','layout','cpu')}))
    monkeypatch.setattr(check_caps, 'OUTPUT', p)
    monkeypatch.setattr(check_caps, 'check_cpu', lambda: pytest.fail('must skip valid cache'))
    assert check_caps.main(['--if-missing']) == 0
    p.write_text('{broken')
    assert not check_caps.caps_valid(p)


def test_caps_probe_failure_does_not_block_launch(monkeypatch, tmp_path):
    def fail(*_, **__):
        raise OSError('no device')
    monkeypatch.setattr(launcher.subprocess, 'run', fail)
    launcher.ensure_local_caps(tmp_path, logging.getLogger('test'))


def test_cancel_dependencies_has_no_network(tmp_path, monkeypatch):
    (tmp_path/'requirements.txt').write_text('test')
    monkeypatch.setattr(launcher, 'msg_box', lambda *_: 2)
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *_,**__: pytest.fail('network after cancel'))
    assert not launcher.install_dependencies(tmp_path, logging.getLogger('test'))


def test_startup_reliability_helpers_are_shipped(release_tree):
    files = rp.collect_payload(release_tree, False)
    for name in ('launcher_runtime.py', 'jarvis/https_trust.py',
                 'scripts/prepare_flet_client.py'):
        assert name in files


def test_optional_aec_files_shipped_but_not_required_by_base_dependencies(release_tree):
    files=rp.collect_payload(release_tree,False)
    assert {'install_aec.bat','requirements-aec.txt','jarvis/echo.py'}<=set(files)
    assert 'pywebrtc-audio==0.2.0' in (release_tree/'requirements-aec.txt').read_text()
    assert 'pywebrtc' not in (release_tree/'requirements.txt').read_text()
