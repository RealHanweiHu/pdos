"""Owned fake-Session proofs; no PostgreSQL, HTTP, qualification or real bytes.

The real quality kernel computes mutations. Fakes only stand in for the root's
ACL, source, professional and fixed-original bridge ports. PG/rollback/RLS
verification belongs to the separate transaction suite run by root.
"""

import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from quality_issues.helpers import NOW, fixed_run, source, uid

from pdos_next.domain.quality_execution import evidence, policy, service
from pdos_next.domain.quality_execution.adapters import TransactionCommands
from pdos_next.domain.quality_execution.models import (
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyFact,
)
from pdos_next.domain.quality_execution.ports import FixedQualityResult, FixedQualityScope
from pdos_next.domain.quality_execution.schemas import (
    CapaDraftPayload,
    ContainmentPayload,
    IssueCreatePayload,
    IssueMergePayload,
    IssueTriagePayload,
    PolicyInput,
)
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.quality_issues.rules import replace
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, digest


def assert_code(code, fn):
    with pytest.raises(DomainError) as error:
        fn()
    assert error.value.reason == code


def result(event=None, **changes):
    run = fixed_run(revision=3)
    refs = (
        run.measurements[0].source,
        run.items[0].method,
        run.items[0].criterion.source,
        run.execution.equipment,
        run.execution.calibration,
    )
    return FixedQualityResult(
        scope=run.scope,
        purpose="prototype dimensional verification",
        event_id=event,
        run_version_id=uid("run-version-3"),
        run_revision=3,
        measurement_id=run.measurements[0].id,
        projection_id=uid("projection"),
        projection_revision=1,
        basis_sha256=digest("fixed-basis"),
        rules_version="synthetic-test-rules-v1",
        rules_sha256=digest("fixed-rules"),
        verified=VerifiedRun(run=run, nature="synthetic"),
        visibility="private",
        owner_id=uid("actor"),
        sources=refs,
        required_source_read_set=[{"artifact_id": uid("evidence"), "expected_revision": 1}],
        source_basis={"byte_proof": "exact-original"},
        retained={
            "current": True,
            "facts_revision": digest("retained"),
            "checked_at": NOW.isoformat(),
            "execution_window_elapsed": False,
        },
        current=True,
        **changes,
    )


class MemorySession:
    """SQL-shaped in-memory storage; intentionally cannot commit or issue receipts."""

    def __init__(self):
        self.engine = SimpleNamespace()
        self.rows = []

    def get_bind(self):
        return self.engine

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        if hasattr(row, "created_at") and row.created_at is None:
            row.created_at = NOW
        if row not in self.rows:
            self.rows.append(row)

    def flush(self):
        return None

    def _matches(self, query):
        cls = query.column_descriptions[0]["entity"]
        rows = [r for r in self.rows if isinstance(r, cls)]
        for where in query._where_criteria:
            name = where.left.key
            value = (
                uid("category")
                if name == "category_id"
                and getattr(where.right, "name", None) == "category_for_product"
                else where.right.value
            )
            if where.operator.__name__ == "in_op":
                rows = [r for r in rows if getattr(r, name) in value]
            else:
                rows = [r for r in rows if getattr(r, name) == value]
        return rows

    def scalar(self, query):
        rows = self._matches(query)
        if not rows:
            return None
        field = query.column_descriptions[0]["name"]
        return getattr(rows[0], field) if field == "id" else rows[0]

    def scalars(self, query):
        return self._matches(query)

    def get(self, cls, identity):
        if cls is Principal:
            return SimpleNamespace(
                id=identity, tenant_id=uid("tenant"), kind="human", active=True, name="Synthetic"
            )
        return next((r for r in self.rows if isinstance(r, cls) and r.id == identity), None)


