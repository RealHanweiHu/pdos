"""Root's actual seams, with forbidden connections and explicit owner substitutes.

These tests do not prove source ACL/bytes, public qualification, SQL commit/RLS
or current seven owners. Actual source conversion, structured line comparison,
common consume ordering and delegated module interfaces run unmodified.
"""

import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from quality_issues.helpers import uid
from sqlalchemy.orm import make_transient_to_detached
from test_fact_write import make_world

from pdos_next import capa_fact_owner as owner
from pdos_next import capa_rule_import, capa_rule_publisher
from pdos_next import service as common
from pdos_next.command_handlers import T1_OPERATIONS, T2_OPERATIONS
from pdos_next.contracts import PAYLOADS
from pdos_next.domain.capa_effectiveness import fact_commands as commands
from pdos_next.domain.capa_effectiveness import fact_consumption, fact_service
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.domain.quality_execution import evidence
from pdos_next.errors import DomainError
from pdos_next.models import Category, Confirmation, Product
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest


def rejects(code, fn):
    with pytest.raises(DomainError) as error:
        fn()
    assert error.value.reason == code


def source_line(monkeypatch, f, text):
    """Keep actual whole-line hashing; permission/provenance are explicit substitutes."""
    row = SimpleNamespace(id=uid("root-actual-source"), revision=3, content=text, original_id=None)
    ref = SourceRef(
        id=row.id,
        revision=row.revision,
        kind="artifact",
        position="line:1;quote_sha256:" + sha256(text.encode()).hexdigest(),
    )

    def read(_s, ctx, pid, identity, revision):
        assert (_s, ctx, pid, identity, revision) == (
            f.s,
            f.ctx,
            f.product.id,
            row.id,
            row.revision,
        )
        return row

    monkeypatch.setattr(owner, "source_for", read)
    monkeypatch.setattr(capa_rule_publisher, "source_for", read)
    monkeypatch.setattr(evidence, "source_for", read)
    monkeypatch.setattr(evidence, "source_basis", lambda *_, **__: ([], False))
    return row, ref


def observation_line(f, *, raw=None):
    record = f.payload.records[0].model_dump(mode="json", exclude={"sources"})
    if raw is not None:
        record["raw_material"] = raw
    return {
        "schema_version": "pdos-capa-observation-source-v1",
        "nature": f.fixed.origin.nature,
        "scope": f.fixed.origin.scope.model_dump(mode="json"),
        "issue_id": str(f.payload.issue_id),
        "capa_id": str(f.payload.capa_id),
        "purpose": f.fixed.origin.purpose,
        "rule": f.payload.rule.model_dump(mode="json"),
        "record": record,
        "observed_from": f.payload.observed_from.isoformat(),
        "observed_until": f.payload.observed_until.isoformat(),
        "at": {
            "occurred_at": f.payload.at.occurred_at.isoformat(),
            "original_timezone": f.payload.at.original_timezone,
        },
    }


def invoke_original(f, ref, *, record=None):
    record = record or f.payload.records[0].model_copy(update={"sources": (ref,)})
    owner.ActualFactOwner()._original_record(
        f.s,
        f.ctx,
        f.product.id,
        f.fixed.origin,
        SimpleNamespace(ref=f.payload.rule),
        f.payload,
        record,
    )


def test_actual_definition_reference_uses_full_line_not_quote_digest(monkeypatch):
    f = make_world(monkeypatch)
    row, expected = source_line(monkeypatch, f, "prefix quoted exact material suffix  ")
    definition = DefinitionReference(
        artifact_id=row.id, expected_revision=row.revision, line=1, quote="quoted exact material"
    )
    refs = evidence.refs_from_exact(f.s, f.ctx, f.product.id, (definition,))
    assert refs == (expected,)
    assert (
        refs[0].position != "line:1;quote_sha256:" + sha256(definition.quote.encode()).hexdigest()
    )
    reads, _, _ = evidence.check_source(f.s, f.ctx, f.product.id, refs[0])
    assert reads == [{"artifact_id": str(row.id), "expected_revision": 3}]
    row.content = row.content.rstrip()
    rejects(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: evidence.check_source(f.s, f.ctx, f.product.id, refs[0]),
    )
    f.s.close()


