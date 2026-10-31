"""Pure diagnostic only: frozen corpus/BM25 comparison, no database or provider."""
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/Users/huhanwei/Desktop/ai-native-R&D-platform')
sys.path.insert(0, str(ROOT / 'pdos-next/server'))
from pdos_next.enterprise_search.tokenizer import analyze

OUTPUT = Path('/private/tmp/qua04-query-only-draft')
OUTPUT.mkdir(exist_ok=True)
# Pronouns/determiners, prepositions and sequencing/request particles only.
# Keep negation, all single-character domain terms and all technical identifiers.
parser = argparse.ArgumentParser()
parser.add_argument('--variant', choices=['basic', 'copula'], default='copula')
variant = parser.parse_args().variant
FUNCTION_WORDS = frozenset('我 我们 你 你们 您 这 这个 这些 那 那个 那些 把 对 按 先 再 别 是不是'.split())
if variant == 'copula':
    FUNCTION_WORDS |= {'不是'}
POLICY = 'query-function-words/v1/' + hashlib.sha256('\n'.join(sorted(FUNCTION_WORDS)).encode()).hexdigest()


def query_analyze(value):
    parsed = analyze(value)
    removed = set(parsed['terms']) & FUNCTION_WORDS
    return {**parsed, 'terms': [t for t in parsed['terms'] if t not in FUNCTION_WORDS],
            'counts': {t: n for t, n in parsed['counts'].items() if t not in FUNCTION_WORDS},
            'length': parsed['length'] - sum(parsed['counts'].get(t, 0) for t in removed),
            'removed': sorted(set(parsed['removed']) | removed),
            'query_policy_version': POLICY}


