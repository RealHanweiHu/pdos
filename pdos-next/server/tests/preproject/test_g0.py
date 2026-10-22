from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import category_transaction, tenant_session
from pdos_next.domain.preproject.models import Proposal, ProposalDecision, ProposalItemVersion
from pdos_next.domain.preproject.schemas import ProposalCreate, SpecItem
from pdos_next.models import Artifact, Confirmation, Grant, Principal, Product, Receipt, now
from pdos_next.service import Context, execute


def request(work, operation, payload, revision=1):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(work.category),
        "product_id": None,
        "expected_revision": revision,
        "source_read_set": [],
        "operation": operation,
        "payload": payload,
    }


def payload(work):
    return {
        "title": "轻便充气泵",
        "entry_kind": "new_product",
        "brief": "合成新品评审",
        "groups": {
            "items": [
                {"kind": "section", "content": {"key": "worth_it", "text": "解决便携充气需求"}},
                {"kind": "option", "content": {"name": "开发便携款", "kind": "new"}},
                {"kind": "option", "content": {"name": "保持现状", "kind": "do_nothing"}},
                {
                    "kind": "spec",
                    "content": {
                        "key": "noise",
                        "parameter": "噪声",
                        "value_type": "number",
                        "unit": None,
                        "availability": "unknown",
                        "item_status": "unknown",
                    },
                },
                {
                    "kind": "spec",
                    "content": {
                        "key": "display",
                        "parameter": "压力显示",
                        "value_type": "boolean",
                        "text_value": "true",
                        "availability": "known",
                        "item_status": "confirmed",
                    },
                    "source_refs": [
                        {
                            "type": "human",
                            "id": str(work.human),
                            "version": 1,
                            "statement": "具名产品决定",
                        }
                    ],
                },
            ],
            "questions": [
                {
                    "question": "噪声条件待确定",
                    "owner_id": str(work.human),
                    "due_date": "2026-10-20",
                }
            ],
        },
    }


def post(work, req, *, actor=None, preview=False):
    route = f"/v1/categories/{work.category}/commands" + ("/preview" if preview else "")
    return work.client.post(
        route, json=req, headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"}
    )


def save(work, req, *, actor=None):
    checked = post(work, req, actor=actor, preview=True)
    assert checked.status_code == 200, checked.text
    response = post(work, checked.json()["command"], actor=actor)
    assert response.status_code == 200, response.text
    return response.json(), checked.json()["command"]


def read(work, proposal_id, actor=None):
    return work.client.get(
        f"/v1/categories/{work.category}/proposals/{proposal_id}",
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


@pytest.fixture
def work(setup):
    with Session(setup.admin) as s, s.begin():
        reviewer = s.scalar(
            select(Grant).where(
                Grant.principal_id == setup.peer, Grant.category_id == setup.category
            )
        )
        reviewer.product_manager, reviewer.can_write = True, False
        expert = Principal(id=uuid4(), tenant_id=setup.tenant, name="合成工程专家", kind="human")
        s.add(expert)
        s.flush()
        s.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=setup.category,
                principal_id=expert.id,
                can_write=False,
                expires_at=now() + timedelta(hours=1),
            )
        )
        setup.expert = expert.id
    return setup


def create(work, data=None):
    result, req = save(work, request(work, "proposal.create", data or payload(work)))
    return result["subject_id"], req


def submit(work, proposal_id):
    row = read(work, proposal_id).json()
    result, req = save(
        work,
        request(
            work,
            "proposal.g0.submit",
            {
                "proposal_id": proposal_id,
                "expected_revision": row["revision"],
                "reviewer_id": str(work.peer),
            },
            revision=row["revision"],
        ),
    )
    return result, req


def decide_request(work, proposal_id, outcome="approved"):
    row = read(work, proposal_id, work.peer).json()
    dispositions = [
        {
            "subject_type": i["subject_type"],
            "subject_id": i["subject_id"],
            "kind": "task" if i["subject_type"] == "question" else "risk",
            "owner_id": str(work.expert),
            "due_date": "2026-10-25",
            "note": i["title"],
        }
        for i in row["maturity"]["required_dispositions"]
    ]
    return request(
        work,
        "proposal.g0.decide",
        {
            "proposal_id": proposal_id,
            "submission_id": row["submission"]["id"],
            "expected_revision": row["revision"],
            "outcome": outcome,
            "rationale": "合成独立评审决定",
            "selected_option_item_id": next(
                i["item_id"] for i in row["items"] if i["kind"] == "option"
            ),
            "dispositions": dispositions if outcome == "approved" else [],
            "project": {"name": "合成研发项目", "owner_id": str(work.expert)},
        },
        revision=row["revision"],
    )