def test_original_record_accepts_actual_null_and_keeps_original_clock(monkeypatch):
    f = make_world(monkeypatch)
    actual = observation_line(f)
    _, ref = source_line(monkeypatch, f, json.dumps(actual, separators=(",", ":")))
    invoke_original(f, ref)
    assert actual["record"]["raw_material"]["value"] is None
    assert actual["at"]["occurred_at"].endswith("123457+00:00")
    assert not f.s.new
    f.s.close()


@pytest.mark.parametrize("path", ["raw", "record_clock", "interval", "extra", "duplicate"])
def test_original_record_rejects_real_line_changes_and_duplicate_keys(monkeypatch, path):
    f = make_world(monkeypatch)
    actual = observation_line(f)
    if path == "raw":
        actual["record"]["raw_material"]["value"] = "invented observed value"
    elif path == "record_clock":
        actual["record"]["occurred_at"] = f.payload.observed_from.isoformat()
    elif path == "interval":
        actual["observed_until"] = (f.payload.observed_until - timedelta(seconds=1)).isoformat()
    elif path == "extra":
        actual["complete"] = True
    text = json.dumps(actual, separators=(",", ":"))
    if path == "duplicate":
        text = text[:-1] + ',"nature":"synthetic"}'
    _, ref = source_line(monkeypatch, f, text)
    rejects("FACT_OBSERVATION_ORIGINAL_MISMATCH", lambda: invoke_original(f, ref))
    assert not f.s.new
    f.s.close()


def test_raw_original_true_cannot_become_requested_integer_one(monkeypatch):
    f = make_world(monkeypatch)
    requested = f.payload.records[0].model_copy(update={"raw_material": {"value": 1}})
    actual = observation_line(f, raw={"value": True})
    _, ref = source_line(monkeypatch, f, json.dumps(actual, separators=(",", ":")))
    requested = requested.model_copy(update={"sources": (ref,)})
    rejects(
        "FACT_OBSERVATION_ORIGINAL_MISMATCH",
        lambda: invoke_original(f, ref, record=requested),
    )
    f.s.close()


@pytest.mark.parametrize("offset", ["Z", "-07:00"])
def test_known_original_clock_paths_compare_exact_microsecond_instant(monkeypatch, offset):
    f = make_world(monkeypatch)
    actual = observation_line(f)
    if offset == "Z":
        for key in ("observed_from", "observed_until"):
            actual[key] = actual[key].replace("+00:00", "Z")
        actual["at"]["occurred_at"] = actual["at"]["occurred_at"].replace("+00:00", "Z")
    else:
        from datetime import timezone

        zone = timezone(-timedelta(hours=7))
        actual["observed_from"] = f.payload.observed_from.astimezone(zone).isoformat()
        actual["observed_until"] = f.payload.observed_until.astimezone(zone).isoformat()
        actual["record"]["occurred_at"] = (
            f.payload.records[0].occurred_at.astimezone(zone).isoformat()
        )
        actual["at"]["occurred_at"] = f.payload.at.occurred_at.astimezone(zone).isoformat()
    _, ref = source_line(monkeypatch, f, json.dumps(actual, separators=(",", ":")))
    invoke_original(f, ref)
    f.s.close()


@pytest.mark.parametrize(
    "kind,code",
    [("rule", "FACT_ISSUER_OWNER_REQUIRED"), ("review", "FACT_APPLICABILITY_OWNER_REQUIRED")],
)
def test_missing_actual_publisher_or_review_owner_is_explicit_and_never_positive(
    monkeypatch, kind, code
):
    f = make_world(monkeypatch, kind)
    actual = owner.ActualFactOwner()
    monkeypatch.setattr(actual, "runtime_stamp", lambda _s: digest("explicit offline registry"))
    rejects(code, lambda: actual.read(f.s, f.ctx, f.product.id, kind, f.payload, new_write=True))
    assert not f.s.new
    f.s.close()


