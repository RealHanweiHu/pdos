"""An independent promise is fulfilled only by its recipient's exact checks."""

from pdos_next.domain.work_management.rules import require


def review_state(payload, promise, task, submission, *, actor_id, previous=None):
    require(
        actor_id == promise.recipient_id, "只有原承诺接收者本人可核对履行。", "FORBIDDEN_SCOPE", 403
    )
    require(
        task.assignee_id == promise.promisor_id,
        "当前任务责任人与原承诺人不一致。",
        "VERSION_CONFLICT",
    )
    require(
        task.submission is not None and task.submission == submission.submission,
        "须核对当前任务保留的实际成果提交。",
        "VERSION_CONFLICT",
    )
    require(
        payload.expected_review_revision == (previous.revision if previous else 0),
        "履行核对已续版，请重新核对。",
        "VERSION_CONFLICT",
    )
    require(previous is None or previous.state != "fulfilled", "本版承诺已有接收者确认的履行记录。")
    require(
        {check.key for check in payload.checks} == set(promise.outcome_keys),
        "须逐项核对本承诺的全部成果，包括已承诺的可选成果。",
        "VALIDATION_FAILED",
        422,
    )
    if payload.decision == "accepted":
        results = {result.key: result for result in submission.submission.results}
        require(
            all(
                key in results and results[key].status == "present" and results[key].sources
                for key in promise.outcome_keys
            ),
            "承诺成果须全部有实际完整材料。",
        )
        require(
            all(check.decision == "accepted" for check in payload.checks),
            "确认履行须全部成果核对通过。",
        )
        return "fulfilled"
    require(
        any(check.decision != "accepted" for check in payload.checks),
        "退回须保留未通过或未知的核对项。",
    )
    return "open"
