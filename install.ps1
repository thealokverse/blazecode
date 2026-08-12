#Requires -Version 5.1
<#
.SYNOPSIS
  Blazecode installer for Windows.

.DESCRIPTION
  Installs Blazecode into an isolated venv under $env:LOCALAPPDATA\blazecode
  and exposes `blazecode` through a shim on the user PATH. Re-run to update.
  Never touches ~/.blazecode (config, sessions, skills).

.PARAMETER Version
  Install a specific release tag (e.g. 1.2.1 or v1.2.1). Default: latest
  release, falling back to the main branch.

.PARAMETER BinDir
  Directory for the blazecode shim. Added to the user PATH if missing.

.PARAMETER Uninstall
  Remove Blazecode. Keeps ~/.blazecode.

.EXAMPLE
  # default install (piped)
  irm https://raw.githubusercontent.com/thealokverse/blazecode/main/install.ps1 | iex

.EXAMPLE
  # pin a version (local file)
  .\install.ps1 -Version 1.2.1

.EXAMPLE
  # uninstall
  .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Version,
  [string]$BinDir,
  [switch]$Uninstall,
  [switch]$Help
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # quieten Invoke-WebRequest progress

# native commands should not abort on non-zero exit (PS 7.3+); we check $LASTEXITCODE ourselves
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
  $PSNativeCommandUseErrorActionPreference = $false
}

# force TLS 1.2 for older .NET stacks used by Invoke-WebRequest
try {
  [Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocol]::Tls12
} catch { }

# --- config from env (supports `irm | iex` piping where params can't be passed) ---
$Repo        = if ($env:BLAZECODE_REPO)         { $env:BLAZECODE_REPO }         else { 'thealokverse/blazecode' }
$Branch      = if ($env:BLAZECODE_BRANCH)       { $env:BLAZECODE_BRANCH }       else { 'main' }
$InstallRoot = if ($env:BLAZECODE_INSTALL_ROOT) { $env:BLAZECODE_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA 'blazecode' }
if (-not $Version)   { $Version = $env:BLAZECODE_VERSION }
if (-not $BinDir)    { $BinDir  = $env:BLAZECODE_BIN_DIR }
if (-not $BinDir)    { $BinDir  = Join-Path $InstallRoot 'bin' }
$doUninstall = [bool]$Uninstall -or ($env:BLAZECODE_UNINSTALL -match '^(1|true|yes)$')

# --- logging helpers ---
function Log([string]$msg)        { Write-Host $msg }
function Note([string]$msg)       { Write-Host "=>" -ForegroundColor Cyan; Write-Host " $msg" }
function Warn([string]$msg)       { Write-Host "warn: $msg" -ForegroundColor Yellow }
function Err([string]$msg)        { Write-Host "error: $msg" -ForegroundColor Red }
function Die([string]$msg)        { Err $msg; exit 1 }

if ($Help) {
  Log "Blazecode installer (Windows)"
  Log "  -Version <tag>   Install a specific release tag (default: latest release, else main)"
  Log "  -BinDir <path>   Directory for the blazecode shim (added to user PATH)"
  Log "  -Uninstall       Remove Blazecode (keeps ~/.blazecode)"
  Log ""
  Log "Env vars: BLAZECODE_REPO, BLAZECODE_BRANCH, BLAZECODE_INSTALL_ROOT,"
  Log "          BLAZECODE_BIN_DIR, BLAZECODE_VERSION, BLAZECODE_PYTHON,"
  Log "          BLAZECODE_UNINSTALL=1"
  exit 0
}

# --- path / PATH helpers ---
function Get-UserPath {
  $p = [Environment]::GetEnvironmentVariable('Path', 'User')
  if (-not $p) { return @() }
  return $p -split ';' | Where-Object { $_ -ne '' }
}

