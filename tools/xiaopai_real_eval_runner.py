"""Resumeable real-provider evaluation against an explicitly verified local target."""

import argparse
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import local_environment as local
from pdos_next.agent.kernel.models import AgentEvent, AgentRun, AgentToolCall, TenantAdministrator
from pdos_next.core.database import engine_for
from pdos_next.core.models import Grant, LoginSession, Principal
from pdos_next.core.service import Context, digest
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
# A later regression writes to its own folders, so W1's committed evidence is never overwritten.
EVIDENCE = Path(os.environ.get(
    'REAL_EVAL_EVIDENCE', ROOT / 'docs/reports/evidence/pdos-next-real-eval-20261101/live'))
# Which evaluation runtime's API to call; defaults to runtime A.
RUNTIME = Path(os.environ.get('REAL_EVAL_RUNTIME', EVIDENCE / 'runtime.json'))
PRIVATE = Path(os.environ.get('REAL_EVAL_PRIVATE', ROOT / '.local/real-eval-20261101'))
PROVIDER_OUTPUT_LIMIT = 524_288


def context_reserve():
    """R the server actually holds back: the capped output budget plus the tool-result reserve.

    Since D252 bootstrap.route() requests at most OUTPUT_BUDGET, so F = window - R uses that
    cap rather than the provider's 524288 limit.
    """
    from pdos_next.agent.kernel.context_budget import OUTPUT_BUDGET, TOOL_RESULT_RESERVE

    return min(PROVIDER_OUTPUT_LIMIT, OUTPUT_BUDGET) + TOOL_RESULT_RESERVE
TENANT = UUID('78340ac0-57c2-4235-87c6-a468dd3d8173')


def checked_environment():
    local.STATE = ROOT / '.local/comprehensive-runtime-20261022.json'
    state = local.verified(local.read_state())
    assert state['marker'] == 'c351c0ca-b874-49b9-bf1b-44c3ad150aaf'
    os.environ.update(local.environment(state))
    os.environ['PDOS_TENANT_RUNTIME_CONFIG'] = str(ROOT / '.local/comprehensive-minimax-20261023.json')
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
    runtime = json.loads(RUNTIME.read_text())
    client = httpx.Client(base_url=runtime['api_base'], timeout=180)
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
    runtime = json.loads(RUNTIME.read_text())
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
    client=httpx.Client(base_url=runtime['api_base'],timeout=180)
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


def restore_configuration(person):
    """Put back the pre-evaluation context window (the only field set_focus changed)."""
    path=f'/v1/categories/{person.category}/model-configuration'
    reading=response_json(person.client.get(path,headers=person.headers))
    current=reading['configuration']
    original=json.loads((PRIVATE/'original-model-configuration.json').read_text())
    metadata=current['metadata'].copy()
    metadata['context_window_tokens']=original['metadata']['context_window_tokens']
    receipt=save_command(person,'model.configuration.save',{'expected_revision':current['revision'],
        'metadata':metadata,'enabled':True},revision=reading['category_revision'])
    after=response_json(person.client.get(path,headers=person.headers))['configuration']
    print(json.dumps({'restored_context_window':after['metadata']['context_window_tokens'],
                      'revision':after['revision'],'receipt_id':receipt['id']}),flush=True)


def set_focus(person, focus):
    path=f'/v1/categories/{person.category}/model-configuration'
    reading=response_json(person.client.get(path,headers=person.headers))
    current=reading['configuration']
    original=PRIVATE/'original-model-configuration.json'
    if not original.exists():save_private(original,current)
    metadata=current['metadata'].copy()
    metadata['context_window_tokens']=context_reserve()+focus
    receipt=save_command(person,'model.configuration.save',{'expected_revision':current['revision'],
        'metadata':metadata,'enabled':True},revision=reading['category_revision'])
    result=response_json(person.client.get(path,headers=person.headers))
    (EVIDENCE/f'model-configuration-F{focus}.json').write_text(json.dumps({
        'reading':result,'receipt_id':receipt['id'],'focus':focus,
        'provider_output_limit':PROVIDER_OUTPUT_LIMIT,'context_reserve':context_reserve(),
        'at_utc':datetime.now(UTC).isoformat()},ensure_ascii=False,indent=2)+'\n')
    print('focus configured',focus,'revision',result['configuration']['revision'],flush=True)


