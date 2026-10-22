# Wave18 actual named-review owner · frozen v1

This is an actual same-Session material assembler, not a new Issue/Run ledger, a saved Review, an effectiveness/closure approval, or a live seven-owner attestation. Public PG/HTTP validation belongs to the main task. These owned checks make no database connections.

## Startup interface

```python
from pdos_next.domain.capa_effectiveness.candidate_commands import semantic_owner
from pdos_next.domain.capa_effectiveness.named_review_owner import ActualNamedReviewOwner

fact_owner.review_owner = ActualNamedReviewOwner(
    fact_owner,
    candidate_semantic_owner=semantic_owner(),
    paired_owner=None,
    applicability_owner=None,
)
```

The main startup API already uses this constructor. A configured `ActualFactOwner` invokes:
`review_owner.read(s, ctx, product_id, NamedReviewPayload, *, previous=None, new_write=True) -> FactWriteMaterial`.
The returned value stays delegated material. Only the main FactWriteHost/common T2 path may consume a real named proof, append a fact and save its Receipt/Audit/Outbox. This owner does not begin, flush, commit, produce a proof or change any Current.

## Actual reads and exact binding

- Read the actual current Rule and its saved full StableCapaAnchor through FactOwner `_rule`, and actual original failure/byte/current/ACL closure through `_anchor`. Keep the originally persisted full anchor; no resealing of its observation clocks. Current must still be the completed origin, and a new write also checks the explicit expected Issue revision.
- Read the actual immutable candidate and exact common group via `read_candidate` with the server configured CandidateSemanticOwner. Exact candidate binding, full original failure identities, every mapped new Run/sample/item/configuration, all CAPA action IDs and their saved completion/executor hashes must agree.
- Map each immutable selected Run row to its actual logical Run, full saved BuildRef and exact FormalCurrent. The row snapshot SHA, scope, logical Run/request/revision and Build identity agree before the live paired reader. Run.request_version_id remains the origin; it is never substituted for Current. A subsequent Build is allowed only with its own real exact scope/configuration material and live paired proof.
- Read ordered Observation refs through the actual immutable registry, fixed Rule/anchor/scope/CAPA/purpose and common group. Observation records use target_key/occurred_at/original_timezone/sources/raw_material/missing_fields; no fabricated raw_value or inferred sampling completion.
- `read_participants` and `refresh_participants` preserve actual original test/report registration, root cause, containment, completed action, new Run/measurement and Observation participants from saved rows/groups. The current caller, including an original report registrant, cannot appear in that set. ProductGrant is neither independence nor professional qualification. Actual private reader ACL remains in every owner; no alternate owner Context is constructed.
- Pair applicability SourceRef/ExactSource compatibility compares typed normalized complete id/revision/kind/position; it does not compare only IDs or loosen locators. Every requested pair/action selection must match the actual owner result, exact saved action binding and exact selected sources.

## Missing live owners stay disabled

A raw StoragePairReader does not supply the required live gate. `paired_owner` must implement the actual paired `read/refresh/attest` protocol consumed by `paired.read_paired_formal_output`, bound to this actual Session/caller/scope/Current. A performed structural result alone is insufficient. Missing callback, missing fact/retained/bytes/current authority, missing HostGate stamps or missing live deadline rejects with LIVE_PAIRED_OWNER_REQUIRED or the actual underlying owner error. The live owner is not configured in this delivery.

Unknown human pair/action conclusions remain unknown, with classification and fulfillment explicitly null. Any non-unknown pair/action/overall selection additionally requires a real startup `applicability_owner`; it cannot be a client positive flag. Its `read`/`refresh` receive `(s,ctx,pid,payload, *, anchor, candidate, pairs, observations)`; refresh additionally receives the previous `ActualReviewApplicability` positionally. That frozen returned material is tied to the same actual Session and caller object, product, full anchor SHA, exact candidate ref, whole pair/action coverage, explicit owner material/sources/reads and current aware deadline. Fields: `session, caller, product_id, anchor_sha256, candidate_ref, conclusion, pairs, actions, owner_material, sources, reads, checked_at, valid_until`.

The existing private investigation and its participant cannot become an independent Review by adding a peer grant or borrowing the series owner's Context. Default startup deliberately permits actual negative diagnosis while it denies the unconfigured live pair/applicability path.

## Refresh and clocks

All selected output/source bytes are read in the same active real Session/UOW with no autoflush. The source union includes original anchor, Rule, candidate inspection, complete pair/Observation/participant material, human selections, current professional and policy sources; 1..20 exact artifact versions, no truncation. New DefinitionReference quotes are resolved against the actual whole line before making the SourceRef SHA. Native registration and uploaded-original bytes/security remain distinct actual proofs.

After owner/byte IO, reread participant set, Observation groups, actual paired structure and live stamps, applicability material, candidate group, Rule/original Current, current professional/policy and the entire raw source/Project closure. Runtime identity includes actual fact owner, current callback objects/functions/epochs and source/registry ports. Recheck the full active main/nested UOW and original caller binding; actual final Grant SQL precedes the saved eligibility clock. Deadline is the minimum actual caller/source/professional/policy/pair/applicability boundary, including future activations supplied by the authority owner. Pure output construction also cannot carry a value beyond that deadline.

`FactWriteMaterial` keeps full original anchor, real Current version/revision, actual named reviewer, complete raw source basis/read set, current professional/policy material and structured missing codes. Inspection does not grant decision: applicable=None, independently_verified=None, observation_complete=None, effectiveness='indeterminate', close=False. Raw domain-source/independence-owner missing codes are not silently removed or turned into seven-gate success. The main FactWriteHost refreshes this entire owner again before and after common proof consumption.

## Checks and boundaries

Owned `--noconftest` tests use actual SQLAlchemy Session/UOW and actual Core SELECT compilation with explicit saved-row/owner substitutes. Engine connections and owner flush are prohibited. They cover strict fixed pair/action coverage, current actor participant exclusion, raw/missing live-pair rejection, unknown classification, actual immutable Run→Current/full Build scope/hash/private guards, exact typed source subclass equality plus changed fields, actual UOW/runtime drift and an explicit read-path negative with real caller ACL. They do not prove a new independent professional, live paired owner, PG RLS/deferred atoms, actual report acceptance, effectiveness/close or public performance.

Evidence is in named-review-owner-check-result-v1.json. Earlier pure failures are preserved: invalid test factory field `failure.item` and old `original_failures`, missing fixture raw sources/snapshot, and input ExactSource passed a base SourceRef instance. The genuine BuildRef constructor mismatch found during those checks was corrected before production freeze; defaults/missing guards were retained. No failed log is replaced with a passing claim.
