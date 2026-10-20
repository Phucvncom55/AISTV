#requires -version 5.1
<#
  AI STV - bootstrap cho Windows.
  Luon tai/cap nhat repo roi moi chay run.ps1 trong repo, nho vay khong bi
  ket ban cu do cache cua raw.githubusercontent.com.

  Chay mot dong (cmd hoac PowerShell):
      powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.ps1 | iex"

  Hoac trong repo:
      .\bootstrap.ps1
      bootstrap.bat

  Bien moi truong: AISTV_REPO, AISTV_BRANCH, AISTV_DIR (nhu run.ps1).
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
$UserHome = $(if ($env:USERPROFILE) { $env:USERPROFILE } else { $env:HOME })
$AppDir = $(if ($env:AISTV_DIR) { $env:AISTV_DIR } elseif ($UserHome) { Join-Path $UserHome "AISTV" } else { Join-Path ([Environment]::GetFolderPath("UserProfile")) "AISTV" })

$scriptDir = $PSScriptRoot
if ($scriptDir -and (Test-Path -LiteralPath (Join-Path $scriptDir "aistv_bot.py"))) {
    $AppDir = $scriptDir
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "x Can Git de tai repo." -ForegroundColor Red
    Write-Host "  Cai bang: winget install --id Git.Git -e   (hoac https://git-scm.com/download/win)"
    exit 1
}

Say "AI STV bootstrap (Windows)"

if (Test-Path -LiteralPath (Join-Path $AppDir ".git")) {
    Say "Cap nhat ma nguon trong $AppDir"
    $pull = Invoke-Native git @("-C", $AppDir, "pull", "--ff-only")
    if ($pull.Code -ne 0) {
        Say "Khong fast-forward duoc - lay dung ban $Branch tren GitHub."
        $fetch = Invoke-Native git @("-C", $AppDir, "fetch", "--depth", "1", "origin", $Branch)
        if ($fetch.Code -ne 0) {
            Write-Host "x Khong tai duoc $Repo (nhanh $Branch)." -ForegroundColor Red
            if ($fetch.Output) { Write-Host $fetch.Output -ForegroundColor DarkGray }
            exit 1
        }
        $reset = Invoke-Native git @("-C", $AppDir, "reset", "--hard", "FETCH_HEAD")
        if ($reset.Code -ne 0) {
            Write-Host "x Khong cap nhat duoc $AppDir." -ForegroundColor Red
            if ($reset.Output) { Write-Host $reset.Output -ForegroundColor DarkGray }
            exit 1
        }
    }
} else {
    Say "Tai ma nguon tu $Repo"
    $clone = Invoke-Native git @("clone", "--depth", "1", "--branch", $Branch, $Repo, $AppDir)
    if ($clone.Code -ne 0) {
        Write-Host "x Khong clone duoc $Repo - kiem tra URL / nhanh $Branch." -ForegroundColor Red
        if ($clone.Output) { Write-Host $clone.Output -ForegroundColor DarkGray }
        exit 1
    }
}

$runScript = Join-Path $AppDir "run.ps1"
if (-not (Test-Path -LiteralPath $runScript)) {
    Write-Host "x Repo thieu run.ps1." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $AppDir "aistv_bot.py"))) {
    Write-Host "x Repo thieu aistv_bot.py." -ForegroundColor Red
    exit 1
}

$shellExe = (Get-Process -Id $PID).Path
if (-not $shellExe) {
    $shellExe = Join-Path $PSHOME $(if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" })
}
& $shellExe -NoProfile -ExecutionPolicy Bypass -File $runScript
exit $LASTEXITCODE
