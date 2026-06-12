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
#define AppPublisher "noseglasses/MatchPatch"
#define AppURL "https://github.com/noseglasses/MatchPatch"

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
Name: "{group}\Uninstall MatchPatch"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MatchPatch"; Filename: "{app}\MatchPatch.exe"; WorkingDir: "{app}"; IconFilename: "{app}\installer-assets\matchpatch.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\MatchPatch.exe"; Description: "{cm:LaunchProgram,MatchPatch}"; Flags: nowait postinstall skipifsilent unchecked
