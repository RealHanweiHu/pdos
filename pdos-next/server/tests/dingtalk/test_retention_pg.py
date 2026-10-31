"""Root-run native PG retention/lock probes. No send, model or real provider.

Sources are actual native uploaded/parsed private originals and ordinary Human
source projections. Delivery rows are deliberate server-side retention fixtures,
not claims of passing P31 outbound taint. No original text is copied or sent.
Pending/quarantine probes always roll back their entire outer transaction.
"""
# ruff: noqa: F401,F811 -- register the exact original native fixture tree

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pdos_next.database import tenant_session
from pdos_next.dingtalk.models import Delivery, Message
from pdos_next.dingtalk.runtime import delivery_key
from pdos_next.dingtalk.schemas import ChannelReference
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.models import Artifact, Category, Grant, LifecycleObject, Product, now
from pdos_next.service import digest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.dingtalk.test_channel_pg import bind, channel, incoming
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


class ProbeRollback(Exception):
    """Controlled destructive-state probes never commit invented lifecycle decisions."""


def source(work):
    original = uploaded(work, visibility="private", content=b"Private local retention fixture only")
    identity = parsed(work, original)
    setup = work.setup
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        read_snapshot=True,
    ) as session:
        prepare_read(session, ["artifact"])
        row = (
            session.execute(select_sources(source_type="artifact", source_id=identity))
            .mappings()
            .one()
        )
        assert row["private"]
        proof = {
            key: str(row[key]) if key in {"source_id", "category_id"} else row[key]
            for key in (
                "source_type",
                "source_id",
                "source_revision",
                "content_hash",
                "category_id",
            )
        }
    return original, identity, proof


def message(channel, key="retention-1"):
    response = incoming(channel, message_id=key)
    assert response.status_code == 202, response.text
    return UUID(response.json()["message_id"])


def delivery(channel, mid, proof):
    with Session(channel.setup.admin) as session:
        actual_run_id = session.get(Message, mid).run_id
    body = {
        "target_kind": "direct",
        "target_id": "external-owner",
        "text": "Retention metadata fixture; no original text",
        "url": "https://pdos.synthetic.invalid/dingtalk/runs/" + str(actual_run_id),
    }
    return dict(
        id=uuid4(),
        tenant_id=channel.setup.tenant,
        message_id=mid,
        owner_id=channel.setup.human,
        consent_id=None,
        request_key=delivery_key(mid, "answer"),
        phase="answer",
        payload=body,
        payload_sha256=digest(body),
        content_kind="answer",
        source_dependencies=deepcopy(proof),
        state="planned",
        attempts=0,
        created_at=now(),
    )


def epochs(session, categories, products):
    return (
        dict(
            session.execute(
                select(Category.id, Category.lifecycle_epoch).where(Category.id.in_(categories))
            ).all()
        ),
        dict(
            session.execute(
                select(Product.id, Product.lifecycle_epoch).where(Product.id.in_(products))
            ).all()
        ),
    )


def metadata_roots(session, setup, category, value):
    metadata = {
        key: str(value[key]) if key == "tenant_id" else value[key]
        for key in ("tenant_id", "source_dependencies", "content_kind")
    }
    return set(
        session.scalar(
            text("SELECT public.m3_lifecycle_roots(:t,:c,'dingtalk_deliveries',CAST(:p AS jsonb))"),
            {"t": setup.tenant, "c": category, "p": json.dumps(metadata)},
        )
    )


def test_private_two_category_delivery_retains_each_actual_root_without_service_body_read(
    channel, security_work
):
    setup = channel.setup
    # Seed a second new self-owned synthetic scope exactly as the core setup
    # factory does; no existing owner/ACL is patched. Upload/scan/parse still use
    # real native commands and the existing explicit synthetic security ports.
    category2, product2 = uuid4(), uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=category2,
                tenant_id=setup.tenant,
                name="Second private retention scope",
                purpose="Synthetic source grouping",
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(
            Product(
                id=product2,
                tenant_id=setup.tenant,
                category_id=category2,
                name="Second synthetic product",
                purpose="Retention fixture",
                owner_id=setup.human,
            )
        )
        session.add_all(
            [
                Grant(
                    tenant_id=setup.tenant,
                    category_id=category2,
                    principal_id=person,
                    can_write=True,
                    expires_at=now() + timedelta(hours=1),
                )
                for person in [setup.human, setup.peer, setup.agent]
            ]
        )
    second_setup = SimpleNamespace(
        **{
            **vars(setup),
            "category": category2,
            "product": product2,
            "ctx": replace(setup.ctx, category_id=category2),
        }
    )
    second_work = SimpleNamespace(**{**vars(security_work), "setup": second_setup})
    root1, artifact1, proof1 = source(security_work)
    root2, artifact2, proof2 = source(second_work)
    bind(channel)
    mid = message(channel)
    value = delivery(channel, mid, [proof2, proof1])  # deliberate reverse order
    with tenant_session(
        setup.admin, setup.tenant, actor_id=setup.human, requester_id=setup.human
    ) as session:
        before = epochs(session, [setup.category, category2], [setup.product, product2])
    with channel.service.metadata(ChannelReference(tenant_id=setup.tenant, message_id=mid)) as (
        session,
        actual_message,
        _app,
    ):
        assert session.get(Artifact, artifact1) is None and session.get(Artifact, artifact2) is None
        session.execute(insert(Delivery.__table__).values(**value))
    with tenant_session(
        setup.admin, setup.tenant, actor_id=setup.human, requester_id=setup.human
    ) as session:
        after = epochs(session, [setup.category, category2], [setup.product, product2])
        assert all(after[i][key] == before[i][key] + 1 for i in (0, 1) for key in before[i])
        assert metadata_roots(session, setup, setup.category, value) == {root1}
        assert metadata_roots(session, setup, category2, value) == {root2}
        for cat, expected in [(setup.category, artifact1), (category2, artifact2)]:
            nodes = session.execute(
                text(
                    "SELECT table_name,node_id,links FROM "
                    "public.m3_lifecycle_nodes(:t,:c,CAST(:ids AS uuid[]))"
                ),
                {"t": setup.tenant, "c": cat, "ids": [value["id"]]},
            ).all()
            assert len(nodes) == 1 and nodes[0][:2] == ("dingtalk_deliveries", value["id"])
            assert expected in nodes[0].links
        assert session.execute(
            text(
                "SELECT node_id FROM public.m3_lifecycle_nodes(:t,:c) "
                "WHERE table_name='dingtalk_deliveries'"
            ),
            {"t": setup.tenant, "c": setup.category},
        ).scalars().all() == [value["id"]]
        assert metadata_roots(session, setup, uuid4(), value) == set()
    assert channel.runtime.adapter.send_count == 0


