"""Fixed dependency identities in the signed read result, never an ACL cache."""

from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationError

from pdos_next.schema_base import StrictModel
from pdos_next.service import digest


class Root(StrictModel):
    type: Literal["artifact", "snapshot"]
    id: UUID
    category_id: UUID
    version: int = Field(gt=0, strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_id: UUID | None = None


class Dependency(StrictModel):
    type: Literal["artifact", "original", "claim", "snapshot"]
    id: UUID
    version: int = Field(gt=0, strict=True)
    root: Root


class Basis(StrictModel):
    version: int = Field(ge=1, le=1, strict=True)
    references_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: list[Dependency]


def references(refs):
    return [ref for ref in refs if ref["type"] not in {"human", "parameter"}]


def fixed(item, refs):
    """Reject incomplete/foreign footprints before using any of their identities."""
    raw = item.get("dependency_basis")
    if raw is None:
        return None
    try:
        basis = Basis.model_validate(raw)
        expected = [(ref["type"], UUID(ref["id"]), ref["version"]) for ref in references(refs)]
        if basis.references_digest != digest(refs) or [
            (dep.type, dep.id, dep.version) for dep in basis.dependencies
        ] != expected:
            return False
        for dep in basis.dependencies:
            if dep.root.type == "snapshot" and (
                dep.root.version != 1 or dep.root.original_id is not None
            ):
                return False
            if dep.type != "claim" and (dep.root.type != (
                "artifact" if dep.type == "original" else dep.type
            ) or dep.root.id != dep.id or dep.root.version != dep.version):
                return False
            if str(dep.root.category_id) != item["category_id"]:
                return False
        return basis
    except (ValidationError, ValueError, KeyError, TypeError):
        return False


def capture(refs, rows, claims, snapshots):
    dependencies = []
    for ref in references(refs):
        typ, identity = ref["type"], UUID(ref["id"])
        claim = claims.get(identity) if typ == "claim" else None
        kind = claim.source_kind if claim else "artifact" if typ == "original" else typ
        root_id = (
            claim.artifact_id if kind == "artifact" else claim.snapshot_id
        ) if claim else identity
        if kind == "artifact":
            row = rows[(kind, root_id)]
            root = Root(type=kind, id=root_id, category_id=row["category_id"],
                        version=row["source_revision"], content_hash=row["content_hash"],
                        original_id=row["original_id"])
        else:
            row = snapshots[root_id]
            root = Root(type=kind, id=root_id, category_id=row.category_id,
                        version=1, content_hash=row.content_hash)
        dependencies.append(Dependency(type=typ, id=identity, version=ref["version"], root=root))
    return Basis(version=1, references_digest=digest(refs), dependencies=dependencies)


def recheck(basis, rows, claims, snapshots, safe):
    """Every old root must still be readable; newer roots never replace this check."""
    changed = False
    for dep in basis.dependencies:
        root = dep.root
        if root.type == "artifact":
            row = rows.get((root.type, root.id))
            if (row is None or row["category_id"] != root.category_id
                or row["original_id"] is not None and row["original_id"] not in safe
                or root.original_id is not None and root.original_id not in safe):
                return False, changed
            changed |= (row["source_revision"], row["content_hash"], row["original_id"]) != (
                root.version, root.content_hash, root.original_id
            )
        else:
            row = snapshots.get(root.id)
            if row is None or row.category_id != root.category_id:
                return False, changed
            changed |= row.content_hash != root.content_hash
        if dep.type == "claim":
            row = claims.get(dep.id)
            if (row is None or row.category_id != root.category_id
                or row.revision != dep.version or row.source_kind != root.type
                or (row.artifact_id if root.type == "artifact" else row.snapshot_id) != root.id
                or row.source_revision != root.version):
                return False, changed
    return True, changed