@pytest.fixture
def host(monkeypatch):
    session = MemorySession()
    ctx = Context(uid("tenant"), uid("actor"), uid("actor"), category_id=uid("category"))
    product = SimpleNamespace(id=uid("product"), category_id=uid("category"), revision=1)
    state = {"authorized": True, "epoch": 1, "byte_reads": 0}

    def bridge(s, context, pid, **binding):
        state["byte_reads"] += 1
        template = state.get("values", {}).get(binding["run_id"], result())
        value = replace(template, event_id=binding.get("event_id"))
        if "during_read" in state:
            state["during_read"](binding)
        return value

    def refresh(s, context, pid, value, **kwargs):
        if state.get("retained_revoked"):
            return replace(value, current=False)
        return value

    service.configure_result_bridge(session.engine, bridge, refresh=refresh)

    def authority(*args, **kwargs):
        return {
            "authorized": state["authorized"],
            "qualified": state["authorized"],
            "roles": ["quality"],
            "facts_revision": digest(state["epoch"]),
            "valid_until": None,
            "operation": args[4],
            "purpose": args[5],
            "synthetic": True,
            "fact_refs": [
                {
                    "kind": kind,
                    "role": "quality",
                    "nature": "synthetic",
                    "state": "active",
                    "operations": [args[4]],
                    "purposes": [args[5]],
                    "valid_from": (NOW - timedelta(hours=1)).isoformat(),
                    "valid_until": (NOW + timedelta(hours=1)).isoformat(),
                }
                for kind in ("duty", "qualification")
            ],
            "required_source_read_set": [],
        }

    def basis(s, context, pid, reads):
        return [
            {"id": r["artifact_id"], "revision": r["expected_revision"]}
            for r in evidence.merge_reads(reads)
        ], False

    publication = {
        "id": str(uid("risk-policy")),
        "revision": 1,
        "risk": "high",
        "independent_verification": True,
        "nature": "synthetic",
        "sources": (),
        "required_source_read_set": [],
        "facts_revision": digest("policy"),
        "valid_until": None,
        "source_basis": [
            {
                "id": str(uid("risk-policy")),
                "revision": 1,
                "state": "active",
                "valid_from": (NOW - timedelta(hours=1)).isoformat(),
                "valid_until": (NOW + timedelta(hours=1)).isoformat(),
            }
        ],
        "private": False,
    }
    monkeypatch.setattr(service, "now", lambda: NOW)
    monkeypatch.setattr(service, "_human", lambda *a, **k: product)
    monkeypatch.setattr(service.professional, "assess", authority)
    monkeypatch.setattr(service.policy, "assess", lambda *a, **k: deepcopy(publication))
    monkeypatch.setattr(service, "source_basis", basis)
    monkeypatch.setattr(service, "check_source", lambda *a: ([], [], False))
    from pdos_next import quality_result_bridge, source_current

    def fixed_failure(s, context, pid, issue, failure, *, purpose):
        fixed = state.get("values", {}).get(failure.run.id, result())
        if (
            state.get("retained_revoked")
            or not fixed.current
            or fixed.scope != issue.scope
            or fixed.verified.run.id != failure.run.id
            or fixed.measurement_id != failure.measurement_id
        ):
            raise DomainError("SOURCE_STALE", "Synthetic fixed failure changed")
        measurement = next(
            item for item in fixed.verified.run.measurements if item.id == failure.measurement_id
        )
        return quality_result_bridge.DirectQualityFailure(
            scope=fixed.scope,
            purpose=purpose,
            failure=failure,
            measurement=measurement.model_dump(mode="json"),
            projection_id=fixed.projection_id,
            basis_sha256=fixed.basis_sha256,
            sources=fixed.sources,
            required_source_read_set=fixed.required_source_read_set,
            watermark={"synthetic_host": True},
            event_ids=(),
        )

    # This fake host represents original proof with one fixed synthetic basis;
    # actual direct source positions and immutable rows are verified by PG tests.
    monkeypatch.setattr(
        source_current,
        "direct_source_basis",
        lambda s, context, pid, refs, reads: service.source_basis(
            s, context, pid, result().required_source_read_set
        ),
    )
    monkeypatch.setattr(
        quality_result_bridge,
        "direct_issue_failure",
        fixed_failure,
    )
    original_load = service._load

    def kernel_inputs(s, context, command, actual_product, payload, *, require_reads=True):
        # This in-memory host supplies fixed kernel inputs. Actual direct T1
        # Session/source guards belong to the PG and confirmation suites.
        if command.operation not in {
            "quality.issue.triage",
            "quality.issue.containment.record",
        }:
            return original_load(
                s, context, command, actual_product, payload, require_reads=require_reads
            )
        bound = service._load_material(
            s, context, command, actual_product, payload, require_reads=require_reads
        )
        service._refresh(s, context, actual_product.id, command.operation, bound)
        return bound

    monkeypatch.setattr(service, "_load", kernel_inputs)
    actor_grant = Grant(
        tenant_id=ctx.tenant_id,
        category_id=uid("category"),
        principal_id=ctx.requester_id,
        can_write=True,
        expires_at=NOW + timedelta(hours=1),
    )
    session.add(actor_grant)
    return SimpleNamespace(s=session, ctx=ctx, product=product, state=state)


