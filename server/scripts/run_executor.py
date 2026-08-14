"""Run the LLM-enabled Agent execution plane."""

from __future__ import annotations

import os
import time

from app.ai.runtime_factory import configured_agent_runtime


def main() -> int:
    poll_seconds = float(os.environ.get("PDOS_EXECUTOR_POLL_SECONDS", "2"))
    if not 0.1 <= poll_seconds <= 60:
        raise ValueError("executor poll seconds must be between 0.1 and 60")
    with configured_agent_runtime() as runtime:
        while True:
            result = runtime.executor.execute_next()
            if result.status == "idle":
                time.sleep(poll_seconds)
                continue
            print(
                "agent_execution "
                f"run_id={result.run_id} status={result.status} "
                f"error_code={result.error_code or '-'}",
                flush=True,
            )


if __name__ == "__main__":
    raise SystemExit(main())
