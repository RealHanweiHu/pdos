# QUA-04 query-only lexical diagnostic — unapplied proposal

No repository inputs were changed. No database, model, embedding or network was called. Files here are a proposal and pure numerical simulation; the frozen native baseline remains macro recall@5/@10 = 97.92%.

## Concrete cause

`tokenizer.py:60–77` uses the same index vocabulary for queries and source projection. The QUA-04 query removes only `和`; it retains 23 tokens, including pronouns, prepositions and request sequencing. `query.py:86–90` uses OR eligibility, and `query.py:231–256` sums BM25 for every retained query token. Rare grammatical tokens therefore receive positive IDF and can outrank the relevant laboratory report.

With the exact 24 frozen document texts/titles and tenant DF (including private documents), a Python transcription of the production BM25 reproduces all 28 recorded native top-10 ordered lists exactly. Native creation-time freshness is omitted; this agreement does not establish SQL/RLS equivalence for any changed query. Each document is one production-sized chunk in this corpus.

QUA-04 laboratory report is a lexical candidate, estimated rank 14, score 3.7924 before freshness: `裂纹` contributes 2.2356, `对` 1.5568. Its title already contributes `裂纹`. At rank 4 the engineering meeting record scores 6.5229 from only `按` (3.1184), `先` (1.9233), `问题` (1.4812). Thus the miss is ranking pollution, together with the genuine absence of a lexical `料太湿` → `含水率` correspondence. It is not an absent report/index/candidate or a broken exact-code channel.

## Bounded candidate, with both variants retained

Query-only function words are a distinct frozen lexical policy, with no source-type/category-specific rules and no synonyms, label-dependent boosts or rank constants. The 18-word conservative variant removes pronouns/determiners, prepositions and request sequencing. It moves the lab report 14→11 and leaves both recall cutoffs unchanged. Its output is `comparison.json`.

The 19-word drafted variant additionally removes the negative copula `不是`, matching the existing grammatical treatment of `是` and interrogative `是不是`. It deliberately keeps factual negatives such as `未/无/没有/不能` and single-character technical terms such as `料/孔/测`, as well as compound tokens `对照/按键/把手`. It moves the report 14→10. No other question's expected-source ranks change. On this pure simulation only:

| Metric | Frozen/native-aligned pure baseline | 19-word query-only draft |
|---|---:|---:|
| macro recall@5 | 97.92% | 97.92% |
| macro recall@10 | 97.92% | 100% |
| micro recall@5 | 96.43% | 96.43% |
| micro recall@10 | 96.43% | 100% |
| MRR | 97.92% | 97.92% |

The rank-10 outcome is marginal and does not resolve the semantic mismatch or establish general retrieval quality. The two variants are shown explicitly; this is not a claim that this small authored set selects an optimal stop list. Do not remove `问题/登记/检测/原因/批/料`, hardcode `太湿→含水率`, change expected labels, or raise cutoffs to force success. Retain the recall@5 gap.

## Proposed minimal code boundary

`query-only-function-words.patch` touches only tokenizer.py and query.py. It adds `analyze_query`, called only by production keyword search. Existing `analyze`, terms.txt, stopwords.txt, dictionary fingerprint, projection work key, index tokenizer version, source/title counts, DF and chunk hashes stay unchanged. No reindex is required for this query-only policy. All raw query arguments remain exact and independent `codes(value)`/UUID handling is retained. An all-function-word query remains empty and uses the existing INVALID_PAYLOAD check; there is no fallback to discarded noise.

Each new result records a separate `query_policy_version` containing the full SHA256 of the ordered function-word vocabulary. Keyword `ranking_version` gains `+query-function-words/v1` (fits the existing 160-character feedback column). If this vocabulary changes, change the named policy and its digest; do not silently reuse a result's version. Hybrid RRF keeps its unchanged fusion version and inherits the policy-bearing keyword query_trace. No production response cache exists in query.search; existing LRU caches contain syntax/dictionaries only.

## Durable results and query fingerprints

AgentToolCall.input_digest remains the digest of the exact original tool arguments, which this helper does not rewrite. Completed assistant.search replay calls restore_search (`assistant_adapter.py:189–201`) to reauthorize its issued citations and return the original immutable result. Such replay must retain its original query trace/ranking and must not be presented as re-evaluation under the new policy. Use fresh READ calls/runs for the comparison. No tool-ledger rewrite, broad invalidation or tool-version bump is needed for this ranking-only draft; if a future cache is introduced its cache key must include the query policy fingerprint.

Query embedding binding (`embedding_query_binding.py:100–119`) hashes and transmits the original query. Since that text is untouched, embedding cached vectors remain correctly bound to their original text; this proposal changes only the keyword candidate path. It does not enable any embedding/model call.

## Pure checks and next validation

`build_draft.py` writes only this directory, compiles both draft modules and checks all 48 frozen body/title analyses unchanged; all 40 question strings/code channels/index versions/counts/safe tsquery; nine additional engineering identifier controls; technical and factual negative terms; and empty-query/code-only behavior. `validation.json` stores original and draft SHAs. Ruff passes for both draft modules using the repository config plus known-first-party=pdos_next because the drafts live outside the package tree.

`qua04_query_only_diagnostic.py --variant basic|copula` replays the pure ranking calculations and uses the existing frozen-label scorer. Original top-10 order is 28/28 identical to native-candidate2. Derived simulation rows carry no timing or actual-query claims. Both variants leave the four synthetic peer forbidden-source checks passing by the same fixture-visible set; this is not new database authority evidence.

After the ANN candidate finishes and root authorizes implementation, the bounded follow-up is the existing 28-query native HTTP baseline plus affected tokenizer and existing identifier/ACL regression checks, with fresh output directory and unchanged question/corpus SHA. Keep the 97.92% historical baseline; only a new real HTTP observation may establish the changed candidate's retrieval result. No new search algorithm or real embedding is required.
