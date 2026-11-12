# -*- coding: utf-8 -*-
"""Обновление Феникса с GitHub Releases: проверка, скачивание, помощник установки.

Сеть здесь только по явному действию или по галочке «Проверять обновления при
запуске» (config: update_check_enabled). Модуль не трогает GUI: он отдаёт
простые данные, а окно решает, что показать.

Установщик запускает отдельный помощник из %APPDATA%\\Phoenix\\updates, а не из
каталога программы: Nuitka-сборка заменяет все файлы в своём каталоге, и
помощник не должен от этого сломаться. Порядок: помощник ждёт выхода Феникса,
проверяет SHA-256 заново, ставит тихо поверх текущей версии, пишет результат и
запускает Феникс снова (установщик этого не делает — skipifsilent).

Что здесь НЕ доказывается: SHA-256 из того же релиза — защита от битого или
подменённого при скачивании файла, а не подпись автора. Оба установщика не
подписаны, UAC спрашивает про неизвестного издателя. Об этом честно сказано в
интерфейсе; успех установки подтверждается версией файла, а не только кодом
выхода.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from jarvis import __version__, paths

log = logging.getLogger(__name__)

REPO = "BobLoTiK/jarvis-fenix"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPO}/releases"
ALLOWED_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
ASSET_NAMES = {"light": "Feniks_Setup_{version}.exe",
               "standalone": "Feniks_Fast_Setup_{version}.exe"}
SUMS_NAME = "SHA256SUMS.txt"
APP_EXE = "Феникс.exe"
INSTALL_KINDS = ("light", "standalone", "source")
KIND_TITLES = {"light": "обычный установщик", "standalone": "автономный (Nuitka)",
               "source": "запуск из папки проекта"}
HELPER_NAME = "apply_update.ps1"
RESULT_NAME = "last_update.json"
LOG_NAME = "update.log"
SETUP_LOG_NAME = "setup.log"
TIMEOUT = 20.0
MAX_JSON = 2 * 1024 * 1024
MAX_SUMS = 64 * 1024
CHUNK = 256 * 1024
PROGRESS_STEP = 2 * 1024 * 1024
NOTES_LIMIT = 1500
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INSTALLER_RE = re.compile(r"^Feniks_(Fast_)?Setup_[0-9]+(\.[0-9]+){1,3}\.exe$")
# Окно помощника не показываем. Именно CREATE_NO_WINDOW, а не DETACHED_PROCESS:
# с DETACHED_PROCESS powershell.exe стартует и молча завершается, ничего не сделав
# (проверено на этой машине). Задания (job object), которое убило бы помощника
# вместе с Фениксом, ни лаунчер, ни установщик не создают.
CREATE_NO_WINDOW = 0x08000000


class UpdateError(Exception):
    """Ошибка обновления с понятным текстом; kind — для честного статуса."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message

    def __str__(self) -> str:  # никаких внутренних деталей в интерфейсе
        return self.message


def user_agent() -> str:
    return f"Phoenix/{__version__}"


# ---------------------------------------------------------------- версии

def parse_version(text) -> tuple | None:
    """'v2.1.3' -> (2, 1, 3); с суффиксом (-beta) -> None: их не предлагаем."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    if not value or "-" in value or "+" in value:
        return None
    parts = value.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    if not all(part.isdigit() and part.isascii() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(candidate, current) -> bool:
    """Сравнение по числовым частям; короткая версия добивается нулями."""
    first, second = tuple(candidate), tuple(current)
    size = max(len(first), len(second))
    return (first + (0,) * (size - len(first))) > (second + (0,) * (size - len(second)))


# ---------------------------------------------------------------- релиз

@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0
    digest: str = ""


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    page: str
    notes: str = ""
    assets: tuple = field(default=())

    def asset(self, name):
        for item in self.assets:
            if item.name == name:
                return item
        return None

    def installer(self, kind):
        template = ASSET_NAMES.get(kind)
        return self.asset(template.format(version=self.version)) if template else None

    def sums(self):
        return self.asset(SUMS_NAME)


@dataclass(frozen=True)
class CheckResult:
    status: str                 # update / current / error
    current: str
    release: "Release | None" = None
    error: str = ""


def _check_url(url) -> str:
    """Только https и только наши хосты: редирект в сторону не пускаем."""
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise UpdateError("unavailable", "Некорректная ссылка на обновление.")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise UpdateError("unavailable", "Некорректная ссылка на обновление.") from None
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)):
        raise UpdateError("unavailable", "Ссылка на обновление ведёт не на GitHub — не использую.")
    return url


class _SafeRedirect(HTTPRedirectHandler):
    """GitHub отдаёт ассеты с редиректом: проверяем каждый шаг."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return build_opener(_SafeRedirect())


