"""Consented Microsoft VC++ x64 prerequisite; no silent installs or TLS bypass."""
import base64
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from launcher_download import _powershell_path

VC_URL = 'https://aka.ms/vc14/vc_redist.x64.exe'
VC_FILE = 'vc_redist.x64.exe'
VC_DLLS = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
MARKER = 'PHOENIX_VC_VERIFIED'


class RuntimePreparationError(RuntimeError):
    pass


def runtime_present():
    """Probe x64 system DLLs, not PyInstaller's private bundled runtime."""
    if sys.platform != 'win32':
        raise RuntimePreparationError('VC++ check requires Windows')
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    try:
        libraries = [ctypes.WinDLL(str(system / name)) for name in VC_DLLS]
        return len(libraries) == len(VC_DLLS)
    except OSError:
        return False


VERIFY = r"""
$sig = Get-AuthenticodeSignature -LiteralPath $env:PHOENIX_VC_FILE
if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate) {
    throw 'Invalid Microsoft installer signature'
}
$name = $sig.SignerCertificate.GetNameInfo(
    [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
if ($name -cne 'Microsoft Corporation') { throw 'Unexpected signer' }
Write-Output 'PHOENIX_VC_VERIFIED'
"""
DOWNLOAD = r"""
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $env:PHOENIX_VC_URL -OutFile $env:PHOENIX_VC_FILE `
    -UseBasicParsing -TimeoutSec 60 -MaximumRedirection 5
"""


def _verified(script, path, timeout):
    body = "$ErrorActionPreference='Stop'\n$ProgressPreference='SilentlyContinue'\n" + script
    env = os.environ.copy()
    env.update(PHOENIX_VC_FILE=str(Path(path).resolve()), PHOENIX_VC_URL=VC_URL)
    try:
        result = subprocess.run(
            [str(_powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive',
             '-EncodedCommand', base64.b64encode(body.encode('utf-16le')).decode('ascii')],
            capture_output=True, env=env, timeout=timeout, creationflags=0x08000000,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimePreparationError('Microsoft download/signature check failed') from exc
    if (result.returncode != 0 or MARKER not in result.stdout.decode('utf-8', errors='replace').splitlines()
            or not Path(path).is_file() or Path(path).stat().st_size == 0):
        raise RuntimePreparationError('Microsoft installer is not verified')


def ensure_vc_runtime(session, logger, *, opener=None):
    """Download only on consent; launch verified native UI and recheck readiness."""
    if runtime_present():
        logger.info('VC++ Runtime x64: системные DLL доступны')
        return True
    if session is None:
        raise RuntimePreparationError('Открой Феникс через окно подготовки для установки VC++ x64.')
    if not session.ask(
        'Для голосовых компонентов нужен Microsoft Visual C++ Runtime x64.\n'
        'Необходимые системные DLL не удалось загрузить.\n\n'
        'Скачать официальный установщик Microsoft и открыть его? '
        'Установка и разрешение Windows потребуют твоего подтверждения.',
        'Феникс — компонент Windows', 'Скачать и открыть', 'Не устанавливать'):
        logger.info('Установка VC++ отклонена; запуск остановлен без изменений')
        session.declined = True
        return False
    folder = Path(tempfile.mkdtemp(prefix='phoenix-vc-', dir=os.environ.get('TEMP') or None))
    exe, part = folder / VC_FILE, folder / 'vc_redist.x64.part.exe'
    try:
        session.stage('Готовим компонент Windows',
                      'Скачиваем VC++ x64 с сайта Microsoft и проверяем цифровую подпись.', show=True)
        _verified(DOWNLOAD + VERIFY, part, 240)
        part.replace(exe)
        _verified(VERIFY, exe, 60)  # verify again immediately before execution
        logger.info('VC++ Runtime: подпись Valid, Microsoft Corporation; открываю установщик')
        (opener or os.startfile)(str(exe))
        while session.ask(
            'Заверши установку Microsoft Visual C++ Runtime в отдельном окне.\n'
            'Затем нажми «Проверить». Если Windows требует перезагрузку, '
            'сохрани логи; закрытие Sandbox удаляет её данные.\n\n'
            'Готовность проверяется загрузкой системных DLL, а не фактом открытия установщика.',
            'Феникс — проверка компонента Windows', 'Проверить', 'Завершить подготовку'):
            if runtime_present():
                logger.info('VC++ Runtime x64: проверка после установки пройдена')
                return True
            session.detail('Системные DLL пока недоступны. Заверши установку; возможно, Windows требует перезапуск.')
        session.declined = True
        return False
    finally:
        # Only our known files; a running installer may keep its file locked.
        for path in (part, exe):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass
