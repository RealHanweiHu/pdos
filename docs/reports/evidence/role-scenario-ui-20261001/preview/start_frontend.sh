#!/bin/sh
set -eu
preview_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_dir=$(CDPATH= cd -- "$preview_dir/../../../../.." && pwd)
cd "$preview_dir/frontend"
exec env -i PATH="$PATH" \
  PDOS_API_INTERNAL_URL='http://127.0.0.1:8894' NEXT_TELEMETRY_DISABLED=1 \
  node "$repository_dir/web/node_modules/next/dist/bin/next" dev --webpack --hostname 127.0.0.1 --port 3024
