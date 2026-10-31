"""Real private target and a revocable recipient ACL for the four negative cases.

Native T1 commands create every configuration/Build and source. Only the explicit
synthetic recipient ACL is seeded/revoked through the fixture's guarded admin
engine; no business row's owner, audience, content or status is rewritten.
"""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy.orm import Session
from test_builds import build_command
from test_project_first_plan import accepted, cmd, post
from verification_handoff.fixtures import artifact, caller

from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build
from pdos_next.domain.builds.schemas import BuildCreatePayload
from pdos_next.domain.builds.service import _linked
from pdos_next.domain.configurations.service import get_engineering, get_process
from pdos_next.models import Artifact, ObjectAudience
from pdos_next.service import digest
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.verification_action_harness import bound_target


def session_for(person):
    return tenant_session(
        person.engine, person.tenant, actor_id=person.human,
        requester_id=person.human, category_id=person.category, read_snapshot=True,
    )


@pytest.fixture
def private_action_work(ready_work):
    """Keep the real project owner and issuer; create a new private Build normally."""
    base, setup = ready_work, ready_work.setup
    with session_for(setup) as session:
        _, engineering = get_engineering(
            session, setup.ctx, setup.product, UUID(base.config["engineering"]["subject_id"]),
        )
        _, process = get_process(
            session, setup.ctx, setup.product, UUID(base.config["process"]["subject_id"]),
        )
        source = session.get(Artifact, UUID(base.config["source"]))
        assert source is not None and source.status == "active"
        reference = {
            "artifact_id": str(source.id), "expected_revision": source.revision,
            "line": 1, "quote": source.content.splitlines()[0],
        }
    common = {
        "visibility": "private", "reason": "Synthetic private verification target only",
        "sources": [reference],
    }
    value = cmd(setup, "engineering.configuration.create", {
        **common, "name": "Private verification engineering " + str(uuid4()),
        "definition_id": engineering["definition_id"],
        "expected_definition_revision": engineering["definition_revision"],
        "bom_id": engineering["bom_id"], "expected_bom_revision": engineering["bom_revision"],
    })
    value["source_read_set"] = engineering["required_source_read_set"]
    fixed_engineering, _ = accepted(setup, value)
    value = cmd(setup, "npi.process.revise", {
        **common, "name": "Private verification manufacturing " + str(uuid4()),
        "engineering_configuration_id": fixed_engineering["subject_id"],
        "expected_engineering_revision": fixed_engineering["subject_revision"],
        "site": process["site"], "line": process["line"],
        "operations": deepcopy(process["operations"]),
    })
    with session_for(setup) as session:
        _, fixed = get_engineering(
            session, setup.ctx, setup.product, UUID(fixed_engineering["subject_id"]),
        )
        assert fixed["visibility"] == "private"
        value["source_read_set"] = fixed["required_source_read_set"]
    fixed_process, _ = accepted(setup, value)
    config = {**base.config, "engineering": fixed_engineering, "process": fixed_process}
    value = build_command(setup, config, name="Private verification Build " + str(uuid4()))
    with session_for(setup) as session:
        _, _, _, reads = _linked(
            session, setup.ctx, setup.product,
            BuildCreatePayload.model_validate(value["payload"]), new_consumption=True,
        )
        value["source_read_set"] = reads
    build, _ = accepted(setup, value)
    # The existing actual issuer is already bound to this same product/project.
    # These are Human professional facts, never AI/T0 admission or qualifications.
    for kind in ("duty", "qualification"):
        import_authority(
            base, "quality", kind, subject_id=str(setup.human),
            operations=["verification.request.create"],
            external_id=f"synthetic-private-action-{kind}-{uuid4()}",
        )
    work = SimpleNamespace(**{**vars(base), "config": config, "build_id": build["subject_id"],
                              "quality": setup})
    with session_for(setup) as session:
        row = session.get(Build, UUID(work.build_id))
        assert row is not None and row.visibility == "private" and row.owner_id == setup.human
    return work


def restricted_materials(work):
    person, selection = bound_target(work)
    owner = caller(work.setup, work.setup.peer, work.setup.tokens[work.setup.peer])
    content = "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER"
    response = post(owner, cmd(owner, "evidence.artifact.register", {
        "title": "Private auxiliary discussion", "source_label": "Synthetic recipient ACL only",
        "visibility": "private", "content": content,
    }))
    assert response.status_code == 200, response.text
    basis = {"artifact_id": response.json()["subject_id"], "expected_revision": 1,
             "line": 1, "quote": content}
    with Session(person.admin) as session, session.begin():
        source = session.get(Artifact, UUID(basis["artifact_id"]))
        assert source.visibility == "private" and source.owner_id == owner.human != person.human
        audience = ObjectAudience(
            tenant_id=person.tenant, category_id=person.category, object_type="artifact_versions",
            subject_id=source.id, owner_id=owner.human, principal_id=person.human,
        )
        session.add(audience)
        session.flush()
        audience_id = audience.id
    index(person, UUID(basis["artifact_id"]))
    execution = artifact(person, "Synthetic drawing\nVERIFICATION_EXECUTION_RAW_ONLY",
                         "Synthetic current execution definition")
    assert basis["artifact_id"] != execution["artifact_id"]
    result = SimpleNamespace(person=person, selection=selection, basis=basis,
                             execution=execution, audience_id=audience_id, source_owner=owner)
    assert_source_access(result)
    return result


def assert_source_access(case, *, auxiliary_revoked=False, execution_revision=1):
    """Actual ordinary Human RLS, in a fresh transaction after every boundary."""
    person = case.person
    with session_for(person) as session:
        basis = session.get(Artifact, UUID(case.basis["artifact_id"]))
        execution = session.get(Artifact, UUID(case.execution["artifact_id"]))
        build = session.get(Build, UUID(case.selection["id"]))
        assert (basis is None) is auxiliary_revoked
        if basis is not None:
            assert basis.visibility == "private"
            assert basis.revision == 1 and basis.status == "active"
        assert execution is not None and execution.revision == execution_revision
        assert execution.status == "active"
        assert build is not None and build.visibility == "private"
        assert build.owner_id == person.human
    with session_for(case.source_owner) as session:
        basis = session.get(Artifact, UUID(case.basis["artifact_id"]))
        assert basis is not None and basis.visibility == "private"
        assert basis.revision == 1 and basis.status == "active"


def artifact_identity(row):
    return (row.tenant_id, row.category_id, row.product_id, row.owner_id, row.visibility,
            row.revision, row.status, digest(row.content))


def revoke_auxiliary(case):
    """Revoke the one real recipient, preserving the immutable registered source."""
    person = case.person
    with Session(person.admin) as session, session.begin():
        source = session.get(Artifact, UUID(case.basis["artifact_id"]))
        before = artifact_identity(source)
        row = session.get(ObjectAudience, case.audience_id)
        assert (row.tenant_id, row.category_id, row.object_type, row.subject_id,
                row.owner_id, row.principal_id) == (
                    person.tenant, person.category, "artifact_versions", source.id,
                    case.source_owner.human, person.human,
                )
        session.delete(row)
        session.flush()
        session.refresh(source)
        assert artifact_identity(source) == before
    assert_source_access(case, auxiliary_revoked=True)


def change_execution_revision(case):
    with Session(case.person.admin) as session, session.begin():
        source = session.get(Artifact, UUID(case.execution["artifact_id"]))
        assert source.revision == 1
        source.revision += 1  # Existing guard permits a synthetic stale-current revision.
    assert_source_access(case, execution_revision=2)
