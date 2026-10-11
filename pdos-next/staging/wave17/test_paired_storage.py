"""Real ORM/owner functions with explicit no-DB SELECT substitutes.

This checks storage normalization and rejection, never real ACL grants, bytes,
retained execution, SQL enforcement or publicly usable professional authority.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import paired as p
import paired_storage as storage
import pytest
import test_paired as samples
from pdos_next import service as common
from pdos_next.domain.builds.models import Build
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (
    TestResultActionFact as ActionORM,
)
from pdos_next.domain.verification_results.models import (
    TestResultProjection as ProjectionORM,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Grant, Outbox, Principal, Product, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import DocumentRequirement, SourceRef
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators


def owner_shape(row):
    """Add explicit synthetic handoff/professional facts to real owner shape.

    The previous structural fixture deliberately didn't claim those host facts.
    These synthetic data let the real _snapshot checks run, without monkeypatching
    them or interpreting the added metadata as a genuine professional approval.
    """
    request = row.snapshot
    timeline = request.timeline.model_copy(
        update={
            "offered": samples.tf(samples.ev("offered", 100), samples.OWNER, 101),
            "accepted": request.acceptances[-1].at,
        }
    )
    documents = request.documents + tuple(
        DocumentRequirement(
            id=storage.front.professional_key(item.id),
            title=f"synthetic method {item.id}",
            item_ids=(item.id,),
            source=SourceRef(
                kind="domain",
                id=samples.uid(f"applicability:{item.id}"),
                revision=1,
                position=storage.front.METHOD_POSITION,
            ),
        )
        for item in request.items
    )
    request = request.model_copy(update={"timeline": timeline, "documents": documents})
    return row.model_copy(
        update={"snapshot": request, "snapshot_sha256": p.digest(request.model_dump(mode="json"))}
    )


def actual_material(operation):
    binding, material = samples.saved(operation)
    material = material.model_copy(
        update={
            name: owner_shape(getattr(material, name))
            for name in ("origin_request", "request_before", "request_after")
        }
    )
    reads = p._merged_reads([p._artifact_refs(material.model_dump(mode="json"))])
    material = material.model_copy(
        update={
            name: getattr(material, name).model_copy(update={"reads": reads})
            for name in (
                "origin_request",
                "request_before",
                "request_after",
                "run_before",
                "run_after",
                "fact",
                "projection",
                "projection_run",
            )
            if getattr(material, name) is not None
        }
    )
    assert p.verify_paired_material(binding, material, at=samples.AT).proof
    return binding, material


class SelectMemory:
    """Understand only the actual reader's ORM equality SELECTs; no SQL effects."""

    def __init__(self, rows):
        self.rows = {}
        self.queries = []
        self.hook = None
        for row in rows:
            self.add(row)

    def add(self, row):
        group = self.rows.setdefault(type(row), [])
        if not any(existing.id == row.id for existing in group):
            group.append(row)

    def drop(self, model):
        self.rows[model] = []

    def first(self, model):
        return self.rows[model][0]

    def _matches(self, row, expression):
        if expression.operator is operators.and_:
            return all(self._matches(row, child) for child in expression.clauses)
        assert expression.operator is operators.eq, "New SQL requires an explicit substitute."
        if getattr(expression.right, "name", None) == "category_for_product":
            product_id = next(iter(expression.right.clauses)).value
            return row.category_id == next(
                value.category_id for value in self.rows[Product] if value.id == product_id
            )
        assert hasattr(expression.right, "value"), "No fabricated SQL expression truth."
        return getattr(row, expression.left.key) == expression.right.value

    def selected(self, statement):
        assert statement.is_select
        self.queries.append(statement)
        model = statement.column_descriptions[0]["entity"]
        assert model in self.rows, f"Unconfigured ORM model {model.__name__}"
        if self.hook:
            self.hook(model, statement)
        matches = [
            row
            for row in self.rows[model]
            if all(self._matches(row, clause) for clause in statement._where_criteria)
        ]
        limit = statement._limit_clause
        return matches if limit is None else matches[: limit.value]

    def scalar(self, statement):
        matches = self.selected(statement)
        return matches[0] if matches else None

    def scalars(self, statement):
        return self.selected(statement)

    def execute(self, statement):
        assert [value["entity"] for value in statement.column_descriptions] == [Principal, Grant]
        self.queries.append(statement)
        values = []
        for person in self.rows[Principal]:
            for grant in self.rows[Grant]:
                if (person.id, person.tenant_id) != (grant.principal_id, grant.tenant_id):
                    continue
                matches = True
                for clause in statement._where_criteria:
                    row = person if clause.left.table.name == Principal.__tablename__ else grant
                    actual = getattr(row, clause.left.key)
                    expected = clause.right.value
                    if clause.operator is operators.in_op:
                        matches = matches and actual in expected
                    else:
                        assert clause.operator is operators.eq
                        matches = matches and actual == expected
                if matches:
                    values.append((person, grant))
        return SimpleNamespace(all=lambda: sorted(values, key=lambda value: str(value[0].id)))

    def get(self, model, identity):
        assert model in self.rows
        return next((row for row in self.rows[model] if row.id == identity), None)


