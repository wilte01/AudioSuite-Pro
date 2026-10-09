; audiosuite.iss - Inno Setup 6 script for the AudioSuite-Pro installer.
;
; Route A: the staged payload already contains the first-party source tree,
; a relocatable CPython runtime (runtime\), and a CLI shim (bin\audiosuite.cmd),
; so this script only lays the payload down and wires up shortcuts, PATH and
; the optional post-install launch.
;
; Compile via packaging\build_installer.ps1, which supplies the /D defines:
;   AppVersion, StagingDir, OutputDir, ShortcutsFile (and BundleFFmpeg when set)
;
; Per-user install under {localappdata} on purpose: the suite writes its config
; (audio_suite_config.json) and logs next to its own source tree
; (audio_suite_shared/suite_config.py, audio_suite_shared/logging_setup.py), so
; {app} must be user-writable without elevation.

#define AppName "AudioSuite-Pro"
#define AppPublisher "AudioSuite-Pro"
#define MasterLauncher "Master_Driver.pyw"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StagingDir
  #define StagingDir "build\app"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef ShortcutsFile
  #define ShortcutsFile "build\shortcuts.iss"
#endif

[Setup]
AppId={{B7F2C1E4-5A3D-4E9B-8C6F-1D2E3F4A5B6C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\AudioSuite-Pro
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=AudioSuite-Pro-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
#if FileExists(AddBackslash(StagingDir) + "LICENSE")
LicenseFile={#StagingDir}\LICENSE
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the audiosuite command to my PATH"; GroupDescription: "Command line:"

[Files]
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Master Driver is the suite hub and is always present; the per-tool launchers
; are enumerated from the staged payload by build_installer.ps1.
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\{#MasterLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\runtime\pythonw.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\{#MasterLauncher}"""; WorkingDir: "{app}"; IconFilename: "{app}\runtime\pythonw.exe"; Tasks: desktopicon
#include ShortcutsFile

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\bin"; Check: NeedsAddPath('{app}\bin'); Tasks: addtopath

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\{#MasterLauncher}"""; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { Look for the path with a leading semicolon so we do not match a prefix
    of another directory. }
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;
