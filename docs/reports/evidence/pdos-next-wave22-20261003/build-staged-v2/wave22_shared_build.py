"""Inert, isolated shared synthetic Build continuation. Root alone runs main.

Consumes only the new Wave21 shared foundation; never imports/constructs Demo.
No connection, checkpoint read, clock fabrication or write occurs at import.
T1/T2 stop after a real preview. An explicit digest-bound confirmation sends
one prepared command. Unknown writes retain the complete original request.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

SCHEMA = "wave22-shared-build-v1"
FOUNDATION_SCHEMA = "wave21-shared-foundation-v1"
PORT = 62513
CONTROLS = (
    "no_external_delivery",
    "no_test_run_or_sample_qualification",
    "retain_traceable_outputs",
    "stop_on_configuration_deviation",
)
PROFESSIONAL_RULES = {
    "engineering": ("product_definition_applicability", "verification_objective_applicability"),
    "manufacturing": ("process_configuration_applicability", "output_disposition_applicability"),
}


class Stop(RuntimeError):
    """Safe fixed-code error: never contains URL, command, token or source text."""


class Pending(Stop):
    def __init__(self, label, stage, digest=None):
        self.label, self.stage, self.digest = label, stage, digest
        super().__init__("PENDING_" + stage.upper())


def root_for(path):
    for candidate in Path(path).resolve().parents:
        if candidate.name == "pdos-next" and (candidate / "server/pdos_next").is_dir():
            return candidate
    raise Stop("PROJECT_LAYOUT_UNAVAILABLE")


def encode(value):
    if isinstance(value, (datetime, UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(type(value).__name__)


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=encode,
    )


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def positive(value):
    return type(value) is int and value >= 1


def exact_decimal(value, expected):
    """Compare finite server decimal strings without rewriting source precision."""
    if (
        type(value) is not str
        or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value) is None
    ):
        return False
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    return number.is_finite() and number == Decimal(expected)


def known_two_unit_demand(demands):
    """Require the exact one-line known server DTO; retain its original strings."""
    if type(demands) is not list or len(demands) != 1 or type(demands[0]) is not dict:
        return False
    line = demands[0]
    return (
        set(line)
        == {
            "item_id",
            "material_id",
            "unit",
            "critical",
            "ancestry",
            "quantity_per_product",
            "required_quantity",
            "issues",
        }
        and exact_decimal(line["quantity_per_product"], "1")
        and exact_decimal(line["required_quantity"], "2")
        and line["unit"] == "ea"
        and type(line["issues"]) is list
        and line["issues"] == []
        and type(line["critical"]) is bool
        and type(line["ancestry"]) is list
        and type(line["item_id"]) is str
        and bool(line["item_id"])
        and type(line["material_id"]) is str
        and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            line["material_id"],
        )
        is not None
    )


def uuid(value):
    if type(value) is not str:
        raise Stop("EXACT_UUID_REQUIRED")
    try:
        return str(UUID(value))
    except ValueError:
        raise Stop("EXACT_UUID_REQUIRED") from None


def aware(value, *, at=None):
    if type(value) is not str:
        raise Stop("ACTUAL_AWARE_TIME_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except ValueError:
        raise Stop("ACTUAL_AWARE_TIME_REQUIRED") from None
    if at is not None and parsed > at:
        raise Stop("FUTURE_EVENT_REJECTED")
    return parsed


def reference(value):
    if (
        type(value) is not dict
        or set(value)
        != {
            "artifact_id",
            "expected_revision",
            "line",
            "quote",
        }
        or not positive(value["expected_revision"])
        or not positive(value["line"])
    ):
        raise Stop("EXACT_SOURCE_REQUIRED")
    uuid(value["artifact_id"])
    if type(value["quote"]) is not str or not 1 <= len(value["quote"]) <= 4000:
        raise Stop("EXACT_SOURCE_REQUIRED")
    return deepcopy(value)


def reads(*groups):
    result = {}
    for group in groups:
        if type(group) is not list:
            raise Stop("COMPLETE_READSET_REQUIRED")
        for entry in group:
            if type(entry) is not dict or set(entry) != {"artifact_id", "expected_revision"}:
                raise Stop("COMPLETE_READSET_REQUIRED")
            identity, revision = uuid(entry["artifact_id"]), entry["expected_revision"]
            if not positive(revision) or (identity in result and result[identity] != revision):
                raise Stop("SOURCE_VERSION_CONFLICT")
            result[identity] = revision
    if len(result) > 20:
        raise Stop("SOURCE_CLOSURE_EXCEEDS_20")
    return [{"artifact_id": key, "expected_revision": result[key]} for key in sorted(result)]


def ref_reads(refs):
    return reads(
        [
            {
                "artifact_id": reference(ref)["artifact_id"],
                "expected_revision": ref["expected_revision"],
            }
            for ref in refs
        ]
    )


def receipt(value, *, operation, family, actor):
    if (
        type(value) is not dict
        or (
            value.get("operation"),
            value.get("subject_type"),
            value.get("writer_id"),
            value.get("requester_id"),
        )
        != (operation, family, actor, actor)
        or not positive(value.get("subject_revision"))
    ):
        raise Stop("EXACT_RECEIPT_REQUIRED")
    uuid(value["id"])
    uuid(value["subject_id"])
    aware(value["created_at"])
    return value


def foundation_material(value, marker):
    """Strict new foundation contract; intentionally never reads an older seed."""
    if (
        type(value) is not dict
        or value.get("schema_version") != FOUNDATION_SCHEMA
        or (
            value.get("marker") != marker
            or value.get("visibility") != "product"
            or value.get("phase") != "foundation_saved_not_build_started"
            or set(value.get("actors", {})) != {"maker", "observer", "independent_reviewer"}
            or type(value.get("purpose")) is not str
            or not 3 <= len(value["purpose"]) <= 160
        )
    ):
        raise Stop("NEW_SHARED_FOUNDATION_REQUIRED")
    ids = [uuid(value["actors"][role]["id"]) for role in value["actors"]]
    if len(set(ids)) != 3 or any(
        type(row.get("login_token")) is not str or len(row["login_token"]) < 20
        for row in value["actors"].values()
    ):
        raise Stop("THREE_EXACT_ACTORS_REQUIRED")
    scope = value.get("scope")
    if type(scope) is not dict or set(scope) != {"tenant_id", "product_id", "project_id"}:
        raise Stop("EXACT_FOUNDATION_SCOPE_REQUIRED")
    for key in scope:
        if uuid(scope[key]) != uuid(value[key]):
            raise Stop("EXACT_FOUNDATION_SCOPE_REQUIRED")
    config = value.get("configuration", {})
    if set(config) != {
        "bom_id",
        "bom_revision",
        "engineering_id",
        "engineering_revision",
        "manufacturing_id",
        "manufacturing_revision",
    }:
        raise Stop("EXACT_SHARED_CONFIGURATION_REQUIRED")
    for label, family in (
        ("project", "project"),
        ("definition", "definition_revision"),
        ("bom", "bom_revision"),
        ("engineering", "engineering_configuration"),
        ("manufacturing", "process_revision"),
        ("native-source", "artifact"),
    ):
        row = value.get("receipts", {}).get(label)
        if type(row) is not dict or row.get("subject_type") != family:
            raise Stop("SAVED_FOUNDATION_RECEIPT_REQUIRED")
        uuid(row["subject_id"])
        if not positive(row.get("subject_revision")):
            raise Stop("SAVED_FOUNDATION_RECEIPT_REQUIRED")
        if label in {"bom", "engineering", "manufacturing"} and (
            config[label + "_id"],
            config[label + "_revision"],
        ) != (row["subject_id"], row["subject_revision"]):
            raise Stop("EXACT_SHARED_CONFIGURATION_REQUIRED")
    if value["receipts"]["project"]["subject_id"] != value["project_id"]:
        raise Stop("EXACT_FOUNDATION_SCOPE_REQUIRED")
    source = value.get("sources", {}).get("foundation", {})
    ref = reference(source.get("reference"))
    if (ref["artifact_id"], ref["expected_revision"]) != (
        value["receipts"]["native-source"]["subject_id"],
        value["receipts"]["native-source"]["subject_revision"],
    ) or reads(source.get("required_source_read_set")) != ref_reads([ref]):
        raise Stop("EXACT_FOUNDATION_SOURCE_REQUIRED")
    if set(value.get("readback", {})) != set(value["actors"]) or any(
        row.get("shared_objects") != 6 for row in value["readback"].values()
    ):
        raise Stop("THREE_ACTOR_FOUNDATION_READBACK_REQUIRED")
    # Identity/profile credentials are not emitted into reports/digests of business material.
    return {
        "case_id": uuid(value["case_id"]),
        "scope": deepcopy(scope),
        "actors": {k: uuid(v["id"]) for k, v in value["actors"].items()},
        "purpose": value["purpose"],
        "configuration": deepcopy(config),
        "project_revision": value["receipts"]["project"]["subject_revision"],
        "definition_id": value["receipts"]["definition"]["subject_id"],
        "definition_revision": value["receipts"]["definition"]["subject_revision"],
        "foundation_source": deepcopy(source),
    }


def foundation_views(material, workspace, projects, configs):
    """Consume real Project nested Definition status, not an invented top-level field."""
    product = workspace["product"]
    scope, config = material["scope"], material["configuration"]
    if product["id"] != scope["product_id"] or product["purpose"] != material["purpose"]:
        raise Stop("CURRENT_SHARED_PRODUCT_CHANGED")
    groups = (
        ("project", projects["items"], scope["project_id"], material["project_revision"]),
        (
            "engineering",
            configs["engineering"],
            config["engineering_id"],
            config["engineering_revision"],
        ),
        (
            "manufacturing",
            configs["processes"],
            config["manufacturing_id"],
            config["manufacturing_revision"],
        ),
    )
    selected = []
    for label, rows, identity, revision in groups:
        found = [v for v in rows if v["id"] == identity and v["revision"] == revision]
        if len(found) != 1 or found[0].get("visibility") != "product":
            raise Stop("CURRENT_SHARED_FOUNDATION_UNAVAILABLE")
        row = found[0]
        state = (
            row.get("definition", {}).get("source_status")
            if label == "project"
            else row.get("source_status")
        )
        if state != "current":
            raise Stop("CURRENT_SHARED_FOUNDATION_UNAVAILABLE")
        reads(row["required_source_read_set"])
        selected.append(row)
    project, engineering, manufacturing = selected
    if (
        project["owner_id"] != material["actors"]["maker"]
        or project["purpose"] != material["purpose"]
    ):
        raise Stop("MAKER_PROJECT_OWNER_REQUIRED")
    if (
        (project["definition"]["id"], project["definition"]["revision"])
        != (
            material["definition_id"],
            material["definition_revision"],
        )
        or (
            engineering["definition_id"],
            engineering["definition_revision"],
            engineering["bom_id"],
            engineering["bom_revision"],
        )
        != (
            material["definition_id"],
            material["definition_revision"],
            config["bom_id"],
            config["bom_revision"],
        )
        or (manufacturing["engineering_configuration_id"], manufacturing["engineering_revision"])
        != (
            engineering["id"],
            engineering["revision"],
        )
    ):
        raise Stop("EXACT_FOUNDATION_FIXED_CHAIN_CHANGED")
    return product, selected


def private_read(path):
    path = Path(path)
    mode = path.lstat()
    if (
        not stat.S_ISREG(mode.st_mode)
        or stat.S_IMODE(mode.st_mode) != 0o600
        or (mode.st_uid != os.getuid() or path.is_symlink())
    ):
        raise Stop("OWNED_REGULAR_0600_FILE_REQUIRED")

    def pairs(items):
        result = {}
        for key, val in items:
            if key in result:
                raise Stop("DUPLICATE_JSON_KEY")
            result[key] = val
        return result

    return json.loads(
        path.read_text(),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(Stop("FINITE_JSON_REQUIRED")),
    )


def private_write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise Stop("CHECKPOINT_SYMLINK_REJECTED")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp-" + str(uuid4()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()


def occurred_json(value, *, kind, material, at):
    """An explicit already-observed input, not an automatically generated clock."""
    keys = set(material) | {"occurred_at"}
    if (
        type(value) is not dict
        or set(value) != keys
        or any(value[key] != val for key, val in material.items())
    ):
        raise Stop("EXACT_OCCURRED_" + kind.upper() + "_REQUIRED")
    aware(value["occurred_at"], at=at)
    return canonical(value)


def base_command(*, operation, product_id, revision, payload, source_reads):
    if not positive(revision):
        raise Stop("CURRENT_PRODUCT_REVISION_REQUIRED")
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": uuid(product_id),
        "expected_revision": revision,
        "source_read_set": reads(source_reads),
        "payload": deepcopy(payload),
    }


def saved_phase(data):
    """History of retained receipts only; never current qualification or permission."""
    saved = data["receipts"]
    for required, label in (
        ({"ready-A1", "ready-A2"}, "two_A_readiness_facts_saved_no_handoff_or_test_run"),
        ({"samples"}, "two_A_identities_saved_readiness_not_asserted"),
        ({"lot"}, "two_A_output_observation_saved_no_test_run"),
        ({"actual"}, "same_plan_actual_observation_saved"),
        ({"start"}, "internal_synthetic_start_saved_current_qualification_not_asserted"),
        (
            {"approve-engineering", "approve-manufacturing"},
            "two_named_decisions_saved_start_not_recorded",
        ),
        ({"assessment"}, "assessed_professional_approval_pending"),
        ({"operational"}, "operational_saved_api_profile_reload_required"),
        ({"demand"}, "planned_demand_saved_not_started"),
        ({"build"}, "planned_build_saved_demand_not_read"),
    ):
        if required <= set(saved):
            return label
    return "plan_not_saved"


def prepared_equal(original, prepared, normalize):
    if type(prepared) is not dict or set(prepared) != set(original):
        return False
    plain = deepcopy(prepared)
    plain["payload"] = {
        k: v
        for k, v in plain["payload"].items()
        if k not in {"confirmation_token", "approval_token"}
    }
    old = deepcopy(original)
    old["payload"] = normalize(old["payload"])
    plain["payload"] = normalize(plain["payload"])
    return canonical(old) == canonical(plain)


class SharedBuild:
    def __init__(self, marker, *, confirm=None, review_digest=None, recover=None):
        self.root = root_for(__file__)
        self.directory = self.root / ".local/wave22-build-staged"
        self.path = self.directory / "checkpoint.json"
        self.foundation_path = self.root / ".local/wave21-shared-case.json"
        self.marker = str(UUID(marker))
        self.seed = private_read(self.foundation_path)
        self.basis = foundation_material(self.seed, self.marker)
        self.actor = self.basis["actors"]["maker"]
        self.pid = self.basis["scope"]["product_id"]
        self.confirm, self.review_digest, self.recover = confirm, review_digest, recover
        self.confirm_used = self.recover_used = False
        if self.path.exists() or self.path.is_symlink():
            self.data = private_read(self.path)
            if (
                self.data.get("schema_version"),
                self.data.get("marker"),
                self.data.get("foundation_sha256"),
            ) != (SCHEMA, self.marker, sha(self.basis)):
                raise Stop("SAVED_BUILD_SCOPE_CHANGED")
        else:
            self.data = {
                "schema_version": SCHEMA,
                "marker": self.marker,
                "foundation_sha256": sha(self.basis),
                "case_id": str(uuid4()),
                "equipment_id": str(uuid4()),
                "requests": {},
                "receipts": {},
                "events": {},
                "phase": "plan_not_saved",
            }
            self.save()
        # Runtime imports occur only after Root invokes this tool; tests never construct it.
        sys.path[:0] = [str(self.root / "tools"), str(self.root / "server")]
        from local_environment import read_state, verified

        self.read_state, self.verified = read_state, verified
        self.target()

    def target(self):
        state = self.verified(self.read_state())
        if state["port"] != PORT or str(state["marker"]) != self.marker:
            raise Stop("EXACT_MARKED_62513_TARGET_REQUIRED")
        return state

    def save(self):
        private_write(self.path, self.data)

    def get(self, path, **params):
        return self.http("GET", f"/v1/products/{self.pid}/{path}", params=params)

    def http(self, method, path, *, body=None, params=None):
        import httpx

        self.target()  # No fallback to old/default environment.
        with httpx.Client(
            base_url="http://127.0.0.1:8898",
            trust_env=False,
            follow_redirects=False,
            timeout=180,
            headers={"Authorization": "Bearer " + self.seed["actors"]["maker"]["login_token"]},
        ) as client:
            response = client.request(method, path, json=body, params=params)
        if not response.is_success:
            try:
                code = response.json().get("code")
            except (ValueError, AttributeError):
                code = None
            code = (
                code if type(code) is str and re.fullmatch(r"[A-Z_]{1,80}", code) else "HTTP_ERROR"
            )
            raise Stop("SERVER_REJECTED_" + str(response.status_code) + "_" + code)
        return response.json()

    def source(self):
        return deepcopy(self.basis["foundation_source"]["reference"])

    def fresh_foundation(self):
        workspace, projects, configs = (
            self.get("workspace"),
            self.get("projects"),
            self.get("configurations"),
        )
        return foundation_views(self.basis, workspace, projects, configs)

    def normalized(self, operation, payload):
        from pdos_next.contracts import PAYLOADS

        cls = PAYLOADS.get(operation)
        if cls is None:
            raise Stop("ACTUAL_OPERATION_NOT_REGISTERED")
        return cls.model_validate(payload).model_dump(mode="json", exclude_none=True)

    def resume(self, label, operation, family):
        saved = self.data["requests"].get(label)
        if saved is None:
            return None
        if (saved["original"]["operation"], saved["original"]["product_id"], saved["actor"]) != (
            operation,
            self.pid,
            self.actor,
        ):
            raise Stop("ORIGINAL_REQUEST_SCOPE_CHANGED")
        if label in self.data["receipts"]:
            return receipt(
                self.data["receipts"][label], operation=operation, family=family, actor=self.actor
            )
        if saved["stage"] in {"execute_sending", "execute_unknown"}:
            if self.recover != label or self.recover_used:
                raise Pending(label, "unknown")
            self.recover_used = True
            return self.send(label, family)
        if saved["stage"] in {"preview_sending", "preview_unknown", "rejected"}:
            raise Pending(label, saved["stage"])
        if saved["stage"] == "awaiting_confirmation":
            if (
                self.confirm != label
                or self.confirm_used
                or self.review_digest != saved["review_digest"]
            ):
                raise Pending(label, "confirmation", saved["review_digest"])
            self.confirm_used = True
            return self.send(label, family)
        return self.prepare(label, family)

    def submit(self, label, operation, payload, source_reads, family):
        old = self.resume(label, operation, family)
        if old is not None:
            return old
        workspace = self.get("workspace")
        current = workspace["product"]
        if current["id"] != self.pid:
            raise Stop("CURRENT_PRODUCT_SCOPE_CHANGED")
        original = base_command(
            operation=operation,
            product_id=self.pid,
            revision=current["revision"],
            payload=self.normalized(operation, payload),
            source_reads=source_reads,
        )
        self.data["requests"][label] = {
            "actor": self.actor,
            "original": original,
            "body": deepcopy(original),
            "stage": "ready",
        }
        self.save()
        return self.prepare(label, family)

    def prepare(self, label, family):
        from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS

        saved = self.data["requests"][label]
        operation = saved["original"]["operation"]
        tier = "T2" if operation in T2_OPERATIONS else "T1" if operation in T1_OPERATIONS else "T0"
        if tier != "T0":
            saved["stage"] = "preview_sending"
            self.save()
            try:
                preview = self.http("POST", "/v1/commands/preview", body=saved["original"])
                prepared = preview["command"]
                if not prepared_equal(
                    saved["original"], prepared, lambda p: self.normalized(operation, p)
                ):
                    raise Stop("PREVIEW_ORIGINAL_MATERIAL_CHANGED")
                token = "approval_token" if tier == "T2" else "confirmation_token"
                if (
                    not prepared["payload"].get(token)
                    or (
                        tier == "T2"
                        and (
                            preview.get("write_tier") != "T2"
                            or preview.get("named_decision") is not True
                        )
                    )
                    or not isinstance(preview.get("review"), dict)
                ):
                    raise Stop("REAL_NAMED_CONFIRMATION_REQUIRED")
            except Exception:
                saved["stage"] = "preview_unknown"
                self.save()
                raise
            saved.update(
                body=prepared,
                preview=preview,
                stage="awaiting_confirmation",
                tier=tier,
                review_digest=sha({"command": prepared, "review": preview["review"]}),
            )
            self.save()
            raise Pending(label, "confirmation", saved["review_digest"])
        return self.send(label, family)

    def send(self, label, family):
        saved = self.data["requests"][label]
        saved["stage"] = "execute_sending"
        self.save()  # Exact original prepared command survives timeout/process termination.
        try:
            result = self.http("POST", "/v1/commands", body=saved["body"])
            receipt(
                result, operation=saved["original"]["operation"], family=family, actor=self.actor
            )
        except Exception:
            saved["stage"] = "execute_unknown"
            self.save()  # Even non-authoritative error must not permit another command.
            raise
        self.data["receipts"][label] = result
        saved["stage"] = "saved"
        self.save()  # Receipt wins over a subsequent read failure.
        return result

    def artifact(self, label, lines):
        if not lines or any(type(v) is not str or not 1 <= len(v) <= 4000 for v in lines):
            raise Stop("BOUNDED_COMPLETE_SOURCE_LINES_REQUIRED")
        saved = self.data["requests"].get("source-" + label)
        if saved is not None and saved["original"]["payload"].get("content") != "\n".join(lines):
            raise Stop("ORIGINAL_NATIVE_SOURCE_CONTENT_CHANGED")
        result = self.submit(
            "source-" + label,
            "evidence.artifact.register",
            {
                "title": "Wave22 共享合成 · " + label,
                "content": "\n".join(lines),
                "source_label": "已发生本地合成记录；非真实生产/设备资格/外发证明",
                "visibility": "product",
            },
            [],
            "artifact",
        )
        return [
            {
                "artifact_id": result["subject_id"],
                "expected_revision": result["subject_revision"],
                "line": i + 1,
                "quote": text,
            }
            for i, text in enumerate(lines)
        ]

    def saved(self, label):
        row = self.data["receipts"].get(label)
        if row is None:
            raise Stop("PREREQUISITE_RECEIPT_REQUIRED_" + label.upper())
        return row

    def selected_build(self):
        result = self.saved("build")
        found = [v for v in self.get("builds")["items"] if v["id"] == result["subject_id"]]
        if (
            len(found) != 1
            or found[0]["revision"] != result["subject_revision"]
            or (
                found[0]["visibility"] != "product"
                or found[0]["owner_id"] != self.actor
                or found[0]["source_status"] != "current"
            )
        ):
            raise Stop("CURRENT_SHARED_BUILD_UNAVAILABLE")
        return found[0]

    def plan(self):
        existing = self.resume("build", "build.create", "build")
        if existing is None:
            _, rows = self.fresh_foundation()
            config = self.basis["configuration"]
            complete = reads(
                self.basis["foundation_source"]["required_source_read_set"],
                *[row["required_source_read_set"] for row in rows],
            )
            self.submit(
                "build",
                "build.create",
                {
                    "project_id": self.basis["scope"]["project_id"],
                    "expected_project_revision": self.basis["project_revision"],
                    "engineering_configuration_id": config["engineering_id"],
                    "manufacturing_configuration_id": config["manufacturing_id"],
                    "name": "Wave22 共享内部两件A合成轮次",
                    "type": "prototype",
                    "purpose": self.basis["purpose"],
                    "planned_quantity": "2",
                    "unit": "ea",
                    "planned_start": None,
                    "planned_end": None,
                    "verification_objectives": (
                        "两件独立A身份供原失败与整改后复验；开工不授测试资格"
                    ),
                    "disposition_plan": "本地合成、内部保留可追溯样件；不外发、不正式放行",
                    "previous_build_id": None,
                },
                complete,
                "build",
            )
        build = self.selected_build()
        self.submit(
            "demand",
            "build.readiness.compute",
            {
                "build_id": build["id"],
                "expected_build_revision": build["revision"],
            },
            build["required_source_read_set"],
            "build_readiness",
        )
        self.data["phase"] = "planned_demand_saved_not_started"
        self.save()

    def operational(self, raw):
        """Actual host import, isolated issuer/profile; no public qualification endpoint."""
        from pdos_next.database import engine_for, tenant_session
        from pdos_next.domain.build_operational_facts.schemas import FactInput
        from pdos_next.engines.planning.calendar import frozen_timezone
        from pdos_next.operational_bootstrap import configure_local_profiles
        from pdos_next.operational_import import import_operational_fact
        from pdos_next.service import Context

        if "operational" in self.data["receipts"]:
            receipt(
                self.data["receipts"]["operational"],
                operation="build.operational_facts.import",
                family="build_operational_fact",
                actor=self.actor,
            )
            return
        if self.data.get("operational_stage") in {"sending", "unknown"}:
            if self.recover != "operational" or self.recover_used:
                raise Pending("operational", "unknown")
            self.recover_used = True
        build = self.selected_build()
        if "operational_input" not in self.data:
            if (
                type(raw) is not dict
                or set(raw) != {"observed_at", "window_start", "window_end", "ack_local_synthetic"}
                or (raw["ack_local_synthetic"] is not True)
            ):
                raise Stop("EXPLICIT_SYNTHETIC_OPERATIONAL_OBSERVATION_REQUIRED")
            at, until = aware(raw["observed_at"], at=datetime.now(UTC)), aware(raw["window_end"])
            start = aware(raw["window_start"])
            if not at <= start < until or until <= datetime.now(UTC):
                raise Stop("BOUNDED_OPERATIONAL_WINDOW_REQUIRED")
            demands = build["readiness"]["result"]["demands"]
            if not known_two_unit_demand(demands):
                raise Stop("EXACT_KNOWN_TWO_UNIT_DEMAND_REQUIRED")
            identity = self.data["case_id"]
            pool = "wave22-pool-" + identity
            site = "wave22-internal-lab-" + identity
            scope = {
                "purpose": self.basis["purpose"],
                "quantity": "2",
                "unit": "ea",
                "site": site,
                "window": {
                    "start": raw["window_start"],
                    "finish": raw["window_end"],
                    "original_timezone": "UTC",
                },
            }
            observed = {
                "nature": "synthetic",
                "observed_at": raw["observed_at"],
                "source_system": "SYN-W22-NEW",
                "pool_id": pool,
                "material_id": demands[0]["material_id"],
                "quantity": "2",
                "unit": "ea",
                "availability": "available",
                "quality": "released",
                "external_holds": [],
                "external_holds_complete": True,
            }
            named = [
                {
                    "kind": k,
                    "purpose": self.basis["purpose"],
                    "operation_id": "assembly",
                    "status": "accepted",
                    "valid_from": at.isoformat(),
                    "valid_until": until.isoformat(),
                    "named_decision_id": str(uuid4()),
                    "actor_id": self.actor,
                }
                for k in ("acceptance", "calibration")
            ]
            calendar = {
                "calendar_id": "wave22-calendar-" + identity,
                "version": "1",
                "timezone": "UTC",
                "timezone_rules_sha256": frozen_timezone("UTC")[1],
                "weekly": [
                    {"weekday": d, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                    for d in range(7)
                ],
            }
            lines = [
                canonical(observed),
                canonical(
                    {
                        "nature": "synthetic",
                        "equipment_id": self.data["equipment_id"],
                        "capacity": "1",
                        "external_occupancies": [],
                        "external_occupancies_complete": True,
                    }
                ),
                canonical({"nature": "synthetic", "decisions": named}),
                canonical(calendar),
            ]
            # Freeze generated synthetic named IDs and all original source bytes BEFORE
            # their registration; a stopped/recovered capture never recreates decisions.
            draft = self.data.get("operational_draft")
            if draft is None:
                draft = {
                    "raw": deepcopy(raw),
                    "scope": scope,
                    "observed": observed,
                    "named": named,
                    "calendar": calendar,
                    "lines": lines,
                }
                self.data["operational_draft"] = draft
                self.save()
            elif canonical(draft["raw"]) != canonical(raw):
                raise Stop("ORIGINAL_OPERATIONAL_OBSERVATION_CHANGED")
            scope, observed, named, calendar, lines = (
                draft[key] for key in ("scope", "observed", "named", "calendar", "lines")
            )
            refs = self.artifact("新库存与专用制造资源", lines)
            resource = {
                "resource": {"id": self.data["equipment_id"], "revision": 1, "kind": "equipment"},
                "purposes": [self.basis["purpose"]],
                "operation_ids": ["assembly"],
                "lifecycle": "active",
                "maintenance": [],
                "calendar": calendar,
                "calendar_sources": [refs[3]],
                "capacity": "1",
                "external_occupancies": [],
                "external_occupancies_complete": True,
                "sources": [refs[1]],
                "facts": [{**decision, "sources": [refs[2]]} for decision in named],
            }
            fact = FactInput.model_validate(
                {
                    "build_id": build["id"],
                    "expected_build_revision": build["revision"],
                    "scope": scope,
                    "external_id": "wave22-operational-" + identity,
                    "valid_from": at.isoformat(),
                    "valid_until": until.isoformat(),
                    "materials_scope_complete": True,
                    "materials": [
                        {
                            "key": {
                                k: observed[k] for k in ("source_system", "pool_id", "material_id")
                            },
                            "version": 1,
                            "observed_at": observed["observed_at"],
                            "stage": "on_hand",
                            "quantity": "2",
                            "unit": "ea",
                            "availability": "available",
                            "quality": "released",
                            "external_holds": [],
                            "external_holds_complete": True,
                            "sources": [refs[0]],
                        }
                    ],
                    "resources": [resource],
                    "requirements": [
                        {
                            "operation_key": "assembly",
                            "uses": [{"resource": resource["resource"], "units": "1"}],
                            "sources": [refs[1]],
                        }
                    ],
                    "sources": refs,
                    "reason": "新独立本地合成余额与具名资源决定；不替代真实生产资格",
                }
            )
            binding = {
                "build_id": build["id"],
                "build_revision": build["revision"],
                "project_id": self.basis["scope"]["project_id"],
                "scope": fact.scope.model_dump(mode="json"),
                "engineering_configuration_id": self.basis["configuration"]["engineering_id"],
                "engineering_configuration_revision": self.basis["configuration"][
                    "engineering_revision"
                ],
                "manufacturing_configuration_id": self.basis["configuration"]["manufacturing_id"],
                "manufacturing_configuration_revision": self.basis["configuration"][
                    "manufacturing_revision"
                ],
            }
            self.data.update(
                operational_input=fact.model_dump(mode="json"),
                operational_binding=binding,
                operational_request_key=str(uuid4()),
                operational_command_id=str(uuid4()),
            )
            self.save()
        fact = FactInput.model_validate(self.data["operational_input"])
        profile = {
            "tenant_id": self.basis["scope"]["tenant_id"],
            "product_id": self.pid,
            "issuer_key": "wave22-operational-" + self.data["case_id"],
            "issuer_version": "v1",
            "decisions": [
                {
                    "binding": self.data["operational_binding"],
                    "resource": r.resource.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                }
                for r in fact.resources
                for decision in r.facts
            ],
        }
        private_write(self.directory / "operational-profile.json", profile)
        target = self.target()
        engine = engine_for(target["app_url"])
        (issuer,) = configure_local_profiles(engine, [profile])
        ctx = Context(UUID(self.basis["scope"]["tenant_id"]), UUID(self.actor), UUID(self.actor))
        self.data["operational_stage"] = "sending"
        self.save()
        try:
            with tenant_session(engine, ctx.tenant_id) as session:
                result = import_operational_fact(
                    session,
                    ctx,
                    issuer,
                    fact,
                    request_key=self.data["operational_request_key"],
                    command_id=UUID(self.data["operational_command_id"]),
                )
        except Exception:
            self.data["operational_stage"] = "unknown"
            self.save()
            raise
        receipt(
            result,
            operation="build.operational_facts.import",
            family="build_operational_fact",
            actor=self.actor,
        )
        self.data["receipts"]["operational"] = result
        self.data["operational_stage"] = "saved"
        self.data["phase"] = "operational_saved_api_profile_reload_required"
        self.save()

    def assess(self):
        old = self.resume("assessment", "build.readiness.compute", "build_execution_assessment")
        if old is None:
            self.saved("operational")
            build = self.selected_build()
            scope = self.data["operational_input"]["scope"]
            payload = {
                "build_id": build["id"],
                "expected_build_revision": build["revision"],
                "execution_scope": {
                    "purpose": scope["purpose"],
                    "quantity": scope["quantity"],
                    "unit": scope["unit"],
                    "site": scope["site"],
                    "window_start": scope["window"]["start"],
                    "window_end": scope["window"]["finish"],
                    "window_timezone": scope["window"]["original_timezone"],
                },
                "previous_assessment_id": None,
                "expected_previous_revision": 0,
                "reason": "按本轮固定新余额与资源核对准备度；未知不得推进开工",
            }
            inputs = self.http(
                "POST", f"/v1/products/{self.pid}/build-start/assessment-inputs", body=payload
            )
            if inputs["result"].get("candidate_ready") is not True:
                raise Stop("CURRENT_OPERATIONAL_READY_REQUIRED")
            self.submit(
                "assessment",
                "build.readiness.compute",
                payload,
                inputs["required_source_read_set"],
                "build_execution_assessment",
            )
        self.data["phase"] = "assessed_professional_approval_pending"
        self.save()

    def authorize(self, role, raw):
        operation, label = f"build.{role}.authorize", "approve-" + role
        if self.resume(label, operation, "build_authorization") is not None:
            return
        state = self.get("build-start")
        assessment = self.saved("assessment")
        bid = self.saved("build")["subject_id"]
        found = [v for v in state["assessments"] if v["id"] == assessment["subject_id"]]
        if (
            len(found) != 1
            or found[0]["is_current"] is not True
            or (state["capabilities_by_build"][bid].get(role + "_approve") is not True)
        ):
            raise Stop("CURRENT_NAMED_" + role.upper() + "_AUTHORITY_REQUIRED")
        if (
            type(raw) is not dict
            or set(raw) != {"professional_assessments", "accepted_controls", "sources", "reason"}
            or (
                set(raw["accepted_controls"]) != set(CONTROLS)
                or [v["rule_id"] for v in raw["professional_assessments"]]
                != list(PROFESSIONAL_RULES[role])
            )
        ):
            raise Stop("EXPLICIT_PROFESSIONAL_ASSESSMENTS_AND_CONTROLS_REQUIRED")
        row = found[0]
        end = self.data["operational_input"]["scope"]["window"]["finish"]
        payload = {
            "assessment_id": row["id"],
            "expected_assessment_revision": row["revision"],
            "expected_assessment_sha256": row["snapshot_sha256"],
            "action": "approve",
            "previous_decision_id": None,
            "expected_previous_revision": 0,
            "valid_until": end,
            **raw,
        }
        self.submit(
            label,
            operation,
            payload,
            reads(
                row["required_source_read_set"],
                ref_reads(raw["sources"]),
                *[ref_reads(v["sources"]) for v in raw["professional_assessments"]],
            ),
            "build_authorization",
        )

    def occurred_source(self, label, raw, material):
        if label not in self.data["events"]:
            line = occurred_json(raw, kind=label, material=material, at=datetime.now(UTC))
            self.data["events"][label] = {"raw": deepcopy(raw), "line": line}
            self.save()  # Freeze the explicitly provided event before source registration.
        elif canonical(self.data["events"][label]["raw"]) != canonical(raw):
            raise Stop("ORIGINAL_OCCURRED_EVENT_CHANGED")
        event = self.data["events"][label]
        if "reference" not in event:
            event["reference"] = self.artifact(label, [event["line"]])[0]
            self.save()
        return event["reference"], event["raw"]["occurred_at"]

    def start(self, raw):
        if self.resume("start", "build.start", "build_start") is not None:
            return
        state = self.get("build-start")
        bid = self.saved("build")["subject_id"]
        if state["capabilities_by_build"][bid].get("start") is not True:
            raise Stop("CURRENT_START_CAPABILITY_REQUIRED")
        aid = self.saved("assessment")["subject_id"]
        assessment = next(v for v in state["assessments"] if v["id"] == aid)
        config = self.basis["configuration"]
        ref, clock = self.occurred_source(
            "start",
            raw,
            {
                "build_id": bid,
                "purpose": self.basis["purpose"],
                "engineering_configuration_id": config["engineering_id"],
                "manufacturing_configuration_id": config["manufacturing_id"],
            },
        )
        engineering, manufacturing = (
            self.saved("approve-engineering"),
            self.saved("approve-manufacturing"),
        )
        payload = {
            "assessment_id": aid,
            "expected_assessment_revision": assessment["revision"],
            "expected_assessment_sha256": assessment["snapshot_sha256"],
            "engineering_authorization_id": engineering["subject_id"],
            "expected_engineering_authorization_revision": engineering["subject_revision"],
            "manufacturing_authorization_id": manufacturing["subject_id"],
            "expected_manufacturing_authorization_revision": manufacturing["subject_revision"],
            "occurred_at": clock,
            "occurred_timezone": "UTC",
            "event_source": ref,
            "reason": "具名记录已经发生的本地合成内部开工；不代表真实生产启用",
        }
        self.submit(
            "start",
            "build.start",
            payload,
            reads(
                assessment["required_source_read_set"],
                state["capabilities_by_build"][bid]["required_source_read_set"],
                ref_reads([ref]),
            ),
            "build_start",
        )
        self.data["phase"] = "internal_synthetic_started_not_test_qualified"
        self.save()

    def physical(self, kind, raw):
        operations = {
            "actual": ("build.configuration.actual.record", "actual_configuration"),
            "lot": ("build.output.record", "build_lot"),
            "samples": ("build.sample.allocate", "sample_allocation"),
        }
        operation, family = operations[kind]
        if self.resume(kind, operation, family) is not None:
            return
        self.saved("start")
        build, config = self.selected_build(), self.basis["configuration"]
        if kind == "samples":
            lot = self.saved("lot")
            payload = {
                "lot_id": lot["subject_id"],
                "expected_lot_revision": lot["subject_revision"],
                "samples": [
                    {
                        "label": f"Wave22-{self.data['case_id'][:8]}-A{i}",
                        "operation_key": "assembly",
                        "cavity": "A",
                        "custodian_id": self.actor,
                        "location": "本地合成内部保留",
                        "availability": "unknown",
                    }
                    for i in (1, 2)
                ],
                "sources": [self.data["events"]["lot"]["reference"]],
                "reason": "仅分配本批两件独立A身份；不预约、不交样、不自授测试资格",
            }
            basis_reads = self.get("build-execution")["lots"]
            row = next(v for v in basis_reads if v["id"] == lot["subject_id"])
            self.submit(kind, operation, payload, row["required_source_read_set"], family)
            self.data["phase"] = "two_A_identities_saved_readiness_not_asserted"
            self.save()
            return
        material = {
            "build_id": build["id"],
            "engineering_configuration_id": config["engineering_id"],
            "manufacturing_configuration_id": config["manufacturing_id"],
        }
        if kind == "lot":
            actual = self.saved("actual")
            material = {
                "build_id": build["id"],
                "actual_configuration_id": actual["subject_id"],
                "observed_unit_count": 2,
                "unit": "ea",
                "nature": "synthetic",
            }
        ref, clock = self.occurred_source(kind, raw, material)
        if aware(clock) < aware(self.data["events"]["start"]["raw"]["occurred_at"]):
            raise Stop("PHYSICAL_EVENT_BEFORE_START")
        payload = {
            "build_id": build["id"],
            "expected_build_revision": build["revision"],
            "sources": [ref],
            "reason": "仅记录本轮已发生的本地合成实物观察，不作为放行",
        }
        if kind == "actual":
            compared = self.get(
                "build-execution/compare",
                build_id=build["id"],
                engineering_configuration_id=config["engineering_id"],
                manufacturing_configuration_id=config["manufacturing_id"],
            )
            if compared["differences"] or compared["source_status"] != "current":
                raise Stop("EXACT_SAME_PLAN_ACTUAL_REQUIRED")
            payload.update(
                actual_engineering_configuration_id=config["engineering_id"],
                expected_actual_engineering_revision=config["engineering_revision"],
                actual_manufacturing_configuration_id=config["manufacturing_id"],
                expected_actual_manufacturing_revision=config["manufacturing_revision"],
                observed_at=clock,
                differences=[],
            )
            complete = compared["required_source_read_set"]
        else:
            row = next(
                v
                for v in self.get("build-execution")["actual_configurations"]
                if v["id"] == actual["subject_id"]
            )
            if aware(clock) < aware(row["observed_at"]):
                raise Stop("LOT_OBSERVATION_BEFORE_ACTUAL")
            payload.update(
                actual_configuration_id=actual["subject_id"],
                expected_actual_configuration_revision=actual["subject_revision"],
                lot_label="wave22-two-A-" + self.data["case_id"],
                observed_unit_count=2,
                unit="ea",
                observation={
                    "system": "explicit-synthetic-wave22",
                    "external_id": "wave22-output-" + self.data["case_id"],
                    "nature": "synthetic",
                    "occurred_at": clock,
                },
            )
            complete = row["required_source_read_set"]
        self.submit(kind, operation, payload, reads(complete, ref_reads([ref])), family)

    def ready(self, raw):
        """Separate purpose-specific readiness facts, never rewrites Sample.availability."""
        allocation = self.saved("samples")
        bid = self.saved("build")["subject_id"]
        roster = [
            v
            for v in self.get("build-execution")["samples"]
            if v["allocation_id"] == allocation["subject_id"]
        ]
        roster.sort(key=lambda v: v["label"])
        if len(roster) != 2 or any(v["cavity"] != "A" for v in roster):
            raise Stop("EXACT_TWO_A_SAMPLE_IDENTITIES_REQUIRED")
        if "ready_events" not in self.data:
            if (
                type(raw) is not dict
                or set(raw) != {"events"}
                or type(raw["events"]) is not list
                or len(raw["events"]) != 2
            ):
                raise Stop("TWO_EXPLICIT_OCCURRED_READY_EVENTS_REQUIRED")
            source_lines = []
            by_sample = {v["sample_id"]: v for v in raw["events"]}
            if len(by_sample) != 2:
                raise Stop("EXACT_TWO_A_SAMPLE_IDENTITIES_REQUIRED")
            for sample in roster:
                event = by_sample.get(sample["id"])
                source_lines.append(
                    occurred_json(
                        event,
                        kind="sample_ready",
                        material={
                            "sample_id": sample["id"],
                            "lot_id": sample["lot_id"],
                            "actual_configuration_id": sample["actual_configuration_id"],
                            "build_id": bid,
                            "state": "ready",
                            "purpose": self.basis["purpose"],
                        },
                        at=datetime.now(UTC),
                    )
                )
                if aware(event["occurred_at"]) < aware(
                    self.data["events"]["lot"]["raw"]["occurred_at"]
                ):
                    raise Stop("READY_EVENT_BEFORE_LOT_OBSERVATION")
            self.data["ready_events"] = {"raw": deepcopy(raw), "lines": source_lines}
            self.save()
        events = self.data["ready_events"]
        if raw is not None and canonical(raw) != canonical(events["raw"]):
            raise Stop("ORIGINAL_READY_EVENTS_CHANGED")
        if "references" not in events:
            events["references"] = self.artifact("两件A已发生实物就绪", events["lines"])
            self.save()
        for i, sample in enumerate(roster):
            label = "ready-A" + str(i + 1)
            operation = "build.sample.readiness.record"
            if self.resume(label, operation, "sample_readiness_fact") is not None:
                continue
            projection = self.get("sample-handoff", build_id=bid, purpose=self.basis["purpose"])
            cap = projection["capabilities_by_sample"][sample["id"]]
            if cap["ready"] is not True or cap["purpose"] != self.basis["purpose"]:
                raise Stop("CURRENT_PURPOSE_MANUFACTURING_READY_AUTHORITY_REQUIRED")
            ref = events["references"][i]
            event = next(v for v in events["raw"]["events"] if v["sample_id"] == sample["id"])
            self.submit(
                label,
                operation,
                {
                    "sample_id": sample["id"],
                    "expected_sample_revision": sample["revision"],
                    "previous_readiness_id": cap["previous_readiness_id"],
                    "expected_previous_revision": cap["expected_previous_revision"],
                    "state": "ready",
                    "purpose": self.basis["purpose"],
                    "occurred_at": event["occurred_at"],
                    "occurred_timezone": "UTC",
                    "event_source": ref,
                    "sources": [ref],
                    "reason": "具名记录本地合成实物已就绪；品质接收、方法与开测须独立办理",
                },
                reads(cap["required_source_read_set"], ref_reads([ref])),
                "sample_readiness_fact",
            )
        self.data["phase"] = "two_A_readiness_facts_saved_no_handoff_or_test_run"
        self.save()

    def readback(self):
        """Explicit new checkpoint handoff to B; every consumer must recheck live owner state."""
        for label in ("start", "actual", "lot", "samples", "ready-A1", "ready-A2"):
            self.saved(label)
        build = self.selected_build()
        executions = self.get("build-execution")
        bid = build["id"]
        start_view = self.get("build-start")
        cap = start_view["capabilities_by_build"][bid]
        if (
            cap.get("execution_qualification") != "limited_current"
            or cap.get("stop_required") is not False
        ):
            raise Stop("CURRENT_LIMITED_BUILD_QUALIFICATION_REQUIRED")
        starts = [v for v in start_view["starts"] if v["id"] == self.saved("start")["subject_id"]]
        actuals = [
            v
            for v in executions["actual_configurations"]
            if v["id"] == self.saved("actual")["subject_id"]
        ]
        lots = [v for v in executions["lots"] if v["id"] == self.saved("lot")["subject_id"]]
        if any(len(v) != 1 for v in (starts, actuals, lots)):
            raise Stop("EXACT_SAVED_PHYSICAL_READBACK_REQUIRED")
        start, actual, lot = starts[0], actuals[0], lots[0]
        if any(
            v.get("source_status") != "current" or v.get("visibility") != "product"
            for v in (start, actual, lot)
        ):
            raise Stop("CURRENT_SHARED_PHYSICAL_SOURCES_REQUIRED")
        if (
            lot["observed_unit_count"] != 2
            or lot["unit"] != "ea"
            or lot["actual_configuration_id"] != actual["id"]
        ):
            raise Stop("EXACT_TWO_UNIT_LOT_REQUIRED")
        samples = [
            v
            for v in executions["samples"]
            if v["allocation_id"] == self.saved("samples")["subject_id"]
        ]
        samples.sort(key=lambda v: v["label"])
        if (
            len(samples) != 2
            or len({v["id"] for v in samples}) != 2
            or any(
                v["cavity"] != "A"
                or v["lot_id"] != lot["id"]
                or v["actual_configuration_id"] != actual["id"]
                or v["source_status"] != "current"
                or v["visibility"] != "product"
                for v in samples
            )
        ):
            raise Stop("EXACT_SHARED_TWO_A_SAMPLES_REQUIRED")
        handed = self.get("sample-handoff", build_id=bid, purpose=self.basis["purpose"])
        sample_views, all_reads = (
            [],
            [build["required_source_read_set"], cap["required_source_read_set"]],
        )
        for i, sample in enumerate(samples):
            inspected = handed["availability_by_sample"][sample["id"]]
            fixed = self.saved("ready-A" + str(i + 1))
            current = inspected["current_readiness"]
            if (
                inspected["availability"] != "ready"
                or current is None
                or (current["id"], current["revision"], current["purpose"], current["state"])
                != (fixed["subject_id"], fixed["subject_revision"], self.basis["purpose"], "ready")
            ):
                raise Stop("EXACT_CURRENT_PURPOSE_SAMPLE_READY_REQUIRED")
            sample_views.append(
                {
                    **deepcopy(sample),
                    "readiness": deepcopy(current),
                    "purpose_availability": inspected["availability"],
                }
            )
            all_reads.append(inspected["required_source_read_set"])
        all_reads.extend(v["required_source_read_set"] for v in (start, actual, lot))
        self.data["continuation"] = {
            "schema_version": "wave22-shared-build-continuation-v1",
            "state": "readback_saved_requires_consumer_recheck",
            "scope": deepcopy(self.basis["scope"]),
            "purpose": self.basis["purpose"],
            "maker_id": self.actor,
            "build": {
                k: deepcopy(build[k])
                for k in (
                    "id",
                    "revision",
                    "name",
                    "unit",
                    "planned_quantity",
                    "owner_id",
                    "visibility",
                )
            },
            "configuration": deepcopy(self.basis["configuration"]),
            "execution_scope": deepcopy(self.data["operational_binding"]["scope"]),
            "start": deepcopy(start),
            "actual_configuration": deepcopy(actual),
            "lot": deepcopy(lot),
            "samples": sample_views,
            "required_source_read_set": reads(*all_reads),
            "readback_at": datetime.now(UTC).isoformat(),
            "synthetic_only": True,
            "test_qualification": None,
            "professional_review": None,
            "effectiveness": None,
            "close": False,
        }
        self.save()


def main():
    parser = argparse.ArgumentParser(
        description="Root-only new shared synthetic Build; never auto-confirms T1/T2"
    )
    parser.add_argument(
        "step",
        choices=(
            "plan",
            "operational",
            "assess",
            "engineering",
            "manufacturing",
            "start",
            "actual",
            "lot",
            "samples",
            "ready",
            "readback",
        ),
    )
    parser.add_argument("--marker", required=True)
    parser.add_argument(
        "--material", type=Path, help="Owned 0600 actual observation/professional input JSON"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--confirm", help="Exact one prepared label; requires private review digest"
    )
    parser.add_argument("--review-digest")
    actions.add_argument("--recover", help="Retry only this exact original unknown command")
    args = parser.parse_args()
    if bool(args.confirm) != bool(args.review_digest) or (
        args.review_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", args.review_digest)
    ):
        parser.error("--confirm requires its exact 64-character review digest")
    directory = root_for(__file__) / ".local/wave22-build-staged"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lockpath = directory / ".lock"
    descriptor = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            tool = SharedBuild(
                args.marker,
                confirm=args.confirm,
                review_digest=args.review_digest,
                recover=args.recover,
            )
            raw = private_read(args.material) if args.material else None
            if args.step in {"plan", "assess", "readback"}:
                getattr(tool, args.step)()
            elif args.step in {"engineering", "manufacturing"}:
                tool.authorize(args.step, raw)
            elif args.step in {"actual", "lot", "samples"}:
                tool.physical(args.step, raw)
            else:
                getattr(tool, args.step)(raw)
            tool.data["phase"] = saved_phase(tool.data)
            tool.save()
            print(
                json.dumps(
                    {
                        "state": tool.data["phase"],
                        "saved_receipts": len(tool.data["receipts"]),
                        "synthetic_only": True,
                        "test_qualification": None,
                        "release": False,
                    }
                )
            )
    except Pending as error:
        print(
            json.dumps(
                {
                    "state": error.stage,
                    "label": error.label,
                    "review_digest": error.digest,
                    "manual_review_required": True,
                }
            )
        )
        return 2
    except Exception as error:
        # Fixed-code only. No raw exception, URL, SQL, token or private source logging.
        code = (
            str(error) if isinstance(error, Stop) else "EXECUTION_STOPPED_CHECK_PRIVATE_CHECKPOINT"
        )
        print(json.dumps({"state": "stopped", "code": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
