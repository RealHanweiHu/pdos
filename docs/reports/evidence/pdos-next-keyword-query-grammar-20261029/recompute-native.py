"""Independent identity-intersection check of persisted HTTP results; no DB."""
import hashlib
import json
import statistics
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[3]
data = json.loads((FOLDER / 'native-live/baseline.json').read_text())
questions = json.loads((ROOT / 'docs/evaluations/xiaopai-v0/questions.json').read_text())
old = json.loads((ROOT / 'docs/reports/evidence/pdos-next-eval-v0-20261029/native-candidate2/baseline.json').read_text())
assert data['input_sha256'] == old['input_sha256']
bound = data['bound_sources']
identity = lambda row: (row['source_type'], row['source_id'])
observations = {row['case_id']: row for row in data['observations']}
positive, negative, ranks = [], [], {}
for case in questions['questions']:
    if case['evaluation'] != 'retrieval':
        continue
    observation = observations[case['id']]
    found = [identity(row) for row in observation['items']]
    assert len(found) == len(set(found))
    assert observation['query_trace']['query_policy_version'].startswith('query-function-words/v1/')
    expected = {identity(bound[key]) for key in case['expected_sources']}
    forbidden = {identity(bound[key]) for key in case['forbidden_sources']}
    assert not forbidden.intersection(found)
    if forbidden:
        negative.append(case['id'])
    if expected:
        hits = {k: len(expected.intersection(found[:k])) for k in (5, 10)}
        positive.append({'case_id': case['id'], 'expected': len(expected), **hits})
        ranks[case['id']] = {key: found.index(identity(bound[key])) + 1 if identity(bound[key]) in found else None for key in case['expected_sources']}
assert len(observations) == 28 and len(positive) == 24 and len(negative) == 4
result = {'method': 'original HTTP source identities intersect original frozen labels; no producer scorer imported', 'questions_and_corpus_sha256_unchanged': data['input_sha256'], 'positive_cases': len(positive), 'negative_cases_passed': len(negative), 'expected_sources': sum(row['expected'] for row in positive), 'recall': {}, 'expected_source_ranks': ranks, 'p50_ms': statistics.median(row['elapsed_ms'] for row in observations.values()), 'p95_inclusive_ms': statistics.quantiles([row['elapsed_ms'] for row in observations.values()], n=20, method='inclusive')[18], 'identifier_channel_passed': sum(row['identifier_channel_hit'] for row in data['identifier_channel_checks']), 'protected_state_unchanged': data['protected_state_unchanged'], 'real_model_calls': data['real_model_calls'], 'real_embedding_calls': data['real_embedding_calls']}
for k in (5, 10):
    macro = statistics.mean(row[k] / row['expected'] for row in positive)
    micro = sum(row[k] for row in positive) / result['expected_sources']
    assert abs(macro - data['metrics']['retrieval'][f'macro_recall_at_{k}']) < 1e-12
    assert abs(micro - data['metrics']['retrieval'][f'micro_recall_at_{k}']) < 1e-12
    result['recall'][k] = {'macro': macro, 'micro': micro, 'hits': sum(row[k] for row in positive)}
assert all(bound[key]['document_sha256'] == value['document_sha256'] for key, value in old['bound_sources'].items())
result['all_24_source_document_sha256_unchanged'] = True
(FOLDER / 'independent-native-metrics.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'expected_source_ranks'}, indent=2))
