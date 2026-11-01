"""Public payload, reproducible manifest and bootstrap regression checks."""
import hashlib
import importlib.util
import json
import logging
import os
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


def _load_build_exe():
    """Импорт scripts/build_exe.py как модуля: побочных эффектов на импорте нет."""
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "scripts" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_exe_is_built_with_version_resource():
    """У Феникс.exe должны быть версия и название в «Свойствах файла».

    Без --version-file PyInstaller собирает exe без метаданных: у готового
    установщика «Подробно» пустые — ни версии, ни продукта (видно на
    CI-артефакте 0.0.0-ci). Ловим это по исходнику сборки, не по бинарю.
    """
    text = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    assert "--version-file" in text, "build_exe.py больше не передаёт ресурс версии"
    module = _load_build_exe()
    version = module.load_version()
    assert version == __import__("jarvis").__version__
    resource = module.make_version_file(version)
    assert f"'{version}'" in resource, "в ресурсе нет версии файла"
    assert "ProductName" in resource and "Феникс" in resource
    assert "filevers=(" in resource and "OriginalFilename" in resource
    assert module.version_tuple(version) == (2, 1, 2, 0) or len(module.version_tuple(version)) == 4


def test_only_public_files(release_tree):
    root = release_tree
    for name in ('config.json', 'system_caps.json', 'profiles/alice.json',
                 'jarvis/__pycache__/secret.py', 'models/private.py', 'tasks.json'):
        p = root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('private', encoding="utf-8")
    files = rp.collect_payload(root, False)
    assert 'jarvis/gui_widgets.py' in files
    assert 'jarvis/gui_home_actions.py' in files
    # Личные данные и мусор в поставку не идут: ни файлов настроек, ни моделей,
    # ни кэша байткода, ни профилей.
    assert not any(p in ('config.json', 'system_caps.json', 'tasks.json') for p in files)
    for personal in ('profiles/alice.json', 'jarvis/__pycache__/secret.py', 'models/private.py'):
        assert personal not in files
    # Но исходник с «secret» в имени — публичный код, а не секрет пользователя.
    assert 'jarvis/secrets_store.py' in files



def test_readme_illustrations_are_shipped(release_tree):
    files = rp.collect_payload(release_tree, False)
    for name in ('hero', 'hero-mobile', 'commands', 'commands-mobile',
                 'themes', 'themes-mobile'):
        assert f'assets/readme/{name}.svg' in files


def test_stage_clean_manifest(release_tree):
    root = release_tree
    dest = root/'build/release-payload'
    dest.mkdir(parents=True)
    (dest/'obsolete.txt').write_text('old', encoding="utf-8")
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
    (dest/'previous').write_text('keep', encoding="utf-8")
    (release_tree/'jarvis/gui_widgets.py').unlink()
    with pytest.raises(ValueError, match='Missing'):
        rp.stage_payload(release_tree, dest, False)
    assert (dest/'previous').read_text(encoding="utf-8") == 'keep'


@pytest.mark.parametrize('path', ['..', '.', 'build', 'profiles/payload'])
def test_reject_unsafe_destination(release_tree, path):
    with pytest.raises(ValueError):
        rp.stage_payload(release_tree, release_tree/path, False)


def test_reject_linked_resource(release_tree, tmp_path):
    p = release_tree/'jarvis/gui_widgets.py'
    p.unlink()
    outside = tmp_path/'outside.py'
    outside.write_text('secret', encoding="utf-8")
    try:
        p.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink privilege is unavailable")
    with pytest.raises(ValueError, match='Linked'):
        rp.collect_payload(release_tree, False)


def test_no_default_user_widgets(release_tree):
    p = release_tree/'config.example.json'
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg['gui_home_widgets'] = ['tasks']
    p.write_text(json.dumps(cfg), encoding="utf-8")
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
    s = (ROOT/'installer.iss').read_text(encoding="utf-8")
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
    req.write_text('changed', encoding="utf-8")
    assert not launcher.check_dependencies(tmp_path, log)
    (tmp_path/'.venv311/phoenix-requirements.sha256').write_bytes(b'\xff')
    assert not launcher.check_dependencies(tmp_path, log)


def test_caps_atomic_failure_preserves_old(tmp_path, monkeypatch):
    p = tmp_path/'system_caps.json'
    p.write_text('previous', encoding="utf-8")
    def fail(*_):
        raise OSError('disk failure')
    monkeypatch.setattr(check_caps.os, 'replace', fail)
    with pytest.raises(OSError):
        check_caps.write_caps({'cpu':{}}, p)
    assert p.read_text(encoding="utf-8") == 'previous'
    assert list(tmp_path.iterdir()) == [p]


