"""Startup ambiguity fails before engine/issuer configuration; no database."""

from types import SimpleNamespace

import pytest

from pdos_next.api import create_app

CHOICES = (
    ("professional_synthetic_scope", "professional_synthetic_profiles"),
    ("operational_synthetic_profile", "operational_synthetic_profiles"),
    ("test_resource_synthetic_profile", "test_resource_synthetic_profiles"),
    ("quality_synthetic_profile", "quality_synthetic_profiles"),
    ("quality_followup_synthetic_profile", "quality_followup_synthetic_profiles"),
    ("capa_facts_synthetic_profile", "capa_facts_synthetic_profiles"),
)


@pytest.mark.parametrize("single,plural", CHOICES)
def test_ambiguous_host_choices_do_not_mutate_engine(single, plural):
    engine = SimpleNamespace(retained=object())
    before = vars(engine).copy()
    with pytest.raises(ValueError, match="one explicit"):
        create_app(engine, **{single: {}, plural: [{}]})
    assert vars(engine) == before


@pytest.mark.parametrize("single,plural", CHOICES)
@pytest.mark.parametrize("invalid", [[], {}, (), False, [None] * 21])
def test_invalid_plural_choice_fails_before_engine_creation(monkeypatch, single, plural, invalid):
    def forbidden():
        pytest.fail("Invalid startup input must fail before obtaining engines")

    monkeypatch.setattr("pdos_next.api.configured_engines", forbidden)
    with pytest.raises(ValueError, match="nonempty"):
        create_app(**{plural: invalid})


@pytest.mark.parametrize(
    "profile", ["capa_facts_synthetic_profile", "capa_facts_synthetic_profiles"]
)
def test_explicit_fact_owner_and_publisher_are_ambiguous_before_any_configuration(profile):
    engine = SimpleNamespace(retained=object())
    before = vars(engine).copy()
    with pytest.raises(ValueError, match="one explicit fact"):
        create_app(engine, capa_fact_material_owner=object(), **{profile: [{}]})
    assert vars(engine) == before


@pytest.mark.parametrize("profile_count", [1, 21])
def test_professional_plural_requires_real_target_guard_before_issuer_registration(
    monkeypatch, profile_count
):
    engine = SimpleNamespace(retained=object())
    before = vars(engine).copy()

    def rejected_target(actual):
        assert actual is engine
        raise RuntimeError("Target is not the explicitly verified temporary database")

    def no_registration(*args, **kwargs):
        pytest.fail("No professional issuer may register after target rejection")

    monkeypatch.setattr("pdos_next.safety.verify_test_target", rejected_target)
    monkeypatch.setattr(
        "pdos_next.domain.professional_authority.service.configure_local_synthetic_profiles",
        no_registration,
        raising=False,
    )
    with pytest.raises(RuntimeError, match="explicitly verified"):
        create_app(engine, professional_synthetic_profiles=[{} for _ in range(profile_count)])
    assert vars(engine) == before
