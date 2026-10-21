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
  // Same name as QUIT_EVENT in app/coletor/instance_lock.py. The Coletor
  // ignores WM_CLOSE (it hides beside the clock), so Restart Manager cannot
  // close it: it is asked to quit, finishes the collection in flight and exits.
  QuitEvent = 'Local\EcossistemaEscolar.ColetorFrequencia.Encerrar';
  // Longer than EXIT_COLLECTION_WAIT in app/coletor/desktop.py (15 min).
  QuitWaitSeconds = 17 * 60;
  // Versions up to 0.4.245 have no quit event: they are stopped after this.
  LegacyWaitSeconds = 5;
  EVENT_MODIFY_STATE = $0002;

var
  CollectorWasRunning: Boolean;

function OpenEvent(Access: DWORD; Inherit: BOOL; Name: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(Handle: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';
function GetTickCount(): DWORD;
  external 'GetTickCount@kernel32.dll stdcall';

// Coletor processes started from this installation folder only (the launcher,
// pythonw and its python workers), never another Python on the computer.
// Terminate stops them (launcher first, so it shows no start-failure message).
function CollectorProcesses(Folder: String; Terminate: Boolean): Integer;
var
  Locator, Service, Items, Item: Variant;
  Names: array of String;
  N, I: Integer;
  Path: String;
begin
  Result := 0;
  Folder := Lowercase(AddBackslash(Folder));
  SetArrayLength(Names, 2);
  Names[0] := 'Name = ''ColetorFrequencia.exe''';
  Names[1] := 'Name = ''pythonw.exe'' OR Name = ''python.exe''';
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    for N := 0 to GetArrayLength(Names) - 1 do
    begin
      Items := Service.ExecQuery('SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE ' + Names[N]);
      for I := 0 to Items.Count - 1 do
      begin
        Item := Items.ItemIndex(I);
        Path := '';
        if not VarIsNull(Item.ExecutablePath) then Path := Item.ExecutablePath;
        Path := Lowercase(Path);
        if (Path <> '') and (Pos(Folder, Path) = 1) then
        begin
          Result := Result + 1;
          if Terminate then
            try
              Item.Terminate();
            except
              Log('Coletor process could not be stopped: ' + GetExceptionMessage);
            end;
        end;
      end;
    end;
  except
    Log('Coletor processes could not be listed: ' + GetExceptionMessage);
    Result := -1;
  end;
end;

function AskCollectorToQuit(): Boolean;
var
  Handle: THandle;
begin
  Result := False;
  Handle := OpenEvent(EVENT_MODIFY_STATE, False, QuitEvent);
  if Handle <> 0 then
  begin
    Result := SetEvent(Handle);
    CloseHandle(Handle);
  end;
end;

function WaitForCollectorExit(Folder: String; Seconds: Integer; Page: TOutputProgressWizardPage): Boolean;
var
  Started, Elapsed: DWORD;
begin
  // Wall-clock time: each process query itself can take over a second.
  Started := GetTickCount();
  repeat
    if CollectorProcesses(Folder, False) = 0 then
    begin
      Result := True;
      exit;
    end;
    Elapsed := GetTickCount() - Started;
    if Page <> nil then Page.SetProgress(Elapsed div 1000, Seconds);
    Sleep(500);
  until Elapsed >= Seconds * 1000;
  Result := CollectorProcesses(Folder, False) = 0;
end;

// Closes a running Coletor before its files are replaced or removed. It never
// interrupts a collection: the app finishes it first (up to 15 min). Only an
// unresponsive or older Coletor is stopped, and its saved queue is kept.
function CloseCollector(Folder: String; Page: TOutputProgressWizardPage): String;
var
  Seconds: Integer;
begin
  Result := '';
  if CollectorProcesses(Folder, False) = 0 then exit;
  CollectorWasRunning := True;
  if AskCollectorToQuit() then Seconds := QuitWaitSeconds else Seconds := LegacyWaitSeconds;
  Log('Closing the running Coletor; quit event answered: ' + IntToStr(Ord(Seconds = QuitWaitSeconds)));
  if Page <> nil then
  begin
    Page.SetText('Fechando o Coletor de Frequência…',
                 'Se uma coleta estiver em andamento, o Coletor termina essa coleta antes de fechar.');
    Page.Show;
  end;
  try
    if not WaitForCollectorExit(Folder, Seconds, Page) then
    begin
      Log('Coletor did not quit in time; stopping its processes.');
      CollectorProcesses(Folder, True);
      if not WaitForCollectorExit(Folder, 15, nil) then
        Result := 'Não foi possível fechar o Coletor de Frequência. Use "Encerrar coletor" no ícone ao lado do relógio e tente de novo.';
    end;
  finally
    if Page <> nil then Page.Hide;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Page: TOutputProgressWizardPage;
begin
  Page := nil;
  if not WizardSilent then
    Page := CreateOutputProgressPage('Preparando a atualização', 'Fechando o Coletor de Frequência.');
  Result := CloseCollector(ExpandConstant('{app}'), Page);
end;

procedure ReopenCollector();
var
  Code: Integer;
begin
  // Reopened beside the clock, as it was before the update.
  if not ExecAsOriginalUser(ExpandConstant('{app}\programa\ColetorFrequencia.exe'), '--background',
                            ExpandConstant('{app}\programa'), SW_SHOWNORMAL, ewNoWait, Code) then
    Log('Coletor could not be reopened: ' + SysErrorMessage(Code));
end;

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
  Xml, Path, User, Folder: String;
  Code: Integer;
begin
  User := GetEnv('USERDOMAIN') + '\' + GetUserNameString();
  Folder := ExpandConstant('{app}\programa');
  Path := ExpandConstant('{tmp}\coletor-logon-task.xml');
  // schtasks rejects UTF-8 task files; system-ANSI text without an XML declaration is accepted.
  Xml :=
    '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' +
    '<RegistrationInfo><Description>Abre o Coletor de Frequência ao lado do relógio ao entrar no Windows.</Description></RegistrationInfo>' +
    '<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>' + XmlText(User) + '</UserId><Delay>PT30S</Delay></LogonTrigger></Triggers>' +
    '<Principals><Principal id="Author"><UserId>' + XmlText(User) + '</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>' +
    '<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' +
    '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>5</Priority>' +
    '<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings></Settings>' +
    '<Actions Context="Author"><Exec><Command>' + XmlText(Folder + '\ColetorFrequencia.exe') + '</Command>' +
    '<Arguments>--background</Arguments><WorkingDirectory>' + XmlText(Folder) + '</WorkingDirectory></Exec></Actions></Task>';
  if not SaveStringToFile(Path, Xml, False) then
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
  begin
    if WizardIsTaskSelected('autostart') then RegisterLogonTask() else DeleteLogonTask();
    if CollectorWasRunning then ReopenCollector();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Error: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    DeleteLogonTask();
    Error := CloseCollector(ExpandConstant('{app}'), nil);
    if Error <> '' then Log(Error);
  end;
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
