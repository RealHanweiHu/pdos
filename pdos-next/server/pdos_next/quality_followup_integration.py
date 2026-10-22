"""Explicit host wiring, with actual Current request choices and no business writes."""

from types import MappingProxyType

from pydantic import ValidationError
from sqlalchemy import Text, and_, func, or_, select

from pdos_next.domain.capa_verification.commands import configure_consumed_proof
from pdos_next.domain.capa_verification.schemas import OutputRef
from pdos_next.domain.quality_followup.service import configure_followup
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import TestResultActionFact
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.quality_followup_host import append_issue, require_consumed_proof

PAIRED_FORMAL_OPERATIONS = (
    "verification.schedule.promise",
    "test.run.start",
    "test.results.import",
    "test.run.review",
    "test.disposition.decide",
)


def request_options(s, ctx, product_id, basis):
    """Enumerate Current rows; each option still needs its actual business owner."""
    if basis.scope.tenant_id != ctx.tenant_id or basis.scope.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "复验候选不在当前范围。", 403)
    rows = s.scalars(current_formal_options_query(ctx, product_id, basis))
    formals = tuple(
        OutputRef(kind="verification_request", id=row.id, revision=row.revision) for row in rows
    )
    runs = tuple(s.scalars(current_run_options_query(ctx, product_id, basis)))
    return formals + tuple(
        OutputRef(kind="verification_run", id=row.id, revision=row.revision) for row in runs
    )


def current_formal_options_query(ctx, product_id, basis):
    """Direct receipts and supported paired families are distinct actual owner inputs."""
    direct = (
        select(Receipt.id)
        .where(
            Receipt.tenant_id == FormalVerificationRequest.tenant_id,
            Receipt.product_id == FormalVerificationRequest.product_id,
            Receipt.subject_type == "verification_request",
            Receipt.subject_id == FormalVerificationRequest.id,
            Receipt.subject_revision == FormalVerificationRequest.revision,
            Receipt.operation == FormalVerificationRequest.operation,
            Receipt.result["id"].astext == FormalVerificationRequest.id.cast(Text),
            Receipt.result["revision"] == func.to_jsonb(FormalVerificationRequest.revision),
        )
        .exists()
    )
    # A Formal is an aggregate. Several exact current Run actions may legitimately
    # retain that same Formal version; it then cannot identify one paired output.
    # Enumerate the individual Runs instead. Explicit ambiguous Formal reads still
    # fail in the paired owner, and every enumerated option is verified there.
    paired_count = _paired_current_fact_count(VerificationLaunchFact) + _paired_current_fact_count(
        TestResultActionFact
    )
    return (
        select(FormalVerificationRequest)
        .join(
            FormalVerificationCurrent,
            and_(
                FormalVerificationCurrent.tenant_id == FormalVerificationRequest.tenant_id,
                FormalVerificationCurrent.product_id == FormalVerificationRequest.product_id,
                FormalVerificationCurrent.request_id == FormalVerificationRequest.request_id,
                FormalVerificationCurrent.request_version_id == FormalVerificationRequest.id,
                FormalVerificationCurrent.request_revision == FormalVerificationRequest.revision,
            ),
        )
        .where(
            FormalVerificationRequest.tenant_id == ctx.tenant_id,
            FormalVerificationRequest.product_id == product_id,
            FormalVerificationRequest.project_id == basis.scope.project_id,
            or_(
                direct,
                and_(
                    FormalVerificationRequest.operation.in_(PAIRED_FORMAL_OPERATIONS),
                    paired_count == 1,
                ),
            ),
        )
        .order_by(FormalVerificationRequest.created_at.desc(), FormalVerificationRequest.id)
    )


