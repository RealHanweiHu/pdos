"""Root-executed distinct shared Formal/Run after an actually saved expired plan.

Inert import; no change/replan/withdrawal of any old saved Plan or Promise.
All real profile installation, target IO and exact common confirmations are Root's.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

FIRST_SOURCE_SHA = "e1613219fec3fd4ff8b6c954c3f023905a5290499ac47bb3240d40a8230e9659"
INTENT_KEYS = {
    "schema_version",
    "generation",
    "marker",
    "scope",
    "purpose",
    "build_id",
    "sample_id",
    "source_generation",
    "source_checkpoint_sha256",
    "source_resource_profile_sha256",
    "source_resource_input_sha256",
    "readback_file",
    "readback_sha256",
    "decision_file",
    "decision_sha256",
    "reason",
}
READBACK_KEYS = {
    "schema_version",
    "marker",
    "scope",
    "source_generation",
    "source_checkpoint_sha256",
    "build_id",
    "request_id",
    "run_id",
    "request_current",
    "run_current",
    "plan_receipt_id",
    "promise_receipt_id",
    "actual_start_count",
    "resource_occupancy_count",
    "sample_usage_count",
    "checked_at",
}
DECISION_KEYS = {
    "schema_version",
    "marker",
    "scope",
    "source_generation",
    "source_checkpoint_sha256",
    "readback_sha256",
    "generation",
    "operation",
    "old_saved_plan_and_promise_preserved",
    "reason",
}


def layout_root(path):
    path = Path(path).resolve()
    if path.name != "wave22_shared_fresh_request.py":
        raise RuntimeError("Unexpected fresh-request filename")
    if path.parent.name == "tools":
        return path.parent.parent
    if path.parent.name == "wave22-fresh-request-staged" and path.parent.parent.name == ".local":
        return path.parents[2]
    raise RuntimeError("Unexpected fresh-request layout")


ROOT = layout_root(__file__)


def first_module():
    staged = Path(__file__).resolve().parent.name != "tools"
    path = ROOT / (
        ".local/wave22-test-staged/v4/wave22_shared_test.py"
        if staged
        else "tools/wave22_shared_test.py"
    )
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != FIRST_SOURCE_SHA:
        raise RuntimeError("Exact frozen FirstRun v4 helper source required")
    spec = importlib.util.spec_from_file_location("wave22_fresh_first_v4_helpers", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


first = first_module()
Missing, Pending, Unknown = first.Missing, first.Pending, first.Unknown


def canonical_uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise Missing("Explicit canonical UUID required")
    return value


def fresh_paths(generation):
    generation = canonical_uuid(generation)
    prefix = ROOT / ".local" / ("wave22-shared-test-fresh-" + generation)
    return (
        Path(str(prefix) + ".json"),
        Path(str(prefix) + "-resource-profile.json"),
        Path(str(prefix) + "-resource-input.json"),
    )


def checked_fresh_material(raw, old, profile, readback, decision, *, marker, scope, at):
    """Bind Root's actual readback and explicit selection; metadata is never a host gate."""
    if type(raw) is not dict or set(raw) != INTENT_KEYS:
        raise Missing("Exact sixteen-field fresh-request intent required")
    generation = canonical_uuid(raw["generation"])
    source_generation = canonical_uuid(raw["source_generation"])
    if generation == source_generation:
        raise Missing("Fresh branch requires distinct new generation")
    if type(readback) is not dict or set(readback) != READBACK_KEYS:
        raise Missing("Exact sixteen-field actual saved-planned/no-start readback required")
    if type(decision) is not dict or set(decision) != DECISION_KEYS:
        raise Missing("Exact ten-field explicit fresh-branch decision required")
    if (
        raw["schema_version"] != "wave22-fresh-request-intent-v1"
        or readback["schema_version"] != "wave22-saved-planned-no-start-readback-v1"
        or decision["schema_version"] != "wave22-fresh-request-decision-v1"
        or any(v["marker"] != marker or v["scope"] != scope for v in (raw, readback, decision))
        or old.get("scope") != scope
        or raw["purpose"] != old.get("purpose")
        or any(v["source_generation"] != source_generation for v in (readback, decision))
        or any(
            v["source_checkpoint_sha256"] != raw["source_checkpoint_sha256"]
            for v in (readback, decision)
        )
        or decision["generation"] != generation
        or decision["readback_sha256"] != raw["readback_sha256"]
        or decision["operation"] != "create_distinct_formal_from_saved_unstarted_plan"
        or decision["old_saved_plan_and_promise_preserved"] is not True
        or any(type(v["reason"]) is not str or not v["reason"].strip() for v in (raw, decision))
    ):
        raise Missing("Exact Root selection/readback scope or purpose mismatch")
    selected = old.get("prospective_generation", {})
    receipts = old.get("receipts", {})
    if (
        old.get("schema_version") != "wave22-shared-test-v1"
        or selected.get("id") != source_generation
        or old.get("run_id") != str(uuid5(UUID(source_generation), "original:run"))
        or raw["build_id"] != old.get("build_id")
        or readback["build_id"] != raw["build_id"]
        or raw["sample_id"] != old.get("original_sample_id")
        or readback["request_id"] != old.get("request_id")
        or readback["run_id"] != old.get("run_id")
        or not {"run-plan", "promise"} <= receipts.keys()
        or "run-start" in receipts
        or "results" in receipts
        or "compute" in receipts
        or "run-start" in old.get("requests", {})
    ):
        raise Missing("Actual saved Plan/Promise without any submitted Start required")
    for name, label, status, operation, family in (
        ("run_current", "run-plan", "planned", "test.run.plan", "test_run"),
        (
            "request_current",
            "promise",
            "scheduled",
            "verification.schedule.promise",
            "verification_request",
        ),
    ):
        current, receipt = readback[name], receipts[label]
        if (
            type(current) is not dict
            or set(current) != {"id", "revision", "status"}
            or type(current["revision"]) is not int
            or current["revision"] < 1
            or current["status"] != status
            or current["id"] != receipt.get("subject_id")
            or current["revision"] != receipt.get("subject_revision")
            or receipt.get("operation") != operation
            or receipt.get("subject_type") != family
            or receipt.get("result", {}).get("id") != current["id"]
            or receipt.get("result", {}).get("revision") != current["revision"]
            or readback["plan_receipt_id" if label == "run-plan" else "promise_receipt_id"]
            != receipt.get("id")
        ):
            raise Missing("Exact actual saved Receipt and Current version mismatch")
        canonical_uuid(current["id"])
    if any(
        type(readback[name]) is not int or readback[name] != 0
        for name in ("actual_start_count", "resource_occupancy_count", "sample_usage_count")
    ):
        raise Missing("Exact zero actual Start, test occupancy and sample usage required")
    checked = first.aware_past(readback["checked_at"])
    plan = old["requests"]["run-plan"]["original"]["payload"]["execution_plan"]
    finish = datetime.fromisoformat(plan["window"]["finish"].replace("Z", "+00:00"))
    if not finish <= checked <= at:
        raise Missing("Actual old fixed window must have ended; never withdraw saved facts")
    if (
        type(profile) is not dict
        or set(profile) != {"tenant_id", "product_id", "issuer_key", "issuer_version", "decisions"}
        or profile["tenant_id"] != scope["tenant_id"]
        or profile["product_id"] != scope["product_id"]
        or profile["issuer_version"] != "v2"
    ):
        raise Missing("Actual full-scope first resource issuer ledger required")
    old_raw = old.get("resource_input")
    if not old_raw or old_raw["binding"]["run_id"] != old["run_id"]:
        raise Missing("Actual original resource export bound to old Run required")
    entries = [
        {"binding": old_raw["binding"], "resource": r["resource"], "decision": d}
        for r in old_raw["resources"]
        for d in r["facts"]
    ]
    if not entries or any(v not in profile["decisions"] for v in entries):
        raise Missing("Every original finite decision must remain in the full ledger")
    return generation


