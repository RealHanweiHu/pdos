"""Meaningful substituted-IO boundaries, never PG/qualification/external coverage evidence."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import change_controlled_owner as controlled
from pdos_next import change_coverage_binding as binding
from pdos_next import service as common
from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_coverage_owner import importer, models, owner, registry, schemas, trust
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.graph import OwnedObject
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.schemas.change_control.contracts import ChangeRequest, Edge, GraphSnapshot, Node, Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef

ACTUAL_PROJECT = controlled._project
ACTUAL_SOURCE_GUARD = controlled._source_guard
ACTUAL_EXECUTE = Session.execute


def test_temporal_current_summary_retains_future_interval_and_ordinary_grant_rules(
    env, monkeypatch
):
    for row in env.rows:
        if isinstance(row, Grant):
            row.expires_at = None
    baseline = owner.temporal(env.s, env.ctx, env.pid, env.scope)[0]
    monkeypatch.setattr(owner, "clock", lambda: env.at + timedelta(days=30))
    assert owner.temporal(env.s, env.ctx, env.pid, env.scope)[0] == baseline

    fact_id = uuid4()
    pointer = owner.ProfessionalCurrent(
        id=uuid4(),
        tenant_id=env.ctx.tenant_id,
        product_id=env.pid,
        project_id=env.scope.project_id,
        subject_id=env.ctx.requester_id,
        kind="qualification",
        issuer_key="synthetic-interval",
        external_id="fixed-interval",
        series_id=fact_id,
        fact_id=fact_id,
        fact_revision=1,
        epoch=1,
        summary={
            **{
                key: str(value)
                for key, value in {
                    "id": fact_id,
                    "tenant_id": env.ctx.tenant_id,
                    "category_id": CategoryUUID(int=1000000),
                    "product_id": env.pid,
                    "project_id": env.scope.project_id,
                    "subject_id": env.ctx.requester_id,
                    "owner_id": env.ctx.requester_id,
                    "series_id": fact_id,
                }.items()
            },
            "kind": "qualification",
            "issuer_key": "synthetic-interval",
            "external_id": "fixed-interval",
            "revision": 1,
            "fact_sha256": "1" * 64,
            "state": "active",
            "valid_from": (env.at + timedelta(minutes=1)).isoformat(),
            "valid_until": (env.at + timedelta(minutes=2)).isoformat(),
            "required_source_read_set": [],
        },
    )
    env.rows.append(pointer)
    monkeypatch.setattr(owner, "clock", lambda: env.at)
    before = owner.temporal(env.s, env.ctx, env.pid, env.scope)[0]
    monkeypatch.setattr(owner, "clock", lambda: env.at + timedelta(seconds=90))
    active = owner.temporal(env.s, env.ctx, env.pid, env.scope)[0]
    assert active != before
    monkeypatch.setattr(owner, "clock", lambda: env.at + timedelta(minutes=2))
    assert owner.temporal(env.s, env.ctx, env.pid, env.scope)[0] != active
    pointer.summary = {**pointer.summary, "revision": 2}
    with pytest.raises(DomainError):
        owner.temporal(env.s, env.ctx, env.pid, env.scope)


def append_canonical_successor(e, *, owner_id=None, visibility=None):
    """Pure IO-substituted lineage; no actual qualification or PG claim."""
    pointer = next(row for row in e.rows if isinstance(row, ChangeCurrent))
    previous = next(
        row
        for row in e.rows
        if isinstance(row, ChangeRequestVersion) and row.id == pointer.version_id
    )
    request = e.request.model_copy(update={"revision": previous.revision + 1})
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=previous.tenant_id,
        product_id=previous.product_id,
        project_id=previous.project_id,
        change_id=previous.change_id,
        revision=request.revision,
        previous_version_id=previous.id,
        previous_revision=previous.revision,
        owner_id=owner_id if owner_id is not None else previous.owner_id,
        visibility=visibility if visibility is not None else previous.visibility,
        status=request.status,
        operation="change.impact.compute",
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=digest(request),
    )
    e.rows.append(row)
    pointer.version_id, pointer.revision = row.id, row.revision
    e.request = request
    return row


def test_binding_canonical_successor_preserves_origin_and_current_identity(env):
    publish(env)
    original = read(env)
    graph = binding.covered_graph(env.graph, original)
    append_canonical_successor(env)
    current = binding.read_graph(
        env.s,
        env.ctx,
        env.pid,
        request=env.request,
        purpose=env.material.purpose,
        graph=graph,
        saved=original.source_basis,
    )
    assert current.source_basis["binding"]["revision"] == 2
    assert (
        current.source_basis["binding"]["current_id"]
        == original.source_basis["binding"]["current_id"]
    )
    assert binding.stable_basis(current.source_basis) == binding.stable_basis(original.source_basis)
    assert (
        binding.refresh_graph(
            env.s,
            env.ctx,
            env.pid,
            current,
            request=env.request,
            purpose=env.material.purpose,
            graph=graph,
        ).coverage
        == graph.coverage
    )
    with pytest.raises(DomainError):
        binding.refresh_graph(
            env.s,
            env.ctx,
            env.pid,
            original,
            request=env.request,
            purpose=env.material.purpose,
            graph=graph,
        )


@pytest.mark.parametrize("field", ["owner_id", "visibility"])
def test_intermediate_canonical_owner_or_audience_aba_rejected(env, field):
    publish(env)
    actual = env.ctx.actor_id if field == "owner_id" else "product"
    altered = uuid4() if field == "owner_id" else "private"
    append_canonical_successor(env, **{field: altered})
    append_canonical_successor(env, **{field: actual})
    with pytest.raises(DomainError):
        read(env)


@pytest.mark.parametrize(
    "field", ["current_id", "origin_version_id", "origin_revision", "fixed_request"]
)
def test_saved_coverage_binding_cannot_change_stable_header(env, field):
    publish(env)
    current = read(env)
    altered = deepcopy(current.source_basis)
    altered["binding"][field] = "different"
    with pytest.raises(DomainError):
        binding.require_saved(altered, current)


@pytest.mark.parametrize(
    "field",
    [
        "fact_id",
        "revision",
        "epoch",
        "issuer",
        "dependency_epoch",
        "temporal_sha256",
        "publication_group_sha256",
        "reads",
        "sources",
        "units",
    ],
)
def test_saved_coverage_publication_material_never_relaxed_for_successor(env, field):
    publish(env)
    current = read(env)
    altered = deepcopy(current.source_basis)
    altered[field] = "different"
    with pytest.raises(DomainError):
        binding.require_saved(altered, current)


def test_only_missing_current_can_leave_new_graph_unknown(env):
    assert (
        binding.read_graph(
            env.s,
            env.ctx,
            env.pid,
            request=env.request,
            purpose=env.material.purpose,
            graph=env.graph,
            optional=True,
        )
        is None
    )
    publish(env)
    trust.disable(env.engine, scope=env.scope)
    with pytest.raises(DomainError):
        binding.read_graph(
            env.s,
            env.ctx,
            env.pid,
            request=env.request,
            purpose=env.material.purpose,
            graph=env.graph,
            optional=True,
        )


def test_complete_graph_without_saved_owner_proof_is_not_a_capability(env):
    publish(env)
    graph = binding.covered_graph(env.graph, read(env))
    with pytest.raises(DomainError):
        binding.read_graph(
            env.s,
            env.ctx,
            env.pid,
            request=env.request,
            purpose=env.material.purpose,
            graph=graph,
            optional=True,
        )


@pytest.mark.parametrize("field", ["active", "can_write", "access_epoch", "expires_at"])
def test_last_non_byte_fence_rereads_publisher_after_other_owner_io(env, field):
    publish(env)
    current = read(env)
    assert (
        owner.recheck_access(
            env.s, env.ctx, env.pid, current, request=env.request, purpose=env.material.purpose
        )
        <= current.valid_until
    )
    cls = Principal if field == "active" else Grant
    row = next(row for row in env.rows if isinstance(row, cls))
    value = (
        False
        if field in {"active", "can_write"}
        else row.access_epoch + 1
        if field == "access_epoch"
        else env.at - timedelta(seconds=1)
    )
    setattr(row, field, value)  # Substituted DB result, not a pending ORM edit.
    with pytest.raises(DomainError):
        owner.recheck_access(
            env.s, env.ctx, env.pid, current, request=env.request, purpose=env.material.purpose
        )


def test_capture_basis_relaxes_only_verified_successor_version_header(env):
    publish(env)
    current = read(env)
    left = {"coverage": current.source_basis, "runtime_stamp": "fixed", "closure": {"epoch": 7}}
    right = deepcopy(left)
    right["coverage"]["binding"].update(version_id=str(uuid4()), revision=2)
    assert binding.same_capture_basis(left, right)
    assert left["coverage"]["binding"]["revision"] == 1
    right["runtime_stamp"] = "changed"
    assert not binding.same_capture_basis(left, right)


class Scalars(list):
    def all(self):
        return self


def condition(expression, row):
    if hasattr(expression, "clauses"):
        values = [condition(v, row) for v in expression.clauses]
        return any(values) if expression.operator.__name__ == "or_" else all(values)
    left = getattr(row, expression.left.key)
    right = getattr(expression.right, "value", None)
    op = expression.operator.__name__
    return {"eq": lambda: left == right, "is_": lambda: left is right}[op]()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(owner, "category_for_product", lambda _pid: CategoryUUID(int=1000000))
    at = datetime.now(UTC)
    engine = create_engine("postgresql+psycopg://unused/unused")  # No connect, ever.
    s = Session(engine)
    s.begin()
    tid, pid, project_id, actor, change_id, version_id = [uuid4() for _ in range(6)]
    scope = Scope(tenant_id=tid, product_id=pid, project_id=project_id)
    ctx = common.Context(tid, actor, actor, category_id=CategoryUUID(int=1000000))
    source = SourceRef(id=uuid4(), revision=1, position="line:1;quote_sha256:" + "0" * 64)
    ref = Ref(id=uuid4(), revision=1, kind="issue")
    request = ChangeRequest(
        id=change_id,
        revision=1,
        scope=scope,
        audience=(f"product:{pid}",),
        requester_id=actor,
        title="fixed issue",
        reason="fixed scope",
        roots=(ref,),
        references=(),
        sources=(SourceRef(id=ref.id, revision=1, kind="domain", position="issue-owner"),),
    )
    version = ChangeRequestVersion(
        id=version_id,
        tenant_id=tid,
        product_id=pid,
        project_id=project_id,
        change_id=change_id,
        revision=1,
        previous_version_id=None,
        previous_revision=None,
        owner_id=actor,
        visibility="category",
        status="draft",
        operation="change.request.create",
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=digest(request),
    )
    objects = {
        ref.identity: OwnedObject(
            ref,
            "fixed issue",
            scope,
            actor,
            "product",
            {"name": "fixed issue", "source_status": "current"},
            [],
            {},
            True,
        )
    }
    links = {}

    class Reader:
        def __init__(self, *args):
            pass

        def resolve(self, value):
            obj = objects[value.identity]
            if obj.visibility == "private":
                raise DomainError("FORBIDDEN_SCOPE", str(obj.ref.id), 403)
            return obj

        def links(self, obj):
            return links.get(obj.ref.identity, ())

    monkeypatch.setattr(registry, "OwnerReader", Reader)
    monkeypatch.setattr(old, "_issue_loader", lambda s: object())
    monkeypatch.setattr(
        owner, "fixed_seed", lambda *args, verify_sources=True: (scope, "bounded fixed purpose")
    )
    lock_calls = []

    def scope_lock(s, ctx, *, scope, audience):
        assert scope.tenant_id == tid and scope.product_id == pid and scope.project_id == project_id
        assert audience == request.audience
        lock_calls.append((s, ctx, scope, audience))
        return 7

    monkeypatch.setattr(owner, "lock_dependency_clock", scope_lock)
    monkeypatch.setattr(
        controlled,
        "_caller",
        lambda s, ctx, *args, **kwargs: (
            (str(ctx.actor_id), "actual-IO-substitute"),
            at + timedelta(minutes=20),
        ),
    )
    project = SimpleNamespace(owner_id=actor)
    monkeypatch.setattr(controlled, "_project", lambda *args: (project, (project_id, actor)))
    auth = {
        "synthetic": True,
        "roles": ["quality"],
        "required_source_read_set": [],
        "valid_until": (at + timedelta(minutes=20)).isoformat(),
    }
    monkeypatch.setattr(
        controlled,
        "authority",
        lambda *args, **kwargs: (deepcopy(auth), at + timedelta(minutes=20)),
    )
    monkeypatch.setattr(controlled, "original_authority", lambda *args: at + timedelta(minutes=20))
    monkeypatch.setattr(
        controlled,
        "_source_guard",
        lambda s, ctx, pid, visibility, owner_id, reads, sources, **kwargs: {
            "fixed": deepcopy(reads)
        },
    )
    monkeypatch.setattr(controlled, "_native_registration", lambda *args: None, raising=False)
    monkeypatch.setattr(old, "_native_registration", lambda *args: None)
    rows = [
        Product(id=pid, tenant_id=tid, revision=1, category_id=CategoryUUID(int=1000000)),
        Principal(
            id=actor, tenant_id=tid, name="publisher A", kind="human", active=True, access_epoch=1
        ),
        Grant(
            id=uuid4(),
            tenant_id=tid,
            category_id=CategoryUUID(int=1000000),
            principal_id=actor,
            can_write=True,
            expires_at=at + timedelta(minutes=20),
            access_epoch=1,
        ),
        version,
        ChangeCurrent(
            id=uuid4(),
            tenant_id=tid,
            product_id=pid,
            change_id=change_id,
            version_id=version_id,
            revision=1,
        ),
        ChangeDependencyClock(id=uuid4(), tenant_id=tid, product_id=pid, epoch=7),
    ]

    queries = []

    def scalars(query):
        queries.append(query)
        model = query.column_descriptions[0]["entity"]
        result = [
            r
            for r in rows
            if isinstance(r, model) and all(condition(v, r) for v in query._where_criteria)
        ]
        if query._order_by_clauses:
            clause = query._order_by_clauses[0]
            key = getattr(getattr(clause, "element", None), "key", getattr(clause, "key", None))
            result.sort(
                key=lambda r: getattr(r, key),
                reverse=getattr(getattr(clause, "modifier", None), "__name__", None) == "desc_op",
            )
        return Scalars(
            result[: query._limit_clause.value] if query._limit_clause is not None else result
        )

    monkeypatch.setattr(s, "scalars", scalars)

    def execute(query):
        # Substitute only the temporal watermark's projected scalar reads.
        entities = {column["entity"] for column in query.column_descriptions}
        assert entities == {Grant}
        return [
            SimpleNamespace(
                **{
                    column["name"]: getattr(row, column["name"])
                    for column in query.column_descriptions
                }
            )
            for row in scalars(query)
        ]

    monkeypatch.setattr(s, "execute", execute)
    monkeypatch.setattr(s, "add", rows.append)
    monkeypatch.setattr(s, "add_all", rows.extend)

    def flush(*args, **kwargs):
        for r in rows:
            if r.id is None:
                r.id = uuid4()
            if r.created_at is None:
                r.created_at = at

    monkeypatch.setattr(s, "flush", flush)
    monkeypatch.setitem(common.EVENTS, schemas.OPERATION, schemas.EVENT)
    basis = registry.read_registry(s, ctx, pid, request)
    material = schemas.CoverageMaterial(
        schema_version="pdos-controlled-change-coverage-v1",
        scope=scope,
        purpose="bounded fixed purpose",
        change_id=change_id,
        origin_version_id=version_id,
        origin_revision=1,
        owner_id=actor,
        visibility="category",
        publisher_id=actor,
        roots=(ref,),
        nodes=(ref,),
        units=({"unit": f"object:{ref.identity}", "object_identity": ref.identity},),
        facets=tuple(
            {
                "facet": f,
                "nodes": (ref,),
                "statement": "Trusted whole original explicitly enumerates this bounded facet",
            }
            for f in schemas.FACETS
        ),
        closure_sha256=basis.closure_sha256,
        valid_from=at - timedelta(minutes=1),
        valid_until=at + timedelta(minutes=10),
        nature="synthetic",
    )
    original = json.dumps(
        material.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    source = source.model_copy(
        update={"position": "line:1;quote_sha256:" + hashlib.sha256(original.encode()).hexdigest()}
    )
    artifact = Artifact(
        category_id=CategoryUUID(int=1000000),
        id=source.id,
        tenant_id=tid,
        product_id=pid,
        owner_id=actor,
        visibility="category",
        revision=1,
        status="active",
        original_id=None,
        content=original,
        content_hash=common.digest(original),
    )
    rows.append(artifact)

    def fixed_original(s, ctx, pid, identity, revision):
        assert identity == artifact.id and revision == artifact.revision
        if artifact.status != "active":
            raise DomainError("SOURCE_UNAVAILABLE", "source withdrawn")
        return artifact

    monkeypatch.setattr(controlled, "source_for", fixed_original)
    professional_issuer = professional.configure_local_synthetic(
        engine, tenant_id=tid, product_id=pid, enabled=True
    )
    pin = schemas.OriginalApproval(source=source, material_sha256=digest(material))
    issuer = trust.configure(engine, professional_issuer, scope=scope, approvals=(pin,))
    graph = GraphSnapshot(
        id=uuid4(),
        revision=1,
        scope=scope,
        audience=request.audience,
        roots=request.roots,
        nodes=(Node.model_validate(basis.projection["nodes"][0]),),
        edges=(),
        coverage=(),
        sources=request.sources,
        captured_at=at,
        expires_at=at + timedelta(minutes=10),
        nature="synthetic",
    )
    payload = schemas.CoverageImport(
        project_id=project_id,
        change_id=change_id,
        purpose=material.purpose,
        source=source,
        reason="trusted host import",
    )
    result = SimpleNamespace(
        s=s,
        engine=engine,
        scope=scope,
        ctx=ctx,
        pid=pid,
        at=at,
        material=material,
        source=source,
        artifact=artifact,
        issuer=issuer,
        professional=professional_issuer,
        graph=graph,
        request=request,
        rows=rows,
        objects=objects,
        links=links,
        payload=payload,
        command_id=uuid4(),
        request_key="pure-fixed-request",
        lock_calls=lock_calls,
        queries=queries,
    )
    yield result
    s.rollback()
    s.close()
    engine.dispose()


def publish(e):
    return importer.trusted_import(
        e.s, e.ctx, e.pid, e.issuer, e.payload, command_id=e.command_id, request_key=e.request_key
    )


def read(e):
    return owner.read(
        e.s,
        e.ctx,
        e.pid,
        change_id=e.material.change_id,
        purpose=e.material.purpose,
        graph=e.graph,
        origin_version=(e.material.origin_version_id, e.material.origin_revision),
    )


def separate_reader(e):
    """Only pure mapped rows; current caller/professional IO remains substituted."""
    reader = Principal(
        id=uuid4(),
        tenant_id=e.ctx.tenant_id,
        name="reader B",
        kind="human",
        active=True,
        access_epoch=1,
    )
    grant = Grant(
        id=uuid4(),
        tenant_id=e.ctx.tenant_id,
        category_id=CategoryUUID(int=1000000),
        principal_id=reader.id,
        can_write=False,
        expires_at=e.at + timedelta(minutes=20),
        access_epoch=1,
    )
    e.rows.extend((reader, grant))
    publisher_id = e.ctx.actor_id
    publish(e)
    e.ctx = common.Context(
        e.ctx.tenant_id, reader.id, reader.id, category_id=CategoryUUID(int=1000000)
    )
    return next(r for r in e.rows if isinstance(r, Principal) and r.id == publisher_id), reader


def pending_confirmation(e):
    row = Confirmation(
        id=uuid4(),
        tenant_id=e.ctx.tenant_id,
        product_id=e.pid,
        actor_id=e.ctx.actor_id,
        subject_id=e.material.change_id,
        operation="change.order.approve",
        revision=1,
        token_hash="0" * 64,
        expires_at=e.at + timedelta(minutes=20),
        consumed=True,
        payload_digest="1" * 64,
        snapshot={"pending": "common proof"},
    )
    # Use the actual unconnected Session pending collection, not the IO fake add.
    Session.add(e.s, row)
    assert row in e.s.new
    return row


def tracked_listeners(e, monkeypatch):
    listeners = []
    listen = event.listen

    def track(target, name, callback, *args, **kwargs):
        if target is e.s and name == "do_orm_execute":
            listeners.append(callback)
        return listen(target, name, callback, *args, **kwargs)

    monkeypatch.setattr(event, "listen", track)
    return listeners


def assert_read_guard_clean(e, listeners):
    assert listeners
    assert all(not event.contains(e.s, "do_orm_execute", callback) for callback in listeners)
    assert all(q.column_descriptions[0]["entity"] is not Confirmation for q in e.queries)
    assert e.s.autoflush is True


def use_actual_scope_acls(e, monkeypatch, *, private_change=False):
    """Actual ACL functions + mapped IO substitutes, not real authority/native roots."""
    publisher_id = e.ctx.actor_id
    project_owner, change_owner, reader_id = (uuid4() for _ in range(3))
    for identity in (project_owner, change_owner, reader_id):
        e.rows.extend(
            (
                Principal(
                    id=identity,
                    tenant_id=e.ctx.tenant_id,
                    name="named ACL person",
                    kind="human",
                    active=True,
                    access_epoch=1,
                ),
                Grant(
                    id=uuid4(),
                    tenant_id=e.ctx.tenant_id,
                    category_id=CategoryUUID(int=1000000),
                    principal_id=identity,
                    can_write=True,
                    access_epoch=1,
                    expires_at=e.at + timedelta(minutes=20),
                ),
            )
        )
    project = Project(
        id=e.scope.project_id,
        tenant_id=e.ctx.tenant_id,
        product_id=e.pid,
        owner_id=project_owner,
        name="readable project",
        purpose=e.material.purpose,
        scope="fixed",
        visibility="category",
        status="active",
        revision=1,
    )
    e.rows.append(project)
    change = next(r for r in e.rows if isinstance(r, ChangeRequestVersion))
    change.owner_id = change_owner
    change.visibility = "private" if private_change else "category"
    e.request = e.request.model_copy(update={"requester_id": change_owner})
    change.request_snapshot, change.request_sha256 = (
        e.request.model_dump(mode="json"),
        digest(e.request),
    )
    e.material = e.material.model_copy(
        update={
            "owner_id": change_owner,
            "visibility": change.visibility,
            "publisher_id": change_owner if private_change else publisher_id,
        }
    )
    original = json.dumps(
        e.material.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    e.source = e.source.model_copy(
        update={"position": "line:1;quote_sha256:" + hashlib.sha256(original.encode()).hexdigest()}
    )
    e.artifact.content, e.artifact.content_hash = original, common.digest(original)
    if private_change:
        e.ctx = common.Context(
            e.ctx.tenant_id, change_owner, change_owner, category_id=CategoryUUID(int=1000000)
        )
    e.payload = e.payload.model_copy(update={"source": e.source})
    e.issuer = trust.configure(
        e.engine,
        e.professional,
        scope=e.scope,
        approvals=(schemas.OriginalApproval(source=e.source, material_sha256=digest(e.material)),),
    )
    monkeypatch.setattr(controlled, "_project", ACTUAL_PROJECT)
    monkeypatch.setattr(controlled, "source_for", common.source_for)
    monkeypatch.setattr(controlled, "_source_guard", ACTUAL_SOURCE_GUARD)
    monkeypatch.setattr(e.s, "scalar", lambda query: next(iter(e.s.scalars(query)), None))
    # Native provenance stays an explicit substitute; actual Source ACL and
    # private propagation, original parser and whole-line SHA are exercised.
    monkeypatch.setattr(old, "_native_registration", lambda *args: {})
    e.engine._pdos_change_store = object()
    return project, change, reader_id


def test_product_project_owner_change_owner_publisher_and_reader_can_differ(env, monkeypatch):
    publisher_id = env.ctx.actor_id
    project, change, reader_id = use_actual_scope_acls(env, monkeypatch)
    assert len({project.owner_id, change.owner_id, publisher_id, reader_id}) == 4
    publish(env)
    env.ctx = common.Context(
        env.ctx.tenant_id, reader_id, reader_id, category_id=CategoryUUID(int=1000000)
    )
    current = read(env)
    assert len(current.coverage) == 8
    fact = next(r for r in env.rows if isinstance(r, models.ChangeCoverageFact))
    assert fact.owner_id == change.owner_id and fact.actor_id == publisher_id
    assert fact.visibility == change.visibility == "category"


def test_private_change_owner_in_readable_project_can_publish_and_read_own(env, monkeypatch):
    project, change, reader_id = use_actual_scope_acls(env, monkeypatch, private_change=True)
    assert project.owner_id != change.owner_id == env.ctx.actor_id
    publish(env)
    assert len(read(env).coverage) == 8
    env.ctx = common.Context(
        env.ctx.tenant_id, reader_id, reader_id, category_id=CategoryUUID(int=1000000)
    )
    with pytest.raises(DomainError) as failure:
        read(env)
    assert failure.value.status == 403


def test_private_change_cannot_be_published_by_project_owner(env, monkeypatch):
    project, _, _ = use_actual_scope_acls(env, monkeypatch, private_change=True)
    env.ctx = common.Context(
        env.ctx.tenant_id, project.owner_id, project.owner_id, category_id=CategoryUUID(int=1000000)
    )
    with pytest.raises(DomainError) as failure:
        publish(env)
    assert failure.value.status == 403
    assert not any(isinstance(r, models.ChangeCoverageFact) for r in env.rows)


def test_private_project_cannot_be_read_by_change_owner(env, monkeypatch):
    project, _, _ = use_actual_scope_acls(env, monkeypatch, private_change=True)
    project.visibility = "private"
    with pytest.raises(DomainError) as failure:
        publish(env)
    assert failure.value.status == 403


@pytest.mark.parametrize("source_owner", ["publisher", "change_owner"])
def test_private_source_cannot_publish_into_product_change(env, monkeypatch, source_owner):
    _, change, _ = use_actual_scope_acls(env, monkeypatch)
    env.artifact.visibility = "private"
    env.artifact.owner_id = env.ctx.actor_id if source_owner == "publisher" else change.owner_id
    with pytest.raises(DomainError) as failure:
        publish(env)
    assert failure.value.status == 403
    assert not any(isinstance(r, models.ChangeCoverageFact) for r in env.rows)


def test_publisher_a_reader_b_have_scoped_real_lock_statements(env, monkeypatch):
    publisher, reader = separate_reader(env)
    original = controlled.original_authority
    authority_calls = []

    def authority(s, ctx, pid, row):
        authority_calls.append((ctx.actor_id, row.actor_id))
        return original(s, ctx, pid, row)

    monkeypatch.setattr(controlled, "original_authority", authority)
    env.queries.clear()
    current = read(env)
    assert len(current.coverage) == 8
    assert authority_calls == [(reader.id, publisher.id)] * 2
    selected = [
        q
        for q in env.queries
        if q.column_descriptions[0]["entity"] in (Principal, Grant)
        and q._for_update_arg is not None
    ]
    assert [q.column_descriptions[0]["entity"] for q in selected] == [Principal, Grant] * 4
    expected = sorted((publisher.id, reader.id), key=str) * 2
    identities = [
        next(v.right.value for v in q._where_criteria if v.left.key == "id")
        for q in selected
        if q.column_descriptions[0]["entity"] is Principal
    ]
    assert identities == expected
    for query in selected:
        where = {v.left.key: v.right.value for v in query._where_criteria}
        assert where["tenant_id"] == env.ctx.tenant_id
        if query.column_descriptions[0]["entity"] is Grant:
            assert where["category_id"] == env.ctx.category_id
            assert where["principal_id"] in (publisher.id, reader.id)
    # Publisher fence digest is stable for another legitimate reader phase.
    assert "publisher_access_sha256" in current.source_basis
    assert len(current.source_basis["publisher_access_sha256"]) == 64


@pytest.mark.parametrize("field", ["active", "access_epoch"])
@pytest.mark.parametrize("phase", ["source_io", "last_caller"])
def test_publisher_a_tail_revocation_fails_reader_b(env, monkeypatch, field, phase):
    publisher, _ = separate_reader(env)
    original = controlled._source_guard if phase == "source_io" else controlled._caller
    calls = 0

    def revoke(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if (phase == "source_io" and kwargs.get("io", True)) or (
            phase == "last_caller" and calls == 2
        ):
            setattr(publisher, field, False if field == "active" else 2)
        return result

    monkeypatch.setattr(controlled, "_source_guard" if phase == "source_io" else "_caller", revoke)
    with pytest.raises(DomainError):
        read(env)
    assert getattr(publisher, field) == (False if field == "active" else 2)


def test_pending_publisher_revocation_cannot_be_erased(env):
    publisher, _ = separate_reader(env)
    Session.add(env.s, publisher)
    publisher.active = False
    with pytest.raises(DomainError):
        read(env)
    assert publisher.active is False and publisher in env.s.new


@pytest.mark.parametrize(
    "field", ["can_write", "expires_at", "access_epoch", "tenant_id", "category_id", "principal_id"]
)
def test_source_io_pending_publisher_grant_is_not_refreshed_away(env, monkeypatch, field):
    publisher, _ = separate_reader(env)
    grant = next(r for r in env.rows if isinstance(r, Grant) and r.principal_id == publisher.id)
    # An actual Session identity-map row, clean before IO; no SELECT/flush/DB.
    make_transient_to_detached(grant)
    Session.add(env.s, grant)
    assert grant in env.s and grant not in env.s.dirty
    before = deepcopy(grant.__dict__)
    original = controlled._source_guard

    def pending_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("io", True):
            value = {
                "can_write": False,
                "expires_at": env.at - timedelta(seconds=1),
                "access_epoch": 2,
                "tenant_id": uuid4(),
                "category_id": uuid4(),
                "principal_id": uuid4(),
            }[field]
            setattr(grant, field, value)
            # Fire the real ORM before-SELECT event inside the source callback.
            # The guard must reject before the forbidden Engine IO is reached.
            ACTUAL_EXECUTE(env.s, select(Grant))
        return result

    monkeypatch.setattr(controlled, "_source_guard", pending_revoke)
    with pytest.raises(DomainError):
        read(env)
    assert grant in env.s.dirty
    assert grant.__dict__[field] != before[field]


@pytest.mark.parametrize("state", ["new", "deleted"])
def test_pending_grant_rejected_before_owner_io(env, monkeypatch, state):
    publisher, _ = separate_reader(env)
    grant = next(r for r in env.rows if isinstance(r, Grant) and r.principal_id == publisher.id)
    if state == "deleted":
        make_transient_to_detached(grant)
        Session.add(env.s, grant)
        env.s.delete(grant)
        assert grant in env.s.deleted
    else:
        Session.add(env.s, grant)
        assert grant in env.s.new

    def no_source_io(*args, **kwargs):
        raise AssertionError("Pending authority must reject before original source IO")

    monkeypatch.setattr(controlled, "original", no_source_io)
    with pytest.raises(DomainError):
        read(env)


@pytest.mark.parametrize("entry", ["read", "refresh"])
@pytest.mark.parametrize("mutation", ["consumed", "missing", "raise_after_mutation"])
def test_full_source_io_preserves_pending_confirmation(env, monkeypatch, entry, mutation):
    publish(env)
    previous = read(env) if entry == "refresh" else None
    confirmation = pending_confirmation(env)
    listeners = tracked_listeners(env, monkeypatch)
    original = controlled._source_guard

    def change_confirmation(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("io", True):
            if mutation == "missing":
                confirmation.__dict__.pop("consumed", None)
            else:
                confirmation.consumed = False
            if mutation == "raise_after_mutation":
                raise RuntimeError("substituted source IO failure")
        return result

    monkeypatch.setattr(controlled, "_source_guard", change_confirmation)
    with pytest.raises(DomainError):
        if entry == "read":
            read(env)
        else:
            owner.refresh(
                env.s,
                env.ctx,
                env.pid,
                previous,
                change_id=env.material.change_id,
                purpose=env.material.purpose,
                graph=env.graph,
            )
    assert confirmation.__dict__.get("consumed") is not True
    assert_read_guard_clean(env, listeners)


def test_full_source_io_preserves_confirmation_and_restores_after_source_exception(
    env, monkeypatch
):
    publish(env)
    confirmation = pending_confirmation(env)
    listeners = tracked_listeners(env, monkeypatch)
    read(env)
    assert confirmation.consumed is True
    assert_read_guard_clean(env, listeners)
    original = controlled._source_guard

    def fail_io(*args, **kwargs):
        if kwargs.get("io", True):
            raise RuntimeError("substituted source IO failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(controlled, "_source_guard", fail_io)
    with pytest.raises(RuntimeError, match="source IO failure"):
        read(env)
    assert confirmation.consumed is True
    assert_read_guard_clean(env, listeners)


def test_fixed_original_publish_current_complete_and_refresh(env):
    receipt = publish(env)
    current = read(env)
    assert len(current.coverage) == 8 and all(
        v.status == "complete" and v.source == env.source for v in current.coverage
    )
    assert current.source_basis["dependency_epoch"] == 7
    assert env.source in current.sources
    assert {v["artifact_id"] for v in current.required_source_read_set} == {str(env.source.id)}
    assert current.valid_until == env.graph.expires_at
    assert (
        owner.refresh(
            env.s,
            env.ctx,
            env.pid,
            current,
            change_id=env.material.change_id,
            purpose=env.material.purpose,
            graph=env.graph,
        )._proof_sha256
        == current._proof_sha256
    )
    assert publish(env)["id"] == receipt["id"]
    assert len([r for r in env.rows if isinstance(r, models.ChangeCoverageFact)]) == 1
    assert all(
        len([r for r in env.rows if isinstance(r, cls)]) == 1
        for cls in (Receipt, Audit, Outbox, RequestKey)
    )


@pytest.mark.parametrize(
    "mutation", ["scope", "purpose", "nodes", "root", "topology", "nature", "origin"]
)
def test_graph_or_origin_is_not_a_self_attestation(env, mutation):
    publish(env)
    if mutation == "scope":
        env.graph = env.graph.model_copy(
            update={"scope": env.scope.model_copy(update={"project_id": uuid4()})}
        )
    elif mutation == "purpose":
        env.material = env.material.model_copy(update={"purpose": "other"})
    elif mutation in {"nodes", "root"}:
        wrong = Ref(id=uuid4(), revision=1, kind="issue")
        env.graph = env.graph.model_copy(
            update={"roots": (wrong,)} if mutation == "root" else {"nodes": ()}
        )
    elif mutation == "topology":
        ref = env.graph.roots[0]
        env.graph = env.graph.model_copy(
            update={
                "edges": (
                    Edge(
                        id="fake-edge",
                        origin=ref,
                        target=ref,
                        relation="invented relation",
                        source=env.source,
                    ),
                )
            }
        )
    elif mutation == "nature":
        env.graph = env.graph.model_copy(update={"nature": "real"})
    else:
        env.material = env.material.model_copy(update={"origin_version_id": uuid4()})
    with pytest.raises(DomainError):
        read(env)


@pytest.mark.parametrize(
    "mutation",
    [
        "clock_aba",
        "current",
        "issuer_rotation",
        "issuer_disable",
        "professional_rotation",
        "withdrawn",
        "line",
        "row_material",
        "row_hash",
        "row_epoch",
        "group",
        "final_clock",
        "expired",
        "caller",
        "uow",
    ],
)
def test_saved_current_owner_fails_closed_on_drift(env, monkeypatch, mutation):
    publish(env)
    prior = read(env)
    fact = next(r for r in env.rows if isinstance(r, models.ChangeCoverageFact))
    if mutation == "clock_aba":
        next(r for r in env.rows if isinstance(r, ChangeDependencyClock)).epoch += 2
    elif mutation == "current":
        next(r for r in env.rows if isinstance(r, models.ChangeCoverageCurrent)).epoch += 1
    elif mutation == "issuer_rotation":
        trust.configure(
            env.engine, env.professional, scope=env.scope, approvals=env.issuer.approvals
        )
    elif mutation == "issuer_disable":
        trust.disable(env.engine, scope=env.scope)
    elif mutation == "professional_rotation":
        professional.configure_local_synthetic(
            env.engine, tenant_id=env.scope.tenant_id, product_id=env.pid, enabled=True
        )
    elif mutation == "withdrawn":
        env.artifact.status = "withdrawn"
    elif mutation == "line":
        env.artifact.content += " "
        env.artifact.content_hash = common.digest(env.artifact.content)
    elif mutation == "row_material":
        fact.material = {**fact.material, "purpose": "changed"}
    elif mutation == "row_hash":
        fact.material_sha256 = "f" * 64
    elif mutation == "row_epoch":
        fact.dependency_epoch += 1
    elif mutation == "group":
        env.rows[:] = [r for r in env.rows if not isinstance(r, Outbox)]
    elif mutation in {"final_clock", "expired"}:
        monkeypatch.setattr(owner, "clock", lambda: env.material.valid_until)
    elif mutation == "caller":
        env.ctx = common.Context(
            env.scope.tenant_id, uuid4(), uuid4(), category_id=CategoryUUID(int=1000000)
        )
    elif mutation == "uow":
        env.s.rollback()
        env.s.begin()
    with pytest.raises(DomainError):
        owner.refresh(
            env.s,
            env.ctx,
            env.pid,
            prior,
            change_id=env.material.change_id,
            purpose=env.material.purpose,
            graph=env.graph,
        )


def test_hidden_dependency_is_generic_and_cannot_disappear(env):
    publish(env)
    ref = Ref(id=uuid4(), revision=1, kind="part")
    env.objects[ref.identity] = OwnedObject(
        ref, "secret label", env.scope, uuid4(), "private", {}, [], {}, True
    )
    env.links[env.graph.roots[0].identity] = ((ref, "secret relation"),)
    with pytest.raises(DomainError) as error:
        read(env)
    assert error.value.reason == "COVERAGE_DEPENDENCY_UNRESOLVED"
    assert str(ref.id) not in error.value.message and "secret" not in error.value.message


@pytest.mark.parametrize("mode", ["missing", "copy", "wrong_engine", "callback", "unapproved_line"])
def test_forged_capability_never_publishes(env, mode):
    supplied = env.issuer
    if mode == "missing":
        supplied = None
    elif mode == "copy":
        supplied = object.__new__(trust.CoverageIssuer)
        for name in supplied.__slots__:
            object.__setattr__(supplied, name, getattr(env.issuer, name))
    elif mode == "wrong_engine":
        env.engine._pdos_change_coverage_issuers[
            (env.scope.tenant_id, env.pid, env.scope.project_id)
        ] = None
    elif mode == "callback":

        def supplied():
            return True
    else:
        trust.configure(
            env.engine,
            env.professional,
            scope=env.scope,
            approvals=(schemas.OriginalApproval(source=env.source, material_sha256="f" * 64),),
        )
    with pytest.raises(DomainError):
        publish_env = importer.trusted_import(
            env.s,
            env.ctx,
            env.pid,
            supplied,
            env.payload,
            command_id=env.command_id,
            request_key=env.request_key,
        )
        assert publish_env is None
    assert not any(isinstance(r, models.ChangeCoverageFact) for r in env.rows)


@pytest.mark.parametrize(
    "change",
    [
        "missing_facet",
        "duplicate_facet",
        "empty_enum",
        "other_enum",
        "batch_unit",
        "unmapped_unit",
        "float_revision",
        "null_source",
        "extra_complete",
    ],
)
def test_original_closed_schema_rejects_unsupported_claims(env, change):
    raw = env.material.model_dump(mode="json")
    if change == "missing_facet":
        raw["facets"].pop()
    elif change == "duplicate_facet":
        raw["facets"][-1] = raw["facets"][0]
    elif change == "empty_enum":
        raw["facets"][0]["nodes"] = []
    elif change == "other_enum":
        raw["facets"][0]["nodes"][0]["id"] = str(uuid4())
    elif change == "batch_unit":
        raw["units"][0]["unit"] = "batch:invented"
    elif change == "unmapped_unit":
        raw["units"][0]["object_identity"] = "invented"
    elif change == "float_revision":
        raw["nodes"][0]["revision"] = 1.0
    elif change == "null_source":
        raw["closure_sha256"] = None
    else:
        raw["complete"] = True
    with pytest.raises(ValidationError):
        schemas.CoverageMaterial.model_validate(raw)


def test_duplicate_original_keys_rejected_before_import(env):
    raw = env.artifact.content
    env.artifact.content = '{"purpose":"spoof",' + raw[1:]
    env.artifact.content_hash = common.digest(env.artifact.content)
    source = env.source.model_copy(
        update={
            "position": "line:1;quote_sha256:"
            + hashlib.sha256(env.artifact.content.encode()).hexdigest()
        }
    )
    with pytest.raises(DomainError) as error:
        controlled.original(env.s, env.ctx, env.pid, source, schemas.CoverageMaterial)
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_future_authority_boundary_and_last_io_clock(env, monkeypatch):
    grant = Grant(
        id=uuid4(),
        tenant_id=env.scope.tenant_id,
        category_id=CategoryUUID(int=1000000),
        principal_id=uuid4(),
        access_epoch=1,
        can_write=False,
        expires_at=env.at + timedelta(seconds=1),
    )
    env.rows.append(grant)
    publish(env)
    current = read(env)
    assert current.valid_until == env.material.valid_until
    monkeypatch.setattr(owner, "clock", lambda: grant.expires_at)
    with pytest.raises(DomainError):
        owner.refresh(
            env.s,
            env.ctx,
            env.pid,
            current,
            change_id=env.material.change_id,
            purpose=env.material.purpose,
            graph=env.graph,
        )


def test_inspection_only_does_not_supply_complete_or_write(env):
    result = owner.inspect_basis(
        env.s, env.ctx, env.pid, change_id=env.material.change_id, purpose=env.material.purpose
    )
    assert result["closure_sha256"] == env.material.closure_sha256
    assert "coverage" not in result
    assert not any(isinstance(r, models.ChangeCoverageFact) for r in env.rows)


def test_final_clock_before_publication_has_no_pending_effects(env, monkeypatch):
    monkeypatch.setattr(owner, "clock", lambda: env.material.valid_until)
    with pytest.raises(DomainError):
        publish(env)
    assert not any(isinstance(r, (models.ChangeCoverageFact, Receipt)) for r in env.rows)


def test_clock_changed_by_last_owner_io_has_no_pending_effects(env, monkeypatch):
    caller = controlled._caller
    calls = 0

    def last_io(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            next(r for r in env.rows if isinstance(r, ChangeDependencyClock)).epoch += 1
        return caller(*args, **kwargs)

    monkeypatch.setattr(controlled, "_caller", last_io)
    with pytest.raises(DomainError):
        publish(env)
    assert not any(isinstance(r, (models.ChangeCoverageFact, Receipt)) for r in env.rows)


@pytest.mark.parametrize("field", ["sources", "status", "operation"])
def test_stored_publication_shape_must_remain_exact(env, field):
    publish(env)
    fact = next(r for r in env.rows if isinstance(r, models.ChangeCoverageFact))
    setattr(fact, field, [] if field == "sources" else "other")
    with pytest.raises(DomainError):
        read(env)


def test_original_approval_registry_keeps_pins_beyond_previous_cap(env):
    pins = tuple(
        schemas.OriginalApproval(
            source=env.source.model_copy(update={"id": uuid4()}),
            material_sha256=digest(env.material),
        )
        for _ in range(101)
    )
    issuer = trust.configure(
        env.engine, env.professional, scope=env.scope, approvals=pins
    )
    assert issuer.epoch == env.issuer.epoch + 1
    assert issuer.approvals == pins
    assert trust.current(env.engine, env.scope, supplied=issuer) is issuer
    assert trust.check(
        env.engine, env.scope, pins[-1].source, env.material, supplied=issuer
    ) is issuer


def test_registry_growth_over_previous_cap_retains_full_closure_and_invalidates_old_graph(env):
    for _ in range(250):
        ref = Ref(id=uuid4(), revision=1, kind="part")
        env.objects[ref.identity] = OwnedObject(
            ref, "visible part", env.scope, env.ctx.actor_id, "product", {}, [], {}, True
        )
    env.links[env.graph.roots[0].identity] = tuple(
        (o.ref, "actual substituted relationship")
        for o in env.objects.values()
        if o.ref != env.graph.roots[0]
    )
    with pytest.raises(DomainError) as error:
        publish(env)
    assert error.value.reason == "COVERAGE_OWNER_STALE"


def test_same_product_change_current_rollback_cannot_hide_newer_version(env):
    publish(env)
    old_version = next(r for r in env.rows if isinstance(r, ChangeRequestVersion))
    newer = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=env.scope.tenant_id,
        product_id=env.pid,
        project_id=env.scope.project_id,
        change_id=env.material.change_id,
        revision=2,
        previous_version_id=old_version.id,
        previous_revision=1,
        owner_id=env.ctx.actor_id,
        visibility="category",
        status="analysis",
        operation="change.impact.compute",
        request_snapshot=env.request.model_copy(
            update={"revision": 2, "status": "analysis"}
        ).model_dump(mode="json"),
    )
    newer.request_sha256 = digest(newer.request_snapshot)
    env.rows.append(newer)
    with pytest.raises(DomainError):
        read(env)
    p = next(r for r in env.rows if isinstance(r, ChangeCurrent))
    p.version_id, p.revision = newer.id, 2
    assert len(read(env).coverage) == 8


def test_refresh_binds_original_graph_identity_and_interval(env):
    publish(env)
    current = read(env)
    other = env.graph.model_copy(update={"id": uuid4()})
    with pytest.raises(DomainError):
        owner.refresh(
            env.s,
            env.ctx,
            env.pid,
            current,
            change_id=env.material.change_id,
            purpose=env.material.purpose,
            graph=other,
        )


def test_declared_second_node_requires_exact_second_unit(env):
    raw = env.material.model_dump(mode="json")
    other = Ref(id=uuid4(), revision=1, kind="part")
    raw["nodes"].append(other.model_dump(mode="json"))
    for f in raw["facets"]:
        f["nodes"].append(other.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        schemas.CoverageMaterial.model_validate(raw)
    raw["units"].append({"unit": f"object:{other.identity}", "object_identity": other.identity})
    assert len(schemas.CoverageMaterial.model_validate(raw).units) == 2


def test_replay_detects_same_orm_pointer_changed_during_later_io(env, monkeypatch):
    publish(env)
    original = controlled._source_guard

    def changed_current(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("io") is False:
            next(r for r in env.rows if isinstance(r, models.ChangeCoverageCurrent)).epoch += 1
        return result

    monkeypatch.setattr(controlled, "_source_guard", changed_current)
    with pytest.raises(DomainError):
        publish(env)


def test_import_read_refresh_each_take_actual_scope_lock_seam(env):
    publish(env)
    published_locks = len(env.lock_calls)
    assert published_locks > 0
    current = read(env)
    read_locks = len(env.lock_calls)
    assert read_locks > published_locks
    owner.refresh(
        env.s,
        env.ctx,
        env.pid,
        current,
        change_id=env.material.change_id,
        purpose=env.material.purpose,
        graph=env.graph,
    )
    assert len(env.lock_calls) > read_locks


@pytest.mark.parametrize("kind", ["dependency", "coverage_current"])
def test_real_session_pending_dependencies_are_not_erased_by_refresh(env, kind):
    publish(env)
    row = (
        Artifact(
            id=uuid4(),
            tenant_id=env.scope.tenant_id,
            product_id=env.pid,
            category_id=CategoryUUID(int=1000000),
        )
        if kind == "dependency"
        else models.ChangeCoverageCurrent(
            id=uuid4(), tenant_id=env.scope.tenant_id, product_id=env.pid
        )
    )
    Session.add(env.s, row)  # Real Session.new, still no SQL/connect.
    with pytest.raises(DomainError):
        read(env)
    assert row in env.s.new


@pytest.mark.parametrize("drift", ["disable", "rotate", "runtime", "ttl", "uow"])
def test_final_fence_after_append_rejects_pending_publication(env, monkeypatch, drift):
    actual_append = common.append_receipt

    def after_append(*args, **kwargs):
        result = actual_append(*args, **kwargs)
        if drift == "disable":
            trust.disable(env.engine, scope=env.scope)
        elif drift == "rotate":
            trust.configure(
                env.engine, env.professional, scope=env.scope, approvals=env.issuer.approvals
            )
        elif drift == "runtime":
            env.engine._pdos_security_runtime = object()
        elif drift == "ttl":
            monkeypatch.setattr(owner, "clock", lambda: env.material.valid_until)
        else:
            env.s.rollback()
            env.s.begin()
        return result

    monkeypatch.setattr(common, "append_receipt", after_append)
    with pytest.raises(DomainError):
        publish(env)
    # Substituted rows deliberately remain pending: actual wholeTx rollback is Root PG work.
    assert any(isinstance(r, Receipt) for r in env.rows)
