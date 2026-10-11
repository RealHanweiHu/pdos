"""Trusted rule publication ports, with an explicitly marked local profile.

Real external signature validation belongs to an injected trusted publisher.
Native registered test material can only publish a synthetic rule in the exact
verified temporary scope. No public API or model can configure this issuer.
"""

# ruff: noqa: I001
from pdos_next.service import Context, digest, source_for

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from pdos_next.capa_fact_owner import PublishedRuleMaterial, require, same_original_material
from pdos_next.domain.capa_effectiveness import candidate_commands, candidate_storage
from pdos_next.domain.capa_effectiveness.facts import IssuerRef
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.quality_execution import evidence
from pdos_next.safety import verify_test_target

_DISPATCHER = "_pdos_capa_rule_profile_dispatcher"


@dataclass(frozen=True)
class SyntheticRuleIssuer:
    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    key: str
    version: str
    epoch: int


class RegisteredSyntheticRulePublisher:
    def __init__(self, issuer):
        require(type(issuer) is SyntheticRuleIssuer)
        self.issuer = issuer

    @property
    def epoch(self):
        return self.issuer.epoch

    def _current_issuer(self, s, ctx, pid, project_id):
        issuer = self.issuer
        require(
            getattr(s.get_bind(), "_pdos_capa_rule_issuers", {}).get(issuer.key) is issuer,
            "FACT_ISSUER_REVOKED",
        )
        require(
            (issuer.tenant_id, issuer.product_id, issuer.project_id)
            == (ctx.tenant_id, pid, project_id),
            "FORBIDDEN_SCOPE",
            403,
        )
        return IssuerRef(
            key=issuer.key, version=issuer.version, epoch=issuer.epoch, nature="synthetic"
        )

    def current(self, s, ctx, pid, rule):
        expected = self._current_issuer(s, ctx, pid, rule.scope.project_id)
        require(rule.issuer == expected and rule.nature == "synthetic", "FACT_ISSUER_REVOKED")
        return expected

    def read(self, s, ctx, pid, payload):
        rows = list(
            s.scalars(
                select(CapaVerificationEvidence)
                .where(
                    CapaVerificationEvidence.tenant_id == ctx.tenant_id,
                    CapaVerificationEvidence.product_id == pid,
                    CapaVerificationEvidence.issue_id == payload.issue_id,
                    CapaVerificationEvidence.issue_version_id == payload.origin.id,
                    CapaVerificationEvidence.issue_revision == payload.origin.revision,
                )
                .order_by(CapaVerificationEvidence.created_at, CapaVerificationEvidence.id)
                .limit(1)
            )
        )
        require(bool(rows), "FACT_FIXED_ANCHOR_REQUIRED")
        selected = candidate_storage.read_candidate(
            s, ctx, pid, rows[0].id, semantic_owner=candidate_commands.semantic_owner()
        )
        saved = selected.body.stable_anchor
        issuer = self._current_issuer(s, ctx, pid, saved.origin.scope.project_id)
        require(
            saved.origin.nature == "synthetic" and saved.origin.ref == payload.origin,
            "NATURE_MISMATCH",
            403,
        )
        fields = (
            "origin",
            "previous",
            "external_id",
            "policy_ref",
            "method",
            "criterion",
            "sampling",
            "rule_material",
            "independence_material",
            "valid_from",
            "valid_until",
            "visibility",
        )
        wanted = {
            "schema_version": "pdos-capa-rule-publication-source-v1",
            "nature": "synthetic",
            "scope": saved.origin.scope.model_dump(mode="json"),
            "issue_id": str(payload.issue_id),
            "capa_id": str(payload.capa_id),
            "purpose": saved.origin.purpose,
            "material": payload.model_dump(mode="json", include=set(fields)),
        }
        matched = False
        for ref in payload.sources:
            match = evidence.POSITION.fullmatch(ref.position) if ref.kind == "artifact" else None
            require(match is not None, "FACT_RULE_SOURCE_REQUIRED")
            row = source_for(s, ctx, pid, ref.id, ref.revision)
            evidence.check_source(s, ctx, pid, ref)
            require(row.original_id is None, "FACT_RULE_ORIGINAL_OWNER_REQUIRED")
            try:

                def pairs(items):
                    result = {}
                    for key, value in items:
                        if key in result:
                            raise ValueError("duplicate")
                        result[key] = value
                    return result

                actual = json.loads(
                    row.content.splitlines()[int(match[1]) - 1],
                    object_pairs_hook=pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
                )
            except (ValueError, IndexError):
                continue
            if same_original_material(actual, wanted):
                matched = True
        require(matched, "FACT_RULE_ORIGINAL_MISMATCH", 409)
        require(datetime.now(UTC) < payload.valid_until, "RULE_NOT_CURRENT", 409)
        return PublishedRuleMaterial(
            saved,
            issuer,
            tuple(payload.sources),
            {
                "publisher": "registered_local_synthetic",
                "original_material_sha256": digest(wanted),
                "production_qualified": False,
                "effectiveness": "indeterminate",
            },
            payload.valid_until,
        )


