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
;   2. python scripts\build_exe.py   (сначала обновить Феникс.exe)
;   3. Открой installer.iss в Inno Setup Compiler
;   4. Нажми Build → Build
;
; Результат: dist\Феникс_Setup.exe
;
; Обновление поверх старой версии: .venv311, models\ и данные в
; %APPDATA%\Phoenix НЕ трогаются — Inno только перезаписывает код.

#define MyAppName "Феникс"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Phoenix Project"
#define MyAppURL "https://github.com/BobLoTiK/jarvis-fenix"
#define MyAppExeName "Феникс.exe"

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
WizardImageBackColor=$00160E0A
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
; Тот же мьютекс, что в launcher.py — Inno попросит закрыть
; запущенного Феникса перед перезаписью файлов.
AppMutex=Local\JarvisPhoenixSingleInstance
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
; Главный exe
Source: "Феникс.exe"; DestDir: "{app}"; Flags: ignoreversion
; Пакет jarvis (без createallsubdirs — иначе пустые __pycache__ создаются)
Source: "jarvis\*"; DestDir: "{app}\jarvis"; Flags: ignoreversion recursesubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
; Паки
Source: "packs\*"; DestDir: "{app}\packs"; Flags: ignoreversion recursesubdirs
; Скрипты
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
; Конфиг-пример
Source: "config.example.json"; DestDir: "{app}"; Flags: ignoreversion
; Зависимости
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Возможности системы (генерируется scripts\check_caps.py;
; читается actions.py и gui.py — не критичен, поэтому skipifsourcedoesntexist)
Source: "system_caps.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Документация
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "ARCHITECTURE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

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