"""Structural read authorization and restoration, without a model or database."""

from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import project_object_reads as module
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.builds.models import Build
from pdos_next.errors import DomainError


@pytest.fixture
def port(monkeypatch):
    scope = RunScope(
        *(UUID(int=i) for i in range(1, 8)),
        project_id=UUID(int=8),
        data_categories=frozenset({"internal"}),
    )
    fields = asdict(scope)
    fields["id"] = fields.pop("run_id")
    run = NS(**fields, state="running", reverted_at=None)
    state = NS(
        scope=scope,
        run=run,
        rows=[],
        queries=[],
        authority_calls=0,
        project=NS(id=scope.project_id, visibility="category"),
        product=NS(visibility="category"),
    )

    @contextmanager
    def transaction(engine, tenant, **kwargs):
        assert tenant == scope.tenant_id
        assert kwargs == dict(
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
            read_snapshot=True,
        )
        yield NS(
            get=lambda *_: run, scalars=lambda query: state.queries.append(query) or state.rows
        )

    def authority(*_):
        state.authority_calls += 1

    monkeypatch.setattr(module, "tenant_session", transaction)
    monkeypatch.setattr(module, "require_run_project", lambda *_: state.project)
    monkeypatch.setattr(module, "require_access", lambda *_: state.product)
    state.port = module.ProjectObjectReads(NS(engine=None, authority=authority), DomainCommands)
    return state


def build(identity=100):
    return Build(
        id=UUID(int=identity),
        revision=3,
        project_id=UUID(int=8),
        owner_id=UUID(int=2),
        visibility="category",
        status="planned",
        created_at=datetime(2026, 10, 22, tzinfo=UTC),
        type="tool_trial",
        project_revision=4,
        engineering_configuration_id=UUID(int=20),
        manufacturing_configuration_id=UUID(int=21),
        previous_build_id=None,
        name="private text must never leave",
        purpose="customer identity",
    )


@pytest.mark.parametrize("name", module.SCHEMAS)
@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "product_id",
        "project_id",
        "run_id",
        "private_context",
        "data_categories",
        "expected_revision",
    ],
)
def test_selectors_cannot_supply_scope_or_authority(name, field):
    with pytest.raises(ValidationError):
        module.SCHEMAS[name].model_validate({field: str(UUID(int=3))})


@pytest.mark.parametrize("size", [0, 101])
def test_page_size_is_bounded(size):
    with pytest.raises(ValidationError):
        module.BuildInput(page_size=size)


def test_registered_and_bootstrap_ports_include_revalidation():
    registry = default_registry()
    adapters = Bootstrap(NS()).adapters()
    for name in module.SCHEMAS:
        spec = registry.get(name)
        assert spec.tier == "READ" and spec.operation_key is None
        assert name in adapters.read_tools and name in adapters.read_restores
        assert name not in {d["name"] for d in registry.definitions("extract")}


@pytest.mark.parametrize("name", module.SCHEMAS)
def test_sql_restricts_scope_and_never_selects_bodies(port, name):
    query, _ = module._query(port.scope, module.SCHEMAS[name](), name, private=False)
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert all(value in sql for value in ("tenant_id =", "product_id =", "project_id ="))
    assert ".visibility IN" in sql and "LIMIT" in sql
    for body in (
        "issue_snapshot",
        "run_snapshot",
        "input_snapshot",
        "sources",
        "name,",
        "purpose,",
        "execution_plan",
        "reason,",
    ):
        assert body not in sql
    if name in {"quality.issue.read", "test.run.read"}:
        assert "JOIN" in sql and "_revision =" in sql


@pytest.mark.parametrize(
    "field,value",
    [("category_id", None), ("product_id", None), ("project_id", None), ("isolation", "extract")],
)
def test_unbound_or_isolated_run_cannot_read(port, field, value):
    with pytest.raises(DomainError, match="领域读取须绑定"):
        port.port.call(replace(port.scope, **{field: value}), {}, name="build.read")
    assert not port.queries and port.authority_calls == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "cancelled"),
        ("project_id", UUID(int=99)),
        ("cancel_epoch", 1),
        ("reverted_at", datetime.now(UTC)),
    ],
)
def test_actual_run_binding_checked_before_query(port, field, value):
    setattr(port.run, field, value)
    with pytest.raises(DomainError):
        port.port.call(port.scope, {}, name="build.read")
    assert not port.queries


