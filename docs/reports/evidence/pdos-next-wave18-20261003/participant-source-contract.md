# Wave18 actual participant / source owners

Two business-read-only, same-Session material readers. They do not create facts,
begin transactions, flush, commit, mint proof, grant qualification, decide
independence, certify applicability, or enable effectiveness/close. Existing
source gates acquire SELECT locks, so this is not a PostgreSQL READ ONLY claim.

`participants_owner.read_participants(s, ctx, product_id, *, anchor, pairs=(),
observations=()) -> ParticipantRead` accepts explicit fixed selectors. `anchor`
must equal the actual stored completion-origin descriptor. Every original Run
uses the failure's fixed logical id/revision; new PairBinding selections must
match actual Formal and Run Current, same project/Build/revision/purpose and
actual caller. Run origin is not substituted for Formal Current. Exact immutable
rows, full snapshot/plan/measurement hashes, launch/result action records,
Receipt/Audit/Outbox and at least one original RequestKey digest association are
read bounded with `populate_existing`/no autoflush. Common and domain intent are
retained independently. Report participants are actual registration/upload
writer and requester; they are not inferred instrument authors or operators.
Actual measurement executor metadata remains missing when absent. Root cause,
containment and completion actors must match their real saved Issue operation
and corresponding snapshot fact. Observation executor comes from actual
`read_stored_fact(..., 'observation', exact FactRef)` body/group/current evidence.

`ParticipantRead` returns participants `{id, roles, owner_sources}`, complete
`owner_material`, `material_sha256`, `sources`, `required_source_read_set`, sparse
`source_basis`, `checked_at`, earliest `valid_until`, `missing`, and
`needs_lineage_owner`. It always keeps `current_evidence_authorized=False` and
`same_uow_consumption_attested=False`. Roles are original_test/root_cause/
containment/completion/new_test/measurement/observation. No `qualified` verdict.
`refresh_participants` independently rereads all material; it does not validate a
previous DTO's positive boolean or reuse any cross-phase cache.

`fact_sources_owner.read_source_closure(s, ctx, product_id, *, scope, owner_id,
visibility, sources, reads, expected_basis=(), boundaries=()) -> FactSourcesRead`
reads actual current Product/Principal/Grant and exact Project ACL, current
Artifact scope/status/revision/hash, server-checked exact whole-line SourceRefs,
native registration provenance, or real configured OriginalStore bytes/hash/
size/parse state/security epoch. Uploaded bytes are consumed internally only.
Native registered text is explicitly separate and cannot claim instrument
report qualification. Sources/reads are a complete canonical union of 1..20
Artifacts; conflicts/overflow are rejected, never truncated. Unknown domain refs
remain `DOMAIN_SOURCE_OWNER_REQUIRED`. Private source/Project access uses the
actual caller and cannot widen a product audience or borrow an owner Context.
Every original-byte IO is followed by current security/source/Project/runtime/
UOW checks, and final real Grant IO precedes the expiry clock.

`read_fact_sources(s, ctx, product_id, material: FactMaterial, *, operations,
candidate_owner=None)` additionally reads actual policy/current professional
scope and full fact-ref source closure, including negative/future activation
boundaries. Professional DefinitionReferences are converted through actual
`evidence.refs_from_exact`, not client key substitution. All selected saved Rule,
ordered Observation and Review bodies/groups are independently fetched from
the real registry and must equal the selectors; Review needs the configured
actual candidate owner callback or fails missing/503. Paired owner is outside
these two files and remains `PAIRED_SOURCE_OWNER_REQUIRED`. Actual assessment
verdicts are checked internally and bound by SHA but are not exported as an
authorization/qualification verdict. `refresh_fact_sources` performs a fresh
full pass and compares stable material/source basis. No seven-host-gate proof.

`FactSourcesRead` returns scope/sources/required_source_read_set/source_basis/
byte_material/authority_material/policy_material/material_sha256/checked_at/
valid_until/missing and the two fixed false flags. Byte material contains safe
id/hash/size/epoch only. Missing owner/configuration yields explicit DomainError,
never a generated identity, optimistic stub or positive gate.

Sampling keeps the actual frozen DTO: Rule.sampling.targets contains
`{key, kind:sample|lot|population, ref, actual_configuration|null,
identity_sources}`; sampling_method/acceptance are exact SourceRefs and intervals
are original aware clocks. ObservationRecord contains target_key/occurred_at/
original_timezone/sources/raw_material/missing_fields. Null, unknown and decimal
text remain raw; existence of records does not imply complete coverage.

Owned checks use actual SQLAlchemy Session/active transaction chains with an
Engine connection prohibition and explicit row/byte/safety substitutes. They
cover exact common groups, original key association, private access, source
withdrawal/hash/line drift, full 20-source bounds, actual byte mismatch/security
ABA, runtime/UOW replacement and post-IO expiry. These pure checks are not PG,
real scanner/professional qualification, actual observation completeness or
public integration acceptance. Root owns live host assembly and central checks.