@pytest.mark.parametrize("state", ["pending", "quarantined"])
def test_pending_original_blocks_new_body_copy_but_existing_receipt_metadata_can_update(
    channel, security_work, state
):
    setup = channel.setup
    original, _artifact, proof = source(security_work)
    bind(channel)
    mid1, mid2 = message(channel), message(channel, "retention-2")
    first = delivery(channel, mid1, [proof])
    with channel.service.metadata(ChannelReference(tenant_id=setup.tenant, message_id=mid1)) as (
        session,
        _message,
        _app,
    ):
        session.execute(insert(Delivery.__table__).values(**first))
    with pytest.raises(ProbeRollback):
        with tenant_session(
            setup.admin, setup.tenant, actor_id=setup.human, requester_id=setup.human
        ) as session:
            session.add(
                LifecycleObject(
                    id=original,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product,
                    owner_id=setup.human,
                    reference={},
                    state={
                        "value": {
                            "pending_intent_id": str(uuid4()) if state == "pending" else None,
                            "disposition": "active" if state == "pending" else "quarantined",
                        }
                    },
                )
            )
            session.flush()
            before = epochs(session, [setup.category], [setup.product])
            # After rollback-only maintenance setup, bind the actual channel Agent
            # context and ordinary app role. No human identity is lent to the INSERT.
            session.execute(
                text(
                    "SELECT set_config('pdos.actor_id',:agent,true),"
                    "set_config('pdos.requester_id',:agent,true)"
                ),
                {"agent": str(setup.agent)},
            )
            session.execute(text("SET LOCAL ROLE pdos_next_app"))
            with pytest.raises(DBAPIError) as error:
                with session.begin_nested():
                    session.execute(
                        insert(Delivery.__table__).values(**delivery(channel, mid2, [proof]))
                    )
            assert (
                error.value.orig.sqlstate == "23514"
                and error.value.orig.diag.constraint_name == "m3_source_reference_fence"
            )
            # Only technical receipt state changes: no body/proof rewrite and no
            # category/product epoch change. It must remain possible to reconcile.
            session.execute(
                update(Delivery)
                .where(Delivery.id == first["id"])
                .values(state="blocked", error_code="SOURCE_STALE")
            )
            assert epochs(session, [setup.category], [setup.product]) == before
            raise ProbeRollback
    with Session(setup.admin) as session:
        assert session.get(LifecycleObject, original) is None
    assert channel.runtime.adapter.send_count == 0


def test_delivery_footprint_is_immutable_and_lifecycle_helpers_are_not_runtime_read_ports(
    channel, security_work
):
    setup = channel.setup
    _original, _artifact, proof = source(security_work)
    bind(channel)
    mid = message(channel)
    value = delivery(channel, mid, [proof])
    with channel.service.metadata(ChannelReference(tenant_id=setup.tenant, message_id=mid)) as (
        session,
        _message,
        _app,
    ):
        session.execute(insert(Delivery.__table__).values(**value))
    with channel.service.metadata(ChannelReference(tenant_id=setup.tenant, message_id=mid)) as (
        session,
        _message,
        _app,
    ):
        for field, replacement in [
            ("source_dependencies", [{**proof, "category_id": str(uuid4())}]),
            ("payload_sha256", "b" * 64),
        ]:
            with pytest.raises(DBAPIError) as error:
                with session.begin_nested():
                    session.execute(
                        update(Delivery)
                        .where(Delivery.id == value["id"])
                        .values(**{field: replacement})
                    )
            assert error.value.orig.sqlstate == "23514"
    with Session(setup.admin) as session:
        for function in [
            "assistant_source_lifecycle_links(uuid,uuid,jsonb)",
            "dingtalk_lifecycle_reference_clock()",
            "dingtalk_lifecycle_reference_gate()",
        ]:
            for role in ["pdos_next_app", "pdos_agent", "pdos_next_auth", "pdos_next_dispatch"]:
                assert not session.scalar(
                    text("SELECT has_function_privilege(:role,:function,'EXECUTE')"),
                    {"role": role, "function": function},
                )
        for role in ["pdos_next_app", "pdos_agent", "pdos_next_auth", "pdos_next_dispatch"]:
            assert not session.scalar(
                text("SELECT pg_has_role(:role,'pdos_next_owner','MEMBER')"), {"role": role}
            )
    assert channel.runtime.adapter.send_count == 0
