#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
smoke_log_dir="$(mktemp -d "${TMPDIR:-/tmp}/pdos-s0-1-smoke.XXXXXX")"
api_pid=""
web_pid=""
test_database_url="$(
  cd "$repository_root/server"
  uv run --python 3.12 python -c \
    'from app.db.test_safety import configured_test_database_url; print(configured_test_database_url())'
)"

cleanup() {
  trap - EXIT INT TERM
  for process_id in "$api_pid" "$web_pid"; do
    if [[ -n "$process_id" ]]; then
      pkill -TERM -P "$process_id" 2>/dev/null || true
      kill "$process_id" 2>/dev/null || true
    fi
  done
  wait "$api_pid" "$web_pid" 2>/dev/null || true
  rm -rf "$smoke_log_dir"
}

show_logs() {
  printf '%s\n' '--- API smoke log ---' >&2
  sed -n '1,160p' "$smoke_log_dir/api.log" >&2 || true
  printf '%s\n' '--- Web smoke log ---' >&2
  sed -n '1,160p' "$smoke_log_dir/web.log" >&2 || true
}

wait_for_url() {
  local url="$1"
  for attempt in {1..30}; do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$api_pid" 2>/dev/null || ! kill -0 "$web_pid" 2>/dev/null; then
      show_logs
      return 1
    fi
    sleep 1
  done
  show_logs
  printf 'Timed out waiting for %s\n' "$url" >&2
  return 1
}

trap cleanup EXIT INT TERM
trap show_logs ERR

(cd "$repository_root/server" && DATABASE_URL="$test_database_url" exec uv run --python 3.12 uvicorn app.main:app --host 127.0.0.1 --port 8800) >"$smoke_log_dir/api.log" 2>&1 &
api_pid="$!"
(cd "$repository_root/web" && PDOS_API_INTERNAL_URL=http://127.0.0.1:8800 exec "$repository_root/scripts/pnpm.sh" dev --hostname 127.0.0.1 --port 3300) >"$smoke_log_dir/web.log" 2>&1 &
web_pid="$!"

wait_for_url http://127.0.0.1:8800/healthz
wait_for_url http://127.0.0.1:3300/
wait_for_url http://127.0.0.1:3300/login

health_response="$(curl --fail --silent --show-error http://127.0.0.1:8800/healthz)"
if [[ "$health_response" != '{"status":"ok","service":"pdos-api","version":"0.1.0"}' ]]; then
  printf 'Unexpected API health response: %s\n' "$health_response" >&2
  exit 1
fi

web_response="$(curl --fail --silent --show-error http://127.0.0.1:3300/)"
if [[ "$web_response" != *'<title>PDOS · 产品开发操作系统</title>'* ]]; then
  printf '%s\n' 'Web smoke response did not contain the expected title' >&2
  exit 1
fi

login_response="$(curl --fail --silent --show-error http://127.0.0.1:3300/login)"
if [[ "$login_response" != *'<title>登录 · PDOS</title>'* ]]; then
  printf '%s\n' 'Login smoke response did not contain the expected title' >&2
  exit 1
fi

session_status="$(curl --fail --silent --show-error http://127.0.0.1:3300/api/session/status)"
if [[ "$session_status" != '{"needs_setup":true}' && "$session_status" != '{"needs_setup":false}' ]]; then
  printf 'Unexpected same-origin session status response: %s\n' "$session_status" >&2
  exit 1
fi

printf '%s\n' 'Application smoke passed: web, login BFF, and API returned expected responses'