def orm_rows(binding, material):
    scope = binding.scope
    base = dict(tenant_id=scope.tenant_id, product_id=scope.product_id)
    scoped = dict(**base, project_id=scope.project_id, build_id=binding.build.id)
    rows = [
        Principal(
            id=binding.caller_id,
            tenant_id=scope.tenant_id,
            kind="human",
            active=True,
            access_epoch=1,
        ),
        Product(id=scope.product_id, tenant_id=scope.tenant_id, category_id=samples.uid("category")),
        Grant(
            id=samples.uid("grant"),
            tenant_id=scope.tenant_id,
            category_id=samples.uid("category"),
            principal_id=binding.caller_id,
            can_write=True,
            expires_at=samples.AT + timedelta(days=1),
            access_epoch=1,
        ),
        Build(
            id=binding.build.id,
            **base,
            project_id=scope.project_id,
            revision=binding.build.revision,
            owner_id=samples.OWNER,
            visibility="category",
            engineering_configuration_id=binding.build.engineering_configuration.id,
            manufacturing_configuration_id=binding.build.manufacturing_configuration.id,
        ),
        EngineeringConfiguration(
            id=binding.build.engineering_configuration.id,
            **base,
            revision=binding.build.engineering_configuration.revision,
            owner_id=samples.OWNER,
            visibility="category",
        ),
        ProcessRevision(
            id=binding.build.manufacturing_configuration.id,
            **base,
            revision=binding.build.manufacturing_configuration.revision,
            owner_id=samples.OWNER,
            visibility="category",
            engineering_configuration_id=binding.build.engineering_configuration.id,
            engineering_revision=binding.build.engineering_configuration.revision,
        ),
        VerificationRunIdentity(
            id=binding.run_id,
            **scoped,
            request_id=binding.request_id,
            owner_id=material.run_after.owner_id,
            visibility=material.run_after.visibility,
        ),
        FormalVerificationCurrent(
            id=samples.uid("formal-current"),
            **base,
            request_id=binding.request_id,
            request_version_id=material.request_current.id,
            request_revision=material.request_current.revision,
        ),
        VerificationRunCurrent(
            id=samples.uid("run-current"),
            **base,
            request_id=binding.request_id,
            run_id=binding.run_id,
            run_version_id=material.run_current.id,
            run_revision=material.run_current.revision,
        ),
    ]
    for row in (material.origin_request, material.request_before, material.request_after):
        rows.append(
            FormalVerificationRequest(
                id=row.ref.id,
                **scoped,
                build_revision=binding.build.revision,
                request_id=binding.request_id,
                revision=row.ref.revision,
                previous_request_id=row.previous.id if row.previous else None,
                previous_revision=row.previous.revision if row.previous else None,
                owner_id=row.owner_id,
                visibility=row.visibility,
                status=row.snapshot.status,
                operation=row.operation,
                purpose=binding.purpose,
                request_snapshot=row.snapshot.model_dump(mode="json"),
                snapshot_sha256=row.snapshot_sha256,
                required_source_read_set=[read.model_dump(mode="json") for read in row.reads],
                authority_snapshot={"subject_id": str(row.authority_actor_id)},
                intent_digest=row.domain_intent,
                created_at=row.created_at,
            )
        )
    for row in (material.run_before, material.run_after, material.projection_run):
        if row is None:
            continue
        rows.append(
            VerificationRunVersion(
                id=row.ref.id,
                **scoped,
                build_revision=binding.build.revision,
                request_id=binding.request_id,
                request_version_id=row.origin_request.id,
                request_revision=row.origin_request.revision,
                run_id=binding.run_id,
                revision=row.ref.revision,
                previous_run_version_id=row.previous.id if row.previous else None,
                previous_revision=row.previous.revision if row.previous else None,
                owner_id=row.owner_id,
                writer_id=row.writer_id,
                visibility=row.visibility,
                operation=row.operation,
                status=row.snapshot.status,
                run_snapshot=row.snapshot.model_dump(mode="json"),
                execution_plan=row.plan.model_dump(mode="json"),
                plan_sha256=row.plan_sha256,
                snapshot_sha256=row.snapshot_sha256,
                intent_digest=row.domain_intent,
                required_source_read_set=[read.model_dump(mode="json") for read in row.reads],
                created_at=row.created_at,
            )
        )
    fact = material.fact
    fact_values = dict(
        id=fact.ref.id,
        **scoped,
        revision=fact.ref.revision,
        request_id=binding.request_id,
        run_id=binding.run_id,
        request_version_id=fact.request_before.id,
        request_revision=fact.request_before.revision,
        next_request_version_id=fact.next_request.id,
        next_request_revision=fact.next_request.revision,
        visibility=fact.visibility,
        operation=fact.operation,
        input_snapshot=deepcopy(fact.input_snapshot),
        intent_digest=fact.domain_intent,
        required_source_read_set=[read.model_dump(mode="json") for read in fact.reads],
        created_at=fact.created_at,
    )
    if isinstance(fact, p.LaunchFact):
        rows.append(
            VerificationLaunchFact(
                **fact_values,
                owner_id=fact.actor_id,
                run_version_id=fact.run.id,
                run_revision=fact.run.revision,
                kernel_event=fact.kernel_event.model_dump(mode="json"),
                snapshot_sha256=fact.snapshot_sha256,
            )
        )
    else:
        rows.append(
            ActionORM(
                **fact_values,
                owner_id=material.run_after.owner_id,
                actor_id=fact.actor_id,
                run_version_id=fact.run_before.id,
                run_revision=fact.run_before.revision,
                next_run_version_id=fact.next_run.id,
                next_run_revision=fact.next_run.revision,
                projection_id=fact.projection.id,
                event=fact.event.model_dump(mode="json"),
            )
        )
    projection = material.projection
    if projection:
        rows.append(
            ProjectionORM(
                id=projection.ref.id,
                **scoped,
                request_id=binding.request_id,
                run_id=binding.run_id,
                revision=projection.ref.revision,
                owner_id=material.run_after.owner_id,
                visibility=material.run_after.visibility,
                run_version_id=projection.run.id,
                run_revision=projection.run.revision,
                run_sha256=projection.run_sha256,
                basis_sha256=projection.basis_sha256,
                rules_version=projection.rules_version,
                rules_sha256=projection.rules_sha256,
                result=projection.result,
                computed_results=[r.model_dump(mode="json") for r in projection.computed_results],
                required_source_read_set=[r.model_dump(mode="json") for r in projection.reads],
            )
        )
    receipt = material.receipt
    rows += [
        Receipt(
            id=receipt.id,
            **base,
            command_id=receipt.command_id,
            actor_id=receipt.actor_id,
            requester_id=receipt.requester_id,
            operation=receipt.operation,
            subject_type=receipt.subject_type,
            subject_id=receipt.subject.id,
            subject_revision=receipt.subject.revision,
            visibility=receipt.visibility,
            request_digest=receipt.request_digest,
            intent_digest=receipt.common_intent,
            run_id=receipt.run_id,
            result=receipt.result.model_dump(mode="json"),
            created_at=receipt.created_at,
        ),
        RequestKey(
            id=samples.uid("original-request-key"),
            tenant_id=scope.tenant_id,
            actor_id=receipt.actor_id,
            receipt_id=receipt.id,
            key="original synthetic key",
            digest=receipt.request_digest,
        ),
    ]
    rows += [Audit(**r.model_dump()) for r in material.audits]
    rows += [
        Outbox(
            id=r.id,
            tenant_id=r.tenant_id,
            receipt_id=r.receipt_id,
            type=r.type,
            subject_id=r.subject.id,
            subject_revision=r.subject.revision,
            actor_id=r.actor_id,
            correlation_id=r.correlation_id,
            schema_version=r.schema_version,
        )
        for r in material.outbox
    ]
    return rows


