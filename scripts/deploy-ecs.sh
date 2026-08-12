#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 preflight|build|deploy|status|rollback [environment-file]" >&2
}

action="${1:-}"
env_file="${2:-.env.production}"

if [[ ! "$action" =~ ^(preflight|build|deploy|status|rollback)$ ]]; then
  usage
  exit 2
fi

require_release_files() {
  if [[ ! -f "$env_file" || -L "$env_file" ]]; then
    echo "Deployment refused: environment file must be a regular, non-symlink file" >&2
    return 1
  fi
  if [[ "$(stat -c '%u' "$env_file")" != "$(id -u)" ]] || \
     [[ "$(stat -c '%a' "$env_file")" != "600" ]]; then
    echo "Deployment refused: environment file must be owned by the deploy user with mode 0600" >&2
    return 1
  fi
  for required_file in compose.production.yaml server/Dockerfile web/Dockerfile; do
    if [[ ! -f "$required_file" ]]; then
      echo "Deployment refused: release file is missing: $required_file" >&2
      return 1
    fi
  done
  for command_name in docker curl python3; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      echo "Deployment refused: required command is missing: $command_name" >&2
      return 1
    fi
  done
  docker compose version >/dev/null
}

env_value() {
  python3 - "$env_file" "$1" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
target = sys.argv[2]
matches = []
for raw_line in path.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != target:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    matches.append(value)
if len(matches) != 1:
    raise SystemExit(1)
print(matches[0])
PY
}

compose_config() {
  local -a clean_environment=(env -i "PATH=$PATH" "HOME=$HOME")
  local variable_name
  local variable_value
  for variable_name in \
    DOCKER_CERT_PATH DOCKER_CONFIG DOCKER_CONTEXT DOCKER_HOST DOCKER_TLS_VERIFY \
    XDG_RUNTIME_DIR; do
    variable_value="${!variable_name:-}"
    if [[ -n "$variable_value" ]]; then
      clean_environment+=("$variable_name=$variable_value")
    fi
  done
  if [[ -n "${PDOS_COMPOSE_IMAGE_TAG_OVERRIDE:-}" ]]; then
    clean_environment+=("PDOS_IMAGE_TAG=$PDOS_COMPOSE_IMAGE_TAG_OVERRIDE")
  fi
  "${clean_environment[@]}" docker compose \
    --env-file "$env_file" -f compose.production.yaml "$@"
}

release_identity() {
  image_tag="$(env_value PDOS_IMAGE_TAG)"
  app_port="$(env_value APP_PORT)"
  if [[ ! "$image_tag" =~ ^[0-9a-f]{7,40}$ ]]; then
    echo "Deployment refused: PDOS_IMAGE_TAG must be a git commit SHA" >&2
    return 1
  fi
  if [[ "$app_port" != "3002" ]]; then
    echo "Deployment refused: APP_PORT must remain 3002" >&2
    return 1
  fi
}

require_confirmation() {
  local variable_name="$1"
  local expected="$2"
  local actual="${!variable_name:-}"
  if [[ "$actual" != "$expected" ]]; then
    echo "Production action refused: set $variable_name to $expected after explicit approval" >&2
    return 1
  fi
}

container_preflight() {
  local api_image="pdos-api:${image_tag}"
  docker image inspect "$api_image" >/dev/null
  docker run --rm --read-only --env-file "$env_file" "$api_image" \
    python -m scripts.check_production_env --from-environment
}

preflight_release() {
  require_release_files
  release_identity
  compose_config config --quiet
  container_preflight
  echo "Release preflight passed for image tag ${image_tag}"
}

build_release() {
  require_release_files
  release_identity
  compose_config config --quiet
  compose_config build
  container_preflight
  echo "Release images built and validated for tag ${image_tag}"
}

verify_release() {
  compose_config ps
  curl --fail --silent --show-error \
    "http://127.0.0.1:${app_port}/api/session/status" >/dev/null
  curl --fail --silent --show-error "https://pdos.beepump.net/login" >/dev/null

  local log_file
  log_file="$(mktemp)"
  chmod 600 "$log_file"
  if ! compose_config logs --since 10m --no-color api dispatcher executor web \
      >"$log_file" 2>&1; then
    rm -f "$log_file"
    echo "Release verification failed while reading bounded service logs" >&2
    return 1
  fi
  if grep -Eiq 'Traceback|fatal|panic|permission denied|connection refused' "$log_file"; then
    rm -f "$log_file"
    echo "Release verification found a fatal pattern in bounded service logs" >&2
    return 1
  fi
  rm -f "$log_file"
  echo "Release health and bounded-log verification passed"
}

deploy_release() {
  preflight_release
  require_confirmation PDOS_DEPLOY_CONFIRM "deploy:${image_tag}"
  compose_config run --rm --no-deps migrate
  compose_config run --rm --no-deps api \
    python -m scripts.apply_agent_runtime_security
  compose_config up -d --no-build --wait --no-deps api dispatcher executor
  compose_config up -d --no-build --wait --no-deps web
  verify_release
}

status_release() {
  require_release_files
  release_identity
  compose_config config --quiet
  verify_release
}

rollback_release() {
  require_release_files
  release_identity
  local rollback_tag="${PDOS_ROLLBACK_IMAGE_TAG:-}"
  if [[ ! "$rollback_tag" =~ ^[0-9a-f]{7,40}$ ]]; then
    echo "Rollback refused: PDOS_ROLLBACK_IMAGE_TAG must be a prior git commit SHA" >&2
    return 1
  fi
  require_confirmation PDOS_ROLLBACK_CONFIRM "rollback:${rollback_tag}"
  docker image inspect "pdos-api:${rollback_tag}" "pdos-web:${rollback_tag}" >/dev/null
  PDOS_COMPOSE_IMAGE_TAG_OVERRIDE="$rollback_tag" compose_config \
    up -d --no-deps --no-build --wait api dispatcher executor
  PDOS_COMPOSE_IMAGE_TAG_OVERRIDE="$rollback_tag" compose_config \
    up -d --no-deps --no-build --wait web
  verify_release
}

case "$action" in
  preflight) preflight_release ;;
  build) build_release ;;
  deploy) deploy_release ;;
  status) status_release ;;
  rollback) rollback_release ;;
esac
