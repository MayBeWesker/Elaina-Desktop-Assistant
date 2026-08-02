@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%~dp0;%PATH%"
set "PROJECT_DIR=%~dp0"
if defined LIVE2D_PYTHON (
    set "PYTHON_EXE=%LIVE2D_PYTHON%"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python.exe"
)
if /i "%~1"=="--backend" goto BACKEND

title Elaina Desktop Assistant
set "ELECTRON_EXE=%~dp0node_modules\electron\dist\electron.exe"
set "ELECTRON_LOG=%~dp0tmp\electron-console.log"
set "ELECTRON_ERROR_LOG=%~dp0tmp\electron-error.log"
set "ELECTRON_STARTUP_LOG=%~dp0tmp\electron-startup.log"

echo ==========================================
echo   Elaina Desktop Assistant
echo ==========================================
echo.

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ was not found.
    echo Create .venv or set LIVE2D_PYTHON to python.exe.
    pause
    exit /b 1
)

echo [Start] Restarting the backend in a visible command window...
taskkill /FI "WINDOWTITLE eq Live2D Assistant - Backend Runtime" /T /F >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":1017" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1
)
timeout /t 1 /nobreak >nul
start "Live2D Backend Server" /D "%PROJECT_DIR%" cmd.exe /d /k call "%~f0" --backend
echo [INFO] Keep the backend window open to monitor ASR, TTS, WebSocket and errors.

echo.
echo [Start] Launching desktop character...
echo.

if not exist "%ELECTRON_EXE%" (
    echo [ERROR] Electron executable was not found:
    echo %ELECTRON_EXE%
    echo Run npm install in the project directory first.
    pause
    exit /b 1
)

powershell.exe -NoProfile -Command "$shownBefore = 0; if (Test-Path -LiteralPath $env:ELECTRON_STARTUP_LOG) { $shownBefore = @(Select-String -LiteralPath $env:ELECTRON_STARTUP_LOG -SimpleMatch 'window shown').Count }; try { $p = Start-Process -FilePath $env:ELECTRON_EXE -ArgumentList @('.') -WorkingDirectory $env:PROJECT_DIR -RedirectStandardOutput $env:ELECTRON_LOG -RedirectStandardError $env:ELECTRON_ERROR_LOG -PassThru -ErrorAction Stop } catch { Write-Error $_; exit 3 }; $deadline = (Get-Date).AddSeconds(12); do { Start-Sleep -Milliseconds 250; if ($p.HasExited) { exit 1 }; if (Test-Path -LiteralPath $env:ELECTRON_STARTUP_LOG) { $shownNow = @(Select-String -LiteralPath $env:ELECTRON_STARTUP_LOG -SimpleMatch 'window shown').Count; if ($shownNow -gt $shownBefore) { exit 0 } } } while ((Get-Date) -lt $deadline); exit 2"
if %errorlevel% neq 0 (
    echo [ERROR] The desktop character window did not finish loading.
    echo [INFO] If Windows says the application control policy blocked electron.exe,
    echo        the unsigned Electron runtime must be allowed or replaced by an
    echo        administrator-approved signed runtime.
    echo [INFO] Error log: %ELECTRON_ERROR_LOG%
    if exist "%ELECTRON_ERROR_LOG%" type "%ELECTRON_ERROR_LOG%"
    if exist "%ELECTRON_LOG%" type "%ELECTRON_LOG%"
    if exist "%ELECTRON_STARTUP_LOG%" (
        echo [INFO] Startup log:
        powershell.exe -NoProfile -Command "Get-Content -LiteralPath $env:ELECTRON_STARTUP_LOG -Tail 30"
    )
    pause
    exit /b 1
)

echo [OK] Desktop character was launched.
echo [INFO] This launcher window can now be closed.
exit /b 0

:BACKEND
title Live2D Assistant - Backend Runtime
cd /d "%~dp0"
set "PATH=%~dp0;%PATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ==========================================
echo   Live2D Assistant - Backend Runtime
echo ==========================================
echo Project: %CD%
echo Python:  %PYTHON_EXE%
echo Status:  Loading ASR and TTS models...
echo.

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ was not found: %PYTHON_EXE%
    exit /b 1
)

"%PYTHON_EXE%" -u server.py --web
set "BACKEND_EXIT_CODE=%ERRORLEVEL%"
echo.
echo ==========================================
echo [ERROR] Backend stopped. Exit code: %BACKEND_EXIT_CODE%
echo The window is kept open for diagnostics.
echo ==========================================
exit /b %BACKEND_EXIT_CODE%
