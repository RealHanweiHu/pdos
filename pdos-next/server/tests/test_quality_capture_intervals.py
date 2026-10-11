"""Actual invoker guard retains declared duty, qualification and policy intervals."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next.models import now


def test_ordinary_capture_has_no_ttl_but_actual_fact_intervals_remain_required():
    import os

    from pdos_next.database import engine_for
    from pdos_next.safety import verify_test_target

    # No application .env fallback, even for this read-only database guard.
    engine = engine_for(os.environ["TEST_DATABASE_URL"])
    verify_test_target(engine)
    at = now()
    fact = {
        "role": "quality",
        "nature": "synthetic",
        "state": "active",
        "operations": ["quality.issue.root_cause.decide"],
        "purposes": ["scope-specific-purpose"],
        "valid_from": (at - timedelta(days=1)).isoformat(),
        "valid_until": (at + timedelta(days=1)).isoformat(),
    }
    authority = {
        "valid_until": None,
        "roles": ["quality"],
        "operation": fact["operations"][0],
        "purpose": fact["purposes"][0],
        "synthetic": True,
        "fact_refs": [{**fact, "kind": kind} for kind in ("duty", "qualification")],
    }
    policy = {
        "valid_until": None,
        "id": str(uuid4()),
        "revision": 1,
        "source_basis": [],
    }
    policy["source_basis"] = [{**fact, "id": policy["id"], "revision": 1}]
    query = text("SELECT quality_capture_time_current(:authority,:policy,:at)").bindparams(
        bindparam("authority", type_=JSONB), bindparam("policy", type_=JSONB)
    )
    with engine.connect() as s, s.begin():
        s.execute(text("SET LOCAL ROLE pdos_next_app"))

        def current(a=authority, p=policy):
            return s.scalar(query, {"authority": a, "policy": p, "at": at})

        assert current() is True
        for index in (0, 1):
            expired = deepcopy(authority)
            expired["fact_refs"][index]["valid_until"] = at.isoformat()
            assert current(expired) is False
        other_role = deepcopy(authority)
        other_role["fact_refs"][1]["role"] = "engineering"
        assert current(other_role) is False
        revoked = deepcopy(authority)
        revoked["fact_refs"][1]["state"] = "withdrawn"
        assert current(revoked) is False
        declared_deadline = deepcopy(authority)
        declared_deadline["valid_until"] = at.isoformat()
        assert current(declared_deadline) is False
        expired_policy = deepcopy(policy)
        expired_policy["source_basis"][0]["valid_until"] = at.isoformat()
        assert current(p=expired_policy) is False
        wrong_policy = deepcopy(policy)
        wrong_policy["revision"] = 2
        assert current(p=wrong_policy) is False
        # An unrelated expired earlier fact does not impose a capture-wide TTL.
        history = deepcopy(authority)
        history["fact_refs"].append({**fact, "kind": "duty", "valid_until": at.isoformat()})
        assert current(history) is True