def test_private_proposal_and_read_only_reviewer_atomic_g0(work):
    proposal_id, create_req = create(work)
    assert read(work, proposal_id, work.peer).status_code == 404
    with Session(work.admin) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(Product).where(Product.tenant_id == work.tenant)
            )
            == 1
        )
    assert post(work, create_req).json()["subject_id"] == proposal_id
    submit(work, proposal_id)
    fixed = read(work, proposal_id, work.peer).json()
    assert fixed["status"] == "in_review"
    assert fixed["submission"]["frozen_document"]["items"][3]["content"]["unit"] is None
    reviewed = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["project_owner_audience_added"] is True
    assert all(i["audience_added"] for i in reviewed.json()["review"]["dispositions"])
    approved = post(work, reviewed.json()["command"], actor=work.peer)
    assert approved.status_code == 200, approved.text
    result = approved.json()["result"]
    replay = post(work, reviewed.json()["command"], actor=work.peer)
    assert replay.json()["id"] == approved.json()["id"]
    with tenant_session(
        work.engine, work.tenant, actor_id=work.expert, category_id=work.category
    ) as s:
        product = s.get(Product, UUID(result["product_id"]))
        assert product and product.owner_id == work.human
        definition = s.execute(
            text(
                "SELECT sealed,revision,source_proposal_id FROM definition_revisions WHERE id=:id"
            ),
            {"id": UUID(result["definition_id"])},
        ).one()
        assert definition.sealed and definition.revision == 1
        assert str(definition.source_proposal_id) == proposal_id
        specs = s.execute(
            text(
                "SELECT key,item_status,unit,origin FROM definition_specs "
                "WHERE definition_id=:id ORDER BY key"
            ),
            {"id": UUID(result["definition_id"])},
        ).all()
        assert specs == [
            ("display", "confirmed", None, "human"),
            ("noise", "unknown", None, "human"),
        ]
        states = s.execute(
            text("SELECT kind,status FROM project_open_items WHERE project_id=:id ORDER BY kind"),
            {"id": UUID(result["project_id"])},
        ).all()
        assert states == [("risk", "open"), ("task", "assigned")]
    with Session(work.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(ProposalDecision)
                .where(ProposalDecision.proposal_id == UUID(proposal_id))
            )
            == 1
        )
        assert (
            s.scalar(
                text("SELECT count(*) FROM outbox_events WHERE receipt_id=:id"),
                {"id": UUID(approved.json()["id"])},
            )
            == 2
        )
    assert read(work, proposal_id).json()["items"][-1]["content"]["status"] == "carried"


@pytest.mark.parametrize("failure", ["self", "no_capability", "no_options", "no_narrative"])
def test_submit_guards(work, failure):
    data = payload(work)
    if failure == "no_options":
        data["groups"]["items"] = [i for i in data["groups"]["items"] if i["kind"] != "option"]
    if failure == "no_narrative":
        data["groups"]["items"] = [i for i in data["groups"]["items"] if i["kind"] != "section"]
    proposal_id, _ = create(work, data)
    if failure == "self":
        from pdos_next.agent_kernel.models import TenantPilotAdmission

        with Session(work.admin) as s, s.begin():
            s.get(TenantPilotAdmission, work.tenant).active = False
    if failure == "no_capability":
        with Session(work.admin) as s, s.begin():
            s.scalar(select(Grant).where(Grant.principal_id == work.peer)).product_manager = False
    req = request(
        work,
        "proposal.g0.submit",
        {
            "proposal_id": proposal_id,
            "expected_revision": 1,
            "reviewer_id": str(work.human if failure == "self" else work.peer),
        },
    )
    response = post(work, req, preview=True)
    assert response.status_code in {403, 409}, response.text
    assert read(work, proposal_id).json()["status"] == "draft"


def test_unknown_disposition_required_and_owner_cannot_decide(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    req = decide_request(work, proposal_id)
    assert post(work, req, preview=True).json()["detail"]["reason"] == "reviewer_only"
    req["payload"]["dispositions"] = []
    response = post(work, req, actor=work.peer, preview=True)
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "unknown_without_disposition"
    )


