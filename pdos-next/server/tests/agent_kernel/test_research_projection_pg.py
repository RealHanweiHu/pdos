"""Query projection from actual bound private proposals and uploaded originals."""
# ruff: noqa: F811 -- explicitly imported PG fixtures

import pytest
from sqlalchemy.orm import Session

from pdos_next.models import UploadedOriginal
from pdos_next.research.egress import decide
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE
from tests.agent_kernel.test_proposal_context_pg import start
from tests.agent_kernel.test_transactions import run
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


@pytest.mark.parametrize("kind", ["public", "customer", "filename", "fragment"])
def test_actual_proposal_text_is_classified_and_receipted_before_unsigned_research(
    work, security_work, kind
):
    owner, scope = start(work, security_work, "customer_request")
    query = "public pump catalogue"
    if kind == "customer":
        query = "Synthetic customer pump"
    elif kind == "fragment":
        query = "look up " + QUOTE
    elif kind == "filename":
        with owner.store.transaction(scope) as (session, run):
            from uuid import UUID

            from pdos_next.models import Artifact

            source = session.get(Artifact, UUID(run.read_sources[0]["artifact_id"]))
            query = "look up " + session.get(UploadedOriginal, source.original_id).filename
    with owner.store.transaction(scope) as (session, row):
        # P26: unsigned providers are not blocked; the classification is receipted.
        decision = decide(session, scope, row, "unsigned-search", query)
        assert decision.agreement_id is None
        if kind == "public":
            assert decision.data_categories == ("public",)
        elif kind == "customer":
            assert "customer" in decision.data_categories
        else:
            assert "customer_original" in decision.data_categories


def test_bound_model_name_is_classified_as_internal_not_public(setup):
    from pdos_next.models import Product

    store, scope = run(setup, product_id=setup.product, data_categories=("internal",))
    with Session(setup.admin) as session:
        name = session.get(Product, setup.product).name
    with store.transaction(scope) as (session, row):
        # P26: the bound product name keeps the query classified internal, receipted, not blocked.
        decision = decide(session, scope, row, "unsigned-search", "specification " + name)
        assert "internal" in decision.data_categories and decision.agreement_id is None