def frame(monkeypatch, operation="test.run.plan"):
    binding, material = actual_material(operation)
    memory = SelectMemory(orm_rows(binding, material))
    # Explicit empty alternatives are not fabricated positive rows.
    memory.rows.setdefault(VerificationLaunchFact, [])
    memory.rows.setdefault(ActionORM, [])
    s = Session(bind=SimpleNamespace())
    s.begin()
    monkeypatch.setattr(s, "scalar", memory.scalar)
    monkeypatch.setattr(s, "scalars", memory.scalars)
    monkeypatch.setattr(s, "execute", memory.execute)
    monkeypatch.setattr(s, "get", memory.get)
    monkeypatch.setattr(storage, "now", lambda: samples.AT)
    monkeypatch.setattr(common, "now", lambda: samples.AT)
    ctx = common.Context(
        binding.scope.tenant_id, binding.caller_id, binding.caller_id,
        category_id=samples.uid("category"),
    )
    return SimpleNamespace(
        s=s,
        ctx=ctx,
        binding=binding,
        material=material,
        memory=memory,
        read=lambda **kwargs: storage.read_storage_pair(
            s, ctx, binding.scope.product_id, binding.output_ref, at=samples.AT, **kwargs
        ),
    )


@pytest.mark.parametrize("operation", tuple(p.EVENTS))
def test_real_orm_current_and_owner_snapshots_normalize_six_operations(monkeypatch, operation):
    work = frame(monkeypatch, operation)
    read = work.read()
    assert read == p.ServerPairRead(binding=work.binding, material=work.material)
    assert p.verify_paired_material(
        read.binding, read.material, at=samples.AT
    ).proof.structural_only
    assert read.material.common_material.named_actor != read.binding.caller_id
    assert not work.s.new and not work.s.dirty and not work.s.deleted
    assert all(q.is_select for q in work.memory.queries)


