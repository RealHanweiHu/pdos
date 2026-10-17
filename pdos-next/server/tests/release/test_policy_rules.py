"""Pure policy projections; no original, authority, Current or T2 is established."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.release import policy_rules, policy_schemas, schemas
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope, SourceRef

AT = datetime(2026, 10, 17, 18, tzinfo=UTC)


def ref(kind):
    return schemas.ObjectRef(kind=kind, id=uuid4(), revision=1)


@pytest.fixture
def case():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    config = schemas.SubjectConfiguration(
        definition={"id": uuid4(), "revision": 1},
        engineering_configuration={"id": uuid4(), "revision": 1},
        manufacturing_configuration={"id": uuid4(), "revision": 1},
    )
    selected = schemas.ReleaseScope(
        quantity="12",
        unit="台",
        lots=({"id": uuid4(), "revision": 1},),
        site="试制场地",
        lines=({"id": uuid4(), "revision": 1},),
        regions=("CN",),
    )
    run, publication, document = (
        ref("test_run"),
        ref("manufacturing_publication"),
        ref("control_plan"),
    )
    original = SourceRef(id=uuid4(), revision=1, position="line:1;quote_sha256:" + "a" * 64)
    purpose = "已固定小批用途"

    def rule(identity, discipline, predicate, **updates):
        return policy_schemas.PolicyRule(
            **{
                "id": identity,
                "version": "v1",
                "scope": selected,
                "discipline": discipline,
                "applicable_if": {"op": "always"},
                "predicate": predicate,
                "required_evidence": (run,) if discipline == "engineering" else (publication,),
                "freshness": "current",
                "severity": "hard",
                "responsible_role": discipline,
                "waivable": False,
                "allowed_purpose": (purpose,),
                **updates,
            }
        )

    policy = policy_schemas.PolicyMaterial(
        schema_version="pdos-release-policy-v1",
        scope=scope,
        category_id=uuid4(),
        subject_config=config,
        release_scope=selected,
        purpose=purpose,
        policy_version="actual-controlled-policy-v1",
        publisher_id=uuid4(),
        owner_id=uuid4(),
        visibility="category",
        nature="synthetic",
        status="active",
        valid_from=AT - timedelta(days=1),
        valid_until=None,
        rules=(
            rule(
                "engineering-reviewed",
                "engineering",
                {"op": "test_run_status", "status": "reviewed"},
            ),
            rule(
                "manufacturing-fixed", "manufacturing", {"op": "manufacturing_publication_present"}
            ),
        ),
    )
    facts = (
        {
            "ref": run.model_dump(mode="json"),
            "value": {
                "_release_current": True,
                "snapshot": {"status": "reviewed", "result": "fail"},
            },
        },
        {
            "ref": publication.model_dump(mode="json"),
            "value": {"_release_current": True, "body_sha256": "b" * 64},
        },
        {
            "ref": document.model_dump(mode="json"),
            "value": {"_release_current": True, "content_sha256": "c" * 64},
        },
    )
    kwargs = dict(
        scope=scope,
        category_id=policy.category_id,
        subject_config=config,
        release_scope=selected,
        purpose=purpose,
        facts=facts,
        sources=(original,),
        at=AT,
    )
    return SimpleNamespace(**locals())


def test_actual_named_predicates_and_separate_professional_candidates(case):
    before = deepcopy(case.facts)
    basis, checks = policy_rules.evaluate(case.policy, **case.kwargs)
    assert basis.version == case.policy.policy_version
    assert basis.sources == (case.original,)
    assert [(value.discipline, value.state) for value in checks] == [
        ("engineering", "satisfied"),
        ("manufacturing", "satisfied"),
    ]
    assert all(value.required and value.non_waivable for value in checks)
    assert case.facts == before
    assert case.policy.valid_until is None


@pytest.mark.parametrize("missing", [False, True])
def test_explicit_empty_dimensions_match_without_omitting_required_evidence(case, missing):
    selected = case.selected.model_copy(update={"lots": (), "lines": ()})
    policy = case.policy.model_copy(
        update={
            "release_scope": selected,
            "rules": tuple(
                rule.model_copy(update={"scope": selected}) for rule in case.policy.rules
            ),
        }
    )
    _, checks = policy_rules.evaluate(
        policy,
        **{
            **case.kwargs,
            "release_scope": selected,
            "facts": case.facts[1:] if missing else case.facts,
        },
    )
    assert len(checks) == 2 and all(check.applicable for check in checks)
    assert checks[0].state == ("unknown" if missing else "satisfied")
    assert checks[1].state == "satisfied"


def test_explicit_null_policy_boundaries_add_no_ttl_or_unknown(case):
    policy = case.policy.model_copy(update={"valid_from": None, "valid_until": None})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    assert all(value.state == "satisfied" for value in checks)


@pytest.mark.parametrize(
    "predicate",
    [
        {"op": "test_run_status", "status": "pass"},
        {"op": "test_run_result", "result": "pass"},
        {"op": "__import__", "expression": "raise RuntimeError('must not execute')"},
        {"op": "test_run_status", "status": "reviewed", "result": "pass"},
        {"op": "object_exists", "kind": ["test_run"]},
        {"op": "object_exists", "ref": {"kind": "test_run", "id": "not-a-uuid"}},
    ],
)
def test_reviewed_lifecycle_never_proves_results_or_unknown_expression(case, predicate):
    first = case.policy.rules[0].model_copy(update={"predicate": predicate})
    policy = case.policy.model_copy(update={"rules": (first, case.policy.rules[1])})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    assert checks[0].state == "unknown"
    assert checks[1].state == "satisfied"


def test_known_lifecycle_mismatch_blocks_without_waiver_or_score(case):
    facts = deepcopy(case.facts)
    facts[0]["value"]["snapshot"].update(status="running", result="pass", score=100)
    _, checks = policy_rules.evaluate(case.policy, **{**case.kwargs, "facts": facts})
    assert checks[0].state == "blocked"
    assert checks[0].non_waivable is True


@pytest.mark.parametrize(
    "severity,required", [("hard", True), ("required", True), ("advisory", False)]
)
def test_severity_maps_required_without_granting_responsible_role(case, severity, required):
    rule = case.policy.rules[0].model_copy(
        update={"severity": severity, "responsible_role": "policy text only"}
    )
    policy = case.policy.model_copy(update={"rules": (rule, case.policy.rules[1])})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    assert checks[0].required is required
    assert checks[0].state == "satisfied"
    assert "policy text only" in checks[0].detail


@pytest.mark.parametrize("selector", ["kind", "ref"])
def test_object_exists_checks_actual_fixed_object_only(case, selector):
    expression = {
        "op": "object_exists",
        selector: "test_run" if selector == "kind" else case.run.model_dump(mode="json"),
    }
    rule = case.policy.rules[0].model_copy(update={"predicate": expression})
    policy = case.policy.model_copy(update={"rules": (rule, case.policy.rules[1])})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    assert checks[0].state == "satisfied"


@pytest.mark.parametrize(
    "fault",
    ["no_current", "old_version", "missing", "freshness", "unknown_kind", "unknown_applicability"],
)
def test_unknown_required_evidence_or_applicability_cannot_disappear(case, fault):
    facts, policy = deepcopy(case.facts), case.policy
    rule = policy.rules[0]
    if fault == "no_current":
        facts[0]["value"].pop("_release_current")
    elif fault == "old_version":
        facts[0]["ref"]["revision"] = 2
    elif fault == "missing":
        facts = facts[1:]
    elif fault == "freshness":
        rule = rule.model_copy(update={"freshness": "last_30_days"})
    elif fault == "unknown_kind":
        rule = rule.model_copy(update={"required_evidence": ("future_owner",)})
    else:
        rule = rule.model_copy(update={"applicable_if": {"op": "model_says_not_applicable"}})
    policy = policy.model_copy(update={"rules": (rule, policy.rules[1])})
    _, checks = policy_rules.evaluate(policy, **{**case.kwargs, "facts": facts})
    assert checks[0].state == "unknown" and checks[0].applicable and checks[0].required


def test_meaningful_disjoint_scope_keeps_not_applicable_without_fabricated_evidence(case):
    rule = case.policy.rules[0].model_copy(
        update={
            "scope": case.selected.model_copy(update={"regions": ("US",)}),
            "predicate": {"op": "not_implemented"},
        }
    )
    policy = case.policy.model_copy(update={"rules": (rule, case.policy.rules[1])})
    _, checks = policy_rules.evaluate(policy, **{**case.kwargs, "facts": case.facts[1:]})
    assert checks[0].applicable is False and checks[0].state == "satisfied"


@pytest.mark.parametrize("fault", ["config", "range", "withdrawn", "future", "expired"])
def test_uncovered_or_inactive_policy_keeps_both_professionals_unknown(case, fault):
    changes = {}
    if fault == "config":
        changes["subject_config"] = case.config.model_copy(
            update={"definition": schemas.VersionRef(id=uuid4(), revision=1)}
        )
    elif fault == "range":
        changes["release_scope"] = case.selected.model_copy(update={"quantity": 1})
    elif fault == "withdrawn":
        changes["status"] = "withdrawn"
    elif fault == "future":
        changes["valid_from"] = AT + timedelta(seconds=1)
    else:
        changes["valid_until"] = AT
    _, checks = policy_rules.evaluate(case.policy.model_copy(update=changes), **case.kwargs)
    assert {value.discipline for value in checks} == {"engineering", "manufacturing"}
    assert all(value.state == "unknown" and value.required for value in checks)


@pytest.mark.parametrize("fault", ["scope", "category_id", "purpose"])
def test_foreign_policy_root_is_rejected(case, fault):
    value = "other purpose" if fault == "purpose" else uuid4()
    if fault == "scope":
        value = case.scope.model_copy(update={"project_id": value})
    with pytest.raises(DomainError) as caught:
        policy_rules.evaluate(case.policy.model_copy(update={fault: value}), **case.kwargs)
    assert caught.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("kept", [(), (0,), (1,)])
def test_missing_professional_rules_are_unknown_even_for_empty_policy(case, kept):
    policy = case.policy.model_copy(update={"rules": tuple(case.policy.rules[i] for i in kept)})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    for discipline in ("engineering", "manufacturing"):
        check = next(value for value in checks if value.discipline == discipline)
        assert check.state == (
            "satisfied"
            if (discipline == "engineering" and 0 in kept)
            or (discipline == "manufacturing" and 1 in kept)
            else "unknown"
        )


def test_document_and_object_selectors_use_exact_actual_references(case):
    rule = case.rule(
        "document-present",
        "manufacturing",
        {"op": "document_present", "ref": case.document.model_dump(mode="json")},
        required_evidence=("control_plan",),
        applicable_if={"op": "object_exists", "kind": "control_plan"},
    )
    policy = case.policy.model_copy(update={"rules": (case.policy.rules[0], rule)})
    _, checks = policy_rules.evaluate(policy, **case.kwargs)
    assert checks[1].state == "satisfied"
    changed = rule.model_copy(
        update={
            "predicate": {
                "op": "object_exists",
                "ref": {**case.document.model_dump(mode="json"), "revision": 2},
            }
        }
    )
    _, checks = policy_rules.evaluate(
        policy.model_copy(update={"rules": (case.policy.rules[0], changed)}), **case.kwargs
    )
    assert checks[1].state == "unknown"


def test_closed_publication_inputs_and_complete_rule_vocabulary(case):
    raw = case.policy.model_dump(mode="json")
    assert set(raw["rules"][0]) == {
        "id",
        "version",
        "scope",
        "discipline",
        "applicable_if",
        "predicate",
        "required_evidence",
        "freshness",
        "severity",
        "responsible_role",
        "waivable",
        "allowed_purpose",
    }
    with pytest.raises(ValidationError):
        policy_schemas.PolicyMaterial.model_validate({**raw, "ready": True})
    with pytest.raises(ValidationError):
        policy_schemas.PolicyImport.model_validate(
            {
                "project_id": case.scope.project_id,
                "source": case.original,
                "reason": "实际登记原文",
                "qualified": True,
            }
        )
    with pytest.raises(ValidationError):
        policy_schemas.PolicyMaterial.model_validate(
            {**raw, "rules": [raw["rules"][0], raw["rules"][0]]}
        )


def test_duplicate_fact_versions_cannot_be_chosen_by_first_or_latest(case):
    facts = (
        *case.facts,
        {
            "ref": {**case.run.model_dump(mode="json"), "revision": 2},
            "value": {"_release_current": True},
        },
    )
    with pytest.raises(DomainError) as caught:
        policy_rules.evaluate(case.policy, **{**case.kwargs, "facts": facts})
    assert caught.value.reason == "INTEGRITY_MISMATCH"
    assert caught.value.code == "VALIDATION_FAILED"
