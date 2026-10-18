"""Real knowledge Command publication, run only by the root guarded PG checkpoint.

The shared fixture requires explicit TEST_DATABASE_URL and verifies the isolated
pdos_test marker. Root supplies the current 64245 environment; this module never
opens another target or falls back to .env. All content is native synthetic text.
The final source withdrawal is an explicitly authorized fixture fault injection,
not acceptance of a native-artifact withdrawal business endpoint.
"""

# ruff: noqa: F811 -- explicitly imported pytest fixtures remain fixture names.

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_builds import (  # noqa: F401 -- pytest fixtures
    accepted,
    build_command,
    configuration,
    definition,
    project,
)

from pdos_next.database import tenant_session
from pdos_next.domain.builds.models import Build
from pdos_next.domain.knowledge.models import (
    CANDIDATE_EVENT,
    CANDIDATE_OP,
    CANDIDATE_SUBJECT,
    RULE_EVENT,
    RULE_OP,
    RULE_SUBJECT,
    ApplicabilityAssessment,
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import Project
from pdos_next.models import (
    Artifact,
    Audit,
    Category,
    Confirmation,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    now,
)
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import digest

CONTENT = "Synthetic field experience: identify the actual configuration before reusing a result."
AUTHORITY = (
    "Synthetic independent knowledge publication duty and qualification; no production authority."
)
PURPOSE = "Apply one synthetic field lesson to this fixed engineering configuration"
KNOWLEDGE_MODELS = (
    KnowledgeCandidateVersion,
    KnowledgeCandidateCurrent,
    ApplicabilityAssessment,
    DesignRuleVersion,
    DesignRuleCurrent,
)
GROUP_MODELS = (Receipt, Audit, Outbox, RequestKey, Confirmation)


def scoped(work):
    setup = work.setup
    return tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    )


def snapshot(work, models=(*KNOWLEDGE_MODELS, *GROUP_MODELS)):
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: [
                digest(dict(row))
                for row in session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == work.setup.tenant)
                    .order_by(model.id)
                ).mappings()
            ]
            for model in models
        }


def command(work, operation, payload, *, category_only=False):
    setup = work.setup
    with Session(setup.admin) as session:
        scope = session.get(
            Category if category_only else Product,
            setup.category if category_only else setup.product,
        )
        revision = scope.revision
    return {
        "category_id": str(setup.category),
        "product_id": None if category_only else str(setup.product),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "expected_revision": revision,
        "source_read_set": [],
        "payload": deepcopy(payload),
    }


def send(work, value, *, preview=False):
    setup = work.setup
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands" + ("/preview" if preview else ""),
        headers=setup.headers,
        json=value,
    )


def endpoint(work, *, category_only=False):
    root = f"/v1/categories/{work.setup.category}"
    if not category_only:
        root += f"/products/{work.setup.product}"
    return root + "/experience"


def prepare(work, value, *, expected=200):
    before = snapshot(work)
    response = work.setup.client.post(
        endpoint(work, category_only=value["product_id"] is None) + "/inputs",
        headers=work.setup.headers,
        json=value,
    )
    assert response.status_code == expected, response.text
    assert snapshot(work) == before  # Material preparation is not a business write.
    if expected != 200:
        return response
    result = response.json()
    assert result["required_source_read_set"]
    assert "approval_token" not in result["payload"]
    prepared = deepcopy(value)
    prepared.update(payload=result["payload"], source_read_set=result["required_source_read_set"])
    return prepared


def register(work, title, content, *, category_only=False, visibility="private"):
    response = send(
        work,
        command(
            work,
            "evidence.artifact.register",
            {
                "title": title,
                "content": content,
                "source_label": "Controlled synthetic native text",
                "visibility": visibility,
            },
            category_only=category_only,
        ),
    )
    assert response.status_code == 200, response.text
    identity = response.json()["subject_id"]
    with scoped(work) as session:
        saved = session.get(Artifact, UUID(identity))
        assert saved is not None and saved.original_id is None and saved.status == "active"
    return {
        "kind": "artifact",
        "id": identity,
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(content.encode()).hexdigest(),
    }


