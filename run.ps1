#requires -version 5.1
<#
  AI STV — chạy bot Telegram trên Windows (PowerShell 5.1+ / PowerShell 7)
  Tương đương run.sh trên Linux/macOS.

  Trong thư mục repo:
      .\run.ps1
      run.bat

  Chạy từ xa (một dòng trong cmd hoặc PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.ps1 | iex"

  Biến môi trường: TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, AISTV_REPO,
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
    $path = Join-Path $script:AppDir ".env"
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
    [System.IO.File]::WriteAllLines($path, $lines, $utf8)
    Say "Đã lưu token vào .env (lần sau không cần nhập)."
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

# ── 1. Xác định mã nguồn: chạy tại chỗ hay clone từ GitHub ────────────
$Repo = Normalize-Repo $(if ($Repo) { $Repo } elseif ($env:AISTV_REPO) { $env:AISTV_REPO } else { "https://github.com/Phucvncom55/AISTV.git" })
$Branch = $(if ($env:AISTV_BRANCH) { $env:AISTV_BRANCH } else { "main" })
$script:AppDir = $(if ($env:AISTV_DIR) { $env:AISTV_DIR } else { Join-Path $env:USERPROFILE "AISTV" })

$scriptDir = $PSScriptRoot
if ($scriptDir -and (Test-Path -LiteralPath (Join-Path $scriptDir "aistv_bot.py"))) {
    $script:AppDir = $scriptDir
    Say "Dùng mã nguồn tại $script:AppDir"
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail "Cần Git để tải repo. Cài bằng: winget install --id Git.Git -e   (hoặc https://git-scm.com/download/win)"
    }
    if (Test-Path -LiteralPath (Join-Path $script:AppDir ".git")) {
        Say "Cập nhật mã nguồn trong $script:AppDir"
        $pull = Invoke-Native git @("-C", $script:AppDir, "pull", "--ff-only")
        if ($pull.Code -ne 0) { Warn "Không cập nhật được (bỏ qua), dùng bản hiện có." }
    } else {
        Say "Tải mã nguồn từ $Repo"
        $clone = Invoke-Native git @("clone", "--depth", "1", "--branch", $Branch, $Repo, $script:AppDir)
        if ($clone.Code -ne 0) {
            if ($clone.Output) { Write-Host $clone.Output -ForegroundColor DarkGray }
            Fail "Không clone được $Repo — kiểm tra URL repo / AISTV_REPO."
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $script:AppDir "aistv_bot.py"))) {
        Fail "Repo thiếu aistv_bot.py."
    }
}

Set-Location -LiteralPath $script:AppDir
$envVarsFile = Join-Path $script:AppDir ".env"
if (Test-Path -LiteralPath $envVarsFile) {
    foreach ($line in (Get-Content -LiteralPath $envVarsFile -Encoding UTF8)) {
        $line = $line.TrimStart([char]0xFEFF)
        if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if ($key -eq "TELEGRAM_BOT_TOKEN" -and -not $env:TELEGRAM_BOT_TOKEN) { $env:TELEGRAM_BOT_TOKEN = $value }
        elseif ($key -eq "ALLOWED_USER_IDS" -and -not $env:ALLOWED_USER_IDS) { $env:ALLOWED_USER_IDS = $value }
    }
}

