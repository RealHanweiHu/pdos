"""JSON-over-pipes child entry point; imports document libraries only after resource limits."""

import base64
import json
import sys

from .types import ParseFailure, ParseLimits


def _limits(limits: ParseLimits, *, parent_memory_monitored: bool):
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 1))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        except (OSError, ValueError):
            # Darwin rejects an address-space hard limit. Its parent must enforce RSS.
            if sys.platform != "darwin" or not parent_memory_monitored:
                raise
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError) as exc:
        raise ParseFailure(
            "ISOLATION_UNAVAILABLE", "Parser resource boundaries are unavailable"
        ) from exc


def main():
    try:
        # Caller already bounds the input. The extra cap also protects this entry point.
        request = json.loads(sys.stdin.buffer.read(70_000_001))
        limits = ParseLimits(**request["limits"])
        _limits(limits, parent_memory_monitored=request.get("parent_memory_monitored") is True)
        content = base64.b64decode(request["content"], validate=True)
        from .parsers import parse_in_worker

        response = {
            "ok": True,
            "result": parse_in_worker(content, request["media_type"], limits).as_dict(),
        }
    except ParseFailure as exc:
        response = {"ok": False, "error": exc.as_dict()}
    except MemoryError:
        response = {
            "ok": False,
            "error": ParseFailure("RESOURCE_LIMIT", "Parser memory budget was exceeded").as_dict(),
        }
    except Exception:
        response = {
            "ok": False,
            "error": ParseFailure("MALFORMED_DOCUMENT", "Original could not be parsed").as_dict(),
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
