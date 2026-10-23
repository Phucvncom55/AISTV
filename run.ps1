#requires -version 5.1
<#
  AI STV - chay bot Telegram tren Windows (PowerShell 5.1+ / PowerShell 7)
  Tuong duong run.sh tren Linux/macOS.

  Trong thu muc repo:
      .\run.ps1
      run.bat

  Chay tu xa (mot dong trong cmd hoac PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.ps1 | iex"

  Bien moi truong: TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, AISTV_REPO,
  AISTV_DIR, AISTV_BRANCH, AISTV_VENV, AISTV_CLEAN_INSTALL, STV_HOME.
#>
[CmdletBinding()]
param([string]$Repo = "")

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$ProgressPreference = "SilentlyContinue"

$script:PyExe = ""
$script:PyPre = @()
$script:AppDir = ""

function Say([string]$Message) { Write-Host "> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "! $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "x $Message" -ForegroundColor Red; exit 1 }

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } catch {
        $lines = @("$_")
        $code = 1
    } finally {
        $ErrorActionPreference = $prevEap
    }
    [pscustomobject]@{ Code = $code; Output = (@($lines) -join [Environment]::NewLine) }
}

function Normalize-Repo([string]$Url) {
    $Url = ($Url -as [string]).Trim().TrimEnd("/")
    if (-not $Url) { return "" }
    if ($Url -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://" -and $Url -notmatch "^git@" -and
        $Url -notmatch "^[A-Za-z]:[\\/]" -and $Url -notmatch "^[\\/]" -and
        $Url -notmatch "^\.{1,2}[\\/]" -and $Url -match "/") {
        $Url = "https://github.com/$Url"
    }
    if ($Url -match "^https?://" -and $Url -notmatch "\.git$") { $Url += ".git" }
    return $Url
}

function Invoke-Py {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PyArgs)
    $exe = $script:PyExe
    $pre = $script:PyPre
    & $exe @pre @PyArgs
}

function Initialize-Python {
    $candidates = @()
    if ($env:PYTHON) { $candidates += , @($env:PYTHON) }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($v in @("-3", "-3.13", "-3.12", "-3.11", "-3.10")) {
            $candidates += , @($launcher.Source, $v)
        }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += , @($cmd.Source) }
    }
    foreach ($cand in $candidates) {
        $exe = $cand[0]
        $pre = @()
        if ($cand.Count -gt 1) { $pre = $cand[1..($cand.Count - 1)] }
        try {
            $probe = Invoke-Native $exe (@($pre) + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"))
            if ($probe.Code -eq 0) {
                $script:PyExe = $exe
                $script:PyPre = $pre
                return (& $exe @pre -c "import platform; print(platform.python_version())").Trim()
            }
        } catch { }
    }
    return $null
}

function Save-EnvToken([string]$Token) {
    # Luu ca .env cua repo lan config.env dung chung: clone lai repo van con token.
    foreach ($path in @((Join-Path $script:AppDir ".env"), $script:CfgFile)) {
        if (-not $path) { continue }
        $dir = Split-Path -Parent $path
        if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $lines = @()
        if (Test-Path -LiteralPath $path) {
            $lines = @(Get-Content -LiteralPath $path -Encoding UTF8 | ForEach-Object { $_.TrimStart([char]0xFEFF) })
        }
        $found = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^\s*TELEGRAM_BOT_TOKEN\s*=") {
                $lines[$i] = "TELEGRAM_BOT_TOKEN=$Token"
                $found = $true
            }
        }
        if (-not $found) { $lines += "TELEGRAM_BOT_TOKEN=$Token" }
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        try { [System.IO.File]::WriteAllLines($path, $lines, $utf8) } catch { }
    }
    Say "Da luu token vao .env va $script:CfgFile (lan sau khong can nhap)."
}

