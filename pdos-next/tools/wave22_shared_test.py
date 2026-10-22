"""Root-run original shared Observer Run; inert until an explicit phase.

No Demo instance, old private seed, profile installation or automatic approval.
The second real Run and independent review remain separate explicit handoffs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import stat
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5


def layout_root(source):
    source = Path(source)
    if source.name != "wave22_shared_test.py":
        raise RuntimeError("Unexpected shared-test filename")
    if source.parent.name == "tools":
        return source.parent.parent
    if source.parent.name == "wave22-test-staged" and source.parent.parent.name == ".local":
        return source.parents[2]
    if (
        source.parent.name in {"v2", "v3", "v4"}
        and source.parent.parent.name == "wave22-test-staged"
        and source.parents[2].name == ".local"
    ):
        return source.parents[3]
    raise RuntimeError("Unexpected shared-test layout")


ROOT = layout_root(Path(__file__).resolve())
FOUNDATION = ROOT / ".local/wave21-shared-case.json"
BUILD = ROOT / ".local/wave22-build-staged/checkpoint.json"
CHECKPOINT = ROOT / ".local/wave22-shared-test.json"
RESOURCE_PROFILE = ROOT / ".local/wave22-shared-test-resource-profile.json"
RESOURCE_INPUT = ROOT / ".local/wave22-shared-test-resource-input.json"
ROLES = ("maker", "observer", "independent_reviewer")
PHASES = (
    "prospective-plan",
    "publication",
    "handoff",
    "resources",
    "plan",
    "promise",
    "start",
    "report",
    "compute",
    "readback",
)

PROSPECTIVE_KEYS = {
    "schema_version",
    "generation",
    "origin_checkpoint_sha256",
    "old_resource_input_sha256",
    "old_resource_profile_sha256",
    "readback_file",
    "readback_sha256",
    "decision_file",
    "decision_sha256",
    "intent_recorded_at",
    "window",
    "valid_until",
    "issuer_key",
    "issuer_version",
    "reason",
}
HANDOFF_LABELS = {
    "preparation",
    "formal",
    "method",
    "actual-method",
    "event-handoff",
    "offer",
    "accept",
}


def value_sha(value):
    return hashlib.sha256(helpers().canonical(value).encode()).hexdigest()


def generation_paths(generation):
    value = str(UUID(generation))
    return (
        ROOT / f".local/wave22-shared-test-generation-{value}.json",
        ROOT / f".local/wave22-shared-test-resource-profile-{value}.json",
        ROOT / f".local/wave22-shared-test-resource-input-{value}.json",
    )


def evidence_file(path):
    """Bounded public Root evidence, not an authorization or a private payload."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT.parent / path
    permitted = ROOT.parent / "docs/reports/evidence/pdos-next-wave22-20261003"
    if path.is_symlink() or path.parent.resolve() != permitted.resolve():
        raise Missing("Exact Wave22 Root evidence path required")
    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_size > 200_000:
        raise Missing("Bounded regular Root evidence required")
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def checked_prospective_material(raw, old, profile, readback, decision, *, at):
    """Only allocate a new unsent intent after Root's exact zero-write observations."""
    from pdos_next.contracts import PAYLOADS, Command
    from pdos_next.domain.test_resources.schemas import TestResourceFactInput
    from pdos_next.domain.verification_launch.schemas import ExecutionPlan

    if type(raw) is not dict or set(raw) != PROSPECTIVE_KEYS:
        raise Missing("Exact explicit prospective Plan material required")
    if raw["schema_version"] != "wave22-prospective-plan-v1":
        raise Missing("Unknown prospective Plan material schema")
    generation = str(UUID(raw["generation"]))
    UUID(old["case_id"])
    proposal = old.get("requests", {}).get("run-plan")
    if (
        not proposal
        or proposal.get("state") != "awaiting_confirmation"
        or "run-plan" in old.get("receipts", {})
        or set(old.get("requests", {})) - (HANDOFF_LABELS | {"run-plan"})
        or set(old.get("receipts", {})) - HANDOFF_LABELS
        or not HANDOFF_LABELS <= set(old.get("receipts", {}))
        or not HANDOFF_LABELS <= set(old.get("requests", {}))
        or set(old.get("events", {})) != {"handoff"}
        or "result_readback" in old
        or "capture" in old
        or "report_material" in old
    ):
        raise Missing("Only a known never-sent prepared first Plan may be superseded")
    command = proposal["original"]
    body = proposal["body"]
    normalized_body = Command.model_validate(body).model_dump(mode="json")
    normalized_body["payload"] = (
        PAYLOADS["test.run.plan"]
        .model_validate(body["payload"])
        .model_dump(
            mode="json", exclude_none=True, exclude={"confirmation_token", "approval_token"}
        )
    )
    if normalized_body != Command.model_validate(command).model_dump(mode="json"):
        raise Missing("Original prepared Plan must differ only by its original actual proof token")
    if (
        command.get("operation") != "test.run.plan"
        or command.get("payload", {}).get("run_id") != old["run_id"]
        or body.get("payload", {}).get("run_id") != old["run_id"]
        or body.get("payload", {}).get("confirmation_token") is None
        or proposal.get("tier") != "T1"
        or proposal.get("preview", {}).get("command") != body
        or command.get("command_id") != readback.get("original_command_id")
        or command.get("idempotency_key") != readback.get("original_key")
        or value_sha(body) != readback.get("original_body_sha256")
        or readback.get("status") != "PASS"
        or readback.get("marker") != old["marker"]
        or readback.get("target") != "127.0.0.1:62513/pdos_test"
        or any(
            type(readback.get(k)) is not int or readback[k] != 0
            for k in (
                "business_writes",
                "action_receipts_count",
                "request_keys_count",
                "verification_run_identities_count",
                "verification_run_versions_count",
                "verification_current_runs_count",
            )
        )
        or readback.get("prepared_confirmation", {}).get("consumed") is not False
        or readback["prepared_confirmation"].get("exact_actor_and_product") is not True
        or readback.get("receipt_fact_id") != body["payload"]["execution_plan"]["resource_fact_id"]
        or readback.get("fixed_window") != body["payload"]["execution_plan"]["window"]
    ):
        raise Missing("Root's exact unsubmitted Plan/zero-write proof does not match")
    if (
        decision.get("status") != "WITHDRAWN_UNSUBMITTED_PROPOSAL"
        or decision.get("original_command_id") != command["command_id"]
        or decision.get("original_key") != command["idempotency_key"]
        or decision.get("readback_sha256") != raw["readback_sha256"]
        or decision.get("readback_proof") != Path(raw["readback_file"]).name
        or decision.get("original_requests_and_token_retained") is not True
        or decision.get("new_prospective_window_requires_new_intent_and_receipt") is not True
        or decision.get("checkpoint_changed") is not False
        or decision.get("fact1_withdrawn_or_deleted") is not False
        or decision.get("new_test_start") is not False
    ):
        raise Missing("Explicit Root withdrawal of only the unsubmitted proposal required")
    recorded = aware_past(raw["intent_recorded_at"])
    proof_at = aware_past(readback["recorded_at"])
    decision_at = aware_past(decision["recorded_at"])
    if not proof_at <= decision_at <= recorded <= at:
        raise Missing("Observed proof/decision/new-intent clocks must be ordered")
    previous = TestResourceFactInput.model_validate(old["resource_input"])
    plan = ExecutionPlan.model_validate(
        {
            **old["execution_plan"],
            "window": raw["window"],
            "resource_fact_id": str(
                uuid5(UUID(generation), "original:resource-selection-placeholder")
            ),
            "expected_resource_fact_revision": 1,
        }
    )
    expiry = datetime.fromisoformat(raw["valid_until"].replace("Z", "+00:00"))
    if (
        plan.window.original_timezone != "UTC"
        or expiry.utcoffset() is None
        or plan.window.start < recorded + timedelta(minutes=15)
        or not at < plan.window.start < plan.window.finish < expiry
        or plan.window == previous.binding.window
        or previous.binding.run_id != UUID(old["run_id"])
        or profile.get("tenant_id") != old["scope"]["tenant_id"]
        or profile.get("product_id") != old["scope"]["product_id"]
        or raw["issuer_key"] != profile.get("issuer_key")
        or profile.get("issuer_version") != "v1"
        or raw["issuer_version"] != "v2"
        or type(raw["reason"]) is not str
        or not raw["reason"].strip()
        or len(raw["reason"]) > 2000
    ):
        raise Missing("New prospective window/finite named host issuer is invalid")
    new_run = str(uuid5(UUID(generation), "original:run"))
    if new_run == old["run_id"] or generation == old["case_id"]:
        raise Missing("New generation must allocate its own logical Run")
    expected_ledger = [
        {
            "binding": previous.binding.model_dump(mode="json"),
            "resource": r.resource.model_dump(mode="json"),
            "decision": d.model_dump(mode="json"),
        }
        for r in previous.resources
        for d in r.facts
    ]
    if profile.get("decisions") != expected_ledger:
        raise Missing("Whole exact old finite ledger required, not a replacement profile")
    return generation, new_run, plan.model_dump(mode="json")


