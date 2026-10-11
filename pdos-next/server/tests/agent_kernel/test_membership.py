from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from tests.agent_kernel.test_revoked_terminal import close
from tests.agent_kernel.test_transactions import run


@pytest.mark.parametrize("product_bound", [False, True])
def test_no_expiration_is_current_authority_and_dispatch_does_not_fail_it(setup, product_bound):
    with Session(setup.admin) as s, s.begin():
        for grant in s.scalars(select(Grant).where(Grant.tenant_id == setup.tenant)):
            grant.expires_at = None
    store, scope = run(setup, **({"product_id": setup.product} if product_bound else {}))
    store.current(scope)
    assert close(setup, scope.run_id) is False
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(select(Grant).where(Grant.principal_id == setup.agent))
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as exc:
        store.current(scope)
    assert exc.value.code == "FORBIDDEN_SCOPE"
    assert close(setup, scope.run_id) is True


def test_no_expiration_does_not_restore_inactive_identity_or_a_missing_grant(setup):
    with Session(setup.admin) as s, s.begin():
        for grant in s.scalars(select(Grant).where(Grant.tenant_id == setup.tenant)):
            grant.expires_at = None
    store, scope = run(setup)
    with Session(setup.admin) as s, s.begin():
        s.get(Principal, setup.agent).active = False
    with pytest.raises(DomainError) as exc:
        store.current(scope)
    assert exc.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as s, s.begin():
        s.get(Principal, setup.agent).active = True
        grant = s.scalar(select(Grant).where(Grant.principal_id == setup.agent))
        s.delete(grant)
    with pytest.raises(DomainError) as exc:
        KernelStore(setup.engine).scope(
            tenant_id=setup.tenant,
            requester_id=setup.human,
            writer_id=setup.agent,
            category_id=setup.category,
            run_id=scope.run_id,
        )
    assert exc.value.code == "FORBIDDEN_SCOPE"