function Copy-Seed([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) { return }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        $target = Join-Path $Destination $item.Name
        if ($item.PSIsContainer) {
            Copy-Seed $item.FullName $target
        } elseif (-not (Test-Path -LiteralPath $target)) {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

# -- 1. Xac dinh ma nguon: chay tai cho hay clone tu GitHub ------------
$Repo = Normalize-Repo $(if ($Repo) { $Repo } elseif ($env:AISTV_REPO) { $env:AISTV_REPO } else { "https://github.com/Phucvncom55/AISTV.git" })
$Branch = $(if ($env:AISTV_BRANCH) { $env:AISTV_BRANCH } else { "main" })
$UserHome = $(if ($env:USERPROFILE) { $env:USERPROFILE } else { $env:HOME })
if (-not $UserHome) { $UserHome = [Environment]::GetFolderPath("UserProfile") }
$script:AppDir = $(if ($env:AISTV_DIR) { $env:AISTV_DIR } else { Join-Path $UserHome "AISTV" })

$scriptDir = $PSScriptRoot
if ($scriptDir -and (Test-Path -LiteralPath (Join-Path $scriptDir "aistv_bot.py"))) {
    $script:AppDir = $scriptDir
    Say "Dung ma nguon tai $script:AppDir"
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail "Can Git de tai repo. Cai bang: winget install --id Git.Git -e   (hoac https://git-scm.com/download/win)"
    }
    if (Test-Path -LiteralPath (Join-Path $script:AppDir ".git")) {
        Say "Cap nhat ma nguon trong $script:AppDir"
        $pull = Invoke-Native git @("-C", $script:AppDir, "pull", "--ff-only")
        if ($pull.Code -ne 0) { Warn "Khong cap nhat duoc (bo qua), dung ban hien co." }
    } else {
        Say "Tai ma nguon tu $Repo"
        $clone = Invoke-Native git @("clone", "--depth", "1", "--branch", $Branch, $Repo, $script:AppDir)
        if ($clone.Code -ne 0) {
            if ($clone.Output) { Write-Host $clone.Output -ForegroundColor DarkGray }
            Fail "Khong clone duoc $Repo - kiem tra URL repo / AISTV_REPO."
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:AppDir "aistv_bot.py"))) {
        Fail "Repo thieu aistv_bot.py."
    }
}

Set-Location -LiteralPath $script:AppDir
$script:CfgFile = Join-Path $(if ($env:AISTV_CONFIG_DIR) { $env:AISTV_CONFIG_DIR } else { Join-Path $UserHome ".config\aistv" }) "config.env"
$script:FileEnv = @{}

# Thu tu uu tien giong run.sh: .env cua repo truoc, config.env dung chung sau.
function Import-EnvFiles {
    foreach ($envVarsFile in @((Join-Path $script:AppDir ".env"), $script:CfgFile)) {
        if (-not (Test-Path -LiteralPath $envVarsFile)) { continue }
        foreach ($line in (Get-Content -LiteralPath $envVarsFile -Encoding UTF8)) {
            $line = $line.TrimStart([char]0xFEFF)
            if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
            $idx = $line.IndexOf("=")
            $key = $line.Substring(0, $idx).Trim()
            if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
            if ($script:FileEnv.ContainsKey($key)) { continue }
            if (Test-Path -LiteralPath "env:$key") { continue }
            $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
            if (-not $value) { continue }
            Set-Item -Path "env:$key" -Value $value
            $script:FileEnv[$key] = $true
        }
    }
}

function Reset-FileEnv {
    foreach ($key in @($script:FileEnv.Keys)) {
        Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue
    }
    $script:FileEnv = @{}
}

Import-EnvFiles

# -- 2. Moi truong Python: venv -> Python he thong ---------------------
Say "AI STV runner (Windows)"

$pyVersion = Initialize-Python
if (-not $pyVersion) {
    Fail "Khong tim thay Python 3.10+. Cai bang: winget install --id Python.Python.3.12 -e
  Nho tick 'Add python.exe to PATH' (hoac chay lai trong cua so cmd moi)."
}
Say "Python $pyVersion"

$venv = Join-Path $script:AppDir ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
$baseExe = $script:PyExe
$basePre = $script:PyPre

if ($env:AISTV_VENV -ne "0" -and -not $env:VIRTUAL_ENV) {
    if ((Test-Path -LiteralPath $venv) -and -not (Test-Path -LiteralPath $venvPy)) {
        $broken = "$venv.broken." + [int][double]::Parse((Get-Date -UFormat %s))
        Say "venv cu khong chay duoc - doi ten thanh $(Split-Path $broken -Leaf)"
        Move-Item -LiteralPath $venv -Destination $broken -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Say "Tao moi truong ao .venv"
        & $baseExe @basePre -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
            Warn "Khong tao duoc venv - dung Python he thong."
            if (Test-Path -LiteralPath $venv) {
                Move-Item -LiteralPath $venv -Destination "$venv.broken" -Force -ErrorAction SilentlyContinue
            }
        }
    }
    if (Test-Path -LiteralPath $venvPy) {
        $script:PyExe = $venvPy
        $script:PyPre = @()
    }
}

