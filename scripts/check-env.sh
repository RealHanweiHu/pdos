#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
}

for command_name in node python3.12 uv docker; do
  require_command "$command_name"
done

node_version="$(node --version)"
node_major="${node_version#v}"
node_major="${node_major%%.*}"
if ((node_major < 22)); then
  printf 'Node.js 22 or newer is required; found %s\n' "$node_version" >&2
  exit 1
fi

python_version="$(python3.12 -c 'import platform; print(platform.python_version())')"
if [[ "$python_version" != 3.12.* ]]; then
  printf 'Python 3.12 is required; found %s\n' "$python_version" >&2
  exit 1
fi

docker_compose_version="$(docker compose version --short)"
pnpm_version="$(cd "$repository_root/web" && "$repository_root/scripts/pnpm.sh" --version)"
uv_version="$(uv --version | awk '{print $2}')"

printf 'Node.js %s\n' "$node_version"
printf 'Python %s\n' "$python_version"
printf 'pnpm %s\n' "$pnpm_version"
printf 'uv %s\n' "$uv_version"
printf 'Docker Compose %s\n' "$docker_compose_version"