def run_request(person, case_id, payload, *, label=None, timeout=1800):
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
    samples=load_observations()
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


def attempt_names(attempt):
    """a1 keeps the original 11-01 file names; later attempts get a fresh category and corpus."""
    if attempt=='a1':
        return SimpleNamespace(person='rag40',bound='bound-rag-sources.json',
                               namespace='real-eval-rag40-F64000-v1',label='rag-',
                               scores='rag-ready-mechanical-scores.json')
    return SimpleNamespace(person='rag40-'+attempt,bound=f'bound-rag-sources-{attempt}.json',
                           namespace=f'real-eval-rag40-F64000-{attempt}',label=f'{attempt}-rag-',
                           scores=f'rag-ready-mechanical-scores-{attempt}.json')


def seed_rag(state, attempt):
    import xiaopai_real_rag_fixtures as rag

    names=attempt_names(attempt)
    person=new_person(names.person,state)
    output=EVIDENCE/names.bound
    if not output.exists():
        bound=rag.seed_corpus(person)
        output.write_text(json.dumps(bound,ensure_ascii=False,indent=2)+'\n')
    print('RAG corpus prepared',str(output),flush=True)
    return person


def run_rag_ready(state, *, only=None, attempt='a1', workers=2):
    import xiaopai_real_rag_fixtures as rag

    names=attempt_names(attempt)
    person=new_person(names.person,state)
    bound=json.loads((EVIDENCE/names.bound).read_text())
    assert bound['category_id']==str(person.category)
    specs=rag.build_run_specs(person.category,namespace=names.namespace)['cases']
    specs=[spec for spec in specs if spec['status']=='ready' and (not only or spec['case_id'] in only)]
    def one(spec):
        own=actor_person(person,spec['actor'])
        result=run_request(own,spec['case_id'],spec['request']['json'],label=names.label+spec['case_id'])
        result.update(suite='rag40',attempt=attempt,role=spec['role'],slice=spec['slice'],focus=64000,
                      native_binding_status='bound',case_sha256=spec['case_sha256'],
                      expected_sha256=spec['expected_sha256'])
        return capture_run(own,result)
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures={executor.submit(one,spec):spec for spec in specs}
        for future in as_completed(futures):
            results.append(future.result())
    if not only:
        (EVIDENCE/names.scores).write_text(json.dumps(
            rag.score_observations(bound['bound_sources'],results),ensure_ascii=False,indent=2)+'\n')
    return results


