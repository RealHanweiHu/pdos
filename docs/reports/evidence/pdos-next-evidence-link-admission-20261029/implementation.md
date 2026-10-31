# Locator-only EvidenceLink admission

This independent increment has one shared implementation file and two new test
files, pinned by `manifest.json` and a surgical `shared.patch`. It changes no live
file, DB, migration, source body, EvidenceLink schema, original scan policy or model
qualification. Root alone applies it and executes PG.

## Confirmed failure and existing owner contract

`EvidenceLinkCreate.evidence` accepts `type/id/version/locator`; it has no `quote`
field. A native Human `evidence.link.create` validates the real locator and stores
an independent immutable association. `root_sources.project_items` already loads
the source through this transaction's actor/requester RLS and `source_for`, then
uses `_canonical_citation` to place an actual nonblank line/quote **inside that
locator** in the item's `source_refs`. Its adjacent `evidence_links[].evidence`
remains an immutable association description with no quote.

Before this patch, `proposal_context.collect` passed both canonical `source_refs`
and that description through the generic recursive `_references`. The second ref
lost the unsupported locator field and had line=None / quote=None. The actual
`baseline.validate_sources` validated each artifact ref with `load_source`, so the
valid native association failed with `quote_not_in_source`. The failure is a
duplicate projection consumer bug; no missing quotation needs to be invented.

## Minimal implementation

`proposal_context._projected_references` traverses only the server-owned proposal
and history projections consumed by `collect` / `validate`. It skips the explicit
`evidence_links` description subtree and delegates the original scalar typed-ref /
SourceRead interpretation to the unchanged generic walker. It does not scan bare
UUIDs or alter a payload, document, citation, body, lineage or stored history.

The canonical source_refs still pass the actual baseline closure / quote validator.
The real `ProposalSource` root union must still be covered; a description by itself
cannot supply proof. Missing or false quotation in a real source_ref still fails.
Every later read retains `_watermarks`, source_for, current ordinary RLS and scan /
withdrawal guards. No quote=None exception or global identity deduplication is added.

## Other walker callers reviewed

| Caller | Actual input and retained check | Change |
| --- | --- | --- |
| `proposal_context.collect/validate` | Native owner projection, complete source root closure, baseline exact quotation, actual current watermarks | Local projected walker |
| `m3_object_reads._public_proposal` / item history | Native projection plus independent real ProposalSource root union, public source heads and privacy | None; identity duplicates do not request quote validation |
| `m3_spec_compare` | Native proposal / knowledge / definition views, ordinary object heads and real Run-bound source identity | None; bound checks use identity/version |
| `m3_definition_diff` | Native definition/proposal views, ordinary scoped baseline/source checks | None; bound checks use identity/version |
| `domain_reads` baseline | Native baseline projection, actual Run object authority | None; bound checks use identity/version |
| `domain_adapter.command` | Model arguments, normalized strict payload and explicit bound-read checks | None; original generic walk is deliberately retained |

## Prepared validation

Nine new pure tests cover locator-only schema plus actual canonical normalization
(None / line / lines / chars), unchanged projection, one canonical consumed ref,
real baseline quote validation, missing/false quotes, missing canonical proof,
preserved typed references and rejection of bare UUID values. Their only source
access double is explicit and in-memory; this is not PG/security evidence.

Candidate pure run: **258 passed** (9 new + 249 existing) with DB / Temporal /
checkpoint variables removed, explicitly loading only this staged production module.
The existing files in that run were:

```text
tests/preproject/test_evidence_g0_unit.py
tests/preproject/test_evidence_payloads.py
tests/preproject/test_baseline.py
tests/agent_kernel/test_m3_baseline_reads.py
```

Explicit `ruff check --config pdos-next/ruff.toml` passed on all three files.
Four new native PG cases collected with database variables removed, not executed:

1. Real uploaded bytes / original scan+parse -> private customer proposal -> native
   Human locator-only Link+Receipt -> actual HTTP Run admission -> ordinary M3
   read/project_context. Check exact fixed source, original/customer taint, actual
   Human provenance and no model/ToolCall.
2. Same native chain, then actual new original scan request. A fresh admission and
   both original-Run reads reject.
3. Same chain, then native T1 original withdrawal. Admission and reads reject;
   immutable Link/Receipt remain.
4. Same chain, then expiry of the existing synthetic 小Pai membership fixture only.
   Admission and reads reject. No business history or source body is rewritten.

The PG file imports only existing repo native fixtures; it has no `/tmp` import.
It uses no real model/provider, fabricated Artifact, derived business history or
golden-case. Root must run it after applying the shared candidate.

## Suggested affected actual PG regression list

New four plus:

```text
tests/agent_kernel/test_proposal_context_pg.py
tests/agent_kernel/test_proposal_context_admission_pg.py
tests/agent_kernel/test_m3_original_binding_pg.py
tests/agent_kernel/test_baseline_watermarks_pg.py
tests/preproject/test_evidence_commands_pg.py
tests/preproject/test_evidence_link_atomic_pg.py
```

These cover real source closure, newly admitted Claim/snapshot, source scope changes,
original scanning, frozen baseline behavior and native Link/source projection atoms.
Root can retain exact same-candidate existing evidence where unaffected; this list
is an impact map, not a request for repeated full-suite or model qualification work.

No actual PG result or design completion is claimed by this stage.

## 整合原生复验（2026-10-29）

四个新 EvidenceLink 正反例（原始、重扫、撤回、作者失权）与三个既有私有入口全部通过；同组 X2 三项候选及一个实际 Temporal 续接也通过，共 11/11。见 [JUnit](../pdos-next-x2-candidate-state-20261029/pg-evidence-x2-run1.xml)、[分组](../pdos-next-x2-candidate-state-20261029/native-integrated-result.json)及[原始日志](../pdos-next-assistant-combined-20261029/pg-evidence-x2-candidate-run1.txt)。真实临时 PostgreSQL/本地 Temporal，模型为离线合成测试端口。
