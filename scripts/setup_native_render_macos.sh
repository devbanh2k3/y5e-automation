#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SERVICE=false
if [[ "${1:-}" == "--install-service" ]]; then
  INSTALL_SERVICE=true
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  }
}

require_command python3
require_command node
require_command npm
require_command ffmpeg
require_command ffprobe

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  printf 'Missing %s/.env; configure it before installing the runner.\n' "$ROOT_DIR" >&2
  exit 1
fi

printf 'Checking ffmpeg h264_videotoolbox support...\n'
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i 'color=c=black:s=64x64:r=30:d=0.2' \
  -an -c:v h264_videotoolbox -pix_fmt yuv420p /tmp/y5e-videotoolbox-check.mp4
rm -f /tmp/y5e-videotoolbox-check.mp4

printf 'Installing Remotion dependencies...\n'
npm --prefix "$ROOT_DIR/video_engine" install

printf 'Checking redis and native runner dependencies...\n'
cd "$ROOT_DIR"
python3 -c 'from core.queue import init_queue; import asyncio; asyncio.run(init_queue())'
python3 scripts/native_render_runner.py --check

if [[ "$INSTALL_SERVICE" == true ]]; then
  label="io.veo3depzai.y5e-native-render"
  plist="$HOME/Library/LaunchAgents/$label.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat >"$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>WorkingDirectory</key><string>$ROOT_DIR</string>
  <key>ProgramArguments</key><array><string>$(command -v python3)</string><string>$ROOT_DIR/scripts/native_render_runner.py</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT_DIR/output/native-render-runner.log</string>
  <key>StandardErrorPath</key><string>$ROOT_DIR/output/native-render-runner.err.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$plist"
  printf 'LaunchAgent installed: %s\n' "$label"
else
  printf 'Ready. Start runner with:\n  cd %s && python3 scripts/native_render_runner.py\n' "$ROOT_DIR"
fi