def run_rag_native(state, *, attempt, workers=2):
    """Eight dependent cases: native Human fixtures, in-project parents, then actual citations.

    Resumes from the saved setup record: finished Runs come from their run files, and the
    native projects are not created again. A request the server refuses is recorded.
    """
    from contextlib import nullcontext
    from uuid import NAMESPACE_URL, uuid5

    import xiaopai_real_rag_fixtures as rag

    names=attempt_names(attempt)
    person=new_person(names.person,state)
    bound=json.loads((EVIDENCE/names.bound).read_text())
    assert bound['category_id']==str(person.category)
    questions,_,_=rag.frozen_inputs()
    cases={case['id']:case for case in questions['questions']}
    record_path=EVIDENCE/f'rag-native-{attempt}.json'
    saved=json.loads(record_path.read_text()) if record_path.exists() else None
    record=saved or {'attempt':attempt,'category_id':str(person.category),'blocked':{},
                     'parents':{}}
    record.setdefault('refused',{})
    def execute(actor,case_id,payload,label,spec_case):
        try:
            result=run_request(actor,case_id,payload,label=label)
        except RuntimeError as error:
            record['refused'][label]={'case_id':case_id,'refusal':str(error)[:800]}
            print(json.dumps({'case':case_id,'label':label,'refused':str(error)[:200]},
                             ensure_ascii=False),flush=True)
            return None
        spec=cases[spec_case]
        result.update(suite='rag40',attempt=attempt,role=spec['role'],slice=spec['slice'],
                      focus=64000,native_binding_status='bound',case_sha256=rag.digest(spec))
        return capture_run(actor,result)
    resume=saved is not None and 'bindings' in saved
    context=nullcontext({'bindings':saved['bindings'],'person_by_case':{},
                         'blocked':saved['blocked']}) if resume else rag.native_bindings(
        person,bound['bound_sources'],PRIVATE/f'native-{attempt}')
    with context as native:
        bindings=native['bindings']
        # Native project actors are copies of the same owner; HTTP needs only its identity.
        actors={case:native['person_by_case'].get(case,person) for case in rag.NATIVE}
        record['blocked'].update(native.get('blocked',{}))
        record['bindings']=json.loads(json.dumps(bindings,ensure_ascii=False,default=str))
        record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
        print(json.dumps({'native_setup':sorted(bindings),'resumed':resume,
                          'blocked':record['blocked']},ensure_ascii=False),flush=True)
        specs={spec['case_id']:spec for spec in rag.build_run_specs(
            person.category,namespace=names.namespace,native_bindings=bindings)['cases']}
        first=[]
        for case_id in ('ENG-09','QUA-09','PRD-09','PUR-09'):
            if specs[case_id]['status']!='ready':
                record['blocked'].setdefault(case_id,'missing '+','.join(
                    specs[case_id]['missing_native_bindings']))
                continue
            first.append((actors[case_id],case_id,specs[case_id]['request']['json'],
                          names.label+case_id,case_id))
        for child,parent in rag.PARENTS.items():
            if child not in bindings:
                record['blocked'].setdefault(child,'native project binding unavailable')
                continue
            payload={'goal':cases[parent]['prompt'],'idempotency_key':str(uuid5(
                NAMESPACE_URL,f'{names.namespace}:rag40:parent:{child}:{parent}')),
                'product_id':bindings[child]['product_id'],
                'project_id':bindings[child]['project_id']}
            first.append((actors[child],parent,payload,f'{names.label}{parent}-for-{child}',parent))
        done={}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures={executor.submit(execute,*item):item for item in first}
            for future in as_completed(futures):
                value=future.result()
                if value is not None:
                    done[futures[future][3]]=value
        bound_children={}
        for child,parent in rag.PARENTS.items():
            if f'{names.label}{parent}-for-{child}' not in done:
                continue
            parent_result=done[f'{names.label}{parent}-for-{child}']
            record['parents'][child]={'parent':parent,'run_id':parent_result['run_id'],
                                      'status':parent_result['status']}
            try:
                bound_children[child]=rag.bind_action_parents(
                    {child:bindings[child]},{parent:parent_result},bound['bound_sources'])[child]
            except ValueError as error:
                record['blocked'][child]=str(error)
        specs={spec['case_id']:spec for spec in rag.build_run_specs(
            person.category,namespace=names.namespace,native_bindings=bound_children)['cases']}
        second=[(actors[child],child,specs[child]['request']['json'],names.label+child,child)
                for child in bound_children if specs[child]['status']=='ready']
        for child in bound_children:
            if specs[child]['status']!='ready':
                missing=specs[child]['missing_native_bindings']
                record['blocked'][child]='missing '+','.join(missing)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures={executor.submit(execute,*item):item for item in second}
            for future in as_completed(futures):
                value=future.result()
                if value is not None:
                    done[futures[future][3]]=value
    results=[done[names.label+case] for case in
             ('ENG-09','QUA-09','PRD-09','PUR-09','ENG-10','QUA-10','PRD-10','PUR-10')
             if names.label+case in done]
    record['scores']=rag.score_observations(bound['bound_sources'],results)
    record['finished']=True
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({'native_done':len(results),'blocked':record['blocked'],
                      'refused':sorted(record['refused'])},ensure_ascii=False),flush=True)
    return results


