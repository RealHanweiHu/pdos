"""Real owner/current/SQL clocks, with synthetic API-created fixed preparation facts."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from build_operational_facts.fixtures import (  # noqa: F401
    imported,
    known_configuration,
    operational_work,
)
from manufacturing_preparation_transactions.fixtures import (
    bootstrap_authority,
    effect_hashes,
    inputs,
    payload,
)
from manufacturing_preparation_transactions.test_transactions import reference, save
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_builds import build_command
from test_project_first_plan import accepted, cmd

from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.change_graph_closure import (
    closure_stamp,
    lock_dependency_clock,
    recheck_graph_closure,
)
from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.change_control.rules import compute_impact, digest
from pdos_next.domain.change_execution.graph import OwnerReader, audience, capture_graph
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product, now
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef


def epoch(work, session=None):
    def read(s):
        return s.scalar(
            select(ChangeDependencyClock.epoch).where(
                ChangeDependencyClock.tenant_id == work.setup.tenant,
                ChangeDependencyClock.product_id == work.setup.product,
            )
        )

    if session is not None:
        return read(session)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.ctx.actor_id,
        requester_id=work.setup.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        return read(s)


def graph(work):
    setup = work.setup
    scope = Scope(tenant_id=setup.tenant, product_id=setup.product, project_id=work.project_id)
    at = now()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        reader = OwnerReader(
            s,
            setup.ctx,
            setup.product,
            scope,
            audience(setup.product, setup.human, "private"),
            None,
        )
        return capture_graph(
            reader,
            identity=uuid4(),
            roots=(Ref(kind="manufacturing_configuration", **work.process_ref),),
            captured_at=at,
            expires_at=at + timedelta(minutes=10),
            nature="synthetic",
            sources=(
                SourceRef(id=work.document_source, revision=1, kind="artifact", position="line:1"),
            ),
        )


def recheck(work, captured, expected=None):
    setup = work.setup
    command = Command.model_validate(cmd(setup, "change.order.approve", {}))
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        current = closure_stamp(s, setup.ctx, scope=captured.scope, audience=captured.audience)
        return recheck_graph_closure(
            s,
            setup.ctx,
            command,
            graph=captured,
            scope=captured.scope,
            audience=captured.audience,
            roots=captured.roots,
            expected_closure=current if expected is None else expected,
            valid_until=captured.expires_at,
            complete_recheck=True,
        )


def test_actual_manufacturing_nodes_current_children_and_dependency_clock(manufacturing_case):
    work, setup = manufacturing_case, manufacturing_case.setup
    assert epoch(work) > 1  # API-created parent/source ledgers have real DB mutations.
    bootstrap_authority(work)
    before_preview = epoch(work)
    wi_input = inputs(work, "work_instruction", payload(work, "work_instruction"))
    assert epoch(work) == before_preview  # inputs/preview/confirmation are not dependency facts.
    _, _, wi = save(work, wi_input)
    _, _, cp = save(work, inputs(work, "control_plan", payload(work, "control_plan")))
    _, _, baseline = save(
        work,
        inputs(
            work,
            "manufacturing_baseline",
            payload(
                work,
                "manufacturing_baseline",
                documents={"work_instruction": reference(wi), "control_plan": reference(cp)},
            ),
        ),
    )
    before_read = effect_hashes(work), epoch(work)
    captured = graph(work)
    nodes = {node.ref.identity: node for node in captured.nodes}
    for view in (wi, cp, baseline):
        ref = Ref(kind=view["kind"], id=view["id"], revision=view["revision"])
        assert ref.identity in nodes
    baseline_ref = Ref(kind="manufacturing_baseline", id=baseline["id"], revision=1)
    assert {
        (edge.target.kind, str(edge.target.id), edge.target.revision)
        for edge in captured.edges
        if edge.origin == baseline_ref
    } >= {("work_instruction", wi["id"], 1), ("control_plan", cp["id"], 1)}
    assert all(row.status == "unknown" for row in captured.coverage)
    assessment = compute_impact(captured, 1)
    assert {unknown.facet for unknown in assessment.unknown} == {
        "engineering",
        "manufacturing",
        "evidence_applicability",
        "in_process_builds",
        "customer_samples",
        "supply_inventory_wip",
        "production_switch",
        "training",
    }
    assert effect_hashes(work) == before_read[0] and epoch(work) == before_read[1]
    checked = recheck(work, captured)
    assert checked.graph is captured and checked.authority_attested is False
    assert checked.required_source_read_set
    assert effect_hashes(work) == before_read[0] and epoch(work) == before_read[1]

    # An allowed actual project edit and restore leaves its original material but
    # advances the dedicated DB clock twice, including through the same Session.
    with Session(setup.admin) as s, s.begin():
        original = s.scalar(select(Project.scope).where(Project.id == work.project_id))
        s.execute(
            update(Project).where(Project.id == work.project_id).values(scope="Synthetic ABA edit")
        )
        s.execute(update(Project).where(Project.id == work.project_id).values(scope=original))
    assert epoch(work) == before_read[1] + 2
    with pytest.raises(DomainError) as changed:
        recheck(work, captured, checked.closure)
    assert changed.value.reason == "RECHECK_REQUIRED"
    assert digest(
        graph(work).model_copy(
            update={
                "id": captured.id,
                "captured_at": captured.captured_at,
                "expires_at": captured.expires_at,
            }
        )
    ) == digest(captured)

    # Product's own business fields also fence ABA, while ordinary lifecycle-only
    # bookkeeping must not invalidate a graph through its common receipt tail.
    stable = recheck(work, captured)
    with Session(setup.admin) as s, s.begin():
        original_name = s.scalar(select(Product.name).where(Product.id == setup.product))
        s.execute(
            update(Product).where(Product.id == setup.product).values(name="Synthetic ABA name")
        )
        s.execute(update(Product).where(Product.id == setup.product).values(name=original_name))
    assert epoch(work) == stable.closure["dependency_epoch"] + 2
    with pytest.raises(DomainError) as changed:
        recheck(work, captured, stable.closure)
    assert changed.value.reason == "RECHECK_REQUIRED"
    stable = recheck(work, captured)
    with Session(setup.admin) as s, s.begin():
        s.execute(update(Product).where(Product.id == setup.product).values(lifecycle_epoch=12345))
    assert epoch(work) == stable.closure["dependency_epoch"]
    assert recheck(work, captured, stable.closure).closure == stable.closure
    with (
        pytest.raises(RuntimeError, match="synthetic rollback"),
        Session(setup.admin) as s,
        s.begin(),
    ):
        s.execute(
            update(Project)
            .where(Project.id == work.project_id)
            .values(scope="Rolled back dependency")
        )
        raise RuntimeError("synthetic rollback")
    assert epoch(work) == stable.closure["dependency_epoch"]
    assert recheck(work, captured, stable.closure).closure == stable.closure

    # Counter writes cannot be forged, even by the isolated privileged test actor.
    before_rejection = epoch(work)
    with pytest.raises(DBAPIError), Session(setup.admin) as s, s.begin():
        s.execute(update(ChangeDependencyClock).values(epoch=1))
    assert epoch(work) == before_rejection
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.ctx.actor_id,
            requester_id=setup.ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        s.execute(update(ChangeDependencyClock).values(epoch=1))
    assert epoch(work) == before_rejection
    with Session(setup.admin) as s:
        for role in ("pdos_next_app", "pdos_next_auth", "pdos_agent"):
            for operation in ("INSERT", "UPDATE", "DELETE"):
                assert (
                    s.scalar(
                        text("SELECT has_table_privilege(:role, 'change_dependency_clocks', :op)"),
                        {"role": role, "op": operation},
                    )
                    is False
                )

    # Actual new Build reverse dependency is visible on a fresh traversal.
    old_graph = graph(work)
    old_proof = recheck(work, old_graph)
    build, _ = accepted(setup, build_command(setup, work.config))
    latest = graph(work)
    assert any(
        node.ref.kind == "build" and str(node.ref.id) == build["subject_id"]
        for node in latest.nodes
    )
    assert not any(node.ref.kind == "build" for node in old_graph.nodes)
    assert epoch(work) > before_rejection
    with pytest.raises(DomainError) as new_dependency:
        recheck(work, old_graph, old_proof.closure)
    assert new_dependency.value.reason == "RECHECK_REQUIRED"
    assert build["subject_id"] not in str(new_dependency.value)

    # A new WI Current makes the captured fixed baseline need recheck. It is
    # never silently replaced or treated as released/qualified in a new graph.
    saved_body = deepcopy(wi["body"])
    _, _, wi2 = save(
        work,
        inputs(
            work, "work_instruction", payload(work, "work_instruction", previous=wi, revision=2)
        ),
    )
    assert wi2["revision"] == 2
    with pytest.raises(DomainError) as stale:
        graph(work)
    assert stale.value.reason == "RECHECK_REQUIRED"
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/manufacturing-preparations/work_instruction/{wi['id']}?revision=1",
        headers=setup.headers,
    )
    assert response.status_code == 200 and response.json()["body"] == saved_body
    assert response.json()["is_current"] is False
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(select(Confirmation.id).where(Confirmation.actor_id == setup.human))
            is not None
        )


def test_new_product_clock_and_tenant_isolation(setup):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        rows = list(s.scalars(select(ChangeDependencyClock)))
        assert len(rows) == 1 and rows[0].product_id == setup.product and rows[0].epoch == 1
    with tenant_session(
        setup.engine,
        setup.other_human,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        assert list(s.scalars(select(ChangeDependencyClock))) == []
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json=cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Hidden dependency source",
                "content": "Explicit synthetic private source",
                "source_label": "Synthetic fixture",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(ChangeDependencyClock.epoch)) == 2


def test_actual_tenant_shared_asset_fence_and_rejected_roles(operational_work):  # noqa: F811
    """Real SQL clock isolation only; this creates no qualified resource fact."""
    from pdos_next.domain.build_operational_facts.models import OperationalAsset

    setup = operational_work.setup
    imported(operational_work)
    second_product, asset = uuid4(), operational_work.resource_id
    with Session(setup.admin) as s, s.begin():
        s.add(
            Product(
                id=second_product,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                category_id=setup.category,
                visibility="category",
                name="Synthetic clock peer",
                purpose="SQL isolation only",
            )
        )
        s.flush()
    with Session(setup.admin) as s:
        before = dict(
            s.execute(
                select(ChangeDependencyClock.product_id, ChangeDependencyClock.epoch).where(
                    ChangeDependencyClock.tenant_id == setup.tenant
                )
            ).all()
        )
        assert set(before) == {setup.product, second_product}
        assert all(type(epoch) is int and epoch > 0 for epoch in before.values())
        for role in ("pdos_agent", "pdos_next_auth"):
            assert (
                s.scalar(
                    text(
                        "SELECT has_function_privilege(:role, "
                        "'lock_change_dependency_clock(uuid,uuid)','EXECUTE')"
                    ),
                    {"role": role},
                )
                is False
            )
        assert (
            s.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_proc p, "
                    "LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
                    "WHERE p.oid='lock_change_dependency_clock(uuid,uuid)'::regprocedure "
                    "AND a.grantee=0 AND a.privilege_type='EXECUTE')"
                )
            )
            is False
        )

    def contend():
        try:
            with Session(setup.admin) as s, s.begin():
                s.execute(text("SET LOCAL lock_timeout='500ms'"))
                s.execute(
                    update(OperationalAsset)
                    .where(OperationalAsset.id == asset)
                    .values(occupancy_epoch=OperationalAsset.occupancy_epoch + 1)
                )
        except DBAPIError as error:
            return error.orig.sqlstate
        return "UNEXPECTED_COMMIT"

    scope = Scope(
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(operational_work.config["project"]),
    )
    target = audience(setup.product, setup.human, "private")
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        assert (
            lock_dependency_clock(s, setup.ctx, scope=scope, audience=target)
            == before[setup.product]
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(contend).result(timeout=5) == "55P03"
        assert (
            s.scalar(select(OperationalAsset.occupancy_epoch).where(OperationalAsset.id == asset))
            == 1
        )
        assert (
            dict(
                s.execute(
                    select(ChangeDependencyClock.product_id, ChangeDependencyClock.epoch)
                ).all()
            )
            == before
        )
    with Session(setup.admin) as s, s.begin():
        s.execute(
            update(OperationalAsset)
            .where(OperationalAsset.id == asset)
            .values(occupancy_epoch=OperationalAsset.occupancy_epoch + 1)
        )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as s:
        assert dict(
            s.execute(select(ChangeDependencyClock.product_id, ChangeDependencyClock.epoch)).all()
        ) == {key: value + (key == setup.product) for key, value in before.items()}
    with (
        pytest.raises(DBAPIError),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.ctx.actor_id,
            requester_id=setup.ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        s.execute(
            text("SELECT lock_change_dependency_clock(:tenant,:product)"),
            {"tenant": setup.other_human, "product": setup.product},
        )
