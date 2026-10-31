import hashlib,json,statistics,sys
from pathlib import Path
folder=Path(sys.argv[1])
raw=folder/'ann-quality-diagnostic-n32768.json'
d=json.loads(raw.read_text())
assert d['status']=='diagnostic_control_checks_passed'
assert d['cleanup']['status']=='native_t1_disabled' and d['cleanup']['remaining_profile_vectors']==0
observer=json.loads((folder/'observer-state.json').read_text())
assert observer['restored'] and observer['role_settings_match_baseline'] and observer['duration_privilege_matches_baseline']
def walk(plan):
 node=plan.get('Plan',plan)
 yield node
 for child in node.get('Plans',[]):yield from walk(child)
rows=[];captures=[]
for phase in d['phases']:
 for query in phase['queries']:
  captures.append(query['exact'])
  for item in query['configurations']:
   evidence=item['production_read'];captures.append(evidence)
   assert evidence['actual_plan_capture']['status']=='same_execution_matched'
   assert not evidence['prepared_statement_counts']['matching_statements']
   assert evidence['settings']['hnsw.iterative_scan']==item['mode']
   assert evidence['settings']['hnsw.ef_search']==str(item['ef_search'])
   physical=any(n.get('Index Name')=='ix_enterprise_embedding_hnsw_384' and n.get('Actual Loops',0)>0 for n in walk(evidence['executions'][-1]['plan']))
   assert item['ann_recall_attributed']==evidence['hnsw_exercised']==physical
   recall={}
   for comparison in item['comparisons']:
    expected=comparison['exact_source_ids'];found=comparison['iterative_source_ids']
    k=comparison['k']
    assert expected==query['exact']['executions'][-1]['source_ids'][:k]
    assert found==evidence['executions'][-1]['source_ids'][:k]
    value=len(set(expected)&set(found))/len(expected)
    assert abs(value-comparison['same_filtered_set_recall'])<1e-12
    recall[comparison['k']]=value
   rows.append({'phase':phase['phase'],'query':query['query_number'],'configuration':item['configuration'],'hnsw':item['ann_recall_attributed'],'recall5':recall[5],'recall10':recall[10],'elapsed_ms':evidence['strategy_elapsed_ms'],'exact_elapsed_ms':query['exact']['strategy_elapsed_ms'],'shortfall':evidence['scan_evidence']['shortfall'],'pools':[a['pool_limit'] for a in evidence['executions']],'distance_monotonic':item['distances']['nondecreasing_with_tolerance_1e_7']})
assert len(rows)==48 and len(d['phases'])==3
ab=[]
for entry in d['materialization_ab']:
 assert entry['same_authority_and_ordered_source_chunk_results']
 variants={v['materialized']:v for v in entry['variants']}
 captures.extend(v['production_read'] for v in entry['variants'])
 ab.append({'actor':entry['actor_id'],'ordered_variant_materialized':entry['order'],'same_authority_and_ordered_results':True,'inline_ms':variants[False]['production_read']['strategy_elapsed_ms'],'materialized_ms':variants[True]['production_read']['strategy_elapsed_ms'],'hotspots':{str(k):v['hotspots'] for k,v in variants.items()}})
assert len(captures)==64 and all(c['actual_plan_capture']['status']=='same_execution_matched' for c in captures)
summary={}
for label in [x['configuration'] for x in d['phases'][0]['queries'][0]['configurations']]:
 selected=[r for r in rows if r['configuration']==label];ann=[r for r in selected if r['hnsw']]
 summary[label]={'controls':len(selected),'final_hnsw':len(ann),'all_final_macro_recall5':statistics.mean(r['recall5'] for r in selected),'all_final_macro_recall10':statistics.mean(r['recall10'] for r in selected),'actual_final_hnsw_macro_recall5':statistics.mean(r['recall5'] for r in ann) if ann else None,'actual_final_hnsw_macro_recall10':statistics.mean(r['recall10'] for r in ann) if ann else None,'median_elapsed_ms':statistics.median(r['elapsed_ms'] for r in selected),'median_exact_elapsed_ms':statistics.median(r['exact_elapsed_ms'] for r in selected),'source_shortfalls':sum(r['shortfall'] for r in selected),'all_returned_distances_nondecreasing':all(r['distance_monotonic'] for r in selected)}
stage_rows=[]
for phase in d['phases']:
 for query in phase['queries']:
  baseline=query['exact']['executions'][-1]['source_ids']
  for item in query['configurations']:
   for stage in item['production_read']['executions']:
    physical=any(n.get('Index Name')=='ix_enterprise_embedding_hnsw_384' and n.get('Actual Loops',0)>0 for n in walk(stage['plan']))
    stage_rows.append({'phase':phase['phase'],'query':query['query_number'],'configuration':item['configuration'],'pool_limit':stage['pool_limit'],'physical_hnsw':physical,'source_count':len(stage['source_ids']),'recall5':len(set(baseline[:5])&set(stage['source_ids'][:5]))/len(baseline[:5]),'recall10':len(set(baseline[:10])&set(stage['source_ids'][:10]))/len(baseline[:10])})
result={'stages':stage_rows,'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'same_select_captures':len(captures),'same_select_nearest_plans':sum(len(c['executions']) for c in captures),'materialization_ab':ab,'configurations':summary,'rows':rows,'observer_restored':True,'profile_vectors_remaining':0,'real_model_calls':0,'real_embedding_calls':0,'default':'keyword','production_p95_measured':False,'synthetic_geometry_not_semantic_quality':True}
target=folder/'independent-summary.json'
with target.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({'configurations':summary,'ab':[dict((k,v) for k,v in r.items() if k!='hotspots') for r in ab],'same_select_captures':len(captures)},indent=2))
