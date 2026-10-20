"""Small config bridge run by installed .venv311, never by frozen bootstrap imports.

stdin/stdout JSON only. Uses project paths and config_manager's existing lock
and atomic writer. Read is side-effect-free for config content; corrupt JSON
fails closed. Select compares current model/endpoint under the same file lock.
"""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis import config_manager, paths
from jarvis.config import DEFAULT_CONFIG


def _raw(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('configuration')
    return data


def _settings(raw):
    data = {key: raw.get(key, DEFAULT_CONFIG[key]) for key in ('llm_model', 'ollama_url', 'mode')}
    if any(not isinstance(v, str) or not v or len(v) > 2048 for v in data.values()):
        raise ValueError('configuration')
    return data


def process(request, path=None):
    path = Path(path) if path is not None else paths.config_path()
    if request.get('operation') == 'read':
        return {'ok': True, **_settings(_raw(path))}
    if request.get('operation') != 'select':
        raise ValueError('operation')
    model = request.get('model')
    if (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}', model)
            or model.lower().endswith((':cloud', '-cloud'))):
        raise ValueError('model')
    # Reuse the manager's per-path interprocess lock; its FileLock is recursive.
    path.parent.mkdir(parents=True, exist_ok=True)
    t_lock, f_lock = config_manager._get_locks(path)
    with t_lock, f_lock:
        raw = _raw(path)
        current = _settings(raw)
        expected = request.get('expected')
        if not isinstance(expected, dict) or any(expected.get(k) != v for k, v in current.items()):
            return {'ok': False, 'error': 'conflict'}
        if current['llm_model'] == model:
            return {'ok': True}
        raw['llm_model'] = model
        if not config_manager.save(raw, path=path):
            return {'ok': False, 'error': 'write'}
        return {'ok': True}


def main():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError('request size')
        request = json.loads(raw.decode('utf-8'))
        if not isinstance(request, dict):
            raise ValueError('request')
        result = process(request)
    except Exception:
        result = {'ok': False, 'error': 'configuration'}
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + '\n')
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
