@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
title AI STV bootstrap

rem ==================================================================
rem  AI STV - bootstrap cho Windows (cmd thuan, khong PowerShell)
rem
rem  Chay 1 dong trong cmd:
rem    curl -fsSL -o "%TEMP%\aistv_bootstrap.bat" "https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.bat?v=1" && call "%TEMP%\aistv_bootstrap.bat"
rem
rem  Hoac trong thu muc repo: bootstrap.bat
rem  Bien moi truong: AISTV_REPO, AISTV_BRANCH, AISTV_DIR.
rem ==================================================================

set "DEFAULT_REPO=https://github.com/Phucvncom55/AISTV.git"
set "BRANCH=%AISTV_BRANCH%"
if not defined BRANCH set "BRANCH=main"

if not defined USERPROFILE (
  if defined HOMEDRIVE if defined HOMEPATH set "USERPROFILE=%HOMEDRIVE%%HOMEPATH%"
)
if not defined USERPROFILE set "USERPROFILE=%CD%"

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "APP_DIR=%AISTV_DIR%"
if not defined APP_DIR set "APP_DIR=%USERPROFILE%\AISTV"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "HAVE_SRC="
if exist "%SCRIPT_DIR%\aistv_bot.py" (
  set "APP_DIR=%SCRIPT_DIR%"
  set "HAVE_SRC=1"
)

set "REPO=%~1"
if not defined REPO set "REPO=%AISTV_REPO%"
if not defined REPO set "REPO=%DEFAULT_REPO%"
if "%REPO:~-1%"=="/" set "REPO=%REPO:~0,-1%"

if /i "%REPO:~0,8%"=="https://" goto repo_norm
if /i "%REPO:~0,7%"=="http://" goto repo_norm
if /i "%REPO:~0,4%"=="git@" goto repo_norm
if /i "%REPO:~0,6%"=="ssh://" goto repo_norm
echo %REPO% | findstr /c:"/" >nul
if not errorlevel 1 set "REPO=https://github.com/%REPO%"

:repo_norm
rem Dung cat chuoi, KHONG dung findstr: findstr /e khong khop ".git" khi
rem echo co khoang trang -> sinh ra AISTV.git.git (loi cu).
if /i not "%REPO:~-4%"==".git" set "REPO=%REPO%.git"

where git >nul 2>nul
if errorlevel 1 (
  if defined HAVE_SRC goto have_source
  goto no_git
)

echo [AI STV] Bootstrap (Windows / cmd)
if defined HAVE_SRC if not exist "%APP_DIR%\.git" goto have_source
if exist "%APP_DIR%\.git" (
  echo [AI STV] Cap nhat ma nguon trong "%APP_DIR%"
  git -C "%APP_DIR%" pull --ff-only
  if errorlevel 1 (
    echo [AI STV] Khong fast-forward duoc - lay dung ban %BRANCH% tren GitHub.
    git -C "%APP_DIR%" fetch --depth 1 origin %BRANCH%
    if errorlevel 1 goto fetch_fail
    git -C "%APP_DIR%" reset --hard FETCH_HEAD
    if errorlevel 1 goto reset_fail
  )
) else (
  echo [AI STV] Tai ma nguon tu %REPO%
  git clone --depth 1 --branch "%BRANCH%" "%REPO%" "%APP_DIR%"
  if errorlevel 1 goto clone_fail
)

:have_source
if not exist "%APP_DIR%\run.bat" goto no_run
if not exist "%APP_DIR%\aistv_bot.py" goto no_source

call "%APP_DIR%\run.bat"
set "CODE=%errorlevel%"
endlocal & exit /b %CODE%

:no_git
echo x Can Git de tai repo.
echo   Cai bang: winget install --id Git.Git -e
echo   Hoac tai: https://git-scm.com/download/win
goto fail

:no_source
echo x Repo thieu aistv_bot.py.
goto fail

:no_run
echo x Repo thieu run.bat.
goto fail

:clone_fail
echo x Khong clone duoc %REPO% - kiem tra URL repo / nhanh %BRANCH%.
goto fail

:fetch_fail
echo x Khong tai duoc %REPO% (nhanh %BRANCH%).
goto fail

:reset_fail
echo x Khong cap nhat duoc "%APP_DIR%".
goto fail

:fail
echo.
endlocal & exit /b 1
