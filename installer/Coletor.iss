; Private per-user installation candidate. No services, admin rights or key creation.
; Opening at Windows sign-in is an installer option (checked by default): a per-user
; logon task (like the Atualizador's) that opens beside the clock. Startup-folder
; shortcuts wait behind every Run entry and were missed. Distribution only after the native CI gates.
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
; The logon task replaces the old Startup-folder shortcut.
Type: files; Name: "{userstartup}\Coletor de Frequência.lnk"

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LEIA-ME-INSTALADOR.txt"; DestDir: "{app}"; DestName: "INSTALACAO-E-RETIRADA.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Coletor de Frequência"; Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; IconFilename: "{app}\programa\app\assets\fox-icons\fox-idle.ico"; Comment: "Coletor de Frequência Escolar"; AppUserModelID: "EcossistemaEscolar.ColetorFrequenciaSmecel"
Name: "{autoprograms}\Retirar acesso deste PC"; Filename: "{app}\Remover acesso deste PC.cmd"; WorkingDir: "{app}"
Name: "{autoprograms}\Instruções de instalação e retirada"; Filename: "{app}\INSTALACAO-E-RETIRADA.txt"
Name: "{autodesktop}\Coletor de Frequência"; Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; IconFilename: "{app}\programa\app\assets\fox-icons\fox-idle.ico"; AppUserModelID: "EcossistemaEscolar.ColetorFrequenciaSmecel"; Tasks: desktopicon

[Run]
Filename: "{app}\programa\ColetorFrequencia.exe"; WorkingDir: "{app}\programa"; Description: "Abrir Coletor de Frequência"; Flags: postinstall nowait skipifsilent unchecked

; The uninstaller does not claim or silently perform access revocation.
; Confirm the operator has reviewed pending receipts and the device binding.
[Code]
const
  LogonTask = '\EcossistemaEscolar\ColetorFrequencia';

function XmlText(Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '&', '&amp;', True);
  StringChangeEx(Result, '<', '&lt;', True);
  StringChangeEx(Result, '>', '&gt;', True);
end;

procedure DeleteLogonTask();
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Delete /TN "' + LogonTask + '" /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure RegisterLogonTask();
var
  Lines: TArrayOfString;
  Path, User, Folder: String;
  Code: Integer;
begin
  User := GetEnv('USERDOMAIN') + '\' + GetUserNameString();
  Folder := ExpandConstant('{app}\programa');
  Path := ExpandConstant('{tmp}\coletor-logon-task.xml');
  SetArrayLength(Lines, 1);
  Lines[0] :=
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' +
    '<RegistrationInfo><Description>Abre o Coletor de Frequência ao lado do relógio ao entrar no Windows.</Description></RegistrationInfo>' +
    '<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>' + XmlText(User) + '</UserId><Delay>PT30S</Delay></LogonTrigger></Triggers>' +
    '<Principals><Principal id="Author"><UserId>' + XmlText(User) + '</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>' +
    '<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' +
    '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>5</Priority>' +
    '<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings></Settings>' +
    '<Actions Context="Author"><Exec><Command>' + XmlText(Folder + '\ColetorFrequencia.exe') + '</Command>' +
    '<Arguments>--background</Arguments><WorkingDirectory>' + XmlText(Folder) + '</WorkingDirectory></Exec></Actions></Task>';
  if not SaveStringsToUTF8File(Path, Lines, False) then
    RaiseException('Não foi possível preparar a abertura com o Windows.');
  if not Exec(ExpandConstant('{sys}\schtasks.exe'), '/Create /TN "' + LogonTask + '" /XML "' + Path + '" /F', '',
              SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    SuppressibleMsgBox('Não foi possível programar a abertura com o Windows. Abra o Coletor pelo menu Iniciar.',
                       mbError, MB_OK, IDOK);
  DeleteFile(Path);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if WizardIsTaskSelected('autostart') then RegisterLogonTask() else DeleteLogonTask();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then DeleteLogonTask();
end;

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
