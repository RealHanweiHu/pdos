"""Real PostgreSQL ancestor ACL checks after replacing recursive reader policies."""

# ruff: noqa: F811 -- register the existing configuration fixture and its dependencies
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from test_builds import accepted, build_command, configuration, definition, project  # noqa: F401

from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build
from pdos_next.models import ObjectAudience


def test_summary_cannot_expand_ancestor_audience_and_source_revoke_hides_build(
    setup, configuration
):
    receipt, _ = accepted(setup, build_command(setup, configuration))
    identity = UUID(receipt["subject_id"])
    with Session(setup.admin) as s:
        dependencies = s.scalar(
            text("SELECT audience_dependencies FROM builds WHERE id=:id"), {"id": identity}
        )
        assert any(ref["type"] == "definition_revisions" for ref in dependencies)
        assert all(set(ref) == {"type", "id", "product_id"} for ref in dependencies)
        # The summary contains identity/scope only, never an old ACL decision.
        targets = [(ref["type"], UUID(ref["id"])) for ref in dependencies]
        targets.extend([("builds", identity), ("artifact_versions", UUID(configuration["source"]))])
        targets = set(targets)
    with Session(setup.admin) as s, s.begin():
        for kind, target in sorted(targets):
            if kind == "definition_revisions":
                continue
            s.add(
                ObjectAudience(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    object_type=kind,
                    subject_id=target,
                    owner_id=setup.human,
                    principal_id=setup.peer,
                )
            )

    def visible():
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.peer,
            requester_id=setup.peer,
            category_id=setup.category,
            read_snapshot=True,
        ) as s:
            return s.get(Build, identity) is not None

    assert not visible()
    with Session(setup.admin) as s, s.begin():
        s.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type="definition_revisions",
                subject_id=UUID(configuration["definition"]),
                owner_id=setup.human,
                principal_id=setup.peer,
            )
        )
    assert visible()
    with Session(setup.admin) as s, s.begin():
        s.execute(
            delete(ObjectAudience).where(
                ObjectAudience.subject_id == UUID(configuration["source"]),
                ObjectAudience.principal_id == setup.peer,
            )
        )
    assert not visible()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as s:
        assert s.scalar(select(Build).where(Build.id == identity)) is not None