# ── 2. Token: .env → biến môi trường → hỏi trực tiếp ─────────────────
if (-not $env:TELEGRAM_BOT_TOKEN) {
    $canPrompt = $true
    try { $canPrompt = -not [Console]::IsInputRedirected } catch { $canPrompt = $true }
    try {
        if (-not $canPrompt) { throw "non-interactive" }
        $secure = Read-Host "Dán Telegram Bot Token (Enter để bỏ qua)" -AsSecureString
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

if (-not $env:TELEGRAM_BOT_TOKEN) {
    Write-Host ""
    Write-Host "x Chưa có Telegram Bot Token." -ForegroundColor Red
    Write-Host "  • Tạo bot: nhắn @BotFather → /newbot → lấy token 123456:ABC..."
    Write-Host "  • Tạo file .env trong thư mục repo:"
    Write-Host "        TELEGRAM_BOT_TOKEN=123456:ABC..."
    Write-Host "        ALLOWED_USER_IDS=123456789        (nên đặt, để khoá bot)"
    Write-Host "  • Hoặc chạy: `$env:TELEGRAM_BOT_TOKEN='123456:ABC...'; .\run.ps1"
    Write-Host ""
    exit 1
}

# ── 3. Môi trường Python: venv → Python hệ thống ─────────────────────
Say "AI STV runner (Windows)"

$pyVersion = Initialize-Python
if (-not $pyVersion) {
    Fail "Không tìm thấy Python 3.10+. Cài bằng: winget install --id Python.Python.3.12 -e
  Nhớ tick 'Add python.exe to PATH' (hoặc chạy lại trong cửa sổ cmd mới)."
}
Say "Python $pyVersion"

$venv = Join-Path $script:AppDir ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
$baseExe = $script:PyExe
$basePre = $script:PyPre

if ($env:AISTV_VENV -ne "0" -and -not $env:VIRTUAL_ENV) {
    if ((Test-Path -LiteralPath $venv) -and -not (Test-Path -LiteralPath $venvPy)) {
        $broken = "$venv.broken." + [int][double]::Parse((Get-Date -UFormat %s))
        Say "venv cũ không chạy được — đổi tên thành $(Split-Path $broken -Leaf)"
        Move-Item -LiteralPath $venv -Destination $broken -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Say "Tạo môi trường ảo .venv"
        & $baseExe @basePre -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPy)) {
            Warn "Không tạo được venv — dùng Python hệ thống."
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
    Say "Python thiếu pip — chạy ensurepip"
    $null = Invoke-Native $script:PyExe (@($script:PyPre) + @("-m", "ensurepip", "--upgrade"))
}

Say "Cài thư viện Python"
Invoke-Py "-m" "pip" "install" "-q" "-U" "pip" | Out-Null
$requirements = Join-Path $script:AppDir "requirements.txt"
Invoke-Py "-m" "pip" "install" "-q" "-U" "-r" $requirements
if ($LASTEXITCODE -ne 0) {
    Fail "Cài thư viện thất bại.
  Thử tay: $script:PyExe -m pip install -r $requirements"
}
$importCheck = Invoke-Native $script:PyExe (@($script:PyPre) + @("-c", "import telegram, nest_asyncio"))
if ($importCheck.Code -ne 0) {
    if ($importCheck.Output) { Write-Host $importCheck.Output -ForegroundColor DarkGray }
    Fail "Đã cài nhưng không import được python-telegram-bot / nest_asyncio."
}
Say "Thư viện Python OK"

# ── 4. Seed workspace lần đầu (SOUL, AGENTS, skills) ─────────────────
$seed = Join-Path $script:AppDir "seed"
if (Test-Path -LiteralPath $seed) {
    if ($env:STV_HOME) {
        $workspace = Join-Path $env:STV_HOME "workspace"
    } else {
        $workspace = Join-Path $env:USERPROFILE "stv_agent\workspace"
    }
    New-Item -ItemType Directory -Force -Path $workspace | Out-Null
    Copy-Seed $seed $workspace
}

# ── 5. Chạy bot ──────────────────────────────────────────────────────
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if (-not $env:AISTV_CLEAN_INSTALL) { $env:AISTV_CLEAN_INSTALL = "0" }
if (-not $env:STV_SKIP_SETUP) { $env:STV_SKIP_SETUP = "0" }

Say "Khởi chạy AI STV… (Ctrl+C để dừng)"
Invoke-Py (Join-Path $script:AppDir "aistv_bot.py")
exit $LASTEXITCODE
