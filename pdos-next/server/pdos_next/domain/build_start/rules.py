"""Small execution guards; supply and resource calculations belong to their existing cores."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from pdos_next.errors import DomainError

STATES = frozenset({"UNKNOWN", "BLOCKED", "READY_WITH_CONDITIONS", "READY"})
NON_WAIVABLE = (
    "source_integrity_and_current_authorization",
    "fixed_configuration_and_quantity_scope",
    "named_professional_authority",
    "material_identity_and_quality_release",
    "resource_acceptance_calibration_and_qualification",
    "complete_atomic_material_and_resource_reservation",
)
EXPLORATION_BOUNDARY = {
    "allowed": False,
    "reason": "本版无已批准的用途限定探索例外；未知不作为通过，不支持通用绕过。",
    "required_typed_fields": [
        "allowed_purpose",
        "specific_rule_ids",
        "risk_controls",
        "execution_limits",
        "responsible_named_role",
        "valid_until",
        "exact_evidence",
    ],
    "non_waivable": list(NON_WAIVABLE),
}
CONTROLS = frozenset(
    {
        "no_test_run_or_sample_qualification",
        "no_external_delivery",
        "retain_traceable_outputs",
        "stop_on_configuration_deviation",
    }
)
PROFESSIONAL_RULES = {
    "engineering": ("product_definition_applicability", "verification_objective_applicability"),
    "manufacturing": ("process_configuration_applicability", "output_disposition_applicability"),
}


def readiness_result(operational, *, build_type, purpose):
    """Pending professional review stays unknown; it is separate from nonwaivable facts."""
    result = dict(operational)
    state = operational.get("state")
    if state not in STATES:
        raise DomainError("INTEGRITY_MISMATCH", "操作事实状态无法核对。")
    result["operational_state"] = state
    result["candidate_ready"] = state == "READY" and build_type in {"prototype", "tool_trial"}
    result["state"] = "BLOCKED" if state == "BLOCKED" else "UNKNOWN"
    result["template"] = "internal-build-manufacturing.v1"
    result["accepted_controls_required"] = sorted(CONTROLS)
    checks = []
    for check in operational.get("checks", []):
        checks.append(
            {
                **check,
                "rule_version": "v1",
                "severity": "hard",
                "waivable": False,
                "responsible_role": "supply"
                if "material" in check.get("dimension", "")
                else "manufacturing",
                "allowed_purpose": purpose,
                "freshness": "current",
                "source": operational.get("fact_refs", []),
            }
        )
    for role, rules in PROFESSIONAL_RULES.items():
        for rule in rules:
            checks.append(
                {
                    "dimension": "product_verification"
                    if role == "engineering"
                    else (
                        "delivery_applicability"
                        if rule == "output_disposition_applicability"
                        else "manufacturing_applicability"
                    ),
                    "code": rule,
                    "status": "UNKNOWN",
                    "detail": "等待固定用途与执行范围的具名专业评审。",
                    "rule_version": "v1",
                    "severity": "hard",
                    "waivable": False,
                    "responsible_role": role,
                    "allowed_purpose": purpose,
                    "source": [],
                    "freshness": "not_reviewed",
                }
            )
    if build_type == "pilot":
        checks.append(
            {
                "dimension": "manufacturing_applicability",
                "code": "PILOT_MANUFACTURING_BASELINE_UNCONNECTED",
                "status": "UNKNOWN",
                "detail": "量产试运行的真实制造基线端口未接通，不可用人工适用性声明替代。",
                "rule_version": "v1",
                "severity": "hard",
                "waivable": False,
                "responsible_role": "manufacturing",
                "allowed_purpose": purpose,
                "source": [],
                "freshness": "unknown",
            }
        )
    for code, detail in (
        (
            "TEST_RUN_METHOD_OUTSIDE_MANUFACTURING_SCOPE",
            "本固定模板仅制造试制，不启动TestRun或确认样件测试资格。",
        ),
        (
            "EXTERNAL_DELIVERY_OUTSIDE_MANUFACTURING_SCOPE",
            "本固定模板不批准真实外部交付、客户接收或正式外发。",
        ),
    ):
        checks.append(
            {
                "dimension": "product_verification"
                if code.startswith("TEST")
                else "delivery_applicability",
                "code": code,
                "status": "NOT_APPLICABLE",
                "detail": detail,
                "rule_version": "v1",
                "severity": "hard",
                "waivable": False,
                "responsible_role": "engineering" if code.startswith("TEST") else "manufacturing",
                "allowed_purpose": purpose,
                "source": [{"kind": "server_rule", "id": "internal-build-manufacturing.v1"}],
                "freshness": "fixed_server_rule",
            }
        )
    result["checks"] = checks
    return result


def require_candidate(result):
    if result.get("candidate_ready") is not True or result.get("operational_state") != "READY":
        raise DomainError(
            "BUILD_NOT_REVIEWABLE",
            "物料、资源、范围或制造基线仍有不可豁免的阻塞或未知，不能用专业声明绕过。",
            409,
        )


def validate_professional_review(payload, role, scope, at):
    if payload.action != "approve":
        return
    if set(payload.accepted_controls) != CONTROLS:
        raise DomainError(
            "EXECUTION_CONTROLS_REQUIRED", "须具名接受固定制造用途的全部四项执行约束。", 422
        )
    reviews = {item.rule_id: item for item in payload.professional_assessments}
    if set(reviews) != set(PROFESSIONAL_RULES[role]):
        raise DomainError(
            "PROFESSIONAL_REVIEW_INCOMPLETE", "本专业必须逐项核对固定范围的全部适用性规则。", 422
        )
    for review in reviews.values():
        if review.status != "applicable" or not review.sources:
            raise DomainError(
                "PROFESSIONAL_REVIEW_NOT_APPLICABLE",
                "未知或阻塞的专业适用项不能批准，须提供精确适用依据。",
                409,
            )
        if review.valid_until is not None and (
            review.valid_until <= at or review.valid_until < scope.window_end
        ):
            raise DomainError(
                "PROFESSIONAL_REVIEW_EXPIRED",
                "明确限定期限的专业适用结论须有效并覆盖固定执行范围。",
                409,
            )


def validate_scope(build, scope):
    if Decimal(str(build.planned_quantity)) != scope.quantity or build.unit != scope.unit:
        raise DomainError(
            "EXECUTION_SCOPE_MISMATCH",
            "执行数量与单位必须精确等于固定计划，本版不缩量重算需求。",
            409,
        )


def require_ready(result, at):
    if result.get("state") not in STATES:
        raise DomainError("INTEGRITY_MISMATCH", "执行评估状态无法核对。")
    if result["state"] != "READY":
        raise DomainError(
            "BUILD_NOT_READY", "执行评估有阻塞、未知或未批准的限定条件，不能批准或开工。", 409
        )


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate field")
        value[key] = item
    return value


def validate_start_event(quote, *, build_id, scope, engineering_id, manufacturing_id, occurred_at):
    """Event line is a strict JSON object, not a free quote asserting an unrelated fact."""
    try:
        value = json.loads(quote, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {
            "build_id",
            "occurred_at",
            "purpose",
            "engineering_configuration_id",
            "manufacturing_configuration_id",
        }:
            raise ValueError("event shape")
        instant = datetime.fromisoformat(value["occurred_at"])
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("event timezone")
        matches = (
            value["build_id"] == str(build_id)
            and value["purpose"] == scope.purpose
            and value["engineering_configuration_id"] == str(engineering_id)
            and value["manufacturing_configuration_id"] == str(manufacturing_id)
            and instant.astimezone(UTC) == occurred_at
        )
        if not matches:
            raise ValueError("event binding")
    except (ValueError, TypeError, KeyError):
        raise DomainError(
            "START_EVENT_MISMATCH",
            "开工原文须为固定本轮、实际时间、用途与双配置的单行JSON事件。",
            422,
        ) from None


def validate_start_time(scope, occurred_at, at, decisions):
    if not scope.window_start <= at < scope.window_end:
        raise DomainError(
            "CURRENT_EXECUTION_WINDOW_REQUIRED",
            "当前开工与原子占用须在固定窗口内；已结束窗口的实绩请另行如实记录。",
            409,
        )
    if occurred_at > at:
        raise DomainError("FUTURE_ACTUAL", "实际开工时间不能在未来。", 422)
    if not scope.window_start <= occurred_at < scope.window_end:
        raise DomainError("START_OUTSIDE_WINDOW", "实际开工时间不在固定授权窗口内。", 409)
    if any(occurred_at < decision.created_at for decision in decisions):
        raise DomainError("START_PRECEDES_AUTHORIZATION", "实际开工不能早于两项具名批准。", 409)