def current_focus(person):
    reading=response_json(person.client.get(
        f'/v1/categories/{person.category}/model-configuration',headers=person.headers))
    return reading['configuration']['metadata']['context_window_tokens']-context_reserve()


def settle_for_continuation(person, previous, limit=1200):
    """A continued turn needs a terminal parent (conversation.py: completed/partial/failed/
    cancelled). Await automatic reconciliation; an open question is cancelled the way a
    person ignoring it and sending the next message would. Returns the recorded intervention."""
    if previous['status'] not in {'waiting_input','observation_timeout'}:
        return None
    path=f"/v1/categories/{person.category}/agent-runs/{previous['run_id']}"
    kinds=[event['body'].get('type') for event in previous.get('events',[])]
    started=time.monotonic()
    if previous['status']=='observation_timeout':
        intervention='awaited_unobserved_completion'
    elif 'reconciliation_required' in kinds[-3:]:
        intervention='awaited_automatic_reconciliation'
    else:
        intervention='cancelled_open_question'
        response_json(person.client.post(path+'/cancel',headers=person.headers))
    while time.monotonic()-started<limit:
        # Poll the ledger, not GET run: a reconciled run's own answer currently returns 403
        # (cancel_epoch +1 on reconciliation vs. archived read proof; see the W1 report).
        with Session(person.admin) as session:
            current=session.get(AgentRun,UUID(previous['run_id'])).state
        if current in {'completed','partial','failed','cancelled'}:
            settled=capture_run(person,{**previous,'status':current,'state':current,
                                       'settled_by':intervention})
            return settled,{'intervention':intervention,'final_status':current,
                            'waited_ms':(time.monotonic()-started)*1000}
        time.sleep(5)
    raise RuntimeError(f'{intervention} did not settle within {limit}s')