def test_revoked_authority_fails_before_select(port):
    def denied(*_):
        raise DomainError("FORBIDDEN_SCOPE", "revoked")

    port.port.store.authority = denied
    with pytest.raises(DomainError, match="revoked"):
        port.port.call(port.scope, {}, name="build.read")
    assert not port.queries


def test_metadata_pagination_and_no_free_text(port):
    port.rows = [build(101), build(102)]
    result = port.port.call(port.scope, {"page_size": 1}, name="build.read")
    assert len(result["items"]) == 1
    assert result["next_cursor"] == str(UUID(int=101)) and result["has_more"]
    assert result["basis_status"] == "not_assessed"
    assert result["items"][0]["revision"] == 3
    assert result["items"][0]["record_status"] == "planned"
    assert "name" not in result["items"][0] and "purpose" not in result["items"][0]
    assert port.authority_calls == 2
    port.rows = []
    assert port.port.call(port.scope, {}, name="build.read")["next_cursor"] is None
    with pytest.raises(DomainError):
        port.port.call(port.scope, {"build_id": str(UUID(int=99))}, name="build.read")


def test_outbound_internal_classification_is_server_bound(port):
    port.scope = replace(port.scope, data_categories=frozenset({"public"}))
    port.run.data_categories = port.scope.data_categories
    with pytest.raises(DomainError, match="内部业务资料出站类别"):
        port.port.call(port.scope, {}, name="build.read")
    assert not port.queries


def test_newly_private_project_requires_new_private_run(port):
    port.project.visibility = "private"
    with pytest.raises(DomainError, match="私有项目资料"):
        port.port.call(port.scope, {}, name="build.read")
    assert not port.queries


def test_unrelated_private_source_cannot_authorize_private_objects(port):
    scope = replace(port.scope, private_context=True)
    port.run.private_context = True
    port.port.call(scope, {}, name="build.read")
    query = port.queries[0].compile(dialect=postgresql.dialect())
    assert ["category"] in query.params.values()
    port.project.visibility = "private"
    port.port.call(scope, {}, name="build.read")
    query = port.queries[1].compile(dialect=postgresql.dialect())
    assert ["category", "private", "audience"] in query.params.values()


def test_restoration_rejects_changed_current_revision(port):
    port.rows = [build()]
    first = port.port.call(port.scope, {}, name="build.read")
    assert port.port.restore(port.scope, {}, first, name="build.read") == first
    port.rows[0].revision += 1
    with pytest.raises(DomainError) as stale:
        port.port.restore(port.scope, {}, first, name="build.read")
    assert stale.value.code == "SOURCE_STALE"


def test_shared_project_private_metadata_requires_exact_server_admission(port):
    port.scope = replace(port.scope, private_context=True)
    port.run.private_context = True
    port.run.versions = {
        module.CONTEXT_KEY: {
            "projection": module.PROJECTION,
            "project_id": str(port.scope.project_id),
            "product_id": str(port.scope.product_id),
            "private_objects": True,
        }
    }
    assert module._private_binding(port.run)
    port.port.call(port.scope, {}, name="build.read")
    query = port.queries[0].compile(dialect=postgresql.dialect())
    assert ["category", "private", "audience"] in query.params.values()
    port.run.versions[module.CONTEXT_KEY]["project_id"] = str(UUID(int=99))
    assert not module._private_binding(port.run)


@pytest.mark.parametrize("private", [False, True])
def test_server_admission_classifies_readable_private_metadata_without_bodies(port, private):
    port.product.id = port.scope.product_id
    seen = []
    session = NS(scalar=lambda query: seen.append(query) or private)
    result = module.bind_project_metadata(
        session, DomainCommands.context(port.scope), port.project, port.product
    )
    assert result["private_objects"] == private and result["project_id"] == str(
        port.scope.project_id
    )
    sql = str(seen[0].compile(dialect=postgresql.dialect()))
    assert "EXISTS" in sql and all(body not in sql for body in ("issue_snapshot", "run_snapshot"))


def test_project_read_module_imports_without_prior_common_model_import():
    import os
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "-c", "import pdos_next.agent_kernel.project_object_reads"],
        env={**os.environ, "PYTHONPATH": str(Path(module.__file__).parents[2])},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