def _paired_current_fact_count(model):
    formal, current = FormalVerificationRequest, VerificationRunCurrent
    version, revision = (
        (model.run_version_id, model.run_revision)
        if model is VerificationLaunchFact
        else (model.next_run_version_id, model.next_run_revision)
    )
    return (
        select(func.count())
        .select_from(model)
        .join(
            current,
            and_(
                current.tenant_id == model.tenant_id,
                current.product_id == model.product_id,
                current.request_id == model.request_id,
                current.run_id == model.run_id,
                current.run_version_id == version,
                current.run_revision == revision,
            ),
        )
        .where(
            model.tenant_id == formal.tenant_id,
            model.product_id == formal.product_id,
            model.project_id == formal.project_id,
            model.build_id == formal.build_id,
            model.request_id == formal.request_id,
            model.next_request_version_id == formal.id,
            model.next_request_revision == formal.revision,
        )
        .correlate(formal)
        .scalar_subquery()
    )


def current_run_options_query(ctx, product_id, basis):
    """Actual SQL binding all Current keys and the exact canonical Run receipt."""
    row, current = VerificationRunVersion, VerificationRunCurrent
    return (
        select(row)
        .join(
            current,
            and_(
                current.tenant_id == row.tenant_id,
                current.product_id == row.product_id,
                current.request_id == row.request_id,
                current.run_id == row.run_id,
                current.run_version_id == row.id,
                current.run_revision == row.revision,
            ),
        )
        .where(
            row.tenant_id == ctx.tenant_id,
            row.product_id == product_id,
            row.project_id == basis.scope.project_id,
            select(Receipt.id)
            .where(
                Receipt.tenant_id == row.tenant_id,
                Receipt.product_id == row.product_id,
                Receipt.subject_type == "test_run",
                Receipt.subject_id == row.id,
                Receipt.subject_revision == row.revision,
                Receipt.operation == row.operation,
                Receipt.result["id"].astext == row.id.cast(Text),
                Receipt.result["revision"] == func.to_jsonb(row.revision),
            )
            .exists(),
        )
        .order_by(row.created_at.desc(), row.id)
    )


def _link_proof(s, ctx, command, product, payload):
    if product.id != command.product_id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "共同回链证明不在当前范围。", 403)
    return require_consumed_proof(s, ctx, command, payload, tier="T1")


