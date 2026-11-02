"""Local explicit file selection; no database, credentials or runtime start."""

import importlib.util
import json
from pathlib import Path

import pytest


def loader():
    path = Path(__file__).parent.parent / "local_environment.py"
    spec = importlib.util.spec_from_file_location("staged_local_host_profiles", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.local_profile_environment


STATE = {"preview_tenant_id": "old-tenant", "preview_product_id": "old-product"}


def test_no_profiles_clears_all_plural_choices_and_retains_exact_legacy_professional(tmp_path):
    value = loader()(tmp_path, STATE)
    assert len(value) == 12
    assert json.loads(value.pop("PDOS_PROFESSIONAL_SYNTHETIC_SCOPE")) == {
        "tenant_id": "old-tenant",
        "product_id": "old-product",
    }
    assert set(value.values()) == {"null"}


@pytest.mark.parametrize(
    "family,stem,suffix",
    [
        ("PROFESSIONAL", "professional", "SCOPE"),
        ("OPERATIONAL", "operational", "PROFILE"),
        ("TEST_RESOURCE", "test-resource", "PROFILE"),
        ("QUALITY", "quality", "PROFILE"),
        ("QUALITY_FOLLOWUP", "quality-followup", "PROFILE"),
        ("CAPA_FACTS", "capa-facts", "PROFILE"),
    ],
)
def test_explicit_list_selects_only_list_and_does_not_rewrite_retained_file(
    tmp_path, family, stem, suffix
):
    old = tmp_path / f"{stem}-synthetic-profile.json"
    old.write_text('{"retained":"unchanged"}\n')
    profiles = [{"old_scope": "explicit"}, {"new_scope": "explicit"}]
    (tmp_path / f"{stem}-synthetic-profiles.json").write_text(json.dumps(profiles))
    value = loader()(tmp_path, STATE)
    assert value[f"PDOS_{family}_SYNTHETIC_{suffix}"] == "null"
    assert json.loads(value[f"PDOS_{family}_SYNTHETIC_PROFILES"]) == profiles
    assert old.read_text() == '{"retained":"unchanged"}\n'


@pytest.mark.parametrize("invalid", [[], {}, False, [None] * 21])
def test_bad_explicit_list_never_falls_back_to_old_profile(tmp_path, invalid):
    (tmp_path / "operational-synthetic-profile.json").write_text('{"old":"retained"}')
    (tmp_path / "operational-synthetic-profiles.json").write_text(json.dumps(invalid))
    with pytest.raises(RuntimeError, match="Invalid finite OPERATIONAL"):
        loader()(tmp_path, STATE)


def test_single_file_bytes_are_forwarded_without_reconstructing_issuer_or_ledger(tmp_path):
    raw = ' {"arbitrary_fixed_ledger": [1, 2]}\n'
    (tmp_path / "operational-synthetic-profile.json").write_text(raw)
    value = loader()(tmp_path, STATE)
    assert value["PDOS_OPERATIONAL_SYNTHETIC_PROFILE"] == raw
    assert value["PDOS_OPERATIONAL_SYNTHETIC_PROFILES"] == "null"