def test_rule_is_host_only_not_t2_or_any_public_payload(monkeypatch):
    f = make_world(monkeypatch, "rule")
    assert commands.RULE_OPERATION not in PAYLOADS
    assert commands.RULE_OPERATION not in T1_OPERATIONS | T2_OPERATIONS
    assert commands.OBSERVATION_OPERATION in T1_OPERATIONS
    assert commands.REVIEW_OPERATION in T2_OPERATIONS
    fact_service.configure(f.s.get_bind(), owner.ActualFactOwner())
    rejects(
        "FACT_RULE_HOST_ONLY",
        lambda: capa_rule_import.publish_rule(f.s, f.ctx, f.command, publisher=None),
    )
    assert not f.s.new
    f.s.close()


@pytest.mark.parametrize("kind", ["observation", "review"])
def test_actual_common_capture_is_first_before_phase_check_or_sql(monkeypatch, kind):
    f = make_world(monkeypatch, kind)
    runtime = fact_service.configure(f.s.get_bind(), f.host.owner)
    f.host = runtime.host
    monkeypatch.setattr(fact_service, "datetime", fact_consumption.datetime)
    preview = fact_service.preview_view(f.s, f.ctx, f.command, f.product, f.payload)
    token = getattr(f.payload, "approval_token" if kind == "review" else "confirmation_token")
    proof = Confirmation(
        id=uid("root-integrated-" + kind),
        tenant_id=f.ctx.tenant_id,
        category_id=f.ctx.category_id,
        subject_type="product",
        product_id=f.product.id,
        actor_id=f.ctx.actor_id,
        subject_id=f.product.id,
        operation=f.command.operation,
        revision=f.product.revision,
        token_hash=digest(token),
        payload_digest=common.material_digest(f.ctx, f.command, f.payload, fact_service),
        snapshot=deepcopy(preview),
        created_at=f.clock.at - timedelta(seconds=1),
        expires_at=f.clock.at + timedelta(minutes=10),
        consumed=False,
    )
    make_transient_to_detached(proof)
    f.s.add(proof)
    phase, review = fact_service.prepare_write_review(
        f.s, f.ctx, f.command, f.product, f.payload, proof=proof
    )
    monkeypatch.setattr(common, "confirmation_for", lambda *_, **__: proof)
    trace = []
    capture = fact_consumption.ConsumptionHost.capture_after_transition
    phase_check = fact_service._phase

    def actual_capture(host, *args, **kwargs):
        assert proof.consumed is True
        trace.append("actual-first-capture")
        return capture(host, *args, **kwargs)

    def checked_phase(*args, **kwargs):
        if proof.consumed is True:
            trace.append("phase-after-capture")
        return phase_check(*args, **kwargs)

    monkeypatch.setattr(
        fact_consumption.ConsumptionHost, "capture_after_transition", actual_capture
    )
    monkeypatch.setattr(fact_service, "_phase", checked_phase)
    for method in ("execute", "scalar", "scalars", "flush"):
        monkeypatch.setattr(
            f.s, method, lambda *_, **__: pytest.fail("Consumption must not perform SQL")
        )
    consumption = common.consume_material_confirmation(
        f.s,
        f.ctx,
        f.command,
        f.product,
        f.payload,
        fact_service,
        prepared_review=review,
        write_phase=phase,
    )
    assert trace[:2] == ["actual-first-capture", "phase-after-capture"]
    row, family, visibility = fact_service.apply_prepared_write(
        f.s, f.ctx, f.command, f.product, f.payload, phase, consumption=consumption
    )
    assert family == commands.SPECS[kind][2] and visibility == f.payload.visibility
    assert row.shared_proof_id == proof.id and row.fact_body["body"]["kind"] == kind
    assert row.input_snapshot["shared_proof"]["tier"] == ("T1" if kind == "observation" else "T2")
    f.s.close()


