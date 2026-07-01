<#
Unified Windows production installer for Y5E Automation.

Run from an elevated PowerShell in the repository root:
  Set-ExecutionPolicy -Scope Process Bypass -Force
  .\scripts\install_windows_production.ps1 -InstallTools

After validating a foreground render, install the native runner at startup:
  .\scripts\install_windows_production.ps1 -InstallRunnerService
#>

[CmdletBinding()]
param(
    [switch]$InstallTools,
    [switch]$InstallRunnerService,
    [switch]$SkipStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw "Run PowerShell as Administrator."
    }
}

function Install-WingetPackage([string]$Id, [string]$Name) {
    if (-not (Test-Command "winget")) {
        throw "winget is missing. Install App Installer from Microsoft Store, then rerun this command."
    }
    winget list --id $Id --exact --accept-source-agreements 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$Name is already installed."
        return
    }
    if (-not $InstallTools) {
        throw "$Name is missing. Rerun with -InstallTools."
    }
    Write-Host "Installing $Name..."
    winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed to install $Name ($Id)."
    }
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Require-Command([string]$Name) {
    if (-not (Test-Command $Name)) {
        throw "$Name was installed but is not available yet. Close PowerShell, open it as Administrator, then rerun the installer."
    }
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Assert-Environment([string]$EnvPath) {
    $values = Read-DotEnv $EnvPath
    $required = @(
        "PRIMARY_API_BASE", "PRIMARY_API_KEY", "PRIMARY_MODEL",
        "TELEGRAM_BOT_TOKEN", "CLOUDFLARE_TUNNEL_TOKEN",
        "YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET",
        "YOUTUBE_TOKEN_ENCRYPTION_KEY"
    )
    $missing = @()
    foreach ($key in $required) {
        $value = if ($values.ContainsKey($key)) { [string]$values[$key] } else { "" }
        if (-not $value -or $value -match "CHANGE_ME|your-|placeholder") { $missing += $key }
    }
    if ($missing.Count -gt 0) {
        throw "Configure .env before startup. Missing or placeholder values: $($missing -join ', ')"
    }
    if ($values["NATIVE_RENDER_ENABLED"] -ne "true") {
        throw "Set NATIVE_RENDER_ENABLED=true in .env."
    }
    if ($values["NATIVE_RENDER_FALLBACK"] -ne "error") {
        throw "Set NATIVE_RENDER_FALLBACK=error in .env; Docker rendering is not allowed."
    }
}

function Wait-Docker([int]$TimeoutSeconds = 120) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (docker info 2>$null)) {
        if (Test-Path $dockerDesktop) { Start-Process $dockerDesktop }
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    throw "Docker Desktop did not become ready within $TimeoutSeconds seconds. Open Docker Desktop and rerun."
}

function Test-Nvenc {
    Write-Step "Checking NVIDIA and h264_nvenc"
    nvidia-smi | Out-Host
    $probe = Join-Path $env:TEMP "y5e-nvenc-check.mp4"
    ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i "color=c=black:s=64x64:r=30:d=0.2" `
        -an -c:v h264_nvenc -pix_fmt yuv420p $probe
    if ($LASTEXITCODE -ne 0) { throw "NVIDIA h264_nvenc test failed. Update the NVIDIA driver and rerun." }
    Remove-Item $probe -Force -ErrorAction SilentlyContinue
}

function Wait-ApiReady([int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $result = Invoke-RestMethod -Uri "http://localhost:8000/api/ready" -TimeoutSec 5
            if ($result.status -eq "ready") { return }
        } catch { }
        Start-Sleep -Seconds 3
    }
    docker compose logs --tail=100 api | Out-Host
    throw "API /api/ready did not become ready within $TimeoutSeconds seconds."
}

Assert-Administrator
Write-Step "Installing Windows prerequisites"
Install-WingetPackage "Git.Git" "Git for Windows"
Install-WingetPackage "Docker.DockerDesktop" "Docker Desktop"
Install-WingetPackage "Python.Python.3.12" "Python 3.12"
Install-WingetPackage "OpenJS.NodeJS.LTS" "Node.js LTS"
Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
Refresh-ProcessPath

foreach ($command in @("git", "docker", "python", "node", "npm", "ffmpeg", "ffprobe", "nvidia-smi")) {
    Require-Command $command
}

Push-Location $RootDir
try {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        throw ".env was created. Fill its secrets, copy licensed music into assets\audio\bgm, then rerun."
    }
    Assert-Environment (Join-Path $RootDir ".env")

    Write-Step "Installing Python dependencies"
    if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
    $Python = Join-Path $RootDir ".venv\Scripts\python.exe"
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt

    Write-Step "Installing Remotion dependencies (npm ci)"
    npm --prefix video_engine ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }

    $music = Get-ChildItem (Join-Path $RootDir "assets\audio\bgm") -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".mp3", ".wav", ".m4a", ".aac", ".ogg") }
    if (-not $music) {
        Write-Warning "No background music found. Copy licensed tracks to assets\audio\bgm before production."
    } else {
        Write-Host "Background music tracks: $($music.Count)"
    }

    Wait-Docker
    Test-Nvenc

    if (-not $SkipStart) {
        Write-Step "Starting Docker control plane: docker compose up -d --build"
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose startup failed." }
        Wait-ApiReady
    }

    Write-Step "Checking native renderer"
    & $Python scripts\native_render_runner.py --check
    if ($LASTEXITCODE -ne 0) { throw "Native renderer check failed." }

    if ($InstallRunnerService) {
        $action = New-ScheduledTaskAction -Execute $Python -Argument "scripts\native_render_runner.py" -WorkingDirectory $RootDir
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName "Y5ENativeRenderRunner" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
        Start-ScheduledTask -TaskName "Y5ENativeRenderRunner"
        Write-Host "Scheduled task Y5ENativeRenderRunner installed and started."
    } else {
        Write-Host "Setup complete. Test foreground runner:"
        Write-Host "  .\.venv\Scripts\python.exe scripts\native_render_runner.py"
        Write-Host "Then rerun with -InstallRunnerService."
    }
} finally {
    Pop-Location
}
