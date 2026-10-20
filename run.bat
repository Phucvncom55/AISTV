@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul
title AI STV

rem ==================================================================
rem  AI STV - runner cho Windows, viet bang cmd thuan (khong PowerShell)
rem
rem  Trong thu muc repo:   run.bat
rem  Repo khac:            run.bat owner/repo
rem
rem  Bien moi truong: TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, AISTV_REPO,
rem  AISTV_DIR, AISTV_BRANCH, AISTV_VENV, AISTV_CLEAN_INSTALL, STV_HOME.
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

if exist "%SCRIPT_DIR%\aistv_bot.py" (
  set "APP_DIR=%SCRIPT_DIR%"
  echo [AI STV] Dung ma nguon tai "!APP_DIR!"
  goto app_ready
)

rem -- 1. Xac dinh repo va tai ma nguon ---------------------------------
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
echo %REPO% | findstr /i /e /c:".git" >nul
if errorlevel 1 set "REPO=%REPO%.git"

where git >nul 2>nul
if errorlevel 1 goto no_git

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

:app_ready
if not exist "%APP_DIR%\aistv_bot.py" goto no_source
cd /d "%APP_DIR%"

rem -- 2. Doc .env ------------------------------------------------------
if exist "%APP_DIR%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%APP_DIR%\.env") do (
    if /i "%%A"=="TELEGRAM_BOT_TOKEN" if not defined TELEGRAM_BOT_TOKEN set "TELEGRAM_BOT_TOKEN=%%B"
    if /i "%%A"=="ALLOWED_USER_IDS" if not defined ALLOWED_USER_IDS set "ALLOWED_USER_IDS=%%B"
  )
)
if defined TELEGRAM_BOT_TOKEN set "TELEGRAM_BOT_TOKEN=%TELEGRAM_BOT_TOKEN:"=%"
if defined ALLOWED_USER_IDS set "ALLOWED_USER_IDS=%ALLOWED_USER_IDS:"=%"
if defined TELEGRAM_BOT_TOKEN set "TELEGRAM_BOT_TOKEN=%TELEGRAM_BOT_TOKEN: =%"

rem -- 3. Tim Python 3.10+ ---------------------------------------------
set "PYEXE="
set "PYPRE="
set "PYTEST=import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"

py -3 -c "%PYTEST%" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=py"
  set "PYPRE=-3"
  goto python_found
)
python -c "%PYTEST%" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=python"
  goto python_found
)
python3 -c "%PYTEST%" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=python3"
  goto python_found
)
goto no_python

:python_found
set "PYVER="
for /f "usebackq delims=" %%V in (`%PYEXE% %PYPRE% -c "import platform;print(platform.python_version())"`) do set "PYVER=%%V"
echo [AI STV] Python %PYVER%

set "VENV=%APP_DIR%\.venv"
if "%AISTV_VENV%"=="0" goto python_ready
if defined VIRTUAL_ENV goto python_ready

if exist "%VENV%\Scripts\python.exe" (
  set "PYEXE=%VENV%\Scripts\python.exe"
  set "PYPRE="
  goto python_ready
)

if exist "%VENV%" (
  echo [AI STV] venv cu khong chay duoc - doi ten thanh .venv.broken
  move "%VENV%" "%VENV%.broken.%RANDOM%" >nul 2>nul
)

echo [AI STV] Tao moi truong ao .venv
%PYEXE% %PYPRE% -m venv "%VENV%"
if exist "%VENV%\Scripts\python.exe" (
  set "PYEXE=%VENV%\Scripts\python.exe"
  set "PYPRE="
) else (
  echo [AI STV] Khong tao duoc venv - dung Python he thong.
  if exist "%VENV%" move "%VENV%" "%VENV%.broken.%RANDOM%" >nul 2>nul
)

:python_ready
"%PYEXE%" %PYPRE% -m pip --version >nul 2>nul
if errorlevel 1 (
  echo [AI STV] Python thieu pip - chay ensurepip
  "%PYEXE%" %PYPRE% -m ensurepip --upgrade >nul 2>nul
  "%PYEXE%" %PYPRE% -m pip --version >nul 2>nul
  if errorlevel 1 goto no_pip
)

