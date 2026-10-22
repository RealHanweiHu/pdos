from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_definition_transactions import command, definitions, payload, post, source

from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.models import ObjectAudience
from pdos_next.service import Context


def named_review(setup, object_type, identity):
    with Session(setup.admin) as s, s.begin():
        s.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type=object_type,
                subject_id=UUID(identity),
                owner_id=setup.human,
                principal_id=setup.peer,
            )
        )


def peer_setup(setup):
    return type(setup)(
        **{
            **vars(setup),
            "headers": {"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
            "ctx": Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category),
        }
    )


def test_audience_target_must_exist_and_have_the_actual_owner(setup):
    import pytest
    from sqlalchemy.exc import DBAPIError

    artifact = source(setup)
    for identity, owner in ((UUID(artifact), setup.peer), (uuid4(), setup.human)):
        with pytest.raises(DBAPIError) as rejected:
            with Session(setup.admin) as s, s.begin():
                s.add(ObjectAudience(
                    tenant_id=setup.tenant, category_id=setup.category,
                    object_type="artifact_versions", subject_id=identity,
                    owner_id=owner, principal_id=setup.peer,
                ))
        assert rejected.value.orig.sqlstate == "23514"


def test_named_reviewer_reads_private_definition_then_source_revoke_hides_derived_body(setup):
    artifact = source(setup)
    saved = post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    assert saved.status_code == 200, saved.text
    identity = saved.json()["subject_id"]
    named_review(setup, "definition_revisions", identity)
    peer = peer_setup(setup)
    # An authorized output cannot expose an inaccessible direct source's body.
    assert definitions(peer).json()["items"] == []
    named_review(setup, "artifact_versions", artifact)
    visible = definitions(peer)
    assert visible.status_code == 200, visible.text
    assert visible.json()["items"][0]["sources"][0]["quote"] == "Pressure: 150 PSI"
    workspace = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/workspace",
        headers=peer.headers,
    )
    assert workspace.status_code == 200 and workspace.json()["sources"][0]["id"] == artifact
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(DefinitionRevision, UUID(identity)) is not None
    with Session(setup.admin) as s, s.begin():
        s.execute(
            delete(ObjectAudience).where(
                ObjectAudience.subject_id == UUID(artifact),
                ObjectAudience.principal_id == setup.peer,
            )
        )
    hidden = definitions(peer)
    assert hidden.status_code == 200 and hidden.json()["items"] == []
    assert "Pressure: 150 PSI" not in hidden.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(DefinitionRevision, UUID(identity)) is None


def test_designated_audience_source_cannot_expand_to_category_definition(setup):
    artifact = source(setup, visibility="audience")
    named_review(setup, "artifact_versions", artifact)
    response = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(artifact, visibility="category"),
            artifact,
        ),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(DefinitionRevision.id).where(
                    DefinitionRevision.tenant_id == setup.tenant,
                )
            )
            is None
        )


def test_audience_revoke_waits_for_new_command_then_hides_private_derived_claim(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import pytest
    from sqlalchemy import event, text
    from sqlalchemy.exc import DBAPIError
    from test_trusted_source_work import claim_cmd

    from pdos_next.models import Claim, Receipt

    artifact = source(setup)
    named_review(setup, "artifact_versions", artifact)
    peer = peer_setup(setup)
    value = claim_cmd(setup, artifact, line=2)
    entered, release = Event(), Event()

    def paused(_mapper, _connection, target):
        if target.operation == "evidence.claim.record" and target.requester_id == setup.peer:
            entered.set()
            assert release.wait(5), "Synthetic receipt pause was not released"

    def save():
        return setup.client.post(
            f"/v1/categories/{setup.category}/commands", json=value, headers=peer.headers
        )

    event.listen(Receipt, "before_insert", paused)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(save)
            try:
                assert entered.wait(5)
                with pytest.raises(DBAPIError) as blocked:
                    with Session(setup.admin) as s, s.begin():
                        s.execute(text("SET LOCAL lock_timeout='150ms'"))
                        s.execute(
                            delete(ObjectAudience).where(
                                ObjectAudience.subject_id == UUID(artifact),
                                ObjectAudience.principal_id == setup.peer,
                            )
                        )
                assert blocked.value.orig.sqlstate == "55P03"
            finally:
                release.set()
            response = future.result(timeout=10)
            assert response.status_code == 200, response.text
    finally:
        event.remove(Receipt, "before_insert", paused)
    identity = UUID(response.json()["subject_id"])
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(Claim, identity) is not None
    with Session(setup.admin) as s, s.begin():
        s.execute(
            delete(ObjectAudience).where(
                ObjectAudience.subject_id == UUID(artifact),
                ObjectAudience.principal_id == setup.peer,
            )
        )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(Claim, identity) is None
