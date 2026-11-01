"""Resumeable real-provider evaluation against an explicitly verified local target."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

import local_environment as local
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall, TenantAdministrator
from pdos_next.database import engine_for
from pdos_next.models import Grant, LoginSession, Principal
from pdos_next.service import Context, digest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/reports/evidence/pdos-next-real-eval-20261101/live'
PRIVATE = ROOT / 'pdos-next/.local/real-eval-20261101'
TENANT = UUID('78340ac0-57c2-4235-87c6-a468dd3d8173')


def checked_environment():
    local.STATE = ROOT / 'pdos-next/.local/comprehensive-runtime-20261022.json'
    state = local.verified(local.read_state())
    assert state['marker'] == 'c351c0ca-b874-49b9-bf1b-44c3ad150aaf'
    os.environ.update(local.environment(state))
    os.environ['PDOS_TENANT_RUNTIME_CONFIG'] = str(ROOT / 'pdos-next/.local/comprehensive-minimax-20261023.json')
    return state


def save_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    path.chmod(0o600)


def response_json(response, expected=200):
    if response.status_code != expected:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:1500]}')
    return response.json()


def save_command(person, operation, payload, *, revision=1):
    command = {'command_id':str(uuid4()), 'idempotency_key':str(uuid4()),
               'category_id':str(person.category), 'product_id':None,
               'expected_revision':revision, 'source_read_set':[],
               'operation':operation, 'payload':payload}
    path = f'/v1/categories/{person.category}/commands'
    preview = response_json(person.client.post(path+'/preview',headers=person.headers,json=command))
    receipt = response_json(person.client.post(path,headers=person.headers,json=preview['command']))
    return receipt


def person_from(value, state):
    runtime = json.loads((EVIDENCE/'runtime.json').read_text())
    client = httpx.Client(base_url=runtime['api_base'], timeout=60)
    tokens = {UUID(key):token for key,token in value['tokens'].items()}
    ids = {key:UUID(value[key]) for key in ('tenant','human','peer','agent','category','product')}
    return SimpleNamespace(**ids, tokens=tokens, headers={'Authorization':'Bearer '+tokens[ids['human']]},
        ctx=Context(ids['tenant'],ids['human'],ids['human'],category_id=ids['category']),
        admin=engine_for(state['admin_url']), engine=engine_for(state['app_url']),
        auth=engine_for(state['auth_url']),client=client)


def new_person(label, state=None):
    state = state or checked_environment()
    path = PRIVATE / ('person-'+label+'.json')
    if path.exists():
        return person_from(json.loads(path.read_text()),state)
    runtime = json.loads((EVIDENCE/'runtime.json').read_text())
    admin = engine_for(state['admin_url'])
    tokens = {}
    human,peer = uuid4(),uuid4()
    with Session(admin) as session,session.begin():
        agents = list(session.scalars(select(Principal.id).where(
            Principal.tenant_id==TENANT,Principal.kind=='agent',Principal.active.is_(True))))
        assert len(agents)==1
        agent=agents[0]
        for identity,suffix in ((human,'owner'),(peer,'peer')):
            token=secrets.token_urlsafe(32);tokens[str(identity)]=token
            session.add(Principal(id=identity,tenant_id=TENANT,name=f'RealEval-{label}-{suffix}',kind='human'))
            session.flush()
            session.add(LoginSession(token_hash=digest(token),tenant_id=TENANT,principal_id=identity,
                                     expires_at=datetime.now(UTC)+timedelta(days=7)))
            session.add(TenantAdministrator(tenant_id=TENANT,principal_id=identity,active=True))
    client=httpx.Client(base_url=runtime['api_base'],timeout=60)
    headers={'Authorization':'Bearer '+tokens[str(human)]}
    body={'key':'real-eval-'+label.lower().replace('_','-')+'-'+uuid4().hex[:8],
          'name':'真实模型合成评测 '+label, 'purpose':'现有52题合成资料隔离验证，不代表真实业务或模型资格。',
          'deidentified_confirmed':True,'idempotency_key':str(uuid4())}
    preview=response_json(client.post('/v1/categories/preview',headers=headers,json=body))
    body['confirmation_token']=preview['confirmation_token']
    receipt=response_json(client.post('/v1/categories',headers=headers,json=body),201)
    category=receipt['subject_id']
    # Test-identity bootstrap only, as in the existing isolated native fixtures.
    # Business materials/actions below still use their normal Human commands.
    with Session(admin) as session, session.begin():
        owner_grant=session.scalar(select(Grant).where(Grant.category_id==UUID(category),
                                                       Grant.principal_id==human))
        owner_grant.product_manager=True
        for identity in (peer,agent):
            session.add(Grant(tenant_id=TENANT,category_id=UUID(category),principal_id=identity,
                              can_write=True,product_manager=identity==peer))
    product=response_json(client.post(f'/v1/categories/{category}/products',headers=headers,json={
        'name':'评测合成产品 '+label,'purpose':'仅用作原生事实与来源绑定，不授予量产或业务资格。',
        'idempotency_key':str(uuid4())}),201)['subject_id']
    value={'tenant':str(TENANT),'human':str(human),'peer':str(peer),'agent':str(agent),
           'category':category,'product':product,'tokens':tokens}
    save_private(path,value)
    person=person_from(value,state)
    for identity in (person.human,person.peer):
        own=SimpleNamespace(**vars(person));own.human=identity
        own.headers={'Authorization':'Bearer '+person.tokens[identity]}
        reading=response_json(client.get(f'/v1/categories/{category}/agent-budgets',headers=own.headers))
        save_command(own,'ai.budget.configure',{'action':'allocate','expected_active_digest':reading['active_digest'],
            'limits':{'limit_micro_usd':100_000_000,'input_token_limit':1_000_000_000,
                      'output_token_limit':1_000_000_000,'call_limit':2000}},revision=reading['category_revision'])
    client.close();admin.dispose()
    return person


def set_focus(person, focus):
    path=f'/v1/categories/{person.category}/model-configuration'
    reading=response_json(person.client.get(path,headers=person.headers))
    current=reading['configuration']
    original=PRIVATE/'original-model-configuration.json'
    if not original.exists():save_private(original,current)
    metadata=current['metadata'].copy()
    metadata['context_window_tokens']=524_288+4000+focus
    receipt=save_command(person,'model.configuration.save',{'expected_revision':current['revision'],
        'metadata':metadata,'enabled':True},revision=reading['category_revision'])
    result=response_json(person.client.get(path,headers=person.headers))
    (EVIDENCE/f'model-configuration-F{focus}.json').write_text(json.dumps({
        'reading':result,'receipt_id':receipt['id'],'focus':focus,
        'provider_output_limit':524288,'at_utc':datetime.now(UTC).isoformat()},ensure_ascii=False,indent=2)+'\n')
    print('focus configured',focus,'revision',result['configuration']['revision'],flush=True)


def run_request(person, case_id, payload, *, label=None, timeout=600):
    folder=EVIDENCE/'runs';folder.mkdir(exist_ok=True)
    filename=folder/((label or case_id)+'.json')
    if filename.exists():return json.loads(filename.read_text())
    payload={**payload,'idempotency_key':payload.get('idempotency_key') or str(uuid4())}
    private_path=PRIVATE/('intent-'+(label or case_id)+'.json')
    if private_path.exists():payload=json.loads(private_path.read_text())
    else:save_private(private_path,payload)
    path=f'/v1/categories/{person.category}/agent-runs'
    started=time.monotonic()
    accepted=response_json(person.client.post(path,headers=person.headers,json=payload),202)
    first_visible=None
    while True:
        view=response_json(person.client.get(path+'/'+accepted['run_id'],headers=person.headers))
        state=view['status']
        if first_visible is None:
            events=response_json(person.client.get(path+'/'+accepted['run_id']+'/events',headers=person.headers))
            if any(row['event'].get('type') in {'model_delta','model_text','text_delta'} for row in events.get('items',[])):
                first_visible=(time.monotonic()-started)*1000
        if state in {'completed','partial','failed','cancelled','waiting_input','needs_reconciliation'}:
            break
        if time.monotonic()-started>timeout:
            state='observation_timeout'
            break
        time.sleep(.5)
    result={'case_id':case_id,'label':label or case_id,'id':accepted['run_id'],
            'run_id':accepted['run_id'],'session_id':accepted['session_id'],
            'status':state,'state':state,'category_id':str(person.category),
            'product_id':payload.get('product_id'),'project_id':payload.get('project_id'),
            'continued_from_id':payload.get('continue_from_run_id'),
            'elapsed_ms':(time.monotonic()-started)*1000,'first_visible_ms':first_visible,
            'request':payload,'view':view,'output':view.get('result'),
            'observed_at':datetime.now(UTC).isoformat()}
    filename.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({'case':case_id,'label':label or case_id,'run_id':accepted['run_id'],
                      'status':state,'elapsed_ms':round(result['elapsed_ms'])}),flush=True)
    return result


def capture_run(person, result):
    """Export actual scoped ledgers after execution; never manufactures a READ."""
    run_id=UUID(result['run_id'])
    fields=('id','run_id','tool','state','error_code','created_at','execution_binding','result',
            'reserved_tokens','charged_tokens','provider_request_id','actual_input_tokens',
            'actual_output_tokens','cost_state','cost_reserved_micro_usd',
            'cost_charged_micro_usd','cost_pricing')
    with Session(person.admin) as session:
        row=session.get(AgentRun,run_id)
        assert row.tenant_id==person.tenant and row.requester_id==person.human
        calls=list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id==run_id).order_by(AgentToolCall.created_at)))
        events=list(session.scalars(select(AgentEvent).where(
            AgentEvent.run_id==run_id).order_by(AgentEvent.sequence)))
        result['output']=row.result
        result['versions']=row.versions
        result['tool_calls']=[{key:getattr(call,key) for key in fields} for call in calls]
        result['events']=[{'id':event.id,'run_id':event.run_id,'created_at':event.created_at,
                           'sequence':event.sequence,'body':event.body} for event in events]
        result['held_tokens']=row.held_tokens
        result['used_tokens']=row.used_tokens
    observations=EVIDENCE/'provider-observations.jsonl'
    samples=[json.loads(line) for line in observations.read_text().splitlines()] if observations.exists() else []
    by_request={sample.get('request_id'):sample for sample in samples
                if sample.get('run_id')==str(run_id) and sample.get('request_id')}
    for call in result['tool_calls']:
        sample=by_request.get(call['provider_request_id'])
        if sample:
            call.update(elapsed_ms=sample['elapsed_ms'],protocol=sample['protocol'])
            if 'raw_usage' in sample:call['raw_usage']=sample['raw_usage']
            call['provider_observation']=sample
    issued=[]
    def collect(value):
        if isinstance(value,dict):
            if value.get('citation_id') and value.get('source_id'):
                issued.append(value)
            for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    for call in result['tool_calls']:
        if call['tool']!='model' and call['state']=='completed':collect(call['result'])
    result['issued_citations']=issued
    result['read_source_ids']=sorted({item['source_id'] for item in issued})
    result['carried_source_ids']=result['read_source_ids'][:]
    assistant=((result.get('output') or {}).get('result') or {}).get('assistant') or {}
    result['citation_source_ids']=sorted({item['source_id'] for item in assistant.get('sources',[])
                                         if item.get('source_id')})
    response=person.client.get(f'/v1/categories/{person.category}/agent-runs/{run_id}/candidates',
                               headers=person.headers)
    result['candidates']=response.json().get('items',[]) if response.status_code==200 else []
    path=EVIDENCE/'runs'/((result['label'])+'.json')
    serial=json.loads(json.dumps(result,ensure_ascii=False,default=str))
    path.write_text(json.dumps(serial,ensure_ascii=False,indent=2)+'\n')
    return serial


def actor_person(person,actor):
    selected=copy(person)
    selected.human=person.peer if actor=='peer' else person.human
    selected.headers={'Authorization':'Bearer '+person.tokens[selected.human]}
    selected.ctx=Context(person.tenant,selected.human,selected.human,category_id=person.category)
    return selected


def run_rag_ready(state, *, only=None):
    import xiaopai_real_rag_fixtures as rag

    person=new_person('rag40',state)
    bound=json.loads((EVIDENCE/'bound-rag-sources.json').read_text())
    specs=rag.build_run_specs(person.category,namespace='real-eval-rag40-F64000-v1')['cases']
    specs=[spec for spec in specs if spec['status']=='ready' and (not only or spec['case_id'] in only)]
    def one(spec):
        own=actor_person(person,spec['actor'])
        result=run_request(own,spec['case_id'],spec['request']['json'],label='rag-'+spec['case_id'])
        result.update(suite='rag40',role=spec['role'],slice=spec['slice'],focus=64000,
                      native_binding_status='bound',case_sha256=spec['case_sha256'],
                      expected_sha256=spec['expected_sha256'])
        return capture_run(own,result)
    results=[]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures={executor.submit(one,spec):spec for spec in specs}
        for future in as_completed(futures):
            results.append(future.result())
    (EVIDENCE/'rag-ready-mechanical-scores.json').write_text(json.dumps(
        rag.score_observations(bound['bound_sources'],results),ensure_ascii=False,indent=2)+'\n')
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['bootstrap','smoke','seed-rag','rag-ready'])
    parser.add_argument('--only',nargs='*')
    args=parser.parse_args()
    state=checked_environment()
    if args.action=='rag-ready':
        run_rag_ready(state,only=set(args.only) if args.only else None)
        return
    if args.action=='seed-rag':
        import xiaopai_real_rag_fixtures as rag
        person=new_person('rag40',state)
        output=EVIDENCE/'bound-rag-sources.json'
        if not output.exists():
            bound=rag.seed_corpus(person)
            output.write_text(json.dumps(bound,ensure_ascii=False,indent=2)+'\n')
        print('RAG corpus prepared',str(output),flush=True)
        return
    person=new_person('control',state)
    if args.action=='bootstrap':set_focus(person,64000)
    else:
        import xiaopai_real_rag_fixtures as rag
        specs=rag.build_run_specs(person.category,namespace='real-eval-smoke-20261101')['cases']
        spec=next(item for item in specs if item['case_id']=='ENG-07')
        run_request(person,spec['case_id'],spec['request']['json'],label='smoke-ENG-07')


if __name__=='__main__':main()
