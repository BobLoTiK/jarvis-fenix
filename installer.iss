; Inno Setup скрипт для Феникса.
;
; Собирает установщик Феникс_Setup.exe:
;   - Копирует сборку в C:\ProgramData\Phoenix (ASCII-путь из paths.py)
;   - Создаёт ярлык в меню Пуск
;   - Создаёт ярлык на рабочем столе (опционально)
;   - Добавляет в автозапуск (опционально)
;
; Почему ProgramData: Vosk (C++/Kaldi) падает на не-ASCII путях,
; а PROGRAM_DIR из jarvis/paths.py должен быть без кириллицы.
;
; Сборка (автоматически — из корня проекта):
;   python scripts\build_setup.py
;
; Сборка (вручную):
;   1. Установи Inno Setup: https://jrsoftware.org/isdl.php
;   2. python scripts\build_setup.py (подготовить launcher и чистый payload)
;   3. Открой installer.iss в Inno Setup Compiler
;   4. Нажми Build → Build
;
; Результат: dist\Феникс_Setup.exe
;
; Обновление поверх старой версии: .venv311, models\ и данные в
; %APPDATA%\Phoenix НЕ трогаются — Inno только перезаписывает код.

#define MyAppName "Феникс"
; Версия по умолчанию. Переопределяется снаружи:
;   ISCC.exe /DMyAppVersion=1.0.2 installer.iss
; (CI передаёт версию из тега: scripts\build_setup.py --version 1.0.2)
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "Phoenix Project"
#define MyAppURL "https://github.com/BobLoTiK/jarvis-fenix"
#define MyAppExeName "Феникс.exe"
; Only scripts/build_setup.py publishes this curated directory.
#ifndef PayloadDir
  #define PayloadDir "build\release-payload"
#endif

[Setup]
AppId={{8E4B3F2A-1A2B-4C5D-9E8F-7A6B5C4D3E2F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={commonappdata}\Phoenix
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=Феникс_Setup
SetupIconFile=jarvis\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_small.bmp
WizardImageStretch=yes
WizardImageBackColor=$001C1212
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Мьютексы ядра И setup-лаунчера — Inno попросит закрыть
; запущенного Феникса перед перезаписью файлов.
AppMutex=Local\JarvisPhoenixSingleInstance,Local\JarvisPhoenixLauncherSetup
; При обновлении поверх работающего Феникса — не требовать перезагрузки
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "autostart"; Description: "Запускать Феникс при старте Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Dirs]
; models\ — сюда лаунчер качает Vosk-модель (~45 МБ) при первом запуске
Name: "{app}\models"
; runtime\ — ASCII-фоллбэк из paths.py (PROGRAM_DIR)
Name: "{app}\runtime"

[Files]
; Prepared and validated by scripts/release_payload.py. No developer config,
; profiles, caches, venv, models or machine-specific system_caps.json.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
; Ярлык в меню Пуск
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
; Ярлык на рабочем столе (если выбран)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Запустить после установки
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
; Автозапуск (если выбран)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart