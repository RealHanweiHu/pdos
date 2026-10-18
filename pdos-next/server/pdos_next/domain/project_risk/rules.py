"""Internal followup never derives a professional approval or task result."""

from pdos_next.domain.work_management.rules import require


def next_state(payload, basis, *, actor_id, legacy_status, previous=None):
    require(basis["kind"] == "risk", "须引用实际 G0 风险。", "VALIDATION_FAILED", 422)
    require(
        basis["owner_id"] == str(actor_id),
        "只有原 G0 具名跟进人本人可记录风险跟进。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(legacy_status == "open", "原风险状态无法作为此跟进的有效起点。", "VERSION_CONFLICT")
    expected = {"id": str(previous.id), "revision": previous.revision} if previous else None
    actual = payload.current.model_dump(mode="json") if payload.current else None
    require(actual == expected, "风险跟进已续版，请重新核对。", "VERSION_CONFLICT")
    state = previous.state if previous else "open"
    require(
        state in {"open", "closed"}
        and (
            (payload.action == "close" and state == "open")
            or (payload.action == "reopen" and state == "closed")
        ),
        "当前风险跟进状态不支持此动作。",
        "VERSION_CONFLICT",
    )
    return "closed" if payload.action == "close" else "open"