def _profile(profile):
    keys = {"tenant_id", "product_id", "project_id", "issuer_key", "issuer_version"}
    if not isinstance(profile, dict) or set(profile) != keys:
        raise ValueError("Exact marked local rule profile required")
    require(
        all(
            type(profile[k]) is str
            and profile[k].strip() == profile[k]
            and 1 <= len(profile[k]) <= 100
            for k in ("issuer_key", "issuer_version")
        )
    )
    scope = []
    for field in ("tenant_id", "product_id", "project_id"):
        value = profile[field]
        if isinstance(value, UUID):
            scope.append(value)
        elif type(value) is str:
            try:
                scope.append(UUID(value))
            except ValueError:
                raise ValueError("Rule profile scope requires exact server UUIDs") from None
        else:
            raise ValueError("Rule profile scope requires exact server UUIDs")
    return (*scope, profile["issuer_key"], profile["issuer_version"])


def _prepare_issuer(registry, epochs, values, *, reuse):
    tenant_id, product_id, project_id, key, version = values
    previous = registry.get(key)
    if previous is not None:
        if type(previous) is not SyntheticRuleIssuer or (
            previous.tenant_id,
            previous.product_id,
            previous.project_id,
        ) != (tenant_id, product_id, project_id):
            raise ValueError("An issuer key cannot replace another rule scope")
        if reuse and previous.version != version:
            raise ValueError("A profile list cannot rotate an existing rule issuer version")
        if reuse and previous.version == version:
            epoch = epochs.get(key, previous.epoch)
            if type(epoch) is not int or epoch != previous.epoch:
                raise ValueError("The existing rule issuer epoch cannot be verified")
            epochs[key] = epoch
            return previous
    epoch = epochs.get(key, previous.epoch if previous else 0)
    if type(epoch) is not int or epoch < 0 or (previous and epoch < previous.epoch):
        raise ValueError("The existing rule issuer epoch cannot be verified")
    issuer = SyntheticRuleIssuer(tenant_id, product_id, project_id, key, version, epoch + 1)
    registry[issuer.key] = issuer
    epochs[key] = issuer.epoch
    return issuer


def _registry(engine):
    return (
        dict(getattr(engine, "_pdos_capa_rule_issuers", {})),
        dict(getattr(engine, "_pdos_capa_rule_issuer_epochs", {})),
    )


def configure_local_profile(engine, profile):
    """Existing single-profile return type and marked-environment guard remain."""
    values = _profile(profile)
    registry, epochs = _registry(engine)
    issuer = _prepare_issuer(registry, epochs, values, reuse=False)
    verify_test_target(engine)
    engine._pdos_capa_rule_issuers = registry
    engine._pdos_capa_rule_issuer_epochs = epochs
    return RegisteredSyntheticRulePublisher(issuer)