def run_context_cell(state, case_id, focus, attempt):
    """One context cell per runner-contract.md: native controls between actual continued Runs."""
    import xiaopai_real_context_fixtures as fixtures

    label=f'{attempt}-ctx-{case_id}-F{focus}'
    folder=EVIDENCE/'context'
    folder.mkdir(exist_ok=True)
    summary_path=folder/(label+'.json')
    spec_path=PRIVATE/f'context-spec-{label}.json'
    resumed=None
    if summary_path.exists():
        summary=json.loads(summary_path.read_text())
        if summary.get('finished'):
            return summary
        saved=json.loads(spec_path.read_text()) if spec_path.exists() else None
        if saved is None or any(step['before'] or step['after'] for step in saved['steps']):
            print(json.dumps({'cell':label,'skipped':'unfinished with native controls; '
                              'rerun under a new --attempt'}),flush=True)
            return summary
        # Control-free cell (e.g. CTX-01): continue after the last captured step.
        resumed=[step for step in summary['steps'] if step.get('run_id')]
    person=new_person(f'ctx-{case_id.lower()}-f{focus}-{attempt}',state)
    if resumed is None:
        summary={'case_id':case_id,'focus':focus,'attempt':attempt,'label':label,
                 'category_id':str(person.category),'steps':[],'blocked':None,'error':None}
    else:
        summary.update(steps=resumed,error=None,
                       resumed_from=summary.get('resumed_from',[])+[len(resumed)])
    try:
        if resumed is None:
            spec=fixtures.prepare_case(person,case_id,focus)
            save_private(spec_path,json.loads(json.dumps(spec,ensure_ascii=False,default=str)))
        else:
            spec=saved
        summary.update(binding_status=spec['binding_status'],execution_class=spec['execution_class'],
                       limits=spec['limits'],step_count=len(spec['steps']))
        previous,revision=None,None
        for ordinal,step in enumerate(spec['steps']):
            if resumed and ordinal<len(resumed):
                previous=json.loads((EVIDENCE/'runs'/f'{label}-s{ordinal:02d}.json').read_text())
                continue
            entry={'ordinal':ordinal,'phase':step['phase'],'turn_index':step['turn_index'],
                   'before':[],'after':[]}
            summary['steps'].append(entry)
            for action in step['before']:
                control=fixtures.apply_control(person,spec,action,previous)
                entry['before'].append(json.loads(json.dumps(control,ensure_ascii=False,default=str)))
                revision=control.get('context_revision',revision)
            payload=fixtures.run_payload(spec,ordinal,previous,context_revision=revision)
            result=run_request(person,case_id,payload,label=f'{label}-s{ordinal:02d}')
            result.update(suite='context',attempt=attempt,focus=focus,ordinal=ordinal,
                          phase=step['phase'],turn_index=step['turn_index'])
            previous=capture_run(person,result)
            entry.update(run_id=previous['run_id'],status=previous['status'])
            if ordinal+1<len(spec['steps']):
                settled=settle_for_continuation(person,previous)
                if settled:
                    previous,entry['continuation']=settled
                    entry['settled_status']=previous['status']
            revision=None
            for action in step['after']:
                control=fixtures.apply_control(person,spec,action,previous)
                entry['after'].append(json.loads(json.dumps(control,ensure_ascii=False,default=str)))
                revision=control.get('context_revision',revision)
            # A failed or cancelled turn is a result, and a terminal parent may be continued,
            # so the replay goes on with the next original user turn.
    except fixtures.FixtureBlocked as error:
        summary['blocked']=str(error)
    except RuntimeError as error:
        last=summary['steps'][-1] if summary['steps'] else {}
        reconciled=any((step.get('continuation') or {}).get('intervention')==
                       'awaited_automatic_reconciliation' for step in summary['steps'])
        if 'FORBIDDEN_SCOPE' in str(error) and reconciled:
            summary['blocked']=('reconciled_parent_provenance_defect: the next turn after an '
                                'automatically reconciled Run was refused; '+str(error)[:300])
            last['blocked_by_defect']=True
        else:
            summary['error']=f'{type(error).__name__}: {str(error)[:800]}'
    except Exception as error:  # keep the other cells running; the record shows the failure
        summary['error']=f'{type(error).__name__}: {str(error)[:800]}'
    summary['finished']=summary['error'] is None or summary['blocked'] is not None
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({'cell':label,'steps':len(summary['steps']),'blocked':summary['blocked'],
                      'error':summary['error']},ensure_ascii=False),flush=True)
    return summary


def run_context(state, *, focus, attempt, only=None, workers=2):
    import xiaopai_real_context_fixtures as fixtures

    control=new_person('control',state)
    if current_focus(control)!=focus:
        raise RuntimeError(f'Tenant focus is {current_focus(control)}; switch with set-focus first')
    identities=[case for case in sorted(fixtures.cases()) if not only or case in only]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures=[executor.submit(run_context_cell,state,case,focus,attempt) for case in identities]
        return [future.result() for future in futures]


