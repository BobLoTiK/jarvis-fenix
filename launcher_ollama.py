"""Optional Ollama setup: explicit consent, local inventory/pull, safe config bridge.

No inference, cloud models, auto hardware tuning or silent choice replacement.
The bootstrap UI owns widgets; this module runs entirely on its worker thread.
"""
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit


# Approximate download sizes: https://ollama.com/library/qwen2.5/tags (2026-10).
# This is a size catalog, not measured quality/speed or a RAM requirement.
# Approximate download sizes: https://ollama.com/library/qwen2.5/tags (2026-10).
# This is a size catalog, not measured quality/speed or a RAM requirement.
MODEL_OPTIONS = (
    ('qwen2.5:1.5b-instruct', 'Qwen2.5 1.5B — около 986 МБ'),
    ('qwen2.5:3b-instruct', 'Qwen2.5 3B — около 1,9 ГБ'),
    ('qwen2.5:7b-instruct', 'Qwen2.5 7B — около 4,7 ГБ'),
)
DEFAULT_URL = 'http://127.0.0.1:11434'
DOWNLOAD_PAGE = 'https://ollama.com/download/windows'
MAX_JSON = 2 * 1024 * 1024
MAX_LINE = 65536
PULL_DEADLINE = 7200


class SetupError(RuntimeError):
    pass


def local_model(name):
    return (isinstance(name, str) and
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}', name) is not None and
            not name.lower().endswith((':cloud', '-cloud')))


def canonical(name):
    return name if ':' in name.rsplit('/', 1)[-1] else name + ':latest'