def test_actual_series_replay_reads_current_but_new_revision_cannot_skip_parent(monkeypatch):
    f = make_world(monkeypatch)
    actual = owner.ActualFactOwner()
    old = f.payload.rule.model_copy(update={"id": uid("old-observation"), "revision": 1})
    current = old.model_copy(update={"id": uid("current-observation"), "revision": 2})
    payload = f.payload.model_copy(update={"previous": old})
    pointer = SimpleNamespace(
        id=uid("actual-observation-pointer"),
        series_id=old.id,
        fact_id=current.id,
        fact_revision=2,
        epoch=2,
    )
    statements = []

    def query(statement):
        statements.append(statement)
        return (pointer,)

    monkeypatch.setattr(f.s, "scalars", query)
    stored = SimpleNamespace(
        registry=SimpleNamespace(current_ref=current, state="historical_registered")
    )
    monkeypatch.setattr(owner, "read_stored_fact", lambda *_, **__: stored)
    result = actual._series(
        f.s,
        f.ctx,
        f.product.id,
        "observation",
        payload,
        f.fixed,
        f.material.body_material.issuer,
        new_write=False,
    )
    assert result.fact == current and result.epoch == 2
    statement = statements[-1]
    assert statement._limit_clause.value == 2
    assert statement.get_execution_options()["populate_existing"] is True
    assert statement.get_execution_options()["autoflush"] is False
    rejects(
        "VERSION_CONFLICT",
        lambda: actual._series(
            f.s,
            f.ctx,
            f.product.id,
            "observation",
            payload,
            f.fixed,
            f.material.body_material.issuer,
            new_write=True,
        ),
    )
    assert not f.s.new
    f.s.close()


def test_uploaded_artifact_content_is_not_claimed_as_verified_observation_bytes(monkeypatch):
    f = make_world(monkeypatch)
    row, ref = source_line(monkeypatch, f, json.dumps(observation_line(f)))
    row.original_id = uid("actual-upload-not-native")
    rejects("FACT_OBSERVATION_SOURCE_OWNER_REQUIRED", lambda: invoke_original(f, ref))
    assert not f.s.new
    f.s.close()


@pytest.mark.parametrize("actual,wanted", [(True, 1), (1.0, 1), (None, "null")])
def test_root_original_material_helper_keeps_json_types_exact(actual, wanted):
    assert owner.same_original_material({"raw": actual}, {"raw": wanted}) is False
    assert owner.same_original_material({"raw": actual}, {"raw": actual}) is True


def test_root_original_clock_normalization_is_only_for_declared_actual_fields():
    actual = {"at": "2026-10-03T08:01:02.123457Z", "raw": "2026-10-03T08:01:02.123457Z"}
    expected = {"at": "2026-10-03T01:01:02.123457-07:00", "raw": actual["raw"]}
    assert owner.same_original_material(actual, expected, clock_paths=(("at",),))
    assert not owner.same_original_material(actual, expected)
    assert not owner.same_original_material(
        {**actual, "at": "2026-10-03T08:01:02.123457"}, expected, clock_paths=(("at",),)
    )
    assert not owner.same_original_material(
        {**actual, "at": "2026-10-03T08:01:02.123458Z"}, expected, clock_paths=(("at",),)
    )
    assert not owner.same_original_material(
        actual, {**expected, "raw": expected["at"]}, clock_paths=(("at",),)
    )