@pytest.fixture
def knowledge_work(setup, configuration):
    work = SimpleNamespace(
        setup=setup, config=configuration, project_id=UUID(configuration["project"]), at=now()
    )
    work.source = register(
        work, "Synthetic experience original", CONTENT, category_only=True, visibility="category"
    )
    work.authority_source = register(work, "Synthetic explicit publication authority", AUTHORITY)
    assert work.source["id"] != work.authority_source["id"] != configuration["source"]
    previous_synthetic = getattr(setup.engine, "_pdos_professional_synthetic", False)
    work.issuer = professional.configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=work.project_id,
        key=f"synthetic-knowledge:{setup.tenant}",
        enabled=True,
    )
    yield work
    professional.disable_issuer(setup.engine, work.issuer.key)
    setup.engine._pdos_professional_synthetic = previous_synthetic


def authorize(work, *, role="knowledge"):
    operation = RULE_OP if role == "knowledge" else "release.engineering.approve"
    receipts = []
    for kind in ("duty", "qualification"):
        value = {
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "subject_id": str(work.setup.human),
            "external_id": f"synthetic-{role}-{kind}",
            "kind": kind,
            "role": role,
            "operations": [operation],
            "purposes": [PURPOSE],
            "state": "active",
            "valid_from": (work.at - timedelta(minutes=2)).isoformat(),
            "valid_until": (work.at + timedelta(hours=1)).isoformat(),
            "approval": {
                "system": "Controlled synthetic knowledge authority",
                "external_id": str(uuid4()),
                "version": "synthetic-v1",
                "approved_by": "Explicit synthetic issuer",
                "issued_at": (work.at - timedelta(minutes=1)).isoformat(),
            },
            "sources": [
                {
                    "artifact_id": work.authority_source["id"],
                    "expected_revision": 1,
                    "line": 1,
                    "quote": AUTHORITY,
                }
            ],
            "reason": "Explicit independently registered synthetic publication responsibility",
        }
        with scoped(work) as session:
            receipts.append(
                import_professional_fact(
                    session,
                    work.setup.ctx,
                    work.issuer,
                    value,
                    request_key=str(uuid4()),
                    command_id=uuid4(),
                )
            )
    return receipts


def assessment(work, operation=RULE_OP):
    with scoped(work) as session:
        return professional.assess(
            session, work.setup.ctx, work.setup.product, work.project_id, operation, PURPOSE, now()
        )


def candidate_payload(work, **changes):
    return {
        "candidate": None,
        "project_id": None,
        "visibility": "private",
        "title": "Synthetic configuration-location experience",
        "lesson": "Reuse a result only after its actual configuration is established.",
        "evidence_summary": "One explicit synthetic source, with no asserted production sample.",
        "applicability_hypothesis": "Check separately against the selected engineering version.",
        "result_receipts": [],
        "sources": [deepcopy(work.source)],
        "reason": "Retain an experience hypothesis, without publishing a standard.",
        **changes,
    }


def rule_payload(work, candidate, **changes):
    return {
        "project_id": str(work.project_id),
        "candidate": deepcopy(candidate),
        "rule": None,
        "title": "Synthetic configuration-bound reuse rule",
        "rule_text": "For this configured purpose, establish configuration identity before reuse.",
        "applicability": {
            "target": {
                "kind": "engineering_configuration",
                "id": work.config["engineering"]["subject_id"],
                "revision": 1,
            },
            "purpose": PURPOSE,
            "differences": [],
            "adopted_rule": "Explicit named evidence review",
            "conditions": ["Only the selected configuration and stated internal purpose"],
            "decision": "applicable",
            "rationale": "The actual target and source were explicitly reviewed.",
            "valid_from": (work.at - timedelta(minutes=1)).isoformat(),
            "valid_until": None,
        },
        "sources": [deepcopy(work.source)],
        "reason": "Named publication of one explicitly assessed synthetic lesson.",
        **changes,
    }


