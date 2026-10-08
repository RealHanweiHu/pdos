#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
api_pid=""
web_pid=""
reminders_pid=""
agent_pid=""
api_reload_args=()
case "${PDOS_DEV_API_RELOAD:-true}" in
  true) api_reload_args=(--reload --reload-dir app) ;;
  false) ;;
  *) printf 'PDOS_DEV_API_RELOAD must be true or false\n' >&2; exit 1 ;;
esac

cleanup() {
  trap - EXIT INT TERM
  for process_id in "$api_pid" "$web_pid" "$reminders_pid" "$agent_pid"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  wait "$api_pid" "$web_pid" "$reminders_pid" "$agent_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

(cd "$repository_root/server" && uv run --python 3.12 python -m scripts.agent_runtime_environment start)
(cd "$repository_root/server" && exec uv run --env-file ../.env --python 3.12 python -m app.ai.durable_worker) &
agent_pid="$!"
(cd "$repository_root/server" && exec uv run --env-file ../.env --python 3.12 python -m uvicorn app.main:app ${api_reload_args[@]+"${api_reload_args[@]}"}) &
api_pid="$!"
(cd "$repository_root/web" && exec "$repository_root/scripts/pnpm.sh" dev) &
web_pid="$!"
(cd "$repository_root/server" && exec uv run --env-file ../.env --python 3.12 python -m scripts.run_reminder_scheduler) &
reminders_pid="$!"

printf 'PDOS API pid: %s\n' "$api_pid"
printf 'PDOS web pid: %s\n' "$web_pid"
printf 'PDOS reminders pid: %s\n' "$reminders_pid"
printf 'PDOS Agent runtime pid: %s\n' "$agent_pid"

while kill -0 "$api_pid" 2>/dev/null \
    && kill -0 "$web_pid" 2>/dev/null \
    && kill -0 "$reminders_pid" 2>/dev/null \
    && kill -0 "$agent_pid" 2>/dev/null; do
  sleep 1
done
