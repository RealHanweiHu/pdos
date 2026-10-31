"""Write an unapplied two-file patch; compile and verify the drafted query-only helper."""
from pathlib import Path
import difflib
import hashlib
import json
import sys
import types

ROOT = Path('/Users/huhanwei/Desktop/ai-native-R&D-platform')
SERVER = ROOT / 'pdos-next/server'
sys.path.insert(0,str(SERVER))
from pdos_next.enterprise_search import tokenizer as production

DEST = Path('/private/tmp/qua04-query-only-draft')
target = SERVER / 'pdos_next/enterprise_search/tokenizer.py'
old = target.read_text()
new = old.replace('DASHES = ', '''QUERY_RULE = "query-function-words/v1"
QUERY_FUNCTION_WORDS = frozenset(
    "我 我们 你 你们 您 这 这个 这些 那 那个 那些 把 对 按 先 再 别 是不是 不是".split()
)
QUERY_POLICY_VERSION = QUERY_RULE + "/" + hashlib.sha256(
    "\\n".join(sorted(QUERY_FUNCTION_WORDS)).encode()
).hexdigest()
DASHES = ''',1)
new = new.replace('\ndef or_query(terms):', '''
def analyze_query(value):
    """Remove request grammar only; retain raw text, IDs and the index vocabulary."""
    parsed = analyze(value)
    removed = set(parsed["terms"]) & QUERY_FUNCTION_WORDS
    return {
        **parsed,
        "terms": [term for term in parsed["terms"] if term not in QUERY_FUNCTION_WORDS],
        "counts": {
            term: count for term, count in parsed["counts"].items()
            if term not in QUERY_FUNCTION_WORDS
        },
        "length": parsed["length"] - sum(parsed["counts"].get(term, 0) for term in removed),
        "removed": sorted(set(parsed["removed"]) | removed),
        "query_policy_version": QUERY_POLICY_VERSION,
    }


def or_query(terms):''',1)
query = SERVER / 'pdos_next/enterprise_search/query.py'
qold = query.read_text()
qnew = qold.replace(
    'from .tokenizer import CHUNKER, CODE_RULE, RANKING, analyze, or_query, version',
    'from .tokenizer import CHUNKER, CODE_RULE, QUERY_RULE, RANKING, analyze_query, or_query, version')
qnew = qnew.replace('parsed = analyze(data.query)', 'parsed = analyze_query(data.query)')
qnew = qnew.replace('"tokenizer_version",\n                "code_rule_version",',
                    '"tokenizer_version",\n                "code_rule_version",\n                "query_policy_version",')
qnew = qnew.replace('"ranking_version": RANKING + "+review/v1",',
                    '"ranking_version": RANKING + "+review/v1+" + QUERY_RULE,')
patch = ''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/pdos-next/server/pdos_next/enterprise_search/tokenizer.py',tofile='b/pdos-next/server/pdos_next/enterprise_search/tokenizer.py'))
patch += ''.join(difflib.unified_diff(qold.splitlines(True),qnew.splitlines(True),fromfile='a/pdos-next/server/pdos_next/enterprise_search/query.py',tofile='b/pdos-next/server/pdos_next/enterprise_search/query.py'))
(DEST/'query-only-function-words.patch').write_text(patch)
(DEST/'tokenizer-draft.py').write_text(new)
(DEST/'query-draft.py').write_text(qnew)
module=types.ModuleType('query_tokenizer_draft')
# Resource files remain the exact production dictionary/stopword files, in memory only.
module.__file__=str(target)
exec(compile(new,str(DEST/'tokenizer-draft.py'),'exec'),module.__dict__)
compile(qnew,str(DEST/'query-draft.py'),'exec')
corpus=json.loads((ROOT/'docs/evaluations/xiaopai-v0/corpus.json').read_text())['documents']
questions=json.loads((ROOT/'docs/evaluations/xiaopai-v0/questions.json').read_text())['questions']
checks=[]
for document in corpus:
    for key in ['body','title']:
        assert module.analyze(document[key]) == production.analyze(document[key])
checks.append('all 48 unchanged source/title analyses and index tokenizer version')
for case in questions:
    original=case['prompt']; before=production.analyze(original); after=module.analyze_query(original)
    assert original==case['prompt']
    assert before['codes']==after['codes'] and before['families']==after['families']
    assert after['length']==sum(after['counts'].values())
    assert set(after['counts'])==set(after['terms'])
    assert after['tokenizer_version']==before['tokenizer_version']
    assert set(after['terms'])<=set(before['terms'])
    assert set(after['removed'])==set(before['removed'])|(set(before['terms'])&module.QUERY_FUNCTION_WORDS)
    assert module.or_query(after['terms'])==production.or_query(after['terms'])
checks.append('all 40 raw question strings unchanged; codes/families/index version preserved; safe tsquery/counts/removed trace')
technical='料 孔 测 裂纹 含水率 未超上限 非最终根因 无裂纹 没有验证 不能放行 对照 对接 按键 先进工艺 把手 再生料'
assert module.analyze_query(technical)['terms']==production.analyze(technical)['terms']
checks.append('single-character technical words, factual negations and compound words retained')
for code in ['FA-2026-029','TR-A7-2026-006','CAPA-2026-018','RFQ-2026-118','ENG-PRV-2026-009','IPX7','D16-01','GB/T 4706.1','IEC 60529']:
    text='请先把这个'+code+'对'
    assert module.analyze_query(text)['codes']==production.analyze(text)['codes']
checks.append('9 exact identifier controls unchanged')
assert module.analyze_query('先把这个对')['terms']==[]
assert module.analyze_query('先把这个CAPA-2026-018对')['codes']==['CAPA-2026-018']
assert '不是' in module.analyze_query('不是裂纹')['removed']
assert '裂纹' in module.analyze_query('不是裂纹')['terms']
checks.append('all-function query stays empty with no noise fallback; exact-code-only channel survives; copula removal explicit')
manifest={'version':'query-only-draft-validation/v1','applied':False,'database_connections':0,'real_model_calls':0,'real_embedding_calls':0,'checks':checks,'query_policy_version':module.QUERY_POLICY_VERSION,'repository_read_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [target,query,ROOT/'docs/evaluations/xiaopai-v0/corpus.json',ROOT/'docs/evaluations/xiaopai-v0/questions.json']},'draft_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in [DEST/'query-only-function-words.patch',DEST/'tokenizer-draft.py',DEST/'query-draft.py']}}
(DEST/'validation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
