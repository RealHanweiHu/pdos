"""T2 customer acceptance (D309, P97 第 5–8 项, C11) on the isolated PG target.

The signed sheet is a real uploaded, scanned and parsed synthetic original; the
Build comes from the existing demand fixture. Nothing is sent anywhere.
"""

# ruff: noqa: F401, F811 -- imported pytest fixtures are intentional

from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from builds.test_build_demand import demand_work
from builds.test_builds import configuration, definition, project
from originals.test_original_security import parsed, security_work, uploaded
from sqlalchemy import select

from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Outbox, Product, now
from pdos_next.core.service import Context
from pdos_next.domain.delivery.customer_acceptance import service as acceptance
from pdos_next.domain.delivery.customer_acceptance.schemas import Payload
from pdos_next.errors import DomainError
from tests.d47_support import command, confirmed, get, headers_for, post, preview

OPERATION = "customer.acceptance.record"
LINE = "Synthetic original"


@pytest.fixture
def acceptance_work(setup, security_work, demand_work):
    original = uploaded(security_work)
    artifact = parsed(security_work, original)
    return {
        "build_id": demand_work["build_id"],
        "project": demand_work["project"],
        "sheet": str(artifact),
    }


def sheet(work, artifact=None):
    return {
        "id": artifact or work["sheet"],
        "revision": 1,
        "kind": "artifact",
        "position": f"line:1;quote_sha256:{sha256(LINE.encode()).hexdigest()}",
    }


def scopes(**states):
    values = {
        "appearance": {
            "state": "conditionally_accepted",
            "conditions": ["量产前改为哑光表面"],
            "expires_at": "2027-06-30T00:00:00+08:00",
        },
        "dimensions": {"state": "accepted"},
        "performance": {"state": "not_accepted"},
        "packaging_labeling": {"state": "not_applicable"},
        "certification_docs": {"state": "accepted"},
    }
    values.update(states)
    return [{"scope": key, **value} for key, value in values.items()]


def record(setup, work, *, artifact=None, previous=None, **changes):
    payload = {
        "customer": {"label": "客户 A（合成）", "goodjob_id": "GJ-SYN-001"},
        "scopes": scopes(),
        "signed_sheet": sheet(work, artifact),
        "reason": "客户签样单回传，按五类登记",
        **(
            {"acceptance": previous}
            if previous
            else {"build_id": work["build_id"], "expected_build_revision": 1}
        ),
        **changes,
    }
    return command(
        setup,
        OPERATION,
        payload,
        reads=[{"artifact_id": artifact or work["sheet"], "expected_revision": 1}],
    )


def test_scopes_record_what_is_and_is_not_accepted_and_reviews_only_list_it(setup, acceptance_work):
    work = acceptance_work
    receipt, shown = confirmed(setup, record(setup, work))
    review = shown["review"]
    assert shown["write_tier"] == "T2" and review["after"]["state"] == "not_accepted"
    assert review["covered"] == ["外观", "尺寸", "认证资料"] and review["not_covered"] == [
        "性能",
        "包装标识",
    ]
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "customer.acceptance_recorded"
        )
    revised, _ = confirmed(
        setup,
        record(
            setup,
            work,
            previous={"id": receipt["subject_id"], "revision": 1},
            scopes=scopes(performance={"state": "accepted"}),
        ),
    )
    listed = get(setup, f"builds/{work['build_id']}/customer-acceptances").json()["items"]
    assert [(row["state"], row["revision"]) for row in listed] == [("conditional", 2)]
    assert [row["revision"] for row in listed[0]["history"]] == [2, 1]
    governance = get(setup, f"projects/{work['project']}/governance")
    assert governance.status_code == 200, governance.text
    listing = governance.json()["customer_acceptances"]
    assert listing[0]["state"] == "conditional" and "性能" in listing[0]["covered"]
    assert revised["subject_id"] != receipt["subject_id"]


def test_refusals_sheet_scope_send_and_identity(setup, acceptance_work):
    work = acceptance_work
    typed = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Typed note",
                "source_label": "Synthetic",
                "content": LINE,
                "visibility": "private",
            },
        ),
    )
    assert typed.status_code == 200, typed.text
    not_original = preview(setup, record(setup, work, artifact=typed.json()["subject_id"]))
    assert not_original.status_code == 409 and not_original.json()["code"] == "VALIDATION_FAILED"
    missing = preview(setup, record(setup, work, scopes=scopes()[:4]))
    assert missing.status_code == 422
    unconditional = preview(
        setup, record(setup, work, scopes=scopes(appearance={"state": "conditionally_accepted"}))
    )
    assert unconditional.status_code == 422
    linked = preview(setup, record(setup, work, send_ref={"id": str(uuid4()), "revision": 1}))
    assert linked.status_code == 503
    expired = preview(
        setup,
        record(
            setup,
            work,
            scopes=scopes(
                appearance={"state": "accepted", "expires_at": "2020-01-01T00:00:00+00:00"}
            ),
        ),
    )
    assert expired.status_code == 409 and expired.json()["code"] == "VALIDATION_FAILED"
    peer = preview(setup, record(setup, work), headers_for(setup, setup.peer))
    assert peer.status_code == 403
    unconfirmed = post(setup, record(setup, work))
    assert unconfirmed.status_code in {403, 409}
    receipt, shown = confirmed(setup, record(setup, work))
    assert post(setup, shown["command"]).json()["id"] == receipt["id"]


def test_ai_cannot_sign_for_the_customer(setup, acceptance_work):
    work = acceptance_work
    cmd = Command.model_validate(record(setup, work))
    ctx = Context(setup.tenant, setup.agent, setup.human, category_id=setup.category)
    with (
        pytest.raises(DomainError) as failed,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        acceptance.validate(
            s, ctx, cmd, s.get(Product, setup.product), Payload.model_validate(cmd.payload)
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    assert now()
