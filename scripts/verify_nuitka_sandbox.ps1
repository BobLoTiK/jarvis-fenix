# Runs INSIDE Windows Sandbox. Input mapping is read-only; only reports are writable.
$ErrorActionPreference = 'Stop'
$inputDir = 'C:\PhoenixTest\input'
$outDir = 'C:\PhoenixTest\results'
$appDir = 'C:\PhoenixStandaloneTest\App'
# Keep this file pure ASCII: Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI,
# so any non-ASCII literal here becomes mojibake and silently breaks the check.
# The application executable is therefore discovered, not hardcoded by name.
$summary = [ordered]@{
    schema = 1
    ok = $false
    scope = 'offline_install_native_imports_flet_uninstall'
    host_python_absent = $false
    installer_ok = $false
    manifest_ok = $false
    native_probe_ok = $false
    flet_gui_ok = $false
    uninstall_ok = $false
    user_data_preserved = $false
    not_tested = @('microphone', 'physical_audio', 'voice_models', 'Ollama', 'GPU_inference', 'assistant_workflow')
}

function Run-Checked([string]$File, [string[]]$Arguments, [int]$TimeoutSeconds) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru
    $null = $process.Handle # retain a valid handle for ExitCode after process exit
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        throw "Timed out after $TimeoutSeconds seconds: $File"
    }
    $process.Refresh()
    if ($process.ExitCode -ne 0) {
        throw "ExitCode=$($process.ExitCode): $File"
    }
}

try {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    Start-Transcript -Path (Join-Path $outDir 'sandbox.log') -Force | Out-Null
    $expected = Get-Content -Raw -Encoding UTF8 (Join-Path $inputDir 'expected.json') | ConvertFrom-Json
    $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $inputDir 'setup.exe')).Hash.ToLowerInvariant()
    if ($actual -ne $expected.sha256) { throw 'Installer SHA256 mismatch' }
    $python = @(Get-Command python.exe, pythonw.exe, py.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' })
    if ($python.Count -ne 0) { throw 'This environment contains external Python; it is not the required clean test' }
    $summary.host_python_absent = $true

    Run-Checked (Join-Path $inputDir 'setup.exe') @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
        "/DIR=$appDir", "/LOG=$outDir\install.log"
    ) 600
    $exe = @(Get-ChildItem -LiteralPath $appDir -File -Filter '*.exe' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike 'unins*' } |
        Sort-Object -Property Name |
        Select-Object -First 1).FullName
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { throw 'Application executable was not installed' }
    $summary.installer_ok = $true
    $info = Get-Content -Raw -Encoding UTF8 (Join-Path $appDir 'build-info.json') | ConvertFrom-Json
    if ($info.kind -ne 'nuitka-application-standalone' -or $info.external_python_required -ne $false) {
        throw 'Not a full standalone application payload'
    }
    $interpreters = @(Get-ChildItem -LiteralPath $appDir -File -Recurse |
        Where-Object { $_.Name -match '^pythonw?\.exe$' })
    if ($interpreters.Count -ne 0 -or (Test-Path (Join-Path $appDir '.venv311'))) {
        throw 'Unexpected external interpreter or development environment'
    }
    $manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $appDir 'release-manifest.json') | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        if ($entry.path -match '(^[/\\]|(^|[/\\])\.\.([/\\]|$)|:)') { throw 'Unsafe manifest path' }
        $file = Join-Path $appDir $entry.path
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant()
        if ($hash -ne $entry.sha256) { throw "Payload SHA256 mismatch: $($entry.path)" }
    }
    $summary.manifest_ok = $true

    $nativeReport = Join-Path $outDir 'native-probe.json'
    Run-Checked $exe @('--self-test', $nativeReport) 300
    $native = Get-Content -Raw -Encoding UTF8 $nativeReport | ConvertFrom-Json
    if ($native.ok -ne $true -or $native.compiled -ne $true) { throw 'Compiled native probe failed' }
    $summary.native_probe_ok = $true

    $guiReport = Join-Path $outDir 'flet-gui.json'
    Run-Checked $exe @('--gui-smoke', $guiReport) 120
    $gui = Get-Content -Raw -Encoding UTF8 $guiReport | ConvertFrom-Json
    if ($gui.ok -ne $true -or $gui.session_opened -ne $true -or $gui.window_close_awaited -ne $true) {
        throw 'Packaged Flet GUI startup/close failed'
    }
    $summary.flet_gui_ok = $true

    $userDir = Join-Path $env:APPDATA 'Phoenix'
    New-Item -ItemType Directory -Path $userDir -Force | Out-Null
    $sentinel = Join-Path $userDir 'sandbox-preserve-marker.txt'
    Set-Content -LiteralPath $sentinel -Value 'keep-user-data' -Encoding UTF8
    $before = (Get-FileHash -Algorithm SHA256 -LiteralPath $sentinel).Hash
    $uninstaller = Join-Path $appDir 'unins000.exe'
    Run-Checked $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$outDir\uninstall.log") 180
    for ($i = 0; $i -lt 30 -and (Test-Path -LiteralPath $exe); $i++) { Start-Sleep -Seconds 1 }
    if (Test-Path -LiteralPath $exe) { throw 'Uninstaller left the main application executable' }
    $summary.uninstall_ok = $true
    $summary.user_data_preserved = (Test-Path -LiteralPath $sentinel) -and (
        (Get-FileHash -Algorithm SHA256 -LiteralPath $sentinel).Hash -eq $before)
    if (-not $summary.user_data_preserved) { throw 'Uninstall modified user data' }
    $summary.ok = $true
    Write-Host 'PASS: offline installation, bundled native imports, packaged Flet GUI, uninstall and preservation.' -ForegroundColor Green
    Write-Host 'Microphone, actual speech, model downloads and Ollama were NOT tested.'
} catch {
    $summary.error = $_.Exception.Message
    Write-Host "FAIL: $($summary.error)" -ForegroundColor Red
} finally {
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $outDir 'summary.json') -Encoding UTF8
    try { Stop-Transcript | Out-Null } catch {}
}
Write-Host "Reports: $outDir (also visible in the mapped host results folder)."
Write-Host 'Keep this window open to inspect failures; close Windows Sandbox when finished.'
Read-Host 'Press Enter to finish'
