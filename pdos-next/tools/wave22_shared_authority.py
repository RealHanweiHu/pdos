"""Root-run, isolated shared-case synthetic publication; never production authority.

Importing this tool performs no configuration, IO, connection or publication.
Root alone applies/runs it after actual shared foundation receipts exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5


def layout_root(source):
    source = Path(source).resolve()
    if source.name != "wave22_shared_authority.py":
        raise ValueError("Unexpected tool filename")
    if source.parent.name == "tools":
        return source.parent.parent
    if source.parent.name == "wave22-authority-staged" and source.parent.parent.name == ".local":
        return source.parents[2]
    raise ValueError("Unexpected isolated tool layout")


ROOT = layout_root(__file__)
EXPECTED_PORT = 62513
ROLES = ("maker", "observer", "independent_reviewer")
FOUNDATION_OPERATIONS = {
    "product": ("product.create", "product"),
    "native-source": ("evidence.artifact.register", "artifact"),
    "definition": ("product.definition.draft", "definition_revision"),
    "project": ("project.create", "project"),
    "bom": ("engineering.bom.revise", "bom_revision"),
    "engineering": ("engineering.configuration.create", "engineering_configuration"),
    "manufacturing": ("npi.process.revise", "process_revision"),
}
GROUPS = (
    (
        "maker-engineering",
        "maker",
        "engineering",
        (
            "build.engineering.authorize",
            "quality.issue.create",
            "quality.issue.merge",
            "quality.issue.triage",
            "quality.issue.containment.record",
            "quality.capa.draft",
            "quality.capa.actions.complete",
            "quality.capa.followup.link",
            "quality.capa.verification.candidate.record",
        ),
    ),
    (
        "maker-manufacturing",
        "maker",
        "manufacturing",
        (
            "build.manufacturing.authorize",
            "build.start",
            "build.sample.readiness.record",
            "verification.handoff.offer",
        ),
    ),
    (
        "maker-quality",
        "maker",
        "quality",
        ("quality.issue.root_cause.decide", "quality.capa.verification.rule.import"),
    ),
    (
        "observer-quality-front",
        "observer",
        "quality",
        (
            "verification.request.create",
            "verification.method.prepare",
            "verification.actual_method.prepare",
            "verification.handoff.accept",
            "test.run.plan",
            "verification.schedule.promise",
            "test.run.start",
        ),
    ),
    (
        "observer-quality-results",
        "observer",
        "quality",
        (
            "test.results.import",
            "test.result.compute",
            "test.run.review",
            "test.disposition.decide",
            "quality.capa.observation.record",
        ),
    ),
    (
        "independent-reviewer-quality",
        "independent_reviewer",
        "quality",
        ("quality.capa.verification.review",),
    ),
)


class Blocked(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def strict_json(value):
    def pairs(rows):
        result = {}
        for key, item in rows:
            if key in result:
                raise Blocked("DUPLICATE_JSON_FIELD")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: invalid_json())


def invalid_json():
    raise Blocked("INVALID_JSON_VALUE")


def aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise Blocked("AWARE_REAL_CLOCK_REQUIRED")
    return value.astimezone(UTC)


def positive(value):
    if type(value) is not int or value < 1:
        raise Blocked("EXACT_REVISION_REQUIRED")
    return value


def private_read(path):
    path = Path(path)
    if not path.exists() or path.is_symlink() or path.parent.is_symlink():
        raise Blocked("PRIVATE_INPUT_REQUIRED")
    mode = path.stat()
    if (
        not stat.S_ISREG(mode.st_mode)
        or stat.S_IMODE(mode.st_mode) != 0o600
        or mode.st_uid != os.getuid()
    ):
        raise Blocked("PRIVATE_INPUT_REQUIRED")
    return strict_json(path.read_text())


def private_write(path, value):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise Blocked("PRIVATE_OUTPUT_SYMLINK_REFUSED")
    if path.exists():
        private_read(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(uuid4()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class FoundationBasis:
    marker: str
    case_id: UUID
    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    purpose: str
    actors: tuple[UUID, UUID, UUID]
    expires_at: datetime
    source_id: UUID
    source_revision: int
    source_content_hash: str
    source_text_sha256: str
    receipts_json: str

    def actor(self, role):
        return self.actors[ROLES.index(role)]

    def material(self):
        return {
            "marker": self.marker,
            "case_id": str(self.case_id),
            "tenant_id": str(self.tenant_id),
            "product_id": str(self.product_id),
            "project_id": str(self.project_id),
            "purpose": self.purpose,
            "actors": {role: str(self.actor(role)) for role in ROLES},
            "expires_at": self.expires_at.isoformat(),
            "source": {
                "id": str(self.source_id),
                "revision": self.source_revision,
                "stored_content_hash": self.source_content_hash,
                "raw_text_sha256": self.source_text_sha256,
            },
            "receipts": strict_json(self.receipts_json),
        }


def foundation_basis(data, *, marker, at):
    """Only a structural projection; actual saved rows must independently match."""
    at = aware(at)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != "wave21-shared-foundation-v1"
        or data.get("marker") != marker
        or data.get("phase") != "foundation_saved_not_build_started"
        or data.get("visibility") != "product"
        or set(data.get("actors", {})) != set(ROLES)
    ):
        raise Blocked("ACTUAL_SHARED_FOUNDATION_REQUIRED")
    actors = tuple(UUID(data["actors"][role]["id"]) for role in ROLES)
    if len(set(actors)) != 3:
        raise Blocked("THREE_DISTINCT_HUMANS_REQUIRED")
    scope = data.get("scope", {})
    if (
        scope
        != {
            "tenant_id": data["tenant_id"],
            "product_id": data["product_id"],
            "project_id": data["project_id"],
        }
        or not isinstance(data.get("purpose"), str)
        or not data["purpose"].strip()
    ):
        raise Blocked("FOUNDATION_SCOPE_MISMATCH")
    expires = aware(data["bootstrap_expires_at"])
    if expires <= at or aware(data["created_at"]) > at:
        raise Blocked("FOUNDATION_EXPIRED")
    receipts = {}
    for label, (operation, family) in FOUNDATION_OPERATIONS.items():
        receipt = data.get("receipts", {}).get(label)
        if (
            not isinstance(receipt, dict)
            or receipt.get("operation") != operation
            or receipt.get("subject_type") != family
            or receipt.get("writer_id") != str(actors[0])
            or receipt.get("requester_id") != str(actors[0])
        ):
            raise Blocked("FOUNDATION_RECEIPT_REQUIRED")
        UUID(receipt["id"])
        UUID(receipt["subject_id"])
        revision = positive(receipt["subject_revision"])
        if (
            receipt.get("result", {}).get("id") != receipt["subject_id"]
            or type(receipt["result"].get("revision")) is not int
            or receipt["result"]["revision"] != revision
        ):
            raise Blocked("FOUNDATION_RECEIPT_MISMATCH")
        receipts[label] = deepcopy(receipt)
    if (
        receipts["product"]["subject_id"] != data["product_id"]
        or receipts["project"]["subject_id"] != data["project_id"]
    ):
        raise Blocked("FOUNDATION_SCOPE_MISMATCH")
    source = receipts["native-source"]
    reads = [{"artifact_id": source["subject_id"], "expected_revision": source["subject_revision"]}]
    if canonical(
        data.get("sources", {}).get("foundation", {}).get("required_source_read_set")
    ) != canonical(reads):
        raise Blocked("FOUNDATION_SOURCE_MISMATCH")
    readback = data.get("readback", {})
    if set(readback) != set(ROLES):
        raise Blocked("SHARED_ACTOR_READBACK_REQUIRED")
    if any(
        not isinstance(readback[role], dict)
        or set(readback[role])
        != {
            "shared_objects",
            "stored_content_hash",
            "raw_text_sha256",
            "professional_qualification",
        }
        or type(readback[role].get("shared_objects")) is not int
        or readback[role]["shared_objects"] != 6
        or readback[role]["professional_qualification"] is not None
        for role in ROLES
    ):
        raise Blocked("FOUNDATION_SOURCE_MISMATCH")
    hashes = []
    for name in ("stored_content_hash", "raw_text_sha256"):
        values = {readback[role][name] for role in ROLES}
        if len(values) != 1:
            raise Blocked("FOUNDATION_SOURCE_MISMATCH")
        (sha,) = values
        if type(sha) is not str or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise Blocked("FOUNDATION_SOURCE_MISMATCH")
        hashes.append(sha)
    return FoundationBasis(
        marker,
        UUID(data["case_id"]),
        UUID(data["tenant_id"]),
        UUID(data["product_id"]),
        UUID(data["project_id"]),
        data["purpose"],
        actors,
        expires,
        UUID(source["subject_id"]),
        source["subject_revision"],
        *hashes,
        canonical(receipts),
    )


def profiles_for(basis):
    return {
        "professional": {
            "tenant_id": str(basis.tenant_id),
            "product_id": str(basis.product_id),
            "project_id": str(basis.project_id),
            "key": "wave22-professional-" + str(basis.case_id),
            "version": "v1",
        },
        "quality": {
            "tenant_id": str(basis.tenant_id),
            "product_id": str(basis.product_id),
            "project_id": str(basis.project_id),
            "issuer_key": "wave22-quality-" + str(basis.case_id),
            "issuer_version": "v1",
        },
    }


def append_profile(existing, new, *, family):
    if family not in {"professional", "quality"}:
        raise Blocked("EXACT_PROFILE_FAMILY_REQUIRED")
    if type(existing) is not list or not 1 <= len(existing) < 20:
        raise Blocked("EXPLICIT_RETAINED_PROFILE_LIST_REQUIRED")
    key_field, version_field = (
        ("key", "version") if family == "professional" else ("issuer_key", "issuer_version")
    )
    required = {"tenant_id", "product_id", key_field, version_field}
    if family == "quality":
        required.add("project_id")
    keys, scopes = set(), set()
    for value in [*existing, new]:
        if (
            type(value) is not dict
            or not required <= set(value)
            or not set(value) <= (required | {"project_id"})
        ):
            raise Blocked("EXACT_PROFILE_FIELDS_REQUIRED")
        scope = (
            UUID(value["tenant_id"]),
            UUID(value["product_id"]),
            UUID(value["project_id"]) if value.get("project_id") is not None else None,
        )
        if family == "quality" and scope[2] is None:
            raise Blocked("EXACT_PROFILE_FIELDS_REQUIRED")
        for field in (key_field, version_field):
            if (
                type(value[field]) is not str
                or value[field].strip() != value[field]
                or not (1 <= len(value[field]) <= 100)
            ):
                raise Blocked("EXACT_ISSUER_NAME_REQUIRED")
        if scope in scopes or value[key_field] in keys:
            raise Blocked("PROFILE_SCOPE_OR_KEY_CONFLICT")
        keys.add(value[key_field])
        scopes.add(scope)
    result = deepcopy(existing) + [deepcopy(new)]
    if canonical(result[:-1]) != canonical(existing):
        raise Blocked("OLD_PROFILE_REPLACED")
    return result


def publications(basis, *, issued_at, valid_until):
    """Host-owned synthetic publication only; no occurrence/test/completion claims."""
    issued_at, valid_until = aware(issued_at), aware(valid_until)
    if valid_until > basis.expires_at or valid_until <= issued_at:
        raise Blocked("FIXED_PUBLICATION_INTERVAL_REQUIRED")
    profiles = profiles_for(basis)
    facts, lines = [], []
    for group, actor_role, role, operations in GROUPS:
        for kind in ("duty", "qualification"):
            label = group + "-" + kind
            external = f"wave22-{basis.case_id}-{label}"
            payload = {
                "product_id": str(basis.product_id),
                "project_id": str(basis.project_id),
                "subject_id": str(basis.actor(actor_role)),
                "external_id": external,
                "kind": kind,
                "role": role,
                "operations": sorted(operations),
                "purposes": [basis.purpose],
                "state": "active",
                "valid_from": (issued_at - timedelta(minutes=1)).isoformat(),
                "valid_until": valid_until.isoformat(),
                "approval": {
                    "system": profiles["professional"]["key"],
                    "external_id": external,
                    "version": "v1",
                    "approved_by": "Root controlled local synthetic publisher; no production grant",
                    "issued_at": issued_at.isoformat(),
                },
                "reason": "New shared-case synthetic duty/qualification; old scopes retained",
            }
            lines.append(
                canonical(
                    {
                        "schema_version": "wave22-synthetic-professional-publication-v1",
                        "tenant_id": str(basis.tenant_id),
                        "issuer": {**profiles["professional"], "nature": "synthetic"},
                        "visibility": "product",
                        "publisher_id": str(basis.actor("maker")),
                        "fact": payload,
                    }
                )
            )
            facts.append({"label": label, "line": len(lines), "payload": payload})
    external = f"wave22-{basis.case_id}-quality-policy"
    policy = {
        "external_id": external,
        "purpose": basis.purpose,
        "risk": "high",
        "independent_verification": True,
        "state": "active",
        "valid_from": (issued_at - timedelta(minutes=1)).isoformat(),
        "valid_until": valid_until.isoformat(),
        "approval": {
            "system": profiles["quality"]["issuer_key"],
            "external_id": external,
            "version": "v1",
            "approved_by": "Root explicit local synthetic risk publication; no production policy",
            "issued_at": issued_at.isoformat(),
        },
    }
    lines.append(canonical(policy))
    policy_line = len(lines)
    lines.append(
        canonical(
            {
                "schema_version": "wave22-synthetic-policy-scope-v1",
                "scope": {
                    "tenant_id": str(basis.tenant_id),
                    "product_id": str(basis.product_id),
                    "project_id": str(basis.project_id),
                    "purpose": basis.purpose,
                },
                "issuer": {**profiles["quality"], "nature": "synthetic"},
                "visibility": "product",
                "publisher_id": str(basis.actor("maker")),
                "publication_sha256": content_sha(canonical(policy)),
            }
        )
    )
    return {
        "issued_at": issued_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "profiles": profiles,
        "lines": lines,
        "facts": facts,
        "policy_lines": [policy_line, len(lines)],
        "policy": {
            "product_id": str(basis.product_id),
            "project_id": str(basis.project_id),
            **policy,
            "reason": "New exact shared synthetic risk/independence policy",
        },
    }


def bound_payloads(plan, source_id, revision):
    source_id, revision = UUID(str(source_id)), positive(revision)
    lines = plan["lines"]

    def ref(number):
        quote = lines[number - 1]
        if len(quote) > 4000 or "\n" in quote or "\r" in quote:
            raise Blocked("FULL_NATIVE_PUBLICATION_LINE_REQUIRED")
        return {
            "artifact_id": str(source_id),
            "expected_revision": revision,
            "line": number,
            "quote": quote,
        }

    from pdos_next.domain.professional_authority.schemas import FactInput
    from pdos_next.domain.professional_authority.service import OPERATION_ROLES
    from pdos_next.domain.quality_execution.schemas import PolicyInput

    facts = []
    for entry in plan["facts"]:
        raw = {**entry["payload"], "sources": [ref(entry["line"])]}
        parsed = FactInput.model_validate(raw)
        if any(parsed.role not in OPERATION_ROLES.get(op, ()) for op in parsed.operations):
            raise Blocked("AUTHORITY_OPERATION_MISMATCH")
        facts.append({"label": entry["label"], "payload": parsed.model_dump(mode="json")})
    policy = PolicyInput.model_validate(
        {**plan["policy"], "sources": [ref(n) for n in plan["policy_lines"]]}
    )
    return facts, policy.model_dump(mode="json")


class AuthorityTool:
    def __init__(self, marker, *, professional_profiles=None, quality_profiles=None):
        sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
        from local_environment import read_state, verified
        from pdos_next.database import engine_for

        self.marker = str(marker)
        self.read_state, self.verified = read_state, verified
        self.checkpoint = ROOT / ".local/wave22-shared-authority.json"
        self.old_paths = {
            "professional": Path(
                professional_profiles or ROOT / ".local/professional-synthetic-profiles.json"
            ),
            "quality": Path(quality_profiles or ROOT / ".local/quality-synthetic-profiles.json"),
        }
        self.basis = foundation_basis(
            private_read(ROOT / ".local/wave21-shared-case.json"),
            marker=self.marker,
            at=datetime.now(UTC),
        )
        # No environment verification/connection is attempted for unfinished foundation.
        state = self.target()
        if str(self.basis.tenant_id) != state["preview_tenant_id"]:
            raise Blocked("FOUNDATION_TENANT_MISMATCH")
        self.engine = engine_for(state["app_url"])
        self.data = private_read(self.checkpoint) if self.checkpoint.exists() else None
        if self.data is not None and (
            self.data.get("schema_version") != "wave22-shared-authority-v1"
            or canonical(self.data.get("foundation")) != canonical(self.basis.material())
        ):
            raise Blocked("SAVED_AUTHORITY_SCOPE_CHANGED")

    def target(self):
        state = self.verified(self.read_state())
        if state["port"] != EXPECTED_PORT or str(state["marker"]) != self.marker:
            raise Blocked("EXACT_MARKED_TARGET_REQUIRED")
        return state

    def save(self):
        private_write(self.checkpoint, self.data)

    def ctx(self, role="maker"):
        from pdos_next.service import Context

        return Context(self.basis.tenant_id, self.basis.actor(role), self.basis.actor(role))

    def guard(self, s):
        from pdos_next.domain.projects.models import Project
        from pdos_next.domain.quality_execution.evidence import source_basis
        from pdos_next.models import Grant, Principal, Product, Receipt
        from pdos_next.service import digest, receipt_view, require_access, source_for
        from sqlalchemy import select

        b = self.basis
        product = s.scalar(
            select(Product)
            .where(Product.tenant_id == b.tenant_id, Product.id == b.product_id)
            .with_for_update()
        )
        project = s.scalar(
            select(Project).where(
                Project.tenant_id == b.tenant_id,
                Project.product_id == b.product_id,
                Project.id == b.project_id,
            )
        )
        if (
            product is None
            or project is None
            or (
                product.owner_id,
                product.purpose,
                project.owner_id,
                project.purpose,
                project.visibility,
                project.status,
            )
            != (b.actor("maker"), b.purpose, b.actor("maker"), b.purpose, "product", "active")
        ):
            raise Blocked("ACTUAL_FOUNDATION_SCOPE_UNAVAILABLE")
        for saved in strict_json(b.receipts_json).values():
            actual = s.get(Receipt, UUID(saved["id"]))
            if (
                actual is None
                or (actual.tenant_id, actual.product_id, actual.visibility, actual.run_id)
                != (b.tenant_id, b.product_id, "product", None)
                or (canonical(receipt_view(actual)) != canonical(saved))
            ):
                raise Blocked("ACTUAL_FOUNDATION_RECEIPT_MISMATCH")
        deadlines = [b.expires_at]
        for role in ROLES:
            actor = s.scalar(
                select(Principal).where(
                    Principal.tenant_id == b.tenant_id, Principal.id == b.actor(role)
                )
            )
            require_access(s, self.ctx(role), b.product_id, write=True, lock=True)
            if (
                actor is None
                or actor.kind != "human"
                or actor.active is not True
                or (actor.name != "Wave21 shared · " + role)
            ):
                raise Blocked("ACTUAL_HUMAN_REQUIRED")
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == b.tenant_id,
                    Grant.product_id == b.product_id,
                    Grant.principal_id == actor.id,
                )
            )
            if grant is None or grant.can_write is not True:
                raise Blocked("CURRENT_WRITE_GRANT_REQUIRED")
            deadlines.append(aware(grant.expires_at))
            source = source_for(s, self.ctx(role), b.product_id, b.source_id, b.source_revision)
            if (
                source.visibility != "product"
                or source.original_id is not None
                or (
                    source.owner_id != b.actor("maker")
                    or source.content_hash != b.source_content_hash
                    or digest(source.content) != b.source_content_hash
                    or content_sha(source.content) != b.source_text_sha256
                )
            ):
                raise Blocked("ACTUAL_SHARED_SOURCE_REQUIRED")
            _, private = source_basis(
                s,
                self.ctx(role),
                b.product_id,
                [{"artifact_id": str(source.id), "expected_revision": source.revision}],
            )
            if private:
                raise Blocked("ACTUAL_SHARED_SOURCE_REQUIRED")
        deadline = min(deadlines)
        if deadline <= datetime.now(UTC):
            raise Blocked("FOUNDATION_EXPIRED")
        return product.revision, deadline

    def validate_saved_plan(self):
        plan = self.data["plan"]
        reconstructed = publications(
            self.basis, issued_at=plan["issued_at"], valid_until=plan["valid_until"]
        )
        if canonical(plan) != canonical(reconstructed) or aware(plan["issued_at"]) > datetime.now(
            UTC
        ):
            raise Blocked("SAVED_PUBLICATION_MATERIAL_CHANGED")
        command = self.data["source_command"]
        positive(command["expected_revision"])
        if (
            command["payload"]
            != {
                "title": "Wave22 shared synthetic professional/policy publication",
                "content": "\n".join(plan["lines"]),
                "visibility": "product",
                "source_label": "Controlled local synthetic publication; no production grant",
            }
            or command["operation"] != "evidence.artifact.register"
            or (
                command["product_id"] != str(self.basis.product_id)
                or command["command_id"]
                != str(uuid5(self.basis.case_id, "wave22:authority-source"))
                or command["idempotency_key"] != f"wave22-{self.basis.case_id}-authority-source"
                or command["source_read_set"] != []
            )
        ):
            raise Blocked("ORIGINAL_SOURCE_COMMAND_CHANGED")

    def read_plan_inputs(self):
        existing = {family: private_read(path) for family, path in self.old_paths.items()}
        return {
            family: append_profile(values, profiles_for(self.basis)[family], family=family)
            for family, values in existing.items()
        }, existing

    def prepare(self):
        from pdos_next.contracts import ArtifactPayload, Command
        from pdos_next.database import tenant_session
        from pdos_next.service import execute

        self.target()
        lists, original_lists = self.read_plan_inputs()
        with tenant_session(self.engine, self.basis.tenant_id) as s:
            revision, deadline = self.guard(s)
        if self.data is None:
            plan = publications(self.basis, issued_at=datetime.now(UTC), valid_until=deadline)
            if any(len(line) > 4000 or "\n" in line or "\r" in line for line in plan["lines"]):
                raise Blocked("FULL_NATIVE_PUBLICATION_LINE_REQUIRED")
            payload = ArtifactPayload(
                title="Wave22 shared synthetic professional/policy publication",
                content="\n".join(plan["lines"]),
                visibility="product",
                source_label="Controlled local synthetic publication; no production grant",
            )
            command = Command(
                command_id=uuid5(self.basis.case_id, "wave22:authority-source"),
                idempotency_key=f"wave22-{self.basis.case_id}-authority-source",
                operation="evidence.artifact.register",
                product_id=self.basis.product_id,
                expected_revision=revision,
                payload=payload.model_dump(mode="json"),
            )
            self.data = {
                "schema_version": "wave22-shared-authority-v1",
                "foundation": self.basis.material(),
                "plan": plan,
                "original_profiles": original_lists,
                "profiles": lists,
                "source_command": command.model_dump(mode="json"),
                "receipts": {},
                "state": "publication_prepared_not_registered",
            }
            self.save()
        elif canonical(self.data["original_profiles"]) != canonical(original_lists) or (
            canonical(self.data["profiles"]) != canonical(lists)
        ):
            raise Blocked("RETAINED_PROFILE_LIST_CHANGED")
        self.validate_saved_plan()
        command = Command.model_validate(self.data["source_command"])
        with tenant_session(self.engine, self.basis.tenant_id) as s:
            self.guard(s)
            receipt = execute(s, self.ctx(), command)
        self.record_receipt("authority-source", receipt, "evidence.artifact.register", "artifact")
        self.data["state"] = "publication_saved_profiles_reload_required"
        self.save()
        self.write_profiles()
        return {
            "state": self.data["state"],
            "professional_groups": len(GROUPS),
            "professional_facts": len(GROUPS) * 2,
            "policy_facts": 1,
            "new_source_versions": 1,
            "actual_professional_imports": 0,
        }

    def record_receipt(self, label, value, operation, family):
        if (
            value.get("operation") != operation
            or value.get("subject_type") != family
            or (value.get("writer_id"), value.get("requester_id"))
            != (str(self.basis.actor("maker")), str(self.basis.actor("maker")))
        ):
            raise Blocked("IMPORT_RECEIPT_MISMATCH")
        UUID(value["id"])
        UUID(value["subject_id"])
        positive(value["subject_revision"])
        if value["result"].get("id") != value["subject_id"] or (
            type(value["result"].get("revision")) is not int
            or value["result"]["revision"] != value["subject_revision"]
        ):
            raise Blocked("IMPORT_RECEIPT_MISMATCH")
        previous = self.data["receipts"].get(label)
        if previous is not None and canonical(previous) != canonical(value):
            raise Blocked("SAVED_RECEIPT_CHANGED")
        self.data["receipts"][label] = deepcopy(value)
        self.save()

    def write_profiles(self):
        for family, values in self.data["profiles"].items():
            path = ROOT / f".local/wave22-{family}-synthetic-profiles.json"
            if path.exists() and canonical(private_read(path)) != canonical(values):
                raise Blocked("PROFILE_OUTPUT_CONFLICT")
            private_write(path, values)

    def source_guard(self, s):
        from pdos_next.domain.quality_execution.evidence import source_basis
        from pdos_next.models import Receipt
        from pdos_next.service import digest, receipt_view, source_for

        self.validate_saved_plan()
        saved = self.data["receipts"].get("authority-source")
        if saved is None:
            raise Blocked("ACTUAL_AUTHORITY_SOURCE_REQUIRED")
        receipt = s.get(Receipt, UUID(saved["id"]))
        if (
            receipt is None
            or canonical(receipt_view(receipt)) != canonical(saved)
            or (receipt.tenant_id, receipt.product_id, receipt.visibility, receipt.run_id)
            != (self.basis.tenant_id, self.basis.product_id, "product", None)
        ):
            raise Blocked("ACTUAL_AUTHORITY_SOURCE_REQUIRED")
        content = "\n".join(self.data["plan"]["lines"])
        for role in ROLES:
            row = source_for(
                s,
                self.ctx(role),
                self.basis.product_id,
                UUID(saved["subject_id"]),
                saved["subject_revision"],
            )
            if (
                row.visibility != "product"
                or row.original_id is not None
                or (
                    row.owner_id != self.basis.actor("maker")
                    or row.content != content
                    or row.content_hash != digest(content)
                )
            ):
                raise Blocked("ACTUAL_AUTHORITY_SOURCE_REQUIRED")
            _, private = source_basis(
                s,
                self.ctx(role),
                self.basis.product_id,
                [{"artifact_id": str(row.id), "expected_revision": row.revision}],
            )
            if private:
                raise Blocked("ACTUAL_AUTHORITY_SOURCE_REQUIRED")
        return bound_payloads(self.data["plan"], saved["subject_id"], saved["subject_revision"])

    def import_facts(self):
        from pdos_next.database import tenant_session
        from pdos_next.domain.professional_authority.service import (
            configure_local_synthetic_profiles,
        )
        from pdos_next.professional_import import import_professional_fact
        from pdos_next.quality_bootstrap import configure_local_profiles
        from pdos_next.quality_policy_import import import_quality_policy_fact

        self.target()
        if self.data is None or "authority-source" not in self.data["receipts"]:
            raise Blocked("ACTUAL_AUTHORITY_SOURCE_REQUIRED")
        lists, old = self.read_plan_inputs()
        if canonical(lists) != canonical(self.data["profiles"]) or canonical(old) != canonical(
            self.data["original_profiles"]
        ):
            raise Blocked("RETAINED_PROFILE_LIST_CHANGED")
        prof = configure_local_synthetic_profiles(self.engine, lists["professional"], enabled=True)[
            -1
        ]
        policy = configure_local_profiles(self.engine, lists["quality"])[-1]
        if prof.nature != "synthetic" or (prof.key, policy.key) != (
            self.data["plan"]["profiles"]["professional"]["key"],
            self.data["plan"]["profiles"]["quality"]["issuer_key"],
        ):
            raise Blocked("EXACT_SYNTHETIC_ISSUER_REQUIRED")
        saved = []
        with tenant_session(self.engine, self.basis.tenant_id) as s:
            _, deadline = self.guard(s)
            facts, policy_input = self.source_guard(s)
            if aware(self.data["plan"]["valid_until"]) > deadline:
                raise Blocked("CURRENT_GRANT_INTERVAL_CHANGED")
            if aware(self.data["plan"]["valid_until"]) <= datetime.now(UTC):
                raise Blocked("FIXED_PUBLICATION_EXPIRED")
            for entry in facts:
                label = entry["label"]
                result = import_professional_fact(
                    s,
                    self.ctx(),
                    prof,
                    entry["payload"],
                    request_key=f"wave22-{self.basis.case_id}-{label}",
                    command_id=uuid5(self.basis.case_id, "wave22:" + label),
                )
                saved.append(
                    (label, result, "professional.authority.import", "professional_authority_fact")
                )
            result = import_quality_policy_fact(
                s,
                self.ctx(),
                policy,
                policy_input,
                request_key=f"wave22-{self.basis.case_id}-quality-policy",
                command_id=uuid5(self.basis.case_id, "wave22:quality-policy"),
            )
            saved.append(("quality-policy", result, "quality.policy.import", "quality_policy_fact"))
        for args in saved:
            self.record_receipt(*args)
        self.data["state"] = "synthetic_facts_saved_root_reload_required"
        self.save()
        self.write_profiles()
        return {
            "state": self.data["state"],
            "professional_facts": len(facts),
            "policy_facts": 1,
            "source_versions": 1,
            "production_qualification": False,
            "independent_review_decision": False,
            "business_execution": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "import"))
    parser.add_argument("--marker", required=True)
    parser.add_argument("--professional-profiles")
    parser.add_argument("--quality-profiles")
    args = parser.parse_args()
    try:
        tool = AuthorityTool(
            args.marker,
            professional_profiles=args.professional_profiles,
            quality_profiles=args.quality_profiles,
        )
        result = tool.prepare() if args.stage == "prepare" else tool.import_facts()
        print(canonical(result))
    except Exception as error:
        # Never output SQL, endpoint, environment, source contents, credentials or a traceback.
        print(canonical({"state": "blocked", "code": getattr(error, "code", type(error).__name__)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
