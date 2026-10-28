; Full compiled application. No Python installer, pip, venv or launcher.py.
#define MyAppName "Феникс"
#ifndef MyAppVersion
  #define MyAppVersion "2.1.2"
#endif
#ifndef PayloadDir
  #define PayloadDir "dist\nuitka-app"
#endif
#define MyAppExeName "Феникс.exe"

[Setup]
AppId={{8E4B3F2A-1A2B-4C5D-9E8F-7A6B5C4D3E2F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Phoenix Project
AppPublisherURL=https://github.com/BobLoTiK/jarvis-fenix
DefaultDirName={autopf}\Phoenix
UsePreviousAppDir=no
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename=Феникс_Nuitka_Setup
SetupIconFile=jarvis\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer_banner.bmp
WizardSmallImageFile=installer_small.bmp
WizardImageStretch=yes
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=Local\JarvisPhoenixSingleInstance,Local\JarvisPhoenixLauncherSetup
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: checkedonce
Name: "autostart"; Description: "Запускать Феникс при старте Windows"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Подготовить Silero"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--prepare-silero"; WorkingDir: "{app}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart
