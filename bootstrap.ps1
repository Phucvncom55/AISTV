#requires -version 5.1
<#
  AI STV — bootstrap cho Windows.
  Luôn tải/cập nhật repo rồi mới chạy run.ps1 trong repo, nhờ vậy không bị
  kẹt bản cũ do cache của raw.githubusercontent.com.

  Chạy một dòng (cmd hoặc PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.ps1 | iex"

  Hoặc trong repo:
      .\bootstrap.ps1
      bootstrap.bat

  Biến môi trường: AISTV_REPO, AISTV_BRANCH, AISTV_DIR (như run.ps1).
#>
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$ProgressPreference = "SilentlyContinue"

$PSNativeCommandUseErrorActionPreference = $false

function Say([string]$Message) { Write-Host "> $Message" -ForegroundColor Cyan }

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

$Repo = $(if ($args.Count -ge 1 -and $args[0]) { $args[0] }
          elseif ($env:AISTV_REPO) { $env:AISTV_REPO }
          else { "https://github.com/Phucvncom55/AISTV.git" })
$Repo = Normalize-Repo $Repo
$Branch = $(if ($env:AISTV_BRANCH) { $env:AISTV_BRANCH } else { "main" })
$AppDir = $(if ($env:AISTV_DIR) { $env:AISTV_DIR } else { Join-Path $env:USERPROFILE "AISTV" })

$scriptDir = $PSScriptRoot
if ($scriptDir -and (Test-Path -LiteralPath (Join-Path $scriptDir "aistv_bot.py"))) {
    $AppDir = $scriptDir
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "x Cần Git để tải repo." -ForegroundColor Red
    Write-Host "  Cài bằng: winget install --id Git.Git -e   (hoặc https://git-scm.com/download/win)"
    exit 1
}

Say "AI STV bootstrap (Windows)"

if (Test-Path -LiteralPath (Join-Path $AppDir ".git")) {
    Say "Cập nhật mã nguồn trong $AppDir"
    $pull = Invoke-Native git @("-C", $AppDir, "pull", "--ff-only")
    if ($pull.Code -ne 0) {
        Say "Không fast-forward được — lấy đúng bản $Branch trên GitHub."
        $fetch = Invoke-Native git @("-C", $AppDir, "fetch", "--depth", "1", "origin", $Branch)
        if ($fetch.Code -ne 0) {
            Write-Host "x Không tải được $Repo (nhánh $Branch)." -ForegroundColor Red
            if ($fetch.Output) { Write-Host $fetch.Output -ForegroundColor DarkGray }
            exit 1
        }
        $reset = Invoke-Native git @("-C", $AppDir, "reset", "--hard", "FETCH_HEAD")
        if ($reset.Code -ne 0) {
            Write-Host "x Không cập nhật được $AppDir." -ForegroundColor Red
            if ($reset.Output) { Write-Host $reset.Output -ForegroundColor DarkGray }
            exit 1
        }
    }
} else {
    Say "Tải mã nguồn từ $Repo"
    $clone = Invoke-Native git @("clone", "--depth", "1", "--branch", $Branch, $Repo, $AppDir)
    if ($clone.Code -ne 0) {
        Write-Host "x Không clone được $Repo — kiểm tra URL / nhánh $Branch." -ForegroundColor Red
        if ($clone.Output) { Write-Host $clone.Output -ForegroundColor DarkGray }
        exit 1
    }
}

$runScript = Join-Path $AppDir "run.ps1"
if (-not (Test-Path -LiteralPath $runScript)) {
    Write-Host "x Repo thiếu run.ps1." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $AppDir "aistv_bot.py"))) {
    Write-Host "x Repo thiếu aistv_bot.py." -ForegroundColor Red
    exit 1
}

$shellExe = (Get-Process -Id $PID).Path
if (-not $shellExe) {
    $shellExe = Join-Path $PSHOME $(if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" })
}
& $shellExe -NoProfile -ExecutionPolicy Bypass -File $runScript
exit $LASTEXITCODE