def test_caps_skip_valid_only(tmp_path, monkeypatch):
    p = tmp_path/'system_caps.json'
    p.write_text(json.dumps({k:{} for k in ('volume','brightness','layout','cpu')}), encoding="utf-8")
    monkeypatch.setattr(check_caps, 'OUTPUT', p)
    monkeypatch.setattr(check_caps, 'check_cpu', lambda: pytest.fail('must skip valid cache'))
    assert check_caps.main(['--if-missing']) == 0
    p.write_text('{broken', encoding="utf-8")
    assert not check_caps.caps_valid(p)


def test_caps_probe_failure_does_not_block_launch(monkeypatch, tmp_path):
    def fail(*_, **__):
        raise OSError('no device')
    monkeypatch.setattr(launcher.subprocess, 'run', fail)
    launcher.ensure_local_caps(tmp_path, logging.getLogger('test'))


def test_cancel_dependencies_has_no_network(tmp_path, monkeypatch):
    (tmp_path/'requirements.txt').write_text('test', encoding="utf-8")
    monkeypatch.setattr(launcher, 'msg_box', lambda *_: 2)
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *_,**__: pytest.fail('network after cancel'))
    assert not launcher.install_dependencies(tmp_path, logging.getLogger('test'))


def test_cancel_dependencies_problems_are_logged(tmp_path, monkeypatch, caplog):
    """Падение pip без хвоста вывода делает причину невидимой в журнале."""
    (tmp_path/'requirements.txt').write_text('test', encoding="utf-8")
    monkeypatch.setattr(launcher, 'msg_box', lambda *_: 1)

    class Result:
        returncode = 2
        stdout = 'Collecting vosk'
        stderr = 'UnicodeDecodeError: charmap codec can not decode byte 0x8f'

    monkeypatch.setattr(launcher.subprocess, 'run', lambda *_, **__: Result())
    monkeypatch.setattr(launcher, 'error', lambda *_, **__: None)
    with caplog.at_level(logging.ERROR):
        assert not launcher.install_dependencies(tmp_path, logging.getLogger('test'))
    assert 'pip install упал' in caplog.text
    assert 'charmap' in caplog.text


def test_launcher_sets_certifi_bundle_for_https(tmp_path, monkeypatch):
    """На чистой Windows urllib не находит корневой сертификат (проверено в ВМ).

    Скачивание модели Vosk падало с SSLCertVerificationError; приложение
    использует jarvis.https_trust, а лаунчер — нет. Проверяем, что вызов
    возвращает режим и подставляет существующий бандл.
    """
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    logger = logging.getLogger('test')
    mode = launcher.ensure_https_trust(logger)
    try:
        assert mode == 'certifi'
        assert Path(os.environ['SSL_CERT_FILE']).is_file()
    finally:
        os.environ.pop('SSL_CERT_FILE', None)


def test_launcher_survives_missing_certifi(monkeypatch):
    import types, sys
    broken = types.ModuleType('jarvis.https_trust')

    def boom():
        raise ImportError('no certifi')

    broken.configure_https_trust = boom
    monkeypatch.setitem(sys.modules, 'jarvis.https_trust', broken)
    assert launcher.ensure_https_trust(logging.getLogger('test')) == 'system'


def test_launcher_configures_https_before_network():
    source = (ROOT / 'launcher.py').read_text(encoding='utf-8')
    assert 'ensure_https_trust(logger)' in source
    assert source.index('ensure_https_trust(logger)') < source.index('def download_vosk_model')


def test_requirements_files_are_decodable_with_any_ansi_codepage():
    """pip читает requirements.txt кодировкой локали (cp1252), а не UTF-8.

    На англоязычной Windows байты кириллицы в UTF-8 падают с UnicodeDecodeError,
    и установщик показывает «нет интернета». Поэтому либо чистый ASCII, либо
    явная строка coding — тогда pip декодирует файл как UTF-8.
    """
    import codecs
    for path in sorted(ROOT.glob('requirements*.txt')):
        data = path.read_bytes()
        if all(b < 128 for b in data):
            continue
        assert data.decode('utf-8'), f'{path.name}: не UTF-8'
        first_two = data.split(b'\n')[:2]
        assert any(b'coding' in line and b'utf-8' in line.lower() for line in first_two), (
            f'{path.name}: кириллица без строки coding: utf-8 — pip упадёт на cp1252')

def test_startup_reliability_helpers_are_shipped(release_tree):
    files = rp.collect_payload(release_tree, False)
    for name in ('launcher_runtime.py', 'jarvis/https_trust.py',
                 'scripts/prepare_flet_client.py'):
        assert name in files


def test_optional_aec_files_shipped_but_not_required_by_base_dependencies(release_tree):
    files=rp.collect_payload(release_tree,False)
    assert {'install_aec.bat','requirements-aec.txt','jarvis/echo.py'}<=set(files)
    assert 'pywebrtc-audio==0.2.0' in (release_tree/'requirements-aec.txt').read_text(encoding="utf-8")
    assert 'pywebrtc' not in (release_tree/'requirements.txt').read_text(encoding="utf-8")
