from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,re,hashlib,sys
root=Path(__file__).resolve().parents[4];sys.path.insert(0,str(root/'pdos-next/server'))
from pdos_next.agent_kernel.context_budget import estimate_tokens,budget_for
p=root/'docs/evaluations/xiaopai-v0/context-questions.json';data=json.loads(p.read_text());assert len(data['cases'])==data['case_count']==12
profiles=data['budget_basis']['profiles'];budgets=[x['f_budget_tokens'] for x in profiles]
for v in profiles:assert budget_for(SimpleNamespace(context_window_tokens=v['context_window_tokens'],max_output_tokens=data['budget_basis']['max_output_tokens']))['focus']==v['f_budget_tokens']
def save(path,body):
 if path.exists():assert path.read_text()==body, 'Existing frozen output differs: '+str(path)
 else:path.write_text(body)
rows=[];materialized={}
for case in data['cases']:
 assert case['f_budget_tokens']==budgets and case['expected_behavior'] and case['forbidden_behavior']
 turns=deepcopy(case['turns']);assert all(t['role'] in ['user','assistant','tool'] and isinstance(t['content'],str) and t['content'] for t in turns)
 anchors=0
 for item in case['facts']+case['constraints']:
  for a in item['review_anchors']:
   if a=='final_prompt':assert case['final_prompt']
   else:
    match=re.fullmatch(r'turns\[(\d+)\]',a);assert match and int(match.group(1))<len(turns),(case['id'],a)
   anchors+=1
 recipe=case.get('replay_input')
 if recipe:
  assert recipe['version']=='inline-context-pressure/v1' and recipe['repeat_each_record']==1
  rule=recipe['expansion_rule'];assert rule['operation']=='append_to_existing_turn_content'
  records={x['record_id']:x for x in recipe['records']};assert len(records)==len(recipe['records'])==len(recipe['record_order']) and set(records)==set(recipe['record_order'])
  for identity in recipe['record_order']:
   record=records[identity];at=record[rule['target_index_field']];assert 0<=at<len(turns)
   turns[at]['content']+=rule['prefix']+rule['line_joiner'].join(record['lines'])+rule['suffix']
 turns.append({'role':'user','content':case['final_prompt']})
 body=json.dumps(turns,ensure_ascii=False,sort_keys=True,separators=(',',':'));summary={'case_id':case['id'],'turns_with_final':len(turns),'anchors_checked':anchors,'characters':len(body),'utf8_bytes':len(body.encode()),'estimated_tokens':estimate_tokens(body),'sha256':hashlib.sha256(body.encode()).hexdigest()}
 if recipe:
  expected=recipe['input_measurement'];assert summary['sha256']==expected['sha256'] and summary['characters']==expected['characters'] and summary['utf8_bytes']==expected['utf8_bytes'] and summary['estimated_tokens']==expected['current_estimator_tokens']
 rows.append(summary);materialized[case['id']]=turns
out=root/'docs/reports/evidence/pdos-next-eval-v0-20261029';save(out/'context-input-validation-v2.json',json.dumps({'context_questions_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'cases':12,'budgets':budgets,'formula_checked_against_current_code':True,'raw_inputs_reproduced':True,'real_model_calls':0,'answer_quality':'not_run','per_case':rows},ensure_ascii=False,indent=2)+'\n');save(out/'context-expanded-inputs.json',json.dumps(materialized,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'cases':len(rows),'anchors':sum(x['anchors_checked'] for x in rows),'long_cases':[x for x in rows if x['case_id'] in ['CTX-01','CTX-12']]}))