def _completion_profiles(engine, profiles):
    """Explicit startup whitelist; scope facts still come from the real caller UOW.

    This registry selects a configured classifier, never a professional grant or
    a saved positive assessment. Every call invokes the existing actual source
    and classification checks. Identical existing publications are not reissued.
    """
    from pdos_next import quality_followup_bootstrap as bootstrap

    if type(profiles) is not list or not profiles:
        raise DomainError(
            "COMPLETION_PROFILE_CONFIG_INVALID", "多范围调查配置须为非空明确列表。", 422
        )
    try:
        parsed = tuple(
            bootstrap.CompletionProfile.model_validate(
                value.model_dump(mode="json")
                if isinstance(value, bootstrap.CompletionProfile)
                else value
            )
            for value in profiles
        )
    except (ValidationError, TypeError, ValueError):
        raise DomainError(
            "COMPLETION_PROFILE_CONFIG_INVALID", "调查分类配置缺少完整固定范围或出处。", 422
        ) from None
    keys = tuple(bootstrap._scope(value) for value in parsed)
    if len(set(keys)) != len(keys):
        raise DomainError("COMPLETION_PROFILE_CONFLICT", "同一精确范围不能有多个签发配置。")
    issued = [
        (*key, entry.issue_id, entry.capa_id, entry.action_id, entry.executor_id, entry.purpose)
        for key, value in zip(keys, parsed, strict=True)
        for entry in value.entries
    ]
    if len(set(issued)) != len(issued):
        raise DomainError("COMPLETION_PROFILE_CONFLICT", "精确措施签发key不能重复。")
    registry = getattr(engine, "_pdos_quality_completion_profiles", {})
    epochs = getattr(engine, "_pdos_quality_completion_profile_epochs", {})
    if type(registry) is not dict or type(epochs) is not dict:
        raise DomainError("COMPLETION_PROFILE_CONFLICT", "现有调查签发注册表不能完整核对。")
    # Validate the whole batch, including existing bindings, before publishing
    # any new scope. Never replace or broaden a previously registered profile.
    for key, value in zip(keys, parsed, strict=True):
        existing = registry.get(key)
        if key in registry and (
            type(existing) is not bootstrap._Profile
            or bootstrap._scope(existing.data) != key
            or existing.data != value
            or type(existing.epoch) is not int
            or existing.epoch <= 0
            or epochs.get(key) != existing.epoch
        ):
            raise DomainError("COMPLETION_PROFILE_CONFLICT", "现有范围的完整签发配置发生冲突。")
    # The actual registrar replaces only these two attributes with copied maps.
    # Preserve the original objects and absent-attribute state across the whole
    # startup batch; no new runtime is installed until this helper returns.
    absent = object()
    previous = tuple(
        (name, getattr(engine, name, absent))
        for name in (
            "_pdos_quality_completion_profiles",
            "_pdos_quality_completion_profile_epochs",
        )
    )
    try:
        bootstrap.verify_test_target(engine)
        configured = {}
        for key, value in zip(keys, parsed, strict=True):
            if key not in registry:
                bootstrap.configure_local_profile(engine, value)
            actual = engine._pdos_quality_completion_profiles.get(key)
            if type(actual) is not bootstrap._Profile or actual.data != value:
                raise DomainError(
                    "COMPLETION_PROFILE_CONFLICT", "实际调查签发注册结果不能精确核对。"
                )
            configured[key] = actual
        selected = MappingProxyType(configured)
    except BaseException:
        for name, original in previous:
            if original is absent:
                if hasattr(engine, name):
                    delattr(engine, name)
            else:
                setattr(engine, name, original)
        raise

    def assess(
        s, ctx, product_id, basis, action, completion, *, policy_snapshot, observation, write=False
    ):
        from pdos_next.service import Context

        if (
            not isinstance(ctx, Context)
            or not callable(getattr(s, "get_bind", None))
            or s.get_bind() is not engine
            or ctx.run_id is not None
            or ctx.actor_id != ctx.requester_id
            or basis.scope.tenant_id != ctx.tenant_id
            or basis.scope.product_id != product_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "调查核对须实际宿主会话与具名本人精确范围。", 403)
        key = ctx.tenant_id, product_id, basis.scope.project_id
        actual = selected.get(key)
        if actual is None:
            raise DomainError(
                "COMPLETION_PROFILE_SCOPE_MISSING", "当前精确范围未配置本地调查签发依据。", 503
            )
        bootstrap._active(engine, actual)
        if getattr(engine, "_pdos_quality_completion_profile_epochs", {}).get(key) != actual.epoch:
            raise DomainError("SOURCE_STALE", "实际调查签发epoch已改变。")
        result = bootstrap._assess(
            actual,
            engine,
            s,
            ctx,
            product_id,
            basis,
            action,
            completion,
            policy_snapshot,
            observation,
        )
        bootstrap._active(engine, actual)
        if getattr(engine, "_pdos_quality_completion_profile_epochs", {}).get(key) != actual.epoch:
            raise DomainError("SOURCE_STALE", "核对期间实际调查签发epoch已改变。")
        return result

    return assess


def configure_integration(
    engine, *, synthetic_completion_profile=None, synthetic_completion_profiles=None
):
    """Install only shared UOW assertions; optional classification is host explicit."""
    from pdos_next.quality_followup_views import configure_output_options

    if synthetic_completion_profile is not None and synthetic_completion_profiles is not None:
        raise DomainError(
            "COMPLETION_PROFILE_CONFIG_INVALID", "调查分类single与plural配置不能同时提供。", 422
        )
    assessment = None
    if synthetic_completion_profile is not None:
        from pdos_next.quality_followup_bootstrap import configure_local_profile

        assessment = configure_local_profile(engine, synthetic_completion_profile)
    elif synthetic_completion_profiles is not None:
        assessment = _completion_profiles(engine, synthetic_completion_profiles)
    configure_followup(
        engine,
        append_issue=append_issue,
        consumed_proof=require_consumed_proof,
        assess_action_completion=assessment,
    )
    configure_consumed_proof(engine, _link_proof)
    configure_output_options(
        engine,
        request_options,
    )
