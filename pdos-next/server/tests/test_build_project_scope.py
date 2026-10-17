"""Project-bound Build reads over real commands and an explicit synthetic baseline.

Only the empty published parent and its reader audience are owner-level fixture
data. Both projects are actual named G0 outputs; configurations and Builds use
their public preview/confirmation commands. No trigger or RLS guard is disabled.
"""

from copy import copy, deepcopy
from uuid import uuid4

from g0_fixture import create_g0_project
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert
from test_builds import build_command
from test_builds import configuration as configuration
from test_project_first_plan import accepted, cmd
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project

from pdos_next.database import tenant_session
from pdos_next.domain.preproject.baseline import publication_digest
from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.models import ObjectAudience, Receipt
from pdos_next.safety import verify_test_target
from pdos_next.service import digest
from tests.preproject.test_g0 import create, read, request, save, submit


def synthetic_published_baseline(setup):
    """Represent a stored empty publication, without claiming publish qualification."""
    verify_test_target(setup.admin)
    identity, receipt_id = uuid4(), uuid4()
    with tenant_session(
        setup.admin,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        session.execute(text("SET LOCAL ROLE pdos_next_owner"))
        baseline = DefinitionRevision(
            id=identity,
            tenant_id=setup.tenant,
            category_id=setup.category,
            product_id=setup.product,
            owner_id=setup.human,
            revision=2,
            title="Synthetic empty published baseline for project scope",
            purpose="Isolated Build project selection only",
            status="draft",
            sealed=False,
            visibility="private",
            use_cases=[],
            requirements=[],
            constraints=[],
            unknowns=[],
            exclusions=[],
            change_reason="Synthetic stored publication; no real publication acceptance",
        )
        session.add(baseline)
        session.flush()
        content_digest = publication_digest(definition_view(session, setup.ctx, baseline))
        session.add(
            Receipt(
                id=receipt_id,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                command_id=uuid4(),
                actor_id=setup.human,
                requester_id=setup.human,
                operation="product.definition.publish",
                subject_type="definition_revision",
                subject_id=identity,
                subject_revision=2,
                visibility="private",
                request_digest=digest(str(uuid4())),
                intent_digest=digest(str(uuid4())),
                result={"definition_digest": content_digest, "synthetic": True},
            )
        )
        session.flush()
        baseline.status, baseline.publication_receipt_id, baseline.sealed = (
            "published",
            receipt_id,
            True,
        )
        # Keep parent access explicit; project audience remains a separate fact.
        for object_type, subject_id in (
            ("products", setup.product),
            ("definition_revisions", identity),
            ("action_receipts", receipt_id),
        ):
            session.execute(
                insert(ObjectAudience)
                .values(
                    id=uuid4(),
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    object_type=object_type,
                    subject_id=subject_id,
                    owner_id=setup.human,
                    principal_id=setup.peer,
                )
                .on_conflict_do_nothing()
            )
    return identity


def second_project_configuration(setup, first):
    baseline_id = synthetic_published_baseline(setup)
    proposal_id, _ = create(
        setup,
        {
            "title": "Synthetic second project for the same model",
            "entry_kind": "derivative",
            "target_kind": "new_variant",
            "baseline_product_id": str(setup.product),
            "baseline_definition_id": str(baseline_id),
            "baseline_definition_revision": 2,
            "brief": "Verify project-bound Build selection",
            "groups": {
                "items": [
                    {
                        "kind": "section",
                        "content": {"key": "worth_it", "text": "Isolate trial projects"},
                    },
                    {"kind": "option", "content": {"name": "Trial variant", "kind": "new"}},
                    {
                        "kind": "option",
                        "content": {"name": "Keep current state", "kind": "do_nothing"},
                    },
                ]
            },
        },
    )
    submit(setup, proposal_id)
    reviewed = read(setup, proposal_id, setup.peer)
    assert reviewed.status_code == 200, reviewed.text
    row = reviewed.json()
    assert row["maturity"]["required_dispositions"] == []
    decision, _ = save(
        setup,
        request(
            setup,
            "proposal.g0.decide",
            {
                "proposal_id": proposal_id,
                "submission_id": row["submission"]["id"],
                "expected_revision": row["revision"],
                "outcome": "approved",
                "rationale": "Named review of an isolated synthetic variant",
                "selected_option_item_id": next(
                    item["item_id"]
                    for item in row["items"]
                    if item["kind"] == "option" and item["content"]["kind"] == "new"
                ),
                "dispositions": [],
                "project": {"name": "Synthetic second trial project", "owner_id": str(setup.human)},
            },
            revision=row["revision"],
        ),
        actor=setup.peer,
    )
    result = decision["result"]
    assert result["product_id"] == str(setup.product)
    assert result["project_id"] != first["project"]
    second = deepcopy(first)
    second["project"], second["definition"] = result["project_id"], result["definition_id"]
    second["engineering_payload"]["definition_id"] = second["definition"]
    second["engineering_payload"]["name"] = "Synthetic second project engineering configuration"
    second["engineering"], _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.configuration.create",
            second["engineering_payload"],
            first["source"],
        ),
    )
    second["process_payload"].update(
        engineering_configuration_id=second["engineering"]["subject_id"],
        name="Synthetic second project manufacturing configuration",
    )
    second["process"], _ = accepted(
        setup, cmd(setup, "npi.process.revise", second["process_payload"], first["source"])
    )
    return second


