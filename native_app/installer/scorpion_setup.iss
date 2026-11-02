; Scorpion IDM installer (Inno Setup 6). Compiled by build_installer.ps1, which passes:
;   /DAppVersion=<x.y.z> /DAppDir=<staged app> /DToolsDir=<bundled programs> /DRepoRoot=<repo>
;   /DOutputDir=<folder> /DOutputBaseName=<file name without .exe>
; The installed ScorpionIDM.exe is the official, signed Python runtime; app\sitecustomize.py starts the app.

#define AppName "Scorpion Download Manager"
#define AppExe "ScorpionIDM.exe"
#define RunName "ScorpionIDM"
#define TorrentProgId "ScorpionIDM.torrent"

[Setup]
; Fixed id: lets later setups and the uninstaller recognise this app. Never change it.
AppId={{53EB99EF-A68D-4FF0-A085-D8938A20CBD5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Scorpion Labs
DefaultDirName={localappdata}\Programs\ScorpionIDM
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
SetupIconFile={#RepoRoot}\build\icon.ico
UninstallDisplayIcon={app}\build\icon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=auto

[Languages]
Name: "ar"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ar.StartWithWindows=تشغيل البرنامج تلقائياً مع ويندوز
en.StartWithWindows=Start Scorpion with Windows
ar.AssociateTorrents=فتح ملفات التورنت وروابط ماجنت بالبرنامج
en.AssociateTorrents=Open .torrent files and Magnet links with Scorpion
ar.Integration=التكامل مع ويندوز:
en.Integration=Windows integration:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "{cm:StartWithWindows}"; GroupDescription: "{cm:Integration}"
Name: "torrents"; Description: "{cm:AssociateTorrents}"; GroupDescription: "{cm:Integration}"

[InstallDelete]
; PyInstaller runtime of versions before the move to the signed Python runtime
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ToolsDir}\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\build\icon.ico"; AppUserModelID: "Scorpion.DownloadManager"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\build\icon.ico"; AppUserModelID: "Scorpion.DownloadManager"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the app creates itself (compiled Python caches, downloaded tools pack, update leftovers)
Type: filesandordirs; Name: "{app}"

[Code]
procedure AskRunningAppToQuit();
var
  ResultCode: Integer;
begin
  { The app's local bridge only accepts /quit with the trusted-client header }
  Exec('powershell.exe',
    '-NoProfile -NonInteractive -WindowStyle Hidden -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 ' +
    '-Headers @{''X-Scorpion-Client''=''1''} http://127.0.0.1:19615/quit | Out-Null; Start-Sleep -Seconds 2 } catch {}"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  AskRunningAppToQuit();
  Result := '';
end;

function BoolText(Value: Boolean): String;
begin
  if Value then Result := 'true' else Result := 'false';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PrefsDir: String;
begin
  { The app applies these once on its next start (startup entry, torrent association, desktop shortcut).
    Silent updates keep the user's existing choices, so they write nothing. }
  if (CurStep = ssPostInstall) and not WizardSilent then
  begin
    PrefsDir := ExpandConstant('{localappdata}\ScorpionIDM');
    ForceDirectories(PrefsDir);
    SaveStringToFile(PrefsDir + '\install_prefs.json',
      '{"startWithWindows": ' + BoolText(WizardIsTaskSelected('startup')) +
      ', "associateTorrents": ' + BoolText(WizardIsTaskSelected('torrents')) +
      ', "desktopShortcut": ' + BoolText(WizardIsTaskSelected('desktopicon')) + '}', False);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  AskRunningAppToQuit();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Windows integration written by the app itself }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunName}');
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\{#TorrentProgId}');
  end;
end;