def export_attempt(attempt, output):
    """Content-free export for xiaopai_real_eval_metrics.py (metering fields only)."""
    import xiaopai_real_context_fixtures as context_fixtures
    import xiaopai_real_rag_fixtures as rag

    questions,_,_=rag.frozen_inputs()
    cases=[{'case_id':case['id']} for case in questions['questions']]
    cases+=[{'case_id':case} for case in sorted(context_fixtures.cases())]
    # Several attempt prefixes may be combined (a2,a2m,a3,a4,c48); the aborted a2 context
    # cell (stopped before the continuation fix) is excluded.
    files=sorted({path for prefix in attempt.split(',')
                  for path in (EVIDENCE/'runs').glob(f'{prefix}-*.json')
                  if not path.name.startswith('a2-ctx-')})
    runs,calls,events=[],[],[]
    keep=('id','run_id','tool','state','error_code','created_at','execution_binding',
          'reserved_tokens','charged_tokens','provider_request_id','actual_input_tokens',
          'actual_output_tokens','cost_state','cost_reserved_micro_usd',
          'cost_charged_micro_usd','cost_pricing','elapsed_ms','protocol','raw_usage')
    for path in files:
        run=json.loads(path.read_text())
        context=run.get('suite')=='context'
        view=run.get('view') or {}
        error=view['error'].get('code') if isinstance(view.get('error'),dict) \
            else view.get('error_code')
        runs.append({'id':run['run_id'],'case_id':run['case_id'],
                     'suite':'context12' if context else 'rag40','label':run['label'],
                     'state':run['state'],'error_code':error,
                     'continued_from_id':run.get('continued_from_id'),
                     'elapsed_ms':run.get('elapsed_ms'),'first_visible_ms':run.get('first_visible_ms'),
                     'focus':run.get('focus')})
        for call in run.get('tool_calls',[]):
            row={key:call.get(key) for key in keep if key in call}
            if call['tool']=='model':
                result=call.get('result') or {}
                row['result']={key:result[key] for key in ('usage','context_budget')
                               if key in result}
            calls.append(row)
        for event in run.get('events',[]):
            if event['body'].get('type')=='context_observed':
                events.append({'run_id':run['run_id'],'body':event['body']})
    value={'version':'xiaopai-real-eval-export/v1','attempt':attempt,'cases':cases,
           'runs':runs,'tool_calls':calls,'events':events}
    output.write_text(json.dumps(value,ensure_ascii=False,indent=1,default=str)+'\n')
    print(json.dumps({'export':str(output),'runs':len(runs),'tool_calls':len(calls),
                      'events':len(events)}),flush=True)


def load_observations():
    samples=[]
    for observations in [EVIDENCE/'provider-observations.jsonl',
                         *sorted(EVIDENCE.glob('runtime-*/provider-observations.jsonl'))]:
        if observations.exists():
            samples+=[json.loads(line) for line in observations.read_text().splitlines()]
    return samples


def reattach_observations(attempt):
    """Pure file pass: attach both workers' provider observations to captured model calls."""
    index={(sample.get('run_id'),sample.get('request_id')):sample for sample in load_observations()
           if sample.get('request_id')}
    attached=0
    for path in sorted((EVIDENCE/'runs').glob(f'{attempt}-*.json')):
        run=json.loads(path.read_text())
        for call in run.get('tool_calls',[]):
            sample=index.get((run['run_id'],call.get('provider_request_id')))
            if sample and 'provider_observation' not in call:
                call.update(elapsed_ms=sample['elapsed_ms'],protocol=sample['protocol'],
                            provider_observation=sample)
                if 'raw_usage' in sample:
                    call['raw_usage']=sample['raw_usage']
                attached+=1
        path.write_text(json.dumps(run,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'reattached':attached}),flush=True)


