@echo off
setlocal
cd /d "%~dp0"

set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
set "CODE=%errorlevel%"
endlocal & exit /b %CODE%