@pytest.mark.parametrize("changed", [False, True])
def test_registered_rule_publisher_checks_actual_full_material_not_python_bool_equal(
    monkeypatch, changed
):
    f = make_world(monkeypatch, "rule")
    payload_raw = f.payload.model_dump(mode="json")
    payload_raw["rule_material"]["minimum"] = 1
    payload = commands.RulePublicationInput.model_validate(payload_raw)
    fields = {
        "origin",
        "previous",
        "external_id",
        "policy_ref",
        "method",
        "criterion",
        "sampling",
        "rule_material",
        "independence_material",
        "valid_from",
        "valid_until",
        "visibility",
    }
    actual = {
        "schema_version": "pdos-capa-rule-publication-source-v1",
        "nature": "synthetic",
        "scope": f.fixed.origin.scope.model_dump(mode="json"),
        "issue_id": str(payload.issue_id),
        "capa_id": str(payload.capa_id),
        "purpose": f.fixed.origin.purpose,
        "material": payload.model_dump(mode="json", include=fields),
    }
    if changed:
        actual["material"]["rule_material"]["minimum"] = True
    _, ref = source_line(monkeypatch, f, json.dumps(actual, separators=(",", ":")))
    payload = payload.model_copy(update={"sources": (ref,)})
    issuer = capa_rule_publisher.SyntheticRuleIssuer(
        f.ctx.tenant_id,
        f.product.id,
        f.fixed.origin.scope.project_id,
        "explicit-pure-publisher",
        "v1",
        1,
    )
    f.s.get_bind()._pdos_capa_rule_issuers = {issuer.key: issuer}
    publisher = capa_rule_publisher.RegisteredSyntheticRulePublisher(issuer)
    monkeypatch.setattr(capa_rule_publisher, "datetime", fact_consumption.datetime)
    monkeypatch.setattr(
        f.s, "scalars", lambda *_: (SimpleNamespace(id=uid("exact-candidate-row")),)
    )
    monkeypatch.setattr(
        capa_rule_publisher.candidate_storage,
        "read_candidate",
        lambda *_, **__: SimpleNamespace(body=SimpleNamespace(stable_anchor=f.fixed)),
    )
    if changed:
        rejects(
            "FACT_RULE_ORIGINAL_MISMATCH", lambda: publisher.read(f.s, f.ctx, f.product.id, payload)
        )
    else:
        result = publisher.read(f.s, f.ctx, f.product.id, payload)
        assert result.anchor == f.fixed and result.issuer.nature == "synthetic"
        assert result.inspection["production_qualified"] is False
        assert result.valid_until == payload.valid_until
    assert not f.s.new
    f.s.close()


