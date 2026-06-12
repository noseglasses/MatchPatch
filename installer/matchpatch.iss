#ifndef AppVersion
  #error AppVersion must be supplied, for example: /DAppVersion=0.1.0
#endif

#ifndef SourceDir
  #error SourceDir must be supplied, for example: /DSourceDir=build\windows-payload\MatchPatch
#endif

#ifndef OutputDir
  #error OutputDir must be supplied, for example: /DOutputDir=dist\installer
#endif

#define AppName "MatchPatch"
#define AppUninstallRegistryKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{15537D18-AE3B-4B79-A046-9B95C60E2DB4}_is1"
#define AppPublisher "noseglasses/MatchPatch"
#define AppURL "https://github.com/noseglasses/MatchPatch"
#define UninstallerBaseName "Uninstall-MatchPatch"
#define UninstallerExeName "Uninstall-MatchPatch.exe"

[Setup]
AppId={{15537D18-AE3B-4B79-A046-9B95C60E2DB4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\MatchPatch
DefaultGroupName=MatchPatch
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\MatchPatch.exe
SetupIconFile={#SourceDir}\installer-assets\matchpatch.ico
WizardImageFile={#SourceDir}\installer-assets\wizard-logo.bmp
WizardSmallImageFile={#SourceDir}\installer-assets\wizard-small-logo.bmp
OutputDir={#OutputDir}
OutputBaseFilename=MatchPatch-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MatchPatch"; Filename: "{app}\MatchPatch.exe"; WorkingDir: "{app}"; IconFilename: "{app}\installer-assets\matchpatch.ico"
Name: "{group}\MatchPatch Documentation"; Filename: "{app}\docs_html\index.html"; WorkingDir: "{app}\docs_html"
Name: "{group}\Uninstall MatchPatch"; Filename: "{app}\{#UninstallerExeName}"
Name: "{autodesktop}\MatchPatch"; Filename: "{app}\MatchPatch.exe"; WorkingDir: "{app}"; IconFilename: "{app}\installer-assets\matchpatch.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\MatchPatch.exe"; Description: "{cm:LaunchProgram,MatchPatch}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
const
  UninstallerBaseName = '{#UninstallerBaseName}';
  UninstallerExeName = '{#UninstallerExeName}';
  UninstallRegistryKey = '{#AppUninstallRegistryKey}';

procedure RenameUninstallerFile(SourceName: string; TargetName: string);
var
  SourcePath: string;
  TargetPath: string;
begin
  SourcePath := ExpandConstant('{app}\') + SourceName;
  TargetPath := ExpandConstant('{app}\') + TargetName;

  if FileExists(SourcePath) then
  begin
    if FileExists(TargetPath) then
    begin
      DeleteFile(TargetPath);
    end;

    if not RenameFile(SourcePath, TargetPath) then
    begin
      RaiseException('Could not rename ' + SourcePath + ' to ' + TargetPath);
    end;
  end;
end;

procedure UpdateUninstallRegistry;
var
  UninstallerPath: string;
begin
  UninstallerPath := ExpandConstant('{app}\') + UninstallerExeName;
  RegWriteStringValue(
    HKEY_LOCAL_MACHINE,
    UninstallRegistryKey,
    'UninstallString',
    '"' + UninstallerPath + '"'
  );
  RegWriteStringValue(
    HKEY_LOCAL_MACHINE,
    UninstallRegistryKey,
    'QuietUninstallString',
    '"' + UninstallerPath + '" /SILENT'
  );
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RenameUninstallerFile('unins000.exe', UninstallerExeName);
    RenameUninstallerFile('unins000.dat', UninstallerBaseName + '.dat');
    RenameUninstallerFile('unins000.msg', UninstallerBaseName + '.msg');
    UpdateUninstallRegistry;
  end;
end;
