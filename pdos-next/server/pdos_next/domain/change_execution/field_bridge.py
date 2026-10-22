"""Read the native fixed Field owner; no Issue, TestRun or authority is invented."""

from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import Scope


def get(s, ctx, product_id, ref):
    if ref.kind != "field_feedback" or ref.key is not None:
        raise DomainError("FIXED_REFERENCE_MISMATCH", "须引用完整现场反馈固定版本。")
    from pdos_next.domain.field_feedback.owner import get_feedback_for_change

    row, typed = get_feedback_for_change(s, ctx, product_id, ref.id, ref.revision, write=False)
    return _checked(ctx, product_id, ref, row, typed)


def current(s, ctx, product_id, feedback_id):
    """Only GET options may select Current; command references stay exact."""
    from pdos_next.domain.field_feedback.owner import get_feedback_for_change

    row, typed = get_feedback_for_change(s, ctx, product_id, feedback_id, None, write=False)
    return _checked(
        ctx,
        product_id,
        Ref(kind="field_feedback", id=feedback_id, revision=row.revision),
        row,
        typed,
    )


def _checked(ctx, product_id, ref, row, typed):
    view = typed.model_dump(mode="json") if hasattr(typed, "model_dump") else typed
    if (
        row.tenant_id != ctx.tenant_id
        or row.category_id != ctx.category_id
        or row.product_id != product_id
        or row.feedback_id != ref.id
        or row.revision != ref.revision
        or str(view["feedback_id"]) != str(row.feedback_id)
        or str(view["version_id"]) != str(row.id)
        or view["revision"] != row.revision
        or str(view["project_id"]) != str(row.project_id)
    ):
        raise DomainError("FIXED_REFERENCE_MISMATCH", "现场反馈端口未返回指定范围和固定版本。")
    if (
        row.project_id is None
        or not isinstance(view["purpose"], str)
        or not view["purpose"].strip()
        or view["location"]["state"] != "known"
        or view["is_current"] is not True
        or view["source_status"] != "current"
    ):
        raise DomainError("RECHECK_REQUIRED", "现场反馈须有已定位配置、实际项目与用途和当前来源。")
    # Parsing retains exact immutable configuration identities and rejects a
    # malformed owner response; it does not choose a newer configuration.
    configuration_refs(view)
    return (
        row,
        view,
        Scope(tenant_id=ctx.tenant_id, product_id=product_id, project_id=row.project_id),
        view["purpose"],
    )


def configuration_refs(view):
    location = view["location"]
    result = []
    for key, kind in (
        ("engineering_configuration", "engineering_configuration"),
        ("manufacturing_configuration", "manufacturing_configuration"),
    ):
        value = location.get(key)
        if value is None:
            if key == "engineering_configuration":
                raise DomainError("RECHECK_REQUIRED", "已定位反馈缺少实际固定工程配置。")
            continue
        if type(value["revision"]) is not int:
            raise DomainError("FIXED_REFERENCE_MISMATCH", "现场反馈配置须有精确整数版本。")
        result.append(Ref(kind=kind, id=value["id"], revision=value["revision"]))
    return tuple(result)