function Test-PathOnUserPath([string]$Dir) {
  $target = $Dir.TrimEnd('\', '/')
  foreach ($p in (Get-UserPath)) {
    if ($p.TrimEnd('\', '/') -ieq $target) { return $true }
  }
  return $false
}

function Add-UserPath([string]$Dir) {
  if (Test-PathOnUserPath $Dir) { return $false }
  $parts = @(Get-UserPath) + $Dir
  $new = $parts -join ';'
  if ($new.Length -gt 1024) {
    Warn "User PATH is too long to add $Dir automatically."
    return $false
  }
  [Environment]::SetEnvironmentVariable('Path', $new, 'User')
  if (-not (Test-PathOnUserPath $Dir)) {
    # reflect in current session too
    $env:Path = "$Dir;$env:Path"
  }
  return $true
}

function Remove-UserPath([string]$Dir) {
  $target = $Dir.TrimEnd('\', '/')
  $parts  = Get-UserPath
  $kept = @()
  foreach ($p in $parts) {
    if ($p.TrimEnd('\', '/') -ieq $target) { continue }
    $kept += $p
  }
  if ($kept.Count -eq $parts.Count) { return $false }
  [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
  return $true
}

# --- python discovery (3.11+) ---
function Find-Python {
  $tries = @()
  if ($env:BLAZECODE_PYTHON) { $tries += ,@{ Exe = $env:BLAZECODE_PYTHON; Args = @() } }
  # the py launcher is the most reliable on Windows
  foreach ($v in '3.14', '3.13', '3.12', '3.11') {
    $tries += ,@{ Exe = 'py'; Args = @("-$v") }
  }
  $tries += ,@{ Exe = 'py';      Args = @('-3') }
  $tries += ,@{ Exe = 'python';  Args = @() }
  $tries += ,@{ Exe = 'python3'; Args = @() }

  foreach ($t in $tries) {
    $exe = $t.Exe
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
      & $exe @($t.Args) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) {
        $ver = (& $exe @($t.Args) -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>$null).Trim()
        return @{ Exe = $exe; Args = $t.Args; Version = $ver }
      }
    } catch { }
  }
  Die "Python 3.11+ is required. Install it from https://www.python.org/ (or 'winget install Python.Python.3.12'), then re-run this script."
}

# --- version resolution ---
function Resolve-Version {
  if ($Version) { return ($Version -replace '^v', '') }
  try {
    $url = "https://api.github.com/repos/$Repo/releases/latest"
    $resp = Invoke-RestMethod -Uri $url -Headers @{ 'User-Agent' = 'blazecode-installer' }
    if ($resp.tag_name) { return ($resp.tag_name -replace '^v', '') }
  } catch { }
  return $null
}

function Download-File([string]$Url, [string]$Dest) {
  try {
    Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
  } catch {
    Die "download failed: $Url`n$_"
  }
}

# --- uninstall ---
function Invoke-Uninstall {
  Note "Uninstalling Blazecode"
  $shim = Join-Path $BinDir 'blazecode.cmd'
  $removed = $false

  if (Test-Path -LiteralPath $shim) {
    try { Remove-Item -LiteralPath $shim -Force } catch { }
    if (-not (Test-Path -LiteralPath $shim)) {
      Log "  removed $shim"
      $removed = $true
    } else {
      Warn "could not remove $shim (in use?)"
    }
  } else {
    Log "  no $shim found"
  }

  foreach ($p in @($InstallRoot, "$InstallRoot.old")) {
    if (Test-Path -LiteralPath $p) {
      try { Remove-Item -LiteralPath $p -Recurse -Force } catch { }
      if (-not (Test-Path -LiteralPath $p)) {
        Log "  removed $p"
        $removed = $true
      } else {
        Warn "could not remove $p (in use? close editors/terminals and retry)"
      }
    } else {
      Log "  no $p found"
    }
  }

  # drop the shim dir from PATH if it was ours
  if (Remove-UserPath $BinDir) { Log "  removed $BinDir from user PATH" }

  $userHome = if ($env:BLAZECODE_HOME) { $env:BLAZECODE_HOME } else { Join-Path $env:USERPROFILE '.blazecode' }
  if (Test-Path -LiteralPath $userHome) {
    Log "  preserved $userHome (config, sessions, skills)"
  }

  if (-not $removed) { Note "Nothing to uninstall." }
  else { Note "Blazecode removed." }
}

# --- install ---
function Invoke-Install {
  $py = Find-Python
  $resolved = Resolve-Version
  if ($resolved) {
    $displayVersion = "v$resolved"
    $archive = "blazecode-$resolved.zip"
    $url = "https://github.com/$Repo/archive/refs/tags/v$resolved.zip"
  } else {
    $displayVersion = "$Branch (no release tag found)"
    $archive = "blazecode-$Branch.zip"
    $url = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
  }

  Note "Blazecode installer"
  Log "  python:  $($py.Exe)$(if ($py.Args) { ' ' + ($py.Args -join ' ') }) ($($py.Version))"
  Log "  prefix:  $InstallRoot"
  Log "  bin-dir: $BinDir"
  Log "  version: $displayVersion"

  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("blazecode-install-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp -Force | Out-Null
  $zipPath = Join-Path $tmp $archive

  Note "Downloading source"
  Download-File $url $zipPath
  if (-not (Test-Path -LiteralPath $zipPath)) { Die "download produced no file: $url" }

  Note "Extracting"
  $extract = Join-Path $tmp 'src'
  Expand-Archive -Path $zipPath -DestinationPath $extract -Force
  $srcDir = Get-ChildItem -Path $extract -Directory | Select-Object -First 1
  if (-not $srcDir -or -not (Test-Path -LiteralPath (Join-Path $srcDir.FullName 'pyproject.toml'))) {
    Die "unexpected archive layout (no pyproject.toml at archive root)"
  }
  $srcDir = $srcDir.FullName

  Note "Creating virtualenv"
  $parent = Split-Path -Parent $InstallRoot
  if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

  # keep previous install until the new one is ready, then swap
  if (Test-Path -LiteralPath "$InstallRoot.old") {
    Remove-Item -LiteralPath "$InstallRoot.old" -Recurse -Force
  }
  if (Test-Path -LiteralPath $InstallRoot) {
    Move-Item -LiteralPath $InstallRoot -Destination "$InstallRoot.old"
  }

  & $py.Exe @($py.Args) -m venv $InstallRoot
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $InstallRoot 'Scripts\python.exe'))) {
    if (Test-Path -LiteralPath "$InstallRoot.old") { Move-Item -LiteralPath "$InstallRoot.old" -Destination $InstallRoot }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Die "failed to create virtualenv at $InstallRoot"
  }

  $venvPython = Join-Path $InstallRoot 'Scripts\python.exe'

  # upgrade pip quietly; ignore failure on locked-down environments
  & $venvPython -m pip install --upgrade pip setuptools wheel -q 2>$null
  if ($LASTEXITCODE -ne 0) { Warn "could not upgrade pip/setuptools (continuing)" }

  Note "Installing package"
  & $venvPython -m pip install --upgrade $srcDir -q
  if ($LASTEXITCODE -ne 0) {
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath "$InstallRoot.old") { Move-Item -LiteralPath "$InstallRoot.old" -Destination $InstallRoot }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Die "pip install failed"
  }

  Remove-Item -LiteralPath "$InstallRoot.old" -Recurse -Force -ErrorAction SilentlyContinue
  $versionLabel = if ($resolved) { $resolved } else { $Branch }
  Set-Content -LiteralPath (Join-Path $InstallRoot 'VERSION') -Value $versionLabel -Encoding ascii

  if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'Scripts\blazecode.exe'))) {
    Die "install succeeded but blazecode entrypoint is missing"
  }

  # shim calls the venv python at its final path (mirrors install.sh launcher)
  Note "Linking $BinDir\blazecode.cmd"
  if (-not (Test-Path -LiteralPath $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
  $shim = @"
@echo off
"$venvPython" -m blazecode %*
"@
  Set-Content -LiteralPath (Join-Path $BinDir 'blazecode.cmd') -Value $shim -Encoding ascii

  Note "Verifying"
  $reportedRaw = & "$BinDir\blazecode.cmd" --version 2>&1
  $verifyCode = $LASTEXITCODE
  $reported = ($reportedRaw | Out-String).Trim()
  if ($verifyCode -ne 0) {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Die "blazecode --version failed after install:`n$reported"
  }
  Log "  $reported"

  $addedPath = Add-UserPath $BinDir
  if (-not (Test-PathOnUserPath $BinDir)) {
    Warn "$BinDir is not on your PATH"
    Log "  Add it manually via Settings > Environment Variables, or:"
    Log "    [Environment]::SetEnvironmentVariable('Path', `"$BinDir;`$([Environment]::GetEnvironmentVariable('Path','User'))`", 'User')"
  } elseif ($addedPath) {
    Warn "$BinDir was added to your user PATH."
    Log "  Open a new terminal for the change to take effect."
  }

  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

  Log ""
  Note "Done. Run: blazecode"
  Log "  Binary: $BinDir\blazecode.cmd"
  Log "  Prefix: $InstallRoot"
  Log "  Config: ~/.blazecode (never modified by this installer)"
  Log ""
  Log "  Update:    irm https://raw.githubusercontent.com/$Repo/main/install.ps1 | iex"
  Log "  Uninstall: .\install.ps1 -Uninstall"
}

if ($doUninstall) { Invoke-Uninstall } else { Invoke-Install }
