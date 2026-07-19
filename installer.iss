; Inno Setup script — wraps the built app into a friendly Windows installer.
; OPTIONAL: only needed if you want a real "Setup.exe" wizard instead of a zip.
;
; How to use:
;   1. Run BUILD_EXE.bat first (creates dist\Bandwidth Report Manager\).
;   2. Install Inno Setup (free): https://jrsoftware.org/isdl.php
;   3. Open this file in Inno Setup and click Build (or run ISCC.exe installer.iss).
;   Output: Output\BandwidthReportManagerSetup.exe  — this is what you send users.
;
; NOTE: this installs PER-USER (under %LOCALAPPDATA%\Programs), NOT into
; Program Files. The manager writes credentials into the report scripts in
; its own folder, so the install directory must stay user-writable.

#define AppName "Bandwidth Report Manager"
#define AppVersion "1.1.0"
#define AppPublisher "Your Team"
#define AppExe "Bandwidth Report Manager.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={userpf}\Bandwidth Report Manager
DefaultGroupName=Bandwidth Report Manager
DisableProgramGroupPage=yes
OutputBaseFilename=BandwidthReportManagerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Bundle everything PyInstaller produced (exe + report scripts + templates).
Source: "dist\Bandwidth Report Manager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Bandwidth Report Manager"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall Bandwidth Report Manager"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bandwidth Report Manager"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Bandwidth Report Manager"; Flags: nowait postinstall skipifsilent