def call(host, operation, payload, *, preview=False):
    command = SimpleNamespace(
        operation=operation,
        command_id=uuid4(),
        product_id=host.product.id,
        expected_revision=1,
        source_read_set=result().required_source_read_set,
    )
    return (
        service.preview_view(host.s, host.ctx, command, host.product, payload)
        if preview
        else service.apply(host.s, host.ctx, command, host.product, payload)
    )


def create(host, event="event", title="Synthetic fixed failure"):
    value = result()
    return call(
        host,
        "quality.issue.create",
        IssueCreatePayload(
            run_id=value.verified.run.id,
            measurement_id=value.measurement_id,
            event_id=uid(event),
            title=title,
        ),
    )[0]


def test_kernel_host_stages_versions_and_delivery_without_receipt_or_commit(host):
    row = create(host)
    assert row.issue_snapshot["failures"][0]["run"] == {
        "id": str(result().verified.run.id),
        "revision": 3,
    }
    assert {type(r) for r in host.s.rows} == {
        Grant,
        QualityIssueVersion,
        QualityIssueCurrent,
        QualityFailureMap,
        QualityEventFailureLink,
    }
    assert row.operation == "quality.issue.create" and row.status == "open"
    assert len(row.issue_snapshot["history"]) == 1


def test_repeated_failure_new_event_key_title_preserves_first_version_and_links_event(host):
    first = create(host)
    second = create(host, "new-event", "Different title")
    assert second is first
    assert len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)]) == 1
    links = [r for r in host.s.rows if isinstance(r, QualityEventFailureLink)]
    assert {r.event_id for r in links} == {uid("event"), uid("new-event")}
    assert all(r.run_version_id == result().run_version_id for r in links)
    assert first.issue_snapshot["title"] == "Synthetic fixed failure"


def test_triage_containment_capa_reuses_kernel_and_preserves_unknown_conclusions(host):
    first = create(host)
    triage = IssueTriagePayload(issue_id=first.issue_id, expected_issue_revision=1, reason="Triage")
    preview = call(host, "quality.issue.triage", triage, preview=True)
    assert preview["after"][str(first.issue_id)]["history"][-1]["at"] is None
    second = call(host, "quality.issue.triage", triage)[0]
    containment = ContainmentPayload(
        issue_id=first.issue_id,
        expected_issue_revision=2,
        action={
            "id": uid("containment"),
            "text": "Synthetic containment observed",
            "executor_id": host.ctx.requester_id,
            "evidence": [source("containment")],
            "at": {"occurred_at": NOW, "original_timezone": "UTC", "source": source("action")},
        },
    )
    third = call(host, "quality.issue.containment.record", containment)[0]
    failure = third.issue_snapshot["failures"][0]["identity"]
    draft = CapaDraftPayload(
        issue_id=first.issue_id,
        expected_issue_revision=3,
        capa_id=uid("capa"),
        hypotheses=[{"text": "Tentative only", "sources": [source("hypothesis")]}],
        actions=[
            {
                "id": uid("corrective"),
                "kind": "corrective",
                "text": "Planned investigation",
                "executor_id": host.ctx.requester_id,
            }
        ],
        requirement={
            "method": "New verification run",
            "acceptance": "Fixed affected pairs pass",
            "observation_until": NOW + timedelta(days=1),
            "required_failure_ids": [failure],
        },
    )
    fourth = call(host, "quality.capa.draft", draft)[0]
    snapshot = fourth.issue_snapshot
    assert [first.revision, second.revision, third.revision, fourth.revision] == [1, 2, 3, 4]
    assert snapshot["root_cause"] is None and snapshot["closure"] is None
    assert snapshot["capa"]["actions"][0]["completion"] is None
    assert snapshot["capa"]["effectiveness"] is None
    assert first.status == "open" and len(first.issue_snapshot["history"]) == 1