def main():
    dataset = ROOT / 'docs/evaluations/xiaopai-v0'
    documents = json.loads((dataset / 'corpus.json').read_text())['documents']
    questions = json.loads((dataset / 'questions.json').read_text())
    native = json.loads((ROOT / 'docs/reports/evidence/pdos-next-eval-v0-20261029/native-candidate2/baseline.json').read_text())
    bound = native['bound_sources']
    by_alias = {d['alias']: (d, analyze(d['body']), analyze(d['title'])) for d in documents}
    n = len(by_alias)
    average = sum(w['length'] for _, w, _ in by_alias.values()) / n
    df = Counter(t for _, words, title in by_alias.values() for t in set(words['terms']) | set(title['terms']))
    actual = {r['case_id']: r for r in native['observations']}
    aliases = {v['source_id']: k for k, v in bound.items()}

    def rank(case, parser):
        query = parser(case['prompt'])
        scored = []
        for alias, (document, words, title) in by_alias.items():
            if case['actor'] == 'peer' and document['visibility'] == 'private':
                continue
            codes = set(words['codes']) | set(title['codes'])
            families = set(words['families']) | set(title['families'])
            code_hit = 2 if codes & set(query['codes']) else 1 if families & set(query['codes']) else 0
            terms = set(query['terms']) & (set(words['terms']) | set(title['terms']))
            if not terms and not code_hit:
                continue
            contributions = {}
            for term in sorted(terms):
                tf = words['counts'].get(term, 0) + 2.5 * title['counts'].get(term, 0)
                contributions[term] = math.log(1 + (n - df[term] + .5) / (df[term] + .5)) * tf * 2.2 / (tf + 1.2 * (.25 + .75 * words['length'] / average))
            scored.append({'alias': alias, 'score_without_freshness': sum(contributions.values()),
                           'contributions': contributions, 'code_hit': code_hit,
                           'source_id': bound[alias]['source_id'], 'source_type': 'artifact'})
        return sorted(scored, key=lambda row: (-row['code_hit'], -row['score_without_freshness'], row['source_id']))

    baseline_observations, draft_observations, cases = [], [], []
    for case in questions['questions']:
        if case['evaluation'] != 'retrieval':
            continue
        before, after = rank(case, analyze), rank(case, query_analyze)
        for rows, out in [(before, baseline_observations), (after, draft_observations)]:
            out.append({'case_id': case['id'], 'items': [{'source_type': 'artifact', 'source_id': r['source_id']} for r in rows[:10]], 'pure_simulation': True})
        expected = set(case['expected_sources'])
        original = [aliases[r['source_id']] for r in actual[case['id']]['items']]
        cases.append({'case_id': case['id'], 'actor': case['actor'],
                      'expected_sources': case['expected_sources'],
                      'native_top10': original, 'pure_original_top10': [r['alias'] for r in before[:10]],
                      'baseline_top10_exactly_reproduced': original == [r['alias'] for r in before[:10]],
                      'draft_top10': [r['alias'] for r in after[:10]],
                      'before_expected_ranks': {r['alias']: i for i, r in enumerate(before, 1) if r['alias'] in expected},
                      'after_expected_ranks': {r['alias']: i for i, r in enumerate(after, 1) if r['alias'] in expected},
                      'newly_removed': sorted(set(analyze(case['prompt'])['terms']) & FUNCTION_WORDS),
                      **({'before_all_candidates': before, 'after_all_candidates': after} if case['id'] == 'QUA-04' else {})})
    spec = importlib.util.spec_from_file_location('metrics', ROOT / 'pdos-next/tools/xiaopai_recall_metrics.py')
    metric = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metric)
    for text in ['FA-2026-029', 'TR-A7-2026-006', 'CAPA-2026-018', 'RFQ-2026-118',
                 'ENG-PRV-2026-009', 'IPX7', 'D16-01', 'GB/T 4706.1', 'IEC 60529']:
        old, new = analyze('请先把这份' + text + '查对'), query_analyze('请先把这份' + text + '查对')
        assert old['codes'] == new['codes'] and old['families'] == new['families']
    technical = '料 孔 测 裂纹 含水率 未超上限 非最终根因 无裂纹 没有验证 不能放行 对照 对接 按键 先进工艺 把手 再生料'
    assert not set(analyze(technical)['terms']) & FUNCTION_WORDS
    assert query_analyze(technical)['terms'] == analyze(technical)['terms']
    assert query_analyze('先把这个对')['terms'] == []
    assert query_analyze('先把这个CAPA-2026-018对')['codes'] == ['CAPA-2026-018']
    original_body = {k: copy.deepcopy(w) for k, (_, w, _) in by_alias.items()}
    for alias, (d, _, _) in by_alias.items():
        assert analyze(d['body']) == original_body[alias]
    result = {'version': 'qua04-query-only-pure-diagnostic/v1', 'no_database_or_provider': True,
              'method': 'Python transcription of production BM25; one unchanged chunk per frozen source; same tenant DF including private sources; peer private exclusion mirrors this fixture only; freshness omitted, not PG/ACL proof',
              'policy': POLICY, 'function_words': sorted(FUNCTION_WORDS),
              'input_sha256': {f: hashlib.sha256((dataset / f).read_bytes()).hexdigest() for f in ['corpus.json','questions.json']},
              'native_baseline_top10_reproduced': sum(c['baseline_top10_exactly_reproduced'] for c in cases),
              'native_baseline_cases': len(cases),
              'original_metrics': metric.score(questions, bound, baseline_observations),
              'draft_metrics': metric.score(questions, bound, draft_observations),
              'checks': {'identifier_controls': 9, 'technical_terms_unchanged': True, 'all_function_word_query_empty_no_fallback': True, 'all_24_document_analyses_unchanged': True},
              'cases': cases}
    (OUTPUT / ('comparison.json' if variant == 'basic' else 'comparison-with-negative-copula.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('output', OUTPUT)
    print('native order reproduced', result['native_baseline_top10_reproduced'], '/', len(cases))
    for key in ['original_metrics','draft_metrics']:
        print(key, json.dumps(result[key]['retrieval'], ensure_ascii=False))
    for c in cases:
        if c['case_id'] == 'QUA-04':
            print('QUA-04',json.dumps({k:v for k,v in c.items() if not k.endswith('candidates')},ensure_ascii=False))
    changed = [c['case_id'] for c in cases if c['before_expected_ranks'] != c['after_expected_ranks']]
    print('expected rank changes', changed)


if __name__ == '__main__':
    main()
