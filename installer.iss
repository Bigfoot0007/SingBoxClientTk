; Inno Setup script — builds SingBoxClient-win-x64-setup.exe from the
; PyInstaller COLLECT folder (dist\SingBoxClient\). Run by CI on
; windows-latest (Inno Setup is preinstalled there).

[Setup]
AppName=SingBox Client
AppVersion=1.0
AppPublisher=local
DefaultDirName={autopf}\SingBoxClient
UninstallDisplayIcon={app}\SingBoxClient.exe
OutputDir=Output
OutputBaseFilename=SingBoxClient-win-x64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Files]
Source: "dist\SingBoxClient\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\SingBox Client"; Filename: "{app}\SingBoxClient.exe"
Name: "{autodesktop}\SingBox Client"; Filename: "{app}\SingBoxClient.exe"

[Run]
Filename: "{app}\SingBoxClient.exe"; Description: "启动 SingBox Client"; Flags: nowait postinstall skipifsilent
