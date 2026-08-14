#!/usr/bin/env bash
set -euo pipefail

if command -v pnpm >/dev/null 2>&1; then
  exec pnpm "$@"
fi

if command -v corepack >/dev/null 2>&1; then
  exec corepack pnpm "$@"
fi

printf 'Missing required package manager: install pnpm or enable Corepack\n' >&2
exit 1