echo [AI STV] Cai thu vien Python
"%PYEXE%" %PYPRE% -m pip install -q -U pip
"%PYEXE%" %PYPRE% -m pip install -q -U -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
  echo [AI STV] pip loi - thu lai voi --user
  "%PYEXE%" %PYPRE% -m pip install -q -U --user -r "%APP_DIR%\requirements.txt"
)
if errorlevel 1 goto pip_fail

"%PYEXE%" %PYPRE% -c "import telegram, nest_asyncio" >nul 2>nul
if errorlevel 1 goto import_fail
echo [AI STV] Thu vien Python OK

rem -- 4. Token: .env -> bien moi truong -> hoi truc tiep ---------------
if not defined TELEGRAM_BOT_TOKEN (
  echo.
  echo [AI STV] Chua co Telegram Bot Token.
  echo     Tao bot: nhan @BotFather -^> /newbot -^> lay token 123456:ABC...
  set /p "TOKEN=Dan Telegram Bot Token (Enter de bo qua): "
  if defined TOKEN (
    set "AISTV_TOK=!TOKEN!"
    "%PYEXE%" %PYPRE% -c "import os,pathlib;p=pathlib.Path('.env');t=os.environ['AISTV_TOK'];L=[l for l in (p.read_text('utf-8').splitlines() if p.exists() else []) if not l.strip().startswith('TELEGRAM_BOT_TOKEN')];p.write_text(chr(10).join(L+['TELEGRAM_BOT_TOKEN='+t])+chr(10),'utf-8')"
    set "TELEGRAM_BOT_TOKEN=!TOKEN!"
    echo [AI STV] Da luu token vao .env - lan sau khong can nhap.
  )
)
if not defined TELEGRAM_BOT_TOKEN echo [AI STV] Chua co token - bot se hoi khi khoi dong.

rem -- 5. Seed workspace lan dau (khong ghi de du lieu da co) ----------
set "WS=%USERPROFILE%\stv_agent\workspace"
if defined STV_HOME set "WS=%STV_HOME%\workspace"
if exist "%APP_DIR%\seed" (
  "%PYEXE%" %PYPRE% -c "import pathlib,shutil;s=pathlib.Path(r'%APP_DIR%\seed');d=pathlib.Path(r'%WS%');[(d/f.relative_to(s)).parent.mkdir(parents=True,exist_ok=True) or shutil.copy2(f,d/f.relative_to(s)) for f in s.rglob('*') if f.is_file() and not (d/f.relative_to(s)).exists()]"
)

rem -- 6. Chay bot ------------------------------------------------------
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined AISTV_CLEAN_INSTALL set "AISTV_CLEAN_INSTALL=0"
if not defined STV_SKIP_SETUP set "STV_SKIP_SETUP=0"

echo [AI STV] Khoi chay AI STV... (Ctrl+C de dung)
"%PYEXE%" %PYPRE% "%APP_DIR%\aistv_bot.py"
set "CODE=%errorlevel%"
endlocal & exit /b %CODE%

rem -- loi --------------------------------------------------------------
:no_git
echo x Can Git de tai repo.
echo   Cai bang: winget install --id Git.Git -e
echo   Hoac tai: https://git-scm.com/download/win
goto fail

:no_source
echo x Repo thieu aistv_bot.py.
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

:no_python
echo x Khong tim thay Python 3.10+.
echo   Cai bang: winget install --id Python.Python.3.12 -e
echo   Nho tick "Add python.exe to PATH" roi mo cua so cmd moi.
goto fail

:no_pip
echo x Python khong co pip.
echo   Thu: "%PYEXE%" -m ensurepip --upgrade
echo   Hoac cai lai Python tu python.org (co san pip).
goto fail

:pip_fail
echo x Cai thu vien that bai.
echo   Thu tay: "%PYEXE%" -m pip install -r "%APP_DIR%\requirements.txt"
goto fail

:import_fail
echo x Da cai nhung khong import duoc python-telegram-bot / nest_asyncio.
goto fail

:fail
echo.
endlocal & exit /b 1
