"""Pure metadata query/closure checks; no Session, database, model or network."""

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import union_all
from sqlalchemy.dialects import postgresql

from pdos_next.personal_attention_decisions import external_pending, queries


def _compile(value):
    return value.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})


def test_sources_share_typed_union_columns_and_never_create_actions():
    ctx = SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4())
    sources = queries(ctx)
    assert isinstance(sources, tuple) and len(sources) == 2
    assert tuple(sources[0].selected_columns.keys()) == tuple(sources[1].selected_columns.keys())
    sql = str(_compile(union_all(*sources)))
    assert str(ctx.tenant_id) in sql and str(ctx.requester_id) in sql
    assert "UNION ALL" in sql and "FOR UPDATE" not in sql
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|SECURITY DEFINER)\b", sql)
    assert "proposal.g0.decide" not in sql and "external_handoff.receipt.record" not in sql


def test_g0_is_one_exact_undecided_current_submission_for_the_named_reviewer():
    query = queries(SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4()))[0]
    sql = str(_compile(query))
    assert "proposal_submissions.id = proposals.current_submission_id" in sql
    assert "proposal_submissions.owner_id = proposals.owner_id" in sql
    assert "proposals.status = 'in_review'" in sql
    assert "proposal_submissions.reviewer_id =" in sql and "proposals.owner_id !=" in sql
    assert "proposal_decisions.submission_id = proposal_submissions.id" in sql
    assert "NOT (EXISTS" in sql
    assert "grants.can_write IS true" in sql and "grants.product_manager IS true" in sql
    assert "grants.expires_at > transaction_timestamp()" in sql
    assert "g0_review:" in sql and "named_reviewer" in sql
    assert not any(
        word in sql
        for word in ("frozen_document", "context_refs", "customer_identities", "proposals.brief")
    )


def test_external_reads_only_owned_exact_current_real_receipt_heads_and_stage_leaves():
    query = queries(SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4()))[1]
    sql = str(_compile(query))
    assert "external_handoff_authorizations.owner_id =" in sql
    assert "external_handoff_currents.handoff_id = external_handoff_authorizations.id" in sql
    assert "external_delivery_intents.id = external_handoff_currents.intent_id" in sql
    assert "external_receipts.id = external_handoff_currents.latest_receipt_id" in sql
    assert "external_receipts.revision = external_handoff_currents.latest_receipt_revision" in sql
    assert "external_receipts.sequence = external_handoff_currents.receipt_count" in sql
    assert "external_handoff_currents.receipt_count > 0" in sql
    assert "EXTERNAL_SEND_UNVERIFIED" in sql and "EXTERNAL_RECEIPT_EXCEPTION" in sql
    assert "发送状态未核实" in sql
    assert all("'" + stage + "'" in sql for stage in ("sent", "accepted", "effective"))
    assert not re.search(
        r"\.(?:body|original|source|input_snapshot|material_snapshot|issuer_snapshot)\b", sql
    )
    assert not re.search(r"external_handoff_currents\.projection\s+(?:AS|FROM)\b", sql)


@pytest.mark.parametrize(
    "count,states,pending",
    [
        (0, ("not_recorded",) * 3, False),
        (0, ("unknown", "not_recorded", "not_recorded"), False),
        (1, ("succeeded", "not_recorded", "not_recorded"), True),
        (1, ("not_recorded", "succeeded", "not_recorded"), True),
        (1, ("not_recorded", "not_recorded", "succeeded"), True),
        (3, ("succeeded",) * 3, False),
        *(
            (3, ("succeeded", state, "succeeded"), True)
            for state in ("partial", "unknown", "rejected", "failed", "conflict")
        ),
    ],
)
def test_real_receipt_and_three_independent_stage_boundaries(count, states, pending):
    assert str(_compile(external_pending(count, *states))) == ("true" if pending else "false")
