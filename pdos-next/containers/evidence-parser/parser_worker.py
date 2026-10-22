"""Fixed container entrypoint; no document input is executed as Python or shell code."""

import base64
import json
import math
import resource
import sys

sys.path.insert(0, "/app")

from pdos_next.evidence_processing.types import ParseFailure, ParseLimits


def main():
    try:
        raw = sys.stdin.buffer.read(70_000_001)
        if len(raw) > 70_000_000:
            raise ParseFailure("FILE_TOO_LARGE", "Parser request exceeds its byte limit")
        request = json.loads(raw)
        limits = ParseLimits(**request["limits"])
        for name, value in request["limits"].items():
            if name == "timeout_seconds":
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("Invalid time budget")
            elif type(value) is not int:
                raise ValueError("Invalid integer budget")
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        content = base64.b64decode(request["content"], validate=True)
        from pdos_next.evidence_processing.parsers import parse_in_worker

        response = {
            "ok": True,
            "result": parse_in_worker(content, request["media_type"], limits).as_dict(),
        }
    except ParseFailure as exc:
        response = {"ok": False, "error": exc.as_dict()}
    except MemoryError:
        response = {
            "ok": False,
            "error": ParseFailure("RESOURCE_LIMIT", "Parser exceeded its memory budget").as_dict(),
        }
    except (OSError, ValueError) as exc:
        # Resource boundary setup is never silently ignored.
        code = "ISOLATION_UNAVAILABLE" if isinstance(exc, OSError) else "MALFORMED_DOCUMENT"
        response = {
            "ok": False,
            "error": ParseFailure(code, "Parser could not process the bounded request").as_dict(),
        }
    except Exception:
        response = {
            "ok": False,
            "error": ParseFailure("MALFORMED_DOCUMENT", "Original could not be parsed").as_dict(),
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
