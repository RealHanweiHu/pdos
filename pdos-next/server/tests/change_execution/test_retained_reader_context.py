"""Historical signer facts are read under the actual reader's transaction."""

# ruff: noqa: F811 - imported pytest fixture

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from professional_authority.test_assessment import (
    AT,
    assessed,
    fake,  # noqa: F401 - real reduction fixture
)

from pdos_next import change_controlled_owner as owner
from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.service import Context


@pytest.mark.parametrize("same_reader", [True, False])
def test_saved_signer_is_not_impersonated_in_a_readers_transaction(fake, monkeypatch, same_reader):
    snapshot = assessed(fake)
    actor = fake.subject if same_reader else uuid4()
    reader = Context(fake.tenant, actor, actor)
    fake.info = {"scope": (fake.tenant, actor, actor, None)}
    observed = []

    def project(session, caller, *args, **kwargs):
        require_context(session, caller)
        observed.append(caller)
        return None, None

    monkeypatch.setattr(owner.professional, "_project", project)
    monkeypatch.setattr(owner, "clock", lambda: AT)
    row = SimpleNamespace(
        actor_id=fake.subject, project_id=fake.project, authority_snapshot=snapshot
    )
    assert owner.original_authority(fake, reader, fake.product, row) is None
    assert observed and all(caller is reader for caller in observed)
    assert snapshot["subject_id"] == str(fake.subject)


def test_saved_publication_authority_must_belong_to_its_actual_actor(fake):
    row = SimpleNamespace(
        actor_id=uuid4(), project_id=fake.project, authority_snapshot=assessed(fake)
    )
    with pytest.raises(DomainError) as error:
        owner.original_authority(fake, fake.ctx, fake.product, row)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_invalid_historical_signature_still_blocks_a_new_dependent_action(fake, monkeypatch):
    snapshot = deepcopy(assessed(fake))
    snapshot.pop("purpose")
    row = SimpleNamespace(
        actor_id=fake.subject, project_id=fake.project, authority_snapshot=snapshot
    )
    monkeypatch.setattr(owner, "clock", lambda: AT)
    with pytest.raises(DomainError) as error:
        owner.original_authority(fake, fake.ctx, fake.product, row)
    assert error.value.reason == "RECHECK_REQUIRED"
