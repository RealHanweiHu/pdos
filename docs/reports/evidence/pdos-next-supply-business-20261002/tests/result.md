# Supply/cost business pre-freeze pure-check candidate · 2026-10-02

98 tests passed at this pre-freeze checkpoint. Package-only Ruff check passed. Raw result is [junit.xml](junit.xml), and the consumed source and test hashes are fixed in [candidate.json](candidate.json). Five subsequent snapshot-freshness cases and the on-hand inventory mapping assertion were added after this run; the root package's final freeze check supplies their validation and replaces this checkpoint as the final candidate evidence.

Executed from `pdos-next/server`:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p no:cacheprovider --confcutdir=tests/supply_cost_domain tests/supply_cost_domain -q --junitxml=../../docs/reports/evidence/pdos-next-supply-business-20261002/tests/junit.xml
98 passed in 0.19s

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m ruff check --no-cache tests/supply_cost_domain
All checks passed!
```

Covered:

- The complete Build expansion is compared field by field, including quantity, ancestry, criticality, material and unit. Basis/manufacturing hashes, all four server scope fields, source-read-set attestation, current source state, expiry, future capture and fixed versions are blocking guards.
- Identical shared physical-pool observations deduplicate; contradictory pools, reservations, commitments or receipts block. Immutable snapshot ID replay, ID conflict, revision/previous-pointer conflict, capture order and retained before/after deltas are checked.
- Partial receipt capacity comes only from the authoritative current pool. Promise and transit remain separate evidence, including an overdue promise. Frozen/unavailable stock contributes no usable capacity; restrictions must match the exact server quality partition. Other Build occupancy subtracts from the shared balance.
- Verified alternate applicability is fixed to Build/BOM/configuration. Changed or unconnected current qualification recheck is explicit. No request payload can claim scope or alternate authority.
- Missing quote/process scope remains incomplete with candidate amounts unknown. Decimal precision, explicit quote validity/quantity tier, exact manufacturing operation mapping, currency/rate-age checks and fixed cost-input binding are covered.
- The participant authorizes before domain reads, exposes absent ports as pending, validates current snapshot pointers and substantive T1 preview/hash/expiry, blocks source changes/expiry between preview and apply, and returns completed duplicate receipts before new current-source reads. Semantic intent is independent of retry keys. The same synthetic host UoW is passed through; its `commit` raises if called.
- Read mappers require the original historical FixedBasis, preserve decimal strings/unknown values and separate commitment evidence from pool balances. Reconciliation retains before/after values and never subtracts mismatched units. Historical projections preserve their original input snapshot and results.

Not covered: real database persistence/model registration, shared command confirmation token cryptography and one-use locking, concurrency/rollback, Audit/Outbox atomicity, authenticated API/BFF/routes, Build mainline mapper wiring, browser/theme/responsive review, real inventory/quote/source evidence, external qualification or financial approval. Fake ports model the required host behavior; these checks do not prove those host guarantees. The existing engine suite was not rerun and its previous checks are not counted in the 98.

No `.env` or `.local` credentials were read; no database, service, model, migration, install, full build, commit or push was used. Root database fixtures, plugin autoload, pytest cache and bytecode writes were disabled. This is a package candidate, not a G/N/P/Q or formal joint acceptance result.
