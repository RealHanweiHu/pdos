# Wave17 staged fact registry/raw storage contract

This is an unregistered staged reader. No public action, SQL migration, RLS,
issuer, professional qualification or effectiveness authorization is installed.
Only the three new files in this delivery are owned. The earlier models, codec,
facts v2, anchor, lineage and Root's actual atom reader remain unchanged.

## Frozen interface

```python
read_stored_fact(
    s: sqlalchemy.orm.Session,
    ctx: pdos_next.service.Context,
    product_id: UUID,
    kind: Literal["rule", "observation", "review"],
    ref: facts.FactRef,
    *,
    candidate_owner: CandidateOwner | None = None,
) -> StoredFactRead
```

The named real human Context is the actual current reader. Scope is checked
through the real Product/Principal/Grant, exact Project and exact fact row, never
a client scope. Product-sharing of a Fact cannot bypass a private Project:
the exact tenant/product/project must exist, retain actual `active` status and
`private`/`product` visibility, and a private Project is readable only by its
actual current owner. This uses a bounded direct SELECT, not `_project`'s deep
source chain or a new lock. The caller's active root and all active SAVEPOINT ancestors, bind and
Context are captured. The same objects must still be active at the end.

The implementation deliberately depends on frozen
`fact_atom_storage.read_fact_atom` **v5** and its `_uow`, `_same_uow`, `_acl`
helpers, as approved by Root. Formal migration will change staged import paths
together. The atom reader retains its exact Receipt/Audit/Outbox/RequestKey and
saved proof checks. It does not attest the actual same-UOW false-to-true proof
consumption from a saved `consumed=True` boolean.

`StoredFactRead` returns the assembled exact immutable `fact`, actual saved
`group_sha256`, its `registry`, direct ordered `dependencies`, an optional raw
`candidate`, actual post-IO `registry_observed_at`, and explicit `missing` codes.
Every result has `current_evidence_authorized=False`,
`same_uow_consumption_attested=False` and `needs_lineage_owner=True`.
No `HostFactProof`, complete VerificationEvidence, qualification or effectiveness
decision is created. These flags are not accepted as configurable arguments.

## Exact immutable material and registry

Every fact is selected by tenant/product/id/revision. The full typed v1 body is
assembled with the actual saved atom using the frozen codec, including exact
expected full FactRef SHA. Body payload SHA is never substituted for full SHA.
All child refs retain their complete SHA. Stored column mirrors are compared
with the body; Rule retains the complete origin failures and action-completion
bindings. The complete StableCapaAnchor is parsed and checked, and its origin
IssueVersion is selected by exact full scope and version. The origin snapshot,
source/readset/proof snapshots and prior-version reference must match that real
immutable row. This is raw fixed provenance, not a fresh source proof.

For Rule and Observation, the exact corresponding Current series is required.
Current tenant/product/project/Issue/CAPA, series, origin version, owner,
visibility, nature, purpose, full anchor and requirement binding must match.
Rule Current also matches issuer key/version/external ID of its exact target.
Every Current target is assembled from its own body and real group. The complete
backward chain down to v1 is bounded and checked for exact previous full refs,
consecutive revisions, distinct immutable IDs and the same series binding.
Rule issuer key/external ID cannot change within a series. Observation's Rule
full ref and executor cannot change within a series. Missing roots, disconnected
selection, missing/ambiguous Current, bad epoch or missing full SHA are rejected.

Registry states are:

- `current_registered`: selected full ref equals the exact Current target.
- `historical_registered`: selected exact full ref is an ancestor of that target.
- `fixed_review`: immutable review, no Review Current exists or is inferred.

Current epoch is read as an actual positive strict integer, not guessed from a
revision, timestamp, `MAX(created_at)` or row count. A single Current row cannot
prove historical pointer epoch transitions. The future real registry owner and
installed pointer guards must attest that truth; the registry gate remains
explicitly missing in this delivery.

Observation returns its **saved** full Rule ref, even if Rule Current advanced.
Review returns its fixed Rule followed by the exact ordered saved Observation
refs; historical children are not replaced with current facts. Duplicate child
Observation refs and children bound to a different Rule are rejected.

