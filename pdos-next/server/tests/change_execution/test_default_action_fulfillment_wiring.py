"""Actual create_app startup composition; no database, HTTP or workflow calls.

Factories and owner constructors execute unchanged. These checks demonstrate
wiring and preservation of explicit configuration, not business authorization.
"""

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from temporalio.client import Client

from pdos_next.api import create_app
from pdos_next.capa_applicability_owner import (
    ActualActionFulfillmentOwner,
    ActualApplicabilityOwner,
)
from pdos_next.capa_fact_owner import ActualFactOwner
from pdos_next.change_action_fulfillment_owner import ApprovedChangeActionFulfillmentOwner
from pdos_next.change_controlled_owner import ApprovedActionIntentOwner
from pdos_next.change_implementation_owner import ApprovedImplementationOwner
from pdos_next.domain.capa_effectiveness import fact_service
from pdos_next.domain.capa_effectiveness.candidate_commands import semantic_owner
from pdos_next.domain.capa_effectiveness.named_review_owner import ActualNamedReviewOwner
from pdos_next.paired_output_bridge import LivePairedOwner


@pytest.fixture
def engines(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Startup wiring must not access database, HTTP or Temporal")

    for cls, method in (
        (Engine, "connect"),
        (Engine, "raw_connection"),
        (httpx.Client, "request"),
        (httpx.AsyncClient, "request"),
        (Client, "connect"),
    ):
        monkeypatch.setattr(cls, method, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    engine = create_engine("postgresql+psycopg://unused/never_connect")
    auth_engine = create_engine("postgresql+psycopg://unused/never_authenticate")
    yield engine, auth_engine
    engine.dispose()
    auth_engine.dispose()


def runtime_owner(engine):
    with Session(engine) as session:
        return fact_service._runtime(session).host.owner


def test_actual_default_factory_installs_engine_bound_formal_fulfillment_owner(engines):
    engine, auth_engine = engines
    app = create_app(engine=engine, auth_engine=auth_engine, workflow_enabled=False)
    assert type(app) is FastAPI
    fact = runtime_owner(engine)
    assert type(fact) is ActualFactOwner
    review = fact.review_owner
    assert type(review) is ActualNamedReviewOwner and review.fact_owner is fact
    assert review.candidate_semantic_owner == semantic_owner()
    assert type(review.paired_owner) is LivePairedOwner
    applicability = review.applicability_owner
    assert type(applicability) is ActualApplicabilityOwner
    assert applicability.fact_owner is fact and applicability.paired_owner is review.paired_owner
    action = applicability.action_owner
    assert type(action) is ActualActionFulfillmentOwner
    implementation = action.implementation_owner
    assert type(implementation) is ApprovedChangeActionFulfillmentOwner
    assert implementation.engine is engine and implementation.engine is not auth_engine
    assert type(implementation.implementation) is ApprovedImplementationOwner
    assert implementation.implementation.engine is engine
    assert type(implementation.action_intent) is ApprovedActionIntentOwner
    assert not implementation._reads
    assert not implementation.implementation._reads
    assert not implementation.action_intent._handles


def test_default_startup_does_not_install_professional_or_synthetic_qualification(engines):
    engine, auth_engine = engines
    create_app(engine=engine, auth_engine=auth_engine, workflow_enabled=False)
    assert runtime_owner(engine).publisher is None
    assert getattr(engine, "_pdos_professional_synthetic", False) is False
    for registry in (
        "_pdos_professional_issuers",
        "_pdos_professional_issuer_epochs",
        "_pdos_quality_policy_issuers",
        "_pdos_quality_bootstrap_profiles",
        "_pdos_quality_completion_profiles",
        "_pdos_quality_completion_profile_epochs",
        "_pdos_capa_rule_issuers",
        "_pdos_capa_rule_issuer_epochs",
    ):
        assert not getattr(engine, registry, {})


def test_actual_factory_preserves_explicit_review_owner_and_its_ports(engines):
    engine, auth_engine = engines
    fact = ActualFactOwner()
    paired = LivePairedOwner()
    implementation = ApprovedChangeActionFulfillmentOwner(engine, epoch=3)
    action = ActualActionFulfillmentOwner(implementation_owner=implementation, epoch=2)
    applicability = ActualApplicabilityOwner(fact, paired_owner=paired, action_owner=action)
    review = ActualNamedReviewOwner(
        fact,
        candidate_semantic_owner=semantic_owner(),
        paired_owner=paired,
        applicability_owner=applicability,
    )
    fact.review_owner = review
    create_app(
        engine=engine,
        auth_engine=auth_engine,
        workflow_enabled=False,
        capa_fact_material_owner=fact,
    )
    assert runtime_owner(engine) is fact
    assert fact.review_owner is review
    assert review.paired_owner is paired
    assert review.applicability_owner is applicability
    assert applicability.action_owner is action
    assert action.implementation_owner is implementation and implementation.engine is engine
