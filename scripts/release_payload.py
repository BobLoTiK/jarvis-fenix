"""Curated installer payload; never recurse over the developer's entire workspace."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

ROOT_FILES = (
    'launcher.py', 'launcher_ui.py', 'launcher_download.py', 'launcher_ollama.py', 'requirements.txt', 'config.example.json', 'README.md',
    'ARCHITECTURE.md', 'CHANGELOG.md', 'LICENSE', 'start_fenix.bat',
    'start_fenix_debug.bat', 'create_shortcut.bat',
)
PACKS = ('apps.json', 'games.json', 'sites.json', 'system.json', 'work.json')
BRANDS = ('app', 'audio', 'commands', 'dialog', 'microphone', 'persona', 'phoenix', 'settings', 'timer')
REQUIRED_MODULES = ('gui', 'gui_sidebar', 'gui_preferences', 'gui_home',
                    'gui_home_fx', 'gui_home_actions', 'gui_widgets', 'tasks')
BLOCKED_PARTS = {'__pycache__', '.venv', '.venv311', 'profiles', 'logs', 'models', 'voices', 'dist', 'build'}
BLOCKED_NAMES = {'config.json', 'system_caps.json', 'tasks.json', 'timers.json',
                 'dialog.json', 'user_profile.json'}


def collect_payload(root, include_exe=True):
    """Validate before changing output. Return sorted relative public file paths."""
    root = Path(root).resolve()
    paths = set(ROOT_FILES)
    paths.update(f'packs/{name}' for name in PACKS)
    paths.update(f'jarvis/{name}.py' for name in REQUIRED_MODULES)
    for folder in ('jarvis', 'scripts'):
        paths.update(p.relative_to(root).as_posix() for p in (root/folder).rglob('*.py')
                     if not any(part in BLOCKED_PARTS for part in p.relative_to(root).parts))
    for name in BRANDS:
        for theme in ('dark', 'light'):
            paths.add(f'jarvis/assets/brand/{name}-{theme}.png')
            paths.add(f'jarvis/assets/brand/{name}-{theme}.svg')
    paths.update(('jarvis/icon.ico', 'jarvis/assets/brand/tray.png',
                  'jarvis/assets/brand/README.md', 'jarvis/sounds/fireworks.wav'))
    paths.update(f'assets/nonverbal/{name}' for name in
                 ('README.md', 'sources.json', 'hmm.wav', 'laugh.wav', 'sigh.wav', 'yawn.wav'))
    paths.update(('assets/readme/hero.svg', 'assets/readme/hero-mobile.svg', 'docs/USER_GUIDE.md'))
    # Only public Markdown documentation, not screenshots, logs or audio recordings.
    paths.update(p.relative_to(root).as_posix() for p in (root/'docs').glob('*.md'))
    paths.update(p.relative_to(root).as_posix() for p in (root/'docs/releases').glob('*.md'))
    if include_exe:
        paths.add('Феникс.exe')
    for name in sorted(paths):
        p = root/name
        if any(part in BLOCKED_PARTS for part in Path(name).parts) or p.name in BLOCKED_NAMES:
            raise ValueError(f'Private/generated payload path: {name}')
        if not p.is_file() or not p.stat().st_size:
            raise ValueError(f'Missing or empty release resource: {name}')
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError(f'Linked/outside release resource: {name}')
    cfg = json.loads((root/'config.example.json').read_text(encoding='utf-8'))
    for key in ('gui_home_widgets', 'gui_home_shortcuts'):
        if cfg.get(key) != []:
            raise ValueError(f'Public {key} default must be an empty list')
    return sorted(paths)


def stage_payload(root, destination, include_exe=True):
    """Publish a clean builder-owned directory; no stale files from older builds."""
    root, destination = Path(root).resolve(), Path(destination)
    if destination.is_symlink():
        raise ValueError('Payload destination must not be a symlink')
    destination = destination.resolve()
    if destination in (root, root/'build') or not destination.is_relative_to(root/'build'):
        raise ValueError('Payload destination must be inside the project build directory')
    files = collect_payload(root, include_exe)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='payload-', dir=destination.parent))
    try:
        manifest = []
        for name in files:
            target = temp/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root/name, target)
            manifest.append({'path':name, 'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        (temp/'release-manifest.json').write_text(
            json.dumps({'schema':1, 'files':manifest}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        if destination.exists():
            shutil.rmtree(destination)
        temp.replace(destination)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return files
