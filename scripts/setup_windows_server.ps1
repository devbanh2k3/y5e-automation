<#
Production bootstrap for a new Windows PC.

Run in an elevated PowerShell terminal:
  Set-ExecutionPolicy -Scope Process Bypass -Force
  .\scripts\setup_windows_server.ps1 -InstallTools

This script prepares Windows/WSL and then runs scripts/setup_wsl_production.sh
inside Ubuntu. It does not write secrets and it does not overwrite .env.
#>

[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$WslProjectDir = "/home/y5e/y5e-automation",
    [string]$RepoUrl = "https://github.com/devbanh2k3/y5e-automation.git",
    [string]$Branch = "main",
    [switch]$InstallTools,
    [switch]$SkipWslDeploy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
        throw "Run PowerShell as Administrator."
    }
}

function Enable-WindowsFeatures {
    Write-Step "Checking WSL/Virtual Machine Platform features"
    $features = @(
        "Microsoft-Windows-Subsystem-Linux",
        "VirtualMachinePlatform"
    )
    foreach ($feature in $features) {
        $state = (dism.exe /online /Get-FeatureInfo /FeatureName:$feature | Select-String "State :").ToString()
        if ($state -notmatch "Enabled") {
            Write-Host "Enabling $feature"
            dism.exe /online /Enable-Feature /FeatureName:$feature /All /NoRestart | Out-Host
        }
    }
}

function Install-WithWinget {
    param(
        [string]$Id,
        [string]$Name
    )
    if (-not (Test-Command "winget")) {
        throw "winget is required to install $Name automatically. Install App Installer from Microsoft Store or install $Name manually."
    }
    Write-Host "Installing $Name with winget"
    winget install --id $Id --exact --accept-package-agreements --accept-source-agreements
}

function Ensure-DockerDesktop {
    Write-Step "Checking Docker Desktop"
    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerExe)) {
        if (-not $InstallTools) {
            throw "Docker Desktop is missing. Re-run with -InstallTools or install Docker Desktop manually."
        }
        Install-WithWinget -Id "Docker.DockerDesktop" -Name "Docker Desktop"
        Write-Host "Docker Desktop was installed. Open Docker Desktop once, enable WSL integration for $Distro, then re-run this script."
        exit 0
    }
    if (-not (Test-Command "docker")) {
        Write-Host "Docker CLI is not on PATH yet. Starting Docker Desktop."
        Start-Process $dockerExe
        throw "Docker Desktop started. Wait until Docker is running, then re-run this script."
    }
    docker version | Out-Host
}

function Ensure-Git {
    Write-Step "Checking Git for Windows"
    if (-not (Test-Command "git")) {
        if (-not $InstallTools) {
            throw "Git is missing. Re-run with -InstallTools or install Git manually."
        }
        Install-WithWinget -Id "Git.Git" -Name "Git"
    }
}

function Ensure-WslDistro {
    Write-Step "Checking WSL distro $Distro"
    wsl --set-default-version 2 | Out-Host
    $distros = wsl -l -q
    if ($distros -notcontains $Distro) {
        Write-Host "Installing $Distro"
        wsl --install -d Ubuntu-24.04
        Write-Host "Finish the Ubuntu first-run user setup, then re-run this script."
        exit 0
    }
}

function Invoke-WslDeploy {
    Write-Step "Running WSL production setup"
    $windowsRepo = (Resolve-Path ".").Path
    $wslRepo = (wsl wslpath -a "$windowsRepo").Trim()
    $scriptPath = "$wslRepo/scripts/setup_wsl_production.sh"
    $cmd = "bash '$scriptPath' --repo-url '$RepoUrl' --branch '$Branch' --project-dir '$WslProjectDir'"
    wsl -d $Distro -- bash -lc $cmd
}

Assert-Administrator
Enable-WindowsFeatures
Ensure-Git
Ensure-WslDistro
Ensure-DockerDesktop

Write-Step "Important manual Docker setting"
Write-Host "Open Docker Desktop -> Settings -> Resources -> WSL Integration."
Write-Host "Enable integration for $Distro before running production jobs."

Write-Step "Important .env values"
Write-Host "The WSL installer will create .env if missing, but you must fill:"
Write-Host "PRIMARY_API_BASE, PRIMARY_API_KEY, PRIMARY_MODEL"
Write-Host "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PUBLIC_BASE_URL"
Write-Host "YOUTUBE_UPLOAD_ENABLED, YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET"
Write-Host "YOUTUBE_TOKEN_ENCRYPTION_KEY"

if (-not $SkipWslDeploy) {
    Invoke-WslDeploy
}

Write-Step "Windows bootstrap complete"
Write-Host "Use Telegram: /start, /channels, /create 1 celebrity en flag_hero --duration 90"
