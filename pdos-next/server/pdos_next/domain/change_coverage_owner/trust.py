"""Finite Engine-bound pins over an existing trusted issuer; no qualifications."""

from uuid import uuid4

from sqlalchemy.engine import Engine

from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.professional_authority import service as professional
from pdos_next.errors import DomainError

from .schemas import OriginalApproval

_TOKEN = object()


def require(ok, code="COVERAGE_OWNER_STALE", status=409):
    if not ok:
        raise DomainError(code, "固定范围覆盖依据未满足，须重新取得可信原件并核对。", status)


class CoverageIssuer:
    __slots__ = ("_token", "_engine", "professional", "approvals", "epoch", "scope", "nonce")

    def __init__(self, token, engine, issuer, approvals, epoch, scope):
        if token is not _TOKEN:
            raise ValueError("Coverage issuer is a trusted startup capability")
        for name, value in zip(
            self.__slots__, (token, engine, issuer, approvals, epoch, scope, uuid4()), strict=True
        ):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("Coverage issuer is immutable")


def _professional(engine, issuer, scope):
    professional._issuer(engine, issuer, scope.tenant_id, scope.product_id, scope.project_id)
    require(
        type(getattr(engine, "_pdos_professional_issuer_epochs", {}).get(issuer.key)) is int
        and engine._pdos_professional_issuer_epochs[issuer.key] == issuer.epoch,
        "TRUSTED_ISSUER_REQUIRED",
        403,
    )


def configure(engine, professional_issuer, *, scope, approvals):
    """Host has externally verified each whole original before creating these pins.

    Does not configure professional issuers or import ProfessionalFact. Not public.
    Reconfiguration always rotates the independent coverage epoch, including ABA.
    """
    require(isinstance(engine, Engine), "COVERAGE_ENGINE_REQUIRED", 503)
    require(type(approvals) is tuple and bool(approvals), status=422)
    issuer = professional_issuer
    require(isinstance(issuer, professional.IssuerContext), "TRUSTED_ISSUER_REQUIRED", 403)
    from pdos_next.schemas.verification.contracts import Scope

    # Existing professional issuer may be product-wide; the coverage capability is not.
    scope = Scope.model_validate(scope)
    _professional(engine, issuer, scope)
    values = tuple(OriginalApproval.model_validate(v) for v in approvals)
    require(len({digest(v.source) for v in values}) == len(values), status=422)
    key = (scope.tenant_id, scope.product_id, scope.project_id)
    registry = dict(getattr(engine, "_pdos_change_coverage_issuers", {}))
    epochs = dict(getattr(engine, "_pdos_change_coverage_epochs", {}))
    epoch = epochs.get(key, 0)
    require(type(epoch) is int and epoch >= 0, "COVERAGE_RUNTIME_INVALID", 503)
    previous = registry.get(key)
    require(previous is None or epoch >= previous.epoch, "COVERAGE_RUNTIME_INVALID", 503)
    result = CoverageIssuer(_TOKEN, engine, issuer, values, epoch + 1, scope)
    registry[key], epochs[key] = result, result.epoch
    engine._pdos_change_coverage_issuers, engine._pdos_change_coverage_epochs = registry, epochs
    return result


def disable(engine, *, scope):
    key = (scope.tenant_id, scope.product_id, scope.project_id)
    registry = dict(getattr(engine, "_pdos_change_coverage_issuers", {}))
    epochs = dict(getattr(engine, "_pdos_change_coverage_epochs", {}))
    value = epochs.get(key, 0)
    require(type(value) is int and value >= 0, "COVERAGE_RUNTIME_INVALID", 503)
    epochs[key] = value + 1
    registry.pop(key, None)
    engine._pdos_change_coverage_issuers, engine._pdos_change_coverage_epochs = registry, epochs


def current(engine, scope, *, supplied=None):
    key = (scope.tenant_id, scope.product_id, scope.project_id)
    issuer = getattr(engine, "_pdos_change_coverage_issuers", {}).get(key)
    require(
        type(issuer) is CoverageIssuer
        and issuer._token is _TOKEN
        and issuer._engine is engine
        and issuer.scope == scope
        and (supplied is None or supplied is issuer)
        and type(getattr(engine, "_pdos_change_coverage_epochs", {}).get(key)) is int
        and engine._pdos_change_coverage_epochs[key] == issuer.epoch,
        "COVERAGE_TRUSTED_ISSUER_REQUIRED",
        403,
    )
    _professional(engine, issuer.professional, scope)
    return issuer


def check(engine, scope, source, material, *, supplied=None):
    issuer = current(engine, scope, supplied=supplied)
    require(material.scope == scope and material.nature == issuer.professional.nature, status=403)
    pin = OriginalApproval(source=source, material_sha256=digest(material))
    require(pin in issuer.approvals, "COVERAGE_ORIGINAL_NOT_APPROVED", 403)
    return issuer


def stamp(issuer):
    return {
        "coverage_epoch": issuer.epoch,
        "coverage_runtime_id": str(issuer.nonce),
        "issuer_key": issuer.professional.key,
        "issuer_version": issuer.professional.version,
        "issuer_epoch": issuer.professional.epoch,
        "nature": issuer.professional.nature,
        "pins_sha256": digest([v.model_dump(mode="json") for v in issuer.approvals]),
    }
