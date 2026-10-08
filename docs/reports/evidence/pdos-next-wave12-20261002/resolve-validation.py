"""Preserve initial failures and record a narrow, test-only resolution."""
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPORT = Path(__file__).resolve().parent
ROOT = REPORT.parents[3]
sys.path.insert(0, str(ROOT / 'pdos-next/tools'))
from local_environment import environment, read_state, verified

def load(name):
    return json.loads((REPORT / name).read_text())

def save(name, value):
    with (REPORT / name).open('x') as output:
        output.write(json.dumps(value, indent=2) + '\n')

initial = load('joint-result.json')
assert [key for key, group in initial['groups'].items() if group['exit_code']] == ['verification_handoff-3']
repair = load('test-only-repair.json')
assert repair['exit_code'] == 0 and repair['runtime_source_changed'] is False
assert re.search(r'\b1 passed\b', (REPORT / repair['log']).read_text())
candidate, before = load('candidate.json'), load('candidate-before-test-only-repair.json')
assert [path for path in before if candidate[path] != before[path]] == [repair['path']]
assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha for path, sha in candidate.items())
processes = subprocess.check_output(['ps', '-axo', 'pid,command'], text=True)
assert not any('-m pytest' in line and 'pdos-next' in line for line in processes.splitlines()), 'Tests must be quiescent before isolated checks'
state = verified(read_state())
selection = load('joint-shards.json')['lifecycle-isolated']
started = time.monotonic()
with (REPORT / 'lifecycle-isolated-recheck.log').open('x') as output:
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', *selection], cwd=ROOT / 'pdos-next/server', env=environment(state), stdout=output, stderr=subprocess.STDOUT)
count = re.search(r'(\d+) passed', (REPORT / 'lifecycle-isolated-recheck.log').read_text())
structural = {'exit_code': result.returncode, 'elapsed_seconds': round(time.monotonic() - started, 2), 'passed': int(count[1]) if count else 0, 'selection': selection, 'log': 'lifecycle-isolated-recheck.log', 'other_test_processes_at_start': 0, 'reason': 'Repeat in isolation after the targeted test-only recheck overlapped the end of the initial structural group.'}
save('lifecycle-isolated-recheck.json', structural)
assert result.returncode == 0 and structural['passed'] == initial['groups']['lifecycle-isolated']['passed']
save('joint-initial-result.json', initial)
resolved = {'result': 'passed_after_test_only_repair', 'initial_result': 'joint-result.json', 'initial_passed': initial['total_passed'], 'initial_failed': 1, 'initial_failed_group': 'verification_handoff-3', 'total_passed': initial['total_passed'] + 1, 'elapsed_seconds': initial['elapsed_seconds'], 'elapsed_seconds_scope': 'initial joint run only; recheck times recorded separately', 'test_only_recheck': repair, 'structural_recheck': structural, 'structural_tests_isolated': True, 'runtime_source_changed_after_initial_candidate': False, 'duplicate_rechecks_not_counted': True, 'candidate_manifest': 'candidate.json', 'initial_candidate_manifest': 'candidate-before-test-only-repair.json'}
save('joint-resolved-result.json', resolved)
delta = load('final-candidate-delta.json')
delta['validation'] = 'Initial joint result preserved: 1483 passed and one expected-code assertion failed. Runtime unchanged; the repaired test passed individually, followed by 24 structural checks in isolation. Final selection has 1484 passing cases; repeated structural cases are not double counted.'
delta['resolved_result'] = 'joint-resolved-result.json'
(REPORT / 'final-candidate-delta.json').write_text(json.dumps(delta, indent=2) + '\n')
print(json.dumps({'result': resolved['result'], 'selected_cases_passed': resolved['total_passed'], 'structural_recheck': structural['passed']}))
