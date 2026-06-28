#!/usr/bin/env bash
# Production bootstrap for Ubuntu WSL or Ubuntu Server.
#
# Usage:
#   bash scripts/setup_wsl_production.sh \
#     --repo-url https://github.com/devbanh2k3/y5e-automation.git \
#     --branch main \
#     --project-dir /home/y5e/y5e-automation

set -Eeuo pipefail

REPO_URL="https://github.com/devbanh2k3/y5e-automation.git"
BRANCH="main"
PROJECT_DIR="$HOME/y5e-automation"
SKIP_BUILD=0
SKIP_START=0

log() {
  printf "\n==> %s\n" "$1"
}

die() {
  printf "ERROR: %s\n" "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: setup_wsl_production.sh [options]

Options:
  --repo-url URL       Git repo URL. Default: https://github.com/devbanh2k3/y5e-automation.git
  --branch NAME        Git branch to deploy. Default: main
  --project-dir PATH   Directory inside WSL/Ubuntu. Default: $HOME/y5e-automation
  --skip-build         Do not run docker compose build/start.
  --skip-start         Build/pull source only, do not start services.
  -h, --help           Show help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --skip-start)
      SKIP_START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

install_packages() {
  log "Installing Ubuntu packages"
  if [[ "$(id -u)" -eq 0 ]]; then
    APT_PREFIX=()
  else
    require_command sudo
    APT_PREFIX=(sudo)
  fi
  "${APT_PREFIX[@]}" apt-get update
  "${APT_PREFIX[@]}" apt-get install -y \
    git \
    curl \
    ca-certificates \
    openssl \
    python3 \
    python3-venv
}

ensure_docker_access() {
  log "Checking Docker access"
  require_command docker
  docker version >/dev/null || die "Docker is not reachable from WSL. Enable Docker Desktop WSL integration, then rerun."
  docker compose version >/dev/null || die "Docker Compose v2 is required"
}

sync_repo() {
  log "Syncing source"
  mkdir -p "$(dirname "$PROJECT_DIR")"
  if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$PROJECT_DIR"
  fi
  cd "$PROJECT_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  git status --short --branch
}

ensure_env_file() {
  log "Checking .env"
  cd "$PROJECT_DIR"
  if [[ ! -f .env ]]; then
    cp .env.example .env
    cat <<'EOF'

.env was created from .env.example.
Fill real production values before starting services:
  PRIMARY_API_BASE
  PRIMARY_API_KEY
  PRIMARY_MODEL
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  PUBLIC_BASE_URL
  YOUTUBE_UPLOAD_ENABLED
  YOUTUBE_OAUTH_CLIENT_ID
  YOUTUBE_OAUTH_CLIENT_SECRET
  YOUTUBE_TOKEN_ENCRYPTION_KEY

Generate YOUTUBE_TOKEN_ENCRYPTION_KEY with:
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

EOF
    die ".env is not configured yet"
  fi
}

env_value() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
  printf "%s" "${line#*=}"
}

is_placeholder() {
  local value="$1"
  [[ -z "$value" ]] && return 0
  [[ "$value" == *"your_"* ]] && return 0
  [[ "$value" == *"YOUR_"* ]] && return 0
  [[ "$value" == *"CHANGE_ME"* ]] && return 0
  [[ "$value" == *"localhost:8000"* ]] && return 0
  return 1
}

validate_env() {
  log "Validating production .env"
  cd "$PROJECT_DIR"
  local required=(
    PRIMARY_API_BASE
    PRIMARY_API_KEY
    PRIMARY_MODEL
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    PUBLIC_BASE_URL
    YOUTUBE_UPLOAD_ENABLED
    YOUTUBE_OAUTH_CLIENT_ID
    YOUTUBE_OAUTH_CLIENT_SECRET
    YOUTUBE_TOKEN_ENCRYPTION_KEY
  )
  local missing=()
  for key in "${required[@]}"; do
    value="$(env_value "$key")"
    if is_placeholder "$value"; then
      missing+=("$key")
    fi
  done
  if [[ "${#missing[@]}" -gt 0 ]]; then
    printf "Missing or placeholder env values:\n" >&2
    printf "  - %s\n" "${missing[@]}" >&2
    die "Edit $PROJECT_DIR/.env, then rerun this script"
  fi
  if [[ "$(env_value PUBLIC_BASE_URL)" != https://* ]]; then
    die "PUBLIC_BASE_URL must be a public HTTPS URL for Telegram preview and Google OAuth"
  fi
}

start_stack() {
  log "Starting production Docker stack"
  cd "$PROJECT_DIR"
  mkdir -p output
  if [[ "$SKIP_BUILD" -eq 1 ]]; then
    docker compose up -d api telegram-bot production-worker youtube-upload-worker
  else
    docker compose up -d --build api telegram-bot production-worker youtube-upload-worker
  fi
  docker compose ps
}

health_check() {
  log "Checking API health"
  local attempts=30
  local index=1
  until curl -fsS http://localhost:8000/api/health; do
    if [[ "$index" -ge "$attempts" ]]; then
      docker compose logs --tail=80 api || true
      die "API health check failed"
    fi
    index=$((index + 1))
    sleep 2
  done
  printf "\n"
  curl -fsS http://localhost:8000/api/ready || true
  printf "\n"
}

print_next_steps() {
  cat <<'EOF'

Production setup finished.

Telegram smoke test:
  /start
  /channels
  /create 1 celebrity en flag_hero --duration 90
  /reviews

Useful commands:
  docker compose logs -f telegram-bot
  docker compose logs -f production-worker
  docker compose logs -f youtube-upload-worker
  docker stats

Render scaling after the first successful videos:
  docker compose up -d --scale production-worker=2

EOF
}

install_packages
ensure_docker_access
sync_repo
ensure_env_file
validate_env

if [[ "$SKIP_START" -eq 0 ]]; then
  start_stack
  health_check
fi

print_next_steps
