#!/usr/bin/env bash
set -euo pipefail

expected_commit="${1:-}"
if [[ ! "$expected_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Release source refused: expected commit must be a full git SHA" >&2
  exit 1
fi
if [[ ! -d .git ]]; then
  echo "Release source refused: directory was not cloned from a git bundle" >&2
  exit 1
fi

release_commit="$(git rev-parse --verify 'HEAD^{commit}')"
if [[ "$release_commit" != "$expected_commit" ]]; then
  echo "Release source refused: git HEAD does not match the expected commit" >&2
  exit 1
fi

release_status="$(git status --porcelain=v1 --untracked-files=all --ignored)"
while IFS= read -r status_line; do
  if [[ -z "$status_line" ]]; then
    continue
  fi
  status_path="${status_line:3}"
  if [[ "$status_path" == ".env.production" && \
        ( "${status_line:0:2}" == "??" || "${status_line:0:2}" == "!!" ) ]]; then
    continue
  fi
  echo "Release source refused: git tree contains modified or extra files" >&2
  exit 1
done <<<"$release_status"

printf '%s\n' 'Release source commit and file inventory verified'
