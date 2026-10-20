"""Verified Python bootstrap download using Windows HTTPS (no third-party packages).

The frozen launcher's OpenSSL trust can differ from Windows trust in a fresh
Sandbox. Use Windows PowerShell's HTTPS stack, then require Authenticode Valid
and the Python Software Foundation signer. Never bypass certificate checks.
"""
import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PYTHON_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
PYTHON_FILE = "python-3.11.9-amd64.exe"
DOWNLOAD_TIMEOUT = 240
VERIFY_TIMEOUT = 60
_SUCCESS = "PHOENIX_PYTHON_VERIFIED"


class DownloadError(RuntimeError):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(kind)


# Values are passed in the child environment, never interpolated into commands.
# No profile, browser, shell=True, execution-policy override or TLS bypass.
_VERIFY = r"""
$phase = 'signature'
$sig = Get-AuthenticodeSignature -LiteralPath $env:PHOENIX_PYTHON_FILE
if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate) {
    throw 'Invalid Authenticode signature'
}
$signer = $sig.SignerCertificate.GetNameInfo(
    [System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
if ($signer -cne 'Python Software Foundation') {
    throw 'Unexpected installer signer'
}
Write-Output 'PHOENIX_PYTHON_VERIFIED'
"""
_DOWNLOAD = r"""
$phase = 'download'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $env:PHOENIX_PYTHON_URL -OutFile $env:PHOENIX_PYTHON_FILE `
    -UseBasicParsing -TimeoutSec 60 -MaximumRedirection 0
"""
_HEADER = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$phase = 'download'
try {
"""
_FOOTER = r"""
} catch {
    $kind = 'network'
    if ($phase -eq 'signature') {
        $kind = 'signature'
    } else {
        $cause = $_.Exception
        while ($null -ne $cause) {
            if ($cause -is [System.Net.WebException]) {
                if ($cause.Status -in @('TrustFailure', 'SecureChannelFailure')) {
                    $kind = 'certificate'
                } elseif ($cause.Status -in @('NameResolutionFailure', 'ProxyNameResolutionFailure')) {
                    $kind = 'dns'
                }
            }
            $cause = $cause.InnerException
        }
    }
    [Console]::Error.WriteLine('PHOENIX_FAILURE:' + $kind)
    exit 1
}
"""


def _powershell_path():
    if sys.platform != 'win32':
        raise DownloadError('unavailable')
    path = (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' /
            'WindowsPowerShell' / 'v1.0' / 'powershell.exe')
    if not path.is_file():
        raise DownloadError('unavailable')
    return path


def _run_windows(script, installer, url, timeout, logger):
    encoded = base64.b64encode((_HEADER + script + _FOOTER).encode('utf-16le')).decode('ascii')
    env = os.environ.copy()
    env['PHOENIX_PYTHON_FILE'] = str(installer.resolve())
    env['PHOENIX_PYTHON_URL'] = url
    try:
        result = subprocess.run(
            [str(_powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive',
             '-EncodedCommand', encoded],
            env=env, capture_output=True, timeout=timeout, creationflags=0x08000000,
        )
    except subprocess.TimeoutExpired as exc:
        raise DownloadError('timeout') from exc
    except OSError as exc:
        raise DownloadError('unavailable') from exc
    stdout = result.stdout.decode('utf-8', errors='replace').splitlines()
    stderr = result.stderr.decode('utf-8', errors='replace')
    if result.returncode != 0 or _SUCCESS not in stdout:
        kind = next((k for k in ('signature', 'certificate', 'dns', 'network')
                     if f'PHOENIX_FAILURE:{k}' in stderr), 'verification')
        logger.error('Python bootstrap: Windows helper failed (exit=%s, kind=%s)',
                     result.returncode, kind)
        raise DownloadError(kind)
    if not installer.is_file() or installer.stat().st_size == 0:
        raise DownloadError('verification')


def verify_python_installer(installer, logger):
    """Fail closed; verify again immediately before the installer is started."""
    _run_windows(_VERIFY, Path(installer), '', VERIFY_TIMEOUT, logger)


def cleanup_download(installer):
    """Remove only our known files in a private attempt directory, never recurse."""
    installer = Path(installer)
    if installer.name != PYTHON_FILE or not installer.parent.name.startswith('phoenix-python-'):
        return
    for name in (PYTHON_FILE, PYTHON_FILE + '.part.exe'):
        try:
            (installer.parent / name).unlink()
        except OSError:
            pass
    try:
        installer.parent.rmdir()
    except OSError:
        pass


def download_python(url, logger, reporthook):
    """Return a verified EXE in a private directory; never trust an old temp EXE."""
    if url != PYTHON_URL:
        raise DownloadError('url')
    folder = Path(tempfile.mkdtemp(prefix='phoenix-python-', dir=os.environ.get('TEMP') or None))
    installer = folder / PYTHON_FILE
    part = folder / (PYTHON_FILE + '.part.exe')
    try:
        reporthook(0, 1, -1)  # native downloader has no reliable byte progress here
        logger.info('Python bootstrap: Windows HTTPS; Authenticode verification required')
        _run_windows(_DOWNLOAD + _VERIFY, part, url, DOWNLOAD_TIMEOUT, logger)
        part.replace(installer)  # publish only after successful verification
        size = installer.stat().st_size
        reporthook(size, 1, size)
        logger.info('Python bootstrap: signature Valid, signer Python Software Foundation')
        return installer
    except Exception:
        cleanup_download(installer)
        raise
