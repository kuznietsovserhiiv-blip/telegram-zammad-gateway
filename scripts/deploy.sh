#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
DEFAULT_GATEWAY_URL="http://localhost:8090"
DEFAULT_ZAMMAD_URL="http://localhost:3000"

if [[ ! -f "$PROJECT_DIR/.env.example" ]]; then
  echo ".env.example was not found in $PROJECT_DIR" >&2
  exit 1
fi

if [[ -f "$ENV_FILE" ]]; then
  read -r -p ".env already exists. Overwrite it? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }
fi

prompt_required() {
  local name="$1" default="${2:-}" value=""
  if [[ -n "$default" ]]; then
    read -r -p "$name [$default]: " value
    value="${value:-$default}"
  else
    while [[ -z "$value" ]]; do
      read -r -s -p "$name: " value
      echo
    done
  fi
  printf '%s=%s\n' "$name" "$value"
}

prompt_optional() {
  local name="$1" default="$2" value
  read -r -p "$name [$default]: " value
  printf '%s=%s\n' "$name" "${value:-$default}"
}

umask 077
read -r -p "Public Gateway URL [$DEFAULT_GATEWAY_URL]: " GATEWAY_URL
GATEWAY_URL="${GATEWAY_URL:-$DEFAULT_GATEWAY_URL}"
GATEWAY_URL="${GATEWAY_URL%/}"
read -r -p "Zammad URL [$DEFAULT_ZAMMAD_URL]: " ZAMMAD_URL
ZAMMAD_URL="${ZAMMAD_URL:-$DEFAULT_ZAMMAD_URL}"
ZAMMAD_URL="${ZAMMAD_URL%/}"

{
  echo "APP_ENV=production"
  echo "LOG_LEVEL=INFO"
  echo "DATABASE_URL=sqlite:////data/gateway.db"
  echo "PUBLIC_BASE_URL=$GATEWAY_URL"
  echo "ALLOWED_ORIGINS=$GATEWAY_URL"
  prompt_required TELEGRAM_BOT_USERNAME
  prompt_required TELEGRAM_BOT_TOKEN
  prompt_required TELEGRAM_WEBHOOK_SECRET
  echo "LINK_TOKEN_TTL_SECONDS=600"
  echo "WEBHOOK_MAX_BODY_BYTES=1048576"
  echo "EVENT_RETENTION_DAYS=30"
  echo "ZAMMAD_BASE_URL=$ZAMMAD_URL"
  prompt_optional ZAMMAD_VERIFY_TLS true
  echo "ZAMMAD_REQUEST_TIMEOUT_SECONDS=10"
  prompt_required ZAMMAD_API_TOKEN
  prompt_required ZAMMAD_WEBHOOK_SECRET
  prompt_required ZAMMAD_SERVICE_USER_ID 0
  prompt_optional ZAMMAD_ADMIN_ROLE_ID 1
  prompt_optional ZAMMAD_AGENT_ROLE_ID 2
  prompt_optional ZAMMAD_CUSTOMER_ROLE_ID 3
  prompt_optional GATEWAY_BIND_IP 0.0.0.0
  prompt_optional GATEWAY_PORT 8090
} > "$ENV_FILE"

cd "$PROJECT_DIR"
echo "Building and starting the Gateway..."
docker compose up -d --build --force-recreate
docker compose ps

health_url="http://127.0.0.1:${GATEWAY_PORT:-8090}/healthz"
echo "Checking $health_url ..."
curl --fail --silent --show-error "$health_url"
echo
echo "Deployment complete."