def test_storage_reader_never_attests_live_bytes_or_professional_authority(monkeypatch):
    work = frame(monkeypatch)
    reader = storage.StoragePairReader()
    assert not hasattr(reader, "attest")
    outcome = p.read_paired_formal_output(
        work.s,
        work.ctx,
        work.binding.scope.product_id,
        work.binding.output_ref,
        reader=reader,
        at=samples.AT,
    )
    assert outcome.missing[0].code == "INTEGRATION_REQUIRED"
    assert outcome.host_gate is None and outcome.structure is None
    assert not work.memory.queries


@pytest.mark.parametrize(
    "model,code",
    [
        (VerificationLaunchFact, "PAIR_FACT_MISSING"),
        (Receipt, "PAIR_RECEIPT_MISSING"),
        (RequestKey, "PAIR_REQUEST_PROVENANCE_MISSING"),
        (FormalVerificationCurrent, "PAIR_CURRENT_MISSING"),
        (VerificationRunCurrent, "PAIR_CURRENT_MISSING"),
    ],
)
def test_missing_exact_storage_link_is_not_guessed(monkeypatch, model, code):
    work = frame(monkeypatch)
    work.memory.drop(model)
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == code and error.value.status == 503


def test_alias_digest_does_not_replace_or_invalidate_original_request_key(monkeypatch):
    work = frame(monkeypatch)
    original = work.memory.first(RequestKey)
    alias = RequestKey(
        id=samples.uid("alias"),
        tenant_id=original.tenant_id,
        actor_id=original.actor_id,
        receipt_id=original.receipt_id,
        digest="a" * 64,
        key="new key same semantic",
    )
    work.memory.add(alias)
    assert work.read().material.receipt.id == original.receipt_id
    work.memory.rows[RequestKey] = [alias]
    with pytest.raises(DomainError, match="原回执") as error:
        work.read()
    assert error.value.code == "PAIR_REQUEST_PROVENANCE_MISSING"


