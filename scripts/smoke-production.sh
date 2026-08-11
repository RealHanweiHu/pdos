#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
compose_project="pdos-s0-production-smoke"
smoke_port="3302"
test_database_url="$(
  cd "$repository_root/server"
  uv run --python 3.12 python -c \
    'from app.db.test_safety import configured_test_database_url; from sqlalchemy.engine import make_url; print(make_url(configured_test_database_url()).set(host="host.docker.internal").render_as_string(hide_password=False))'
)"

export APP_PORT="$smoke_port"
export DATABASE_URL="$test_database_url"
export JWT_ACCESS_TOKEN_MINUTES=30
export JWT_AUDIENCE=pdos-production-smoke
export JWT_ISSUER=pdos-production-smoke
export JWT_SECRET=test-only-production-smoke-secret-32-bytes
export PDOS_IMAGE_TAG=smoke
export PDOS_NODE_BASE_IMAGE="${PDOS_NODE_BASE_IMAGE:-node:22.22.0-bookworm-slim}"
export PDOS_PYTHON_BASE_IMAGE="${PDOS_PYTHON_BASE_IMAGE:-python:3.12.10-slim-bookworm}"
export PDOS_UV_BASE_IMAGE="${PDOS_UV_BASE_IMAGE:-ghcr.io/astral-sh/uv:0.11.7}"

compose=(
  docker compose
  --project-name "$compose_project"
  --file "$repository_root/compose.production.yaml"
  --file "$repository_root/compose.production-smoke.yaml"
)

show_logs() {
  "${compose[@]}" logs --no-color --tail 160 >&2 || true
}

cleanup() {
  trap - EXIT INT TERM
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}

assert_security_headers() {
  local url="$1"
  local headers
  headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null "$url")"
  for header_name in content-security-policy permissions-policy referrer-policy strict-transport-security x-content-type-options x-frame-options; do
    if ! grep --ignore-case --quiet "^${header_name}:" <<<"$headers"; then
      printf 'Missing production security header %s on %s\n' "$header_name" "$url" >&2
      return 1
    fi
  done
}

trap cleanup EXIT INT TERM
trap show_logs ERR

"${compose[@]}" config --quiet
"${compose[@]}" up --build --detach --wait --wait-timeout 240

login_response="$(curl --fail --silent --show-error "http://127.0.0.1:${smoke_port}/login")"
if [[ "$login_response" != *'<title>登录 · PDOS</title>'* ]]; then
  printf '%s\n' 'Production image login response did not contain the expected title' >&2
  exit 1
fi
assert_security_headers "http://127.0.0.1:${smoke_port}/login"

session_status="$(curl --fail --silent --show-error "http://127.0.0.1:${smoke_port}/api/session/status")"
if [[ "$session_status" != '{"needs_setup":true}' && "$session_status" != '{"needs_setup":false}' ]]; then
  printf 'Unexpected production image session status response: %s\n' "$session_status" >&2
  exit 1
fi

if [[ "$("${compose[@]}" exec -T api id -u)" != "10001" ]]; then
  printf '%s\n' 'Production API image is not running as the pdos user' >&2
  exit 1
fi

if [[ "$("${compose[@]}" exec -T web id -u)" != "1001" ]]; then
  printf '%s\n' 'Production web image is not running as the nextjs user' >&2
  exit 1
fi

printf '%s\n' 'Production container smoke passed: migrate, API, web, BFF, and non-root users verified'
