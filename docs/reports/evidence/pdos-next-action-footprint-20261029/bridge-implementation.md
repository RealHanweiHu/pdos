# Native action parent discussion carry

Independent fix for actual `pg-run1` action failures. One shared implementation,
one shared native negative fixture and one new pure test file; no DB/migration,
live edit, model/provider or service startup.

The shared base is D's **already integrated final**
`action_sources.py` SHA256
`3a142ee8b7619ece79ef5f58111e251c14517dedee98e45a3072bce3c47088f1`.
`SOURCE_TABLES`, new field-feedback source type and field basis hook are preserved.
Apply `shared.patch` against that base; do not copy an older action package over D.

## Actual root evidence

`pg-run1.xml`: parent shared action denied before Run admission passes, but private
positive and all six old candidates were empty; the child-new-B case timed out.
`pg-run1-readonly-probe.json` then proves for both real completed Runs:

- fixed direct-parent `check_action` / source proof passes;
- child ordinary `ledger.carried/current` contains only its new execution Artifact;
- selected original discussion CID is absent; candidate `capture_child` fails
  `assistant_action_citation_not_carried`.

The exact cause is original continuation `data.sources=[execution]`:
`context_corrections.configure_start` writes that explicit ordinary source limit,
`assistant_ledger.issued` filters inherited refs through `accepts`, and `carried`
returns own/inherited only when a frozen condition exists. The separately fixed
`verification_action` explicitly selected parent discussion but did not bridge it
into capture. Removing ordinary filtering would broaden unrelated retrieval.

## Narrow change

`_discussion_footprint` starts with the actual child carried set. Only when this
actual Run has a frozen native `verification_action`, original `check_action` must
revalidate its direct continued_from parent, tenant/session/requester/product/project,
current target and original immutable parent proof. It then reads that parent's
actual ordinary / inherited sealed READ ledger footprint.

- Only the fixed action's selected discussion CIDs are added to the selectable
  discussion/execution pool. A same-CID/different-metadata collision rejects.
- The parent's **complete** footprint, including unselected sources, joins the
  child's complete footprint solely for current source / dependency / audience
  checks. It does not add references to the resulting proof or Run read_sources.
- Execution references remain explicit and must satisfy both actual child Run
  binding and the selectable actual-read pool. Unselected parent taint alone cannot
  satisfy an execution read, even if that Artifact id appears in read_sources.
- Ordinary context_selection, ledger, retrieval, generic continuation and citation
  re-signing contracts are unchanged. No arbitrary ancestor scan, fabricated quote,
  source binding, business fact, permission or model qualification is introduced.
- Existing recheck on candidate display/preview/confirmation repeats parent and child
  current/taint checks. An ordinary continuation without the native action does not
  import its parent through this helper.

## Offline validation

Final candidate **130 pure tests** (12 new + 118 existing), explicit Ruff config on
all three files. DB / Temporal / checkpoint variables were removed. Candidate validation
loads only this staged production module; delivered tests import repo modules only.
Existing affected files in that run:

```text
tests/enterprise_search/test_action_sources.py
tests/enterprise_search/test_action_footprint.py
tests/enterprise_search/test_verification_actions.py
tests/enterprise_search/test_verification_candidates.py
tests/agent_kernel/test_verification_kernel.py
tests/enterprise_search/test_field_feedback_source_contract.py
```

New cases verify selected A survives separate execution-only context while ordinary
ledger stays narrow; uncited parent or child customer context still rejects shared
output; private output still rejects later uncited parent revocation; wrong direct
parent/session/Human/product cannot borrow proof; unselected parent taint cannot
become a citation/execution read; conflicting same-CID metadata rejects; ordinary
continuation alone grants no bridge.

The original 3 new + 6 old actual PG/Temporal tests collected (9 cases), not executed
here. Root should first rerun normal positive and private target, then the complete
affected group under its actual guarded environment. No native success is claimed
until those actual runs pass.

## Authorized child-B fixture correction

If that negative fixture starts with only `sources=[execution]`, an attempted search
for B is correctly filtered by the ordinary explicit source limit. A provider that
assumes B exists can fail/retry until timeout. This action fix intentionally does
not relax that limit. The shared negative fixture now has the real Human explicitly
choose `sources=[execution,B]` on that turn, while action discussion citation_ids
remain A and model execution references/drawing remain execution only. It asserts
B exists in the actual Run read_sources and native requested_context_selection,
with no shared candidate/event/domain write. No body, read ledger or server scope
is fabricated. The private positive is unchanged and continues to prove that
unselected parent B is never automatically added to Run read_sources.

The original timeout and its `pg-run1.xml` evidence remain unchanged: that fixture
had incorrectly required its synthetic provider to read outside the Human's explicit
ordinary source selection. The correction is not an authority or guard relaxation.