@pytest.mark.parametrize("field", ["actor_id", "receipt_id", "tenant_id"])
def test_original_key_must_bind_actual_writer_receipt_and_tenant(monkeypatch, field):
    work = frame(monkeypatch)
    setattr(work.memory.first(RequestKey), field, samples.uid(f"wrong-{field}"))
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "PAIR_REQUEST_PROVENANCE_MISSING"


@pytest.mark.parametrize(
    "model,field",
    [
        (Build, "project_id"),
        (EngineeringConfiguration, "revision"),
        (ProcessRevision, "engineering_revision"),
        (VerificationRunIdentity, "request_id"),
    ],
)
def test_actual_build_configuration_and_logical_identity_are_bound(monkeypatch, model, field):
    work = frame(monkeypatch)
    row = work.memory.first(model)
    setattr(row, field, 99 if "revision" in field else samples.uid("wrong-scope"))
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "PAIR_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "model",
    [
        Build,
        EngineeringConfiguration,
        ProcessRevision,
        FormalVerificationRequest,
        VerificationRunVersion,
        VerificationRunIdentity,
    ],
)
def test_each_real_private_ancestor_remains_unreadable_to_peer(monkeypatch, model):
    work = frame(monkeypatch)
    work.memory.first(model).visibility = "private"
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "FORBIDDEN_SCOPE" and error.value.status == 403


@pytest.mark.parametrize("mode", ["inactive", "agent", "expired", "no-write"])
def test_current_actor_and_grant_gate_are_real_owner_calls(monkeypatch, mode):
    work = frame(monkeypatch)
    if mode == "inactive":
        work.memory.first(Principal).active = False
    elif mode == "agent":
        work.memory.first(Principal).kind = "agent"
    elif mode == "expired":
        work.memory.first(Grant).expires_at = samples.AT
    else:
        work.memory.first(Grant).can_write = False
    with pytest.raises(DomainError) as error:
        work.read(write=mode == "no-write")
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_current_origin_is_not_mistaken_for_advanced_formal(monkeypatch):
    work = frame(monkeypatch, "test.results.import")
    read = work.read()
    assert read.material.origin_request.ref != read.material.request_current
    with pytest.raises(DomainError) as error:
        storage.read_storage_pair(
            work.s,
            work.ctx,
            work.binding.scope.product_id,
            p.FormalRef(**read.material.origin_request.ref.model_dump()),
            at=samples.AT,
        )
    assert error.value.code == "PAIR_CURRENT_MISMATCH"


@pytest.mark.parametrize("mode", ["missing-semantic", "token", "domain-intent", "common-intent"])
def test_exact_original_semantic_is_not_guessed_from_snapshot(monkeypatch, mode):
    work = frame(monkeypatch)
    fact = work.memory.first(VerificationLaunchFact)
    if mode == "missing-semantic":
        fact.input_snapshot.pop("execution_plan")
    elif mode == "token":
        fact.input_snapshot["confirmation_token"] = "never expose synthetic token"
    elif mode == "domain-intent":
        fact.intent_digest = "f" * 64
    else:
        work.memory.first(Receipt).intent_digest = fact.intent_digest
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code in {
        "PAIR_ORIGINAL_SEMANTIC_MISSING",
        "PAIR_DOMAIN_INTENT_MISMATCH",
        "PAIR_COMMON_INTENT_MISMATCH",
    }