def exact_group(work, value, receipt, *, rule=False, category_only=True):
    model = DesignRuleVersion if rule else KnowledgeCandidateVersion
    current_model = DesignRuleCurrent if rule else KnowledgeCandidateCurrent
    identity = "rule_id" if rule else "candidate_id"
    event = RULE_EVENT if rule else CANDIDATE_EVENT
    with scoped(work) as session:
        saved = session.get(model, UUID(receipt["subject_id"]))
        original = session.get(Receipt, UUID(receipt["id"]))
        assert saved is not None and original is not None
        assert saved.receipt_id == original.id and saved.command_id == original.command_id
        assert saved.command_id == UUID(value["command_id"])
        assert saved.actor_id == saved.requester_id == saved.writer_id == work.setup.human
        assert digest(saved.body) == saved.body_sha256
        assert (
            saved.command["original_key_sha256"]
            == sha256(value["idempotency_key"].encode()).hexdigest()
        )
        assert not {"confirmation_token", "approval_token"} & set(
            saved.command["envelope"]["payload"]
        )
        pointer = session.scalar(
            select(current_model).where(
                getattr(current_model, identity) == getattr(saved, identity)
            )
        )
        assert (pointer.version_id, pointer.revision) == (saved.id, saved.revision)
        assert receipt["subject_type"] == (RULE_SUBJECT if rule else CANDIDATE_SUBJECT)
        group = [saved, pointer, original]
        for group_model in (Audit, Outbox, RequestKey):
            rows = list(
                session.scalars(select(group_model).where(group_model.receipt_id == original.id))
            )
            assert len(rows) == 1 and rows[0].actor_id == work.setup.human
            group.append(rows[0])
            if group_model is Outbox:
                assert (rows[0].type, rows[0].subject_id, rows[0].subject_revision) == (
                    event,
                    saved.id,
                    saved.revision,
                )
                assert rows[0].correlation_id == original.command_id
        if rule:
            applied = session.get(ApplicabilityAssessment, saved.assessment_id)
            proof = session.get(Confirmation, saved.confirmation_id)
            assert applied.publication_id == saved.id and applied.receipt_id == original.id
            assert applied.actor_id == work.setup.human
            assert applied.body == saved.body["applicability"]
            assert digest(applied.body) == applied.body_sha256
            assert proof.consumed is True and proof.actor_id == work.setup.human
            assert (proof.subject_type, proof.subject_id) == ("product", work.setup.product)
            assert proof.snapshot == saved.command["review"]
            assert saved.nature == "synthetic" and saved.source_basis["professional"]["roles"] == [
                "knowledge"
            ]
            assert work.authority_source["id"] not in {
                source["id"] for source in saved.source_basis["artifacts"]
            }
            group.extend((applied, proof))
        else:
            if category_only:
                assert saved.product_id is None and saved.project_id is None
            else:
                assert (
                    saved.product_id == work.setup.product and saved.project_id == work.project_id
                )
            assert saved.confirmation_id is original.confirmation_id is None
        xids = {
            session.scalar(
                text(f'SELECT xmin::text FROM public."{row.__tablename__}" WHERE id=:id'),
                {"id": row.id},
            )
            for row in group
        }
        assert len(xids) == 1 and None not in xids
        return deepcopy(saved.body), str(getattr(saved, identity))


def workspace(work, *, category_only=False):
    before = snapshot(work)
    response = work.setup.client.get(
        endpoint(work, category_only=category_only), headers=work.setup.headers
    )
    assert response.status_code == 200, response.text
    assert snapshot(work) == before
    return response.json()