def test_preview_confirmation_is_common_only_and_not_forged_by_payload(host):
    row = create(host)
    payload = IssueTriagePayload(
        issue_id=row.issue_id,
        expected_issue_revision=1,
        reason="Triage",
        confirmation_token="fake-token-not-a-domain-permit",
    )
    command = SimpleNamespace(
        operation="quality.issue.triage",
        command_id=uuid4(),
        product_id=host.product.id,
        expected_revision=1,
        source_read_set=result().required_source_read_set,
    )
    bound = service._load(host.s, host.ctx, command, host.product, payload)
    adapter = service._kernel(host.s, host.ctx, host.product.id, bound, lambda _: None)
    assert_code(
        "CONFIRMATION_REQUIRED", lambda: adapter.execute(bound.invocation, bound.domain_payload)
    )
    assert len([r for r in host.s.rows if isinstance(r, QualityIssueVersion)]) == 1


@pytest.mark.parametrize("field", ["scope", "actor_id", "nature", "authorized", "risk", "result"])
def test_create_cannot_forge_authority_or_result(field):
    value = result()
    with pytest.raises(ValidationError):
        IssueCreatePayload.model_validate(
            {
                "run_id": value.verified.run.id,
                "measurement_id": value.measurement_id,
                "event_id": uid("event"),
                "title": "Synthetic",
                field: "forged",
            }
        )


def test_missing_bridge_or_final_refresh_fails_closed_before_mutation(host):
    service.configure_result_bridge(host.s.engine, None)
    assert_code("INTEGRATION_REQUIRED", lambda: create(host))
    service.configure_result_bridge(host.s.engine, lambda *a, **k: result(k.get("event_id")))
    assert_code("INTEGRATION_REQUIRED", lambda: create(host))
    assert not any(isinstance(r, QualityIssueVersion) for r in host.s.rows)


def scope_reader(host, **changes):
    fixed = result()
    return lambda *_args, **binding: FixedQualityScope(
        scope=fixed.scope,
        purpose=fixed.purpose,
        run_id=fixed.verified.run.id,
        run_version_id=changes.get("run_version_id", fixed.run_version_id),
        run_revision=fixed.run_revision,
        event_id=binding["event_id"],
    )


def test_ineligible_result_scope_rejects_before_full_original_proof(host):
    host.s.engine._pdos_quality_result_scope = scope_reader(host)
    host.state["authorized"] = False
    assert_code("QUALIFICATION_REQUIRED", lambda: create(host))
    assert host.state["byte_reads"] == 0
    assert not any(isinstance(row, QualityIssueVersion) for row in host.s.rows)


def test_scope_header_cannot_replace_complete_failure_identity(host):
    host.s.engine._pdos_quality_result_scope = scope_reader(
        host, run_version_id=uid("foreign-run-version")
    )
    assert_code("INTEGRITY_MISMATCH", lambda: create(host))
    assert host.state["byte_reads"] == 1
    assert not any(isinstance(row, QualityIssueVersion) for row in host.s.rows)


@pytest.mark.parametrize("changed", ["authority", "retained"])
def test_original_bytes_callback_revocation_is_rechecked_at_end(host, changed):
    def revoked(_):
        if changed == "authority":
            host.state["authorized"] = False
        else:
            host.state["retained_revoked"] = True

    host.state["during_read"] = revoked
    expected = "QUALIFICATION_REQUIRED" if changed == "authority" else "SOURCE_STALE"
    assert_code(expected, lambda: create(host))
    assert not any(isinstance(r, QualityIssueVersion) for r in host.s.rows)


def test_later_byte_read_cannot_hide_revoked_earlier_retained_proof(host):
    first = create(host)
    reads_before = host.state["byte_reads"]

    def during_read(_):
        # This call has both new event and the original archived failure proof.
        if host.state["byte_reads"] >= reads_before + 2:
            host.state["retained_revoked"] = True

    host.state["during_read"] = during_read
    assert_code("SOURCE_STALE", lambda: create(host, "later"))
    assert len([r for r in host.s.rows if isinstance(r, QualityEventFailureLink)]) == 1
    assert first.revision == 1


