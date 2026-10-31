"""Root-run PG draft for explicit personal targets and read-only gap recovery."""
# ruff: noqa: F811 -- explicitly imported native scanner fixture

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.knowledge.assistant_models import (
    KnowledgeAnswerReview,
    KnowledgeGapSubmission,
)
from pdos_next.models import Artifact
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_retrieval_pg import index, register
from tests.knowledge_pg.test_assistant_knowledge import answer, from_seed, root, seed, submit
from tests.test_original_security import security_work as security_work  # noqa: F401


def test_personal_answer_explicit_target_saves_original_run_and_proof_without_fabricated_artifact(
    setup,
):
    identity = register(setup, "个人回答的实际来源", "漏气处理：更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)
    client = SyntheticClient()
    owner, scope, host, _ = fixture(setup, client)
    assert scope.category_id is None
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    with Session(setup.admin) as session:
        before = session.scalar(
            select(func.count()).select_from(Artifact).where(Artifact.tenant_id == setup.tenant)
        )
    value = from_seed(seed(setup, scope.run_id))
    saved = submit(setup, value)
    assert saved.status_code == 200, saved.text
    with Session(setup.admin) as session:
        assert session.get(AgentRun, scope.run_id).category_id is None
        review = session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.subject_id == UUID(saved.json()["result"]["entry_id"])
            )
        )
        assert review.origin_run_id == scope.run_id
        assert [(r["source_id"], r["category_id"]) for r in review.source_proof] == [
            (str(identity), str(setup.category)),
        ]
        assert (
            session.scalar(
                select(func.count()).select_from(Artifact).where(Artifact.tenant_id == setup.tenant)
            )
            == before
        )
    assert client.calls == 5


def test_unknown_gap_response_recovers_exact_native_submission_without_appending(setup):
    _identity, run, client = answer(setup)
    draft = {"run_id": str(run), "kind": "missing_material", "feedback_id": None}
    preview = setup.client.post(root(setup) + "/gaps/preview", headers=setup.headers, json=draft)
    assert preview.status_code == 200, preview.text
    value = {
        **draft,
        "request_key": str(uuid4()),
        "preview_digest": preview.json()["preview_digest"],
    }
    accepted = setup.client.post(root(setup) + "/gaps", headers=setup.headers, json=value)
    assert accepted.status_code == 200, accepted.text
    with Session(setup.admin) as session:
        before = session.scalar(
            select(func.count())
            .select_from(KnowledgeGapSubmission)
            .where(KnowledgeGapSubmission.tenant_id == setup.tenant)
        )
    recovery = setup.client.post(root(setup) + "/gaps/recover", headers=setup.headers, json=value)
    assert recovery.status_code == 200 and recovery.json() == accepted.json(), recovery.text
    changed = {**value, "preview_digest": "b" * 64}
    wrong = setup.client.post(root(setup) + "/gaps/recover", headers=setup.headers, json=changed)
    assert wrong.status_code == 409 and wrong.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    missing = setup.client.post(
        root(setup) + "/gaps/recover",
        headers=setup.headers,
        json={**value, "request_key": str(uuid4())},
    )
    assert missing.status_code == 404
    peer = setup.client.post(
        root(setup) + "/gaps/recover",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        json=value,
    )
    assert peer.status_code == 404
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeGapSubmission)
                .where(KnowledgeGapSubmission.tenant_id == setup.tenant)
            )
            == before
        )
    assert client.calls == 5


def test_personal_product_original_requires_real_product_context_for_candidate(security_work):
    from tests.test_original_security import parsed, uploaded

    work, setup = security_work, security_work.setup
    original = uploaded(work, content="漏气处理：更换密封圈。RAW_ONLY_CHILD_MARKER".encode())
    source = parsed(work, original)
    index(setup, source)
    client = SyntheticClient()
    owner, scope, host, _ = fixture(setup, client)
    assert execute(owner, scope, host)["status"] == "completed"
    response = setup.client.post(root(setup) + "/answer-draft", headers=setup.headers,
                                 json={"run_id": str(scope.run_id), "kind": "rule"})
    assert response.status_code == 403 and "实际型号或项目" in response.text, response.text
    with Session(setup.admin) as session:
        run = session.get(AgentRun, scope.run_id)
        assert run.category_id is None and run.product_id is None
        assert session.get(Artifact, source).original_id == original
    assert client.calls == 5