def local_endpoint(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parts.username is not None or parts.password is not None
                or parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ValueError('not local')
        _ = parts.port  # validate port before any network access
        return url.rstrip('/')
    except (ValueError, TypeError) as exc:
        raise SetupError('endpoint') from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError('redirect')


class OllamaAPI:
    def __init__(self, url):
        self.url = local_endpoint(url)
        # Loopback only; don't send local setup requests via environment proxies.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def inventory(self):
        try:
            with self.opener.open(self.url + '/api/tags', timeout=2) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError('inventory size')
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('models'), list):
                raise ValueError('inventory')
            names = []
            for item in data['models']:
                if not isinstance(item, dict):
                    raise ValueError('inventory entry')
                name = item.get('name', item.get('model'))
                if local_model(name) and not item.get('remote_host') and not item.get('remote_model'):
                    names.append(name)
            return sorted(set(names))
        except Exception as exc:
            raise SetupError('inventory') from exc

    def check_completion(self, name):
        if not local_model(name):
            raise SetupError('model')
        request = urllib.request.Request(
            self.url + '/api/show',
            data=json.dumps({'model': name, 'verbose': False}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError('show size')
            data = json.loads(raw)
            if (not isinstance(data, dict) or data.get('remote_host') or data.get('remote_model')
                    or not isinstance(data.get('capabilities'), list)
                    or 'completion' not in data['capabilities']):
                raise SetupError('capabilities')
        except Exception as exc:
            if isinstance(exc, SetupError):
                raise
            raise SetupError('capabilities') from exc

    def pull(self, name, progress):
        if name not in dict(MODEL_OPTIONS):
            raise SetupError('model')
        body = json.dumps({'model': name, 'stream': True, 'insecure': False}).encode('utf-8')
        request = urllib.request.Request(self.url + '/api/pull', data=body,
                                         headers={'Content-Type': 'application/json'})
        deadline = time.monotonic() + PULL_DEADLINE
        success = False
        try:
            with self.opener.open(request, timeout=30) as response:
                while True:
                    if time.monotonic() > deadline:
                        raise SetupError('timeout')
                    line = response.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if len(line) > MAX_LINE:
                        raise SetupError('pull data')
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get('error'):
                        raise SetupError('pull')
                    if event.get('status') == 'success':
                        success = True
                        break
                    total, completed = event.get('total'), event.get('completed')
                    if (type(total) is int and type(completed) is int and
                            0 < total <= 2**63 - 1 and 0 <= completed <= total):
                        progress(completed / total,
                                 f'Текущий слой: {completed/1000000:.1f} из {total/1000000:.1f} МБ')
                    else:
                        progress(None, 'Получаем манифест / проверяем файлы модели…')
            if not success:
                raise SetupError('incomplete')
            progress(None, 'Проверяем наличие модели в Ollama…')
            if canonical(name) not in {canonical(n) for n in self.inventory()}:
                raise SetupError('not installed')
        except Exception as exc:
            if isinstance(exc, SetupError):
                raise
            raise SetupError('pull') from exc


class ConfigBridge:
    """Use installed runtime's paths/config_manager, without bundling its dependencies."""
    def __init__(self, root, logger, python_exe=None):
        self.root = Path(root)
        self.logger = logger
        self.python = Path(python_exe) if python_exe else self.root / '.venv311/Scripts/python.exe'

    def _call(self, payload):
        try:
            result = subprocess.run(
                [str(self.python), '-I', str(self.root / 'scripts/bootstrap_ollama_config.py')],
                input=json.dumps(payload).encode('utf-8'), capture_output=True, timeout=20,
                creationflags=0x08000000,
            )
            if len(result.stdout) > 16384:
                raise ValueError('bridge size')
            data = json.loads(result.stdout)
            if result.returncode or not isinstance(data, dict) or data.get('ok') is not True:
                raise ValueError('bridge failed')
            return data
        except Exception as exc:
            raise SetupError('configuration') from exc

    def read(self):
        data = self._call({'operation': 'read'})
        if any(not isinstance(data.get(key), str) or not data[key] for key in ('llm_model', 'ollama_url', 'mode')):
            raise SetupError('configuration')
        return {key: data[key] for key in ('llm_model', 'ollama_url', 'mode')}

    def select(self, name, expected):
        self._call({'operation': 'select', 'model': name, 'expected': expected})


def choices(installed):
    result = []
    seen = set()
    # Existing local models first; no forced replacement by the bundled catalog.
    for name in installed[:100]:
        if local_model(name) and canonical(name) not in seen:
            result.append({'value': name, 'label': name + ' — уже скачана', 'installed': True})
            seen.add(canonical(name))
    for name, label in MODEL_OPTIONS:
        if canonical(name) not in seen:
            result.append({'value': name, 'label': label, 'installed': False})
    return result


def _wait_inventory(api, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return api.inventory()
        except SetupError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(.5)


def ensure_server(api, session, logger, find_exe, start_server, open_site):
    try:
        return api.inventory()
    except SetupError:
        pass
    is_default = api.url in (DEFAULT_URL, 'http://localhost:11434')
    site_opened = False
    while True:
        exe = find_exe(logger) if is_default else None
        if exe is not None:
            session.stage('Запускаем Ollama', 'Ждём готовности локального сервера…', show=True)
            try:
                start_server(exe, logger)
                installed = _wait_inventory(api)
                if installed is not None:
                    return installed
            except Exception:
                logger.exception('Не удалось запустить локальную Ollama')
        elif is_default and not site_opened:
            if not session.ask(
                'Для свободного диалога нужна Ollama и отдельная языковая модель.\n\n'
                'Откроется официальный сайт. Установи Ollama, затем вернись сюда: '
                'мы предложим модели и скачаем выбранную без команд в терминале.\n\n'
                'Можно продолжить без ИИ: обычные команды и голос останутся доступны.',
                'Феникс — установка Ollama', 'Открыть сайт', 'Продолжить без ИИ'):
                return None
            try:
                open_site(DOWNLOAD_PAGE)
                site_opened = True
            except Exception:
                logger.exception('Не удалось открыть сайт Ollama')
                session.detail('Сайт не открылся. Адрес: ' + DOWNLOAD_PAGE)
        server_note = (('Сайт установки: ' + DOWNLOAD_PAGE + '\n') if is_default else
                       ('Запусти локальный сервер по адресу ' + api.url + '. Адрес не меняем.\n'))
        if not session.ask(
            server_note + 'Заверши установку и запусти Ollama. Нажми «Проверить», когда будешь готов.\n\n'
            'Если Ollama пока недоступна, можно продолжить без ИИ. '
            'Настройки модели не изменятся.',
            'Феникс — ожидаем Ollama', 'Проверить', 'Продолжить без ИИ'):
            return None
        try:
            return api.inventory()
        except SetupError:
            session.detail('Сервер пока не отвечает или вернул некорректный список моделей.')


def prepare_models(root, session, logger, find_exe, start_server, open_site,
                   bridge=None, api_factory=OllamaAPI):
    bridge = bridge or ConfigBridge(root, logger)
    try:
        settings = bridge.read()
        if settings['mode'] == 'commands':
            logger.info('Режим команд: подготовка ИИ не требуется')
            return
        url = local_endpoint(settings['ollama_url'])
    except SetupError:
        session.ask('Не удалось прочитать настройки или указан нестандартный/удалённый сервер.\n'
                    'Ничего не меняем. Сервер и модель можно настроить в Фениксе.',
                    'Настройка ИИ пропущена', 'Продолжить', 'Продолжить без ИИ')
        return
    api = api_factory(url)
    installed = ensure_server(api, session, logger, find_exe, start_server, open_site)
    if installed is None:
        logger.info('Настройка Ollama пропущена пользователем; конфигурация сохранена')
        return
    if canonical(settings['llm_model']) in {canonical(n) for n in installed}:
        logger.info('Выбранная модель Ollama уже установлена')
        return
    while True:
        options = choices(installed)
        selected = session.choose_model(
            'Феникс — модель для диалога',
            'Ollama готова. Выбери локальную модель. Размеры загрузки примерные; '
            'для работы потребуется дополнительная память. GPU не обязателен, '
            'скорость зависит от компьютера.\n\n'
            f'Текущая модель: {settings["llm_model"]} (не найдена локально).\n'
            'Скачаем только выбранную модель. Отказ не меняет настройки.',
            options,
        )
        if selected is None:
            return
        option = next((o for o in options if o['value'] == selected), None)
        if option is None:
            raise SetupError('choice')
        try:
            current = api.inventory()
            if canonical(selected) not in {canonical(n) for n in current}:
                session.stage('Скачиваем модель Ollama', selected + '\nПроцент относится к текущему слою, не ко всей модели.', show=True)
                api.pull(selected, session.progress_update)
            # Recheck both inventory and config after download; never publish a fake success.
            if canonical(selected) not in {canonical(n) for n in api.inventory()}:
                raise SetupError('not installed')
            api.check_completion(selected)
            bridge.select(selected, settings)
            session.stage('Модель подготовлена', selected + '\nВыбор сохранён. Это проверка наличия, не тест генерации.', show=True)
            logger.info('Модель Ollama выбрана и сохранена: %s', selected)
            return
        except SetupError as exc:
            logger.exception('Не удалось скачать модель или сохранить выбор')
            reason = ('Модель не подтвердила поддержку генерации текста. Выбери другую модель.\n'
                      if str(exc) == 'capabilities' else '')
            if not session.ask(
                reason + 'Не удалось завершить загрузку, подтвердить наличие модели или сохранить настройки.\n'
                'Выбор не объявлен успешным. Можно повторить или продолжить без настройки ИИ.\n'
                'Если настройки менялись в другом окне, сначала проверь их в Фениксе.',
                'Подготовка модели не завершена', 'Повторить', 'Продолжить без ИИ'):
                return
            try:
                settings = bridge.read()
                if local_endpoint(settings['ollama_url']) != api.url:
                    return  # don't send requests to a newly changed endpoint
                installed = api.inventory()
            except SetupError:
                return
