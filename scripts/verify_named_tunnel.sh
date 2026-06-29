#!/usr/bin/env bash
set -Eeuo pipefail

readonly PUBLIC_HEALTH_URL="https://studio.veo3depzai.io.vn/api/health"

if ! docker compose ps --status running cloudflared | grep -q cloudflared; then
  echo "cloudflared is not running" >&2
  docker compose logs --tail=80 cloudflared || true
  exit 1
fi

if ! curl --fail --silent --show-error --max-time 15 "$PUBLIC_HEALTH_URL" >/dev/null; then
  echo "Public tunnel health check failed: $PUBLIC_HEALTH_URL" >&2
  docker compose logs --tail=80 cloudflared api || true
  exit 1
fi

echo "Named Tunnel healthy: $PUBLIC_HEALTH_URL"
