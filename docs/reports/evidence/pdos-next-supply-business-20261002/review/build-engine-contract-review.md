# Build / supply-cost consumer contract review

Read-only review on 2026-10-02. No database, service, environment, engine test suite, credentials, or shared code was accessed or changed. These are in-flight source observations, not a frozen mainline interface or a business acceptance result.

## Canonical demand mapping

`domain/builds/service.py::readiness_snapshot` binds server-loaded Build, engineering configuration/BOM, and manufacturing configuration into `build-readiness-input.v1`. `domain/builds/readiness.py::compute_readiness` validates that snapshot and owns the resulting `demands` projection. The supplier module should consume this projection through BuildDemandPort; it must not save another BOM/Build/MaterialDemand owner.

The current precise engine mapping is:

| Engine field | Canonical Build input |
|---|---|
| `basis.build.build_id` | `input_snapshot.build.id` |
| `basis.build.ref` | `_ref('build', typed_build)` |
| `basis.build.quantity/product_unit` | `build.quantity/unit` |
| `basis.bom.ref` | `_ref('bom', typed_engineering.bom)` |
| `basis.bom.engineering_configuration` | `_ref('configuration', typed_engineering)` |
| `BomItem.item_id/material_id` | BOM line `key/part_id` |
| `quantity_per_parent/unit/loss_rate/critical` | line `quantity/unit/loss_rate/critical` |
| `parent_item_id/supply_required` | currently fixed `None/True`; this is a flat BOM contract |
| authoritative demand | result `demands`, not total coverage quantities |
| manufacturing ref | `_ref('manufacturing_configuration', typed_manufacturing)` kept alongside FixedBasis |

`_ref` is `source_id=f'{kind}:{id}'`, `version=str(revision)`, `sha256=digest(typed_record)`, `captured_at=created_at`, `state=source_state`, `valid_until=valid_until`. These hashes are typed projection hashes with defaults, not hashes of the full SQL row or a client payload. The engineering hash includes its nested typed BOM and definition ID. The `configuration:` source ID intentionally differs from the result's display kind `engineering_configuration`.

Build currently returns FixedBasis only inside `result.coverage.input_snapshot.basis`, because it is a local variable in `compute_readiness`. A server adapter can pass this exact basis and authoritative `result.demands` into a minimal typed port DTO. It must separately carry server-bound tenant/product/project scope, Build/configuration/BOM revisions, manufacturing ref, immutable `as_of`, required source read set, and readiness input digest. Supply must not copy the private Build classes or reconstruct source hashes from an expanded/full configuration view.

## Equivalence and freshness requirements

1. Verify `expand_bom(port.basis, port.as_of)` equals the canonical `demands` in every DemandLine field, including item/material identity, ancestry, unit, critical, per-product/Build quantity, nulls, and issues. Compare structured canonical values by item ID, and reject duplicate/missing/extra IDs. Numeric spelling differences can normalize as Decimal; units or unknowns must not be substituted.
2. The engine's coverage lines are sorted by critical then item ID and include only explicit supply levels, plus uncovered leaf placeholders. Compare the full expansion to canonical demand before calling the engine; do not compare raw ordered `coverage.lines` against Build's sorted expansion. Current flat BOM selects every line, but future hierarchy must retain explicit `supply_required` and parent semantics.
3. `as_of` changes can alter validity even with identical basis. Reuse the canonical demand calculation time or have Build produce a fresh canonical snapshot at the calculation time. A source state/time/digest/read-set change requires a new result and revalidation, not a mutation of old history.
4. Build's source check also covers manufacturing configuration, which engine FixedBasis omits. Supply's consumer must recheck it separately. The current Build service marks authorized loaded snapshots current; `validate` and configuration loader enforce required source read set. Pure engine `state='current'` is an input fact, not authority.
5. Current readiness remains `ready=None`, `hard_blocking=True`, supply/quality/resources/releases unknown. A successful supply candidate cannot approve Build or clear unrelated hard unknowns.