@pytest.mark.parametrize("kind", ["observation", "review", "rule"])
def test_actual_common_tail_flushes_fact_before_deferred_current_pointer(monkeypatch, kind):
    f = make_world(monkeypatch, kind)
    publisher = object()
    if kind == "rule":
        f.host.owner.publisher = publisher  # Explicit trusted-owner substitute only.
    runtime = fact_service.configure(f.s.get_bind(), f.host.owner)
    f.host = runtime.host
    monkeypatch.setattr(fact_service, "datetime", fact_consumption.datetime)
    if kind != "rule":
        view = fact_service.preview_view(f.s, f.ctx, f.command, f.product, f.payload)
        token = getattr(f.payload, "approval_token" if kind == "review" else "confirmation_token")
        proof = Confirmation(
            id=uid("tail-proof-" + kind),
            tenant_id=f.ctx.tenant_id,
            category_id=f.ctx.category_id,
            subject_type="product",
            product_id=f.product.id,
            actor_id=f.ctx.actor_id,
            subject_id=f.product.id,
            operation=f.command.operation,
            revision=f.product.revision,
            token_hash=digest(token),
            payload_digest=common.material_digest(f.ctx, f.command, f.payload, fact_service),
            snapshot=view,
            created_at=f.clock.at - timedelta(seconds=1),
            expires_at=f.clock.at + timedelta(minutes=10),
            consumed=False,
        )
        make_transient_to_detached(proof)
        f.s.add(proof)
        monkeypatch.setattr(common, "confirmation_for", lambda *_, **__: proof)
        monkeypatch.setattr(fact_service, "confirmation_for", lambda *_, **__: proof)
    flushes, facts = [], []

    def scalar(statement):
        return f.product if statement.column_descriptions[0]["entity"] is Product else None

    def flush(objects=None):
        flushes.append(objects)
        if len(flushes) == 1:
            assert isinstance(objects, list) and len(objects) == 1
            fact = objects[0]
            assert fact.fact_kind == kind and fact.anchor_snapshot == f.fixed.model_dump(
                mode="json"
            )
            assert fact.payload_sha256 and fact.operation == f.command.operation
            facts.append(fact)
        elif len(flushes) == 2:
            assert objects is None and len(facts) == 1

    def receipt(*args):
        assert len(flushes) >= 2 and args[4] is facts[0]
        assert args[3] == commands.SPECS[kind][2]
        return SimpleNamespace(id=uid("actual-tail-receipt-" + kind))

    original_get = f.s.get
    monkeypatch.setattr(
        f.s,
        "get",
        lambda model, identity, **kw: (
            SimpleNamespace(id=f.ctx.category_id, tenant_id=f.ctx.tenant_id)
            if model is Category
            else original_get(model, identity, **kw)
        ),
    )
    monkeypatch.setattr(f.s, "scalar", scalar)
    monkeypatch.setattr(f.s, "flush", flush)
    monkeypatch.setattr(common, "require_access", lambda *_, **__: f.product)
    monkeypatch.setattr(common, "check_run", lambda *_, **__: None)
    monkeypatch.setattr(common, "check_qualification", lambda *_, **__: None)
    monkeypatch.setattr(common, "source_for", lambda *_, **__: None)
    monkeypatch.setattr(common, "prove_sources", lambda *_, **__: None)
    monkeypatch.setattr(common, "append_receipt", receipt)
    monkeypatch.setattr(common, "remember_key", lambda *_, **__: None)
    monkeypatch.setattr(common, "receipt_view", lambda r: {"id": str(r.id)})
    if kind == "rule":
        monkeypatch.setattr(capa_rule_import, "require_access", common.require_access)
        monkeypatch.setattr(capa_rule_import, "append_receipt", receipt)
        monkeypatch.setattr(capa_rule_import, "receipt_view", common.receipt_view)
        result = capa_rule_import.publish_rule(f.s, f.ctx, f.command, publisher=publisher)
        assert facts[0].shared_proof_id is None and facts[0].proof_consumed_at is None
    else:
        result = common.execute(f.s, f.ctx, f.command)
        assert proof.consumed is True and facts[0].shared_proof_id == proof.id
    assert result["id"] == str(uid("actual-tail-receipt-" + kind))
    assert flushes[0] == [facts[0]] and flushes[1] is None
    f.s.close()


@pytest.mark.parametrize(
    "change",
    ["registry_revoke", "publisher_callback", "review_callback", "paired_revoke", "paired_epoch"],
)
def test_actual_owner_runtime_fingerprint_detects_late_internal_owner_changes(monkeypatch, change):
    f = make_world(monkeypatch)
    issuer = capa_rule_publisher.SyntheticRuleIssuer(
        f.ctx.tenant_id,
        f.product.id,
        f.fixed.origin.scope.project_id,
        "explicit-runtime-publisher",
        "v1",
        1,
    )
    engine = f.s.get_bind()
    engine._pdos_capa_rule_issuers = {issuer.key: issuer}
    publisher = capa_rule_publisher.RegisteredSyntheticRulePublisher(issuer)
    review = SimpleNamespace(read=lambda *_, **__: None)
    actual = owner.ActualFactOwner(publisher=publisher, review_owner=review)
    paired = SimpleNamespace(runtime={"epoch": 1}, read=lambda *_, **__: None)
    engine._pdos_paired_followup_owner = paired
    # ResultBridge runtime is separately owned; isolate this registry seam only.
    monkeypatch.setattr(owner, "_runtime_stamp", lambda _s: digest("fixed separate bridge stamp"))
    before = actual.runtime_stamp(f.s)
    if change == "registry_revoke":
        engine._pdos_capa_rule_issuers = {}
    elif change == "publisher_callback":
        publisher.current = lambda *_, **__: None
    elif change == "review_callback":
        review.read = lambda *_, **__: None
    elif change == "paired_revoke":
        engine._pdos_paired_followup_owner = None
    else:
        paired.runtime["epoch"] = 3
    assert actual.runtime_stamp(f.s) != before
    assert not f.s.new
    f.s.close()