def retained_resource_profile(original, raw, scope):
    from pdos_next.test_resource_bootstrap import _profile

    profile = deepcopy(original)
    if (profile["tenant_id"], profile["product_id"], profile["issuer_version"]) != (
        scope["tenant_id"],
        scope["product_id"],
        "v2",
    ):
        raise Missing("Same original scope/key/version ledger required")
    profile["decisions"] += [
        {"binding": raw["binding"], "resource": r["resource"], "decision": d}
        for r in raw["resources"]
        for d in r["facts"]
    ]
    _profile(
        {k: profile[k] for k in ("tenant_id", "product_id", "decisions")}, strict_material=True
    )
    return profile


CHECKPOINT_MAX_BYTES = 8 * 1024 * 1024


def checkpoint_json(path):
    """Only internal complete history gets the larger finite private-file bound."""
    return first.private_json(path, limit=CHECKPOINT_MAX_BYTES)


def checkpoint_fits(value):
    encoded = json.dumps(value, ensure_ascii=False, indent=2, default=first.helpers().encode) + "\n"
    if len(encoded.encode()) > CHECKPOINT_MAX_BYTES:
        raise Missing("Complete checkpoint exceeds fixed 8 MiB bound; retain original")


class SharedFreshRequest(first.SharedTest):
    def __init__(
        self, marker, *, generation, material=None, confirm=None, review_digest=None, recover=None
    ):
        sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
        from local_environment import read_state, verified

        self.marker, self.read_state, self.verified = str(marker), read_state, verified
        self.confirm, self.review_digest, self.recover = confirm, review_digest, recover
        self.confirm_used = self.recover_used = False
        self.h = first.helpers()
        target = self.target()
        self.namespace = canonical_uuid(generation)
        self.checkpoint_path, self.resource_profile_path, self.resource_input_path = fresh_paths(
            generation
        )
        prior = checkpoint_json(self.checkpoint_path) if self.checkpoint_path.exists() else None
        raw = (
            first.private_json(material)
            if material is not None
            else deepcopy(prior.get("selection") if prior else None)
        )
        if raw is None or raw.get("generation") != generation:
            raise Missing("Explicit fixed fresh-request intent material required")
        self.foundation = first.foundation_contract(
            first.private_json(first.FOUNDATION), self.marker
        )
        self.foundation_sha = first.digest_file(first.FOUNDATION)
        self.foundation_binding_sha = first.build_foundation_binding(self.foundation, self.marker)
        build_raw = first.private_json(first.BUILD)
        self.build = first.build_contract(build_raw, self.foundation, self.foundation_binding_sha)
        self.build_sha, self.build_case_id = first.digest_file(first.BUILD), build_raw["case_id"]
        if target["preview_tenant_id"] != self.foundation["tenant_id"]:
            raise Missing("Actual marked target tenant mismatch")
        old_paths = first.generation_paths(canonical_uuid(raw["source_generation"]))
        self.first_checkpoint, self.first_profile_path, self.first_resource_input_path = old_paths
        self.first_data = first.private_json(self.first_checkpoint)
        original = first.SharedTest.__new__(first.SharedTest)
        original.data = self.first_data
        original._origin_files(self.first_data["prospective_generation"])
        self.first_profile = first.private_json(self.first_profile_path)
        self.first_profile_sha = first.digest_file(self.first_profile_path)
        readback, readback_sha = first.evidence_file(raw["readback_file"])
        decision, decision_sha = first.evidence_file(raw["decision_file"])
        self.selection = raw
        if (
            first.digest_file(self.first_checkpoint) != raw["source_checkpoint_sha256"]
            or first.digest_file(self.first_resource_input_path)
            != raw["source_resource_input_sha256"]
            or self.first_profile_sha != raw["source_resource_profile_sha256"]
            or first.private_json(self.first_resource_input_path)
            != self.first_data.get("resource_input")
            or readback_sha != raw["readback_sha256"]
            or decision_sha != raw["decision_sha256"]
        ):
            raise Missing("Exact actual old checkpoint/export/readback hashes required")
        checked_fresh_material(
            raw,
            self.first_data,
            self.first_profile,
            readback,
            decision,
            marker=self.marker,
            scope=self.foundation["scope"],
            at=datetime.now(UTC),
        )
        for label, role, operation, family in (
            ("run-plan", "observer", "test.run.plan", "test_run"),
            ("promise", "observer", "verification.schedule.promise", "verification_request"),
        ):
            self.check_receipt(self.first_data["receipts"][label], role, operation, family)
        binding = {
            "schema_version": "wave22-shared-fresh-request-v1",
            "marker": self.marker,
            "generation": generation,
            "scope": self.foundation["scope"],
            "foundation_sha256": self.foundation_sha,
            "build_sha256": self.build_sha,
            "build_case_id": self.build_case_id,
            "build_foundation_sha256": self.foundation_binding_sha,
            "selection": raw,
            "origin_archive": self.first_data,
        }
        if prior is not None:
            if any(prior.get(k) != v for k, v in binding.items()):
                raise Missing("Fresh namespace original selection/archive changed")
            self.data = prior
        else:
            self.data = {
                **binding,
                "purpose": raw["purpose"],
                "build_id": raw["build_id"],
                "case_id": generation,
                "request_id": str(uuid5(UUID(generation), "fresh:formal")),
                "preparation_request_id": str(uuid5(UUID(generation), "fresh:preparation")),
                "run_id": str(uuid5(UUID(generation), "fresh:run")),
                "test_equipment_id": self.first_data["test_equipment_id"],
                "original_sample_id": raw["sample_id"],
                "followup_sample_id": self.first_data["followup_sample_id"],
                "test_publication": deepcopy(self.first_data["test_publication"]),
                "publication_receipt": deepcopy(self.first_data["publication_receipt"]),
                "requests": {},
                "receipts": {},
                "events": {},
                "phase": "allocated_new_branch_old_saved_plan_preserved_no_start",
            }
            self.save()
        if (
            self.data["request_id"] == self.first_data["request_id"]
            or self.data["run_id"] == self.first_data["run_id"]
        ):
            raise Missing("Fresh Formal/Run cannot reuse saved old logical identity")

    def origin_guard(self):
        raw = self.selection
        original = first.SharedTest.__new__(first.SharedTest)
        original.data = first.private_json(self.first_checkpoint)
        original._origin_files(original.data["prospective_generation"])
        if (
            first.digest_file(self.first_checkpoint) != raw["source_checkpoint_sha256"]
            or original.data != self.first_data
            or first.digest_file(self.first_profile_path) != raw["source_resource_profile_sha256"]
            or first.digest_file(self.first_resource_input_path)
            != raw["source_resource_input_sha256"]
            or first.digest_file(first.FOUNDATION) != self.foundation_sha
            or first.digest_file(first.BUILD) != self.build_sha
            or first.evidence_file(raw["readback_file"])[1] != raw["readback_sha256"]
            or first.evidence_file(raw["decision_file"])[1] != raw["decision_sha256"]
        ):
            raise Missing("Original actual files changed; no hidden reuse or replacement")

    def key(self, label, role="observer"):
        return f"wave22-fresh-{self.namespace}-{role}-{label}"

    def command_id(self, label, role):
        return str(uuid5(UUID(self.namespace), role + ":" + label))

    def save(self):
        if self.checkpoint_path.is_symlink():
            raise Missing("New fresh-request checkpoint symlink refused")
        checkpoint_fits(self.data)
        self.h.private_write(self.checkpoint_path, self.data)

    def request(self, role, method, path, *, body=None, params=None):
        self.origin_guard()
        return super().request(role, method, path, body=body, params=params)

    def resource_binding(self, plan):
        self.origin_guard()
        return super().resource_binding(plan)

    def resources(self, *, window_start=None, window_end=None, valid_until=None):
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan

        if "accept" not in self.data["receipts"]:
            raise Missing("Actual Offer/Accept required before fixed resources")
        self.publication()
        if "resource_input" not in self.data:
            if not all((window_start, window_end, valid_until)):
                raise Missing(
                    "Explicit future execution window and finite publication expiry required"
                )
            at = datetime.now(UTC)
            expiry = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
            plan = ExecutionPlan.model_validate(
                {
                    "window": {
                        "start": window_start,
                        "finish": window_end,
                        "original_timezone": "UTC",
                    },
                    "executor_id": self.actor("observer"),
                    "equipment": self.published("equipment"),
                    "calibration": self.published("calibration"),
                    "environment": self.published("environment"),
                    "conditions": self.published("conditions"),
                    "resource_fact_id": str(
                        uuid5(
                            UUID(self.namespace),
                            "fresh:resource-selection-placeholder",
                        )
                    ),
                    "expected_resource_fact_revision": 1,
                }
            )
            if (
                expiry.utcoffset() is None
                or not at + timedelta(minutes=5) <= plan.window.start < plan.window.finish < expiry
                or expiry > datetime.fromisoformat(self.foundation["bootstrap_expires_at"])
            ):
                raise Missing(
                    "Explicit future plan needs >=5 minutes preparation horizon "
                    "and finite scope expiry"
                )
            binding = self.resource_binding(plan)
            original_resources = self.first_data.get("resource_input", {}).get("resources", [])
            resources = []
            for kind, identity, kinds in (
                ("equipment", self.data["test_equipment_id"], ("acceptance", "calibration")),
                ("person", self.actor("observer"), ("qualification",)),
            ):
                physical = [
                    r
                    for r in original_resources
                    if r["resource"]["id"] == identity and r["resource"]["kind"] == kind
                ]
                if len(physical) != 1:
                    raise Missing("Exact original physical resource mirror required")
                physical = physical[0]
                resources.append(
                    {
                        "resource": deepcopy(physical["resource"]),
                        "purposes": [self.data["purpose"]],
                        "operation_ids": ["test.run.start"],
                        "lifecycle": physical["lifecycle"],
                        "maintenance": deepcopy(physical["maintenance"]),
                        "capacity": physical["capacity"],
                        "calendar": deepcopy(physical["calendar"]),
                        "calendar_sources": self.published("resource_sources"),
                        "external_occupancies_complete": True,
                        "sources": self.published("resource_sources"),
                        "facts": [
                            {
                                "kind": k,
                                "purpose": self.data["purpose"],
                                "operation_id": "test.run.start",
                                "status": "accepted",
                                "valid_from": at.isoformat(),
                                "valid_until": expiry.isoformat(),
                                "named_decision_id": str(
                                    uuid5(
                                        UUID(self.namespace),
                                        "fresh:" + kind + ":" + k,
                                    )
                                ),
                                "actor_id": self.actor("observer"),
                                "sources": self.published("resource_sources"),
                            }
                            for k in kinds
                        ],
                    }
                )
            raw = TestResourceFactInput.model_validate(
                {
                    "binding": binding,
                    "external_id": self.key("resource"),
                    "valid_from": at.isoformat(),
                    "valid_until": expiry.isoformat(),
                    "resources": resources,
                    "required_uses": [{"resource": r["resource"], "units": "1"} for r in resources],
                    "requirements_sources": self.published("requirements_sources"),
                    "sources": self.published("resource_sources"),
                    "reason": (
                        "Prospective exact local synthetic trusted publication; "
                        "no production or instrument claim"
                    ),
                }
            ).model_dump(mode="json")
            self.data["execution_plan"] = plan.model_dump(mode="json")
            self.data["resource_input"] = raw
            self.save()
        else:
            plan = self.data["execution_plan"]["window"]
            for provided, old in (
                (window_start, plan["start"]),
                (window_end, plan["finish"]),
                (valid_until, self.data["resource_input"]["valid_until"]),
            ):
                if provided and datetime.fromisoformat(
                    provided.replace("Z", "+00:00")
                ) != datetime.fromisoformat(old.replace("Z", "+00:00")):
                    raise Missing("Original window/publication cannot change")
        raw = self.data["resource_input"]
        original_profile = first.private_json(self.first_profile_path)
        if (
            first.digest_file(self.first_profile_path) != self.first_profile_sha
            or original_profile != self.first_profile
        ):
            raise Missing("Actual first-generation finite host profile changed")
        profile = retained_resource_profile(original_profile, raw, self.foundation["scope"])
        for path, value in ((self.resource_profile_path, profile), (self.resource_input_path, raw)):
            if path.exists() or path.is_symlink():
                if self.h.canonical(first.private_json(path)) != self.h.canonical(value):
                    raise Missing("Existing exact finite resource export differs")
            else:
                self.h.private_write(path, value)
        self.data["phase"] = "resource_exports_not_imported_or_installed"
        self.save()
        return {
            "resource_profile": str(self.resource_profile_path.relative_to(ROOT)),
            "resource_input": str(self.resource_input_path.relative_to(ROOT)),
            "requires_root_trusted_import_and_api_plural_reload": True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=(
            "allocate",
            "handoff",
            "resources",
            "plan",
            "promise",
            "start",
            "report",
            "compute",
            "readback",
        ),
    )
    parser.add_argument("--marker", required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--intent", type=Path)
    parser.add_argument("--material", type=Path)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--confirm")
    choice.add_argument("--recover")
    parser.add_argument("--review-digest")
    for name in (
        "offer-at",
        "accept-at",
        "occurred-at",
        "window-start",
        "window-end",
        "valid-until",
    ):
        parser.add_argument("--" + name)
    tool = None
    try:
        args = parser.parse_args()
        tool = SharedFreshRequest(
            args.marker,
            generation=args.generation,
            material=args.intent,
            confirm=args.confirm,
            review_digest=args.review_digest,
            recover=args.recover,
        )
        phases = {
            "allocate": (
                lambda: {
                    "state": tool.data["phase"],
                    "generation": args.generation,
                    "checkpoint": str(tool.checkpoint_path.relative_to(ROOT)),
                    "old_saved_plan_and_promise_preserved": True,
                },
                {},
            ),
            "handoff": (tool.handoff, {"offer_at": args.offer_at, "accept_at": args.accept_at}),
            "resources": (
                tool.resources,
                {
                    "window_start": args.window_start,
                    "window_end": args.window_end,
                    "valid_until": args.valid_until,
                },
            ),
            "plan": (tool.plan, {}),
            "promise": (tool.promise, {"occurred_at": args.occurred_at}),
            "start": (tool.start, {"occurred_at": args.occurred_at}),
            "report": (tool.report, {"material": args.material}),
            "compute": (tool.compute, {}),
            "readback": (tool.readback, {}),
        }
        call, kwargs = phases[args.phase]
        result = call(**kwargs)
        print(
            json.dumps(
                result
                or {
                    "phase": tool.data["phase"],
                    "generation": args.generation,
                    "receipts_saved": len(tool.data["receipts"]),
                    "effectiveness": None,
                    "close": False,
                },
                ensure_ascii=False,
            )
        )
    except Pending as waiting:
        value = tool.data["requests"][waiting.label]
        print(
            json.dumps(
                {
                    "state": "awaiting_confirmation",
                    "label": waiting.label,
                    "tier": value["tier"],
                    "review_digest": value["review_digest"],
                    "review": value["preview"]["review"],
                    "expires_at": value["preview"].get("expires_at"),
                },
                ensure_ascii=False,
            )
        )
        return 2
    except Unknown as error:
        print(json.dumps({"state": "UNKNOWN", "label": error.label, "new_key_created": False}))
        return 3
    except Exception as error:
        status, code = getattr(error, "status", None), getattr(error, "code", None)
        print(
            json.dumps(
                {
                    "state": "blocked_preserve_original",
                    "error_type": type(error).__name__,
                    **({"status": status, "code": code} if status else {}),
                }
            )
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