## Manufacturing and cost gaps

Current `ProcessOperation` has key/name/kind, dependencies, BOM line links, SOP/resources, cycle_time_minutes and acceptance criterion. It does not provide engine fields `quantity_per_product`, explicit per-qualified-product unit, `loss_rate`, or `price_id`. Cycle time does not prove per-good-product quantity or yield, and missing loss cannot become zero.

CostInputPort must supply an immutable process cost projection from the fixed manufacturing configuration, verified by the server against its ID/revision/digest and operation keys, with explicit process assumptions and quotation references. CostRequest itself has no manufacturing linkage, so the domain consumer must enforce that linkage before calling `calculate_cost`. For materials-only scope, absence of process cost data is permitted and displayed as excluded scope, not complete formal cost.

The underlying configuration model allows Numeric(38,12), while current readiness and engine numeric inputs accept 24 digits/8 decimal places; values outside the consumer DTO must return an explicit mapping/unsupported error, never truncate. The readiness adapter also preserves loss > 1 as unsupported/unknown while FixedBasis Loss permits only [0,1].

## Alternate qualification and physical stock

The engine checks alternate status, source currency, exact Build ID, BOM hash and engineering hash, units and positive ratio. It does not verify tenant, project, requester, audience, named qualification or authentic issuer. Only a server port may return `externally_verified`, and it must validate current qualification scope, evidence, intended use and authorized audience. Payloads must not supply this fact; similar parameters are insufficient.

All related physical pools and active reservations must be included for `supply_scope_complete=True`. Pool identity is `(source_system,pool_id,material_id)`. New in-transit/received/on-hand stages are versions of the same physical pool, not additive supply. Different physical pools for delivered and outstanding portions must have genuine separate fixed IDs and provenance. Released/available/actual stock only enters usable coverage; promises/in-transit, frozen and unknown quality are preserved independently.

## Observed digests

SHA-256 values rechecked unchanged at review completion:

| Source | SHA-256 |
|---|---|
| builds/readiness.py | `ab768a33a0d98e7bf70e7d03969ca86bdfdd67f8e2e49e782f0346a4db88e00d` |
| builds/service.py | `78e7900c1fc247bf963d7ef7b03bee11af51b06fd43e2285e9da050478bca44f` |
| builds/schemas.py | `bc002e93a9f8070f552efaf759fdfcc7cf1003580217b2d7aa37ef330600c086` |
| builds/models.py | `6d4b8da107feddd093f5b4575cc2e5eb5e2c0bceaa647e9fd5704969ab3c2ade` |
| configurations/schemas.py | `c7bfc9afc30fa535b96c531937972fc13ccd6164e47eb49422b9d375830f16cb` |
| configurations/models.py | `7d366adab2fd2e9cf04a570f7b5821a1efe0a60ead9894954d11fb4c0d2606b4` |
| engines/supply_cost/dto.py | `14f3cc902abde9ffcf98639a577812ba8577445a532299899cfb63541718a1d8` |
| engines/supply_cost/bom.py | `cdad615b84a349dae4cb3d7c9e447491ed70d9ab7b63b1e95f67112a4649cdf2` |
| engines/supply_cost/common.py | `cd7f43ffb1c46bf8175fe59da3c76b9aeaf598d03def82aa03b8a10d4dab7379` |
| engines/supply_cost/coverage.py | `534737cf0117ddc1607d7f56e705ebefb2311e72f25dca1a9ff386cfb6ef7e6d` |
| engines/supply_cost/costs.py | `6e5af8ec6a13fc9d5309dc9ca9afbb0111882bf686498b45730551fdced0ea36` |

At review time `domain/configurations/service.py` was absent although Build service imports it; absence is an in-flight integration condition, not a reason to import SQL/mainline service from this isolated adapter. Recheck the consumed DTO/source versions before final candidate delivery.
