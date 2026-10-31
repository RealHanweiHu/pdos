"""Resume after T1 expiry must reject, preserve proof, and recover by fresh review."""

# ruff: noqa: F811 -- imported pytest fixture is deliberate.
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.clock import now, using_clock
from pdos_next.domain.preproject.category_creation_models import CategoryCreationConfirmation
from pdos_next.domain.preproject.models import Proposal, ProposalItemVersion
from pdos_next.models import Audit, Category, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.service import digest
from tests.agent_kernel.test_category_candidate_transactions import personal_fixture
from tests.preproject.test_derivation_transactions import derivative_payload, synthetic_parent
from tests.preproject.test_g0 import payload, post, request
from tests.preproject.test_g0 import work as work


def counts(work):
    with Session(work.admin) as s:
        return {
            model.__tablename__: s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.tenant)
            )
            for model in (
                Category,
                Proposal,
                ProposalItemVersion,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        }


def proof(work, model, token):
    with Session(work.admin) as s:
        row = s.scalar(
            select(model).where(model.tenant_id == work.tenant, model.token_hash == digest(token))
        )
        assert row is not None
        return row.consumed


@pytest.mark.parametrize("entry", ["category_candidate", "new_product", "derivative"])
def test_resume_after_expiry_preserves_unconsumed_proof_and_recovers_same_request(
    work, tmp_path, entry
):
    at = [now()]
    with using_clock(lambda: at[0]):
        if entry == "category_candidate":
            f = personal_fixture(work, tmp_path, sources=False)
            data = deepcopy(f.candidate["payload"])
            data["deidentified_confirmed"] = True

            def preview(value):
                response = work.client.post(
                    "/v1/categories/preview", headers=work.headers, json=value
                )
                assert response.status_code == 200, response.text
                return {**value, "confirmation_token": response.json()["confirmation_token"]}

            def commit(value):
                return work.client.post("/v1/categories", headers=work.headers, json=value)

            model = CategoryCreationConfirmation

            def token_from(value):
                return value["confirmation_token"]
        else:
            args = (
                payload(work)
                if entry == "new_product"
                else derivative_payload(work, synthetic_parent(work), "new_variant")
            )
            data = request(work, "proposal.create", args)

            def preview(value):
                response = post(work, value, preview=True)
                assert response.status_code == 200, response.text
                return response.json()["command"]

            def commit(value):
                return post(work, value)

            model = Confirmation

            def token_from(value):
                return value["payload"]["confirmation_token"]

        original = preview(data)
        token = token_from(original)
        before = counts(work)
        # Deterministic equivalent of a host pause crossing the real 10-minute TTL.
        at[0] += timedelta(minutes=15)
        refused = commit(original)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "CONFIRMATION_REQUIRED"
        assert refused.json()["detail"]["reason"] == (
            "preview_required" if entry == "category_candidate" else "CONFIRMATION_REQUIRED"
        )
        assert not proof(work, model, token) and counts(work) == before
        # A fresh human preview is necessary; do not extend or consume the expired proof.
        refreshed = preview(original)
        new_token = token_from(refreshed)
        assert new_token != token
        accepted = commit(refreshed)
        assert accepted.status_code in (200, 201), accepted.text
        receipt = accepted.json()
        assert proof(work, model, new_token) and not proof(work, model, token)
        after = counts(work)
        # Lost success replays the exact executed request, including its fresh
        # confirmation. The expired request is not interchangeable with it.
        replay = commit(refreshed)
        assert replay.status_code in (200, 201), replay.text
        assert replay.json()["id"] == receipt["id"] and counts(work) == after
        if entry != "category_candidate":
            conflict = commit(original)
            assert conflict.status_code == 409
            assert conflict.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
            assert counts(work) == after
        with Session(work.admin) as s:
            assert s.get(Receipt, UUID(receipt["id"])).actor_id == work.human
