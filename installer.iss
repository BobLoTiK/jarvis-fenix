; Inno Setup скрипт для Феникса.
;
; Собирает установщик Феникс_Setup.exe:
;   - Копирует всю папку проекта в Program Files\Феникс
;   - Создаёт ярлык в меню Пуск
;   - Создаёт ярлык на рабочем столе (опционально)
;   - Добавляет в автозапуск (опционально)
;
; Сборка:
;   1. Установи Inno Setup: https://jrsoftware.org/isdl.php
;   2. Открой installer.iss в Inno Setup Compiler
;   3. Нажми Build → Build
;
; Результат: dist\Феникс_Setup.exe

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
LicenseFile=README.md
OutputDir=dist
OutputBaseFilename=Феникс_Setup
SetupIconFile=jarvis\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_small.bmp
WizardImageStretch=yes
WizardImageBackColor=$00160E0A
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: checkedonce
Name: "autostart"; Description: "Запускать Феникс при старте Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
; Главный exe
Source: "Феникс.exe"; DestDir: "{app}"; Flags: ignoreversion
; Пакет jarvis
Source: "jarvis\*"; DestDir: "{app}\jarvis"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Паки
Source: "packs\*"; DestDir: "{app}\packs"; Flags: ignoreversion recursesubdirs createallsubdirs
; Скрипты
Source: "scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
; Конфиг-пример
Source: "config.example.json"; DestDir: "{app}"; Flags: ignoreversion
; Зависимости
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Документация
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "ARCHITECTURE.md"; DestDir: "{app}"; Flags: ignoreversion

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