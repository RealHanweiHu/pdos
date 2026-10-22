# Wave19 actual applicability/action owner · v1

Status: source delivery for Root startup integration. This report is not PG/HTTP, professional qualification, independence, effectiveness, or closure acceptance.

## Ports and constructors

`pdos_next.capa_applicability_owner.ActualApplicabilityOwner(fact_owner, *, paired_owner=None, action_owner=None, epoch=1)`

`read(s, ctx, product_id, NamedReviewPayload, *, anchor, candidate, pairs, observations) -> named_review_owner.ActualReviewApplicability`

`refresh(s, ctx, product_id, payload, previous, **same_keyword_material) -> ActualReviewApplicability`

The result binds the actual Session/caller/Product, complete anchor SHA, fixed stored candidate ref, ordered PairApplicability, complete ActionFulfillment, whole raw owner material, canonical sources/reads, checked_at and earliest valid_until. It contains no new qualification boolean. `pairs` comes from the actual NamedReview paired owner; passing ServerPairRead/PairedReadOutcome DTOs alone is insufficient. The configured live paired reader is independently invoked in read and refresh.

`ActualActionFulfillmentOwner(*, implementation_owner=None, epoch=1)` is the default action sub-owner. Its read/refresh receive the actual action selection and the same anchor/candidate/rule/observations. It returns ActionRead with current classification, conservative fulfillment, whole owner material, sources/reads/valid_until/missing.

## Actual method evidence

- Current ActualMethodCurrent points to exact ActualMethodApplicability. The fixed Formal sample/item and real Sample→Lot→ActualConfiguration→Build chain are checked under the current caller.
- The existing actual method check rechecks fixed basis, current sources, original professional reviewer, and actual configuration. Planned method checks cannot substitute.
- Exact ActualMethodBatch typed semantic, snapshot/hash/domain intent, child UUID/membership/full child snapshot, fixed Formal parent and Receipt/Audit/Outbox/original RequestKey are read. Domain intent and common intent are kept separate.
- Actual Method SourceRef and numeric criterion.source (or qualitative criterion_source) are typed-normalized without dropping fields, and must match both requested selection and exact Rule sources.
- Whole saved row, original per-pair source order and all raw snapshots stay in owner_material. Sources cannot be silently added as positive evidence.

## Actual action evidence and limitations

- The explicit original completion IssueVersion/Current and its actual completion common group are read; no owner Context is borrowed.
- The saved nine-field CompletionFact is compared with the real source line and the exact executor, purpose, action, text, occurred time and original timezone. Occurrence and receipt clocks remain distinct.
- Current controlled synthetic investigation classification can be read through the existing host registry/publisher and full classification source basis. Investigation remains fulfillment unknown.
- A non-unknown fulfillment requires explicit implementation_owner.read/refresh returning ActualActionAttestation, bound to this Session/caller/Product/anchor/action and its own actual material/refs/expiry. A bool/DTO passed by the client cannot authorize. There is currently no configured physical implementation/fulfillment port; the default cannot prove applicable fulfillment.
- Missing classification or fulfillment is explicit; no Issue/Rule/Run/Receipt, qualifier, effect or close is created. The source action remains actual completed even when fulfillment is unknown.

## Current and end-of-I/O boundary

All source refs and read sets are complete unions bounded at 20, with no truncation. Real current native-registration provenance or uploaded original bytes/security use the existing source owner. Source/source-security epochs, Current/raw rows, original reviewer authority, current caller professional authority, Rule/policy, Project and runtime are independently rechecked after initial I/O; source readers retain their normal same-UOW locks. The last current caller/Grant SQL is followed by actual time and earliest expiry/future activation checking; pure result construction is also checked against the deadline and same UOW. Business read-only permits existing SELECT locks and performs no begin/flush/commit/DML or new connection.

`runtime_stamp` includes fact owner identity/stamp, live paired ports/epoch, action sub-owner stamp and actual method/physical/source/policy functions. Action material separately preserves action_runtime. Root outer stamps must list nested action/implementation ports and profile registry identity/epoch/full SHA without calling this stamp recursively through fact_owner.runtime_stamp.

## Validation scope

Owned tests use a real SQLAlchemy Session/active UOW with connections prohibited and explicit saved-row/source/professional/byte/paired substitutes. They exercise writer-shaped batch/action material, separate domain/common intents, missing/mismatched common groups, fixed sample/config/criterion, unknowns, full source limit, old reviewer revocation, Current/source ABA, future activation, UOW failure, port replacement during final I/O and final material expiry. They do not attest actual PG guards, physical sources, live independent qualification or performance. Root owns actual startup, target DB, HTTP and shared scenario checks.

Private origin and private original sources still require the actual series owner; adding a peer ProductGrant does not authorize reading. A reviewer present among actual test/report/root/containment/completion participants remains ineligible under NamedReview. A positive independent scenario needs a new lawful shared failure lineage and genuine owner outputs; this package does not construct it.
