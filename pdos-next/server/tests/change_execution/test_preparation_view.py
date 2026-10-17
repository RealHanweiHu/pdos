"""Pure read adapters with explicit owner/SQL substitutes, never PG or qualification proof."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from pdos_next import change_preparation_view as view
from pdos_next import service as common
from pdos_next.domain.change_execution import api, service
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.service import Context

from . import kernel_helpers as helper


@pytest.fixture
def case(monkeypatch):
    host = helper.FakeHost()
    host.analyze()
    request = host.request_value
    actor, category = uuid4(), uuid4()
    ctx = Context(request.scope.tenant_id, actor, actor, category_id=category)
    purpose = "Synthetic bounded preparation"
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=category,
        product_id=request.scope.product_id,
        project_id=request.scope.project_id,
        change_id=request.id,
        revision=request.revision,
        owner_id=actor,
        visibility="category",
        status=request.status,
        operation="change.impact.compute",
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=helper.digest(request),
        sources=[],
        required_source_read_set=[],
    )
    material = view.models.SelectionMaterial(
        schema_version="pdos-controlled-change-selection-v1",
        scope=request.scope,
        purpose=purpose,
        change_id=request.id,
        item=helper.plan().items[0],
        issue_id=helper.uid("issue"),
        capa_id=helper.uid("capa"),
        action_id=helper.uid("action"),
        action_sha256="a" * 64,
        executor_id=helper.uid("executor"),
        decider_id=actor,
        status="applicable",
        valid_until=helper.NOW + timedelta(hours=1),
        reason="Synthetic named applicability material",
        nature="synthetic",
    )
    action = {
        "issue_id": str(material.issue_id),
        "issue_revision": 7,
        "capa_id": str(material.capa_id),
        "action_id": str(material.action_id),
        "executor_id": str(material.executor_id),
        "text": "Actual linked action",
        "kind": "corrective",
        "completion": None,
    }
    monkeypatch.setattr(view, "_current", lambda *a: (row, request, purpose))
    monkeypatch.setattr(view, "_actions", lambda *a: [deepcopy(action)])
    monkeypatch.setattr(view.controlled, "clock", lambda: helper.NOW)
    return SimpleNamespace(
        ctx=ctx,
        row=row,
        request=request,
        purpose=purpose,
        material=material,
        action=action,
        pid=request.scope.product_id,
    )


def test_registered_material_builds_token_free_candidate_using_actual_action_revision(
    case, monkeypatch
):
    monkeypatch.setattr(view.controlled, "original", lambda *a: (case.material, None))
    monkeypatch.setattr(view.controlled, "selection_pointer", lambda *a: (None, None))
    monkeypatch.setattr(view, "_one", lambda *a: SimpleNamespace(revision=11))
    received = []

    def prepare(session, ctx, pid, command):
        received.append(command)
        return {
            "command": view.Command.model_validate(
                {
                    **command.model_dump(mode="json"),
                    "source_read_set": [{"artifact_id": helper.SOURCE.id, "expected_revision": 1}],
                }
            ).model_dump(mode="json"),
            "required_source_read_set": [
                {"artifact_id": str(helper.SOURCE.id), "expected_revision": 1}
            ],
        }

    monkeypatch.setattr(view.selection, "inputs", prepare)
    data = view.SelectionMaterialInput(
        change_id=case.request.id, expected_change_revision=case.row.revision, source=helper.SOURCE
    )
    result = view.selection_material(object(), case.ctx, case.pid, data)
    command = result["command"]
    assert len(received) == 1 and command["operation"] == "change.selection.decide"
    assert command["expected_revision"] == 11
    assert command["payload"]["action"]["expected_issue_revision"] == 7
    assert command["payload"]["item"] == case.material.item.model_dump(mode="json")
    assert "approval_token" not in command["payload"]
    assert result["material"] == case.material.model_dump(mode="json")
    assert result["required_source_read_set"] == command["source_read_set"]


@pytest.mark.parametrize("field", ["scope", "decider_id", "change_id"])
def test_registered_material_cannot_cross_project_decider_or_current_change(
    case, monkeypatch, field
):
    value = (
        case.request.scope.model_copy(update={"project_id": uuid4()})
        if field == "scope"
        else uuid4()
    )
    monkeypatch.setattr(
        view.controlled,
        "original",
        lambda *a: (case.material.model_copy(update={field: value}), None),
    )
    data = view.SelectionMaterialInput(
        change_id=case.request.id, expected_change_revision=case.row.revision, source=helper.SOURCE
    )
    with pytest.raises(DomainError) as failure:
        view.selection_material(object(), case.ctx, case.pid, data)
    assert failure.value.status == 403


def test_empty_context_does_not_turn_graph_nodes_into_selection_or_policy(case, monkeypatch):
    objects = [
        {
            "ref": helper.ref("engineering_configuration").model_dump(mode="json"),
            "label": "Fixed actual graph node",
            "source": helper.SOURCE.model_dump(mode="json"),
        }
    ]
    monkeypatch.setattr(view, "_objects", lambda *a: objects)

    def absent(*a, **k):
        raise DomainError("CHANGE_POLICY_OWNER_REQUIRED", "No actual policy publication", 503)

    monkeypatch.setattr(view.controlled, "policy_callback", absent)
    session = SimpleNamespace(scalars=lambda query: iter(()))
    result = view.order_context(session, case.ctx, case.pid, case.request.id)
    assert result["policy"] is None and result["selections"] == []
    assert result["object_options"] == objects and result["missing"]
    assert result["actions"][0]["action_id"] == case.action["action_id"]


def test_object_options_match_known_disposition_scope_and_keep_actual_node_sources(
    case, monkeypatch
):
    assessment = case.request.assessments[-1]
    unreachable = assessment.graph.nodes[0].model_copy(
        update={"ref": helper.ref("evidence", "unreachable"), "label": "Not an affected object"}
    )
    graph = assessment.graph.model_copy(update={"nodes": (*assessment.graph.nodes, unreachable)})
    request = case.request.model_copy(
        update={"assessments": (assessment.model_copy(update={"graph": graph}),)}
    )
    monkeypatch.setattr(view.change, "_issue_loader", lambda *a: object())
    monkeypatch.setattr(
        view,
        "OwnerReader",
        lambda *a: SimpleNamespace(resolve=lambda ref: SimpleNamespace(current=True)),
    )
    result = view._objects(object(), case.ctx, case.pid, request)
    assert result == [
        {
            "ref": value.node.ref.model_dump(mode="json"),
            "label": value.node.label,
            "source": value.node.source.model_dump(mode="json"),
        }
        for value in assessment.known
    ]
    assert all(value["ref"] != unreachable.ref.model_dump(mode="json") for value in result)


@pytest.mark.parametrize("forbidden", [False, True])
def test_live_selection_recheck_failure_never_becomes_a_positive_option(
    case, monkeypatch, forbidden
):
    material = case.material
    fact = SimpleNamespace(
        id=uuid4(),
        revision=1,
        owner_id=case.row.owner_id,
        visibility="category",
        purpose=case.purpose,
        change_id=case.request.id,
        item_id=material.item.id,
        item_sha256=helper.digest(material.item),
        material=material.model_dump(mode="json"),
        material_sha256=helper.digest(material),
        actor_id=material.decider_id,
        status=material.status,
        valid_until=material.valid_until,
        nature=material.nature,
        issue_id=material.issue_id,
        capa_id=material.capa_id,
        action_id=material.action_id,
        action_sha256=material.action_sha256,
        source=helper.SOURCE.model_dump(mode="json"),
        sources=[],
        required_source_read_set=[],
        source_basis={},
        confirmation_material_sha256="b" * 64,
    )
    monkeypatch.setattr(view.controlled, "original", lambda *a: (material, None))
    monkeypatch.setattr(view.controlled, "original_authority", lambda *a: None)
    monkeypatch.setattr(view.controlled, "_source_guard", lambda *a: {})
    monkeypatch.setattr(view, "common_group", lambda *a, **k: {"receipt": {"id": uuid4()}})
    monkeypatch.setattr(view.controlled, "_atom_proof", lambda *a: None)

    def stale(*a, **k):
        raise DomainError(
            "FORBIDDEN_SCOPE" if forbidden else "SOURCE_STALE",
            "Actual owner rejected this selection",
            403 if forbidden else 409,
        )

    monkeypatch.setattr(view.controlled, "selection_callback", stale)
    if forbidden:
        with pytest.raises(DomainError) as failure:
            view._selection_record(
                object(), case.ctx, case.pid, case.row, case.request, case.purpose, fact
            )
        assert failure.value.status == 403
    else:
        result = view._selection_record(
            object(), case.ctx, case.pid, case.row, case.request, case.purpose, fact
        )
        assert result["source_status"] == "needs_recheck" and result["missing"]


def test_project_filter_reaches_both_change_pages_and_capture_subqueries(monkeypatch):
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    project, product, queries = uuid4(), uuid4(), []
    monkeypatch.setattr(service, "_human", lambda *a: None)
    monkeypatch.setattr(common, "require_access", lambda *a, **k: None)

    def read(query):
        queries.append(query)
        return iter(())

    result = service.list_changes(
        SimpleNamespace(execute=read, scalars=read), ctx, product, project_id=project
    )
    assert result["changes"] == result["captures"] == []
    assert len(queries) == 4
    assert all(project in query.compile().params.values() for query in queries)


def test_new_routes_preserve_query_guards_and_read_transaction_modes(monkeypatch):
    app, calls = FastAPI(), []
    actor, product, change_id, category = uuid4(), uuid4(), uuid4(), uuid4()
    ctx = Context(uuid4(), actor, actor, category_id=category)

    @app.exception_handler(DomainError)
    async def error_handler(request, error):
        return JSONResponse(error.payload(), status_code=error.status)

    @contextmanager
    def session(engine, tenant_id, **kwargs):
        calls.append(kwargs)
        yield object()

    monkeypatch.setattr(api, "tenant_session", session)
    monkeypatch.setattr(view, "order_context", lambda *a: {"change_id": str(a[-1])})
    monkeypatch.setattr(view, "selection_material", lambda *a: {"change_id": str(a[-1].change_id)})
    api.register_routes(app, object(), Depends(lambda: ctx))
    path = f"/v1/categories/{category}/products/{product}/change-execution"
    with TestClient(app) as client:
        assert (
            client.get(
                path + "/order-context",
                params=[("change_id", str(change_id)), ("change_id", str(change_id))],
            ).status_code
            == 422
        )
        assert calls == []
        response = client.get(path + "/order-context", params={"change_id": str(change_id)})
        assert response.status_code == 200 and response.json()["change_id"] == str(change_id)
        assert calls[-1]["read_snapshot"] is True
        response = client.post(
            path + "/selection-material",
            json={
                "change_id": str(change_id),
                "expected_change_revision": 2,
                "source": helper.SOURCE.model_dump(mode="json"),
            },
        )
        assert response.status_code == 200 and response.json()["change_id"] == str(change_id)
        assert not calls[-1].get("read_snapshot", False)