def test_later_narrow_refresh_runtime_stamp_change_cannot_commit_earlier_proof(host):
    first = create(host)
    checked = []

    def refresh(s, context, pid, value, **kwargs):
        checked.append(value.event_id)
        if len(checked) == 2:
            # The root refresh contract compares the complete issuer registry
            # stamp even when this later scope revokes an earlier signer.
            raise DomainError("SOURCE_STALE", "Synthetic complete runtime stamp changed")
        return value

    host.s.engine._pdos_quality_result_refresh = refresh
    assert_code("SOURCE_STALE", lambda: create(host, "later-refresh"))
    assert len(checked) == 2
    assert len([r for r in host.s.rows if isinstance(r, QualityEventFailureLink)]) == 1
    assert first.revision == 1


def test_stamp_excludes_only_observation_clock_not_substantive_proof():
    value = result()
    later = replace(
        value, retained={**value.retained, "checked_at": "later", "execution_window_elapsed": True}
    )
    assert service._stamp(value) == service._stamp(later)
    changed = replace(value, retained={**value.retained, "facts_revision": digest("withdrawn")})
    assert service._stamp(value) != service._stamp(changed)


def test_authority_expiring_during_final_query_cannot_stage_mutation(host, monkeypatch):
    clock = [NOW]
    original = service.professional.assess
    calls = []

    def advancing_authority(*args, **kwargs):
        proof = original(*args, **kwargs)
        calls.append(proof)
        if len(calls) == 2:
            clock[0] = NOW + timedelta(hours=2)
        return proof

    monkeypatch.setattr(service.professional, "assess", advancing_authority)
    monkeypatch.setattr(service, "now", lambda: clock[0])
    assert_code("SOURCE_STALE", lambda: create(host))
    assert not any(isinstance(r, QualityIssueVersion) for r in host.s.rows)


def test_exact_line_source_preserves_whitespace_and_rejects_substring_hash(monkeypatch):
    line = "  Synthetic containment exact bytes  "
    row = SimpleNamespace(
        id=uid("manual"),
        tenant_id=uid("tenant"),
        product_id=uid("product"),
        revision=1,
        content=line,
        content_hash=digest(line),
        visibility="private",
        owner_id=uid("actor"),
        status="active",
        original_id=None,
    )
    monkeypatch.setattr(evidence, "source_for", lambda *a: row)
    ctx = Context(uid("tenant"), uid("actor"), uid("actor"))
    receipt = SimpleNamespace(
        id=uid("native-registration"),
        requester_id=row.owner_id,
        actor_id=row.owner_id,
        visibility=row.visibility,
        run_id=None,
        result={"id": str(row.id), "revision": row.revision},
    )
    session = SimpleNamespace(scalar=lambda _: receipt)
    ref = SourceRef(
        id=row.id, revision=1, position=f"line:1;quote_sha256:{sha256(line.encode()).hexdigest()}"
    )
    reads, basis, private = evidence.check_source(session, ctx, uid("product"), ref)
    assert private and reads[0]["expected_revision"] == 1
    assert basis[0]["source_kind"] == "registered_native_text"
    wrong = replace(
        ref, position=f"line:1;quote_sha256:{sha256(line.strip().encode()).hexdigest()}"
    )
    assert_code(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: evidence.check_source(session, ctx, uid("product"), wrong),
    )
    session.scalar = lambda _: None
    assert_code(
        "SOURCE_UNAVAILABLE", lambda: evidence.check_source(session, ctx, uid("product"), ref)
    )


def test_readset_never_truncates_or_accepts_bool_revision():
    with pytest.raises(ValidationError):
        evidence.merge_reads([{"artifact_id": uid("a"), "expected_revision": True}])
    assert_code(
        "SOURCE_STALE",
        lambda: evidence.merge_reads(
            [{"artifact_id": uid("a"), "expected_revision": 1}],
            [{"artifact_id": uid("a"), "expected_revision": 2}],
        ),
    )
    reads = [{"artifact_id": uid(str(i)), "expected_revision": 1} for i in range(21)]
    assert len(evidence.merge_reads(reads)) == 21


def policy_input():
    return PolicyInput(
        product_id=uid("product"),
        project_id=uid("project"),
        external_id="SYN-POLICY",
        purpose="prototype dimensional verification",
        risk="high",
        independent_verification=True,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
        approval={
            "system": "Synthetic",
            "external_id": "SYN-APPROVAL",
            "version": "v1",
            "approved_by": "Synthetic named issuer",
            "issued_at": NOW - timedelta(minutes=1),
        },
        sources=[
            {
                "artifact_id": uid("policy-source"),
                "expected_revision": 1,
                "line": 1,
                "quote": "SYN-POLICY",
            }
        ],
        reason="Synthetic policy publication",
    )