def test_item_level_versions_and_locked_document(work):
    proposal_id, _ = create(work)
    row = read(work, proposal_id).json()
    a, b = row["items"][:2]
    for item in (a, b):
        content = deepcopy(item["content"])
        content["text" if item["kind"] == "section" else "name"] = "人工修订"
        req = request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": proposal_id,
                "ops": [
                    {
                        "kind": item["kind"],
                        "item_id": item["item_id"],
                        "base_version": item["version"],
                        "content": content,
                    }
                ],
            },
        )
        response = post(work, req)
        assert response.status_code == 200, response.text
    assert read(work, proposal_id).json()["revision"] == 3
    assert (
        post(
            work,
            {
                **req,
                "idempotency_key": str(uuid4()),
                "command_id": str(uuid4()),
                "payload": {
                    **req["payload"],
                    "ops": [
                        {**req["payload"]["ops"][0], "content": {"name": "新改动", "kind": "new"}}
                    ],
                },
            },
        ).status_code
        == 409
    )
    submit(work, proposal_id)
    response = post(
        work,
        request(
            work,
            "proposal.item.patch",
            {
                "proposal_id": proposal_id,
                "ops": [{"kind": "section", "content": {"key": "summary", "text": "在审修改"}}],
            },
        ),
    )
    assert response.json()["detail"]["reason"] == "proposal_locked"


def test_return_edit_and_new_submission(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    old_sub = read(work, proposal_id, work.peer).json()["submission"]["id"]
    save(work, decide_request(work, proposal_id, "returned"), actor=work.peer)
    assert read(work, proposal_id).json()["status"] == "returned"
    submit(work, proposal_id)
    assert read(work, proposal_id, work.peer).json()["submission"]["id"] != old_sub


def test_private_direct_rls_and_no_agent_dml(work):
    proposal_id, _ = create(work)
    with tenant_session(
        work.engine, work.tenant, actor_id=work.peer, category_id=work.category
    ) as s:
        assert s.get(Proposal, UUID(proposal_id)) is None
        assert list(s.scalars(select(ProposalItemVersion))) == []
    with Session(work.admin) as s:
        assert not s.scalar(text("SELECT has_table_privilege('pdos_agent','proposals','INSERT')"))
        assert not s.scalar(
            text("SELECT has_table_privilege('pdos_agent','proposal_decisions','INSERT')")
        )


def test_fault_rolls_back_decision_results_receipt_and_confirmation(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    prepared = post(work, decide_request(work, proposal_id), actor=work.peer, preview=True).json()[
        "command"
    ]
    with Session(work.admin) as s, s.begin():
        s.execute(
            text(
                "CREATE FUNCTION m3_test_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "IF NEW.tenant_id='"
                + str(work.tenant)
                + "'::uuid THEN RAISE EXCEPTION 'synthetic rollback'; END IF; RETURN NEW; END $$"
            )
        )
        s.execute(
            text(
                "CREATE TRIGGER m3_test_failure BEFORE INSERT ON project_open_items "
                "FOR EACH ROW EXECUTE FUNCTION m3_test_failure()"
            )
        )
    try:
        ctx = Context(work.tenant, work.peer, work.peer, category_id=work.category)
        with pytest.raises(DBAPIError):
            category_transaction(
                work.engine, ctx, lambda s: execute(s, ctx, Command.model_validate(prepared))
            )
        with Session(work.admin) as s:
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(ProposalDecision)
                    .where(ProposalDecision.proposal_id == UUID(proposal_id))
                )
                == 0
            )
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.tenant_id == work.tenant)
                )
                == 1
            )
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(Receipt)
                    .where(
                        Receipt.tenant_id == work.tenant, Receipt.operation == "proposal.g0.decide"
                    )
                )
                == 0
            )
            assert (
                s.scalar(
                    select(Confirmation.consumed).where(
                        Confirmation.tenant_id == work.tenant,
                        Confirmation.operation == "proposal.g0.decide",
                    )
                )
                is False
            )
    finally:
        with Session(work.admin) as s, s.begin():
            s.execute(text("DROP TRIGGER m3_test_failure ON project_open_items"))
            s.execute(text("DROP FUNCTION m3_test_failure()"))


