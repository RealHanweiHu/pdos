"""User-visible research evidence is copied from actual tool results, never model counts."""

from copy import deepcopy

from pdos_next.errors import DomainError


def attach(output, tool_results):
    result = deepcopy(output)
    body = result.get("result")
    if not isinstance(body, dict):
        return result
    body.pop("research", None)
    jobs, failed = {}, []
    fields = ("job_id", "status", "ledger", "coverage", "failures", "snapshots")
    for tool in tool_results:
        if tool.get("tool") != "research.fanout" or tool.get("tier") != "READ":
            continue
        value = tool.get("value", {})
        if "error" in value:
            error = value["error"]
            failed.append(
                {
                    "status": "unavailable",
                    "ledger": [],
                    "coverage": [],
                    "snapshots": [],
                    "failures": [
                        {
                            "reason": error.get("code", "SOURCE_UNAVAILABLE"),
                            "message": error.get("message", "研究未完成。"),
                        }
                    ],
                }
            )
            continue
        job = {key: deepcopy(value[key]) for key in fields}
        previous = jobs.get(job["job_id"])
        if previous is not None and previous != job:
            raise DomainError("SOURCE_UNAVAILABLE", "同一研究作业的实际台账不一致。")
        jobs[job["job_id"]] = job
    actual = [*jobs.values(), *failed]
    if actual:
        body["research"] = {
            "version": 1,
            "jobs": actual,
            "source_count": len({row["id"] for job in actual for row in job["snapshots"]}),
            "row_count": len({row["row_id"] for job in actual for row in job["ledger"]}),
        }
        if result.get("status") == "completed" and any(
            job["status"] != "completed" for job in actual
        ):
            result["status"] = "partial"
            note = "研究仍有未读取来源或失败，请核对研究来源与覆盖。"
            result["unfinished"] = [*result.get("unfinished", []), note]
    return result