def publication(data):
    return {
        k: data.model_dump(mode="json")[k]
        for k in (
            "external_id",
            "purpose",
            "risk",
            "independent_verification",
            "state",
            "valid_from",
            "valid_until",
            "approval",
        )
    }


@pytest.mark.parametrize("change", ["duplicate", "number_bool", "missing", "risk"])
def test_policy_requires_exact_typed_publication(monkeypatch, change):
    data = policy_input()
    value = publication(data)
    if change == "number_bool":
        value["independent_verification"] = 1
    elif change == "missing":
        value.pop("risk")
    elif change == "risk":
        value["risk"] = "low"
    text = json.dumps(value)
    if change == "duplicate":
        text = text[:-1] + ', "risk": "high"}'
    monkeypatch.setattr(policy, "source_for", lambda *a: SimpleNamespace(content=text))
    assert_code("MISSING_REQUIRED_EVIDENCE", lambda: policy._publication(None, None, data))


def test_synthetic_policy_issuer_requires_exact_host_enable_and_aba_invalidates_old_token():
    engine = SimpleNamespace()
    scope = dict(tenant_id=uid("tenant"), product_id=uid("product"), project_id=uid("project"))
    with pytest.raises(ValueError):
        policy.configure_local_synthetic(engine, **scope, enabled=True)
    issuer = policy.configure_local_synthetic(
        engine, **scope, enabled=True, test_marker_verified=True
    )
    with pytest.raises(AttributeError):
        issuer.version = "forged"
    policy.disable_issuer(engine, issuer.key)
    replacement = policy.configure_local_synthetic(
        engine, **scope, enabled=True, test_marker_verified=True
    )
    assert replacement.epoch > issuer.epoch
    assert_code("TRUSTED_ISSUER_REQUIRED", lambda: policy._issuer(engine, issuer, *scope.values()))


def test_policy_publication_aware_timestamp_formats_bind_the_same_instant(monkeypatch):
    data = policy_input()
    value = publication(data)
    value["approval"]["issued_at"] = data.approval.issued_at.isoformat()
    value["valid_from"] = data.valid_from.isoformat()
    monkeypatch.setattr(policy, "source_for", lambda *a: SimpleNamespace(content=json.dumps(value)))
    policy._publication(None, None, data)


def test_no_t2_completion_or_close_registered_and_t1_has_no_second_confirmation_store():
    assert set(service.PAYLOADS) == {
        "quality.issue.create",
        "quality.issue.merge",
        "quality.issue.triage",
        "quality.issue.containment.record",
        "quality.capa.draft",
    }
    assert not hasattr(TransactionCommands, "commit")
    assert service.replay_subject_type(None) == "quality_issue"


def test_merge_wrapper_is_fixed_logical_sources_not_client_policy():
    payload = IssueMergePayload(
        issue_id=uid("target"),
        expected_issue_revision=2,
        sources=[{"id": uid("source-issue"), "revision": 1}],
        reason="Confirm merge",
    )
    domain = service._domain(payload)
    assert domain.sources[0].id == uid("source-issue")
    assert (
        "issue_id" not in domain.model_dump()
        and "expected_issue_revision" not in domain.model_dump()
    )