def test_category_experience_to_explicit_named_rule_and_retained_source_recheck(knowledge_work):
    work = knowledge_work
    with Session(work.setup.admin) as session:
        projects_before = session.scalar(
            select(func.count()).select_from(Project).where(Project.tenant_id == work.setup.tenant)
        )
    created = prepare(
        work, command(work, CANDIDATE_OP, candidate_payload(work), category_only=True)
    )
    response = send(work, created)
    assert response.status_code == 200, response.text
    candidate_receipt = response.json()
    candidate_body, candidate_id = exact_group(work, created, candidate_receipt)
    candidate_ref = {"id": candidate_id, "revision": 1}
    with Session(work.setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.tenant_id == work.setup.tenant)
            )
            == projects_before
        )
    assert workspace(work, category_only=True)["candidates"][0]["id"] == candidate_id

    # A real category writer/project owner with another actual professional pair
    # has no knowledge publication responsibility until its own facts are imported.
    authorize(work, role="engineering")
    assert assessment(work, "release.engineering.approve")["authorized"] is True
    assert assessment(work)["authorized"] is False
    denied = prepare(work, command(work, RULE_OP, rule_payload(work, candidate_ref)), expected=403)
    assert denied.json()["code"] == "FORBIDDEN_SCOPE"
    authorize(work)
    actual_authority = assessment(work)
    assert actual_authority["authorized"] and actual_authority["qualified"]
    assert actual_authority["roles"] == ["knowledge"] and actual_authority["synthetic"]
    with scoped(work) as session:
        assert {
            row.kind
            for row in session.scalars(
                select(ProfessionalFact).where(ProfessionalFact.role == "knowledge")
            )
        } == {"duty", "qualification"}

    unknown = rule_payload(work, candidate_ref)
    unknown["applicability"]["decision"] = "unknown"
    refused = prepare(work, command(work, RULE_OP, unknown), expected=422)
    assert refused.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    publication = prepare(work, command(work, RULE_OP, rule_payload(work, candidate_ref)))
    preview = send(work, publication, preview=True)
    assert preview.status_code == 200, preview.text
    signed = preview.json()["command"]
    assert signed["payload"]["approval_token"]
    published = send(work, signed)
    assert published.status_code == 200, published.text
    receipt = published.json()
    rule_body, rule_id = exact_group(work, signed, receipt, rule=True)
    before_replay = snapshot(work)
    replay = send(work, signed)
    assert replay.status_code == 200 and replay.json() == receipt, replay.text
    assert snapshot(work) == before_replay

    # An owner's later candidate revision does not rewrite the fixed publication.
    revised = prepare(
        work,
        command(
            work,
            CANDIDATE_OP,
            candidate_payload(
                work,
                candidate=candidate_ref,
                lesson="A later hypothesis, retained independently from the signed rule.",
            ),
            category_only=True,
        ),
    )
    changed = send(work, revised)
    assert changed.status_code == 200, changed.text
    exact_group(work, revised, changed.json())
    with scoped(work) as session:
        old_candidate = session.get(
            KnowledgeCandidateVersion, UUID(candidate_receipt["subject_id"])
        )
        old_rule = session.get(DesignRuleVersion, UUID(receipt["subject_id"]))
        assert old_candidate.body == candidate_body and old_rule.body == rule_body
        assert old_rule.candidate_revision == 1
        assert session.scalar(select(func.count()).select_from(DesignRuleVersion)) == 1
    current_rule = next(row for row in workspace(work)["rules"] if row["id"] == rule_id)
    assert current_rule["usability"]["state"] == "current"
    assert current_rule["candidate"] == candidate_ref
    for model, identity in (
        (KnowledgeCandidateVersion, UUID(candidate_receipt["subject_id"])),
        (DesignRuleVersion, UUID(receipt["subject_id"])),
    ):
        with pytest.raises(DBAPIError) as failure, scoped(work) as session:
            session.execute(
                update(model).where(model.id == identity).values(body={"overwritten": True})
            )
        assert getattr(failure.value.orig, "sqlstate", None) in {"42501", "23514"}

    retained = snapshot(work)
    # Explicit fault injection: withdraw only this native experience original,
    # leaving configuration and the independent publication-authority source active.
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.tenant_id == work.setup.tenant, Artifact.id == UUID(work.source["id"]))
            .values(status="withdrawn")
        )
    assert snapshot(work) == retained
    assert assessment(work)["authorized"] is True
    stale_rule = next(row for row in workspace(work)["rules"] if row["id"] == rule_id)
    assert stale_rule["rule_text"] == rule_body["rule_text"]
    assert stale_rule["usability"]["state"] == "needs_recheck"
    assert stale_rule["usability"]["reason_codes"]
    fresh_source = register(
        work,
        "Synthetic later publication material",
        "Synthetic fresh material does not repair the withdrawn original experience source.",
        category_only=True,
        visibility="category",
    )
    next_use = rule_payload(
        work,
        {"id": candidate_id, "revision": 2},
        rule={"id": rule_id, "revision": 1},
        sources=[fresh_source],
    )
    before_refusal = snapshot(work)
    rejected = work.setup.client.post(
        endpoint(work) + "/inputs",
        headers=work.setup.headers,
        json=command(work, RULE_OP, next_use),
    )
    assert rejected.status_code in {403, 409}, rejected.text
    assert rejected.json()["code"] in {"SOURCE_STALE", "SOURCE_UNAVAILABLE"}
    assert snapshot(work) == before_refusal


