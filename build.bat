@echo off
setlocal

cd /d "%~dp0"

set BUILD_MODE=%~1
if "%BUILD_MODE%"=="" set BUILD_MODE=onedir
set TARGET_DIST=dist
set TARGET_PREV=dist_prev
set TARGET_TMP=dist_build_tmp

echo [ClipDis] Running compile check...
python -m compileall main.py app
if errorlevel 1 exit /b 1

set OLD_APPDATA=%APPDATA%
set OLD_LOCALAPPDATA=%LOCALAPPDATA%
set OLD_QT_QPA_PLATFORM=%QT_QPA_PLATFORM%
set CLIPDIS_BUILD_TEST_ROOT=%TEMP%\clipdis_build_%RANDOM%%RANDOM%
set APPDATA=%CLIPDIS_BUILD_TEST_ROOT%\Roaming
set LOCALAPPDATA=%CLIPDIS_BUILD_TEST_ROOT%\Local
mkdir "%APPDATA%" >nul 2>nul
mkdir "%LOCALAPPDATA%" >nul 2>nul

echo [ClipDis] Running source smoke check...
python main.py --smoke-check
if errorlevel 1 goto :restore_and_fail

echo [ClipDis] Running source QML smoke check...
set QT_QPA_PLATFORM=offscreen
python main.py --qml-smoke-check
if errorlevel 1 goto :restore_and_fail

set APPDATA=%OLD_APPDATA%
set LOCALAPPDATA=%OLD_LOCALAPPDATA%
set QT_QPA_PLATFORM=%OLD_QT_QPA_PLATFORM%

if /i "%BUILD_MODE%"=="release" (
    set TARGET_DIST=dist_release
    set TARGET_PREV=dist_release_prev
    set TARGET_TMP=dist_release_build_tmp
)

echo [ClipDis] Preparing staged build output...
if exist build rmdir /s /q build
if exist "%TARGET_TMP%" rmdir /s /q "%TARGET_TMP%"
if exist "%TARGET_PREV%" rmdir /s /q "%TARGET_PREV%"

if /i "%BUILD_MODE%"=="onefile" (
    echo [ClipDis] Building onefile test executable...
    set CLIPDIS_ONEFILE=1
) else if /i "%BUILD_MODE%"=="release" (
    echo [ClipDis] Building onedir release executable without console...
    set CLIPDIS_ONEFILE=0
) else (
    echo [ClipDis] Building onedir test executable...
    set CLIPDIS_ONEFILE=0
)

if /i "%BUILD_MODE%"=="release" (
    set CLIPDIS_CONSOLE=0
) else (
    set CLIPDIS_CONSOLE=1
)

python -m PyInstaller --noconfirm --clean --distpath "%TARGET_TMP%" ClipDis.spec
if errorlevel 1 exit /b 1

echo [ClipDis] Publishing build output...
if /i "%BUILD_MODE%"=="onefile" (
    if not exist "%TARGET_DIST%" mkdir "%TARGET_DIST%"
    if exist "%TARGET_DIST%\ClipDis.exe" del /q "%TARGET_DIST%\ClipDis.exe"
    move "%TARGET_TMP%\ClipDis.exe" "%TARGET_DIST%\ClipDis.exe" >nul
    if errorlevel 1 exit /b 1
    rmdir /s /q "%TARGET_TMP%"
) else (
    if not exist "%TARGET_DIST%" mkdir "%TARGET_DIST%"
    if exist "%TARGET_DIST%\ClipDis" rmdir /s /q "%TARGET_DIST%\ClipDis"
    if exist "%TARGET_DIST%\ClipDis" (
        echo [ClipDis] Could not replace %TARGET_DIST%\ClipDis. Close any running ClipDis.exe and retry.
        exit /b 1
    )
    move "%TARGET_TMP%\ClipDis" "%TARGET_DIST%\ClipDis" >nul
    if errorlevel 1 exit /b 1
    if exist "%TARGET_TMP%\ClipDis.exe" del /q "%TARGET_TMP%\ClipDis.exe"
    rmdir /s /q "%TARGET_TMP%"
)

if /i "%BUILD_MODE%"=="onefile" (
    echo Build output: %CD%\dist\ClipDis.exe
) else if /i "%BUILD_MODE%"=="release" (
    if exist dist_release\ClipDis.exe del /q dist_release\ClipDis.exe
    echo Build output: %CD%\dist_release\ClipDis\ClipDis.exe
) else (
    if exist dist\ClipDis.exe del /q dist\ClipDis.exe
    echo Build output: %CD%\dist\ClipDis\ClipDis.exe
)

endlocal
exit /b 0

:restore_and_fail
set APPDATA=%OLD_APPDATA%
set LOCALAPPDATA=%OLD_LOCALAPPDATA%
set QT_QPA_PLATFORM=%OLD_QT_QPA_PLATFORM%
endlocal
exit /b 1