class ScopedRulePublisher:
    """Host-only dispatch; no profile selector or positive gate enters business JSON.

    V1 admits one project per configured tenant/product. Supporting several
    projects in one product requires a future actual-anchor dispatch contract.
    """

    def __init__(self, engine, publishers, configuration_epoch):
        self._engine = engine
        self._publishers = tuple(publishers)
        self._configuration_epoch = configuration_epoch

    @property
    def epoch(self):
        # ActualFactOwner already binds publisher.epoch plus the issuer registry.
        # This stamp also catches unselected issuer rotation and reconfiguration
        # ABA; it is runtime-only and never a Rule issuer epoch or published field.
        registry = getattr(self._engine, "_pdos_capa_rule_issuers", {})
        return digest(
            {
                "configuration_epoch": self._configuration_epoch,
                "current_configuration_epoch": getattr(
                    self._engine, "_pdos_capa_rule_profile_epoch", None
                ),
                "dispatcher_identity": id(getattr(self._engine, _DISPATCHER, None)),
                "issuer_epochs": getattr(self._engine, "_pdos_capa_rule_issuer_epochs", {}),
                "issuers": [
                    [
                        key,
                        id(issuer),
                        str(getattr(issuer, "tenant_id", None)),
                        str(getattr(issuer, "product_id", None)),
                        str(getattr(issuer, "project_id", None)),
                        getattr(issuer, "version", None),
                        getattr(issuer, "epoch", None),
                    ]
                    for key, issuer in sorted(registry.items())
                ],
            }
        )

    def _select(self, s, ctx, pid):
        require(
            s.get_bind() is self._engine
            and getattr(self._engine, _DISPATCHER, None) is self
            and getattr(self._engine, "_pdos_capa_rule_profile_epoch", None)
            == self._configuration_epoch,
            "FACT_RULE_PROFILE_CHANGED",
        )
        require(
            isinstance(ctx, Context)
            and ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and isinstance(pid, UUID),
            "FORBIDDEN_SCOPE",
            403,
        )
        matches = tuple(
            publisher
            for publisher in self._publishers
            if (publisher.issuer.tenant_id, publisher.issuer.product_id) == (ctx.tenant_id, pid)
        )
        require(len(matches) == 1, "FACT_RULE_PROFILE_SCOPE_UNAVAILABLE", 403)
        publisher = matches[0]
        publisher._current_issuer(s, ctx, pid, publisher.issuer.project_id)
        return publisher

    def read(self, s, ctx, pid, payload):
        publisher = self._select(s, ctx, pid)
        stamp = self.epoch
        result = publisher.read(s, ctx, pid, payload)
        # The child has checked the actual anchor Project, bytes and deadline.
        # Recheck actual configuration after all delegated source/owner IO.
        require(self._select(s, ctx, pid) is publisher and self.epoch == stamp, "SOURCE_STALE", 409)
        require(datetime.now(UTC) < result.valid_until, "RULE_NOT_CURRENT", 409)
        return result

    def current(self, s, ctx, pid, rule):
        publisher = self._select(s, ctx, pid)
        stamp = self.epoch
        result = publisher.current(s, ctx, pid, rule)
        require(self._select(s, ctx, pid) is publisher and self.epoch == stamp, "SOURCE_STALE", 409)
        return result


def configure_local_profiles(engine, profiles):
    """Atomically add 1..20 exact host scopes after the existing marker check.

    Identical issuer configurations keep their identity/epoch, including an old
    single profile. Each tenant/product has one project and an independent key;
    unknown scopes and conflicting keys never fall back to another profile.
    """
    if type(profiles) is not list or not profiles:
        raise ValueError("Rule profiles require an explicit list of 1..20 scopes")
    values = tuple(_profile(profile) for profile in profiles)
    if len({v[3] for v in values}) != len(values) or len({v[:2] for v in values}) != len(values):
        raise ValueError("Rule profiles need distinct keys and one project per tenant/product")
    registry, epochs = _registry(engine)
    issuers = tuple(_prepare_issuer(registry, epochs, value, reuse=True) for value in values)
    epoch = getattr(engine, "_pdos_capa_rule_profile_epoch", 0)
    if type(epoch) is not int or epoch < 0:
        raise ValueError("The rule dispatcher epoch cannot be verified")
    dispatcher = ScopedRulePublisher(
        engine, tuple(RegisteredSyntheticRulePublisher(v) for v in issuers), epoch + 1
    )
    verify_test_target(engine)
    engine._pdos_capa_rule_issuers = registry
    engine._pdos_capa_rule_issuer_epochs = epochs
    engine._pdos_capa_rule_profile_epoch = epoch + 1
    setattr(engine, _DISPATCHER, dispatcher)
    return dispatcher
