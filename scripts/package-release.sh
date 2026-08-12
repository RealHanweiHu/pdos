#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
output_directory="${1:-$repository_root/output/releases}"
release_commit="$(git -C "$repository_root" rev-parse --verify 'HEAD^{commit}')"

if [[ ! "$release_commit" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Release packaging refused: ref did not resolve to a full git commit SHA" >&2
  exit 1
fi

mkdir -p "$output_directory"
artifact_path="$output_directory/pdos-${release_commit}.bundle"
if [[ -e "$artifact_path" || -L "$artifact_path" ]]; then
  if [[ ! -f "$artifact_path" || -L "$artifact_path" ]]; then
    echo "Release packaging refused: existing artifact is not a regular file" >&2
    exit 1
  fi
  git -C "$repository_root" bundle verify "$artifact_path" >/dev/null
  existing_head="$(git bundle list-heads "$artifact_path" | awk '$2 == "HEAD" { print $1 }')"
  if [[ "$existing_head" != "$release_commit" ]]; then
    echo "Release packaging refused: existing artifact does not match HEAD" >&2
    exit 1
  fi
  printf '%s\n' "$artifact_path"
  exit 0
fi
temporary_artifact="$(mktemp "$output_directory/.pdos-${release_commit}.XXXXXX")"

cleanup() {
  if [[ -f "$temporary_artifact" && ! -L "$temporary_artifact" ]]; then
    rm -f -- "$temporary_artifact"
  fi
}
trap cleanup EXIT INT TERM

git -C "$repository_root" bundle create "$temporary_artifact" HEAD
git -C "$repository_root" bundle verify "$temporary_artifact" >/dev/null
bundle_head="$(git bundle list-heads "$temporary_artifact" | awk '$2 == "HEAD" { print $1 }')"
if [[ "$bundle_head" != "$release_commit" ]]; then
  echo "Release packaging refused: bundle HEAD does not match the expected commit" >&2
  exit 1
fi
chmod 0640 "$temporary_artifact"
mv -f "$temporary_artifact" "$artifact_path"
trap - EXIT INT TERM
printf '%s\n' "$artifact_path"
