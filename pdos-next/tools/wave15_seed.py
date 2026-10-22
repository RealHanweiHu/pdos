"""Explicit isolated synthetic demo; inert until main and never rewrites old truth.

Root alone executes this after migration/profile/API checks. Recovery state and
login credentials are private. Every DB/UOW/HTTP operation verifies the exact
62513 marker. No model invocation, release, deletion, qualification for production,
or alteration of an existing sample/resource/fact is implemented.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
CHECKPOINT = ROOT / ".local/wave15-seed.json"
PURPOSE = "内部问题调查：独立单模穴A尺寸复测（合成）"
TEXT = (
    "Synthetic requirement is unverified\n"
    "Synthetic drawing, dimension in mm; numeric limits 9.5 to 10.5 at 23 C, dry.\n"
    "Synthetic method and material information; no production qualification.\n"
    "Synthetic containment observed by the named person.\n"
    "Synthetic hypothesis only, not a root cause."
)

# Exact retained rows are checked; new rows and Product's normal reference epoch
# are deliberately outside this comparison. This does not assert current real
# qualification for an old execution: its immutable recorded history is retained.
RETAINED_TABLES = (
    "builds",
    "build_readiness",
    "build_execution_assessments",
    "build_current_execution_assessments",
    "build_authorization_decisions",
    "build_current_authorizations",
    "build_starts",
    "actual_configurations",
    "build_lots",
    "sample_allocations",
    "sample_units",
    "sample_readiness_facts",
    "sample_current_readiness",
    "verification_preparations",
    "verification_current_preparations",
    "verification_formal_requests",
    "verification_current_formal_requests",
    "verification_method_applicabilities",
    "verification_window_proposals",
    "verification_run_identities",
    "verification_run_versions",
    "verification_current_runs",
    "verification_launch_facts",
    "test_resource_facts",
    "test_resource_current",
    "test_resource_reservations",
    "sample_usage_sentinels",
    "sample_run_usages",
    "build_operational_facts",
    "build_operational_current",
    "operational_asset_sentinels",
    "operational_material_holds",
    "operational_resource_occupancies",
)


def encode(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return {"byte_sha256": hashlib.sha256(value).hexdigest()}
    raise TypeError(type(value).__name__)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=encode
    )


def private_write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + str(uuid4()))
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, default=encode) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()  # Only this newly allocated temporary metadata file.


def merge_reads(*groups):
    values = {}
    for group in groups:
        for entry in group:
            entry = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
            key, revision = str(entry["artifact_id"]), entry["expected_revision"]
            if (
                type(revision) is not int
                or revision < 1
                or (key in values and values[key] != revision)
            ):
                raise RuntimeError("Conflicting source version")
            values[key] = revision
    if len(values) > 20:
        raise RuntimeError("Complete source set exceeds 20; no truncation")
    return [
        {"artifact_id": key, "expected_revision": value} for key, value in sorted(values.items())
    ]


def subject_revision(receipt):
    value = receipt.get("subject_revision")
    if type(value) is not int or value < 1:
        raise RuntimeError("Receipt must carry its exact positive subject revision")
    return value


def safe_code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", value)
        else "HTTP_ERROR"
    )


class GuardedRequestError(RuntimeError):
    def __init__(self, status, code):
        self.status, self.code = status, safe_code(code)
        super().__init__("Guarded request rejected")


def checked(response):
    if not response.is_success:
        try:
            body = response.json()
            code = body.get("code") if isinstance(body, dict) else None
        except ValueError:
            code = None
        # Never retain or print response bodies, headers or URLs in errors.
        raise GuardedRequestError(response.status_code, code)
    return response.json()


class Demo:
    def __init__(self, marker, *, lead_minutes=10):
        from local_environment import read_state, verified
        from pdos_next.database import engine_for

        self.read_state, self.verified, self.marker = read_state, verified, str(marker)
        target = self.target()
        self.engine = engine_for(target["app_url"])
        self.admin = engine_for(target["admin_url"])
        self.tenant, self.product = (
            UUID(target["preview_tenant_id"]),
            UUID(target["preview_product_id"]),
        )
        self.data = (
            json.loads(CHECKPOINT.read_text())
            if CHECKPOINT.exists()
            else {
                "marker": self.marker,
                "lead_minutes": lead_minutes,
                "tenant_id": str(self.tenant),
                "product_id": str(self.product),
                "demo_id": str(uuid4()),
                "actor_id": str(uuid4()),
                "login_token": secrets.token_urlsafe(32),
                "run_id": str(uuid4()),
                "request_id": str(uuid4()),
                "preparation_request_id": str(uuid4()),
                "build_equipment_id": str(uuid4()),
                "test_equipment_id": str(uuid4()),
                "commands": {},
                "receipts": {},
                "events": {},
                "phase": "allocated",
            }
        )
        if (self.data["marker"], self.data["tenant_id"], self.data["product_id"]) != (
            self.marker,
            str(self.tenant),
            str(self.product),
        ):
            raise RuntimeError("Demo checkpoint scope mismatch")
        if self.data["lead_minutes"] != lead_minutes:
            raise RuntimeError("Saved lead time cannot change; reuse the original CLI value")
        self.actor = UUID(self.data["actor_id"])
        self.save()
        self.retain_old_rows()

    def target(self):
        state = self.verified(self.read_state())
        if state["port"] != 62513 or str(state["marker"]) != self.marker:
            raise RuntimeError("Only the explicitly named 62513 marker is authorized")
        return state

    def save(self):
        private_write(CHECKPOINT, self.data)

    def retained_rows(self):
        from pdos_next.models import Base
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        self.target()
        output = {}
        with Session(self.admin) as session, session.begin():
            for name in RETAINED_TABLES:
                table = Base.metadata.tables.get(name)
                if table is None or "id" not in table.c or "tenant_id" not in table.c:
                    raise RuntimeError("Retained schema contract unavailable")
                query = select(table).where(table.c.tenant_id == self.tenant)
                if "product_id" in table.c:
                    query = query.where(table.c.product_id == self.product)
                rows = session.execute(query.limit(5001)).mappings().all()
                if len(rows) > 5000:
                    raise RuntimeError("Retained inventory exceeded explicit bound")
                output[name] = {
                    str(row["id"]): hashlib.sha256(canonical(dict(row)).encode()).hexdigest()
                    for row in rows
                }
        return output

    def retain_old_rows(self):
        current = self.retained_rows()
        if "retained_before" not in self.data:
            if self.data["phase"] != "allocated" or self.data["receipts"]:
                raise RuntimeError("Cannot invent a pre-execution retained baseline on recovery")
            self.data["retained_before"] = current
            self.save()
        for name, rows in self.data["retained_before"].items():
            if any(current.get(name, {}).get(key) != value for key, value in rows.items()):
                raise RuntimeError("An existing retained row changed; stop without repair")

    @contextmanager
    def session(self):
        from pdos_next.database import tenant_session

        self.target()
        with tenant_session(self.engine, self.tenant) as session:
            yield session

    @property
    def ctx(self):
        from pdos_next.service import Context

        return Context(self.tenant, self.actor, self.actor)

    @contextmanager
    def client(self):
        import httpx

        demo = self

        class VerifiedClient(httpx.Client):
            def request(self, *args, **kwargs):
                demo.target()
                return super().request(*args, **kwargs)

        with VerifiedClient(
            base_url="http://127.0.0.1:8898",
            trust_env=False,
            follow_redirects=False,
            timeout=180,
            headers={"Authorization": "Bearer " + self.data["login_token"]},
        ) as client:
            yield client

    def get(self, path, **params):
        with self.client() as client:
            return checked(client.get(f"/v1/products/{self.product}/{path}", params=params))

    def post(self, path, body):
        with self.client() as client:
            return checked(client.post(path, json=body))

    def key(self, label):
        return "wave15-" + self.data["demo_id"] + "-" + label

    def ref(self, line=1):
        return {
            "artifact_id": self.data["source_id"],
            "expected_revision": self.receipt_revision("independent-input"),
            "line": line,
            "quote": TEXT.splitlines()[line - 1],
        }

    def reads(self, *groups):
        return merge_reads(
            [
                {
                    "artifact_id": self.data["source_id"],
                    "expected_revision": self.receipt_revision("independent-input"),
                }
            ],
            *groups,
        )

    def submit(self, label, operation, payload, reads=(), *, inputs=None):
        from pdos_next.contracts import PAYLOADS
        from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS

        if label in self.data["receipts"]:
            return self.data["receipts"][label]
        cls = PAYLOADS.get(operation)
        if cls is None:
            raise RuntimeError("Required shared operation is not registered")
        payload = cls.model_validate(payload).model_dump(mode="json", exclude_none=True)
        entry = self.data["commands"].get(label)
        if entry is None:
            entry = {
                "command_id": str(uuid4()),
                "idempotency_key": self.key(label),
                "operation": operation,
                "product_id": str(self.product),
                "expected_revision": 1,
                "source_read_set": merge_reads(reads),
                "payload": payload,
            }
            if inputs:
                result = self.post(f"/v1/products/{self.product}/{inputs}", entry)
                if result.get("allowed") is not True:
                    raise RuntimeError("Current input capability is not affirmative")
                entry["source_read_set"] = result["required_source_read_set"]
            self.data["commands"][label] = entry
            self.save()  # Preserve exactly before any preview/execute uncertainty.
        elif entry["operation"] != operation:
            raise RuntimeError("Saved command label cannot change operation")
        if operation in T1_OPERATIONS | T2_OPERATIONS and not any(
            entry["payload"].get(key) for key in ("confirmation_token", "approval_token")
        ):
            entry = self.post("/v1/commands/preview", entry)["command"]
            self.data["commands"][label] = entry
            self.save()
        receipt = self.post("/v1/commands", entry)
        self.data["receipts"][label] = receipt
        self.save()
        return receipt

    def artifact(self, label, content):
        receipt = self.submit(
            label,
            "evidence.artifact.register",
            {
                "title": "Wave15 · " + label,
                "content": content,
                "source_label": "Explicit local synthetic only; not instrument or production proof",
                "visibility": "private",
            },
        )
        return receipt["subject_id"]

    def event(self, label, value):
        if label in self.data["events"]:
            return self.data["events"][label]
        text = canonical(value)
        identity = self.artifact("event-" + label, text)
        revision = self.receipt_revision("event-" + label)
        reference = {
            "artifact_id": identity,
            "expected_revision": revision,
            "line": 1,
            "quote": text,
        }
        result = {
            "reference": reference,
            "at": {
                "occurred_at": value["occurred_at"],
                "original_timezone": "UTC",
                "source": {
                    "id": identity,
                    "revision": revision,
                    "kind": "artifact",
                    "position": "line:1;quote_sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                },
            },
        }
        self.data["events"][label] = result
        self.save()
        return result

    def receipt_id(self, label):
        return self.data["receipts"][label]["subject_id"]

    def receipt_revision(self, label):
        return subject_revision(self.data["receipts"][label])

    def principal(self):
        from pdos_next.models import Grant, LoginSession, Principal, Product, now
        from pdos_next.service import digest
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        self.target()
        with Session(self.admin) as session, session.begin():
            product = session.get(Product, self.product)
            if product is None or product.tenant_id != self.tenant:
                raise RuntimeError("Preview Product binding unavailable")
            person = session.get(Principal, self.actor)
            if person is None:
                session.add(
                    Principal(
                        id=self.actor,
                        tenant_id=self.tenant,
                        name="Wave15 独立具名合成人员",
                        kind="human",
                    )
                )
                session.flush()
                session.add(
                    Grant(
                        tenant_id=self.tenant,
                        product_id=self.product,
                        principal_id=self.actor,
                        can_write=True,
                        expires_at=now() + timedelta(days=2),
                    )
                )
                session.add(
                    LoginSession(
                        tenant_id=self.tenant,
                        principal_id=self.actor,
                        token_hash=digest(self.data["login_token"]),
                        expires_at=now() + timedelta(days=2),
                    )
                )
            else:
                grant = session.scalar(
                    select(Grant).where(
                        Grant.tenant_id == self.tenant,
                        Grant.product_id == self.product,
                        Grant.principal_id == self.actor,
                    )
                )
                login = session.get(LoginSession, digest(self.data["login_token"]))
                if (
                    person.tenant_id != self.tenant
                    or person.kind != "human"
                    or not person.active
                    or not grant
                    or not grant.can_write
                    or grant.expires_at <= now()
                    or not login
                    or login.revoked
                    or login.expires_at <= now()
                ):
                    raise RuntimeError(
                        "New demo person's current access unavailable; no extension or repair"
                    )
        private_write(
            ROOT / ".local/wave15-login.json",
            {
                "marker": self.marker,
                "principal_id": str(self.actor),
                "product_id": str(self.product),
                "login_token": self.data["login_token"],
            },
        )

    def append_profile(self, name, entries):
        path = ROOT / (".local/" + name)
        value = (
            json.loads(path.read_text())
            if path.exists()
            else {"tenant_id": str(self.tenant), "product_id": str(self.product), "decisions": []}
        )
        if set(value) != {"tenant_id", "product_id", "decisions"} or (
            value["tenant_id"],
            value["product_id"],
        ) != (str(self.tenant), str(self.product)):
            raise RuntimeError("Finite profile scope mismatch; existing profile retained")
        before = deepcopy(value["decisions"])
        existing = {item["decision"]["named_decision_id"]: item for item in before}
        for entry in entries:
            key = entry["decision"]["named_decision_id"]
            if key in existing and canonical(existing[key]) != canonical(entry):
                raise RuntimeError("Existing finite named decision cannot change")
            if key not in existing:
                value["decisions"].append(entry)
                existing[key] = entry
        limit = 100 if name == "operational-synthetic-profile.json" else 200
        if len(value["decisions"]) > limit:
            raise RuntimeError("Finite profile capacity exceeded; existing file retained")
        if value["decisions"][: len(before)] != before:
            raise RuntimeError("Original profile entries changed")
        private_write(path, value)
        return value

    def authority(self, *, only_group=None):
        if only_group not in (None, "change-followup"):
            raise ValueError("Only the explicit change-followup recovery group is selectable")

        from pdos_next.domain.professional_authority.service import configure_local_synthetic
        from pdos_next.models import now
        from pdos_next.professional_import import import_professional_fact

        issuer = configure_local_synthetic(
            self.engine, tenant_id=self.tenant, product_id=self.product, enabled=True
        )
        if "authority_at" not in self.data:
            self.data["authority_at"] = now().isoformat()
            self.save()
        at = datetime.fromisoformat(self.data["authority_at"])
        groups = {
            "engineering": ["build.engineering.authorize"],
            "manufacturing": [
                "build.manufacturing.authorize",
                "build.start",
                "build.sample.readiness.record",
                "verification.handoff.offer",
            ],
            "quality-front": [
                "verification.request.create",
                "verification.method.prepare",
                "verification.actual_method.prepare",
                "verification.handoff.accept",
                "test.run.plan",
                "verification.schedule.promise",
                "test.run.start",
            ],
            "quality-results": [
                "test.results.import",
                "test.result.compute",
                "test.run.review",
                "test.disposition.decide",
            ],
            "quality-issue": [
                "quality.issue.create",
                "quality.issue.merge",
                "quality.issue.triage",
                "quality.issue.containment.record",
                "quality.capa.draft",
            ],
            "change-followup": ["change.request.create", "change.impact.compute"],
        }
        for group, operations in groups.items():
            if only_group is not None and group != only_group:
                continue
            for kind in ("duty", "qualification"):
                label = "authority-" + group + "-" + kind
                if label in self.data["receipts"]:
                    continue
                payload = {
                    "product_id": str(self.product),
                    "project_id": self.data["project_id"],
                    "subject_id": str(self.actor),
                    "external_id": self.key(label),
                    "kind": kind,
                    "role": "quality" if group == "change-followup" else group.split("-")[0],
                    "operations": operations,
                    "purposes": [PURPOSE],
                    "state": "active",
                    "valid_from": (at - timedelta(minutes=1)).isoformat(),
                    "valid_until": (at + timedelta(days=2)).isoformat(),
                    "approval": {
                        "system": "explicit-local-synthetic-wave15",
                        "external_id": self.key(label),
                        "version": "v1",
                        "approved_by": "独立合成具名签发，仅本地",
                        "issued_at": at.isoformat(),
                    },
                    "sources": [self.ref()],
                    "reason": (
                        "Independent scoped synthetic facts before every new approval; "
                        "no old facts changed"
                    ),
                }
                with self.session() as session:
                    result = import_professional_fact(
                        session,
                        self.ctx,
                        issuer,
                        payload,
                        request_key=self.key(label),
                        command_id=uuid4(),
                    )
                self.data["receipts"][label] = result
                self.save()

    def current(self, family):
        view = self.get(family, build_id=self.data["build_id"])
        request_id = view["current_by_request"][self.data["request_id"]]["request_version_id"]
        request = next(row for row in view["requests"] if row["id"] == request_id)
        run = None
        if self.data["run_id"] in view.get("current_by_run", {}):
            run_id = view["current_by_run"][self.data["run_id"]]["run_version_id"]
            run = next(row for row in view["runs"] if row["id"] == run_id)
        return view, request, run

    def prepare(self):
        from pdos_next.domain.build_start.rules import CONTROLS, PROFESSIONAL_RULES
        from pdos_next.models import now

        if self.data["phase"] in {"prepared_reload_required", "prepared_waiting"}:
            self.plan_and_promise()
            self.data["phase"] = "prepared_waiting"
            self.save()
            print(
                "Prepared all new domain actions; actual start_at="
                + self.data["execution_plan"]["window"]["start"]
            )
            return
        if "run-start" in self.data["receipts"]:
            raise RuntimeError("Prepare cannot rewrite a started demo")
        self.principal()
        self.data["source_id"] = self.artifact("independent-input", TEXT)
        self.save()
        reads, ref = self.reads(), self.ref()
        defined = self.submit(
            "definition",
            "product.definition.draft",
            {
                "title": "Wave15 独立定义（合成）",
                "purpose": PURPOSE,
                "use_cases": ["内部单模穴A问题调查"],
                "change_reason": "新独立身份，不改原定义",
                "sources": [ref],
            },
            reads,
        )
        projected = self.submit(
            "project",
            "project.create",
            {
                "name": "Wave15 独立调查项目",
                "purpose": PURPOSE,
                "scope": "Synthetic internal manufacturing and measurement only",
                "definition_id": defined["subject_id"],
                "expected_definition_revision": subject_revision(defined),
                "visibility": "private",
            },
            reads,
        )
        self.data["project_id"] = projected["subject_id"]
        self.save()
        common = {
            "visibility": "private",
            "reason": "Independent new fixed configuration",
            "sources": [ref],
        }
        bom = self.submit(
            "bom",
            "engineering.bom.revise",
            {
                **common,
                "name": "Wave15 已知单件BOM",
                "lines": [
                    {
                        "key": "unit",
                        "part": {"name": "Wave15 独立合成件"},
                        "quantity": "1",
                        "unit": "ea",
                        "loss_rate": "0",
                        "critical": True,
                    }
                ],
            },
            reads,
        )
        eng = self.submit(
            "engineering",
            "engineering.configuration.create",
            {
                **common,
                "name": "Wave15 独立工程配置",
                "definition_id": defined["subject_id"],
                "expected_definition_revision": subject_revision(defined),
                "bom_id": bom["subject_id"],
                "expected_bom_revision": subject_revision(bom),
            },
            reads,
        )
        process = self.submit(
            "manufacturing",
            "npi.process.revise",
            {
                **common,
                "name": "Wave15 独立制造配置",
                "engineering_configuration_id": eng["subject_id"],
                "expected_engineering_revision": subject_revision(eng),
                "operations": [
                    {
                        "key": "assembly",
                        "name": "独立合成装配",
                        "kind": "assembly",
                        "bom_line_keys": ["unit"],
                    }
                ],
            },
            reads,
        )
        build = self.submit(
            "build",
            "build.create",
            {
                "project_id": self.data["project_id"],
                "expected_project_revision": subject_revision(projected),
                "engineering_configuration_id": eng["subject_id"],
                "manufacturing_configuration_id": process["subject_id"],
                "name": "Wave15 独立单模穴A轮次",
                "type": "prototype",
                "purpose": PURPOSE,
                "planned_quantity": "1",
                "unit": "ea",
                "planned_start": None,
                "planned_end": None,
                "verification_objectives": "One A/dimension at 23 C, dry",
                "disposition_plan": "Retain internal synthetic sample; no external release",
            },
            reads,
        )
        self.data["build_id"] = build["subject_id"]
        self.save()
        self.authority()
        self.submit(
            "demand",
            "build.readiness.compute",
            {
                "build_id": self.data["build_id"],
                "expected_build_revision": self.receipt_revision("build"),
            },
            reads,
        )
        if not self.operational():
            return  # Root reloads appended finite profile; explicit prepare resume.
        scope = self.data["build_scope"]
        assessment_payload = {
            "build_id": self.data["build_id"],
            "expected_build_revision": self.receipt_revision("build"),
            "reason": "独立物料/资源当前准备度",
            "execution_scope": {
                "purpose": PURPOSE,
                "quantity": "1",
                "unit": "ea",
                "site": scope["site"],
                "window_start": scope["window"]["start"],
                "window_end": scope["window"]["finish"],
                "window_timezone": "UTC",
            },
        }
        bound = self.post(
            f"/v1/products/{self.product}/build-start/assessment-inputs", assessment_payload
        )
        self.submit(
            "assessment",
            "build.readiness.compute",
            assessment_payload,
            bound["required_source_read_set"],
        )
        state = self.get("build-start")
        assessment = next(
            row for row in state["assessments"] if row["id"] == self.receipt_id("assessment")
        )
        decisions = {}
        until = scope["window"]["finish"]
        for role in ("engineering", "manufacturing"):
            decisions[role] = self.submit(
                "approve-" + role,
                f"build.{role}.authorize",
                {
                    "assessment_id": assessment["id"],
                    "expected_assessment_revision": assessment["revision"],
                    "expected_assessment_sha256": assessment["snapshot_sha256"],
                    "action": "approve",
                    "valid_until": until,
                    "accepted_controls": sorted(CONTROLS),
                    "professional_assessments": [
                        {
                            "rule_id": rule,
                            "status": "applicable",
                            "sources": [ref],
                            "valid_until": until,
                            "reason": "Named bounded synthetic applicability",
                        }
                        for rule in PROFESSIONAL_RULES[role]
                    ],
                    "sources": [ref],
                    "reason": "Named internal-only T2; no production qualification",
                },
                assessment["required_source_read_set"],
            )
        occurred = now()
        event = self.event(
            "build-start",
            {
                "build_id": self.data["build_id"],
                "purpose": PURPOSE,
                "engineering_configuration_id": eng["subject_id"],
                "manufacturing_configuration_id": process["subject_id"],
                "occurred_at": occurred.isoformat(),
            },
        )
        self.submit(
            "build-start",
            "build.start",
            {
                "assessment_id": assessment["id"],
                "expected_assessment_revision": assessment["revision"],
                "expected_assessment_sha256": assessment["snapshot_sha256"],
                "engineering_authorization_id": decisions["engineering"]["subject_id"],
                "expected_engineering_authorization_revision": subject_revision(
                    decisions["engineering"]
                ),
                "manufacturing_authorization_id": decisions["manufacturing"]["subject_id"],
                "expected_manufacturing_authorization_revision": subject_revision(
                    decisions["manufacturing"]
                ),
                "occurred_at": event["at"]["occurred_at"],
                "occurred_timezone": "UTC",
                "event_source": event["reference"],
                "reason": "Independent actual synthetic manufacturing start",
            },
            self.reads(
                assessment["required_source_read_set"],
                [
                    {
                        "artifact_id": event["reference"]["artifact_id"],
                        "expected_revision": event["reference"]["expected_revision"],
                    }
                ],
            ),
        )
        self.physical(eng, process)
        self.formal()
        self.resources()
        self.data["phase"] = "prepared_reload_required"
        self.save()
        print(
            "Prepared independent facts; root must reload appended resource profiles before start."
        )

    def calendar(self):
        from pdos_next.engines.planning.calendar import frozen_timezone

        return {
            "calendar_id": self.key("utc-calendar"),
            "version": "1",
            "timezone": "UTC",
            "timezone_rules_sha256": frozen_timezone("UTC")[1],
            "weekly": [
                {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                for i in range(7)
            ],
        }

    def resource(self, kind, identity, operations, at, until):
        kinds = ("qualification",) if kind == "person" else ("acceptance", "calibration")
        return {
            "resource": {"id": str(identity), "revision": 1, "kind": kind},
            "purposes": [PURPOSE],
            "operation_ids": operations,
            "lifecycle": "active",
            "maintenance": [],
            "capacity": "1",
            "calendar": self.calendar(),
            "calendar_sources": [self.ref()],
            "external_occupancies_complete": True,
            "sources": [self.ref()],
            "facts": [
                {
                    "kind": k,
                    "purpose": PURPOSE,
                    "operation_id": operation,
                    "status": "accepted",
                    "valid_from": (at - timedelta(minutes=1)).isoformat(),
                    "valid_until": until.isoformat(),
                    "named_decision_id": str(uuid4()),
                    "actor_id": str(self.actor),
                    "sources": [self.ref()],
                }
                for operation in operations
                for k in kinds
            ],
        }

    def operational(self):
        from pdos_next.domain.build_operational_facts.schemas import FactInput
        from pdos_next.models import now
        from pdos_next.operational_bootstrap import configure_local_profile
        from pdos_next.operational_import import import_operational_fact

        if "operational" in self.data["receipts"]:
            return True
        if "operational_input" not in self.data:
            at, until = now(), now() + timedelta(hours=16)
            build = next(
                row for row in self.get("builds")["items"] if row["id"] == self.data["build_id"]
            )
            demand = build["readiness"]["result"]["demands"][0]
            scope = {
                "purpose": PURPOSE,
                "quantity": "1",
                "unit": "ea",
                "site": self.key("internal-lab"),
                "window": {
                    "start": (at - timedelta(minutes=1)).isoformat(),
                    "finish": until.isoformat(),
                    "original_timezone": "UTC",
                },
            }
            resource = self.resource(
                "equipment", self.data["build_equipment_id"], ["assembly"], at, until
            )
            payload = {
                "build_id": self.data["build_id"],
                "expected_build_revision": self.receipt_revision("build"),
                "scope": scope,
                "external_id": self.key("operational"),
                "valid_from": (at - timedelta(minutes=1)).isoformat(),
                "valid_until": until.isoformat(),
                "materials_scope_complete": True,
                "materials": [
                    {
                        "key": {
                            "source_system": "SYN-W15-EXACT",
                            "pool_id": self.key("new-pool"),
                            "material_id": demand["material_id"],
                        },
                        "version": 1,
                        "observed_at": at.isoformat(),
                        "stage": "on_hand",
                        "quantity": "1",
                        "unit": "ea",
                        "availability": "available",
                        "quality": "released",
                        "external_holds_complete": True,
                        "sources": [self.ref()],
                    }
                ],
                "resources": [resource],
                "requirements": [
                    {
                        "operation_key": "assembly",
                        "uses": [{"resource": resource["resource"], "units": "1"}],
                        "sources": [self.ref()],
                    }
                ],
                "sources": [self.ref()],
                "reason": "Exact independent synthetic observed balance/decisions",
            }
            binding = {
                "build_id": self.data["build_id"],
                "build_revision": self.receipt_revision("build"),
                "project_id": self.data["project_id"],
                "scope": scope,
                "engineering_configuration_id": self.receipt_id("engineering"),
                "engineering_configuration_revision": self.receipt_revision("engineering"),
                "manufacturing_configuration_id": self.receipt_id("manufacturing"),
                "manufacturing_configuration_revision": self.receipt_revision("manufacturing"),
            }
            self.data.update(
                operational_input=payload, operational_binding=binding, build_scope=scope
            )
            self.save()
        payload = FactInput.model_validate(self.data["operational_input"])
        # Match the domain's typed JSON binding exactly, including UTC formatting.
        self.data["operational_binding"]["scope"] = payload.scope.model_dump(mode="json")
        self.data["build_scope"] = payload.scope.model_dump(mode="json")
        self.data["operational_input"] = payload.model_dump(mode="json")
        self.save()
        profile = self.append_profile(
            "operational-synthetic-profile.json",
            [
                {
                    "binding": self.data["operational_binding"],
                    "resource": r.resource.model_dump(mode="json"),
                    "decision": d.model_dump(mode="json"),
                }
                for r in payload.resources
                for d in r.facts
            ],
        )
        issuer = configure_local_profile(self.engine, profile)
        with self.session() as session:
            receipt = import_operational_fact(
                session,
                self.ctx,
                issuer,
                payload,
                request_key=self.key("operational"),
                command_id=uuid4(),
            )
        self.data["receipts"]["operational"] = receipt
        self.data["phase"] = "operational_reload_required"
        self.save()
        print(
            "New independent operational ledger appended; reload API profile, then resume prepare."
        )
        return False

    def physical(self, engineering, manufacturing):
        from pdos_next.models import now

        reads = self.reads()
        actual = self.submit(
            "actual",
            "build.configuration.actual.record",
            {
                "build_id": self.data["build_id"],
                "expected_build_revision": self.receipt_revision("build"),
                "actual_engineering_configuration_id": engineering["subject_id"],
                "expected_actual_engineering_revision": subject_revision(engineering),
                "actual_manufacturing_configuration_id": manufacturing["subject_id"],
                "expected_actual_manufacturing_revision": subject_revision(manufacturing),
                "observed_at": now().isoformat(),
                "differences": [],
                "sources": [self.ref()],
                "reason": "New same-plan observed actual identity",
            },
            reads,
        )
        lot = self.submit(
            "lot",
            "build.output.record",
            {
                "build_id": self.data["build_id"],
                "expected_build_revision": self.receipt_revision("build"),
                "actual_configuration_id": actual["subject_id"],
                "expected_actual_configuration_revision": subject_revision(actual),
                "lot_label": self.key("lot-A"),
                "observed_unit_count": 1,
                "unit": "ea",
                "observation": {
                    "system": "explicit-synthetic-wave15",
                    "external_id": self.key("output"),
                    "nature": "synthetic",
                    "occurred_at": now().isoformat(),
                },
                "sources": [self.ref()],
                "reason": "New observed output only",
            },
            reads,
        )
        allocated = self.submit(
            "allocation",
            "build.sample.allocate",
            {
                "lot_id": lot["subject_id"],
                "expected_lot_revision": subject_revision(lot),
                "samples": [
                    {"label": self.key("sample-A"), "cavity": "A", "availability": "unknown"}
                ],
                "sources": [self.ref()],
                "reason": "Identify new sample; never reuse old A",
            },
            reads,
        )
        sample = next(
            row
            for row in self.get("build-execution")["samples"]
            if row["allocation_id"] == allocated["subject_id"]
        )
        self.data["sample"] = sample
        self.save()
        event = self.event(
            "sample-ready",
            {
                "sample_id": sample["id"],
                "lot_id": sample["lot_id"],
                "actual_configuration_id": sample["actual_configuration_id"],
                "build_id": self.data["build_id"],
                "state": "ready",
                "purpose": PURPOSE,
                "occurred_at": now().isoformat(),
            },
        )
        projection = self.get("sample-handoff", build_id=self.data["build_id"], purpose=PURPOSE)[
            "capabilities_by_sample"
        ][sample["id"]]
        self.submit(
            "ready",
            "build.sample.readiness.record",
            {
                "sample_id": sample["id"],
                "expected_sample_revision": sample["revision"],
                "state": "ready",
                "purpose": PURPOSE,
                "occurred_at": event["at"]["occurred_at"],
                "occurred_timezone": "UTC",
                "event_source": event["reference"],
                "sources": [self.ref()],
                "reason": "New purpose-specific actual sample ready",
            },
            self.reads(
                projection["required_source_read_set"],
                [
                    {
                        "artifact_id": event["reference"]["artifact_id"],
                        "expected_revision": event["reference"]["expected_revision"],
                    }
                ],
            ),
        )

    def formal(self):
        from pdos_next.domain.verification_handoff import service as handoff
        from pdos_next.models import now
        from pdos_next.schemas.verification.contracts import SampleRef

        self.submit(
            "preparation",
            "verification.preparation.record",
            {
                "request_id": self.data["preparation_request_id"],
                "expected_request_revision": 0,
                "build_id": self.data["build_id"],
                "expected_build_revision": self.receipt_revision("build"),
                "title": "Wave15 独立单模穴A尺寸调查",
                "purpose": PURPOSE,
                "return_form": "Native text JSONL with exact original bytes",
                "items": [
                    {
                        "id": "dimension",
                        "feature": "Dimension",
                        "drawing": self.ref(2),
                        "method": self.ref(3),
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
                        "title": "Fixed method information",
                        "item_ids": ["dimension"],
                        "source": self.ref(3),
                        "required": True,
                    }
                ],
                "sources": [self.ref()],
                "reason": "Independent 1/A scope; old 1/3+B/C untouched",
            },
            self.reads(),
        )
        prep = next(
            row
            for row in self.get("verification")["preparations"]
            if row["id"] == self.receipt_id("preparation")
        )
        self.submit(
            "formal",
            "verification.request.create",
            {
                "request_id": self.data["request_id"],
                "preparation_id": prep["id"],
                "expected_preparation_revision": prep["revision"],
                "preparation_sha256": prep["sha256"],
                "reason": "New formal immutable request",
            },
            prep["required_source_read_set"],
        )
        _, request, _ = self.current("verification-handoff")
        self.submit(
            "plan-method",
            "verification.method.prepare",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "assessments": [
                    {
                        "item_id": "dimension",
                        "status": "applicable",
                        "conditions": [],
                        "sources": [self.ref(3)],
                        "reason": "Named fixed-plan applicability",
                    }
                ],
                "reason": "New request only",
            },
            request["required_source_read_set"],
        )
        view, request, _ = self.current("verification-handoff")
        sample = next(
            row
            for row in view["reference_samples"]
            if row["request_id"] == self.data["request_id"]
            and row["id"] == self.data["sample"]["id"]
        )["reference"]
        fixed = SampleRef.model_validate(sample)
        with self.session() as session:
            inputs = handoff.inputs(
                session,
                self.ctx,
                self.product,
                UUID(self.data["request_id"]),
                request["revision"],
                (fixed,),
            )
        self.data["sample_ref"] = fixed.model_dump(mode="json")
        self.data["coverage"] = [{"sample_id": str(fixed.id), "item_id": "dimension"}]
        self.save()
        self.submit(
            "actual-method",
            "verification.actual_method.prepare",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "assessments": [
                    {
                        "sample": self.data["sample_ref"],
                        "item_id": "dimension",
                        "expected_assessment_revision": 0,
                        "status": "applicable",
                        "conditions": [],
                        "sources": [self.ref(3)],
                        "reason": "New physical actual pair applicability",
                    }
                ],
                "sources": [self.ref()],
                "reason": "New actual fact, no inherited old assessment",
            },
            inputs["required_source_read_set"],
        )
        for action in ("offer", "accept"):
            _, request, _ = self.current("verification-handoff")
            with self.session() as session:
                inputs = handoff.inputs(
                    session,
                    self.ctx,
                    self.product,
                    UUID(self.data["request_id"]),
                    request["revision"],
                    (fixed,),
                )
            value = {
                "request_id": self.data["request_id"],
                "purpose": PURPOSE,
                "operation": "verification.handoff." + action,
                "actor_id": str(self.actor),
                "occurred_at": now().isoformat(),
            }
            event = self.event(action, value)
            payload = {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "coverage": self.data["coverage"],
                "at": event["at"],
                "sources": [self.ref(), event["reference"]],
                "reason": "All independent 1/A pair only",
            }
            if action == "offer":
                payload["samples"] = [self.data["sample_ref"]]
            else:
                payload["returned_coverage"] = []
            self.submit(
                action,
                "verification.handoff." + action,
                payload,
                self.reads(
                    inputs["required_source_read_set"],
                    [
                        {
                            "artifact_id": event["reference"]["artifact_id"],
                            "expected_revision": event["reference"]["expected_revision"],
                        }
                    ],
                ),
            )

    def resources(self):
        from pdos_next.domain.test_resources.schemas import TestResourceFactInput
        from pdos_next.domain.verification_front import service as front
        from pdos_next.domain.verification_handoff import service as handoff
        from pdos_next.domain.verification_launch.schemas import ExecutionPlan
        from pdos_next.domain.verification_launch.service import _binding
        from pdos_next.models import now
        from pdos_next.test_resource_bootstrap import configure_local_profile
        from pdos_next.test_resource_import import import_test_resource_fact

        if "test-resource" in self.data["receipts"]:
            return
        if "test_resource_input" not in self.data:
            at, until = now(), now() + timedelta(hours=5)
            plan = ExecutionPlan.model_validate(
                {
                    "window": {
                        "start": (at + timedelta(minutes=self.data["lead_minutes"])).isoformat(),
                        "finish": (at + timedelta(hours=4)).isoformat(),
                        "original_timezone": "UTC",
                    },
                    "executor_id": str(self.actor),
                    "equipment": self.ref(2),
                    "calibration": self.ref(3),
                    "environment": "Explicit synthetic local lab",
                    "conditions": "23 C, dry",
                    "resource_fact_id": str(uuid4()),
                    "expected_resource_fact_revision": 1,
                }
            )
            with self.session() as session:
                _, row = front._current(
                    session, self.ctx, self.product, UUID(self.data["request_id"])
                )
                request = front._snapshot(row)
                methods = {
                    (UUID(p["sample_id"]), p["item_id"]): handoff._method_pointer(
                        session,
                        self.ctx,
                        self.product,
                        request.id,
                        UUID(p["sample_id"]),
                        p["item_id"],
                    )[1]
                    for p in self.data["coverage"]
                }
                binding = _binding(row, request, UUID(self.data["run_id"]), plan, methods)
            resources = [
                self.resource(
                    "equipment", self.data["test_equipment_id"], ["test.run.start"], at, until
                ),
                self.resource("person", str(self.actor), ["test.run.start"], at, until),
            ]
            payload = TestResourceFactInput.model_validate(
                {
                    "binding": binding,
                    "external_id": self.key("test-resource"),
                    "valid_from": (at - timedelta(minutes=1)).isoformat(),
                    "valid_until": until.isoformat(),
                    "resources": resources,
                    "required_uses": [{"resource": r["resource"], "units": "1"} for r in resources],
                    "requirements_sources": [self.ref()],
                    "sources": [self.ref(2), self.ref(3)],
                    "reason": "Exact independent finite Run resource binding",
                }
            )
            self.data["test_resource_input"] = payload.model_dump(mode="json")
            self.data["execution_plan"] = plan.model_dump(mode="json")
            self.save()
        payload = TestResourceFactInput.model_validate(self.data["test_resource_input"])
        profile = self.append_profile(
            "test-resource-synthetic-profile.json",
            [
                {
                    "binding": payload.binding.model_dump(mode="json"),
                    "resource": r.resource.model_dump(mode="json"),
                    "decision": d.model_dump(mode="json"),
                }
                for r in payload.resources
                for d in r.facts
            ],
        )
        issuer = configure_local_profile(self.engine, profile)
        with self.session() as session:
            receipt = import_test_resource_fact(
                session,
                self.ctx,
                self.product,
                issuer,
                payload,
                request_key=self.key("test-resource"),
                command_id=uuid4(),
            )
        self.data["receipts"]["test-resource"] = receipt
        self.data["execution_plan"]["resource_fact_id"] = receipt["subject_id"]
        self.data["execution_plan"]["expected_resource_fact_revision"] = subject_revision(receipt)
        self.save()

    def plan_and_promise(self):
        _, request, _ = self.current("verification-launch")
        self.submit(
            "run-plan",
            "test.run.plan",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "coverage": self.data["coverage"],
                "execution_plan": self.data["execution_plan"],
                "sources": [self.ref()],
                "reason": "Independent complete accepted plan at 23 C, dry",
            },
            inputs="verification-launch/inputs",
        )
        _, request, run = self.current("verification-launch")
        event = self.event(
            "promise",
            {
                "request_id": self.data["request_id"],
                "run_id": self.data["run_id"],
                "purpose": PURPOSE,
                "operation": "verification.schedule.promise",
                "executor_id": str(self.actor),
                "occurred_at": self.data["execution_plan"]["window"]["start"],
            },
        )
        self.submit(
            "promise",
            "verification.schedule.promise",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_plan_sha256": run["plan_sha256"],
                "at": event["at"],
                "sources": [self.ref(), event["reference"]],
                "reason": "Named real future-window commitment",
            },
            inputs="verification-launch/inputs",
        )

    def start(self):
        from pdos_next.models import now

        if self.data["phase"] not in {"prepared_waiting", "started"}:
            raise RuntimeError("Resume prepare after profile reload until Promise is saved")
        window = self.data["execution_plan"]["window"]
        begin, finish = (
            datetime.fromisoformat(window[k].replace("Z", "+00:00")) for k in ("start", "finish")
        )
        while now() < begin:
            self.target()
            time.sleep(min(30, max(0.05, (begin - now()).total_seconds())))
        if now() >= finish:
            raise RuntimeError("Window elapsed; no clock shift, new intent, or auto-replanning")
        _, request, run = self.current("verification-launch")
        event = self.event(
            "run-start",
            {
                "request_id": self.data["request_id"],
                "run_id": self.data["run_id"],
                "purpose": PURPOSE,
                "operation": "test.run.start",
                "executor_id": str(self.actor),
                "occurred_at": now().isoformat(),
            },
        )
        self.submit(
            "run-start",
            "test.run.start",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_plan_sha256": run["plan_sha256"],
                "at": event["at"],
                "sources": [self.ref(), event["reference"]],
                "reason": "Actual new Run start; existing Run is never reused",
            },
            inputs="verification-launch/inputs",
        )
        self.data["phase"] = "started"
        self.save()

    def result(self):
        from pdos_next.domain.verification_launch.models import VerificationRunVersion
        from pdos_next.domain.verification_launch.service import _snapshot
        from pdos_next.models import now
        from sqlalchemy import select

        if "run-start" not in self.data["receipts"]:
            raise RuntimeError("An actual immutable new Start is required")
        if "report" not in self.data:
            with self.session() as session:
                row = session.scalar(
                    select(VerificationRunVersion).where(
                        VerificationRunVersion.tenant_id == self.tenant,
                        VerificationRunVersion.product_id == self.product,
                        VerificationRunVersion.run_id == UUID(self.data["run_id"]),
                        VerificationRunVersion.revision == 2,
                    )
                )
                run, plan = _snapshot(row)
                sample, item = run.samples[0], run.items[0]
                observation = {
                    "format": "pdos-measurement-jsonl-v1",
                    "run_id": str(run.id),
                    "sample_id": str(sample.id),
                    "sample_revision": sample.revision,
                    "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                    "cavity": sample.cavity,
                    "item_id": item.id,
                    "raw_value": "11.0000",
                    "unit": item.unit,
                    "conditions": plan.conditions,
                    "equipment": run.execution.equipment.model_dump(mode="json"),
                    "equipment_label": "独立合成设备，不是真实仪器",
                    "calibration": run.execution.calibration.model_dump(mode="json"),
                    "environment": plan.environment,
                    "method": item.method.model_dump(mode="json"),
                    "executor_id": str(plan.executor_id),
                    "observed_at": now().isoformat(),
                    "observed_timezone": "UTC",
                    "note": (
                        "Explicit synthetic observation; exact uploaded bytes, "
                        "not real instrument data"
                    ),
                }
            if observation["conditions"] != "23 C, dry":
                raise RuntimeError("Saved fixed plan conditions mismatch; no report backfill")
            content = canonical(observation) + "\n"
            self.data["report"] = {
                "content": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
            self.save()
        upload = self.data.get("report_upload")
        if not upload:
            upload = self.post(
                f"/v1/products/{self.product}/originals",
                {
                    "idempotency_key": self.key("report-upload"),
                    "expected_revision": 1,
                    "title": "Wave15 独立合成11.0000原生报告",
                    "source_label": "Synthetic original JSONL; not instrument evidence",
                    "filename": "wave15.jsonl.txt",
                    "visibility": "private",
                    "content_base64": base64.b64encode(
                        self.data["report"]["content"].encode()
                    ).decode(),
                },
            )
            self.data["report_upload"] = upload
            self.save()
        original_id = upload["subject_id"]
        if "report-scan" not in self.data:
            original = next(
                row for row in self.get("workspace")["originals"] if row["id"] == original_id
            )
            self.data["report-scan"] = self.post(
                f"/v1/products/{self.product}/originals/{original_id}/scan",
                {
                    "expected_epoch": original["security"]["epoch"],
                    "idempotency_key": self.key("scan"),
                },
            )
            self.save()
        deadline = time.monotonic() + 300
        while True:
            view, request, run = self.current("verification-results")
            reports = [
                r
                for r in view["report_sources"]
                if r["original_id"] == original_id and r["source_status"] == "current"
            ]
            if reports:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Scan/parse/report gate unavailable; no fabricated safe or parse"
                )
            time.sleep(5)
        report = reports[0]
        capture = self.data.get("capture")
        if capture is None:
            payload = {
                "capture_key": self.key("capture"),
                "expected_product_revision": 1,
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "report_artifact_id": report["artifact_id"],
                "expected_report_revision": report["artifact_revision"],
                "selections": [
                    {"line": 1, "sample_id": self.data["sample"]["id"], "item_id": "dimension"}
                ],
                "reason": "One actual original-line synthetic observation",
            }
            self.data["capture_input"] = payload
            self.save()
            capture = self.post(
                f"/v1/products/{self.product}/verification-results/captures", payload
            )
            self.data["capture"] = capture
            self.save()
        ended = self.event(
            "end",
            {
                "request_id": self.data["request_id"],
                "run_id": self.data["run_id"],
                "purpose": PURPOSE,
                "operation": "test.run.end",
                "actor_id": str(self.actor),
                "occurred_at": now().isoformat(),
            },
        )
        returned = self.event(
            "results",
            {
                "request_id": self.data["request_id"],
                "run_id": self.data["run_id"],
                "purpose": PURPOSE,
                "operation": "test.results.import",
                "actor_id": str(self.actor),
                "occurred_at": now().isoformat(),
            },
        )
        self.submit(
            "results",
            "test.results.import",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "capture_id": capture["capture"]["id"],
                "expected_capture_revision": capture["capture"]["revision"],
                "final": True,
                "at": returned["at"],
                "actual_end": ended["at"],
                "sources": [ended["reference"], returned["reference"]],
                "reason": "Final complete 1/A true uploaded synthetic raw11.0000",
            },
            inputs="verification-results/inputs",
        )
        _, request, run = self.current("verification-results")
        self.submit(
            "compute",
            "test.result.compute",
            {
                "request_id": self.data["request_id"],
                "expected_request_revision": request["revision"],
                "run_id": self.data["run_id"],
                "expected_run_revision": run["revision"],
                "expected_basis_sha256": run["basis_sha256"],
                "reason": "Canonical fixed Decimal11.0000 vs9.5..10.5; no professional conclusion",
            },
            inputs="verification-results/inputs",
        )
        _, _, run = self.current("verification-results")
        if run["run_snapshot"]["result"] != "fail":
            raise RuntimeError("Result is not authoritative fail; do not create an Issue")
        self.data["phase"] = "definite_fail"
        self.save()
        print("New fixed Run has definite fail; old indeterminate Run is retained unchanged.")

    def quality(self):
        from pdos_next.domain.quality_execution.policy import configure_local_synthetic
        from pdos_next.models import now
        from pdos_next.quality_policy_import import import_quality_policy_fact

        if "compute" not in self.data["receipts"]:
            raise RuntimeError("Definite fail result stage is required")
        if "policy_input" not in self.data:
            at = now()
            publication = {
                "external_id": self.key("quality-policy"),
                "purpose": PURPOSE,
                "risk": "high",
                "independent_verification": True,
                "state": "active",
                "valid_from": (at - timedelta(minutes=1)).isoformat(),
                "valid_until": (at + timedelta(days=1)).isoformat(),
                "approval": {
                    "system": "explicit-local-synthetic-wave15",
                    "external_id": self.key("policy-approval"),
                    "version": "v1",
                    "approved_by": "合成具名政策发布，不是真实政策",
                    "issued_at": at.isoformat(),
                },
            }
            identity = self.artifact("policy-source", canonical(publication))
            self.data["policy_input"] = {
                "product_id": str(self.product),
                "project_id": self.data["project_id"],
                **publication,
                "sources": [
                    {
                        "artifact_id": identity,
                        "expected_revision": self.receipt_revision("policy-source"),
                        "line": 1,
                        "quote": canonical(publication),
                    }
                ],
                "reason": "Explicit scoped synthetic risk policy",
            }
            self.save()
        profile = {
            "tenant_id": str(self.tenant),
            "product_id": str(self.product),
            "project_id": self.data["project_id"],
            "issuer_key": self.key("policy-issuer"),
            "issuer_version": "v1",
        }
        path = ROOT / ".local/quality-synthetic-profile.json"
        if path.exists() and json.loads(path.read_text()) != profile:
            private_write(ROOT / ".local/wave15-quality-profile.json", profile)
            raise RuntimeError(
                "Existing policy profile retained; "
                "root must support both scopes before quality stage"
            )
        if "policy" not in self.data["receipts"]:
            private_write(path, profile)
            issuer = configure_local_synthetic(
                self.engine,
                tenant_id=self.tenant,
                product_id=self.product,
                project_id=UUID(self.data["project_id"]),
                key=profile["issuer_key"],
                enabled=True,
                test_marker_verified=True,
            )
            with self.session() as session:
                receipt = import_quality_policy_fact(
                    session,
                    self.ctx,
                    issuer,
                    self.data["policy_input"],
                    request_key=self.key("policy"),
                    command_id=uuid4(),
                )
            self.data["receipts"]["policy"] = receipt
            self.data["phase"] = "quality_profile_reload_required"
            self.save()
            print(
                "Explicit scoped policy saved; root reloads policy profile before quality resume."
            )
            return
        view = self.get(
            "quality-execution", build_id=self.data["build_id"], run_id=self.data["run_id"]
        )
        failure = next(
            f
            for f in view["failures"]
            if f["available"] and f["failure"]["run"]["id"] == self.data["run_id"]
        )
        issue = self.submit(
            "issue",
            "quality.issue.create",
            {
                "run_id": self.data["run_id"],
                "measurement_id": failure["failure"]["measurement_id"],
                "event_id": failure["event_ids"][0],
                "title": "Wave15 独立单模穴A尺寸确定失败调查",
                "visibility": "private",
            },
            inputs="quality-execution/inputs",
        )
        issue_id = issue["result"]["issue_id"]
        self.data["issue_id"] = issue_id
        self.save()

        def current_issue():
            reading = self.get("quality-execution", issue_id=issue_id)
            row_id = reading["current_by_issue"][issue_id]["issue_version_id"]
            return next(row for row in reading["issues"] if row["id"] == row_id)

        row = current_issue()
        self.submit(
            "triage",
            "quality.issue.triage",
            {
                "issue_id": issue_id,
                "expected_issue_revision": row["revision"],
                "reason": "Named internal problem triage",
            },
            inputs="quality-execution/inputs",
        )
        row = current_issue()
        event = self.event(
            "containment",
            {
                "issue_id": issue_id,
                "purpose": PURPOSE,
                "operation": "quality.issue.containment.record",
                "actor_id": str(self.actor),
                "occurred_at": now().isoformat(),
            },
        )

        def source_ref(reference):
            return {
                "id": reference["artifact_id"],
                "revision": reference["expected_revision"],
                "kind": "artifact",
                "position": f"line:{reference['line']};quote_sha256:"
                + hashlib.sha256(reference["quote"].encode()).hexdigest(),
            }

        action_id = self.data.setdefault("containment_action_id", str(uuid4()))
        self.save()
        self.submit(
            "containment",
            "quality.issue.containment.record",
            {
                "issue_id": issue_id,
                "expected_issue_revision": row["revision"],
                "action": {
                    "id": action_id,
                    "text": "独立合成样件仅保留内部调查，非释放/关闭",
                    "executor_id": str(self.actor),
                    "evidence": [source_ref(self.ref(4))],
                    "at": event["at"],
                },
            },
            inputs="quality-execution/inputs",
        )
        row = current_issue()
        self.data.setdefault("capa_id", str(uuid4()))
        self.data.setdefault("capa_action_id", str(uuid4()))
        self.save()
        self.submit(
            "capa",
            "quality.capa.draft",
            {
                "issue_id": issue_id,
                "expected_issue_revision": row["revision"],
                "capa_id": self.data["capa_id"],
                "hypotheses": [
                    {"text": "尺寸偏差可能原因，尚非根因", "sources": [source_ref(self.ref(5))]}
                ],
                "actions": [
                    {
                        "id": self.data["capa_action_id"],
                        "kind": "corrective",
                        "text": "调查固定工况下尺寸偏差",
                        "executor_id": str(self.actor),
                        "completion": None,
                    }
                ],
                "requirement": {
                    "method": "Independent future verification needed",
                    "acceptance": "Dimension9.5..10.5 at23 C,dry",
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [failure["failure"]["identity"]],
                },
            },
            inputs="quality-execution/inputs",
        )
        self.data["phase"] = "capa_draft_only"
        self.save()
        print("New Issue/CAPA draft saved; no root cause, effectiveness, closure or release.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "start", "result", "quality"))
    parser.add_argument("--marker", type=UUID, required=True)
    parser.add_argument("--ack-synthetic-local", action="store_true", required=True)
    parser.add_argument("--lead-minutes", type=int, choices=range(5, 31), default=10)
    args = parser.parse_args()
    if not args.ack_synthetic_local:
        raise RuntimeError("Explicit local synthetic acknowledgement required")
    sys.path.insert(0, str(SERVER))
    demo = Demo(args.marker, lead_minutes=args.lead_minutes)
    getattr(demo, args.phase)()
    demo.retain_old_rows()
    print("Checkpoint saved; pre-existing recorded rows and physical asset epochs unchanged.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        detail = type(error).__name__
        if isinstance(error, GuardedRequestError):
            detail = f"HTTP {error.status}/{error.code}"
        elif type(error).__module__ == "pdos_next.errors":
            detail = safe_code(getattr(error, "code", None))
        print("Demo halted; private checkpoint retained. " + detail, file=sys.stderr)
        raise SystemExit(1) from None
