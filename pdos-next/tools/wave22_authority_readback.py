"""Root-only marked, rollback-only readback of actual shared synthetic publication.

No import/configuration/connection at module import; no login tokens are emitted.
Original authority writer and actual domain assessments remain the sole truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import wave22_shared_authority as authority

ROOT = authority.ROOT
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave22-20261003"
PROFESSIONAL = "professional.authority.import"
POLICY = "quality.policy.import"
FAMILIES = {PROFESSIONAL: "professional_authority_fact", POLICY: "quality_policy_fact"}
EVENTS = {PROFESSIONAL: "professional.authority_imported", POLICY: "quality.policy_imported"}


def checkpoint_material(owner):
    data = owner.data
    if data is None or data.get("state") != "synthetic_facts_saved_root_reload_required":
        raise authority.Blocked("SAVED_AUTHORITY_IMPORTS_REQUIRED")
    owner.validate_saved_plan()
    labels = {entry["label"] for entry in data["plan"]["facts"]} | {
        "quality-policy",
        "authority-source",
    }
    if set(data.get("receipts", {})) != labels:
        raise authority.Blocked("COMPLETE_IMPORT_RECEIPTS_REQUIRED")
    for label, receipt in data["receipts"].items():
        operation = (
            "evidence.artifact.register"
            if label == "authority-source"
            else POLICY
            if label == "quality-policy"
            else PROFESSIONAL
        )
        family = "artifact" if label == "authority-source" else FAMILIES[operation]
        if (
            receipt.get("operation") != operation
            or receipt.get("subject_type") != family
            or receipt.get("writer_id") != str(owner.basis.actor("maker"))
            or receipt.get("requester_id") != str(owner.basis.actor("maker"))
            or receipt.get("result", {}).get("id") != receipt.get("subject_id")
            or type(receipt.get("result", {}).get("revision")) is not int
            or receipt["result"]["revision"] != authority.positive(receipt["subject_revision"])
        ):
            raise authority.Blocked("SAVED_RECEIPT_MISMATCH")
        UUID(receipt["id"])
        UUID(receipt["subject_id"])
    ids = [row["id"] for row in data["receipts"].values()]
    if len(set(ids)) != len(ids):
        raise authority.Blocked("DUPLICATE_SAVED_RECEIPT")
    return deepcopy(data["receipts"])


def assert_group(receipt, saved, audits, events, keys, *, basis, label):
    """Check real ORM fields without treating a saved DTO as a stored atom."""
    from pdos_next.service import receipt_view

    maker = basis.actor("maker")
    operation = saved["operation"]
    key = (
        f"wave22-{basis.case_id}-authority-source"
        if label == "authority-source"
        else f"wave22-{basis.case_id}-{label}"
    )
    command = uuid5(
        basis.case_id,
        "wave22:authority-source" if label == "authority-source" else "wave22:" + label,
    )
    if (
        receipt is None
        or authority.canonical(receipt_view(receipt)) != authority.canonical(saved)
        or (
            receipt.tenant_id,
            receipt.product_id,
            receipt.actor_id,
            receipt.requester_id,
            receipt.visibility,
            receipt.run_id,
            receipt.command_id,
        )
        != (basis.tenant_id, basis.product_id, maker, maker, "product", None, command)
        or type(receipt.subject_revision) is not int
        or receipt.subject_revision < 1
        or len(audits) != 1
        or len(events) != 1
        or len(keys) != 1
    ):
        raise authority.Blocked("IMPORT_COMMON_GROUP_MISMATCH")
    audit, outbox, request = audits[0], events[0], keys[0]
    event_type = "artifact.registered" if label == "authority-source" else EVENTS[operation]
    if (
        (audit.tenant_id, audit.receipt_id, audit.actor_id, audit.operation)
        != (basis.tenant_id, receipt.id, maker, operation)
        or (
            outbox.tenant_id,
            outbox.receipt_id,
            outbox.type,
            outbox.subject_id,
            outbox.subject_revision,
            outbox.actor_id,
            outbox.correlation_id,
        )
        != (
            basis.tenant_id,
            receipt.id,
            event_type,
            receipt.subject_id,
            receipt.subject_revision,
            maker,
            command,
        )
        or type(outbox.subject_revision) is not int
        or type(outbox.schema_version) is not int
        or outbox.schema_version != 1
        or (request.tenant_id, request.actor_id, request.key, request.receipt_id, request.digest)
        != (basis.tenant_id, maker, key, receipt.id, receipt.request_digest)
    ):
        raise authority.Blocked("IMPORT_COMMON_GROUP_MISMATCH")
    return {
        "label": label,
        "receipt_id": str(receipt.id),
        "subject_id": str(receipt.subject_id),
        "revision": receipt.subject_revision,
        "operation": operation,
        "audit_id": str(audit.id),
        "outbox_id": str(outbox.id),
        "request_key_id": str(request.id),
        "outbox_delivery_state_not_a_business_binding": True,
    }


def expected_assessments(basis):
    expected = []
    for _, actor_role, role, operations in authority.GROUPS:
        expected.extend((actor_role, op, role, True) for op in operations)
    non_review = {op for _, _, _, ops in authority.GROUPS for op in ops} - {
        "quality.capa.verification.review"
    }
    expected.extend(("independent_reviewer", op, None, False) for op in sorted(non_review))
    if len({(role, op) for role, op, _, _ in expected}) != len(expected):
        raise authority.Blocked("AMBIGUOUS_EXPECTED_AUTHORITY")
    return tuple(expected)


def assert_assessment(value, basis, actor_role, operation, role, allowed):
    if (
        value.get("scope")
        != {
            "tenant_id": str(basis.tenant_id),
            "product_id": str(basis.product_id),
            "project_id": str(basis.project_id),
        }
        or value.get("subject_id") != str(basis.actor(actor_role))
        or value.get("operation") != operation
        or value.get("purpose") != basis.purpose
        or value.get("synthetic") is not True
        or type(value.get("authorized")) is not bool
    ):
        raise authority.Blocked("ACTUAL_ASSESSMENT_SCOPE_MISMATCH")
    if allowed:
        if (
            value["authorized"] is not True
            or value.get("qualified") is not True
            or value.get("roles") != [role]
            or value.get("reason_codes") != []
            or not value.get("fact_refs")
            or not value.get("required_source_read_set")
        ):
            raise authority.Blocked("EXPECTED_PROFESSIONAL_OPERATION_UNAVAILABLE")
    elif (
        value["authorized"] is not False
        or value.get("qualified") is not None
        or value.get("roles") != []
        or value.get("reason_codes")
        != ["PROFESSIONAL_DUTY_REQUIRED", "PROFESSIONAL_QUALIFICATION_REQUIRED"]
        or not value.get("fact_refs")
        or not value.get("required_source_read_set")
    ):
        raise authority.Blocked("REVIEWER_UNEXPECTED_OTHER_ROLE_AUTHORITY")
    return {
        "actor_role": actor_role,
        "operation": operation,
        "authorized": value["authorized"],
        "qualified": value["qualified"],
        "roles": value["roles"],
        "reason_codes": value["reason_codes"],
        "facts_revision": value["facts_revision"],
    }


def assert_assessment_refs(value, owner, actor_role):
    expected = []
    for entry in owner.data["plan"]["facts"]:
        payload = entry["payload"]
        if payload["subject_id"] != str(owner.basis.actor(actor_role)):
            continue
        saved = owner.data["receipts"][entry["label"]]
        expected.append(
            {
                "id": saved["subject_id"],
                "revision": saved["subject_revision"],
                "epoch": 1,
                "kind": payload["kind"],
                "role": payload["role"],
                "nature": "synthetic",
                "issuer_key": owner.data["plan"]["profiles"]["professional"]["key"],
                "issuer_version": "v1",
            }
        )
    actual = value.get("fact_refs")
    source = owner.data["receipts"]["authority-source"]
    reads = [{"artifact_id": source["subject_id"], "expected_revision": source["subject_revision"]}]
    if (
        not isinstance(actual, list)
        or authority.canonical(sorted(actual, key=lambda r: r["id"]))
        != authority.canonical(sorted(expected, key=lambda r: r["id"]))
        or authority.canonical(value.get("required_source_read_set")) != authority.canonical(reads)
    ):
        raise authority.Blocked("COMPLETE_ACTOR_AUTHORITY_SET_MISMATCH")


def normalized_publication_payload(payload, kind):
    """Use the actual importer DTO, including UTC serialization and previous defaults."""
    from pdos_next.domain.professional_authority.schemas import FactInput
    from pdos_next.domain.quality_execution.schemas import PolicyInput

    if kind == "professional":
        dto = FactInput
    elif kind == "policy":
        dto = PolicyInput
    else:
        raise authority.Blocked("EXACT_FACT_KIND_REQUIRED")
    return dto.model_validate(payload).model_dump(mode="json")


def assert_publication_rows(row, pointer, payload, *, basis, issuer, kind):
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.quality_execution import policy

    payload = normalized_publication_payload(payload, kind)
    if row is None or pointer is None:
        raise authority.Blocked("CURRENT_IMPORTED_FACT_REQUIRED")
    names = (
        "tenant_id",
        "product_id",
        "project_id",
        "owner_id",
        "visibility",
        "nature",
        "issuer_key",
        "issuer_version",
        "external_id",
        "revision",
        "previous_id",
        "previous_revision",
        "series_id",
    )
    wanted = (
        basis.tenant_id,
        basis.product_id,
        basis.project_id,
        basis.actor("maker"),
        "product",
        "synthetic",
        issuer.key,
        issuer.version,
        payload["external_id"],
        1,
        None,
        None,
        row.id,
    )
    if tuple(getattr(row, key) for key in names) != wanted:
        raise authority.Blocked("IMPORTED_FACT_SCOPE_MISMATCH")
    if (
        (
            pointer.tenant_id,
            pointer.product_id,
            pointer.project_id,
            pointer.fact_id,
            pointer.fact_revision,
            pointer.epoch,
            pointer.series_id,
            pointer.issuer_key,
            pointer.external_id,
        )
        != (
            basis.tenant_id,
            basis.product_id,
            basis.project_id,
            row.id,
            1,
            1,
            row.id,
            issuer.key,
            payload["external_id"],
        )
        or type(pointer.fact_revision) is not int
        or type(pointer.epoch) is not int
        or type(row.revision) is not int
    ):
        raise authority.Blocked("IMPORTED_CURRENT_POINTER_MISMATCH")
    if kind == "professional":
        if (
            (row.subject_id, row.kind, row.role, row.operations, row.purposes, row.state)
            != (
                UUID(payload["subject_id"]),
                payload["kind"],
                payload["role"],
                payload["operations"],
                payload["purposes"],
                payload["state"],
            )
            or (pointer.subject_id, pointer.kind) != (row.subject_id, row.kind)
            or authority.canonical(row.sources) != authority.canonical(payload["sources"])
            or authority.canonical(row.source_basis["approval"])
            != authority.canonical(payload["approval"])
            or row.fact_sha256 != professional.digest(professional._material(row))
            or row.source_basis.get("import_digest")
            != professional.digest([issuer.key, issuer.version, issuer.nature, payload])
        ):
            raise authority.Blocked("IMPORTED_PROFESSIONAL_MATERIAL_MISMATCH")
    elif kind == "policy":
        if (
            authority.canonical(row.data) != authority.canonical(payload)
            or (row.purpose, row.risk, row.independent_verification, row.status, row.issuer_epoch)
            != (basis.purpose, "high", True, "active", issuer.epoch)
            or row.independent_verification is not True
            or pointer.purpose != basis.purpose
            or row.fact_sha256 != policy.digest(policy._material(row))
        ):
            raise authority.Blocked("IMPORTED_POLICY_MATERIAL_MISMATCH")
    else:
        raise authority.Blocked("EXACT_FACT_KIND_REQUIRED")
    if (
        authority.aware(row.valid_from) != authority.aware(payload["valid_from"])
        or authority.aware(row.valid_until) != authority.aware(payload["valid_until"])
        or row.reason != payload["reason"]
    ):
        raise authority.Blocked("IMPORTED_FACT_MATERIAL_MISMATCH")


class Readback:
    def __init__(self, marker):
        sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
        self.owner = authority.AuthorityTool(marker)
        self.saved = checkpoint_material(self.owner)
        self.basis = self.owner.basis
        self.engine = self.owner.engine
        self.counts = {"select": 0, "set": 0, "business_dml": 0, "flush": 0, "commit": 0}

    def driver_guard(self, connection, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb not in {"SELECT", "SET"}:
            self.counts["business_dml"] += 1
            raise authority.Blocked("READBACK_DML_REFUSED")
        self.counts[verb.lower()] += 1

    def no_flush(self, *args):
        self.counts["flush"] += 1
        raise authority.Blocked("READBACK_FLUSH_REFUSED")

    def no_commit(self, *args):
        self.counts["commit"] += 1
        raise authority.Blocked("READBACK_COMMIT_REFUSED")

    def caller_gate(self, s):
        from pdos_next.domain.projects.models import Project
        from pdos_next.models import Grant, Principal, Product
        from pdos_next.service import require_access
        from sqlalchemy import select

        b = self.basis
        product = s.scalar(
            select(Product)
            .where(Product.tenant_id == b.tenant_id, Product.id == b.product_id)
            .execution_options(populate_existing=True)
        )
        project = s.scalar(
            select(Project)
            .where(
                Project.tenant_id == b.tenant_id,
                Project.product_id == b.product_id,
                Project.id == b.project_id,
            )
            .execution_options(populate_existing=True)
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
            raise authority.Blocked("ACTUAL_SHARED_SCOPE_REQUIRED")
        stamp = []
        deadlines = [b.expires_at]
        for role in authority.ROLES:
            actor = s.scalar(
                select(Principal)
                .where(Principal.tenant_id == b.tenant_id, Principal.id == b.actor(role))
                .execution_options(populate_existing=True)
            )
            grant = s.scalar(
                select(Grant)
                .where(
                    Grant.tenant_id == b.tenant_id,
                    Grant.product_id == b.product_id,
                    Grant.principal_id == b.actor(role),
                )
                .execution_options(populate_existing=True)
            )
            require_access(s, self.owner.ctx(role), b.product_id, write=True, lock=False)
            if (
                actor is None
                or grant is None
                or actor.active is not True
                or actor.kind != "human"
                or grant.can_write is not True
            ):
                raise authority.Blocked("ACTUAL_CURRENT_HUMAN_GRANT_REQUIRED")
            stamp.append(
                [
                    str(actor.id),
                    actor.access_epoch,
                    actor.active,
                    actor.kind,
                    str(grant.id),
                    grant.access_epoch,
                    grant.can_write,
                    grant.expires_at.isoformat(),
                ]
            )
            deadlines.append(authority.aware(grant.expires_at))
        if min(deadlines) <= datetime.now(UTC):
            raise authority.Blocked("ACTUAL_CURRENT_HUMAN_GRANT_REQUIRED")
        return stamp, min(deadlines)

    def read_group(self, s, label, saved):
        from pdos_next.models import Audit, Outbox, Receipt, RequestKey
        from sqlalchemy import select

        b = self.basis
        receipt = s.scalar(
            select(Receipt)
            .where(
                Receipt.tenant_id == b.tenant_id,
                Receipt.product_id == b.product_id,
                Receipt.id == UUID(saved["id"]),
            )
            .execution_options(populate_existing=True)
        )
        request_key = (
            f"wave22-{b.case_id}-authority-source"
            if label == "authority-source"
            else f"wave22-{b.case_id}-{label}"
        )
        audits = list(
            s.scalars(
                select(Audit)
                .where(Audit.tenant_id == b.tenant_id, Audit.receipt_id == UUID(saved["id"]))
                .limit(2)
            )
        )
        events = list(
            s.scalars(
                select(Outbox)
                .where(Outbox.tenant_id == b.tenant_id, Outbox.receipt_id == UUID(saved["id"]))
                .limit(2)
            )
        )
        keys = list(
            s.scalars(
                select(RequestKey)
                .where(
                    RequestKey.tenant_id == b.tenant_id,
                    RequestKey.actor_id == b.actor("maker"),
                    RequestKey.key == request_key,
                )
                .limit(2)
            )
        )
        group = assert_group(receipt, saved, audits, events, keys, basis=b, label=label)
        unique = list(
            s.scalars(
                select(Receipt.id)
                .where(
                    Receipt.tenant_id == b.tenant_id,
                    Receipt.product_id == b.product_id,
                    Receipt.operation == saved["operation"],
                    Receipt.subject_type == saved["subject_type"],
                    Receipt.subject_id == UUID(saved["subject_id"]),
                    Receipt.subject_revision == saved["subject_revision"],
                )
                .limit(2)
            )
        )
        if unique != [UUID(saved["id"])]:
            raise authority.Blocked("DUPLICATE_IMPORT_RECEIPT")
        return receipt, group

    def rows(self, s, prof, quality):
        from pdos_next.domain.professional_authority import service as professional
        from pdos_next.domain.professional_authority.models import (
            ProfessionalCurrent,
            ProfessionalFact,
        )
        from pdos_next.domain.quality_execution import policy
        from pdos_next.domain.quality_execution.models import (
            QualityPolicyCurrent,
            QualityPolicyFact,
        )
        from pdos_next.service import digest
        from sqlalchemy import select

        b = self.basis
        source = self.saved["authority-source"]
        inputs, policy_input = authority.bound_payloads(
            self.owner.data["plan"], source["subject_id"], source["subject_revision"]
        )
        groups, ids = [], []
        for entry in [*inputs, {"label": "quality-policy", "payload": policy_input}]:
            label, payload = entry["label"], entry["payload"]
            receipt, group = self.read_group(s, label, self.saved[label])
            if label == "quality-policy":
                cls, current, issuer, kind = (
                    QualityPolicyFact,
                    QualityPolicyCurrent,
                    quality,
                    "policy",
                )
            else:
                cls, current, issuer, kind = (
                    ProfessionalFact,
                    ProfessionalCurrent,
                    prof,
                    "professional",
                )
            # Recompute both row and common-group material from the same actual DTO.
            payload = normalized_publication_payload(payload, kind)
            row = s.scalar(
                select(cls)
                .where(
                    cls.tenant_id == b.tenant_id,
                    cls.product_id == b.product_id,
                    cls.project_id == b.project_id,
                    cls.id == receipt.subject_id,
                )
                .execution_options(populate_existing=True)
            )
            pointers = list(
                s.scalars(
                    select(current)
                    .where(
                        current.tenant_id == b.tenant_id,
                        current.product_id == b.product_id,
                        current.project_id == b.project_id,
                        current.issuer_key == issuer.key,
                        current.external_id == payload["external_id"],
                    )
                    .execution_options(populate_existing=True)
                    .limit(2)
                )
            )
            if len(pointers) != 1:
                raise authority.Blocked("EXACT_CURRENT_POINTER_REQUIRED")
            assert_publication_rows(row, pointers[0], payload, basis=b, issuer=issuer, kind=kind)
            expected_reads = [
                {
                    "artifact_id": source["subject_id"],
                    "expected_revision": source["subject_revision"],
                }
            ]
            if authority.canonical(row.required_source_read_set) != authority.canonical(
                expected_reads
            ):
                raise authority.Blocked("IMPORTED_FACT_READSET_MISMATCH")
            if kind == "professional":
                actual_reads, private, evidence = professional._evidence(
                    s, self.owner.ctx(), b.product_id, row.sources
                )
                fingerprint = digest(
                    {
                        "operation": PROFESSIONAL,
                        "product": b.product_id,
                        "actor": b.actor("maker"),
                        "issuer": [prof.key, prof.version, prof.nature],
                        "payload": payload,
                    }
                )
                if (
                    private
                    or actual_reads != row.required_source_read_set
                    or authority.canonical(evidence)
                    != authority.canonical(row.source_basis["evidence"])
                ):
                    raise authority.Blocked("CURRENT_PROFESSIONAL_SOURCE_CHANGED")
            else:
                fingerprint = digest(
                    {
                        "operation": POLICY,
                        "tenant": b.tenant_id,
                        "product": b.product_id,
                        "actor": b.actor("maker"),
                        "issuer": [quality.key, quality.version, quality.epoch],
                        "payload": payload,
                    }
                )
                # Actual original publication and current sources; never trusted_import.
                from pdos_next.domain.quality_execution.schemas import PolicyInput

                policy._publication(s, self.owner.ctx(), PolicyInput.model_validate(payload))
            if receipt.request_digest != fingerprint or receipt.intent_digest != fingerprint:
                raise authority.Blocked("IMPORTED_COMMON_INTENT_MISMATCH")
            groups.append(group)
            ids.append((str(row.id), row.fact_sha256, pointers[0].epoch))
        self.read_group(s, "authority-source", source)
        return groups, ids

    def source(self, s):
        from pdos_next.domain.quality_execution.evidence import source_basis
        from pdos_next.service import digest, source_for

        b = self.basis
        saved = self.saved["authority-source"]
        content = "\n".join(self.owner.data["plan"]["lines"])
        result = []
        foundation_basis = []
        for role in authority.ROLES:
            ctx = self.owner.ctx(role)
            row = source_for(
                s, ctx, b.product_id, UUID(saved["subject_id"]), saved["subject_revision"]
            )
            if (
                row.tenant_id,
                row.product_id,
                row.owner_id,
                row.visibility,
                row.original_id,
                row.status,
                row.content,
                row.content_hash,
            ) != (
                b.tenant_id,
                b.product_id,
                b.actor("maker"),
                "product",
                None,
                "active",
                content,
                digest(content),
            ):
                raise authority.Blocked("ACTUAL_SHARED_PUBLICATION_SOURCE_REQUIRED")
            basis, private = source_basis(
                s,
                ctx,
                b.product_id,
                [{"artifact_id": str(row.id), "expected_revision": row.revision}],
            )
            if private:
                raise authority.Blocked("ACTUAL_SHARED_PUBLICATION_SOURCE_REQUIRED")
            result.append(basis)
            original = source_for(s, ctx, b.product_id, b.source_id, b.source_revision)
            if (
                original.tenant_id != b.tenant_id
                or original.product_id != b.product_id
                or original.owner_id != b.actor("maker")
                or original.visibility != "product"
                or original.original_id is not None
                or original.status != "active"
                or original.content_hash != b.source_content_hash
                or digest(original.content) != b.source_content_hash
                or authority.content_sha(original.content) != b.source_text_sha256
            ):
                raise authority.Blocked("ACTUAL_FOUNDATION_SOURCE_CHANGED")
            original_basis, private = source_basis(
                s,
                ctx,
                b.product_id,
                [{"artifact_id": str(original.id), "expected_revision": original.revision}],
            )
            if private:
                raise authority.Blocked("ACTUAL_FOUNDATION_SOURCE_CHANGED")
            foundation_basis.append(original_basis)
        return {
            "id": saved["subject_id"],
            "revision": saved["subject_revision"],
            "whole_content_sha256": digest(content),
            "raw_utf8_sha256": authority.content_sha(content),
            "lines": len(content.splitlines()),
            "current_three_actor_source_basis": result,
            "foundation_source": {
                "id": str(b.source_id),
                "revision": b.source_revision,
                "stored_content_hash": b.source_content_hash,
                "raw_utf8_sha256": b.source_text_sha256,
                "current_three_actor_source_basis": foundation_basis,
            },
        }

    def assessments(self, s):
        from pdos_next.domain.professional_authority.service import assess
        from pdos_next.domain.quality_execution.policy import assess as policy_assess

        output = []
        deadlines = []
        revisions = []
        for actor_role, op, role, allowed in expected_assessments(self.basis):
            ctx = self.owner.ctx(actor_role)
            value = assess(
                s,
                ctx,
                self.basis.product_id,
                self.basis.project_id,
                op,
                self.basis.purpose,
                datetime.now(UTC),
                write=False,
            )
            assert_assessment_refs(value, self.owner, actor_role)
            output.append(assert_assessment(value, self.basis, actor_role, op, role, allowed))
            revisions.append(value["facts_revision"])
            if value["valid_until"]:
                deadlines.append(authority.aware(value["valid_until"]))
        policies = []
        for role in authority.ROLES:
            value = policy_assess(
                s,
                self.owner.ctx(role),
                self.basis.product_id,
                self.basis.project_id,
                self.basis.purpose,
            )
            if (
                value["id"] != self.saved["quality-policy"]["subject_id"]
                or value["risk"] != "high"
                or value["independent_verification"] is not True
                or value["nature"] != "synthetic"
                or value["private"] is not False
            ):
                raise authority.Blocked("ACTUAL_SHARED_POLICY_UNAVAILABLE")
            policies.append({"actor_role": role, **value})
            revisions.append(value["facts_revision"])
            deadlines.append(authority.aware(value["valid_until"]))
        return output, policies, revisions, min(deadlines)

    def runtime_stamp(self):
        result = []
        for registry_name, epoch_name in (
            ("_pdos_professional_issuers", "_pdos_professional_issuer_epochs"),
            ("_pdos_quality_policy_issuers", "_pdos_quality_policy_epochs"),
        ):
            registry = getattr(self.engine, registry_name, None)
            epochs = getattr(self.engine, epoch_name, None)
            if type(registry) is not dict or type(epochs) is not dict or len(registry) != 2:
                raise authority.Blocked("EXACT_TWO_SCOPE_RUNTIME_REQUIRED")
            rows = []
            for key, issuer in sorted(registry.items()):
                if (
                    type(epochs.get(key)) is not int
                    or type(issuer.epoch) is not int
                    or epochs[key] != issuer.epoch
                    or issuer.epoch < 1
                ):
                    raise authority.Blocked("CURRENT_ISSUER_EPOCH_MISMATCH")
                rows.append(
                    (
                        key,
                        id(issuer),
                        issuer.key,
                        issuer.version,
                        issuer.epoch,
                        issuer.tenant_id,
                        issuer.product_id,
                        issuer.project_id,
                    )
                )
            result.append(tuple(rows))
        if getattr(self.engine, "_pdos_professional_synthetic", None) is not True:
            raise authority.Blocked("EXACT_SYNTHETIC_RUNTIME_REQUIRED")
        return tuple(result)

    def run(self):
        from pdos_next.domain.professional_authority.service import (
            configure_local_synthetic_profiles,
        )
        from pdos_next.quality_bootstrap import configure_local_profiles
        from sqlalchemy import event, text
        from sqlalchemy.orm import Session

        self.owner.target()
        profiles = {
            family: authority.private_read(ROOT / f".local/wave22-{family}-synthetic-profiles.json")
            for family in ("professional", "quality")
        }
        if authority.canonical(profiles) != authority.canonical(self.owner.data["profiles"]):
            raise authority.Blocked("INSTALLED_PROFILE_MATERIAL_REQUIRED")
        prof = configure_local_synthetic_profiles(
            self.engine, profiles["professional"], enabled=True
        )[-1]
        quality = configure_local_profiles(self.engine, profiles["quality"])[-1]
        runtime = self.runtime_stamp()
        event.listen(self.engine, "before_cursor_execute", self.driver_guard)
        try:
            with Session(self.engine, autoflush=False) as s:
                event.listen(s, "before_flush", self.no_flush)
                event.listen(s, "before_commit", self.no_commit)
                transaction = s.begin()
                try:
                    s.execute(
                        text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
                        {"tenant": str(self.basis.tenant_id)},
                    )
                    initial, deadline = self.caller_gate(s)
                    groups, ids = self.rows(s, prof, quality)
                    source = self.source(s)
                    results, policies, revisions, assessment_deadline = self.assessments(s)
                    # Independent final IO: Current/source/assessments, then fresh caller scalars.
                    _, final_ids = self.rows(s, prof, quality)
                    final_source = self.source(s)
                    _, _, final_revisions, final_deadline = self.assessments(s)
                    final, caller_deadline = self.caller_gate(s)
                    at = datetime.now(UTC)
                    if (
                        initial != final
                        or ids != final_ids
                        or source != final_source
                        or revisions != final_revisions
                        or runtime != self.runtime_stamp()
                        or getattr(self.engine, "_pdos_professional_issuers", {}).get(prof.key)
                        is not prof
                        or getattr(self.engine, "_pdos_quality_policy_issuers", {}).get(quality.key)
                        is not quality
                        or min(deadline, assessment_deadline, final_deadline, caller_deadline) <= at
                        or s.new
                        or s.dirty
                        or s.deleted
                        or not transaction.is_active
                    ):
                        raise authority.Blocked("READBACK_FINAL_CURRENT_CHANGED")
                    result = {
                        "status": "PASS",
                        "scope": {
                            "tenant_id": str(self.basis.tenant_id),
                            "product_id": str(self.basis.product_id),
                            "project_id": str(self.basis.project_id),
                        },
                        "synthetic_only": True,
                        "professional_facts": 12,
                        "policy_facts": 1,
                        "common_groups": groups,
                        "current_publication_source": source,
                        "assessments": results,
                        "policy_by_actor": policies,
                        "checked_at": at.isoformat(),
                        "valid_until": min(
                            deadline, assessment_deadline, final_deadline, caller_deadline
                        ).isoformat(),
                        "business_commands": 0,
                        "model_calls": 0,
                        "independent_review_decisions": 0,
                        "production_qualification": False,
                        "independence_not_attested": True,
                        "old_table_capa_private_core_preservation_not_retested": True,
                    }
                finally:
                    transaction.rollback()
                    if s.get_transaction() is not None:
                        raise authority.Blocked("READBACK_ROLLBACK_REQUIRED")
            result["rollback_completed"] = True
            result["driver_counts"] = deepcopy(self.counts)
            return result
        finally:
            event.remove(self.engine, "before_cursor_execute", self.driver_guard)
            self.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=("run",))
    parser.add_argument("--marker", required=True)
    parser.add_argument("--tag", default="v1")
    parser.add_argument("--reuse-evidence", action="append", default=[])
    args = parser.parse_args()
    if not args.tag.startswith("v") or not args.tag[1:].isdigit():
        raise authority.Blocked("EXPLICIT_REPORT_TAG_REQUIRED")
    output = REPORT / f"authority-actual-readback-{args.tag}.json"
    if output.exists():
        raise authority.Blocked("ORIGINAL_EVIDENCE_NOT_OVERWRITTEN")
    REPORT.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "FAIL",
        "started_at": datetime.now(UTC).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
    }
    try:
        reused = []
        for supplied in args.reuse_evidence:
            path = Path(supplied).resolve()
            if (
                not path.is_relative_to(ROOT.parent / "docs/reports/evidence")
                or path.suffix != ".json"
            ):
                raise authority.Blocked("PUBLIC_EVIDENCE_PATH_REQUIRED")
            data = authority.strict_json(path.read_text())
            if data.get("status") != "PASS":
                raise authority.Blocked("REUSED_EVIDENCE_NOT_PASS")
            reused.append(
                {
                    "path": str(path.relative_to(ROOT.parent)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "scope": "historical evidence only; no rerun/current qualification claim",
                }
            )
        result.update(Readback(args.marker).run())
        result["reused_evidence"] = reused
    except Exception as error:
        result["code"] = getattr(error, "code", type(error).__name__)
    result["finished_at"] = datetime.now(UTC).isoformat()
    # Exclusive creation preserves original failure/output evidence. No private content is printed.
    with output.open("x") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "report": str(output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
