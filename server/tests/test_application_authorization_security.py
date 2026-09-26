"""User authorization history is never an Agent or Worker minting interface."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.test_agent_database_security import role_engine
from tests.test_agent_database_security import (
    secured_agent_database_url as secured_agent_database_url,
)


@pytest.mark.parametrize("role", ["pdos_agent", "pdos_worker"])
def test_restricted_roles_cannot_read_or_mutate_user_authority(
    secured_agent_database_url: str, role: str
) -> None:
    engine = role_engine(secured_agent_database_url, role)
    try:
        for sql in (
            "SELECT * FROM cehub_ai.application_authorizations",
            "DELETE FROM cehub_ai.application_authorizations",
            "SELECT * FROM cehub_ai.application_context_observations",
            "DELETE FROM cehub_ai.application_context_observations",
            "SELECT * FROM cehub_ai.application_context_manifests",
            "DELETE FROM cehub_ai.application_context_manifests",
            "SELECT * FROM cehub_ai.application_result_checkpoints",
            "DELETE FROM cehub_ai.application_result_checkpoints",
            "SELECT cehub_ai.application_result_receipt_valid(NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
            "SELECT * FROM cehub_ai.application_run_leases",
            "DELETE FROM cehub_ai.application_run_leases",
            "SELECT cehub_ai.application_lease_is_current(gen_random_uuid(),gen_random_uuid())",
            "SELECT cehub_ai.claim_application_result_run(NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
            "SELECT cehub_ai.application_authorization_is_current(gen_random_uuid())",
        ):
            with pytest.raises(DBAPIError, match="permission denied"), engine.begin() as c:
                c.execute(text(sql))
        if role == "pdos_worker":
            with engine.begin() as c:
                assert (
                    c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one()
                    == 0
                )
        else:
            with pytest.raises(DBAPIError, match="permission denied"), engine.begin() as c:
                c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
    finally:
        engine.dispose()
