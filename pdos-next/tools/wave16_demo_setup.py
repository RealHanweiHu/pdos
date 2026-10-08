"""Explicit, resumable synthetic preparation only; no follow-up business commands.

Importing this module performs no IO. The root session executes a selected phase
after the public registry/migration is ready and the observed completion is known.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
LOCAL = ROOT / ".local"
OLD_SEED = LOCAL / "wave15-seed.json"
SEED = LOCAL / "wave16-seed.json"
PROFILE = LOCAL / "quality-followup-synthetic-profile.json"
OPERATIONS = (
    "quality.issue.root_cause.decide",
    "quality.capa.actions.complete",
    "quality.capa.followup.link",
)
PHASES = (
    "authority",
    "root-source",
    "completion-source",
    "classification-profile",
    "owner-options",
    "status",
)


class Stop(Exception):
    """Safe code only: exception bodies, URLs, credentials and SQL are withheld."""


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Stop("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def finite_json(_value):
    raise Stop("NONFINITE_PRIVATE_JSON")


def private_read(path):
    """Read only owner-held regular files; never follow a private-path symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise Stop("PRIVATE_SETUP_INPUT_MISSING") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size > 8_388_608
        ):
            raise Stop("PRIVATE_FILE_GUARD_FAILED")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = None
            data = json.load(stream, object_pairs_hook=unique_object, parse_constant=finite_json)
        if not isinstance(data, dict):
            raise Stop("PRIVATE_JSON_OBJECT_REQUIRED")
        return data
    finally:
        if fd is not None:
            os.close(fd)


def private_write(path, value, *, immutable=False):
    """Persist commands before effects, and refuse an existing different profile."""
    if path.exists() or path.is_symlink():
        previous = private_read(path)
        if immutable:
            if previous != value:
                raise Stop("PRIVATE_PROFILE_MATERIAL_CONFLICT")
            return
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def setup_lock():
    if (
        LOCAL.is_symlink()
        or not LOCAL.is_dir()
        or LOCAL.stat().st_uid != os.getuid()
        or LOCAL.stat().st_mode & 0o022
    ):
        raise Stop("PRIVATE_DIRECTORY_GUARD_FAILED")
    fd = os.open(LOCAL / "wave16-setup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise Stop("SETUP_LOCK_GUARD_FAILED")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def observed_iso(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise Stop("EXPLICIT_OBSERVED_ISO_REQUIRED")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Stop("AWARE_OBSERVED_TIME_REQUIRED")
    return parsed.astimezone(UTC)


def single_line(value):
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > 2000
        or len(value.splitlines()) != 1
        or "\x00" in value
    ):
        raise Stop("EXPLICIT_SINGLE_LINE_TEXT_REQUIRED")
    return value