def _error_kind(error) -> str:
    reason = getattr(error, "reason", error)
    text = str(reason).lower()
    if "certificate" in text or "ssl" in text:
        return "certificate"
    if "name or service" in text or "getaddrinfo" in text or "dns" in text:
        return "dns"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    return "network"


ERROR_TEXTS = {
    "network": "Нет связи с GitHub. Проверьте интернет и повторите.",
    "dns": "Не удалось найти api.github.com: проверьте интернет и DNS.",
    "certificate": "Проверка сертификата GitHub не прошла. Обновление не скачиваю.",
    "timeout": "GitHub не ответил вовремя. Повторите позже.",
    "unavailable": "Обновление сейчас недоступно.",
    "verification": "Файл обновления не прошёл проверку.",
    "cancelled": "Скачивание отменено.",
}


def _read_json(url) -> dict:
    _check_url(url)
    request = Request(url, headers={"Accept": "application/vnd.github+json",
                                    "User-Agent": user_agent()})
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            _check_url(response.geturl())
            raw = response.read(MAX_JSON + 1)
    except HTTPError as error:
        if error.code == 404:
            raise UpdateError("unavailable", "На GitHub пока нет ни одного релиза.") from None
        if error.code == 403:
            raise UpdateError("unavailable", "GitHub временно ограничил запросы. Повторите позже.") from None
        raise UpdateError(_error_kind(error), ERROR_TEXTS[_error_kind(error)]) from None
    except URLError as error:
        kind = _error_kind(error)
        raise UpdateError(kind, ERROR_TEXTS[kind]) from None
    except (OSError, ValueError):
        raise UpdateError("network", ERROR_TEXTS["network"]) from None
    if len(raw) > MAX_JSON:
        raise UpdateError("unavailable", "Ответ GitHub подозрительно большой.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise UpdateError("unavailable", "GitHub вернул не JSON.") from None
    if not isinstance(data, dict):
        raise UpdateError("unavailable", "GitHub вернул неожиданный ответ.")
    return data


def _clean_text(value, limit=NOTES_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = "".join(ch for ch in text if ch == "\n" or ord(ch) >= 32)
    return text[:limit]


def parse_release(data: dict) -> Release:
    """Строгая проверка ответа: имя, тег, страница и ассеты ожидаемой формы."""
    version = parse_version(data.get("tag_name"))
    if version is None:
        raise UpdateError("unavailable", "Последний релиз без простой версии (например, тестовая) — не предлагаю.")
    text = ".".join(str(part) for part in version)
    tag = data.get("tag_name") if isinstance(data.get("tag_name"), str) else "v" + text
    page = data.get("html_url")
    if not isinstance(page, str) or not page.startswith(f"https://github.com/{REPO}/releases"):
        page = f"{RELEASE_PAGE}/tag/{tag}"
    assets = []
    for item in data.get("assets") or ():
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("browser_download_url")
        if not isinstance(name, str) or name not in (
                ASSET_NAMES["light"].format(version=text),
                ASSET_NAMES["standalone"].format(version=text), SUMS_NAME):
            continue
        try:
            url = _check_url(url)
        except UpdateError:
            continue
        size = item.get("size")
        digest = ""
        raw_digest = item.get("digest")
        if isinstance(raw_digest, str):
            candidate = raw_digest.split(":", 1)[-1].strip().lower()
            digest = candidate if SHA256_RE.match(candidate) else ""
        assets.append(Asset(name=name, url=url,
                            size=size if isinstance(size, int) and size > 0 else 0,
                            digest=digest))
    return Release(version=text, tag=tag, page=page, notes=_clean_text(data.get("body")),
                   assets=tuple(assets))


def fetch_release(loader=None) -> Release:
    return parse_release((loader or _read_json)(API_URL))


def check(current=None, loader=None) -> CheckResult:
    """Проверка без исключений наружу: у любой ошибки есть честный текст."""
    current = current or __version__
    try:
        release = fetch_release(loader)
    except UpdateError as error:
        return CheckResult("error", current, None, str(error))
    except Exception:
        log.exception("Обновление: проверка упала")
        return CheckResult("error", current, None, ERROR_TEXTS["network"])
    now = parse_version(current)
    newer = parse_version(release.version)
    if now is None:
        return CheckResult("error", current, None, "Текущая версия записана необычно — обновление не предлагаю.")
    if newer is not None and is_newer(newer, now):
        return CheckResult("update", current, release)
    return CheckResult("current", current, release)


# ---------------------------------------------------------------- скачивание

def parse_sums(text: str) -> dict:
    """'<sha256>  <имя>' построчно -> {имя в нижнем регистре: sha256}."""
    result = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0].lower(), parts[-1].lstrip("*").strip()
        if SHA256_RE.match(digest) and name and "/" not in name and "\\" not in name:
            result[name.lower()] = digest
    return result


def fetch_sums(asset) -> dict:
    _check_url(asset.url)
    request = Request(asset.url, headers={"Accept": "application/octet-stream",
                                          "User-Agent": user_agent(),
                                          "Accept-Encoding": "identity"})
    try:
        with _opener().open(request, timeout=TIMEOUT) as response:
            _check_url(response.geturl())
            raw = response.read(MAX_SUMS + 1)
    except HTTPError as error:
        raise UpdateError(_error_kind(error), ERROR_TEXTS[_error_kind(error)]) from None
    except URLError as error:
        kind = _error_kind(error)
        raise UpdateError(kind, ERROR_TEXTS[kind]) from None
    except (OSError, ValueError):
        raise UpdateError("network", ERROR_TEXTS["network"]) from None
    if len(raw) > MAX_SUMS:
        raise UpdateError("verification", "Файл контрольных сумм подозрительно большой.")
    return parse_sums(raw.decode("utf-8", "replace"))


def sha256_file(path, cancel=None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise UpdateError("cancelled", ERROR_TEXTS["cancelled"])
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def download(asset: Asset, dest_dir=None, *, sums=None, progress=None, cancel=None) -> Path:
    """Скачать установщик во временный .part и переименовать только после SHA-256."""
    _check_url(asset.url)
    if not INSTALLER_RE.match(asset.name or ""):
        raise UpdateError("verification", "Неожиданное имя установщика — не скачиваю.")
    want = asset.digest or (sums or {}).get(asset.name.lower(), "")
    if not want:
        raise UpdateError("verification", "В релизе нет контрольной суммы — установщик не скачиваю.")
    expected = int(asset.size or 0)
    folder = Path(dest_dir or paths.updates_dir())
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise UpdateError("unavailable", "Не удалось создать папку обновления.") from None
    final = folder / asset.name
    part = folder / (asset.name + ".part")
    if expected:
        try:
            free = shutil.disk_usage(folder).free
        except OSError:
            free = 0
        if free and free < expected + 64 * 1024 * 1024:
            raise UpdateError("unavailable", "Мало места на диске для установщика.")
    request = Request(asset.url, headers={"Accept": "application/octet-stream",
                                          "User-Agent": user_agent(),
                                          "Accept-Encoding": "identity"})
    digest = hashlib.sha256()
    done = 0
    last = 0
    try:
        try:
            response = _opener().open(request, timeout=TIMEOUT)
        except HTTPError as error:
            raise UpdateError(_error_kind(error), ERROR_TEXTS[_error_kind(error)]) from None
        except URLError as error:
            kind = _error_kind(error)
            raise UpdateError(kind, ERROR_TEXTS[kind]) from None
        except (OSError, ValueError):
            raise UpdateError("network", ERROR_TEXTS["network"]) from None
        with response:
            _check_url(response.geturl())
            length = response.headers.get("Content-Length")
            total = expected
            if isinstance(length, str) and length.isdigit():
                total = total or int(length)
            if expected and length is not None and str(length).isdigit() and int(length) != expected:
                raise UpdateError("verification", "Размер установщика не совпал с релизом.")
            with open(part, "wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateError("cancelled", ERROR_TEXTS["cancelled"])
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if expected and done > expected:
                        raise UpdateError("verification", "Установщик больше заявленного размера.")
                    handle.write(chunk)
                    digest.update(chunk)
                    if progress is not None and done - last >= PROGRESS_STEP:
                        last = done
                        try:
                            progress(done, total or expected)
                        except Exception:
                            log.debug("Обновление: обработчик прогресса упал", exc_info=True)
            if progress is not None and done and done != last:
                try:
                    progress(done, total or expected or done)
                except Exception:
                    log.debug("Обновление: обработчик прогресса упал", exc_info=True)
        if expected and done != expected:
            raise UpdateError("verification", "Файл скачался не целиком — повторите.")
        actual = digest.hexdigest()
        if actual != want.lower():
            raise UpdateError("verification", "SHA-256 установщика не совпал — файл не запускаю.")
        os.replace(part, final)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise
    log.info("Обновление: установщик скачан (%s, %s байт)", final.name, done)
    return final


def cleanup_installers(dest_dir=None, keep=None) -> int:
    """Убрать прошлые установщики и недокачанные .part, чтобы не копить гигабайты."""
    folder = Path(dest_dir or paths.updates_dir())
    removed = 0
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    for item in entries:
        try:
            if not item.is_file():
                continue
            name = item.name
            if item == keep:
                continue
            if not (name.startswith("Feniks_Setup_") or name.startswith("Feniks_Fast_Setup_")
                    or name.endswith(".exe.part")):
                continue
            item.unlink()
            removed += 1
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------- установка

def install_root() -> Path:
    return Path(__file__).resolve().parent.parent


def install_kind(root=None) -> str:
    """light / standalone / source — по файлам, а не по догадкам о сборке.

    Обычная установка содержит launcher.py и исходники jarvis/*.py (или уже
    созданное окружение .venv311). Автономная Nuitka-сборка их не содержит по
    построению: build_nuitka_app.py падает, если в ней оказался launcher.py или
    .py из jarvis/. Каталог-исходник узнаём по .git.
    """
    root = Path(root or install_root())
    if (root / ".git").exists():
        return "source"
    if ((root / "launcher.py").is_file() or (root / "jarvis" / "__init__.py").is_file()
            or (root / ".venv311").is_dir()):
        return "light"
    if (root / APP_EXE).is_file():
        return "standalone"
    return "source"


def _powershell() -> str:
    system = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = Path(system) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else "powershell.exe"


HELPER_SCRIPT = r"""# Феникс — помощник обновления. Запускается из %APPDATA%\Phoenix\updates,
# ждёт выхода приложения, ставит установщик тихо и возвращает Феникс.
# Все значения приходят переменными окружения PHOENIX_UPDATE_*: в скрипте нет
# пользовательских путей, поэтому кириллица не ломается.
$ErrorActionPreference = 'Stop'

function Write-Log([string]$Message) {
    try {
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        Add-Content -LiteralPath $env:PHOENIX_UPDATE_LOG -Value "$stamp $Message" -Encoding UTF8
    } catch { }
}

function Save-Result([string]$Status, [int]$Code, [string]$Version, [string]$Message) {
    try {
        $data = [ordered]@{
            status = $Status
            exit_code = $Code
            version = $Version
            message = $Message
            at = (Get-Date).ToString('o')
        }
        Set-Content -LiteralPath $env:PHOENIX_UPDATE_RESULT -Encoding UTF8 -Value ($data | ConvertTo-Json -Compress)
    } catch { }
}

function Show-Problem([string]$Text) {
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        [System.Windows.Forms.MessageBox]::Show($Text, 'Феникс - обновление', 'OK', 'Warning') | Out-Null
    } catch { }
}

function Wait-OldProcess([int]$Id2, [int]$Seconds) {
    if ($Id2 -le 0) { return $true }
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $Id2 -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Wait-Mutex([string]$Name, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $owned = $false
        try {
            $mutex = New-Object System.Threading.Mutex($false, $Name)
            try { $owned = $mutex.WaitOne(0) } finally {
                if ($owned) { $mutex.ReleaseMutex() }
                $mutex.Dispose()
            }
        } catch { $owned = $false }
        if ($owned) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

$installer = $env:PHOENIX_UPDATE_INSTALLER
$root = $env:PHOENIX_UPDATE_ROOT
$exe = $env:PHOENIX_UPDATE_EXE
$target = $env:PHOENIX_UPDATE_VERSION
$want = $env:PHOENIX_UPDATE_SHA
$oldPid = 0
[int]::TryParse($env:PHOENIX_UPDATE_PID, [ref]$oldPid) | Out-Null
$elevate = ($env:PHOENIX_UPDATE_ELEVATE -eq '1')

Write-Log "старт: версия $target, повышение прав $elevate, установщик $installer"

function Restart-Phoenix {
    try {
        if (Test-Path -LiteralPath $exe) {
            Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) | Out-Null
            Write-Log 'Феникс запущен снова'
        } else {
            Write-Log 'Файл Феникс.exe не найден - запустить нечего'
        }
    } catch {
        Write-Log "не удалось запустить Феникс: $($_.Exception.Message)"
    }
}

try {
    if (-not (Test-Path -LiteralPath $installer)) {
        throw [System.IO.FileNotFoundException]::new('Установщик исчез из папки обновления.')
    }
    if (-not (Wait-OldProcess $oldPid 180)) {
        Save-Result 'failed' -1 $target 'Феникс не завершился за три минуты - установщик не запускал.'
        Write-Log 'Феникс не завершился, выход'
        Show-Problem 'Феникс не завершился за три минуты. Обновление не установлено, закройте его и повторите.'
        exit 1
    }
    Write-Log 'Феникс завершился'

    if (-not (Wait-Mutex 'Local\JarvisPhoenixSingleInstance' 90)) {
        Save-Result 'failed' -1 $target 'Приложение всё ещё занято - установщик не запускал.'
        Write-Log 'мьютекс приложения занят, выход'
        Show-Problem 'Феникс всё ещё занят. Обновление не установлено, закройте его и повторите.'
        exit 1
    }
    if (-not (Wait-Mutex 'Local\JarvisPhoenixLauncherSetup' 60)) {
        Save-Result 'failed' -1 $target 'Установщик уже работает - второй раз не запускал.'
        Write-Log 'мьютекс установщика занят, выход'
        exit 1
    }

    $actual = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLower()
    if ($want -and ($actual -ne $want.ToLower())) {
        Save-Result 'failed' -1 $target 'SHA-256 установщика не совпал перед запуском - файл не запускал.'
        Write-Log 'SHA-256 не совпал перед запуском, выход'
        # Сначала возвращаем приложение, потом показываем окно с ошибкой: иначе
        # модальное окно держит пользователя без Феникса до нажатия «OK».
        Restart-Phoenix
        Show-Problem 'Файл обновления изменился после проверки. Установка отменена, повторите скачивание.'
        exit 1
    }
    Write-Log 'SHA-256 подтверждён перед запуском'

    # Start-Process -ArgumentList склеивает массив пробелами и кавычек вокруг
    # значений не ставит, поэтому путь с пробелом рвался на два аргумента и
    # установщик ставил копию в мусорный каталог (проверено живьём:
    # "C:\...\Temp\phx e2e b" -> создавался "...\Temp\phx"). Строку команды
    # собираем сами и передаём одним аргументом: /DIR="путь с пробелом".
    $setupLog = $env:PHOENIX_UPDATE_SETUP_LOG
    $argumentLine = '/VERYSILENT /SUPPRESSMSGBOXES /NOCANCEL /CLOSEAPPLICATIONS ' +
                    '/NORESTART /SP- /DIR="' + $root + '" /LOG="' + $setupLog + '"'
    $process = $null
    if ($elevate) {
        $process = Start-Process -FilePath $installer -ArgumentList $argumentLine -Verb RunAs -PassThru -Wait
    } else {
        $process = Start-Process -FilePath $installer -ArgumentList $argumentLine -PassThru -Wait
    }
    $code = -1
    try { $code = [int]$process.ExitCode } catch { $code = -1 }
    Write-Log "установщик завершён с кодом $code"

    $installed = ''
    try { $installed = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion } catch { $installed = '' }
    Write-Log "версия файла после установки: $installed"

    if ($installed -and $installed.StartsWith($target)) {
        Save-Result 'ok' $code $installed 'Обновление установлено.'
        Write-Log 'успех'
    } elseif (-not $installed -and $code -eq 0) {
        Save-Result 'ok' $code $target 'Установщик завершён с кодом 0, версия файла не читается.'
        Write-Log 'успех по коду выхода'
    } else {
        Save-Result 'failed' $code $installed "Установщик вернул $code, версия файла '$installed'."
        Write-Log 'неудача'
        Restart-Phoenix
        Show-Problem "Обновление не установлено (код $code). Феникс запущен как был. Подробности: $env:PHOENIX_UPDATE_SETUP_LOG"
        exit 1
    }
    # Дальше только успех: установщик (14 МБ лёгкой сборки или 310 МБ
    # автономной) больше не нужен и не должен копиться в папке обновления.
    try {
        Remove-Item -LiteralPath $installer -Force -ErrorAction Stop
        Write-Log 'установщик удалён после успешной установки'
    } catch {
        Write-Log "установщик удалить не удалось: $($_.Exception.Message)"
    }
    Restart-Phoenix
    exit 0
} catch {
    Save-Result 'failed' -1 $target "Помощник обновления упал: $($_.Exception.Message)"
    Write-Log "ошибка помощника: $($_.Exception.Message)"
    Restart-Phoenix
    Show-Problem "Обновление не установлено. Феникс запущен как был. Подробности: $env:PHOENIX_UPDATE_LOG"
    exit 1
}
"""


def helper_path(folder=None) -> Path:
    return Path(folder or paths.updates_dir()) / HELPER_NAME


def write_helper(folder=None) -> Path:
    """Скрипт пишем UTF-8 с BOM: иначе PowerShell 5.1 спотыкается на кириллице."""
    target = helper_path(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="\r\n") as handle:
        handle.write(HELPER_SCRIPT)
    return target


def spawn_installer(installer, version, *, kind=None, root=None, pid=None, folder=None) -> subprocess.Popen:
    """Запустить помощника и вернуть процесс. Дальше приложение обязано выйти."""
    if os.name != "nt":
        raise UpdateError("unavailable", "Обновление на месте ставится только в Windows.")
    installer = Path(installer)
    if not installer.is_file() or installer.suffix.lower() != ".exe":
        raise UpdateError("verification", "Установщик не найден — скачайте заново.")
    target_root = Path(root or install_root())
    exe = target_root / APP_EXE
    if not exe.is_file():
        raise UpdateError("unavailable",
                          "Не нашёл Феникс.exe: обновление ставится только у установленной копии.")
    kind = kind or install_kind(target_root)
    if kind not in INSTALL_KINDS:
        raise UpdateError("unavailable", "Неизвестный тип установки.")
    folder = Path(folder or paths.updates_dir())
    try:
        digest = sha256_file(installer)
    except (OSError, UpdateError) as error:
        raise UpdateError("verification", f"Не удалось перечитать установщик: {error}") from None
    helper = write_helper(folder)
    result = folder / RESULT_NAME
    try:
        result.unlink()
    except OSError:
        pass
    env = os.environ.copy()
    env.update({
        "PHOENIX_UPDATE_INSTALLER": str(installer),
        "PHOENIX_UPDATE_ROOT": str(target_root),
        "PHOENIX_UPDATE_EXE": str(exe),
        "PHOENIX_UPDATE_VERSION": str(version),
        "PHOENIX_UPDATE_SHA": digest,
        "PHOENIX_UPDATE_PID": str(pid if pid is not None else os.getpid()),
        "PHOENIX_UPDATE_ELEVATE": "1" if kind == "standalone" else "0",
        "PHOENIX_UPDATE_RESULT": str(result),
        "PHOENIX_UPDATE_LOG": str(folder / LOG_NAME),
        "PHOENIX_UPDATE_SETUP_LOG": str(folder / SETUP_LOG_NAME),
    })
    command = [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(helper)]
    try:
        process = subprocess.Popen(command, cwd=str(folder), env=env, close_fds=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=CREATE_NO_WINDOW)
    except OSError:
        log.exception("Обновление: не удалось запустить помощника")
        raise UpdateError("unavailable", "Не удалось запустить помощника обновления.") from None
    log.info("Обновление: помощник запущен (pid %s), версия %s, тип %s", process.pid, version, kind)
    return process


def read_last_result(folder=None):
    """Результат прошлой установки для честного тоста при следующем старте."""
    path = Path(folder or paths.updates_dir()) / RESULT_NAME
    if not path.is_file():
        return None
    data = None
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = None
    try:
        path.unlink()
    except OSError:
        pass
    if not isinstance(data, dict) or data.get("status") not in ("ok", "failed"):
        return None
    code = data.get("exit_code")
    return {"status": data["status"],
            "version": data.get("version") if isinstance(data.get("version"), str) else "",
            "exit_code": code if isinstance(code, int) else None,
            "message": data.get("message") if isinstance(data.get("message"), str) else ""}


def describe(result: CheckResult) -> str:
    """Короткий статус для карточки настроек."""
    if result.status == "update" and result.release is not None:
        return f"Есть новая версия {result.release.version} (у вас {result.current})."
    if result.status == "current":
        return f"Установлена последняя версия: {result.current}."
    return result.error or "Проверка не удалась."