def refresh_attempt(state, attempt):
    """Re-capture runs the runner stopped watching; elapsed then comes from durable events."""
    tokens={}
    for path in PRIVATE.glob('person-*.json'):
        tokens.update(json.loads(path.read_text())['tokens'])
    base=new_person('control',state)  # any existing synthetic owner; reads use admin
    for path in sorted((EVIDENCE/'runs').glob(f'{attempt}-*.json')):
        run=json.loads(path.read_text())
        if run['state'] not in {'observation_timeout','waiting_input'}:
            continue
        with Session(base.admin) as session:
            row=session.get(AgentRun,UUID(run['run_id']))
            requester,category,current=row.requester_id,row.category_id,row.state
            stamps=[event.created_at for event in session.scalars(select(AgentEvent).where(
                AgentEvent.run_id==row.id).order_by(AgentEvent.sequence))]
        if current in {'queued','running'} or current==run['state']:
            if current!=run['state']:
                print(json.dumps({'label':run['label'],'still':current}),flush=True)
            continue
        if run['state']=='waiting_input':
            # Reached waiting_input (e.g. reconciliation) and later closed; keep the
            # runner's elapsed to that point and record the durable final state.
            own=copy(base)
            own.human,own.category=requester,category
            own.headers={'Authorization':'Bearer '+tokens[str(requester)]} \
                if str(requester) in tokens else {}
            run.update(status=current,state=current,observed_state='waiting_input',
                       final_state_basis='durable_ledger_after_close')
            capture_run(own,run)
            print(json.dumps({'label':run['label'],'closed_as':current}),flush=True)
            continue
        own=copy(base)
        own.human,own.category=requester,category
        own.headers={'Authorization':'Bearer '+tokens[str(requester)]} if str(requester) in tokens \
            else {}
        run.update(status=current,state=current,observation_timeout_elapsed_ms=run['elapsed_ms'],
                   elapsed_ms=(stamps[-1]-stamps[0]).total_seconds()*1000,
                   elapsed_basis='durable_event_timestamps')
        capture_run(own,run)
        print(json.dumps({'label':run['label'],'refreshed':current}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['bootstrap','smoke','seed-rag','rag-ready','rag-native',
                                          'context','set-focus','export','reattach','refresh',
                                          'rescore','restore-config'])
    parser.add_argument('--focus',type=int,choices=[48000,64000],default=64000)
    parser.add_argument('--only',nargs='*')
    parser.add_argument('--attempt',default='a1')
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    state=checked_environment()
    if args.action=='rag-ready':
        run_rag_ready(state,only=set(args.only) if args.only else None,attempt=args.attempt,
                      workers=args.workers)
        return
    if args.action=='seed-rag':
        seed_rag(state,args.attempt)
        return
    if args.action=='rag-native':
        run_rag_native(state,attempt=args.attempt,workers=args.workers)
        return
    if args.action=='context':
        run_context(state,focus=args.focus,attempt=args.attempt,
                    only=set(args.only) if args.only else None,workers=args.workers)
        return
    if args.action=='export':
        export_attempt(args.attempt,EVIDENCE/f"export-{args.attempt.replace(',','-')}.json")
        return
    if args.action=='rescore':
        import xiaopai_real_rag_fixtures as rag
        names=attempt_names(args.attempt)
        bound=json.loads((EVIDENCE/names.bound).read_text())
        results=[json.loads(path.read_text()) for path in
                 sorted((EVIDENCE/'runs').glob(names.label+'*.json'))
                 if '-for-' not in path.name]
        ready=[row for row in results if not row['case_id'].endswith(('-09','-10'))]
        (EVIDENCE/names.scores).write_text(json.dumps(
            rag.score_observations(bound['bound_sources'],ready),ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'rescored':len(ready)}),flush=True)
        return
    if args.action=='refresh':
        refresh_attempt(state,args.attempt)
        return
    if args.action=='reattach':
        reattach_observations(args.attempt)
        return
    if args.action=='restore-config':
        restore_configuration(new_person('control',state))
        return
    if args.action=='set-focus':
        set_focus(new_person('control',state),args.focus)
        return
    person=new_person('control',state)
    if args.action=='bootstrap':set_focus(person,64000)
    else:
        import xiaopai_real_rag_fixtures as rag
        specs=rag.build_run_specs(person.category,namespace='real-eval-smoke-20261101')['cases']
        spec=next(item for item in specs if item['case_id']=='ENG-07')
        run_request(person,spec['case_id'],spec['request']['json'],label='smoke-ENG-07')


if __name__=='__main__':main()