class Preparation:
    """New preparation state; never constructs/imports the old Wave15 Demo."""

    def __init__(self, args):
        from local_environment import read_state, verified
        from pdos_next.database import engine_for
        from pdos_next.service import Context

        self.args, self.read_state, self.verified = args, read_state, verified
        original = private_read(OLD_SEED)
        keys = ("tenant_id", "product_id", "project_id", "actor_id", "issue_id", "capa_id")
        try:
            self.scope = {key: str(UUID(original[key])) for key in keys}
        except (KeyError, ValueError, TypeError) as exc:
            raise Stop("OBSERVED_WAVE15_ISSUE_CAPA_SCOPE_REQUIRED") from exc
        if str(original.get("marker")) != str(args.marker):
            raise Stop("OLD_SEED_MARKER_MISMATCH")
        self.marker = str(args.marker)
        self.state = self.target()
        if (self.scope["tenant_id"], self.scope["product_id"]) != (
            str(self.state["preview_tenant_id"]),
            str(self.state["preview_product_id"]),
        ):
            raise Stop("SEED_TARGET_SCOPE_MISMATCH")
        self.engine = engine_for(self.state["app_url"])
        self.admin = engine_for(self.state["admin_url"])
        self.ctx = Context(
            UUID(self.scope["tenant_id"]),
            UUID(self.scope["actor_id"]),
            UUID(self.scope["actor_id"]),
        )
        self.product = UUID(self.scope["product_id"])
        self.check_head()
        self.data = (
            private_read(SEED)
            if SEED.exists()
            else {
                "schema": "wave16-explicit-synthetic-preparation-v1",
                "marker": self.marker,
                "container_id": self.state["container_id"],
                "scope": self.scope,
                "setup_id": str(uuid4()),
                "commands": {},
                "receipts": {},
                "materials": {},
                "business_commands_executed": [],
                "effectiveness": None,
                "closure": None,
            }
        )
        if (
            self.data.get("scope") != self.scope
            or self.data.get("marker") != self.marker
            or self.data.get("container_id") != self.state["container_id"]
            or self.data.get("business_commands_executed") != []
        ):
            raise Stop("WAVE16_CHECKPOINT_SCOPE_CONFLICT")
        self.saved_action = original.get("capa_action_id")
        if args.action is not None:
            if self.saved_action and UUID(self.saved_action) != args.action:
                raise Stop("OBSERVED_ACTION_SELECTION_CONFLICT")
            self.saved_action = str(args.action)
        self.issue_context()
        if args.phase != "status":
            self.dependencies()
            self.save()

    def target(self):
        state = self.read_state()
        if state["port"] != 62513 or str(state["marker"]) != self.marker:
            raise Stop("EXACT_SYNTHETIC_TARGET_REQUIRED")
        for name in ("admin_url", "app_url", "auth_url"):
            url = urlsplit(state[name])
            if (
                url.scheme != "postgresql+psycopg"
                or url.hostname not in {"127.0.0.1", "localhost"}
                or url.port != 62513
                or url.path != "/pdos_test"
            ):
                raise Stop("EXACT_SYNTHETIC_ENDPOINT_REQUIRED")
        if hasattr(self, "state") and state["container_id"] != self.state["container_id"]:
            raise Stop("SYNTHETIC_TARGET_REPLACED")
        return self.verified(state)

    def check_head(self):
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        self.target()
        with Session(self.admin) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            heads = list(session.scalars(text("SELECT version_num FROM alembic_version")))
        if heads != [self.args.expected_head]:
            raise Stop("EXPLICIT_MIGRATION_HEAD_MISMATCH")

    @contextmanager
    def session(self):
        from pdos_next.database import tenant_session

        self.target()
        self.check_head()
        with tenant_session(self.engine, self.ctx.tenant_id) as session:
            yield session

    def dependencies(self):
        from pdos_next.command_handlers import T1_OPERATIONS, T2_OPERATIONS, handler
        from pdos_next.contracts import PAYLOADS
        from pdos_next.domain.professional_authority.service import OPERATION_ROLES

        if (
            any(
                op not in PAYLOADS
                or "quality" not in OPERATION_ROLES.get(op, ())
                or handler(op) is None
                for op in OPERATIONS
            )
            or OPERATIONS[0] not in T2_OPERATIONS
            or any(op not in T1_OPERATIONS or op in T2_OPERATIONS for op in OPERATIONS[1:])
            or OPERATIONS[0] in T1_OPERATIONS
        ):
            raise Stop("FOLLOWUP_PUBLIC_MATRIX_INTEGRATION_REQUIRED")

    def save(self):
        private_write(SEED, self.data)

    def material(self, name, value):
        old = self.data["materials"].get(name)
        if old is not None and old != value:
            raise Stop("PREPARATION_MATERIAL_CONFLICT")
        self.data["materials"][name] = value
        self.save()
        return value

    def issue_context(self):
        from pdos_next.domain.quality_execution import service as quality
        from pdos_next.models import Principal
        from pdos_next.service import digest

        with self.session() as session:
            quality._human(session, self.ctx, self.product, write=False)
            person = session.get(Principal, self.ctx.requester_id)
            if person is None or not person.active or person.tenant_id != self.ctx.tenant_id:
                raise Stop("CURRENT_NAMED_PERSON_REQUIRED")
            row = quality._row(session, self.ctx, self.product, UUID(self.scope["issue_id"]))
            issue = quality._snapshot(row)
            if (
                str(row.project_id) != self.scope["project_id"]
                or issue.capa is None
                or str(issue.capa.id) != self.scope["capa_id"]
                or issue.merged_into
                or issue.needs_recheck
                or {f.nature for f in issue.failures} != {"synthetic"}
                or issue.capa.effectiveness is not None
                or issue.closure is not None
            ):
                raise Stop("CURRENT_SYNTHETIC_ISSUE_CAPA_REQUIRED")
            actions = [
                a
                for a in issue.capa.actions
                if a.executor_id == self.ctx.requester_id
                and (self.saved_action is None or str(a.id) == self.saved_action)
            ]
            if len(actions) != 1:
                raise Stop("EXACT_OWN_ACTION_SELECTION_REQUIRED")
            action = actions[0]
            observed = {
                "action_id": str(action.id),
                "executor_id": str(action.executor_id),
                "purpose": row.purpose,
                "action_sha256": digest(action.model_dump(mode="json", exclude={"completion"})),
            }
            if "action_binding" in self.data and self.data["action_binding"] != observed:
                raise Stop("FIXED_CAPA_ACTION_CHANGED")
            self.data["action_binding"] = observed
            self.data.setdefault(
                "observed_issue_basis",
                {
                    "issue_version_id": str(row.id),
                    "issue_revision": row.revision,
                    "snapshot_sha256": row.snapshot_sha256,
                },
            )
            self.issue, self.action, self.purpose = issue, action, row.purpose

    def artifact(self, label, content):
        from pdos_next.contracts import Command
        from pdos_next.domain.quality_execution.evidence import check_source
        from pdos_next.models import Product
        from pdos_next.service import execute, source_for

        self.issue_context()
        payload = {
            "title": f"Wave16 · {label}",
            "content": content,
            "visibility": "private",
            "source_label": (
                "Explicit local synthetic native text; no instrument or production qualification"
            ),
        }
        self.material(f"artifact:{label}", payload)
        if label not in self.data["commands"]:
            with self.session() as session:
                product = session.get(Product, self.product)
                if product is None or product.tenant_id != self.ctx.tenant_id:
                    raise Stop("PRODUCT_SCOPE_UNAVAILABLE")
                command = Command(
                    command_id=uuid4(),
                    idempotency_key=f"wave16:{self.data['setup_id']}:native:{label}",
                    operation="evidence.artifact.register",
                    product_id=self.product,
                    expected_revision=product.revision,
                    payload=payload,
                )
            self.data["commands"][label] = command.model_dump(mode="json")
            self.save()
        command = Command.model_validate(self.data["commands"][label])
        if command.operation != "evidence.artifact.register" or command.payload != payload:
            raise Stop("STORED_PREPARATION_COMMAND_CONFLICT")
        with self.session() as session:
            result = execute(session, self.ctx, command)
            if (
                result["operation"] != command.operation
                or result["subject_type"] != "artifact"
                or result["writer_id"] != str(self.ctx.requester_id)
                or result["requester_id"] != str(self.ctx.requester_id)
            ):
                raise Stop("ACTUAL_NATIVE_RECEIPT_REQUIRED")
            source = source_for(
                session,
                self.ctx,
                self.product,
                UUID(result["subject_id"]),
                result["subject_revision"],
            )
            if (
                source.original_id is not None
                or source.content != content
                or source.visibility != "private"
            ):
                raise Stop("ACTUAL_NATIVE_PUBLICATION_MISMATCH")
            refs = []
            for line, quote in enumerate(content.splitlines(), 1):
                ref = {
                    "kind": "artifact",
                    "id": str(source.id),
                    "revision": source.revision,
                    "position": (
                        f"line:{line};quote_sha256:" + hashlib.sha256(quote.encode()).hexdigest()
                    ),
                }
                _reads, basis, _private = check_source(session, self.ctx, self.product, ref)
                if len(basis) != 1 or basis[0].get("source_kind") != "registered_native_text":
                    raise Stop("ACTUAL_NATIVE_REGISTRATION_PROOF_REQUIRED")
                refs.append(
                    {
                        "source": ref,
                        "definition_reference": {
                            "artifact_id": str(source.id),
                            "expected_revision": source.revision,
                            "line": line,
                            "quote": quote,
                        },
                        "source_basis": basis,
                    }
                )
        # A commit-before-checkpoint crash replays the exact persisted common command.
        self.data["receipts"][label] = result
        self.data.setdefault("publications", {})[label] = refs
        self.save()
        return refs

    def authority(self):
        from pdos_next.domain.professional_authority.schemas import FactInput
        from pdos_next.domain.professional_authority.service import configure_local_synthetic
        from pdos_next.professional_import import import_professional_fact

        timing = self.data["materials"].get("authority_timing")
        if timing is None:
            issued = datetime.now(UTC)
            deadline = (
                observed_iso(self.args.valid_until)
                if self.args.valid_until
                else issued + timedelta(days=2)
            )
            timing = {
                "issued_at": issued.isoformat(),
                "valid_from": (issued - timedelta(minutes=1)).isoformat(),
                "valid_until": deadline.isoformat(),
            }
        if self.args.valid_until and observed_iso(self.args.valid_until) != observed_iso(
            timing["valid_until"]
        ):
            raise Stop("SAVED_AUTHORITY_DEADLINE_CONFLICT")
        if observed_iso(timing["valid_until"]) <= datetime.now(UTC):
            raise Stop("SAVED_AUTHORITY_EXPIRED_NO_IMPLICIT_RENEWAL")
        self.material("authority_timing", timing)
        publication = "\n".join(
            canonical(
                {
                    "nature": "synthetic",
                    "subject_id": self.scope["actor_id"],
                    "project_id": self.scope["project_id"],
                    "operation": op,
                    "purpose": self.purpose,
                    "role": "quality",
                    **timing,
                    "limitation": (
                        "Explicit local synthetic only; not production authority "
                        "or effectiveness/closure approval"
                    ),
                }
            )
            for op in OPERATIONS
        )
        refs = self.artifact("三项具名演练职责出处", publication)
        issuer = configure_local_synthetic(
            self.engine, tenant_id=self.ctx.tenant_id, product_id=self.product, enabled=True
        )
        for index, operation in enumerate(OPERATIONS):
            for kind in ("duty", "qualification"):
                label = f"authority:{index}:{kind}"
                external = f"wave16:{self.data['setup_id']}:{index}:{kind}"
                payload = FactInput(
                    product_id=self.product,
                    project_id=UUID(self.scope["project_id"]),
                    subject_id=self.ctx.requester_id,
                    external_id=external,
                    kind=kind,
                    role="quality",
                    operations=[operation],
                    purposes=[self.purpose],
                    valid_from=timing["valid_from"],
                    valid_until=timing["valid_until"],
                    sources=[refs[index]["definition_reference"]],
                    approval={
                        "system": "explicit-local-synthetic-wave16",
                        "external_id": external,
                        "version": "v1",
                        "approved_by": "具名本地合成签发；无生产资格",
                        "issued_at": timing["issued_at"],
                    },
                    reason="独立新增Wave16演练职责/资格系列，保留所有既有系列，不授权有效性或关闭",
                )
                value = {
                    "payload": payload.model_dump(mode="json"),
                    "request_key": f"wave16:{self.data['setup_id']}:{index}:{kind}",
                    "command_id": str(uuid4()),
                }
                saved = self.data["commands"].get(label)
                if saved is not None:
                    if (
                        saved["payload"] != value["payload"]
                        or saved["request_key"] != value["request_key"]
                    ):
                        raise Stop("STORED_PROFESSIONAL_FACT_CONFLICT")
                    value = saved
                else:
                    self.data["commands"][label] = value
                    self.save()
                with self.session() as session:
                    result = import_professional_fact(
                        session,
                        self.ctx,
                        issuer,
                        value["payload"],
                        request_key=value["request_key"],
                        command_id=UUID(value["command_id"]),
                    )
                    if (
                        result["subject_type"] != "professional_authority_fact"
                        or result["result"].get("nature") != "synthetic"
                    ):
                        raise Stop("ACTUAL_SYNTHETIC_FACT_RECEIPT_REQUIRED")
                self.data["receipts"][label] = result
                self.save()

    def root_source(self):
        text = single_line(self.args.root_text)
        self.artifact(
            "根因调查提议出处", "【本地合成调查提议，待具名T2决定；非有效性/关闭结论】" + text
        )
        self.material("root_cause_text", text)

    def completion_source(self):
        from pdos_next.domain.quality_followup.evidence import verify_completion_line
        from pdos_next.domain.quality_followup.schemas import Completion, CompletionFact

        original = self.args.occurred_at
        occurred = observed_iso(original)
        if occurred > datetime.now(UTC):
            raise Stop("COMPLETION_MUST_ALREADY_HAVE_OCCURRED")
        ZoneInfo(self.args.timezone)
        text = single_line(self.args.completion_text)
        raw = {
            "issue_id": self.scope["issue_id"],
            "capa_id": self.scope["capa_id"],
            "action_id": str(self.action.id),
            "executor_id": self.scope["actor_id"],
            "operation": OPERATIONS[1],
            "occurred_at": original,
            "original_timezone": self.args.timezone,
            "purpose": self.purpose,
            "text": text,
        }
        CompletionFact.model_validate(raw)
        self.material(
            "observed_completion",
            {
                "raw": raw,
                "occurred_at_utc": occurred.isoformat(),
                "nature": "explicit_local_synthetic_observation",
            },
        )
        refs = self.artifact("已发生调查措施出处", canonical(raw))
        completion = Completion(
            id=self.action.id,
            text=text,
            executor_id=self.ctx.requester_id,
            evidence=[refs[0]["source"]],
            at={
                "occurred_at": original,
                "original_timezone": self.args.timezone,
                "source": refs[0]["source"],
            },
        )
        verify_completion_line(
            canonical(raw),
            issue=self.issue,
            purpose=self.purpose,
            completion=completion,
            actor_id=self.ctx.requester_id,
            at=datetime.now(UTC),
        )
        self.material("completion_for_ui", completion.model_dump(mode="json"))

    def classification_profile(self):
        from pdos_next.quality_followup_bootstrap import ClassificationFact, CompletionProfile

        saved_profile = self.data["materials"].get("classification_profile")
        if PROFILE.exists() or PROFILE.is_symlink():
            actual_profile = private_read(PROFILE)
            if saved_profile is None or actual_profile != saved_profile.get("profile"):
                raise Stop("PRIVATE_PROFILE_MATERIAL_CONFLICT")

        deadline = self.data["materials"].get("classification_valid_until")
        if deadline is None:
            if not self.args.valid_until:
                raise Stop("EXPLICIT_CLASSIFICATION_VALID_UNTIL_REQUIRED")
            deadline = observed_iso(self.args.valid_until).isoformat()
        if self.args.valid_until and observed_iso(self.args.valid_until).isoformat() != deadline:
            raise Stop("SAVED_CLASSIFICATION_DEADLINE_CONFLICT")
        if observed_iso(deadline) <= datetime.now(UTC):
            raise Stop("SAVED_CLASSIFICATION_EXPIRED_NO_IMPLICIT_RENEWAL")
        self.material("classification_valid_until", deadline)
        raw = {
            "tenant_id": self.scope["tenant_id"],
            "product_id": self.scope["product_id"],
            "project_id": self.scope["project_id"],
            "issue_id": self.scope["issue_id"],
            "capa_id": self.scope["capa_id"],
            "action_id": str(self.action.id),
            "executor_id": self.scope["actor_id"],
            "purpose": self.purpose,
            "action_sha256": self.data["action_binding"]["action_sha256"],
            "classification": "investigation",
            "nature": "synthetic",
            "valid_until": deadline,
        }
        ClassificationFact.model_validate(raw)
        refs = self.artifact("调查分类具名出版出处", canonical(raw))
        entry = {
            key: raw[key]
            for key in (
                "issue_id",
                "capa_id",
                "action_id",
                "executor_id",
                "purpose",
                "action_sha256",
                "classification",
                "nature",
                "valid_until",
            )
        }
        profile = CompletionProfile(
            tenant_id=self.ctx.tenant_id,
            product_id=self.product,
            project_id=UUID(self.scope["project_id"]),
            entries=[{**entry, "source": refs[0]["source"]}],
        )
        value = profile.model_dump(mode="json")
        self.material(
            "classification_profile",
            {
                "relative_path": str(PROFILE.relative_to(ROOT)),
                "sha256": sha(value),
                "profile": value,
            },
        )
        private_write(PROFILE, value, immutable=True)

    def owner_options(self):
        # The public adapter actually resolves each saved owner and Receipt/source proof.
        # Missing runtime/owner ports fail explicitly; no fake "valid candidate" fallback.
        from pdos_next.quality_followup_integration import request_options
        from pdos_next.quality_followup_views import configure_output_options, list_quality_followup

        configure_output_options(self.engine, request_options)
        with self.session() as session:
            view = list_quality_followup(
                session, self.ctx, self.product, issue_id=UUID(self.scope["issue_id"])
            )
            if view.get("basis") is None or view["issue"].get("source_status") != "current":
                raise Stop("OWNER_OPTIONS_INTEGRATION_OR_RECHECK_REQUIRED")
            options = view["output_options"]
        self.material(
            "owner_options_observed",
            {
                "options": options,
                "integration": view["integration"],
                "candidate_verified": False,
                "effectiveness": None,
                "closure": None,
                "limitation": (
                    "Actual owner references only; applicability/independence/observation "
                    "still require their ports"
                ),
            },
        )

    def run(self):
        if self.args.phase != "status":
            getattr(self, self.args.phase.replace("-", "_"))()
        return {
            "phase": self.args.phase,
            "preparation_only": True,
            "saved_receipts": len(self.data["receipts"]),
            "classification_profile_saved": "classification_profile" in self.data["materials"],
            "completion_observation_saved": "observed_completion" in self.data["materials"],
            "business_commands_executed": 0,
            "effectiveness": None,
            "closure": None,
        }


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--marker", type=UUID, required=True)
    result.add_argument("--expected-head", required=True)
    result.add_argument("--phase", choices=PHASES, required=True)
    result.add_argument("--action", type=UUID)
    result.add_argument("--root-text")
    result.add_argument("--occurred-at")
    result.add_argument("--timezone")
    result.add_argument("--completion-text")
    result.add_argument("--valid-until")
    return result


def main():
    args = parser().parse_args()
    if not re.fullmatch(r"next_[0-9]{4}", args.expected_head):
        raise Stop("EXPLICIT_MIGRATION_HEAD_REQUIRED")
    if args.phase == "completion-source" and not all(
        (args.occurred_at, args.timezone, args.completion_text)
    ):
        raise Stop("EXPLICIT_OBSERVED_COMPLETION_REQUIRED")
    sys.path.insert(0, str(SERVER))
    with setup_lock():
        prepared = Preparation(args)
        try:
            return prepared.run()
        finally:
            prepared.engine.dispose()
            prepared.admin.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception as exc:
        code = str(exc) if isinstance(exc, Stop) else getattr(exc, "code", None)
        # Never render an arbitrary exception (it may contain bound SQL or secrets).
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code):
            code = "SETUP_DEPENDENCY_OR_INPUT_FAILED"
        print(json.dumps({"prepared": False, "code": code, "business_commands_executed": 0}))
        sys.exit(2)
