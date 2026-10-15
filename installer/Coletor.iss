; Private per-user installation candidate. No services, autostart, admin rights or
; key creation. Distribution only after synthetic and native Windows CI gates.
#define AppName "Coletor de Frequência"
#define AppVersion "0.4.0"
#define BundleRoot "..\dist\windows-portable\ColetorFrequencia-0.4.0-teste-windows-x64"

[Setup]
AppId={{D2471FE4-968A-4E83-AC4C-5A85CC8E651B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName=Coletor de Frequência 0.4.0 (candidato)
AppPublisher=Ecossistema Escolar
UninstallDisplayName=Coletor de Frequência
UninstallDisplayIcon={app}\programa\pythonw.exe
DefaultDirName={localappdata}\Programs\ColetorFrequenciaSmecel
DefaultGroupName=Coletor de Frequência
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
MinVersion=10.0
OutputDir=..\dist\windows-installer
OutputBaseFilename=ColetorFrequencia-0.4.0-windows-x64-setup-candidato
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
ChangesEnvironment=no
DisableReadyPage=no
DisableDirPage=auto
UsePreviousAppDir=yes
SetupLogging=no
UninstallLogMode=append

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Coletor de Frequência"; Filename: "{app}\programa\pythonw.exe"; Parameters: "-B -m coletor.portable"; WorkingDir: "{app}\programa"; Comment: "Coletor de Frequência Escolar"
Name: "{autoprograms}\Retirar acesso deste PC"; Filename: "{app}\Remover acesso deste PC.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\Coletor de Frequência"; Filename: "{app}\programa\pythonw.exe"; Parameters: "-B -m coletor.portable"; WorkingDir: "{app}\programa"; Tasks: desktopicon

[Run]
Filename: "{app}\programa\pythonw.exe"; Parameters: "-B -m coletor.portable"; WorkingDir: "{app}\programa"; Description: "Abrir Coletor de Frequência"; Flags: postinstall nowait skipifsilent unchecked

; Inno removes application binaries and shortcuts only. It intentionally does
; NOT delete per-user DPAPI, device keys, queue or account binding: before
; uninstall, the operator must explicitly run "Retirar acesso deste PC".
; Silent uninstall must likewise be preceded by authorized revocation.