def test_actual_planned_build_result_becomes_scoped_candidate_and_named_rule(knowledge_work):
    """A planned Build is a real preparation result, never a passed physical test."""
    work = knowledge_work
    planned, _ = accepted(work.setup, build_command(work.setup, work.config))
    assert planned["operation"] == "build.create" and planned["subject_type"] == "build"
    with scoped(work) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        actual_build = session.get(Build, UUID(planned["subject_id"]))
        native_receipt = session.get(Receipt, UUID(planned["id"]))
        assert actual_build is not None and native_receipt is not None
        assert actual_build.status == "planned" and actual_build.project_id == work.project_id
        assert actual_build.engineering_configuration_id == UUID(
            work.config["engineering"]["subject_id"]
        )
        assert actual_build.manufacturing_configuration_id == UUID(
            work.config["process"]["subject_id"]
        )
        # Independent expected material for the existing finite builds/v1 contract.
        # Qualification, readiness and measured outcomes are deliberately absent.
        actual_material = {
            field: getattr(actual_build, field)
            for field in (
                "name",
                "type",
                "purpose",
                "project_revision",
                "engineering_configuration_id",
                "manufacturing_configuration_id",
                "previous_build_id",
                "planned_quantity",
                "unit",
                "planned_start",
                "planned_end",
                "verification_objectives",
                "disposition_plan",
            )
        }
        wanted = {
            "receipt_id": str(native_receipt.id),
            "operation": "build.create",
            "subject_type": "build",
            "subject_id": str(actual_build.id),
            "subject_revision": actual_build.revision,
            "receipt_request_digest": native_receipt.request_digest,
            "receipt_result_sha256": digest(native_receipt.result),
            "receipt_visibility": native_receipt.visibility,
            "table": "builds",
            "row_id": str(actual_build.id),
            "revision": actual_build.revision,
            "tenant_id": str(work.setup.tenant),
            "category_id": str(work.setup.category),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "owner_id": str(actual_build.owner_id),
            "visibility": actual_build.visibility,
            "material_contract": "builds.fixed_fields/v1",
            "body_sha256": digest(actual_material),
            "direct_content_refs": [],
            "artifacts": [],
        }
    selected_receipt = {"receipt_id": planned["id"]}
    body = candidate_payload(
        work,
        project_id=str(work.project_id),
        title="Synthetic lesson from an actual planned Build",
        evidence_summary=(
            "The native planned-Build receipt fixes configuration selection; no started work, "
            "measurement, performance result or production qualification is asserted."
        ),
        result_receipts=[selected_receipt],
    )
    candidate_command = prepare(work, command(work, CANDIDATE_OP, body))
    saved = send(work, candidate_command)
    assert saved.status_code == 200, saved.text
    candidate_receipt = saved.json()
    _, candidate_id = exact_group(work, candidate_command, candidate_receipt, category_only=False)
    visible = next(row for row in workspace(work)["candidates"] if row["id"] == candidate_id)
    assert visible["project_id"] == str(work.project_id) and visible["visibility"] == "private"
    assert visible["result_receipts"] == [selected_receipt]
    with scoped(work) as session:
        current_candidate = session.get(
            KnowledgeCandidateVersion, UUID(candidate_receipt["subject_id"])
        )
        assert current_candidate is not None
        assert current_candidate.source_basis["result_receipts"] == [wanted]
        # A native Build's fixed planning fields carry no domain SourceRef leaf.
        # Its aggregate sources or signer material must not become knowledge content.
        assert {ref["id"] for ref in current_candidate.source_basis["artifacts"]} == {
            work.source["id"]
        }
        assert "professional" not in current_candidate.source_basis

    authorize(work)
    publication_body = rule_payload(work, {"id": candidate_id, "revision": 1})
    publication_body["applicability"]["rationale"] = (
        "The actual planned Build and exact configuration were reviewed for this internal "
        "preparation rule; it establishes no experimental result."
    )
    publication = prepare(work, command(work, RULE_OP, publication_body))
    preview = send(work, publication, preview=True)
    assert preview.status_code == 200, preview.text
    signed = preview.json()["command"]
    published = send(work, signed)
    assert published.status_code == 200, published.text
    rule_receipt = published.json()
    _, rule_id = exact_group(work, signed, rule_receipt, rule=True)
    with scoped(work) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        candidate = session.get(KnowledgeCandidateVersion, UUID(candidate_receipt["subject_id"]))
        rule = session.get(DesignRuleVersion, UUID(rule_receipt["subject_id"]))
        assert candidate is not None and rule is not None
        assert (
            rule.source_basis["result_receipts"]
            == candidate.source_basis["result_receipts"]
            == [wanted]
        )
        assert rule.visibility == "private" and rule.project_id == work.project_id
        content_ids = {ref["id"] for ref in rule.source_basis["artifacts"]}
        assert {work.source["id"], work.config["source"]} <= content_ids
        assert work.authority_source["id"] not in content_ids
        assert session.get(Build, UUID(planned["subject_id"])).status == "planned"
    visible_rule = next(row for row in workspace(work)["rules"] if row["id"] == rule_id)
    assert visible_rule["usability"]["state"] == "current"
    assert visible_rule["candidate"] == {"id": candidate_id, "revision": 1}
    assert visible_rule["nature"] == "synthetic"