The origin Issue is not compared with Issue Current here. A legitimate later
effectiveness/close append can change Current without changing the fixed anchor.
This reader neither labels all old content invalid nor grants a finite lineage.
The actual limited lineage owner is a separate mandatory integration.

## Candidate full-SHA gap

The existing `CapaVerificationEvidence` has `inspection_sha256` and
`binding_sha256`; neither is the future full candidate FactRef SHA. No existing
actual candidate atom/full-group codec is installed. Review therefore requires:

```python
candidate_owner(s, ctx, product_id, exact_candidate_ref) -> CandidateRegistryRead
```

The typed callback result is bound to the identical Session and Context objects,
product, full selected ref, scope, Issue/CAPA, purpose, owner, visibility, nature,
anchor and requirement SHA. The actual Candidate row must also exist in exact
scope at v1 and retain its unknown candidate state; the callback must read and
verify the actual complete candidate material/group under that same active UOW.
It must not use a caller hash, inspection SHA or DTO boolean as positive truth.
The raw callback grants none of the seven owner gates. Root must freeze its
actual full-SHA definition and publication/common group codec before mounting it.
Without this callback Review raises `FACT_CANDIDATE_OWNER_REQUIRED` (503).
Rule/Observation do not depend on this gap.

## Query, final IO and authority limits

Each owned SQL SELECT uses `LIMIT 2`, `populate_existing=True`,
`autoflush=False` inside `Session.no_autoflush`. There is no mutation, INSERT,
UPDATE, lock reservation, flush, commit or new Session/transaction. Aggregate
immutable versions, origin rows, Project rows, Current rows and Candidate are limited to **64
distinct nodes**. Overflow raises `FACT_REGISTRY_LIMIT_EXCEEDED`; nothing is
truncated, and the first 64 rows cannot justify a current/complete result.
Root's atom reader keeps its independent bounds.

After all fact/group/parent/candidate-owner IO, every encountered Current row is
reselected and compared with the complete initial row, including epoch. All
encountered Projects are reselected and their exact scope/owner/visibility/status
are compared after all owner IO; an unrelated name or current plan revision is
not an ACL fact and does not invalidate the raw read. The real current caller
ACL is checked again with Root's post-Grant-IO clock, and the UOW
and caller identity are checked again. Only then is the actual post-IO observation
clock returned. This timestamp is not a promised freshness interval or a seven
gate attestation. Later callback phases must independently recheck their own
source/runtime/issuer/participant/professional/coverage/applicability truth and
finish with post-all-owner-IO closure/TTL/UOW checks. No result is cached across
inputs, preview, apply, replay, HTTP request or transaction.

The `missing` list always contains all seven registry/sources/participants/
applicability/observation/provenance/authority owner integrations, plus the
issuer and lineage owner integrations. Stored named actors or `applicable` review
DTOs do not satisfy them. Saved full SHA/provenance is not authorization.

## Check scope

Owned pure tests run only with `--noconftest`. They use actual no-connection
SQLAlchemy Session/root/SAVEPOINT objects and compilable bounded PostgreSQL
SELECT substitutes. The frozen atom reader itself is executed; its live SQL
transport and actual external facts are not claimed. Candidate callback
positives are explicitly synthetic raw registry substitutes.

Meaningful checks cover current/history, exact child ordering, broken full-SHA
chains, Current ambiguity/binding, complete original context, missing candidate
owner, callback scope/UOW drift, post-callback pointer changes, actual caller
revocation and expiry, private/cross-tenant/product access, SAVEPOINT ending,
aggregate overflow and no qualification/proof creation. Real PG/DDL/rights/
concurrency and all seven owner gates remain Root's future integration work.

The first 48-test candidate did not yet read Project ACL. Root explicitly
required the narrow Project gate before mounting any raw reader. The original
48-test log is retained; the next candidate adds private Project non-owner,
wrong-scope Project and post-owner-IO audience drift checks. It does not claim
the original 48 checks covered this later delta.