def test_sealed_definition_and_database_independence_constraints(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    definition_id = approved["result"]["definition_id"]
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError):
        s.execute(
            text("UPDATE definition_revisions SET purpose='overwrite' WHERE id=:id"),
            {"id": UUID(definition_id)},
        )
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError):
        s.execute(
            text("UPDATE definition_specs SET item_status='confirmed' WHERE definition_id=:id"),
            {"id": UUID(definition_id)},
        )


@pytest.mark.parametrize("field", ["visibility", "owner_id", "origin", "created_by_run_id"])
def test_policy_fields_rejected(field):
    with pytest.raises(ValidationError):
        ProposalCreate.model_validate(
            {"title": "合成", "entry_kind": "new_product", field: str(uuid4())}
        )


def test_unknown_spec_never_fills_zero_or_unit():
    spec = SpecItem(key="noise", parameter="噪声", value_type="number")
    assert spec.value is None and spec.unit is None and spec.condition_note is None
    with pytest.raises(ValidationError):
        SpecItem(key="noise", parameter="噪声", value_type="number", value=0)


def test_private_source_is_visible_to_reviewer_and_withdrawal_blocks_approval(work):
    source = post(
        work,
        request(
            work,
            "evidence.artifact.register",
            {
                "title": "合成客户输入",
                "source_label": "合成",
                "content": "要求便携\n噪声工况未知",
                "visibility": "private",
            },
        ),
    )
    assert source.status_code == 200, source.text
    artifact_id = source.json()["subject_id"]
    data = payload(work)
    data["entry_kind"] = "customer_request"
    data["source_refs"] = [
        {"type": "artifact", "id": artifact_id, "version": 1, "line": 1, "quote": "要求便携"}
    ]
    proposal_id, _ = create(work, data)
    assert read(work, proposal_id).json()["private_source_count"] == 1
    submit(work, proposal_id)
    req = decide_request(work, proposal_id)
    assert post(work, req, actor=work.peer, preview=True).status_code == 200
    with Session(work.admin) as s, s.begin():
        artifact = s.get(Artifact, UUID(artifact_id))
        artifact.status = "withdrawn"
        artifact.revision += 1
    response = post(work, req, actor=work.peer, preview=True)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "original_withdrawn"
    # Returning remains possible; the owner can remove the stale citation and resubmit.
    save(work, decide_request(work, proposal_id, "returned"), actor=work.peer)


def test_g0_keeps_native_definition_citations_immutable(work):
    source = post(
        work,
        request(
            work,
            "evidence.artifact.register",
            {
                "title": "合成客户原件",
                "source_label": "合成",
                "content": "需有压力显示",
                "visibility": "private",
            },
        ),
    )
    assert source.status_code == 200, source.text
    ref = {
        "type": "artifact",
        "id": source.json()["subject_id"],
        "version": 1,
        "line": 1,
        "quote": "压力显示",
    }
    data = payload(work)
    data["entry_kind"] = "customer_request"
    data["groups"]["items"][4]["source_refs"] = [ref]
    proposal_id, _ = create(work, data)
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    definition_id = UUID(approved["result"]["definition_id"])
    with Session(work.admin) as s:
        citation = (
            s.execute(
                text(
                    "SELECT id,artifact_id,source_revision,line,quote,spec_keys "
                    "FROM definition_sources WHERE definition_id=:id"
                ),
                {"id": definition_id},
            )
            .mappings()
            .one()
        )
        assert citation["artifact_id"] == UUID(ref["id"])
        assert citation["source_revision"] == 1 and citation["line"] == 1
        assert citation["quote"] == "压力显示" and citation["spec_keys"] == ["display"]
        citation_id = citation["id"]
        project = (
            s.execute(
                text("SELECT trigger_type,trigger_id FROM projects WHERE id=:id"),
                {"id": UUID(approved["result"]["project_id"])},
            )
            .mappings()
            .one()
        )
        assert project["trigger_type"] == "customer_request"
        assert project["trigger_id"] == UUID(proposal_id)
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError):
        s.execute(
            text("UPDATE definition_sources SET quote='altered' WHERE id=:id"), {"id": citation_id}
        )