@pytest.mark.parametrize(
    "model,field",
    [
        (Receipt, "requester_id"),
        (Audit, "actor_id"),
        (Outbox, "correlation_id"),
    ],
)
def test_actual_common_group_cannot_be_substituted(monkeypatch, model, field):
    work = frame(monkeypatch)
    setattr(work.memory.first(model), field, samples.uid("wrong-original-person-or-group"))
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code in {
        "PAIR_WRITER_MISMATCH",
        "PAIR_RECEIPT_MISMATCH",
        "PAIR_ATOM_MISMATCH",
    }


def test_refresh_uses_new_actual_current_without_returning_old_success(monkeypatch):
    work = frame(monkeypatch)
    reader = storage.StoragePairReader()
    previous = reader.read(
        work.s, work.ctx, work.binding.scope.product_id, work.binding.output_ref, at=samples.AT
    )
    work.memory.first(VerificationRunCurrent).run_revision += 1
    with pytest.raises(DomainError) as error:
        reader.refresh(work.s, work.ctx, work.binding.scope.product_id, previous, at=samples.AT)
    assert error.value.code == "PAIR_FACT_MISMATCH"


def test_final_current_reread_refuses_midread_pointer_drift(monkeypatch):
    work = frame(monkeypatch)
    counts = {FormalVerificationCurrent: 0}

    def drift(model, _statement):
        if model is FormalVerificationCurrent:
            counts[model] += 1
            if counts[model] == 2:
                work.memory.first(model).request_revision += 1

    work.memory.hook = drift
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "PAIR_CURRENT_MISMATCH"


@pytest.mark.parametrize("mode", ["no-session", "no-uow", "changed-main", "changed-nested"])
def test_actual_session_and_exact_active_uow_required(monkeypatch, mode):
    work = frame(monkeypatch)
    if mode == "no-session":
        work.s = SimpleNamespace()
    elif mode == "no-uow":
        work.s.rollback()
    else:
        changed = False

        def drift(model, _statement):
            nonlocal changed
            if model is Receipt and not changed:
                changed = True
                if mode == "changed-main":
                    work.s.rollback()
                    work.s.begin()
                else:
                    work.s.begin_nested()

        work.memory.hook = drift
    with pytest.raises(DomainError) as error:
        storage.read_storage_pair(
            work.s, work.ctx, work.binding.scope.product_id, work.binding.output_ref, at=samples.AT
        )
    assert error.value.code in {"CALLER_UOW_REQUIRED", "CALLER_UOW_CHANGED"}


def test_real_compiled_sql_scopes_fact_and_original_key_before_limit(monkeypatch):
    work = frame(monkeypatch, "test.run.start")
    work.read()
    queries = {
        q.column_descriptions[0]["entity"]: q
        for q in work.memory.queries
        if q.column_descriptions[0]["entity"] in {VerificationLaunchFact, RequestKey}
    }
    for model in queries:
        compiled = queries[model].compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert sql.index("WHERE") < sql.index("LIMIT")
        assert compiled.params["tenant_id_1"] == work.ctx.tenant_id
    fact_sql = str(queries[VerificationLaunchFact].compile(dialect=postgresql.dialect()))
    assert all(
        f"verification_launch_facts.{name} =" in fact_sql
        for name in (
            "product_id",
            "project_id",
            "build_id",
            "request_id",
            "run_id",
            "next_request_version_id",
            "next_request_revision",
            "run_version_id",
            "run_revision",
        )
    )
    key_query = queries[RequestKey].compile(dialect=postgresql.dialect())
    assert key_query.params["actor_id_1"] == work.material.receipt.actor_id
    assert key_query.params["receipt_id_1"] == work.material.receipt.id
    assert key_query.params["digest_1"] == work.material.receipt.request_digest


def test_read_does_not_autoflush_caller_pending_work(monkeypatch):
    work = frame(monkeypatch)
    pending = Product(id=samples.uid("caller-pending"), tenant_id=work.ctx.tenant_id)
    work.s.add(pending)

    def query_boundary(_model, _statement):
        assert work.s.autoflush is False

    work.memory.hook = query_boundary
    assert work.read().binding == work.binding
    assert pending in work.s.new and work.s.autoflush is True


