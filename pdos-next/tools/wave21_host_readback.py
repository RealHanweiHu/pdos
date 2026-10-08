"""Root-only actual marked-engine configuration; no business writes or fake eligibility.

The second whitelist scope is deliberately unpublished. It exercises startup
dispatch and cannot attest a Product, source, classification or qualification.
"""

# The guarded local loader initializes the server path before package imports.
# ruff: noqa: I001
import copy
import json
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from local_environment import ROOT
from wave16_closeout import private_json
from wave17_migrate import target
from wave19_selection_http import readback
from wave21_check import source
from pdos_next.api import create_app
from pdos_next.database import engine_for, tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave21-20261003"
REGISTRIES = (
    "_pdos_professional_issuers",
    "_pdos_operational_issuers",
    "_pdos_test_resource_issuers",
    "_pdos_quality_policy_issuers",
    "_pdos_quality_completion_profiles",
    "_pdos_capa_rule_issuers",
)


def main():
    if sys.argv[1:] != ["run"]:
        raise RuntimeError("Explicit Root read-only configuration checkpoint required")
    output = REPORT / "actual-host-readback-v1.json"
    if output.exists():
        raise RuntimeError("Original checkpoint must not be overwritten")
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    assert seed["marker"] == state["marker"]
    tenant, actor, product = (UUID(seed[k]) for k in ("tenant_id", "actor_id", "product_id"))
    engine, admin = engine_for(state["app_url"]), engine_for(state["admin_url"])
    ctx = Context(tenant, actor, actor)
    before, frozen = readback(admin), source()
    singles = {
        "professional_synthetic_scope": {"tenant_id": str(tenant), "product_id": str(product)},
        **{
            name + "_synthetic_profile": private_json(
                ROOT / (".local/" + stem + "-synthetic-profile.json")
            )
            for name, stem in (
                ("operational", "operational"),
                ("test_resource", "test-resource"),
                ("quality", "quality"),
                ("quality_followup", "quality-followup"),
                ("capa_facts", "capa-facts"),
            )
        },
    }
    result = {
        "status": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "business_commands": 0,
        "model_calls": 0,
        "before": before,
        "scope": (
            "Real marked SQLAlchemy engine, startup registries and real bound sessions; "
            "no business eligibility or qualification proof"
        ),
    }
    try:
        create_app(engine, engine_for(state["auth_url"]), **singles)
        prior = {name: dict(getattr(engine, name)) for name in REGISTRIES}
        old_professional = next(iter(prior[REGISTRIES[0]].values()))
        old_operational = next(iter(prior[REGISTRIES[1]].values()))
        old_resource = next(iter(prior[REGISTRIES[2]].values()))
        professional = {
            **singles["professional_synthetic_scope"],
            "key": old_professional.key,
            "version": old_professional.version,
        }
        operational = {
            **singles["operational_synthetic_profile"],
            "issuer_key": old_operational.key,
            "issuer_version": old_operational.version,
        }
        resource = {
            **singles["test_resource_synthetic_profile"],
            "issuer_key": old_resource.key,
            "issuer_version": old_resource.version,
        }
        originals = {
            "professional": professional,
            "operational": operational,
            "test_resource": resource,
            "quality": singles["quality_synthetic_profile"],
            "quality_followup": singles["quality_followup_synthetic_profile"],
            "capa_facts": singles["capa_facts_synthetic_profile"],
        }
        unpublished_product, unpublished_project = uuid4(), uuid4()
        plural = {}
        for family, old in originals.items():
            new = copy.deepcopy(old)
            new["product_id"] = str(unpublished_product)
            if "project_id" in new:
                new["project_id"] = str(unpublished_project)
            if family == "professional":
                new["key"] = "wave21-unpublished-authority"
            elif "issuer_key" in new:
                new["issuer_key"] = "wave21-unpublished-" + family
            if family in {"operational", "test_resource"}:
                new["decisions"] = []
            plural[family + "_synthetic_profiles"] = [copy.deepcopy(old), new]
        create_app(engine, engine_for(state["auth_url"]), **plural)
        reused = {}
        for name, existing in prior.items():
            current = getattr(engine, name)
            assert len(current) == 2
            assert all(current[key] is value for key, value in existing.items())
            assert all(current[key].epoch == value.epoch for key, value in existing.items())
            reused[name] = {
                "old_objects_reused": True,
                "old_epochs_preserved": True,
                "configured_scopes": 2,
            }
        result["registries"] = reused
        publisher = engine._pdos_capa_fact_runtime.host.owner.publisher
        unknown_product, unknown_project = uuid4(), uuid4()
        with tenant_session(engine, tenant) as session:
            assert session.get_bind() is engine
            assert publisher._select(session, ctx, product).issuer.product_id == product
            assert (
                publisher._select(session, ctx, unpublished_product).issuer.product_id
                == unpublished_product
            )
            try:
                publisher._select(session, ctx, unknown_product)
            except DomainError as error:
                assert error.code == "FACT_RULE_PROFILE_SCOPE_UNAVAILABLE" and error.status == 403
                result["unknown_rule_scope"] = {"code": error.code, "status": error.status}
            else:
                raise AssertionError("Unknown Rule scope fell back")
            from pdos_next.quality_followup_integration import _completion_profiles

            assessment = _completion_profiles(engine, plural["quality_followup_synthetic_profiles"])
            basis = SimpleNamespace(
                scope=SimpleNamespace(
                    tenant_id=tenant, product_id=unknown_product, project_id=unknown_project
                )
            )
            try:
                assessment(
                    session,
                    ctx,
                    unknown_product,
                    basis,
                    None,
                    None,
                    policy_snapshot=None,
                    observation=None,
                )
            except DomainError as error:
                assert error.code == "COMPLETION_PROFILE_SCOPE_MISSING" and error.status == 503
                result["unknown_completion_scope"] = {"code": error.code, "status": error.status}
            else:
                raise AssertionError("Unknown completion scope fell back")
        result["second_scope"] = (
            "Explicit unpublished whitelist only; no Product/source/event was created or consumed"
        )
        result["status"] = "PASS"
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_type"] = type(error).__name__
    finally:
        result["after"] = readback(admin)
        result["retained_and_fact_counts_unchanged"] = before == result["after"]
        result["source_unchanged"] = frozen == source()
        if not result["retained_and_fact_counts_unchanged"] or not result["source_unchanged"]:
            result["status"] = "FAIL"
        result["finished_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(result, indent=2) + "\n")
        engine.dispose()
        admin.dispose()
    print(json.dumps({"status": result["status"], "report": str(output)}))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
