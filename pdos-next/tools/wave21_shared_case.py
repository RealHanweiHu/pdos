"""Independent shared-case foundation; Root alone executes actual boundaries.

Foundation uses the real API/common preview and retained original requests.
Offline planning/payload construction cannot prove a target, source or result.
The original Demo is never instantiated and its checkpoint/profiles are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo


def layout_root(source: Path) -> Path:
    """Only the owned staged layout and the future real tools layout are valid."""
    if source.name != "wave21_shared_case.py":
        raise RuntimeError("Unexpected shared-case tool filename")
    if source.parent.name == "tools":
        return source.parent.parent
    if source.parent.name == "wave21-case-staged" and source.parent.parent.name == ".local":
        return source.parents[2]
    raise RuntimeError("Unexpected shared-case tool layout")


ROOT = layout_root(Path(__file__).resolve())
SEED_PATH = ROOT / "tools/wave15_seed.py"
CHECKPOINT = ROOT / ".local/wave21-shared-case.json"
EXPECTED_PORT = 62513
MAX_SOURCES = 20
PURPOSE = "内部共享三人调查：独立单模穴A尺寸复测（合成）"
NATIVE_LINES = (
    "Wave21 shared local synthetic requirement; no production qualification.",
    "Dimension in mm: numeric limits 9.5 to 10.5 at 23 C, dry.",
    "Fixed synthetic method and material reference, not instrument evidence.",
    "Known one-line BOM: one synthetic unit per output ea, loss rate zero.",
    "Root cause, physical remediation, observation completeness and closure remain unproved.",
)
Role = Literal["maker", "observer", "independent_reviewer"]


class DependencyMissing(RuntimeError):
    """A specific unconfigured host seam; never a positive simulated outcome."""

    def __init__(self, dependency):
        self.dependency = dependency
        super().__init__("INTEGRATION_REQUIRED: " + dependency)


def _seed_helpers():
    """Import only inert source definitions, not Demo or any old private data."""
    spec = importlib.util.spec_from_file_location("wave21_seed_algorithms", SEED_PATH)
    if spec is None or spec.loader is None:
        raise DependencyMissing("wave15 pure source algorithms")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_algorithms():
    module = _seed_helpers()
    return module.canonical, module.merge_reads, module.subject_revision


@dataclass(frozen=True)
class CaseIdentity:
    marker: str
    case_id: UUID
    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    maker_id: UUID
    observer_id: UUID
    reviewer_id: UUID
    purpose: str

    def __post_init__(self):
        if not self.marker or not self.purpose.strip():
            raise ValueError("explicit target marker and exact purpose required")
        for value in (
            self.case_id,
            self.tenant_id,
            self.product_id,
            self.project_id,
            self.maker_id,
            self.observer_id,
            self.reviewer_id,
        ):
            if type(value) is not UUID:
                raise ValueError("host-observed scope and actor UUIDs required")
        if len({self.maker_id, self.observer_id, self.reviewer_id}) != 3:
            raise ValueError("three distinct real human identities required")

    def actor(self, role: Role) -> UUID:
        return {
            "maker": self.maker_id,
            "observer": self.observer_id,
            "independent_reviewer": self.reviewer_id,
        }[role]


@dataclass(frozen=True)
class Step:
    name: str
    actor: Role | None
    operations: tuple[str, ...]
    prerequisites: tuple[str, ...]
    gate: str
    mode: Literal["host", "common", "actual_event", "human_ui"] = "common"


STEPS = (
    Step(
        "scope",
        None,
        (),
        (),
        "verified(read_state) exact62513+marker; new Product/Project, actual 3 Principals/Grants",
        "host",
    ),
    Step(
        "source_and_configuration",
        "maker",
        (
            "evidence.artifact.register",
            "product.definition.draft",
            "project.create",
            "engineering.bom.revise",
            "engineering.configuration.create",
            "npi.process.revise",
            "build.create",
        ),
        ("scope",),
        "product visibility from first registration; exact source/config versions; quantity2 ea",
    ),
    Step(
        "authority_and_profiles",
        None,
        (),
        ("source_and_configuration",),
        (
            "actual server issuer/import Receipts for every required op "
            "before Start; no public self-grant"
        ),
        "host",
    ),
    Step(
        "build_prepare",
        "maker",
        ("build.readiness.compute",),
        ("authority_and_profiles",),
        (
            "known BOM demand2, new stock pool/equipment, exact "
            "scope/resource facts; no generic waiver"
        ),
    ),
    Step(
        "build_authorize",
        "maker",
        ("build.engineering.authorize", "build.manufacturing.authorize"),
        ("build_prepare",),
        "two separate current engineering/manufacturing T2 approvals and four controls",
        "human_ui",
    ),
    Step(
        "build_and_samples",
        "maker",
        (
            "build.start",
            "build.configuration.actual.record",
            "build.output.record",
            "build.sample.allocate",
            "build.sample.readiness.record",
        ),
        ("build_authorize",),
        "actual sourced Start/Actual/Lot clocks; two real A sample identities; deviation blocks",
        "actual_event",
    ),
    Step(
        "original_request",
        "observer",
        (
            "verification.preparation.record",
            "verification.request.create",
            "verification.method.prepare",
        ),
        ("build_and_samples",),
        "new Request; fixed actual first Sample; full accepted sample/item range,23C dry criterion",
    ),
    Step(
        "original_offer",
        "maker",
        ("verification.handoff.offer",),
        ("original_request",),
        "current limited Build and purpose-bound SampleReady; no old availability shortcut",
    ),
    Step(
        "original_accept_and_method",
        "observer",
        ("verification.actual_method.prepare", "verification.handoff.accept"),
        ("original_offer",),
        "actual perSample/item applicability+batch; quality current authority; original source ACL",
    ),
    Step(
        "original_plan_and_promise",
        "observer",
        ("test.run.plan", "verification.schedule.promise"),
        ("original_accept_and_method",),
        (
            "trusted TestResourceFact, equipment+Observer person; exact "
            "future window/full accepted range"
        ),
    ),
    Step(
        "original_start_and_result",
        "observer",
        (
            "test.run.start",
            "evidence.original.upload",
            "test.results.import",
            "test.result.compute",
        ),
        ("original_plan_and_promise",),
        "actual window Start, real scan/parse and exact original JSONL,11.0000 synthetic failure",
        "actual_event",
    ),
    Step(
        "original_run_review_and_disposition",
        "observer",
        ("test.run.review", "test.disposition.decide"),
        ("original_start_and_result",),
        "distinct human T2 decisions; actual paired Current/LaunchFact/ResultAction/Run Receipt",
        "human_ui",
    ),
    Step(
        "issue_and_capa",
        "maker",
        (
            "quality.issue.create",
            "quality.issue.triage",
            "quality.issue.containment.record",
            "quality.capa.draft",
        ),
        ("original_run_review_and_disposition",),
        (
            "new real Failure/Event link; product-shared Issue; action "
            "executorMaker, independent requirement"
        ),
    ),
    Step(
        "root_cause",
        "maker",
        ("quality.issue.root_cause.decide",),
        ("issue_and_capa",),
        "real sourced investigation conclusion, current quality duty+qualification, named T2 UUID",
        "human_ui",
    ),
    Step(
        "actual_completion",
        "maker",
        ("quality.capa.actions.complete",),
        ("root_cause",),
        (
            "exact9field actualCompletion+12field nativeClassification, full "
            "actionSHA, T1; not physical fix"
        ),
        "actual_event",
    ),
    Step(
        "followup_request",
        "observer",
        (
            "verification.preparation.record",
            "verification.request.create",
            "verification.method.prepare",
        ),
        ("actual_completion",),
        (
            "second new Request/logicalRun, actual second Sample; same fixed "
            "config only if current safe"
        ),
    ),
    Step(
        "followup_offer",
        "maker",
        ("verification.handoff.offer",),
        ("followup_request",),
        "real secondSample current ready for precise purpose, actual Build qualification",
    ),
    Step(
        "followup_accept_and_plan",
        "observer",
        (
            "verification.actual_method.prepare",
            "verification.handoff.accept",
            "test.run.plan",
            "verification.schedule.promise",
        ),
        ("followup_offer",),
        "fresh exact resource fact; disjoint actual reservation window; own second Sample usage",
    ),
    Step(
        "followup_start_and_result",
        "observer",
        (
            "test.run.start",
            "evidence.original.upload",
            "test.results.import",
            "test.result.compute",
        ),
        ("followup_accept_and_plan",),
        (
            "separate actual Start/report bytes/partial-final clocks; no "
            "anticipated pass or old Run reuse"
        ),
        "actual_event",
    ),
    Step(
        "followup_run_review_and_disposition",
        "observer",
        ("test.run.review", "test.disposition.decide"),
        ("followup_start_and_result",),
        (
            "two separate T2 decisions; exact Current successor evidence, no "
            "direct Formal Receipt fiction"
        ),
        "human_ui",
    ),
    Step(
        "link_and_candidate",
        "maker",
        ("quality.capa.followup.link", "quality.capa.verification.candidate.record"),
        ("followup_run_review_and_disposition",),
        (
            "completed Issue origin6; actual current paired outputs, complete "
            "failure/sample/item mappings"
        ),
    ),
    Step(
        "rule",
        "maker",
        ("quality.capa.verification.rule.import",),
        ("actual_completion",),
        (
            "host-only actual RulePublisher, exact "
            "anchor/method/criterion/sampling/source/issuer profile"
        ),
        "host",
    ),
    Step(
        "observation",
        "observer",
        ("quality.capa.observation.record",),
        ("rule", "link_and_candidate"),
        (
            "actual selected target records/raw_material and elapsed "
            "interval; system record!=physical coverage"
        ),
        "actual_event",
    ),
    Step(
        "independent_review_handoff",
        "independent_reviewer",
        ("quality.capa.verification.review",),
        ("observation",),
        (
            "read-only readiness for complete "
            "Pair/Rule/Observation/participants; no automated T2 Review or Close"
        ),
        "human_ui",
    ),
)
BY_STEP = MappingProxyType({step.name: step for step in STEPS})


def merge_complete_reads(groups: dict[str, object]) -> list[dict]:
    """Complete DECLARED owner read union; completeness still needs actual hosts.

    Callers supply every actual owner, source, professional and policy read set.
    No source label is ignored, no set is truncated, and revision conflict rejects.
    Source locators/raw records are retained separately, never replaced by this list.
    """
    if not groups or any(not name or values is None for name, values in groups.items()):
        raise DependencyMissing("all actual owner source-read groups")
    normalized = []
    for values in groups.values():
        if not isinstance(values, (list, tuple)):
            raise ValueError("explicit actual SourceRead list required")
        rows = []
        for value in values:
            raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            if not isinstance(raw, dict) or set(raw) != {"artifact_id", "expected_revision"}:
                raise ValueError("exact SourceRead fields required; no silent projection")
            identity = UUID(str(raw["artifact_id"]))
            if type(raw["expected_revision"]) is not int or raw["expected_revision"] <= 0:
                raise ValueError("exact positive source revision required")
            rows.append(
                {"artifact_id": str(identity), "expected_revision": raw["expected_revision"]}
            )
        normalized.append(rows)
    _, actual_merge, _ = _seed_algorithms()
    return actual_merge(*normalized)


def native_artifact_payload(label: str, complete_actual_lines: tuple[str, ...]) -> dict:
    """Native text is synthetic declared material, never an instrument report.

    Root must supply only already observed events or fixed publications, with full
    actual lines. This pure constructor cannot certify occurrence or current ACL.
    """
    if not label or not complete_actual_lines:
        raise ValueError("actual fixed publication label and full lines required")
    if any(
        not isinstance(line, str) or not line or "\n" in line or "\r" in line
        for line in complete_actual_lines
    ):
        raise ValueError("each explicit publication is one complete original line")
    return {
        "title": "Wave21 · " + label,
        "content": "\n".join(complete_actual_lines),
        "source_label": (
            "Explicit local synthetic shared material; no instrument or production claim"
        ),
        "visibility": "product",
    }


def exact_line(artifact_id: UUID, revision: int, content: str, line: int) -> dict:
    if type(artifact_id) is not UUID or type(revision) is not int or revision < 1:
        raise ValueError("actual Artifact identity and revision required")
    lines = content.splitlines()
    if type(line) is not int or not 1 <= line <= len(lines):
        raise ValueError("exact registered whole line required")
    return {
        "id": str(artifact_id),
        "revision": revision,
        "kind": "artifact",
        "position": f"line:{line};quote_sha256:"
        + hashlib.sha256(lines[line - 1].encode()).hexdigest(),
    }


def actual_completion_line(case, *, issue_id, capa_id, action_id, occurred_at, timezone, text):
    """No default now or future plan may manufacture an actual completion clock."""
    if not isinstance(occurred_at, datetime) or occurred_at.utcoffset() is None:
        raise ValueError("explicit already-observed aware completion timestamp required")
    if occurred_at > datetime.now(UTC) or not text:
        raise ValueError("future or absent completion is not observed")
    ZoneInfo(timezone)
    canonical, _, _ = _seed_algorithms()
    return canonical(
        {
            "issue_id": str(issue_id),
            "capa_id": str(capa_id),
            "action_id": str(action_id),
            "executor_id": str(case.maker_id),
            "operation": "quality.capa.actions.complete",
            "occurred_at": occurred_at.isoformat(),
            "original_timezone": timezone,
            "purpose": case.purpose,
            "text": text,
        }
    )


class SharedCaseHost(Protocol):
    """Future Root-owned actual adapter; no fake default or Owner Context.

    target must verify actual marker/port before every external boundary.
    stage_current must collect real rows, sources, professional/policy and all
    required reads; it may not return a modeled positive qualification.
    """

    def target(self, *, marker: str, port: int) -> None: ...
    def stage_current(self, case: CaseIdentity, step: Step) -> object: ...


class SharedCaseDriver:
    """Explicit handoff skeleton. No submission, T2 approval or auto-advancement."""

    def __init__(self, case: CaseIdentity, host: SharedCaseHost | None = None):
        self.case = case
        self.host = host

    def stage_inputs(self, step_name: str):
        step = BY_STEP[step_name]
        if self.host is None:
            raise DependencyMissing("Root verified shared-case host")
        self.host.target(marker=self.case.marker, port=EXPECTED_PORT)
        # Returning data is a handoff only; no successful step/state is recorded.
        return self.host.stage_current(self.case, step)

    def command(self, label, role, operation, payload, *, product_revision, read_groups):
        if role == "independent_reviewer":
            raise DependencyMissing("manual independent T2 Review entry")
        allowed = {op for step in STEPS if step.actor == role for op in step.operations}
        if operation not in allowed or operation in {
            "test.run.review",
            "test.disposition.decide",
            "quality.issue.root_cause.decide",
        }:
            raise DependencyMissing("manual named T2 entry")
        if not label or type(product_revision) is not int or product_revision < 1:
            raise ValueError("stable command label and actual Product revision required")
        if payload.get("visibility", "product") != "product":
            raise ValueError("new shared branch cannot register private material")
        # Root must additionally validate the real PAYLOADS schema before saving
        # this exact command in the independent 0600 checkpoint and sending it.
        from uuid import uuid5

        return {
            "command_id": str(uuid5(self.case.case_id, role + ":" + label)),
            "idempotency_key": f"wave21-{self.case.case_id}-{role}-{label}",
            "operation": operation,
            "product_id": str(self.case.product_id),
            "expected_revision": product_revision,
            "source_read_set": merge_complete_reads(read_groups),
            "payload": payload,
        }


class UnknownWrite(RuntimeError):
    def __init__(self, label):
        self.label = label
        super().__init__("UNKNOWN_WRITE: original request retained")


class PendingConfirmation(RuntimeError):
    def __init__(self, label):
        self.label = label
        super().__init__("T1_PREVIEW_READY: not submitted")


class Foundation:
    """Root-run actual first segment; no old Demo object or checkpoint is used."""

    ROLES = ("maker", "observer", "independent_reviewer")
    OPERATIONS = {
        "native-source": "evidence.artifact.register",
        "definition": "product.definition.draft",
        "project": "project.create",
        "bom": "engineering.bom.revise",
        "engineering": "engineering.configuration.create",
        "manufacturing": "npi.process.revise",
    }

    def __init__(self, marker, *, purpose=PURPOSE, confirm=None, recover=None):
        sys.path.insert(0, str(ROOT / "tools"))
        sys.path.insert(0, str(ROOT / "server"))
        from local_environment import read_state, verified
        from pdos_next.database import engine_for

        self.read_state, self.verified = read_state, verified
        self.marker, self.purpose = str(marker), purpose
        self.confirm, self.recover = confirm, recover
        self.confirm_used = self.recover_used = False
        self.helpers = _seed_helpers()
        target = self.target()
        self.tenant_id = UUID(target["preview_tenant_id"])
        if CHECKPOINT.exists() or CHECKPOINT.is_symlink():
            mode = CHECKPOINT.lstat()
            if (
                not stat.S_ISREG(mode.st_mode)
                or stat.S_IMODE(mode.st_mode) != 0o600
                or mode.st_uid != os.getuid()
            ):
                raise RuntimeError("Independent checkpoint must be an owned regular 0600 file")
            self.data = json.loads(CHECKPOINT.read_text())
            if (
                self.data.get("schema_version") != "wave21-shared-foundation-v1"
                or self.data.get("marker") != self.marker
                or self.data.get("tenant_id") != str(self.tenant_id)
                or self.data.get("purpose") != purpose
                or self.data.get("visibility") != "product"
                or set(self.data.get("actors", {})) != set(self.ROLES)
            ):
                raise RuntimeError("Independent checkpoint scope/configuration mismatch")
        else:
            observed = datetime.now(UTC)
            self.data = {
                "schema_version": "wave21-shared-foundation-v1",
                "marker": self.marker,
                "tenant_id": str(self.tenant_id),
                "case_id": str(uuid4()),
                "purpose": purpose,
                "visibility": "product",
                "created_at": observed.isoformat(),
                "bootstrap_expires_at": (observed + timedelta(days=2)).isoformat(),
                "actors": {
                    role: {"id": str(uuid4()), "login_token": secrets.token_urlsafe(32)}
                    for role in self.ROLES
                },
                "requests": {},
                "receipts": {},
                "phase": "allocated_not_bootstrapped",
                "sources": {},
            }
            self.save()
        ids = [UUID(v["id"]) for v in self.data["actors"].values()]
        if len(set(ids)) != 3:
            raise RuntimeError("Three distinct immutable actor IDs required")
        self.admin = engine_for(target["admin_url"])

    def target(self):
        state = self.verified(self.read_state())
        if state["port"] != EXPECTED_PORT or str(state["marker"]) != self.marker:
            raise RuntimeError("Only explicit marked62513 target is permitted")
        return state

    def save(self):
        if CHECKPOINT.is_symlink():
            raise RuntimeError("Independent checkpoint symlink refused")
        self.helpers.private_write(CHECKPOINT, self.data)

    def key(self, label, role="maker"):
        return f"wave21-{self.data['case_id']}-{role}-{label}"

    def actor(self, role):
        return UUID(self.data["actors"][role]["id"])

    def bootstrap(self):
        """Only newly allocated principals/logins, one actual admin transaction.

        This is local identity bootstrap, not a professional qualification import.
        Existing identities are checked exactly; expiry/access are never repaired.
        """
        from pdos_next.models import LoginSession, Principal, now
        from pdos_next.service import digest
        from sqlalchemy.orm import Session

        self.target()
        expires = datetime.fromisoformat(self.data["bootstrap_expires_at"])
        if expires <= now():
            raise RuntimeError("Saved bootstrap expired; no automatic extension")
        with Session(self.admin) as s, s.begin():
            for role in self.ROLES:
                actor = self.actor(role)
                name = "Wave21 shared · " + role
                token_hash = digest(self.data["actors"][role]["login_token"])
                person, login = s.get(Principal, actor), s.get(LoginSession, token_hash)
                if person is None and login is None:
                    s.add(Principal(id=actor, tenant_id=self.tenant_id, name=name, kind="human"))
                    s.flush()
                    s.add(
                        LoginSession(
                            tenant_id=self.tenant_id,
                            principal_id=actor,
                            token_hash=token_hash,
                            expires_at=expires,
                        )
                    )
                elif (
                    person is None
                    or login is None
                    or person.tenant_id != self.tenant_id
                    or person.kind != "human"
                    or person.active is not True
                    or person.name != name
                    or login.tenant_id != self.tenant_id
                    or login.principal_id != actor
                    or login.revoked is not False
                    or login.expires_at != expires
                    or login.expires_at <= now()
                ):
                    raise RuntimeError("Saved synthetic identity unavailable; no repair")
            s.flush()
        self.data["phase"] = "principals_bootstrapped"
        self.save()

    def request(self, role, method, path, *, body=None):
        import httpx

        self.target()
        # One request, no retry, no redirects, no proxy/environment fallback.
        with httpx.Client(
            base_url="http://127.0.0.1:8898",
            trust_env=False,
            follow_redirects=False,
            timeout=180,
            headers={"Authorization": "Bearer " + self.data["actors"][role]["login_token"]},
        ) as client:
            return self.helpers.checked(client.request(method, path, json=body))

    def check_receipt(self, value, role, *, operation, family):
        if (
            not isinstance(value, dict)
            or value.get("operation") != operation
            or value.get("subject_type") != family
            or value.get("writer_id") != str(self.actor(role))
            or value.get("requester_id") != str(self.actor(role))
        ):
            raise RuntimeError("Actual receipt operation/writer/family mismatch")
        UUID(value["id"])
        identity = UUID(value["subject_id"])
        revision = self.helpers.subject_revision(value)
        if (
            value.get("result", {}).get("id") != str(identity)
            or value["result"].get("revision") != revision
        ):
            raise RuntimeError("Actual flattened receipt subject mismatch")
        return value

    def record_receipt(self, label, value, role, *, operation, family):
        self.check_receipt(value, role, operation=operation, family=family)
        previous = self.data["receipts"].get(label)
        if previous is not None and self.helpers.canonical(previous) != self.helpers.canonical(
            value
        ):
            raise RuntimeError("Saved receipt cannot be replaced")
        self.data["receipts"][label] = value
        self.data["requests"][label]["state"] = "saved"
        self.save()
        return value

    def _send_saved(self, label, role, path):
        import httpx

        request = self.data["requests"][label]
        if request["state"] in {"sending", "unknown"}:
            if self.recover != label or self.recover_used:
                raise UnknownWrite(label)
            self.recover_used = True
        request["state"] = "sending"
        self.save()  # Original exact body/token/key persisted before the boundary.
        try:
            return self.request(role, "POST", path, body=request["body"])
        except httpx.TransportError:
            request["state"] = "unknown"
            self.save()
            raise UnknownWrite(label) from None
        except self.helpers.GuardedRequestError as error:
            # Preserve the same body/token even when the actual contract refuses
            # stale/expired authority. There is no implicit replacement preview.
            request["state"] = "rejected"
            request["last_error"] = {"status": error.status, "code": error.code}
            self.save()
            raise

    def product(self):
        from pdos_next.contracts import ProductInput

        label = "product"
        body = ProductInput(
            name="Wave21 shared three-person · " + self.data["case_id"][:8],
            purpose=self.purpose,
            idempotency_key=self.key(label),
        ).model_dump(mode="json")
        saved = self.data["requests"].get(label)
        if saved is None:
            self.data["requests"][label] = {
                "role": "maker",
                "actor_id": str(self.actor("maker")),
                "body": body,
                "state": "ready",
            }
            self.save()
        elif (
            saved.get("actor_id") != str(self.actor("maker"))
            or saved.get("role") != "maker"
            or self.helpers.canonical(saved["body"]) != self.helpers.canonical(body)
        ):
            raise RuntimeError("Original product request cannot change")
        receipt = self.data["receipts"].get(label)
        if receipt is None:
            receipt = self.record_receipt(
                label,
                self._send_saved(label, "maker", "/v1/products"),
                "maker",
                operation="product.create",
                family="product",
            )
        else:
            self.check_receipt(receipt, "maker", operation="product.create", family="product")
        self.data["product_id"] = receipt["subject_id"]
        self.save()

    def grants(self):
        from pdos_next.models import Grant, Product, now
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        self.target()
        product_id = UUID(self.data["product_id"])
        expires = datetime.fromisoformat(self.data["bootstrap_expires_at"])
        with Session(self.admin) as s, s.begin():
            product = s.get(Product, product_id)
            if (
                product is None
                or product.tenant_id != self.tenant_id
                or product.owner_id != self.actor("maker")
                or product.purpose != self.purpose
            ):
                raise RuntimeError("Actual new Product scope/owner mismatch")
            for role in self.ROLES:
                grant = s.scalar(
                    select(Grant).where(
                        Grant.tenant_id == self.tenant_id,
                        Grant.product_id == product_id,
                        Grant.principal_id == self.actor(role),
                    )
                )
                if grant is None and role != "maker":
                    s.add(
                        Grant(
                            tenant_id=self.tenant_id,
                            product_id=product_id,
                            principal_id=self.actor(role),
                            can_write=True,
                            expires_at=expires,
                        )
                    )
                elif (
                    grant is None
                    or grant.can_write is not True
                    or grant.expires_at <= now()
                    or (role != "maker" and grant.expires_at != expires)
                ):
                    raise RuntimeError("Existing new-scope access invalid; no renewal/repair")
            s.flush()
        self.data["phase"] = "new_product_access_bootstrapped"
        self.save()

    def submit(self, label, payload, reads, *, family):
        from pdos_next.contracts import PAYLOADS, Command
        from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS

        operation = self.OPERATIONS[label]
        if operation in T2_OPERATIONS:
            raise DependencyMissing("manual T2 entry; not foundation")
        payload_type = PAYLOADS.get(operation)
        if payload_type is None:
            raise DependencyMissing("registered actual operation " + operation)
        saved = self.data["requests"].get(label)
        if label in self.data["receipts"]:
            if (
                saved is None
                or saved["role"] != "maker"
                or saved.get("actor_id") != str(self.actor("maker"))
                or saved["original"]["operation"] != operation
                or saved["original"]["product_id"] != self.data["product_id"]
                or saved["original"]["idempotency_key"] != self.key(label)
                or saved["original"]["command_id"] != str(self.stable_command_id(label))
            ):
                raise RuntimeError(
                    "Saved receipt must retain its exact original actor/scope/command"
                )
            return self.check_receipt(
                self.data["receipts"][label], "maker", operation=operation, family=family
            )
        payload = payload_type.model_validate(payload).model_dump(mode="json", exclude_none=True)
        product_id = self.data["product_id"]
        if saved is None:
            workspace = self.request("maker", "GET", f"/v1/products/{product_id}/workspace")
            product = workspace["product"]
            if product["id"] != product_id or product["purpose"] != self.purpose:
                raise RuntimeError("Current Product scope changed")
            expected_product_revision = product["revision"]
        else:
            if saved["role"] != "maker" or saved.get("actor_id") != str(self.actor("maker")):
                raise RuntimeError("Original fixed command actor changed")
            # Current Product drift is evaluated by the real shared recovery
            # path. Never rewrite an original unknown/prepared request first.
            expected_product_revision = saved["original"]["expected_revision"]
        original = Command(
            command_id=self.stable_command_id(label),
            idempotency_key=self.key(label),
            operation=operation,
            product_id=UUID(product_id),
            expected_revision=expected_product_revision,
            source_read_set=reads,
            payload=payload,
        ).model_dump(mode="json")
        if saved is None:
            saved = {
                "role": "maker",
                "actor_id": str(self.actor("maker")),
                "original": original,
                "body": original,
                "state": "ready",
            }
            self.data["requests"][label] = saved
            self.save()
        elif self.helpers.canonical(saved["original"]) != self.helpers.canonical(original):
            raise RuntimeError("Original fixed command/material changed; no new key or token")
        fixed_body = Command.model_validate(saved["body"]).model_dump(mode="json")
        if "preview" in saved:
            preview_body = Command.model_validate(saved["preview"]["command"]).model_dump(
                mode="json"
            )
            if self.helpers.canonical(fixed_body) != self.helpers.canonical(preview_body):
                raise RuntimeError("Saved actual prepared command/token cannot change")
        elif self.helpers.canonical(fixed_body) != self.helpers.canonical(original):
            raise RuntimeError("Saved original command cannot change")
        if saved["state"] in {"sending", "unknown"}:
            value = self._send_saved(label, "maker", "/v1/commands")
            return self.record_receipt(label, value, "maker", operation=operation, family=family)
        if saved["state"] == "rejected":
            raise RuntimeError("Original operation rejected; follow actual recovery contract")
        if saved["state"] in {"preview_sending", "preview_unknown"}:
            raise DependencyMissing("actual preview transport recovery; no replacement token")
        if operation in T1_OPERATIONS:
            if "preview" not in saved:
                import httpx

                saved["state"] = "preview_sending"
                self.save()
                try:
                    preview = self.request("maker", "POST", "/v1/commands/preview", body=original)
                except httpx.TransportError:
                    saved["state"] = "preview_unknown"
                    self.save()
                    raise DependencyMissing("actual preview transport recovery") from None
                prepared = Command.model_validate(preview["command"]).model_dump(mode="json")
                comparable = dict(prepared)
                comparable["payload"] = payload_type.model_validate(prepared["payload"]).model_dump(
                    mode="json", exclude={"confirmation_token"}, exclude_none=True
                )
                if self.helpers.canonical(comparable) != self.helpers.canonical(original):
                    raise RuntimeError("Actual preview changed original scoped material")
                if (
                    not prepared["payload"].get("confirmation_token")
                    or preview.get("write_tier") == "T2"
                ):
                    raise RuntimeError("Actual T1 prepared command/confirmation missing")
                saved.update(body=prepared, preview=preview, state="awaiting_confirmation")
                self.data["phase"] = "awaiting_confirmation:" + label
                self.save()
            if self.confirm != label or self.confirm_used:
                raise PendingConfirmation(label)
            self.confirm_used = True
        value = self._send_saved(label, "maker", "/v1/commands")
        return self.record_receipt(label, value, "maker", operation=operation, family=family)

    def stable_command_id(self, label):
        from uuid import uuid5

        return uuid5(UUID(self.data["case_id"]), "maker:" + label)

    def ref(self, line):
        source = self.data["receipts"]["native-source"]
        return {
            "artifact_id": source["subject_id"],
            "expected_revision": self.helpers.subject_revision(source),
            "line": line,
            "quote": NATIVE_LINES[line - 1],
        }

    def foundation(self):
        self.bootstrap()
        self.product()
        self.grants()
        self.submit(
            "native-source",
            native_artifact_payload("shared foundation", NATIVE_LINES),
            [],
            family="artifact",
        )
        reference = self.ref(1)
        reads = merge_complete_reads(
            {
                "registered_native": [
                    {
                        "artifact_id": reference["artifact_id"],
                        "expected_revision": reference["expected_revision"],
                    }
                ]
            }
        )
        definition = self.submit(
            "definition",
            {
                "title": "Wave21 shared synthetic definition",
                "purpose": self.purpose,
                "visibility": "product",
                "use_cases": ["内部共享单模穴A调查与独立复测"],
                "unknowns": ["Physical remediation, effectiveness and closure are not established"],
                "sources": [reference],
                "change_reason": "New independent shared branch; no old private object reused",
            },
            reads,
            family="definition_revision",
        )
        project = self.submit(
            "project",
            {
                "name": "Wave21 shared investigation project",
                "purpose": self.purpose,
                "scope": "Internal synthetic two A samples and two real saved Run branches only",
                "definition_id": definition["subject_id"],
                "expected_definition_revision": self.helpers.subject_revision(definition),
                "visibility": "product",
            },
            reads,
            family="project",
        )
        self.data["project_id"] = project["subject_id"]
        self.save()
        common = {
            "visibility": "product",
            "reason": "New fixed shared configuration",
            "sources": [reference],
        }
        bom = self.submit(
            "bom",
            {
                **common,
                "name": "Wave21 known one-unit BOM",
                "lines": [
                    {
                        "key": "unit",
                        "part": {"name": "Wave21 synthetic new unit"},
                        "quantity": "1",
                        "unit": "ea",
                        "loss_rate": "0",
                        "critical": True,
                    }
                ],
            },
            reads,
            family="bom_revision",
        )
        engineering = self.submit(
            "engineering",
            {
                **common,
                "name": "Wave21 shared engineering configuration",
                "definition_id": definition["subject_id"],
                "expected_definition_revision": self.helpers.subject_revision(definition),
                "bom_id": bom["subject_id"],
                "expected_bom_revision": self.helpers.subject_revision(bom),
            },
            reads,
            family="engineering_configuration",
        )
        process = self.submit(
            "manufacturing",
            {
                **common,
                "name": "Wave21 shared manufacturing process",
                "engineering_configuration_id": engineering["subject_id"],
                "expected_engineering_revision": self.helpers.subject_revision(engineering),
                "operations": [
                    {
                        "key": "assembly",
                        "name": "Shared synthetic assembly",
                        "kind": "assembly",
                        "bom_line_keys": ["unit"],
                    }
                ],
            },
            reads,
            family="process_revision",
        )
        self.data["scope"] = {
            "tenant_id": str(self.tenant_id),
            "product_id": self.data["product_id"],
            "project_id": project["subject_id"],
        }
        self.data["sources"]["foundation"] = {
            "reference": reference,
            "required_source_read_set": reads,
        }
        self.data["configuration"] = {
            "bom_id": bom["subject_id"],
            "bom_revision": self.helpers.subject_revision(bom),
            "engineering_id": engineering["subject_id"],
            "engineering_revision": self.helpers.subject_revision(engineering),
            "manufacturing_id": process["subject_id"],
            "manufacturing_revision": self.helpers.subject_revision(process),
        }
        self.data["phase"] = "foundation_saved_not_build_started"
        self.data["readback"] = self.readback_foundation()
        self.save()
        return {
            "state": self.data["phase"],
            "receipts_saved": len(self.data["receipts"]),
            "later_phases_executed": False,
        }

    def readback_foundation(self):
        """Each actual actor reads the same shared objects through existing APIs."""
        from pdos_next.service import digest

        pid = self.data["product_id"]
        receipt_ids = {key: value["subject_id"] for key, value in self.data["receipts"].items()}
        content = "\n".join(NATIVE_LINES)
        stored_content_hash = digest(content)
        raw_text_sha = hashlib.sha256(content.encode()).hexdigest()
        result = {}
        for role in self.ROLES:
            workspace = self.request(role, "GET", f"/v1/products/{pid}/workspace")
            source = next(
                (v for v in workspace["sources"] if v["id"] == receipt_ids["native-source"]), None
            )
            if (
                source is None
                or source["visibility"] != "product"
                or source["status"] != "active"
                or source["content"] != content
                or source["content_hash"] != stored_content_hash
                or source["revision"]
                != self.helpers.subject_revision(self.data["receipts"]["native-source"])
            ):
                raise RuntimeError("Actual shared native source readback mismatch")
            groups = {
                "definition": self.request(role, "GET", f"/v1/products/{pid}/definitions")["items"],
                "project": self.request(role, "GET", f"/v1/products/{pid}/projects")["items"],
            }
            configurations = self.request(role, "GET", f"/v1/products/{pid}/configurations")
            groups.update(
                bom=configurations["boms"],
                engineering=configurations["engineering"],
                manufacturing=configurations["processes"],
            )
            for label, rows in groups.items():
                row = next((v for v in rows if v["id"] == receipt_ids[label]), None)
                source_state = None
                if row is not None:
                    if label == "project":
                        defined = row.get("definition", {})
                        if (
                            row.get("owner_id") != str(self.actor("maker"))
                            or row.get("purpose") != self.purpose
                            or defined.get("id") != receipt_ids["definition"]
                            or defined.get("revision")
                            != self.helpers.subject_revision(self.data["receipts"]["definition"])
                        ):
                            raise RuntimeError("Actual Project fixed Definition readback mismatch")
                        source_state = defined.get("source_status")
                    else:
                        source_state = row.get("source_status")
                if (
                    row is None
                    or row["visibility"] != "product"
                    or source_state != "current"
                    or row["revision"]
                    != self.helpers.subject_revision(self.data["receipts"][label])
                ):
                    raise RuntimeError("Actual shared configuration/project readback mismatch")
            result[role] = {
                "shared_objects": 6,
                "stored_content_hash": stored_content_hash,
                "raw_text_sha256": raw_text_sha,
                "professional_qualification": None,
            }
        return result


def main():
    parser = argparse.ArgumentParser(description="Offline shared three-human case handoff")
    parser.add_argument("--phase", choices=("plan", "foundation"), required=True)
    parser.add_argument("--marker")
    parser.add_argument("--purpose", default=PURPOSE)
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--confirm", choices=tuple(Foundation.OPERATIONS))
    selected.add_argument("--recover", choices=("product", *Foundation.OPERATIONS))
    args = parser.parse_args()
    if args.phase == "plan":
        print(
            json.dumps(
                {
                    "mode": "offline_scaffold_not_executed",
                    "runtime_host": "INTEGRATION_REQUIRED",
                    "steps": [step.__dict__ for step in STEPS],
                    "automatic_review": False,
                    "effectiveness": None,
                    "close": False,
                    "checkpoint_written": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not args.marker:
        parser.error("foundation requires explicit --marker")
    tool = None
    try:
        tool = Foundation(
            args.marker, purpose=args.purpose, confirm=args.confirm, recover=args.recover
        )
        print(json.dumps(tool.foundation(), ensure_ascii=False))
    except PendingConfirmation as pending:
        # The review contains no credentials; its command/token stays only in
        # the owned0600 checkpoint. This is not a request for new user permission.
        preview = tool.data["requests"][pending.label]["preview"]
        print(
            json.dumps(
                {
                    "state": "awaiting_confirmation",
                    "label": pending.label,
                    "review": preview["review"],
                    "expires_at": preview["expires_at"],
                    "submitted": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2) from None
    except UnknownWrite as unknown:
        print(
            json.dumps(
                {
                    "state": "UNKNOWN",
                    "label": unknown.label,
                    "original_request_retained": True,
                    "automatic_retry": False,
                }
            )
        )
        raise SystemExit(3) from None
    except Exception as error:
        code = _seed_helpers().safe_code(getattr(error, "code", None))
        print(
            json.dumps(
                {
                    "state": "blocked",
                    "code": code,
                    "error_type": type(error).__name__,
                    "private_checkpoint_retained": CHECKPOINT.exists(),
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        if tool is not None:
            tool.admin.dispose()


if __name__ == "__main__":
    main()