def test_merge_retains_alias_history_and_blocks_followup_pending_independent_recheck(host):
    first = create(host)
    other_run = fixed_run("other-run", revision=3)
    second_value = replace(
        result(),
        verified=VerifiedRun(run=other_run, nature="synthetic"),
        run_version_id=uid("other-run-version"),
        measurement_id=other_run.measurements[0].id,
        sources=(
            other_run.measurements[0].source,
            other_run.items[0].method,
            other_run.items[0].criterion.source,
        ),
    )
    host.state["values"] = {other_run.id: second_value}
    second = call(
        host,
        "quality.issue.create",
        IssueCreatePayload(
            run_id=other_run.id,
            measurement_id=second_value.measurement_id,
            event_id=uid("other-event"),
            title="Independent failure",
        ),
    )[0]
    merged = call(
        host,
        "quality.issue.merge",
        IssueMergePayload(
            issue_id=first.issue_id,
            expected_issue_revision=1,
            sources=[{"id": second.issue_id, "revision": 1}],
            reason="Confirmed shared scope",
        ),
    )[0]
    assert merged.issue_snapshot["needs_recheck"] is True
    assert len(merged.issue_snapshot["failures"]) == 2
    alias = service._row(host.s, host.ctx, host.product.id, second.issue_id)
    assert alias.issue_snapshot["merged_into"] == str(first.issue_id)
    assert second.revision == 1 and second.issue_snapshot["merged_into"] is None
    assert {r.issue_id for r in host.s.rows if isinstance(r, QualityFailureMap)} == {first.issue_id}
    view = service._view(host.s, host.ctx, host.product.id, merged, current=True)
    assert not any(view.capabilities.values())
    assert_code(
        "RECHECK_REQUIRED",
        lambda: call(
            host,
            "quality.issue.triage",
            IssueTriagePayload(
                issue_id=first.issue_id,
                expected_issue_revision=2,
                reason="Cannot bypass merged recheck",
            ),
        ),
    )


def test_readable_withdrawn_source_keeps_fixed_history_without_current_capability(
    host, monkeypatch
):
    row = create(host)

    def withdrawn(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic withdrawn source")

    monkeypatch.setattr(service, "source_basis", withdrawn)
    view = service._view(host.s, host.ctx, host.product.id, row, current=True)
    assert view.source_status == "needs_recheck" and not any(view.capabilities.values())
    assert view.issue == service._snapshot(row) and view.is_current


def test_preview_only_submission_clock_is_stable_between_read_phases(host, monkeypatch):
    row = create(host)
    payload = IssueTriagePayload(issue_id=row.issue_id, expected_issue_revision=1, reason="Triage")
    command = SimpleNamespace(
        operation="quality.issue.triage",
        command_id=uid("same-preview-command"),
        product_id=host.product.id,
        expected_revision=1,
        source_read_set=result().required_source_read_set,
    )
    first = service.preview_view(host.s, host.ctx, command, host.product, payload)
    monkeypatch.setattr(service, "now", lambda: NOW + timedelta(minutes=2))
    second = service.preview_view(host.s, host.ctx, command, host.product, payload)
    assert digest(first) == digest(second)


def test_policy_expiry_is_checked_after_all_source_reads(monkeypatch):
    engine = SimpleNamespace()
    ctx = Context(uid("tenant"), uid("actor"), uid("actor"))
    issuer = policy.configure_local_synthetic(
        engine,
        tenant_id=ctx.tenant_id,
        product_id=uid("product"),
        project_id=uid("project"),
        enabled=True,
        test_marker_verified=True,
    )
    data = policy_input()
    row = QualityPolicyFact(
        id=uid("policy-version"),
        tenant_id=ctx.tenant_id,
        product_id=data.product_id,
        project_id=data.project_id,
        purpose=data.purpose,
        series_id=uid("policy-version"),
        revision=1,
        previous_id=None,
        previous_revision=None,
        owner_id=ctx.requester_id,
        visibility="private",
        status="active",
        risk=data.risk,
        independent_verification=data.independent_verification,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(seconds=1),
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature="synthetic",
        external_id=data.external_id,
        data=data.model_dump(mode="json"),
        sources=[],
        required_source_read_set=[{"artifact_id": str(uid("evidence")), "expected_revision": 1}],
        source_basis={"sources": []},
        reason=data.reason,
    )
    row.fact_sha256 = digest(policy._material(row))
    pointer = SimpleNamespace(
        id=uid("policy-pointer"),
        fact_id=row.id,
        series_id=row.series_id,
        fact_revision=1,
        issuer_key=issuer.key,
        external_id=row.external_id,
        epoch=1,
    )
    session = SimpleNamespace(
        scalars=lambda q: [pointer], get=lambda *a: row, get_bind=lambda: engine
    )
    clock = [NOW]

    def advancing_source(*args):
        clock[0] = NOW + timedelta(seconds=2)
        return [], False

    monkeypatch.setattr(policy, "source_basis", advancing_source)
    monkeypatch.setattr(policy, "now", lambda: clock[0])
    assert_code(
        "RECHECK_REQUIRED",
        lambda: policy.assess(session, ctx, data.product_id, data.project_id, data.purpose),
    )
