; SPDX-License-Identifier: MIT
#ifndef InputDir
  #error InputDir must point to the verified native artifact
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef ToastClsid
  #error ToastClsid must match the native client identity
#endif

[Setup]
AppId=CapybaraGram.Desktop
AppName=CapybaraGram
AppVersion=0.1.0-preview.1
AppVerName=CapybaraGram 0.1.0 Preview
AppPublisher=CapybaraGram contributors
AppPublisherURL=https://github.com/AlbertBoss/capybaragram-build
DefaultDirName={localappdata}\Programs\CapybaraGram
DefaultGroupName=CapybaraGram Preview
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=CapybaraGram-Windows-x64-Setup
SetupIconFile=..\windows-brand\capy-icon.ico
UninstallDisplayIcon={app}\CapybaraGram.exe
LicenseFile={#InputDir}\LICENSE
InfoBeforeFile={#InputDir}\INSTALL-NOTES.txt
VersionInfoVersion=0.1.0.1
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=CapybaraGram.exe
RestartApplications=no
SetupMutex=CapybaraGram.Desktop.Setup
Uninstallable=yes
UninstallDisplayName=CapybaraGram

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#InputDir}\CapybaraGram.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#InputDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#InputDir}\LEGAL"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#InputDir}\SOURCE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#InputDir}\INSTALL-NOTES.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CapybaraGram"; Filename: "{app}\CapybaraGram.exe"; WorkingDir: "{app}"; AppUserModelID: "CapybaraGram.Preview"; AppUserModelToastActivatorCLSID: "{#ToastClsid}"
Name: "{userdesktop}\CapybaraGram"; Filename: "{app}\CapybaraGram.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "CapybaraGram.Preview"; AppUserModelToastActivatorCLSID: "{#ToastClsid}"

[Run]
Filename: "{app}\CapybaraGram.exe"; Description: "{cm:LaunchProgram,CapybaraGram}"; Flags: nowait postinstall skipifsilent unchecked
