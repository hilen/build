; Per user install of one exe, a start menu shortcut and an uninstaller.
; makensis -DNAME=.. -DVERSION=.. -DEXE=path -DICON=path -DOUTPUT=path installer.nsi
; /S installs silently, which the updater never needs, it swaps the exe itself.

Unicode true
Name "${NAME}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\${NAME}"
InstallDirRegKey HKCU "Software\${NAME}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Icon "${ICON}"
UninstallIcon "${ICON}"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File "/oname=${NAME}.exe" "${EXE}"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${NAME}"
  CreateShortcut "$SMPROGRAMS\${NAME}\${NAME}.lnk" "$INSTDIR\${NAME}.exe"
  WriteRegStr HKCU "Software\${NAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}" "DisplayName" "${NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}" "DisplayIcon" "$INSTDIR\${NAME}.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}" "InstallLocation" "$INSTDIR"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${NAME}.exe"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${NAME}\${NAME}.lnk"
  RMDir "$SMPROGRAMS\${NAME}"
  DeleteRegKey HKCU "Software\${NAME}"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NAME}"
SectionEnd
