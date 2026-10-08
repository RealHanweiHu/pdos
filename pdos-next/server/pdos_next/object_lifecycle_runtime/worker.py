"""Trusted metadata-over-pipes worker. It emits no original bytes or diagnostics."""

import json
import resource
import sys

from .effects import process


def main():
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (10, 11))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (268_435_456, 268_435_456))
        except (OSError, ValueError):
            # Darwin has no usable address-space rlimit. This trusted metadata
            # worker still has bounded input/records/byte reads and a parent kill
            # deadline; it is not the untrusted-document OS parser sandbox.
            if sys.platform != "darwin":
                raise
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        raw = sys.stdin.buffer.read(32_769)
        if len(raw) > 32_768:
            raise ValueError("Bounded request required")
        response = process(json.loads(raw))
    except Exception:
        response = {"error_code": "LIFECYCLE_STORAGE_UNKNOWN"}
    output = json.dumps(response, ensure_ascii=True, separators=(",", ":"))
    if len(output) > 8_192:
        output = '{"error_code":"LIFECYCLE_PROTOCOL_ERROR"}'
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
