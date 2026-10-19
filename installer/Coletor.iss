; Private per-user installation candidate. No services, admin rights or key creation.
; Opening at Windows sign-in is an installer option (checked by default): a Startup
; shortcut that opens beside the clock. Distribution only after the native CI gates.
#define AppName "Coletor de Frequência"
#include "..\dist\windows-portable\version.iss"

[Setup]
AppId={{D2471FE4-968A-4E83-AC4C-5A85CC8E651B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName=Coletor de Frequência {#AppVersion} (candidato)
AppPublisher=Ecossistema Escolar
UninstallDisplayName=Coletor de Frequência
UninstallDisplayIcon={app}\programa\app\assets\fox-icons\fox-idle.ico
DefaultDirName={localappdata}\Programs\ColetorFrequenciaSmecel
DefaultGroupName=Coletor de Frequência
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
MinVersion=10.0
OutputDir=..\dist\windows-installer
OutputBaseFilename=ColetorFrequencia-{#AppVersion}-windows-x64-setup-candidato
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\app\assets\fox-icons\fox-idle.ico
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
Name: "autostart"; Description: "Abrir o Coletor ao entrar no Windows (recomendado para a coleta automática)"
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[InstallDelete]
; Unchecking the option on a later installation removes the previous Startup shortcut.
Type: files; Name: "{userstartup}\Coletor de Frequência.lnk"; Tasks: not autostart

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LEIA-ME-INSTALADOR.txt"; DestDir: "{app}"; DestName: "INSTALACAO-E-RETIRADA.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Coletor de Frequência"; Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; IconFilename: "{app}\programa\app\assets\fox-icons\fox-idle.ico"; Comment: "Coletor de Frequência Escolar"; AppUserModelID: "EcossistemaEscolar.ColetorFrequenciaSmecel"
Name: "{autoprograms}\Retirar acesso deste PC"; Filename: "{app}\Remover acesso deste PC.cmd"; WorkingDir: "{app}"
Name: "{autoprograms}\Instruções de instalação e retirada"; Filename: "{app}\INSTALACAO-E-RETIRADA.txt"
Name: "{userstartup}\Coletor de Frequência"; Filename: "{app}\programa\ColetorFrequencia.exe"; Parameters: "--background"; WorkingDir: "{app}\programa"; IconFilename: "{app}\programa\app\assets\fox-icons\fox-idle.ico"; Comment: "Coletor de Frequência ao lado do relógio"; AppUserModelID: "EcossistemaEscolar.ColetorFrequenciaSmecel"; Tasks: autostart
Name: "{autodesktop}\Coletor de Frequência"; Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; IconFilename: "{app}\programa\app\assets\fox-icons\fox-idle.ico"; AppUserModelID: "EcossistemaEscolar.ColetorFrequenciaSmecel"; Tasks: desktopicon

[Run]
Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; Description: "Abrir Coletor de Frequência"; Flags: postinstall nowait skipifsilent unchecked

; The uninstaller does not claim or silently perform access revocation.
; Confirm the operator has reviewed pending receipts and the device binding.
[Code]
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if not UninstallSilent then
    Result := MsgBox(
      'Antes de remover, confira os lotes pendentes e use o atalho ' +
      '"Retirar acesso deste PC" no menu Iniciar para revogar o vínculo no Ecossistema.' + #13#10#13#10 +
      'Desinstalar não apaga chaves, filas cifradas ou configurações e não ' +
      'revoga automaticamente o computador. Você já concluiu essa conferência ' +
      'e deseja continuar?',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;