class Missing(RuntimeError):
    pass


class Pending(RuntimeError):
    def __init__(self, label):
        self.label = label
        super().__init__("Exact prepared command awaits named confirmation")


class Unknown(RuntimeError):
    def __init__(self, label):
        self.label = label
        super().__init__("Original request retained; explicit recovery required")


def helpers():
    path = ROOT / "tools/wave15_seed.py"
    spec = importlib.util.spec_from_file_location("wave22_test_pure_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_foundation_binding(foundation, marker):
    """Use the actual Build owner's normalized material, not the private-file SHA."""
    path = ROOT / "tools/wave22_shared_build.py"
    if not path.is_file():
        path = ROOT / ".local/wave22-build-staged/wave22_shared_build.py"
    if not path.is_file() or path.is_symlink():
        raise Missing("Actual Build normalization owner unavailable")
    spec = importlib.util.spec_from_file_location("wave22_test_build_binding", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sha(module.foundation_material(foundation, marker))


def private_json(path, *, limit=2_000_000):
    path = Path(path)
    value = path.lstat()
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_uid != os.getuid()
        or value.st_size > limit
    ):
        raise Missing("Owned bounded regular 0600 actual material required")
    return json.loads(path.read_text())


def aware_past(value):
    if type(value) is not str:
        raise Missing("Explicit observed ISO clock required")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Missing("Observed clock malformed") from None
    if at.utcoffset() != timedelta(0) or at > datetime.now(UTC):
        raise Missing("Actual events require explicit nonfuture UTC; no offset substitution")
    return at


def promise_start(value, window):
    """A named commitment targets the fixed future start; it is not an actual Start."""
    if type(value) is not str:
        raise Missing("Explicit fixed future Promise ISO clock required")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        first = datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
        finish = datetime.fromisoformat(window["finish"].replace("Z", "+00:00"))
    except (TypeError, ValueError, KeyError):
        raise Missing("Fixed complete Promise window required") from None
    if (
        at.utcoffset() != timedelta(0)
        or first.utcoffset() != timedelta(0)
        or finish.utcoffset() != timedelta(0)
        or window.get("original_timezone") != "UTC"
        or at != first
        or at < datetime.now(UTC)
        or finish <= first
    ):
        raise Missing("Promise must target the exact fixed future window start")
    return at


def foundation_contract(value, marker):
    if (
        value.get("schema_version") != "wave21-shared-foundation-v1"
        or value.get("phase") != "foundation_saved_not_build_started"
        or value.get("marker") != marker
        or value.get("visibility") != "product"
        or set(value.get("actors", {})) != set(ROLES)
        or value.get("scope")
        != {key: value.get(key) for key in ("tenant_id", "product_id", "project_id")}
        or len({UUID(row["id"]) for row in value["actors"].values()}) != 3
    ):
        raise Missing("Actual complete three-human Foundation required")
    for role in ROLES:
        row = value.get("readback", {}).get(role, {})
        if (
            row.get("shared_objects") != 6
            or not row.get("stored_content_hash")
            or not row.get("raw_text_sha256")
        ):
            raise Missing("Actual three-actor shared readback required")
    for label in (
        "product",
        "native-source",
        "definition",
        "project",
        "bom",
        "engineering",
        "manufacturing",
    ):
        receipt = value.get("receipts", {}).get(label)
        if (
            not receipt
            or type(receipt.get("subject_revision")) is not int
            or receipt["subject_revision"] < 1
        ):
            raise Missing("Actual Foundation receipt missing")
        UUID(receipt["id"])
        UUID(receipt["subject_id"])
    return value


def build_contract(value, foundation, foundation_binding_sha):
    current = value.get("continuation", {})
    if (
        value.get("schema_version") != "wave22-shared-build-v1"
        or value.get("phase") != "two_A_readiness_facts_saved_no_handoff_or_test_run"
        or value.get("marker") != foundation["marker"]
        or value.get("foundation_sha256") != foundation_binding_sha
        or current.get("schema_version") != "wave22-shared-build-continuation-v1"
        or current.get("state") != "readback_saved_requires_consumer_recheck"
        or current.get("scope") != foundation["scope"]
        or current.get("purpose") != foundation["purpose"]
        or current.get("configuration") != foundation["configuration"]
        or current.get("maker_id") != foundation["actors"]["maker"]["id"]
        or current.get("synthetic_only") is not True
        or current.get("test_qualification") is not None
        or current.get("professional_review") is not None
        or current.get("effectiveness") is not None
        or current.get("close") is not False
    ):
        raise Missing("Actual two-Sample Build continuation required")
    if type(value.get("case_id")) is not str:
        raise Missing("Actual independently allocated Build case required")
    try:
        UUID(value["case_id"])
    except ValueError:
        raise Missing("Actual independently allocated Build case required") from None
    samples = current.get("samples", [])
    if len(samples) != 2 or len({row["id"] for row in samples}) != 2:
        raise Missing("Two distinct actual A samples required")
    for sample in samples:
        if (
            sample.get("cavity") != "A"
            or sample.get("purpose_availability") != "ready"
            or not sample.get("readiness")
        ):
            raise Missing("Purpose-bound actual A readiness required")
    return current


class SharedTest:
    def __init__(self, marker, *, confirm=None, review_digest=None, recover=None, generation=None):
        sys.path.insert(0, str(ROOT / "server"))
        sys.path.insert(0, str(ROOT / "tools"))
        from local_environment import read_state, verified

        self.marker, self.read_state, self.verified = str(marker), read_state, verified
        self.confirm, self.review_digest, self.recover = confirm, review_digest, recover
        self.confirm_used = self.recover_used = False
        self.generation = str(UUID(generation)) if generation is not None else None
        self.checkpoint_path, self.resource_profile_path, self.resource_input_path = (
            generation_paths(self.generation)
            if self.generation
            else (CHECKPOINT, RESOURCE_PROFILE, RESOURCE_INPUT)
        )
        self.h = helpers()
        state = self.target()
        self.foundation = foundation_contract(private_json(FOUNDATION), self.marker)
        self.foundation_sha = digest_file(FOUNDATION)
        self.foundation_binding_sha = build_foundation_binding(self.foundation, self.marker)
        build_checkpoint = private_json(BUILD)
        self.build = build_contract(build_checkpoint, self.foundation, self.foundation_binding_sha)
        self.build_case_id = build_checkpoint["case_id"]
        self.build_sha = digest_file(BUILD)
        if self.foundation["tenant_id"] != state["preview_tenant_id"]:
            raise Missing("Actual target tenant mismatch")
        checkpoint = self.checkpoint_path
        if checkpoint.exists() or checkpoint.is_symlink():
            self.data = private_json(checkpoint)
            if (
                self.data.get("schema_version") != "wave22-shared-test-v1"
                or self.data.get("marker") != self.marker
                or self.data.get("foundation_sha256") != self.foundation_sha
                or self.data.get("build_sha256") != self.build_sha
                or self.data.get("build_case_id") != self.build_case_id
                or self.data.get("build_foundation_sha256") != self.foundation_binding_sha
                or self.data.get("scope") != self.foundation["scope"]
            ):
                raise Missing("Saved test scope/input changed; no replacement intent")
            saved_generation = self.data.get("prospective_generation")
            if self.generation is not None:
                if not saved_generation or saved_generation.get("id") != self.generation:
                    raise Missing("Exact explicitly selected prospective generation required")
                self._origin_files(saved_generation)
            elif saved_generation is not None:
                raise Missing("Prospective generation cannot replace the original checkpoint")
        else:
            if self.generation is not None:
                raise Missing("Create the explicit prospective generation before its operations")
            case = UUID(self.foundation["case_id"])
            self.data = {
                "schema_version": "wave22-shared-test-v1",
                "marker": self.marker,
                "foundation_sha256": self.foundation_sha,
                "build_sha256": self.build_sha,
                "build_case_id": self.build_case_id,
                "build_foundation_sha256": self.foundation_binding_sha,
                "scope": self.foundation["scope"],
                "case_id": str(case),
                "purpose": self.foundation["purpose"],
                "build_id": self.build["build"]["id"],
                "preparation_request_id": str(uuid5(case, "original:preparation")),
                "request_id": str(uuid5(case, "original:formal")),
                "run_id": str(uuid5(case, "original:run")),
                "test_equipment_id": str(uuid5(case, "shared-test-equipment")),
                "original_sample_id": self.build["samples"][0]["id"],
                "followup_sample_id": self.build["samples"][1]["id"],
                "requests": {},
                "receipts": {},
                "events": {},
                "phase": "allocated_not_run",
            }
            self.save()

    def target(self):
        state = self.verified(self.read_state())
        if state["port"] != 62513 or str(state["marker"]) != self.marker:
            raise Missing("Exact marked62513 required; no environment fallback")
        return state

    @property
    def product(self):
        return self.foundation["product_id"]

    def actor(self, role):
        if role not in {"maker", "observer"}:
            raise Missing("Independent reviewer cannot participate in this original Run")
        return self.foundation["actors"][role]["id"]

    def key(self, label, role="observer"):
        return f"wave22-{self.command_namespace(label)}-{role}-{label}"

    def command_namespace(self, label):
        selected = self.data.get("prospective_generation")
        if selected and label not in selected["inherited_labels"]:
            return selected["id"]
        return self.foundation["case_id"]

    def command_id(self, label, role):
        return str(uuid5(UUID(self.command_namespace(label)), role + ":" + label))

    def _origin_files(self, selected):
        origin = private_json(CHECKPOINT)
        material = selected["material"]
        generation = str(UUID(selected["id"]))
        expected_plan = {
            **origin["execution_plan"],
            "window": material["window"],
            "resource_fact_id": str(
                uuid5(UUID(generation), "original:resource-selection-placeholder")
            ),
            "expected_resource_fact_revision": 1,
        }
        # Parse to the actual canonical DTO representation, including UTC spelling.
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan

        expected_plan = ExecutionPlan.model_validate(expected_plan).model_dump(mode="json")
        if (
            digest_file(CHECKPOINT) != material["origin_checkpoint_sha256"]
            or digest_file(RESOURCE_PROFILE) != material["old_resource_profile_sha256"]
            or digest_file(RESOURCE_INPUT) != material["old_resource_input_sha256"]
            or value_sha(origin) != selected["origin_material_sha256"]
            or self.data.get("origin_archive") != origin
            or selected["old_profile"] != private_json(RESOURCE_PROFILE)
            or selected["material_sha256"] != value_sha(material)
            or material["generation"] != generation
            or self.data.get("run_id") != str(uuid5(UUID(generation), "original:run"))
            or self.data.get("execution_plan") != expected_plan
            or selected.get("inherited_labels") != sorted(HANDOFF_LABELS)
            or any(self.data["requests"].get(k) != origin["requests"][k] for k in HANDOFF_LABELS)
            or any(self.data["receipts"].get(k) != origin["receipts"][k] for k in HANDOFF_LABELS)
            or self.data["events"].get("handoff") != origin["events"]["handoff"]
            or any(
                self.data.get(k) != origin[k]
                for k in (
                    "case_id",
                    "scope",
                    "purpose",
                    "build_id",
                    "request_id",
                    "preparation_request_id",
                    "test_equipment_id",
                    "original_sample_id",
                    "followup_sample_id",
                    "sample_ref",
                    "coverage",
                )
            )
        ):
            raise Missing("Complete original checkpoint/profile/input must remain unchanged")
        for field in ("readback", "decision"):
            _, sha = evidence_file(selected["material"][field + "_file"])
            if sha != selected["material"][field + "_sha256"]:
                raise Missing("Root's original zero-write evidence changed")

    def prospective_plan(self, *, material):
        """Create a separate intent only; old active slot and every source file are untouched."""
        if getattr(self, "generation", None) is not None or self.data.get("prospective_generation"):
            raise Missing("A new proposal must explicitly branch from the untouched original")
        if material is None:
            raise Missing("Explicit owned 0600 prospective Plan material required")
        raw = private_json(material)
        old = deepcopy(self.data)
        if (
            digest_file(CHECKPOINT) != raw.get("origin_checkpoint_sha256")
            or private_json(CHECKPOINT) != old
            or digest_file(RESOURCE_INPUT) != raw.get("old_resource_input_sha256")
            or private_json(RESOURCE_INPUT) != old.get("resource_input")
            or digest_file(RESOURCE_PROFILE) != raw.get("old_resource_profile_sha256")
        ):
            raise Missing("Exact original file hashes and resource publication required")
        profile = private_json(RESOURCE_PROFILE)
        readback, readback_sha = evidence_file(raw["readback_file"])
        decision, decision_sha = evidence_file(raw["decision_file"])
        if readback_sha != raw["readback_sha256"] or decision_sha != raw["decision_sha256"]:
            raise Missing("Root's actual zero-write and withdrawal evidence must match")
        generation, run_id, plan = checked_prospective_material(
            raw, old, profile, readback, decision, at=datetime.now(UTC)
        )
        if datetime.fromisoformat(
            raw["valid_until"].replace("Z", "+00:00")
        ) > datetime.fromisoformat(self.foundation["bootstrap_expires_at"]):
            raise Missing("New scope expiry cannot exceed original actual Foundation lifetime")
        paths = generation_paths(generation)
        new = deepcopy(old)
        new["origin_archive"] = old
        new["prospective_generation"] = {
            "id": generation,
            "material": raw,
            "material_sha256": value_sha(raw),
            "origin_material_sha256": value_sha(old),
            "old_profile": profile,
            "inherited_labels": sorted(HANDOFF_LABELS),
            "original_plan_not_submitted": True,
            "fact1_preserved": True,
        }
        del new["requests"]["run-plan"]
        new["run_id"] = run_id
        new["execution_plan"] = plan
        for field in ("resource_input", "installed_execution_plan"):
            new.pop(field, None)
        new["phase"] = "new_prospective_intent_no_resource_fact_or_plan"
        if paths[0].exists() or paths[0].is_symlink():
            previous = private_json(paths[0])
            if previous.get("prospective_generation") != new["prospective_generation"]:
                raise Missing("Existing generation material cannot be replaced")
            # Resume only the selected actual state; never overwrite progress or originals.
            if previous.get("origin_archive") != old or previous.get("run_id") != run_id:
                raise Missing("Existing generation origin or logical Run changed")
        else:
            self.h.private_write(paths[0], new)
        return {
            "state": "new_prospective_intent_saved_not_submitted",
            "generation": generation,
            "checkpoint": str(paths[0].relative_to(ROOT)),
            "old_proposal_retained": True,
            "resource_fact_revision": None,
            "new_plan_receipt": None,
            "requires_root_full_host_configuration": True,
        }

    def save(self):
        path = getattr(self, "checkpoint_path", CHECKPOINT)
        if path.is_symlink():
            raise Missing("New test checkpoint symlink refused")
        self.h.private_write(path, self.data)

    def request(self, role, method, path, *, body=None, params=None):
        import httpx

        self.actor(role)
        self.target()
        with httpx.Client(
            base_url="http://127.0.0.1:8898",
            trust_env=False,
            follow_redirects=False,
            timeout=180,
            headers={"Authorization": "Bearer " + self.foundation["actors"][role]["login_token"]},
        ) as client:
            return self.h.checked(client.request(method, path, json=body, params=params))

    def get(self, family, role="observer"):
        return self.request(
            role,
            "GET",
            f"/v1/products/{self.product}/{family}",
            params={"build_id": self.data["build_id"]}
            if family.startswith("verification-")
            else None,
        )

    def reads(self, *groups):
        publication = self.data.get("test_publication")
        additional = []
        if publication:
            ref = publication["method_source"]
            additional = [
                {"artifact_id": ref["artifact_id"], "expected_revision": ref["expected_revision"]}
            ]
        return self.h.merge_reads(
            self.foundation["sources"]["foundation"]["required_source_read_set"],
            self.build["required_source_read_set"],
            additional,
            *groups,
        )

    def current(self, family="verification-handoff", role="observer"):
        view = self.get(family, role)
        pointer = view.get("current_by_request", {}).get(self.data["request_id"])
        if not pointer:
            raise Missing("Exact actual Current Formal missing")
        current = next(
            (row for row in view["requests"] if row["id"] == pointer["request_version_id"]), None
        )
        if (
            not current
            or current["revision"] != pointer["revision"]
            or current.get("source_status") != "current"
        ):
            raise Missing("Current Formal/source version mismatch")
        if (
            current.get("purpose") != self.data["purpose"]
            or current.get("project_id") != self.foundation["project_id"]
        ):
            raise Missing("Current Formal exact purpose/project mismatch")
        run = None
        run_pointer = view.get("current_by_run", {}).get(self.data["run_id"])
        if run_pointer:
            run = next(
                (row for row in view.get("runs", []) if row["id"] == run_pointer["run_version_id"]),
                None,
            )
            if (
                not run
                or run["revision"] != run_pointer["revision"]
                or run["run_id"] != self.data["run_id"]
            ):
                raise Missing("Actual Current Run mismatch")
        return view, current, run

    def ref(self, line=1):
        saved = self.foundation["requests"]["native-source"]["original"]["payload"]["content"]
        source = self.foundation["receipts"]["native-source"]
        return {
            "artifact_id": source["subject_id"],
            "expected_revision": source["subject_revision"],
            "line": line,
            "quote": saved.splitlines()[line - 1],
        }

    def publication(self, *, material=None):
        """Select already published shared native text; this grants no qualification."""
        from pdos_next.domain.configurations.schemas import DefinitionReference
        from pdos_next.domain.verification_front.schemas import ItemAssessment
        from pdos_next.service import digest

        previous = self.data.get("test_publication")
        if previous is None and material is None:
            raise Missing("Actual published method/resource material must be explicitly selected")
        raw = private_json(material) if material is not None else deepcopy(previous)
        expected = {
            "schema_version",
            "scope",
            "purpose",
            "publisher_role",
            "method",
            "actual_method",
            "method_source",
            "actual_method_source",
            "equipment",
            "calibration",
            "requirements_sources",
            "resource_sources",
            "environment",
            "conditions",
        }
        if (
            set(raw) != expected
            or raw["schema_version"] != "wave22-shared-test-publication-v1"
            or raw["scope"] != self.foundation["scope"]
            or raw["purpose"] != self.data["purpose"]
            or raw["publisher_role"] not in {"maker", "observer"}
            or any(
                type(raw[k]) is not str or not raw[k].strip() for k in ("environment", "conditions")
            )
        ):
            raise Missing("Exact explicit local publication scope and conditions required")
        refs = [
            DefinitionReference.model_validate(raw[k]).model_dump(mode="json")
            for k in ("method_source", "actual_method_source", "equipment", "calibration")
        ]
        for key in ("requirements_sources", "resource_sources"):
            if type(raw[key]) is not list or not 1 <= len(raw[key]) <= 20:
                raise Missing("Publication source union cannot be empty or truncated")
            refs.extend(
                DefinitionReference.model_validate(v).model_dump(mode="json") for v in raw[key]
            )
        identities = {(v["artifact_id"], v["expected_revision"]) for v in refs}
        if len(identities) != 1:
            raise Missing("Root must publish consolidated complete method/resource declarations")
        for kind, source_key in (
            ("method", "method_source"),
            ("actual_method", "actual_method_source"),
        ):
            assessment = raw[kind]
            if set(assessment) != {"status", "conditions", "reason"}:
                raise Missing("Explicit named method assessment required")
            ItemAssessment.model_validate(
                {"item_id": "dimension", **assessment, "sources": [raw[source_key]]}
            )
        if previous is not None and self.h.canonical(raw) != self.h.canonical(previous):
            raise Missing("Original selected publication cannot change")
        view = self.get("workspace")
        artifact_id, revision = next(iter(identities))
        rows = [v for v in view["sources"] if v["id"] == artifact_id and v["revision"] == revision]
        if len(rows) != 1:
            raise Missing("Actual current publication Artifact unavailable")
        row = rows[0]
        if (
            row["status"] != "active"
            or row["visibility"] != "product"
            or row.get("original_id") is not None
            or digest(row["content"]) != row["content_hash"]
        ):
            raise Missing("Shared immutable native publication hash/source mismatch")
        lines = row["content"].splitlines()
        for ref in refs:
            if ref["line"] > len(lines) or lines[ref["line"] - 1] != ref["quote"]:
                raise Missing("Publication exact original line mismatch")
        receipts = [
            v
            for v in view["receipts"]
            if v["operation"] == "evidence.artifact.register"
            and v["subject_id"] == artifact_id
            and v["subject_revision"] == revision
        ]
        if len(receipts) != 1:
            raise Missing("Publication exact canonical registration Receipt missing")
        self.check_receipt(
            receipts[0], raw["publisher_role"], "evidence.artifact.register", "artifact"
        )
        self.reads([{"artifact_id": artifact_id, "expected_revision": revision}])
        self.data["test_publication"] = raw
        self.data["publication_receipt"] = receipts[0]
        self.save()

    def published(self, key):
        if "test_publication" not in self.data:
            raise Missing(
                "Selected real publication required; Foundation banner is not qualification"
            )
        return deepcopy(self.data["test_publication"][key])

    def check_receipt(self, value, role, operation, family):
        if (
            not isinstance(value, dict)
            or value.get("operation") != operation
            or value.get("subject_type") != family
            or value.get("writer_id") != self.actor(role)
            or value.get("requester_id") != self.actor(role)
        ):
            raise Missing("Actual receipt operation/family/writer mismatch")
        UUID(value["id"])
        UUID(value["subject_id"])
        revision = self.h.subject_revision(value)
        if (
            value.get("result", {}).get("id") != value["subject_id"]
            or value["result"].get("revision") != revision
        ):
            raise Missing("Actual receipt flattened subject mismatch")
        return value

    def _send(self, label, role, path):
        import httpx

        saved = self.data["requests"][label]
        if saved["state"] in {"sending", "unknown"}:
            if self.recover != label or self.recover_used:
                raise Unknown(label)
            self.recover_used = True
        saved["state"] = "sending"
        self.save()
        try:
            return self.request(role, "POST", path, body=saved["body"])
        except httpx.TransportError:
            saved["state"] = "unknown"
            self.save()
            raise Unknown(label) from None
        except self.h.GuardedRequestError as error:
            saved["state"] = "rejected"
            saved["error"] = {"status": error.status, "code": error.code}
            self.save()
            raise

    def step(self, label, role, operation, family, build_payload, *, inputs=None):
        """Existing originals precede dynamic GET factories and retain every byte/key/token."""
        from pdos_next.contracts import PAYLOADS, Command
        from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS

        actor = self.actor(role)
        saved = self.data["requests"].get(label)
        command_id = self.command_id(label, role)
        if saved is not None and (
            saved["role"] != role
            or saved["actor_id"] != actor
            or saved["original"]["operation"] != operation
            or saved["original"]["product_id"] != self.product
            or saved["original"]["command_id"] != command_id
            or saved["original"]["idempotency_key"] != self.key(label, role)
        ):
            raise Missing("Saved actor/scope/operation/command identity changed")
        if label in self.data["receipts"]:
            if saved is None:
                raise Missing("Actual saved Receipt requires original request")
            return self.check_receipt(self.data["receipts"][label], role, operation, family)
        cls = PAYLOADS.get(operation)
        if cls is None:
            raise Missing("Actual canonical payload not configured")
        if saved is None:
            payload, reads = build_payload()
            typed = cls.model_validate(payload).model_dump(mode="json", exclude_none=True)
            workspace = self.get("workspace", role)
            if workspace["product"]["id"] != self.product:
                raise Missing("Actual Product mismatch")
            original = Command(
                command_id=command_id,
                idempotency_key=self.key(label, role),
                operation=operation,
                product_id=self.product,
                expected_revision=workspace["product"]["revision"],
                source_read_set=self.reads(reads),
                payload=typed,
            ).model_dump(mode="json")
            if inputs:
                response = self.request(
                    role, "POST", f"/v1/products/{self.product}/{inputs}", body=original
                )
                if response.get("allowed") is not True or response.get("operation") != operation:
                    raise Missing("Actual command inputs not allowed; no optimistic command")
                original["source_read_set"] = self.h.merge_reads(
                    original["source_read_set"], response["required_source_read_set"]
                )
            saved = {
                "role": role,
                "actor_id": actor,
                "original": original,
                "body": deepcopy(original),
                "state": "ready",
            }
            self.data["requests"][label] = saved
            self.save()
        original = Command.model_validate(saved["original"]).model_dump(mode="json")
        body = Command.model_validate(saved["body"]).model_dump(mode="json")
        normalized = deepcopy(body)
        normalized["payload"] = cls.model_validate(body["payload"]).model_dump(
            mode="json", exclude_none=True, exclude={"confirmation_token", "approval_token"}
        )
        if self.h.canonical(normalized) != self.h.canonical(original):
            raise Missing("Original prepared command/material changed")
        if "preview" in saved and self.h.canonical(body) != self.h.canonical(
            saved["preview"]["command"]
        ):
            raise Missing("Original prepared token cannot change")
        if saved["state"] == "rejected":
            raise Missing("Original request refused; no fresh key/token repair")
        if saved["state"] in {"preview_sending", "preview_unknown"}:
            raise Missing("Actual preview recovery missing; no replacement preview")
        if (
            saved["state"] not in {"sending", "unknown"}
            and operation in T1_OPERATIONS | T2_OPERATIONS
        ):
            if "preview" not in saved:
                import httpx

                saved["state"] = "preview_sending"
                self.save()
                try:
                    preview = self.request(role, "POST", "/v1/commands/preview", body=original)
                except httpx.TransportError:
                    saved["state"] = "preview_unknown"
                    self.save()
                    raise Missing("Preview outcome unknown") from None
                prepared = Command.model_validate(preview["command"]).model_dump(mode="json")
                material = deepcopy(prepared)
                material["payload"] = cls.model_validate(prepared["payload"]).model_dump(
                    mode="json", exclude_none=True, exclude={"confirmation_token", "approval_token"}
                )
                if self.h.canonical(material) != self.h.canonical(original):
                    raise Missing("Actual preview changed fixed command")
                tier = "T2" if operation in T2_OPERATIONS else "T1"
                field = "approval_token" if tier == "T2" else "confirmation_token"
                if not prepared["payload"].get(field) or (
                    tier == "T2"
                    and (
                        preview.get("write_tier") != "T2"
                        or preview.get("named_decision") is not True
                    )
                ):
                    raise Missing("Actual named proof/tier missing")
                review = hashlib.sha256(
                    self.h.canonical({"command": prepared, "review": preview["review"]}).encode()
                ).hexdigest()
                saved.update(
                    preview=preview,
                    body=prepared,
                    tier=tier,
                    review_digest=review,
                    state="awaiting_confirmation",
                )
                self.save()
            if (
                self.confirm != label
                or self.confirm_used
                or self.review_digest != saved["review_digest"]
            ):
                raise Pending(label)
            self.confirm_used = True
        value = self._send(label, role, "/v1/commands")
        self.check_receipt(value, role, operation, family)
        self.data["receipts"][label] = value
        saved["state"] = "saved"
        self.save()
        return value

    def event(self, label, role, operation, occurred_at, *, executor=False, promise_window=None):
        if label not in self.data["events"]:
            if operation == "verification.schedule.promise":
                if executor is not True or promise_window is None:
                    raise Missing("Promise needs the actual fixed Plan and named executor")
                promise_start(occurred_at, promise_window)
            else:
                if promise_window is not None:
                    raise Missing("Future commitment permission only belongs to Promise")
                aware_past(occurred_at)
            raw = {
                "request_id": self.data["request_id"],
                "purpose": self.data["purpose"],
                "operation": operation,
                "occurred_at": occurred_at,
            }
            if operation.startswith("test.") or operation == "verification.schedule.promise":
                raw["run_id"] = self.data["run_id"]
            raw["executor_id" if executor else "actor_id"] = self.actor(role)
            self.data["events"][label] = {"raw": raw, "text": self.h.canonical(raw)}
            self.save()
        event = self.data["events"][label]
        if event["raw"]["operation"] != operation or event["raw"].get(
            "actor_id", event["raw"].get("executor_id")
        ) != self.actor(role):
            raise Missing("Saved event scope/actor changed")
        if occurred_at is not None and occurred_at != event["raw"]["occurred_at"]:
            raise Missing("Original observed clock cannot change")
        if operation == "verification.schedule.promise":
            if executor is not True or promise_window is None:
                raise Missing("Promise needs the actual fixed Plan and named executor")
            promise_start(event["raw"]["occurred_at"], promise_window)
        result = self.step(
            "event-" + label,
            role,
            "evidence.artifact.register",
            "artifact",
            lambda: (
                {
                    "title": "Wave22 shared synthetic · " + label,
                    "content": event["text"],
                    "source_label": (
                        "Explicit local synthetic commitment to the fixed future start; "
                        "not an actual Start or instrument evidence"
                        if operation == "verification.schedule.promise"
                        else (
                            "Explicit already-observed local synthetic event; "
                            "not instrument evidence"
                        )
                    ),
                    "visibility": "product",
                },
                [],
            ),
        )
        ref = {
            "artifact_id": result["subject_id"],
            "expected_revision": result["subject_revision"],
            "line": 1,
            "quote": event["text"],
        }
        return {
            "reference": ref,
            "at": {
                "occurred_at": event["raw"]["occurred_at"],
                "original_timezone": "UTC",
                "source": {
                    "id": ref["artifact_id"],
                    "revision": ref["expected_revision"],
                    "kind": "artifact",
                    "position": "line:1;quote_sha256:"
                    + hashlib.sha256(event["text"].encode()).hexdigest(),
                },
            },
        }

    def event_batch(self, label, entries, *, publisher):
        """One native publication of two independently supplied past events only."""
        if len(entries) != 2 or len({v[0] for v in entries}) != 2:
            raise Missing("Exact two observed events required")
        saved = self.data["events"].get(label)
        if saved is None:
            rows = []
            for key, role, operation, occurred_at in entries:
                aware_past(occurred_at)
                raw = {
                    "request_id": self.data["request_id"],
                    "purpose": self.data["purpose"],
                    "operation": operation,
                    "occurred_at": occurred_at,
                    "actor_id": self.actor(role),
                }
                if operation.startswith("test."):
                    raw["run_id"] = self.data["run_id"]
                else:
                    raw["sample_id"] = self.data["original_sample_id"]
                rows.append({"key": key, "raw": raw, "text": self.h.canonical(raw)})
            if aware_past(rows[0]["raw"]["occurred_at"]) > aware_past(
                rows[1]["raw"]["occurred_at"]
            ):
                raise Missing("Actual event pair clocks must be ordered")
            saved = {"publisher": publisher, "rows": rows}
            self.data["events"][label] = saved
            self.save()
        if saved["publisher"] != publisher:
            raise Missing("Original event publisher cannot change")
        for entry, row in zip(entries, saved["rows"], strict=True):
            key, role, operation, occurred_at = entry
            if (
                row["key"] != key
                or row["raw"]["operation"] != operation
                or row["raw"]["actor_id"] != self.actor(role)
                or (occurred_at is not None and occurred_at != row["raw"]["occurred_at"])
            ):
                raise Missing("Original whole event pair cannot change")
        result = self.step(
            "event-" + label,
            publisher,
            "evidence.artifact.register",
            "artifact",
            lambda: (
                {
                    "title": "Wave22 shared synthetic · " + label,
                    "content": "\n".join(v["text"] for v in saved["rows"]),
                    "source_label": "Two explicit already-observed events; not instrument evidence",
                    "visibility": "product",
                },
                [],
            ),
        )
        values = {}
        for number, row in enumerate(saved["rows"], 1):
            reference = {
                "artifact_id": result["subject_id"],
                "expected_revision": result["subject_revision"],
                "line": number,
                "quote": row["text"],
            }
            values[row["key"]] = {
                "reference": reference,
                "at": {
                    "occurred_at": row["raw"]["occurred_at"],
                    "original_timezone": "UTC",
                    "source": {
                        "id": result["subject_id"],
                        "revision": result["subject_revision"],
                        "kind": "artifact",
                        "position": f"line:{number};quote_sha256:"
                        + hashlib.sha256(row["text"].encode()).hexdigest(),
                    },
                },
            }
        return values

    def selected(self, view):
        values = [
            row
            for row in view["reference_samples"]
            if row["request_id"] == self.data["request_id"]
            and row["id"] == self.data["original_sample_id"]
        ]
        if len(values) != 1:
            raise Missing("Actual original Sample not currently selectable")
        from pdos_next.schemas.verification.contracts import SampleRef

        fixed = SampleRef.model_validate(values[0]["reference"])
        if str(fixed.build_id) != self.data["build_id"] or fixed.cavity != "A":
            raise Missing("Fixed actual Sample/Build/cavity mismatch")
        return fixed.model_dump(mode="json"), values[0].get("required_source_read_set", [])

    def handoff(self, *, offer_at=None, accept_at=None):
        self.publication()
        self.step(
            "preparation",
            "observer",
            "verification.preparation.record",
            "verification_preparation",
            lambda: (
                {
                    "request_id": self.data["preparation_request_id"],
                    "expected_request_revision": 0,
                    "build_id": self.data["build_id"],
                    "expected_build_revision": self.build["build"]["revision"],
                    "title": "Wave22 shared original single A dimension",
                    "purpose": self.data["purpose"],
                    "return_form": "Exact uploaded UTF-8 JSONL original; synthetic not instrument",
                    "items": [
                        {
                            "id": "dimension",
                            "feature": "Dimension",
                            "drawing": self.ref(2),
                            "method": self.published("method_source"),
                            "criterion": {"lower": "9.5", "upper": "10.5", "source": self.ref(2)},
                            "unit": "mm",
                            "conditions": "23 C, dry",
                            "material": "Synthetic material",
                            "sample_count": 1,
                            "cavities": ["A"],
                            "destructive": False,
                        }
                    ],
                    "documents": [
                        {
                            "id": "method",
                            "title": "Fixed method publication",
                            "item_ids": ["dimension"],
                            "source": self.published("method_source"),
                            "required": True,
                        }
                    ],
                    "sources": [self.ref()],
                    "reason": "New shared original case; no private Failure cloned",
                },
                self.reads(),
            ),
        )

        def formal():
            view = self.get("verification")
            receipt = self.data["receipts"]["preparation"]
            prep = next((r for r in view["preparations"] if r["id"] == receipt["subject_id"]), None)
            if (
                not prep
                or prep["revision"] != receipt["subject_revision"]
                or prep["source_status"] != "current"
            ):
                raise Missing("Exact actual Preparation missing")
            return {
                "request_id": self.data["request_id"],
                "preparation_id": prep["id"],
                "expected_preparation_revision": prep["revision"],
                "preparation_sha256": prep["sha256"],
                "reason": "New shared Formal branch",
            }, prep["required_source_read_set"]

        self.step(
            "formal", "observer", "verification.request.create", "verification_request", formal
        )

        def method():
            _, row, _ = self.current()
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": row["revision"],
                "assessments": [
                    {
                        "item_id": "dimension",
                        **self.published("method"),
                        "sources": [self.published("method_source")],
                    }
                ],
                "reason": "Fixed current plan method only",
            }, row["required_source_read_set"]

        self.step(
            "method", "observer", "verification.method.prepare", "verification_request", method
        )

        def actual_method():
            view, row, _ = self.current()
            sample, reads = self.selected(view)
            self.data["sample_ref"] = sample
            self.data["coverage"] = [{"sample_id": sample["id"], "item_id": "dimension"}]
            self.save()
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": row["revision"],
                "assessments": [
                    {
                        "sample": sample,
                        "item_id": "dimension",
                        "expected_assessment_revision": 0,
                        **self.published("actual_method"),
                        "sources": [self.published("actual_method_source")],
                    }
                ],
                "sources": [self.ref()],
                "reason": "No inherited method positive",
            }, self.reads(row["required_source_read_set"], reads)

        self.step(
            "actual-method",
            "observer",
            "verification.actual_method.prepare",
            "verification_actual_method",
            actual_method,
        )
        observed = self.event_batch(
            "handoff",
            (
                ("offer", "maker", "verification.handoff.offer", offer_at),
                ("accept", "observer", "verification.handoff.accept", accept_at),
            ),
            publisher="maker",
        )
        for action, role, occurred in (
            ("offer", "maker", offer_at),
            ("accept", "observer", accept_at),
        ):

            def payload(action=action, role=role, occurred=occurred):
                view, row, _ = self.current(role=role)
                sample, sample_reads = self.selected(view)
                event = observed[action]
                raw = {
                    "request_id": self.data["request_id"],
                    "expected_request_revision": row["revision"],
                    "coverage": self.data["coverage"],
                    "at": event["at"],
                    "sources": [self.ref(), event["reference"]],
                    "reason": "Exact shared original A/dimension handoff",
                }
                raw["samples" if action == "offer" else "returned_coverage"] = (
                    [sample] if action == "offer" else []
                )
                return raw, self.reads(
                    row["required_source_read_set"],
                    sample_reads,
                    [
                        {
                            "artifact_id": event["reference"]["artifact_id"],
                            "expected_revision": event["reference"]["expected_revision"],
                        }
                    ],
                )

            self.step(
                action, role, "verification.handoff." + action, "verification_request", payload
            )
        self.data["phase"] = "original_accepted_no_run_or_occupancy"
        self.save()

    def resource_binding(self, plan):
        """Actual scoped saved rows only; this structural export grants nothing."""
        from pdos_next.database import engine_for, tenant_session
        from pdos_next.domain.verification_front import service as front
        from pdos_next.domain.verification_handoff import service as handoff
        from pdos_next.domain.verification_launch.service import _binding
        from pdos_next.service import Context, require_access

        target = self.target()
        engine = engine_for(target["app_url"])
        ctx = Context(
            UUID(self.foundation["tenant_id"]),
            UUID(self.actor("observer")),
            UUID(self.actor("observer")),
        )
        try:
            with tenant_session(engine, ctx.tenant_id) as s:
                require_access(s, ctx, UUID(self.product), write=False, lock=True)
                _, row = front._current(s, ctx, UUID(self.product), UUID(self.data["request_id"]))
                if row is None:
                    raise Missing("Exact saved accepted Formal missing")
                request = front._snapshot(row)
                if (
                    request.status != "accepted"
                    or request.scope.project_id != UUID(self.foundation["project_id"])
                    or request.purpose != self.data["purpose"]
                ):
                    raise Missing("Actual accepted original scope required")
                actual_build = front._build(s, ctx, UUID(self.product), request.build.id)
                front._linked(s, ctx, UUID(self.product), actual_build)
                methods = {}
                for pair in self.data["coverage"]:
                    _, method = handoff._method_pointer(
                        s,
                        ctx,
                        UUID(self.product),
                        request.id,
                        UUID(pair["sample_id"]),
                        pair["item_id"],
                    )
                    if method is None:
                        raise Missing("Actual saved per-pair method missing")
                    methods[(UUID(pair["sample_id"]), pair["item_id"])] = method
                result = _binding(
                    row, request, UUID(self.data["run_id"]), plan, methods
                ).model_dump(mode="json")
                require_access(s, ctx, UUID(self.product), write=False, lock=True)
                return result
        finally:
            engine.dispose()

    def resources(self, *, window_start=None, window_end=None, valid_until=None):
        if self.data.get("prospective_generation"):
            return self._prospective_resources(
                window_start=window_start, window_end=window_end, valid_until=valid_until
            )
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan
        from pdos_next.engines.planning.calendar import frozen_timezone

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
                            UUID(self.foundation["case_id"]),
                            "original:resource-selection-placeholder",
                        )
                    ),
                    "expected_resource_fact_revision": 1,
                }
            )
            if (
                expiry.utcoffset() is None
                or not at < plan.window.start < plan.window.finish < expiry
                or expiry > datetime.fromisoformat(self.foundation["bootstrap_expires_at"])
            ):
                raise Missing("Finite future plan within actual login scope lifetime required")
            binding = self.resource_binding(plan)
            calendar = {
                "calendar_id": self.key("test-calendar"),
                "version": "1",
                "timezone": "UTC",
                "timezone_rules_sha256": frozen_timezone("UTC")[1],
                "weekly": [
                    {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                    for i in range(7)
                ],
            }
            resources = []
            for kind, identity, kinds in (
                ("equipment", self.data["test_equipment_id"], ("acceptance", "calibration")),
                ("person", self.actor("observer"), ("qualification",)),
            ):
                resources.append(
                    {
                        "resource": {"id": identity, "revision": 1, "kind": kind},
                        "purposes": [self.data["purpose"]],
                        "operation_ids": ["test.run.start"],
                        "lifecycle": "active",
                        "maintenance": [],
                        "capacity": "1",
                        "calendar": calendar,
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
                                        UUID(self.foundation["case_id"]),
                                        "original:" + kind + ":" + k,
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
        profile = {
            "tenant_id": self.foundation["tenant_id"],
            "product_id": self.product,
            "issuer_key": "wave22-test-resource-" + self.foundation["case_id"],
            "issuer_version": "v1",
            "decisions": [
                {"binding": raw["binding"], "resource": r["resource"], "decision": d}
                for r in raw["resources"]
                for d in r["facts"]
            ],
        }
        for path, value in ((RESOURCE_PROFILE, profile), (RESOURCE_INPUT, raw)):
            if path.exists() or path.is_symlink():
                if self.h.canonical(private_json(path)) != self.h.canonical(value):
                    raise Missing("Existing exact finite resource export differs")
            else:
                self.h.private_write(path, value)
        self.data["phase"] = "resource_exports_not_imported_or_installed"
        self.save()
        return {
            "resource_profile": str(RESOURCE_PROFILE.relative_to(ROOT)),
            "resource_input": str(RESOURCE_INPUT.relative_to(ROOT)),
            "requires_root_trusted_import_and_api_plural_reload": True,
        }

    def _prospective_resources(self, *, window_start=None, window_end=None, valid_until=None):
        """Fresh real accepted/method binding; old physical mirrors and publications are exact."""
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan

        selected = self.data["prospective_generation"]
        self._origin_files(selected)
        material = selected["material"]
        for provided, original in (
            (window_start, material["window"]["start"]),
            (window_end, material["window"]["finish"]),
            (valid_until, material["valid_until"]),
        ):
            if provided is not None and provided != original:
                raise Missing("Explicit new prospective material is fixed, not an editable plan")
        if "resource_input" not in self.data:
            self.publication()
            at = datetime.now(UTC)
            plan = ExecutionPlan.model_validate(self.data["execution_plan"])
            expiry = datetime.fromisoformat(material["valid_until"].replace("Z", "+00:00"))
            if not at < plan.window.start < plan.window.finish < expiry:
                raise Missing("New prospective window has elapsed; retain this unsent intent")
            binding = self.resource_binding(plan)
            old = self.data["origin_archive"]["resource_input"]
            expected = {
                **old["binding"],
                "run_id": self.data["run_id"],
                "window": plan.window.model_dump(mode="json"),
            }
            if binding != expected:
                raise Missing("Actual accepted scope/method changed; no new scope substitution")
            raw = deepcopy(old)
            raw.update(
                binding=binding,
                external_id=self.key("resource"),
                expected_previous_id=None,
                expected_previous_revision=0,
                valid_from=at.isoformat(),
                valid_until=expiry.isoformat(),
                reason=material["reason"],
            )
            for resource in raw["resources"]:
                for decision in resource["facts"]:
                    decision.update(
                        valid_from=at.isoformat(),
                        valid_until=expiry.isoformat(),
                        named_decision_id=str(
                            uuid5(
                                UUID(selected["id"]),
                                "resource:" + resource["resource"]["id"] + ":" + decision["kind"],
                            )
                        ),
                    )
            self.data["resource_input"] = TestResourceFactInput.model_validate(raw).model_dump(
                mode="json"
            )
            self.save()
        raw = self.data["resource_input"]
        new_entries = [
            {"binding": raw["binding"], "resource": r["resource"], "decision": d}
            for r in raw["resources"]
            for d in r["facts"]
        ]
        profile = deepcopy(selected["old_profile"])
        profile["issuer_version"] = material["issuer_version"]
        profile["decisions"] += new_entries
        identities = [v["decision"]["named_decision_id"] for v in profile["decisions"]]
        if len(identities) > 200 or len(set(identities)) != len(identities):
            raise Missing("Finite old+new exact host ledger must be unique and bounded")
        paths = (
            getattr(self, "resource_profile_path", RESOURCE_PROFILE),
            getattr(self, "resource_input_path", RESOURCE_INPUT),
        )
        for path, value in zip(paths, (profile, raw), strict=True):
            if path.exists() or path.is_symlink():
                if private_json(path) != value:
                    raise Missing("Existing exact prospective resource export differs")
            else:
                self.h.private_write(path, value)
        self.data["phase"] = "new_resource_exports_not_imported_or_installed"
        self.save()
        return {
            "generation": selected["id"],
            "resource_profile": str(paths[0].relative_to(ROOT)),
            "resource_input": str(paths[1].relative_to(ROOT)),
            "new_series_revision": 1,
            "requires_root_full_host_configuration_and_trusted_import": True,
            "old_fact_retained_not_rebound": True,
        }

    def installed_plan(self):
        from pdos_next.domain.test_resources.schemas import TestPlanBinding

        if "resource_input" not in self.data:
            raise Missing("Exact resource export required")
        view, row, _ = self.current("verification-launch")
        selected = [
            r
            for r in view["resource_facts"]
            if r.get("current") is True
            and r.get("state") == "active"
            and r.get("source_status") == "current"
            and TestPlanBinding.model_validate(r["binding"])
            == TestPlanBinding.model_validate(self.data["resource_input"]["binding"])
        ]
        if len(selected) != 1:
            raise Missing("Actual current exact imported resource fact required; no client Receipt")
        resource = selected[0]
        plan = deepcopy(self.data["execution_plan"])
        plan.update(
            resource_fact_id=resource["id"], expected_resource_fact_revision=resource["revision"]
        )
        return plan, row

    def plan(self):
        def payload():
            plan, row = self.installed_plan()
            self.data["installed_execution_plan"] = plan
            self.save()
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": row["revision"],
                "run_id": self.data["run_id"],
                "coverage": self.data["coverage"],
                "execution_plan": plan,
                "sources": [self.ref()],
                "reason": "Exact complete accepted original A/dimension plan",
            }, row["required_source_read_set"]

        self.step(
            "run-plan",
            "observer",
            "test.run.plan",
            "test_run",
            payload,
            inputs="verification-launch/inputs",
        )
        self.data["phase"] = "actual_original_plan_saved_no_start"
        self.save()

    def promise(self, *, occurred_at=None):
        def payload():
            _, request, run = self.current("verification-launch")
            if run is None or run["status"] != "planned":
                raise Missing("Actual saved planned Run required")
            window = run["execution_plan"]["window"]
            promise_start(occurred_at, window)
            event = self.event(
                "promise",
                "observer",
                "verification.schedule.promise",
                occurred_at,
                executor=True,
                promise_window=window,
            )
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_plan_sha256": run["plan_sha256"],
                "at": event["at"],
                "sources": [self.ref(), event["reference"]],
                "reason": (
                    "Named commitment to the exact fixed future start; "
                    "not an actual Start or occupancy event"
                ),
            }, self.reads(
                request["required_source_read_set"],
                [
                    {
                        "artifact_id": event["reference"]["artifact_id"],
                        "expected_revision": event["reference"]["expected_revision"],
                    }
                ],
            )

        self.step(
            "promise",
            "observer",
            "verification.schedule.promise",
            "verification_request",
            payload,
            inputs="verification-launch/inputs",
        )
        self.data["phase"] = "actual_promise_saved_no_start"
        self.save()

    def start(self, *, occurred_at=None):
        def payload():
            _, request, run = self.current("verification-launch")
            if run is None or run["status"] != "planned":
                raise Missing("Actual current planned Run required")
            window = run["execution_plan"]["window"]
            now = datetime.now(UTC)
            at = aware_past(occurred_at)
            first, last = [
                datetime.fromisoformat(window[k].replace("Z", "+00:00"))
                for k in ("start", "finish")
            ]
            if not first <= at <= now < last or now < first:
                raise Missing("Actual Start in live original window required; no wait or replan")
            event = self.event(
                "run-start", "observer", "test.run.start", occurred_at, executor=True
            )
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_plan_sha256": run["plan_sha256"],
                "at": event["at"],
                "sources": [self.ref(), event["reference"]],
                "reason": "Actual shared Observer start, exactly original intent",
            }, self.reads(
                request["required_source_read_set"],
                [
                    {
                        "artifact_id": event["reference"]["artifact_id"],
                        "expected_revision": event["reference"]["expected_revision"],
                    }
                ],
            )

        self.step(
            "run-start",
            "observer",
            "test.run.start",
            "test_run",
            payload,
            inputs="verification-launch/inputs",
        )
        self.data["phase"] = "actual_original_started"
        self.save()

    def auxiliary(self, label, role, path, body):
        """Non-Command owner endpoint: retain exact key/body and recover one original."""
        saved = self.data["requests"].get(label)
        if label in self.data:
            return self.data[label]
        if saved is None:
            self.data["requests"][label] = {
                "role": role,
                "actor_id": self.actor(role),
                "path": path,
                "body": body,
                "state": "ready",
            }
            self.save()
        elif (
            saved["role"] != role
            or saved["actor_id"] != self.actor(role)
            or saved["path"] != path
            or self.h.canonical(saved["body"]) != self.h.canonical(body)
        ):
            raise Missing("Original auxiliary body/key/actor cannot change")
        value = self._send(label, role, path)
        self.data[label] = value
        self.data["requests"][label]["state"] = "saved"
        self.save()
        return value

    def report(self, *, material=None):
        if "run-start" not in self.data["receipts"]:
            raise Missing("Actual original Start Receipt required")
        if "report_material" not in self.data:
            if material is None:
                raise Missing("Explicit already-observed complete original JSONL material required")
            raw = private_json(material)
            if (
                set(raw) != {"report_utf8", "actual_end", "returned_at", "original_timezone"}
                or raw["original_timezone"] != "UTC"
                or type(raw["report_utf8"]) is not str
            ):
                raise Missing("Exact original report/end/return material required")
            end, returned = aware_past(raw["actual_end"]), aware_past(raw["returned_at"])
            if (
                end > returned
                or not raw["report_utf8"].endswith("\n")
                or len(raw["report_utf8"].encode()) > 200_000
            ):
                raise Missing("Bounded full JSONL with ordered actual end/return required")
            # No expected Run metadata is inserted into actual report bytes.
            self.data["report_material"] = raw
            self.data["report_sha256"] = hashlib.sha256(raw["report_utf8"].encode()).hexdigest()
            self.save()
        elif material is not None and self.h.canonical(private_json(material)) != self.h.canonical(
            self.data["report_material"]
        ):
            raise Missing("Original report bytes/clocks cannot change")
        raw = self.data["report_material"]
        if "report-upload" not in self.data:
            workspace = self.get("workspace")
            upload_body = {
                "idempotency_key": self.key("report-upload"),
                "expected_revision": workspace["product"]["revision"],
                "title": "Wave22 shared Observer original synthetic report",
                "source_label": "Explicit synthetic exact original report; not instrument evidence",
                "filename": "wave22-original.jsonl.txt",
                "visibility": "product",
                "content_base64": base64.b64encode(raw["report_utf8"].encode()).decode(),
            }
            if "report-upload" in self.data["requests"]:
                upload_body = self.data["requests"]["report-upload"]["body"]
            upload = self.auxiliary(
                "report-upload", "observer", f"/v1/products/{self.product}/originals", upload_body
            )
            self.check_receipt(upload, "observer", "evidence.original.upload", "uploaded_original")
        original_id = self.data["report-upload"]["subject_id"]
        if "report-scan" not in self.data:
            workspace = self.get("workspace")
            original = next(
                (row for row in workspace["originals"] if row["id"] == original_id), None
            )
            if original is None:
                raise Missing("Actual uploaded Original unavailable")
            body = {
                "expected_epoch": original["security"]["epoch"],
                "idempotency_key": self.key("report-scan"),
            }
            if "report-scan" in self.data["requests"]:
                body = self.data["requests"]["report-scan"]["body"]
            self.auxiliary(
                "report-scan",
                "observer",
                f"/v1/products/{self.product}/originals/{original_id}/scan",
                body,
            )
        view, request, run = self.current("verification-results")
        if run is None:
            raise Missing("Actual fixed running Run unavailable")
        reports = [
            row
            for row in view["report_sources"]
            if row["original_id"] == original_id and row["source_status"] == "current"
        ]
        if len(reports) != 1:
            raise Missing("Actual clean scan/OS parse/report not ready; resume later, no fake safe")
        report = reports[0]
        if "capture" not in self.data:
            body = {
                "capture_key": self.key("capture"),
                "expected_product_revision": self.get("workspace")["product"]["revision"],
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "report_artifact_id": report["artifact_id"],
                "expected_report_revision": report["artifact_revision"],
                "selections": [
                    {
                        "line": 1,
                        "sample_id": self.data["original_sample_id"],
                        "item_id": "dimension",
                    }
                ],
                "reason": (
                    "Only exact actual uploaded JSONL line; server verifies all original fields"
                ),
            }
            if "capture" in self.data["requests"]:
                body = self.data["requests"]["capture"]["body"]
            self.auxiliary(
                "capture",
                "observer",
                f"/v1/products/{self.product}/verification-results/captures",
                body,
            )

        def payload():
            _, request, run = self.current("verification-results")
            observed = self.event_batch(
                "return",
                (
                    ("end", "observer", "test.run.end", raw["actual_end"]),
                    ("results", "observer", "test.results.import", raw["returned_at"]),
                ),
                publisher="observer",
            )
            end, returned = observed["end"], observed["results"]
            capture = self.data["capture"]["capture"]
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "capture_id": capture["id"],
                "expected_capture_revision": capture["revision"],
                "final": True,
                "at": returned["at"],
                "actual_end": end["at"],
                "sources": [end["reference"], returned["reference"]],
                "reason": (
                    "Actual exact uploaded synthetic original final return; "
                    "no instrument or pass claim"
                ),
            }, self.reads(
                request["required_source_read_set"],
                [
                    {
                        "artifact_id": end["reference"]["artifact_id"],
                        "expected_revision": end["reference"]["expected_revision"],
                    }
                ],
            )

        self.step(
            "results",
            "observer",
            "test.results.import",
            "test_run",
            payload,
            inputs="verification-results/inputs",
        )
        self.data["phase"] = "actual_original_reported_not_computed"
        self.save()

    def compute(self):
        def payload():
            _, request, run = self.current("verification-results")
            if run is None:
                raise Missing("Actual reported Run required")
            return {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_basis_sha256": run["basis_sha256"],
                "reason": "Actual deterministic fixed raw-value result; no professional conclusion",
            }, request["required_source_read_set"]

        self.step(
            "compute",
            "observer",
            "test.result.compute",
            "test_result_projection",
            payload,
            inputs="verification-results/inputs",
        )
        return self.readback()

    def readback(self):
        _, request, run = self.current("verification-results")
        computed = self.data["receipts"].get("compute")
        projection = run.get("current_projection") if run else None
        if (
            run is None
            or run.get("run_snapshot", {}).get("result") != "fail"
            or computed is None
            or projection is None
            or projection.get("id") != computed["subject_id"]
            or projection.get("revision") != computed["subject_revision"]
            or projection.get("basis_sha256") != run["basis_sha256"]
            or projection.get("result") != "fail"
        ):
            raise Missing(
                "Actual fixed original result/projection not definite fail; "
                "no Issue may be inferred"
            )
        self.data["result_readback"] = {
            "run_id": self.data["run_id"],
            "run_version_id": run["id"],
            "run_revision": run["revision"],
            "request_version_id": request["id"],
            "request_revision": request["revision"],
            "projection": deepcopy(projection),
            "result": "fail",
            "report_sha256": self.data["report_sha256"],
            "required_source_read_set": self.reads(
                request["required_source_read_set"], run["required_source_read_set"]
            ),
            "readback_at": datetime.now(UTC).isoformat(),
            "professional_review": None,
            "disposition": None,
            "followup_run": None,
            "effectiveness": None,
            "close": False,
        }
        self.data["phase"] = "actual_original_definite_fail_no_issue_or_review"
        self.save()
        return {
            "phase": self.data["phase"],
            "second_run_executed": False,
            "automatic_review": False,
        }


