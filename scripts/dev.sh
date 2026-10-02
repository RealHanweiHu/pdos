#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
api_pid=""
web_pid=""
reminders_pid=""

cleanup() {
  trap - EXIT INT TERM
  for process_id in "$api_pid" "$web_pid" "$reminders_pid"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  wait "$api_pid" "$web_pid" "$reminders_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(cd "$repository_root/server" && exec uv run --env-file ../.env --python 3.12 uvicorn app.main:app --reload --reload-dir app) &
api_pid="$!"
(cd "$repository_root/web" && exec "$repository_root/scripts/pnpm.sh" dev) &
web_pid="$!"
(cd "$repository_root/server" && exec uv run --env-file ../.env --python 3.12 python -m scripts.run_reminder_scheduler) &
reminders_pid="$!"

printf 'PDOS API pid: %s\n' "$api_pid"
printf 'PDOS web pid: %s\n' "$web_pid"
printf 'PDOS reminders pid: %s\n' "$reminders_pid"

while kill -0 "$api_pid" 2>/dev/null \
    && kill -0 "$web_pid" 2>/dev/null \
    && kill -0 "$reminders_pid" 2>/dev/null; do
  sleep 1
done