def test_two_genuine_active_savepoints_preserve_complete_identity_chain(monkeypatch):
    work = frame(monkeypatch)
    root = work.s.get_transaction()
    outer = work.s.begin_nested()
    inner = work.s.begin_nested()
    assert storage._uow(work.s)[:2] == (root, (inner, outer))
    assert work.read().material == work.material
    assert work.s.get_nested_transaction() is inner and inner.parent is outer


def test_actual_rollback_deactive_session_cannot_read_before_caller_restoration(monkeypatch):
    work = frame(monkeypatch)
    nested = work.s.begin_nested()
    caught = []

    @event.listens_for(work.s, "after_rollback")
    def while_inactive(session):
        assert session.is_active is False
        with pytest.raises(DomainError) as error:
            storage._uow(session)
        caught.append(error.value.code)

    nested.rollback()
    assert caught == ["CALLER_UOW_REQUIRED"]
    assert work.s.is_active and work.s.get_nested_transaction() is None


def test_active_but_unbound_storage_session_is_explicit_missing():
    s = Session()
    s.begin()
    with pytest.raises(DomainError) as error:
        storage._uow(s)
    assert error.value.code == "CALLER_UOW_REQUIRED"
    assert not s.get_transaction()._connections


@pytest.mark.parametrize(
    "mode", ["placeholder", "foreign-session", "foreign-root", "cycle", "inactive-ancestor"]
)
def test_savepoint_ancestry_cannot_be_fabricated_or_partly_active(monkeypatch, mode):
    work = frame(monkeypatch)
    outer = work.s.begin_nested()
    inner = work.s.begin_nested()
    if mode == "placeholder":
        monkeypatch.setattr(work.s, "get_transaction", lambda: SimpleNamespace(is_active=True))
    elif mode == "foreign-session":
        monkeypatch.setattr(outer, "session", Session())
    elif mode == "foreign-root":
        foreign = Session()
        foreign.begin()
        monkeypatch.setattr(outer, "_parent", foreign.get_transaction())
    elif mode == "cycle":
        monkeypatch.setattr(outer, "_parent", inner)
    else:
        from sqlalchemy.orm.session import SessionTransactionState

        monkeypatch.setattr(outer, "_state", SessionTransactionState.DEACTIVE)
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "CALLER_UOW_REQUIRED"
    assert not work.memory.queries


def test_changed_context_cannot_return_a_pair_from_another_caller(monkeypatch):
    work = frame(monkeypatch)

    def drift(model, _statement):
        if model is Receipt:
            object.__setattr__(work.ctx, "cancel_epoch", 7)

    work.memory.hook = drift
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "CALLER_UOW_CHANGED"


def test_expiry_during_storage_read_is_checked_with_fresh_real_clock(monkeypatch):
    work = frame(monkeypatch)
    clock = [samples.AT]
    grant = work.memory.first(Grant)
    grant.expires_at = samples.AT + timedelta(seconds=1)
    monkeypatch.setattr(storage, "now", lambda: clock[0])
    monkeypatch.setattr(common, "now", lambda: clock[0])

    def cross_deadline(model, _statement):
        if model is Outbox:
            clock[0] += timedelta(seconds=2)

    work.memory.hook = cross_deadline
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("model", [VerificationLaunchFact, Receipt, Audit, Outbox])
def test_exact_pair_and_atom_require_unique_rows(monkeypatch, model):
    work = frame(monkeypatch)
    original = work.memory.first(model)
    values = {
        column.key: deepcopy(getattr(original, column.key)) for column in model.__table__.columns
    }
    values["id"] = samples.uid(f"duplicate-{model.__name__}")
    work.memory.add(model(**values))
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code in {"PAIR_FACT_MISSING", "PAIR_RECEIPT_MISSING", "PAIR_ATOM_MISSING"}


def test_projection_private_scope_and_actual_version_are_not_assumed(monkeypatch):
    work = frame(monkeypatch, "test.results.import")
    projection = work.memory.first(ProjectionORM)
    projection.visibility = "private"
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "FORBIDDEN_SCOPE"
    projection.visibility = "category"
    projection.run_revision = 99
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.code == "PAIR_FACT_MISMATCH"