def main():
    parser = argparse.ArgumentParser(description="Explicit shared original Observer Run phases")
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--marker", required=True)
    pair = parser.add_mutually_exclusive_group()
    pair.add_argument("--confirm")
    pair.add_argument("--recover")
    parser.add_argument("--review-digest")
    parser.add_argument("--offer-at")
    parser.add_argument("--accept-at")
    parser.add_argument("--occurred-at")
    parser.add_argument("--window-start")
    parser.add_argument("--window-end")
    parser.add_argument("--valid-until")
    parser.add_argument("--material", type=Path)
    parser.add_argument("--generation")
    tool = None
    try:
        args = parser.parse_args()
        tool = SharedTest(
            args.marker,
            confirm=args.confirm,
            review_digest=args.review_digest,
            recover=args.recover,
            generation=args.generation,
        )
        kwargs = {
            "prospective-plan": {"material": args.material},
            "publication": {"material": args.material},
            "handoff": {"offer_at": args.offer_at, "accept_at": args.accept_at},
            "resources": {
                "window_start": args.window_start,
                "window_end": args.window_end,
                "valid_until": args.valid_until,
            },
            "promise": {"occurred_at": args.occurred_at},
            "start": {"occurred_at": args.occurred_at},
            "report": {"material": args.material},
        }
        method = "prospective_plan" if args.phase == "prospective-plan" else args.phase
        result = getattr(tool, method)(**kwargs.get(args.phase, {}))
        print(
            json.dumps(
                result
                or {
                    "phase": tool.data["phase"],
                    "receipts_saved": len(tool.data["receipts"]),
                    "no_automatic_t2_review": True,
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
                    "expires_at": value["preview"]["expires_at"],
                    "submitted": False,
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from None
    except Unknown as error:
        print(
            json.dumps(
                {
                    "state": "UNKNOWN",
                    "label": error.label,
                    "original_retained": True,
                    "automatic_retry": False,
                }
            )
        )
        raise SystemExit(3) from None
    except Exception as error:
        print(
            json.dumps(
                {
                    "state": "failed_or_dependency_missing",
                    "error_type": type(error).__name__,
                    "code": getattr(error, "code", "INTEGRATION_REQUIRED"),
                    "no_automatic_repair": True,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