def test_database_submission_check_and_receipt_atom(work):
    proposal_id, _ = create(work)
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError):
        s.execute(
            text(
                "INSERT INTO proposal_submissions(id,tenant_id,category_id,proposal_id,revision,"
                "owner_id,reviewer_id,frozen_document,document_digest,context_refs,"
                "option_count,created_at) "
                "VALUES(:id,:tenant,:category,:proposal,1,:owner,:owner,'{}','synthetic','[]',0,now())"
            ),
            {
                "id": uuid4(),
                "tenant": work.tenant,
                "category": work.category,
                "proposal": UUID(proposal_id),
                "owner": work.human,
            },
        )
    with Session(work.admin) as s:
        version = s.scalar(
            select(ProposalItemVersion).where(ProposalItemVersion.proposal_id == UUID(proposal_id))
        )
        version_id = version.id
    with Session(work.admin) as s, s.begin(), pytest.raises(DBAPIError):
        s.execute(
            text("UPDATE proposal_item_versions SET content='{}' WHERE id=:id"), {"id": version_id}
        )
    with Session(work.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(ProposalDecision)
                .where(ProposalDecision.proposal_id == UUID(proposal_id))
            )
            == 0
        )


def test_participant_selector_excludes_owner_without_manager_capability(work):
    proposal_id, _ = create(work)
    response = work.client.get(
        f"/v1/categories/{work.category}/proposals/{proposal_id}/participants", headers=work.headers
    )
    assert response.status_code == 200
    people = {p["id"]: p for p in response.json()["items"]}
    assert not people[str(work.human)]["reviewer_eligible"]
    assert people[str(work.peer)]["reviewer_eligible"]


def test_question_creation_and_reassignment_require_confirmation(work):
    proposal_id, _ = create(work)
    row = read(work, proposal_id).json()
    question = next(i for i in row["items"] if i["kind"] == "question")
    direct = request(
        work,
        "proposal.item.patch",
        {
            "proposal_id": proposal_id,
            "ops": [{"kind": "question", "content": question["content"]}],
        },
    )
    response = post(work, direct)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "question_confirmation_required"
    # Editing an assignment cannot borrow the T0 item edit path.
    changed = deepcopy(question["content"])
    changed["due_date"] = "2026-10-30"
    direct["payload"]["ops"] = [
        {
            "kind": "question",
            "item_id": question["item_id"],
            "base_version": question["version"],
            "content": changed,
        }
    ]
    response = post(work, direct)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == "question_assignment_requires_confirmation"
    replacement = request(
        work,
        "proposal.question.create",
        {
            "proposal_id": proposal_id,
            "expected_revision": row["revision"],
            "question": question["content"]["question"],
            "owner_id": str(work.human),
            "due_date": "2026-10-30",
            "supersedes_item_id": question["item_id"],
        },
        revision=row["revision"],
    )
    assert post(work, replacement).status_code == 409
    save(work, replacement)
    updated = read(work, proposal_id).json()
    active = [i for i in updated["items"] if i["kind"] == "question"]
    assert len(active) == 1
    assert active[0]["content"]["supersedes_item_id"] == question["item_id"]
    assert active[0]["content"]["due_date"] == "2026-10-30"
    with Session(work.admin) as s:
        old = list(
            s.scalars(
                select(ProposalItemVersion)
                .where(ProposalItemVersion.item_id == UUID(question["item_id"]))
                .order_by(ProposalItemVersion.version)
            )
        )
        assert len(old) == 2 and not old[0].removed and old[1].removed
        assert old[0].content["due_date"] == "2026-10-20"


def test_returned_proposal_writer_can_edit_but_only_owner_can_submit(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    save(work, decide_request(work, proposal_id, "returned"), actor=work.peer)
    with Session(work.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(Grant.principal_id == work.peer, Grant.category_id == work.category)
        )
        grant.can_write = True
    row = read(work, proposal_id, work.peer).json()
    item = next(i for i in row["items"] if i["kind"] == "section")
    edit = request(
        work,
        "proposal.item.patch",
        {
            "proposal_id": proposal_id,
            "ops": [
                {
                    "item_id": item["item_id"],
                    "base_version": item["version"],
                    "kind": "section",
                    "content": {"key": "worth_it", "text": "退回后的共同修订"},
                }
            ],
        },
        revision=row["revision"],
    )
    response = post(work, edit, actor=work.peer)
    assert response.status_code == 200, response.text
    row = read(work, proposal_id, work.peer).json()
    request_submit = request(
        work,
        "proposal.g0.submit",
        {
            "proposal_id": proposal_id,
            "expected_revision": row["revision"],
            "reviewer_id": str(work.human),
        },
        revision=row["revision"],
    )
    response = post(work, request_submit, actor=work.peer, preview=True)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["reason"] == "owner_only"
