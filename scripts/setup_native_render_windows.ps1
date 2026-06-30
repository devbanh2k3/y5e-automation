param(
    [switch]$InstallService
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

Require-Command python
Require-Command node
Require-Command npm
Require-Command ffmpeg
Require-Command ffprobe
Require-Command nvidia-smi

if (-not (Test-Path (Join-Path $RootDir ".env"))) {
    throw "Missing $RootDir\.env; configure it before installing the runner."
}

Write-Host "Checking NVIDIA driver and h264_nvenc..."
nvidia-smi | Out-Host
$Probe = Join-Path $env:TEMP "y5e-nvenc-check.mp4"
ffmpeg -hide_banner -loglevel error -y `
    -f lavfi -i "color=c=black:s=64x64:r=30:d=0.2" `
    -an -c:v h264_nvenc -pix_fmt yuv420p $Probe
Remove-Item $Probe -Force -ErrorAction SilentlyContinue

Write-Host "Installing Remotion dependencies..."
npm --prefix (Join-Path $RootDir "video_engine") install

Write-Host "Checking redis and native runner dependencies..."
Push-Location $RootDir
try {
    python -c "from core.queue import init_queue; import asyncio; asyncio.run(init_queue())"
    python scripts/native_render_runner.py --check
} finally {
    Pop-Location
}

if ($InstallService) {
    $Python = (Get-Command python).Source
    $Action = New-ScheduledTaskAction -Execute $Python -Argument "scripts/native_render_runner.py" -WorkingDirectory $RootDir
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName "Y5ENativeRenderRunner" -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest -Force | Out-Null
    Start-ScheduledTask -TaskName "Y5ENativeRenderRunner"
    Write-Host "Windows task installed: Y5ENativeRenderRunner"
} else {
    Write-Host "Ready. Start runner with:"
    Write-Host "  cd $RootDir; python scripts/native_render_runner.py"
}
