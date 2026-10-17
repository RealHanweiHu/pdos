"""No-connect release publication IO fixtures, not professional qualification.

Registered original parsers, immutable hash/proof bindings, actual scope and
metadata readers run unchanged. SQL SELECT/flush and signature-current IO are
explicit fixtures; these tests do not attest PostgreSQL/RLS or real approval.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from manufacturing_trials.test_native_statistics_owner import original
from sqlalchemy import select

from pdos_next.domain.release import policy_owner as owner
from pdos_next.domain.release.policy_models import ReleasePolicyCurrent as Current
from pdos_next.domain.release.policy_models import ReleasePolicyFact as Fact
from pdos_next.domain.release.policy_schemas import PolicyImport, PolicyMaterial
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Outbox, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import digest


@pytest.fixture
def work(request, monkeypatch):
    world = request.getfixturevalue("native_world")
    s, execute = world.s, world.s.execute

    def columns(statement, *args, **kwargs):
        descriptions = statement.column_descriptions
        models = {value["entity"] for value in descriptions}
        if len(models) != 1 or descriptions[0]["expr"] is descriptions[0]["entity"]:
            return execute(statement, *args, **kwargs)
        model = next(iter(models))
        rows = s.scalars(select(model).where(*statement._where_criteria))
        return SimpleNamespace(
            mappings=lambda: [
                {column.key: getattr(row, column.key) for column in statement.selected_columns}
                for row in rows
            ]
        )

    monkeypatch.setattr(s, "execute", columns)
    scope = Scope(tenant_id=world.ctx.tenant_id, product_id=world.pid, project_id=world.project.id)
    material = PolicyMaterial(
        schema_version="pdos-release-policy-v1",
        scope=scope,
        category_id=world.ctx.category_id,
        subject_config={
            "definition": {
                "id": world.engineering.definition_id,
                "revision": world.engineering.definition_revision,
            },
            "engineering_configuration": {
                "id": world.engineering.id,
                "revision": world.engineering.revision,
            },
            "manufacturing_configuration": {
                "id": world.process.id,
                "revision": world.process.revision,
            },
        },
        release_scope={"quantity": "2", "unit": "ea"},
        purpose=world.project.purpose,
        policy_version="synthetic-v1",
        publisher_id=world.ctx.requester_id,
        owner_id=world.project.owner_id,
        visibility="private",
        nature="synthetic",
        status="active",
        valid_from=None,
        valid_until=None,
        rules=tuple(
            {
                "id": role + "-document",
                "version": "v1",
                "scope": {"quantity": "2", "unit": "ea"},
                "discipline": role,
                "applicable_if": {"op": "always"},
                "predicate": {"op": "document_present", "kind": "artifact"},
                "required_evidence": ["artifact"],
                "freshness": "current",
                "severity": "required",
                "responsible_role": role,
                "waivable": False,
                "allowed_purpose": [world.project.purpose],
            }
            for role in ("engineering", "manufacturing")
        ),
    )
    result = SimpleNamespace(
        **vars(world),
        scope=scope,
        material=material,
        reader=owner.ActualReleasePolicyOwner(s.get_bind()),
        signature=SimpleNamespace(current=True, calls=0),
    )

    def signature_io(*args):
        result.signature.calls += 1
        return result.signature.current

    monkeypatch.setattr(owner, "signature_current", signature_io)
    result.read = lambda: result.reader.read(
        s,
        result.ctx,
        result.pid,
        scope=scope,
        purpose=material.purpose,
        subject_config=material.subject_config,
        release_scope=material.release_scope,
        facts=getattr(result, "facts", ()),
        at=getattr(result, "at", datetime.now(UTC)),
    )
    return result


def rejects(call, code):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def saved_policy(work, *, material=None, previous=None):
    """Synthetic immutable SQL rows and common proof, with real source reader."""
    material = material or work.material
    source = original(work, material.model_dump(mode="json"))
    reads = [{"artifact_id": str(source.id), "expected_revision": source.revision}]
    basis = owner.evidence._evidence(work.s, work.ctx, work.pid, reads, (source,), io=False)[0]
    identity, receipt_id, command = uuid4(), uuid4(), uuid4()
    auth = {
        "scope": work.scope.model_dump(mode="json"),
        "subject_id": str(work.ctx.requester_id),
        "operation": owner.POLICY_OPERATION,
        "purpose": material.purpose,
        "fact_refs": [{"explicit": "signature Current IO fixture"}],
    }
    data = PolicyImport(
        project_id=work.project.id,
        source=source.model_dump(mode="json"),
        expected_previous={"id": previous.id, "revision": previous.revision} if previous else None,
        reason="explicit synthetic policy publication",
    )
    fingerprint = digest(str(command))
    row = Fact(
        id=identity,
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        product_id=work.pid,
        project_id=work.project.id,
        purpose=material.purpose,
        purpose_sha256=digest(material.purpose),
        policy_version=material.policy_version,
        series_id=previous.series_id if previous else identity,
        revision=previous.revision + 1 if previous else 1,
        epoch=previous.epoch + 1 if previous else 1,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        owner_id=material.owner_id,
        writer_id=work.ctx.actor_id,
        actor_id=work.ctx.actor_id,
        requester_id=work.ctx.requester_id,
        visibility=material.visibility,
        status=material.status,
        nature=material.nature,
        operation=owner.POLICY_OPERATION,
        command_id=command,
        receipt_id=receipt_id,
        intent_digest=fingerprint,
        request_digest=fingerprint,
        material=material.model_dump(mode="json"),
        material_sha256=digest(material.model_dump(mode="json")),
        source=source.model_dump(mode="json"),
        sources=[source.model_dump(mode="json")],
        required_source_read_set=reads,
        source_basis=basis,
        authority_snapshot=auth,
        input_snapshot={
            "payload": data.model_dump(mode="json"),
            "original_key_sha256": digest("fixture-key"),
        },
        valid_from=material.valid_from,
        valid_until=material.valid_until,
        created_at=datetime.now(UTC),
    )
    row.fact_sha256 = owner.fact_hash(row)
    work.s.add_row(row)
    pointers = work.s.rows.setdefault(Current, [])
    pointer = next(iter(pointers), None)
    if pointer:
        pointer.fact_id, pointer.revision, pointer.epoch = row.id, row.revision, row.epoch
    else:
        work.s.add_row(
            Current(
                id=uuid4(),
                tenant_id=work.ctx.tenant_id,
                category_id=work.ctx.category_id,
                product_id=work.pid,
                project_id=work.project.id,
                purpose_sha256=row.purpose_sha256,
                series_id=row.series_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                fact_id=row.id,
                revision=row.revision,
                epoch=row.epoch,
            )
        )
    receipt = Receipt(
        id=receipt_id,
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        product_id=work.pid,
        command_id=command,
        actor_id=row.actor_id,
        requester_id=row.requester_id,
        operation=owner.POLICY_OPERATION,
        subject_type=owner.POLICY_FAMILY,
        subject_id=row.id,
        subject_revision=row.revision,
        visibility=row.visibility,
        request_digest=fingerprint,
        intent_digest=fingerprint,
        run_id=None,
        agent_run_id=None,
        confirmation_id=None,
        result={"id": str(row.id), "revision": row.revision, "status": row.status},
        created_at=datetime.now(UTC),
    )
    work.s.add_row(receipt)
    work.s.add_row(
        Audit(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            receipt_id=receipt_id,
            actor_id=row.actor_id,
            operation=owner.POLICY_OPERATION,
        )
    )
    work.s.add_row(
        Outbox(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            receipt_id=receipt_id,
            type=owner.POLICY_EVENT,
            subject_id=row.id,
            subject_revision=row.revision,
            actor_id=row.actor_id,
            correlation_id=command,
        )
    )
    work.s.add_row(
        RequestKey(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            actor_id=row.actor_id,
            key="explicit-fixture-key-" + str(identity),
            digest=fingerprint,
            receipt_id=receipt_id,
        )
    )
    work.facts = (
        {
            "ref": {"kind": "artifact", "id": source.id, "revision": source.revision},
            "value": {"_release_current": True},
        },
    )
    return row, source


def test_missing_policy_preserves_empty_current_watermark(work):
    read = work.read()
    assert read.policy is None and read.checks == () and read.gaps == ("RELEASE_POLICY_MISSING",)
    assert read.source_basis["pointer"] is None
    assert work.reader.current(work.s, work.ctx, work.pid, read)
    saved_policy(work)
    assert work.reader.current(work.s, work.ctx, work.pid, read) is False


def test_actual_policy_read_uses_no_original_bytes_or_historical_assessment(work, monkeypatch):
    row, source = saved_policy(work)

    def forbidden(*args, **kwargs):
        raise AssertionError("A retained policy must use metadata/signature watermarks only")

    monkeypatch.setattr(owner, "_original", forbidden)
    monkeypatch.setattr(owner.evidence, "_evidence", forbidden)
    monkeypatch.setattr(owner.professional, "assess", forbidden)
    read = work.read()
    assert read.policy.version == work.material.policy_version
    assert {check.state for check in read.checks} == {"satisfied"}
    assert read.sources == (source,) and read.required_source_read_set[0].artifact_id == source.id
    assert read.source_basis["fact"]["sha256"] == row.fact_sha256
    assert work.reader.current(work.s, work.ctx, work.pid, read)
    persisted = deepcopy(read.source_basis)
    work.s.rollback()
    work.s.begin()
    assert work.reader.current(work.s, work.ctx, work.pid, persisted)
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, read), "FACT_CALLER_UOW_CHANGED"
    )


def test_cached_read_is_opaque_and_does_not_collect_again(work, monkeypatch):
    saved_policy(work)
    work.at = datetime.now(UTC)
    read = work.read()
    count = len(work.s.queries)
    assert work.read() is read and len(work.s.queries) == count
    forged = replace(read)
    rejects(lambda: work.reader.current(work.s, work.ctx, work.pid, forged), "SOURCE_STALE")
    read.source_basis["purpose"] = "changed"
    rejects(lambda: work.reader.current(work.s, work.ctx, work.pid, read), "SOURCE_STALE")


@pytest.mark.parametrize("fault", ["source", "signature", "pointer", "fact"])
def test_direct_change_invalidates_retained_policy_without_rebuilding_facts(work, fault):
    row, source = saved_policy(work)
    read = work.read()
    if fault == "source":
        work.s.get(Artifact, source.id).status = "withdrawn"
    elif fault == "signature":
        work.signature.current = False
    elif fault == "pointer":
        saved_policy(work, previous=row)
    else:
        row.fact_sha256 = "0" * 64
    assert work.reader.current(work.s, work.ctx, work.pid, read.source_basis) is False


def test_fact_hash_and_common_tail_are_checked_before_policy_evaluation(work):
    row, _ = saved_policy(work)
    row.material["policy_version"] = "tampered"
    rejects(work.read, "INTEGRITY_MISMATCH")
    row.material["policy_version"] = work.material.policy_version
    # Select the policy Outbox, because the base fixture includes other groups.
    policy_outbox = next(v for v in work.s.rows[Outbox] if v.receipt_id == row.receipt_id)
    policy_outbox.type = "unrelated.event"
    rejects(work.read, "IMPLEMENTATION_GROUP_MISMATCH")


def test_future_and_withdrawn_publication_remain_unknown_without_blocking_read(work, monkeypatch):
    at = datetime.now(UTC)
    material = work.material.model_copy(update={"valid_from": at + timedelta(days=1)})
    row, _ = saved_policy(work, material=material)
    work.at = at
    monkeypatch.setattr(owner, "now", lambda: at)
    read = work.read()
    assert read.policy and {check.state for check in read.checks} == {"unknown"}
    assert work.reader.current(work.s, work.ctx, work.pid, read)
    monkeypatch.setattr(owner, "now", lambda: at + timedelta(days=2))
    assert work.reader.current(work.s, work.ctx, work.pid, read.source_basis) is False
    withdrawn = material.model_copy(
        update={"status": "withdrawn", "policy_version": "withdrawal-v2", "valid_from": None}
    )
    saved_policy(work, material=withdrawn, previous=row)
    fresh = work.read()
    assert fresh.policy.version == "withdrawal-v2" and {check.state for check in fresh.checks} == {
        "unknown"
    }


def test_hash_normalizes_database_timestamp_zone_without_changing_original(work):
    at = datetime.now(UTC)
    row, _ = saved_policy(work, material=work.material.model_copy(update={"valid_from": at}))
    expected = row.fact_sha256
    row.valid_from = at.astimezone(timezone(timedelta(hours=8)))
    assert owner.fact_hash(row) == expected


@pytest.mark.parametrize("fault", ["duplicate", "extra", "hash", "registration"])
def test_policy_original_requires_closed_whole_line_and_actual_registration(work, fault):
    raw = work.material.model_dump(mode="json")
    if fault == "extra":
        raw["client_authorized"] = True
    source = original(work, raw)
    artifact = work.s.get(Artifact, source.id)
    if fault == "duplicate":
        artifact.content = artifact.content[:-1] + ',"status":"active"}'
        artifact.content_hash = digest(artifact.content)
        source = source.model_copy(
            update={
                "position": "line:1;quote_sha256:" + sha256(artifact.content.encode()).hexdigest()
            }
        )
    elif fault == "hash":
        artifact.content_hash = "0" * 64
    elif fault == "registration":
        work.s.rows[Receipt] = [row for row in work.s.rows[Receipt] if row.subject_id != source.id]
    expected = (
        "SOURCE_STALE"
        if fault == "hash"
        else "INTEGRATION_REQUIRED"
        if fault == "registration"
        else "MISSING_REQUIRED_EVIDENCE"
    )
    rejects(lambda: owner._original(work.s, work.ctx, work.pid, source), expected)


@pytest.mark.parametrize("fault", ["unconfigured", "unqualified", "nature", "publisher"])
def test_host_import_requires_current_actual_publication_authority(work, monkeypatch, fault):
    value = (
        work.material.model_copy(update={"publisher_id": uuid4()})
        if fault == "publisher"
        else work.material
    )
    source = original(work, value.model_dump(mode="json"))
    auth = {
        "authorized": fault != "unqualified",
        "qualified": fault != "unqualified",
        "reason_codes": ["PROFESSIONAL_OPERATION_NOT_CONFIGURED"]
        if fault == "unconfigured"
        else [],
        "roles": ["quality"],
        "fact_refs": [{"explicit": "current professional IO fixture"}],
        "subject_id": str(work.ctx.requester_id),
        "synthetic": fault != "nature",
        "required_source_read_set": [],
    }
    monkeypatch.setitem(owner.common.EVENTS, owner.POLICY_OPERATION, owner.POLICY_EVENT)
    monkeypatch.setattr(owner.professional, "assess", lambda *args, **kwargs: auth)
    data = PolicyImport(
        project_id=work.project.id,
        source=source.model_dump(mode="json"),
        reason="synthetic controlled publisher request",
    )
    before = {
        model: len(work.s.rows.get(model, ()))
        for model in (Fact, Current, Receipt, Audit, Outbox, RequestKey)
    }
    expected = (
        "FORBIDDEN_SCOPE"
        if fault == "publisher"
        else "INTEGRATION_REQUIRED"
        if fault == "unconfigured"
        else "QUALIFICATION_REQUIRED"
    )
    rejects(
        lambda: work.reader.import_policy(
            work.s, work.ctx, work.pid, data, command_id=uuid4(), request_key=str(uuid4())
        ),
        expected,
    )
    assert before == {model: len(work.s.rows.get(model, ())) for model in before}
    assert not (work.s.new or work.s.dirty or work.s.deleted)


def test_host_common_tail_revision_cas_and_original_or_alias_replay(work, monkeypatch):
    """Real host importer/common append; only SQL and professional IO replaced."""
    s, execute = work.s, work.s.execute
    at = datetime.now(UTC)
    monkeypatch.setitem(owner.common.EVENTS, owner.POLICY_OPERATION, owner.POLICY_EVENT)
    monkeypatch.setitem(
        owner.professional.OPERATION_ROLES, owner.POLICY_OPERATION, frozenset({"quality"})
    )
    calls = []

    def assess_io(*args, **kwargs):
        calls.append((args[5], kwargs["write"]))
        return {
            "scope": work.scope.model_dump(mode="json"),
            "subject_id": str(work.ctx.requester_id),
            "operation": owner.POLICY_OPERATION,
            "purpose": work.material.purpose,
            "authorized": True,
            "qualified": True,
            "roles": ["quality"],
            "synthetic": True,
            "reason_codes": [],
            "required_source_read_set": [],
            "fact_refs": [
                {
                    "kind": kind,
                    "state": "active",
                    "nature": "synthetic",
                    "role": "quality",
                    "operations": [owner.POLICY_OPERATION],
                    "purposes": [work.material.purpose],
                    "valid_from": (at - timedelta(hours=1)).isoformat(),
                    "valid_until": (at + timedelta(hours=1)).isoformat(),
                }
                for kind in ("duty", "qualification")
            ],
        }

    monkeypatch.setattr(owner.professional, "assess", assess_io)

    def flush_io(objects=None):
        for row in list(objects if objects is not None else s.new):
            if row.id is None:
                row.id = uuid4()
            if row.created_at is None:
                row.created_at = at
            if row.category_id is None:
                row.category_id = work.ctx.category_id
            if row not in s.rows.get(type(row), ()):
                s.add_row(row)
            if row in s:
                s.expunge(row)
        s.info.pop("request_proof", None)

    def sql_io(statement, *args, **kwargs):
        if getattr(statement, "is_insert", False):
            assert statement.table.name == RequestKey.__tablename__
            flush_io()
            values = statement.compile().params
            existing = next(
                (
                    row
                    for row in s.rows.get(RequestKey, ())
                    if (row.tenant_id, row.actor_id, row.key)
                    == (values["tenant_id"], values["actor_id"], values["key"])
                ),
                None,
            )
            if existing is None:
                key = RequestKey(**values)
                key.id, key.created_at = key.id or uuid4(), at
                s.add_row(key)
            return SimpleNamespace()
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(s, "flush", flush_io)
    monkeypatch.setattr(s, "execute", sql_io)

    def request(material, previous=None):
        source = original(work, material.model_dump(mode="json"))
        return PolicyImport(
            project_id=work.project.id,
            source=source.model_dump(mode="json"),
            expected_previous=previous,
            reason="named host controlled publication",
        )

    def publish(data, key):
        return work.reader.import_policy(
            s, work.ctx, work.pid, data, command_id=uuid4(), request_key=key
        )

    initial = request(work.material)
    first_key = str(uuid4())
    first = publish(initial, first_key)
    assert len(calls) == 1
    assert publish(initial, first_key) == first
    assert publish(initial, str(uuid4())) == first
    assert len(s.rows[Fact]) == len(s.rows[Current]) == 1
    first_row = s.rows[Fact][0]
    assert first_row.receipt_id == first_row.prepared_receipt_id
    assert first_row.fact_sha256 == owner.fact_hash(first_row)
    assert first_row.material_sha256 == digest(first_row.material)
    assert s.rows[Current][0].fact_id == first_row.id
    original_body = deepcopy(first_row.material)
    revision = request(
        work.material.model_copy(update={"status": "withdrawn", "policy_version": "v2-withdrawn"}),
        {"id": first_row.id, "revision": first_row.revision},
    )
    second = publish(revision, str(uuid4()))
    assert second["subject_revision"] == 2 and second["id"] != first["id"]
    assert s.rows[Current][0].revision == 2
    assert publish(initial, str(uuid4())) == first
    assert s.rows[Current][0].revision == 2 and first_row.material == original_body
    stale = request(
        work.material.model_copy(update={"policy_version": "stale-new-publication"}),
        {"id": first_row.id, "revision": first_row.revision},
    )
    before = {
        model: len(s.rows.get(model, ())) for model in (Fact, Receipt, Audit, Outbox, RequestKey)
    }
    rejects(lambda: publish(stale, str(uuid4())), "VERSION_CONFLICT")
    assert before == {model: len(s.rows.get(model, ())) for model in before}
    rejects(lambda: publish(revision, first_key), "DUPLICATE_INTENT_CONFLICT")