$pipCheck = Invoke-Native $script:PyExe (@($script:PyPre) + @("-m", "pip", "--version"))
if ($pipCheck.Code -ne 0) {
    Say "Python thieu pip - chay ensurepip"
    $null = Invoke-Native $script:PyExe (@($script:PyPre) + @("-m", "ensurepip", "--upgrade"))
}

Say "Cai thu vien Python"
Invoke-Py "-m" "pip" "install" "-q" "-U" "pip" | Out-Null
$requirements = Join-Path $script:AppDir "requirements.txt"
Invoke-Py "-m" "pip" "install" "-q" "-U" "-r" $requirements
if ($LASTEXITCODE -ne 0) {
    Fail "Cai thu vien that bai.
  Thu tay: $script:PyExe -m pip install -r $requirements"
}
$importCheck = Invoke-Native $script:PyExe (@($script:PyPre) + @("-c", "import telegram, nest_asyncio"))
if ($importCheck.Code -ne 0) {
    if ($importCheck.Output) { Write-Host $importCheck.Output -ForegroundColor DarkGray }
    Fail "Da cai nhung khong import duoc python-telegram-bot / nest_asyncio."
}
Say "Thu vien Python OK"

# -- 4. Dong bo cau hinh tu GitHub / URL (giong run.bat / run.sh) -----
# AISTV_ENV_URL -> repo private (AISTV_CONFIG_TOKEN / GH_TOKEN / gh auth token /
# Colab Secrets). Nho vay token da co tren GitHub thi khong hoi lai.
$configScript = Join-Path $script:AppDir "aistv_config.py"
if (Test-Path -LiteralPath $configScript) {
    Reset-FileEnv
    Invoke-Py $configScript "sync"
    Import-EnvFiles
    $env:AISTV_CONFIG_SYNCED = "1"
}

# -- 5. Token: hoi lan cuoi neu GitHub/URL cung khong co ----------------
if (-not $env:TELEGRAM_BOT_TOKEN) {
    $canPrompt = $true
    try { $canPrompt = -not [Console]::IsInputRedirected } catch { $canPrompt = $true }
    if ($canPrompt) {
        Write-Host ""
        Write-Host "x Chua co Telegram Bot Token trong .env / config.env / GitHub." -ForegroundColor Red
        Write-Host "  * Kiem tra nguon: $script:PyExe $configScript doctor"
        Write-Host "  * Tao bot: nhan @BotFather -> /newbot -> lay token 123456:ABC..."
        Write-Host ""
        try {
            $secure = Read-Host "Dan Telegram Bot Token (Enter de bo qua)" -AsSecureString
            $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
            try { $token = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
            finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
            $token = ($token -replace "\s", "")
            if ($token) {
                $env:TELEGRAM_BOT_TOKEN = $token
                Save-EnvToken $token
            }
        } catch { }
    }
}

if (-not $env:TELEGRAM_BOT_TOKEN) {
    Fail "Thieu TELEGRAM_BOT_TOKEN. Da thu .env, config.env, GitHub (gh/PAT) va Colab Secrets.
  * Dang nhap GitHub: gh auth login   (hoac dat AISTV_CONFIG_TOKEN)
  * Hoac them TELEGRAM_BOT_TOKEN vao Colab Secrets / .env roi chay lai.
  * Kiem tra: $script:PyExe $configScript doctor"
}

# -- 6. Seed workspace lan dau (SOUL, AGENTS, skills) -----------------
$seed = Join-Path $script:AppDir "seed"
if (Test-Path -LiteralPath $seed) {
    if ($env:STV_HOME) {
        $workspace = Join-Path $env:STV_HOME "workspace"
    } else {
        $workspace = Join-Path $UserHome "stv_agent\workspace"
    }
    New-Item -ItemType Directory -Force -Path $workspace | Out-Null
    Copy-Seed $seed $workspace
}

# -- 7. Chay bot ------------------------------------------------------
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if (-not $env:AISTV_CLEAN_INSTALL) { $env:AISTV_CLEAN_INSTALL = "0" }
if (-not $env:STV_SKIP_SETUP) { $env:STV_SKIP_SETUP = "0" }

Say "Khoi chay AI STV... (Ctrl+C de dung)"
Invoke-Py (Join-Path $script:AppDir "aistv_bot.py")
exit $LASTEXITCODE