def create_two_project_builds(setup, first, *, include_second_build=True):
    """Reusable local seed: actual same-model G0 projects, configurations and Builds."""
    second = second_project_configuration(setup, first)
    first_build, _ = accepted(
        setup, build_command(setup, first, name="Synthetic project A prototype")
    )
    second_build = None
    if include_second_build:
        second_build, _ = accepted(
            setup, build_command(setup, second, name="Synthetic project B prototype")
        )
    return {
        "product_id": str(setup.product),
        "project_ids": [first["project"], second["project"]],
        "build_ids": [
            first_build["subject_id"],
            second_build["subject_id"] if second_build else None,
        ],
        "configurations": [first, second],
    }


def get_builds(setup, *, project_id=None, actor=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/builds",
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
        params={"project_id": project_id} if project_id is not None else {},
    )


def test_same_model_project_filter_and_unfiltered_compatibility(setup, configuration):
    pair = create_two_project_builds(setup, configuration, include_second_build=False)
    first_id, second_id = pair["project_ids"]
    empty = get_builds(setup, project_id=second_id)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"items": [], "unavailable_count": 0, "has_more": False}
    second_build, _ = accepted(
        setup, build_command(setup, pair["configurations"][1], name="Synthetic project B prototype")
    )
    pair["build_ids"][1] = second_build["subject_id"]

    unfiltered = get_builds(setup)
    assert unfiltered.status_code == 200, unfiltered.text
    all_rows = {item["id"]: item for item in unfiltered.json()["items"]}
    assert set(all_rows) == set(pair["build_ids"])
    assert unfiltered.json()["unavailable_count"] == 0
    for project_id, build_id in zip((first_id, second_id), pair["build_ids"], strict=True):
        filtered = get_builds(setup, project_id=project_id)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json() == {
            "items": [all_rows[build_id]],
            "unavailable_count": 0,
            "has_more": False,
        }
        assert filtered.json()["items"][0]["project_id"] == project_id


def test_project_filter_rejects_missing_and_other_model_project(setup, configuration):
    # A separate actual G0 output is readable in its own model, not this model.
    other = copy(setup)
    foreign = create_g0_project(other, name="Synthetic unrelated model project")
    assert other.product != setup.product
    for project_id in (str(uuid4()), foreign.project_id):
        refused = get_builds(setup, project_id=project_id)
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in refused.json()


def test_project_filter_rechecks_project_audience_after_model_access(setup, configuration):
    pair = create_two_project_builds(setup, configuration)
    # G0 explicitly shares its outputs with the named reviewer. Revoke only the
    # project audience, retaining the reviewer's actual model/baseline access.
    with tenant_session(
        setup.admin,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        session.execute(text("SET LOCAL ROLE pdos_next_owner"))
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.object_type == "projects",
                ObjectAudience.principal_id == setup.peer,
            )
        )
    model_read = get_builds(setup, actor=setup.peer)
    assert model_read.status_code == 200, model_read.text
    # An unreadable project must not become an empty successful response.
    for project_id in pair["project_ids"]:
        refused = get_builds(setup, project_id=project_id, actor=setup.peer)
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "FORBIDDEN_SCOPE"
    own = get_builds(setup, project_id=pair["project_ids"][1])
    assert own.status_code == 200, own.text
    assert [item["id"] for item in own.json()["items"]] == [pair["build_ids"][1]]
