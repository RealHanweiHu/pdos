"""Real PostgreSQL ancestor ACL checks after replacing recursive reader policies."""

# ruff: noqa: F811 -- register the existing configuration fixture and its dependencies
from uuid import UUID

from builds.test_builds import (  # noqa: F401
    accepted,
    build_command,
    configuration,
    definition,
    project,
)
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from pdos_next.core.database import tenant_session
from pdos_next.core.models import ObjectAudience
from pdos_next.domain.builds.models import Build


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
        # G0 already shares its project, model and definition with the named
        # reviewer (the peer), and a project audience must equal its members (D33).
        # Withhold an ancestor the peer was never given: the engineering configuration.
        existing = {
            (kind, subject)
            for kind, subject in s.execute(
                select(ObjectAudience.object_type, ObjectAudience.subject_id).where(
                    ObjectAudience.tenant_id == setup.tenant,
                    ObjectAudience.principal_id == setup.peer,
                )
            )
        }
        withheld = next(item for item in targets if item[0] == "engineering_configurations")
        assert withheld not in existing
    with Session(setup.admin) as s, s.begin():
        for kind, target in sorted(targets - existing - {withheld}):
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
                object_type=withheld[0],
                subject_id=withheld[1],
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
