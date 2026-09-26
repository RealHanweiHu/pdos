"""Synthetic NPD lifecycle through real API handlers, rollback-only pdos_test.

Run with the server dependencies. Optional --serve retains the outer transaction
on 127.0.0.1:8320 for local browser inspection until Ctrl-C; it never commits.
Only tenant/users/members are fixture inserts. Business transitions use APIs.
"""
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
DISCIPLINES = '--disciplines' in sys.argv
sys.path.insert(0, str(ROOT / 'server'))
from app.db.test_safety import configured_test_database_url
URL = configured_test_database_url()
os.environ.update(DATABASE_URL=URL, JWT_SECRET='synthetic-lifecycle-only-secret-at-least-32-bytes', JWT_ISSUER='pdos-test', JWT_AUDIENCE='pdos-test-client')
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, text
from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.url import psycopg_database_url
from app.main import app

class BorrowedConnection:
    def __init__(self, bound): self.bound = bound
    def execution_options(self, **options):
        assert options == {'isolation_level': 'REPEATABLE READ'}
        return self
    def __enter__(self):
        self.bound.lock.acquire()
        return self.bound.connection
    def __exit__(self, *args): self.bound.lock.release()

class RollbackEngine:
    def __init__(self, connection): self.connection, self.lock = connection, RLock()
    @contextmanager
    def begin(self):
        with self.lock, self.connection.begin_nested(): yield self.connection
    def connect(self): return BorrowedConnection(self)

out = {'scenario': 'SIM-BIKE-01 便携锂电自行车泵（全流程模拟）', 'recorded_at': datetime.now(UTC).isoformat(),
       'synthetic': True, 'scope': '真实 API 与数据库约束；全部业务内容、审批、读数和接收回执均为模拟。无真实 ERP/钉钉/LLM 调用。',
       'steps': [], 'checks': [], 'gaps': [], 'stage_snapshots': [], 'success': False}
engine = create_engine(psycopg_database_url(URL))
conn = engine.connect().execution_options(isolation_level='REPEATABLE READ')
transaction = conn.begin()
previous = app.dependency_overrides.copy()
app.dependency_overrides[get_engine] = lambda: RollbackEngineBound
RollbackEngineBound = RollbackEngine(conn)
tenant_id = uuid4()
slug = 'sim-bike-' + uuid4().hex[:10]
password = 'Local-simulation-only-2026'
roles = {'pm': ('project_manager', '林经理·项目/产品（模拟）'), 'engineer': ('engineer', '陈工·研发（模拟）'),
         'quality': ('quality', '王工·品质执行（模拟）'), 'verifier': ('quality', '赵工·独立验证（模拟）'),
         'receiver': ('admin', '周工·转产接收/对账（模拟）')}
if DISCIPLINES:
    roles.update({'id': ('engineer', '孙工·ID（模拟）'), 'md': ('engineer', '钱工·结构（模拟）'), 'fw': ('engineer', '刘工·嵌入式（模拟）')})
    out['scenario'] += ' · ID/结构/硬件/嵌入式专项'
users, headers = {}, {}
phase = 'idea'

def api(actor, method, path, body=None, expected=None, label=None):
    response = client.request(method, path, headers=headers.get(actor, {}), **({'json': body} if body is not None else {}))
    data = response.json()
    out['steps'].append({'index': len(out['steps'])+1, 'phase': phase, 'actor': actor, 'label': label or path.rsplit('/',1)[-1],
                         'method': method, 'path': path, 'request': body, 'http_status': response.status_code, 'response': data})
    if expected is None: assert response.status_code in (200,201), (method,path,response.status_code,data)
    else: assert response.status_code == expected, (method,path,response.status_code,data)
    return data

def negative(actor, method, path, body, code, status=409):
    data = api(actor,method,path,body,expected=status,label='拦截检查：'+code)
    assert data['detail']['code'] == code, data
    out['checks'].append({'code': code, 'status': status, 'phase': phase})

def decision(title, outcome, refs, actor='pm'):
    return api(actor,'POST',base+'/decisions',{'decision_kind':'process_decision','title':'【模拟】'+title,
              'outcome':outcome,'rationale':'流程演示，不表示真实业务批准。','evidence_refs':refs},label=title)

def task(title, actor, stage, dependency=None):
    return api('pm','POST',base+'/tasks',{'title':'【模拟】'+title,'stage_id':stage['id'],'assignee_user_id':str(users[actor]),
               'expected_output':'模拟记录须写明版本、结果、接收人；不作为真实符合性证据。','due_date':'2026-12-31',
               'dependency_task_ids':[dependency['id']] if dependency else []},label='分配任务：'+title)

def finish_task(t, actor, evidence):
    api(actor,'POST',base+'/tasks/'+t['id']+'/transitions',{'to_status':'in_progress'})
    api(actor,'POST',base+'/tasks/'+t['id']+'/transitions',{'to_status':'done','completion_evidence_ref':evidence})

def record_run(actor, method, path, body, label=None):
    # Exercise the actual role restriction once; never grant the fixture broader rights.
    if not any(g['code']=='SIM-GAP-02' for g in out['gaps']):
        negative(actor,method,path,body,'PROJECT_ACCESS_DENIED',403)
        out['gaps'].append({'code':'SIM-GAP-02','finding':'Quality 可以管理测试计划/结果，但逐次 TestRun 写入要求 PRODUCT_ENGINEERING_EDIT，品质执行/独立验证账号均缺此权限。','effect':'模拟中由 Engineer 代录，conditions 标明模拟报告人；品质仍通过原结果 API 核对，独立关闭 Issue。未扩大账号权限。'})
    body['conditions']['simulated_reporter']=roles[actor][1]
    body['result_notes'] += ' 由研发代录（当前品质逐次录入权限缺口）。'
    return api('engineer',method,path,body,label=label)

try:
    conn.execute(text("SET LOCAL lock_timeout='5s'"))
    out['database_revision'] = conn.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    conn.execute(tables.tenants.insert().values(id=tenant_id,slug=slug,name='SIM 全流程隔离演示'))
    hashed = PasswordService().hash(password)
    for key,(role,name) in roles.items():
        users[key] = uuid4()
        conn.execute(tables.users.insert().values(id=users[key],tenant_id=tenant_id,username="sim-"+key,display_name=name,role=role,password_hash=hashed))
    out['actors'] = {key:{'id':str(users[key]),'role':role,'name':name} for key,(role,name) in roles.items()}
    with TestClient(app) as client:
        for actor in roles:
            response=client.post('/api/auth/login',json={'tenant_slug':slug,'username':'sim-'+actor,'password':password})
            assert response.status_code == 200,response.text
            headers[actor]={'Authorization':'Bearer '+response.json()['access_token']}
        req = api('pm','POST','/api/requirements',{'code':'SIM-REQ-BIKE-01','title':'【模拟】骑行途中随身补气',
            'description':'想法：便携锂电自行车泵，预设压力自动停机，USB-C 充电，不带照明。模拟专用，与 D14-04 无关。',
            'acceptance_criteria':['【模拟判据】预设60 psi时停止压力误差不超过±2 psi','【模拟范围】验证充气、自动停机和充电；完整产品测试及认证另行定义']},label='想法进入需求池')
        api('pm','PATCH','/api/requirements/'+req['id'],{'status':'approved'},label='确认需求范围')
        case = api('pm','POST',f"/api/requirements/{req['id']}/convert-to-case",{'code':'SIM-CASE-BIKE-01','title':'【模拟】便携自行车泵可行性评估','summary':'研发确认方案可行；品质确认验证方法；项目经理确认模拟计划。','rationale':'【模拟】同意开展开发评估。'},label='需求转开发案例')['development_case']
        for state in ['evaluating','approved']:
            api('pm','POST',f"/api/development-cases/{case['id']}/transitions",{'to_status':state})
        project = api('pm','POST','/api/projects',{'development_case_id':case['id'],'code':'SIM-BIKE-01','name':'【模拟】便携锂电自行车泵·从想法到结束','description':out['scope'],'start_date':'2026-09-09','target_date':'2026-12-31'},label='批准案例转项目并生成七阶段')
        pid = project['id']; base = '/api/projects/'+pid; npi = base+'/npi'; engineering = base+'/product-engineering'
        stages = project['workflow']['stages']
        for key in roles:
            if key != 'pm':
                conn.execute(tables.project_members.insert().values(id=uuid4(),tenant_id=tenant_id,project_id=UUID(pid),user_id=users[key],added_by_user_id=users['pm']))
        out['ids']={'tenant_id':str(tenant_id),'project_id':pid,'requirement_id':req['id'],'case_id':case['id']}
        disciplines = None
        if DISCIPLINES:
            from disciplinary_tasks import DisciplineSimulation
            disciplines = DisciplineSimulation(ROOT, api, negative, base, stages, users, out)
        for state in ['proposed','approved','active']:
            api('pm','POST',base+'/transitions',{'to_status':state})
        # Probe completion on a savepoint, then undo even if the current system permits it.
        probe=conn.begin_nested()
        completion=api('pm','POST',base+'/transitions',{'to_status':'completed'},label='探测提前结项（独立保存点，立即回滚）')
        probe.rollback()
        if completion['status']=='completed':
            out['gaps'].append({'code':'SIM-GAP-01','finding':'项目在概念阶段可直接标记 completed；结项未校验最终阶段/Gate/遗留任务。探测已单独回滚。','effect':'本次演示主动按七阶段完成，不能据此称结项强约束已实现。'})
        checks = api('pm','POST',base+'/deliverable-checks/prepare',label='从已有资产库生成交付物检查项')
        check_items = api('pm','GET',base+'/deliverable-checks')['items']
        out['deliverable_count'] = len(check_items)
        previous_task=None; pbom=None; handoff=None
        for stage in stages:
            phase = stage['code']; print('STAGE',phase,flush=True)
            gate = next(x for x in api('pm','GET',base+'/gates')['items'] if x['stage']['id']==stage['id'])
            if stage['sequence']<7:
                negative('pm','POST',base+'/stage-transitions',{'to_stage_id':stages[stage['sequence']]['id']},'PROJECT_GATE_NOT_APPROVED')
            lead = 'engineer' if phase in ('design','evt') else 'quality' if phase=='dvt' else 'receiver' if phase in ('pvt','mp') else 'pm'
            work=task(stage['name']+'成果与交接',lead,stage,previous_task)
            if phase=='concept':
                waiting=task('评审规格和测试范围','quality',stages[1],work)
                negative('quality','POST',base+'/tasks/'+waiting['id']+'/transitions',{'to_status':'in_progress'},'TASK_DEPENDENCIES_INCOMPLETE')
                record=decision('立项与分工','林经理协调；陈工设计整改；王工测试；赵工独立验证；周工接收转产。',[req['id'],case['id']])
            elif phase=='planning':
                spec=api('engineer','POST',engineering+'/specifications',{'code':'SIM-SPEC-01','title':'【模拟】自行车泵产品规格','requirement_id':req['id'],'owner_user_id':str(users['engineer']),'verification_method':'模拟压力读数对比；充电功能模拟检查','acceptance_criteria':'仅演示判据：60 psi预设下误差≤±2 psi；无照明测试。','content':{'synthetic':True,'product_type':'lithium-bicycle-pump','lighting':False,'pressure_target_psi':60,'tolerance_psi':2}},label='建立可追溯规格')
                finish_task(waiting,'quality','模拟规格与测试范围确认：'+spec['id'])
                record=spec
            elif phase=='design':
                for kind in ['prototype','ebom']:
                    bom=api('engineer','POST',engineering+'/boms',{'specification_id':spec['id'],'bom_type':kind,'code':'SIM-'+kind.upper()+'-01','name':'【模拟】自行车泵 '+kind,'notes':'模拟版本，禁止用于采购或生产。'},label='建立设计BOM：'+kind)
                    api('engineer','POST',engineering+'/boms/'+bom['id']+'/items',{'line_number':1,'part_number':'SIM-CONTROLLER-01','description':'【模拟】控制板与压力传感器组件','quantity':'1','unit':'set'})
                    if kind=='prototype': pbom=bom
                    else: ebom=bom
                record=decision('设计评审','设计基线V1可进入EVT；遇到差异必须记录问题与变更。',[spec['id'],pbom['id'],ebom['id']])
            elif phase in ('evt','dvt','pvt'):
                build=api('engineer','POST',npi+'/builds',{'stage_id':stage['id'],'phase':phase,'code':'SIM-'+phase.upper()+'-01','planned_quantity':1,'notes':'数量为流程演示，不能代表完整抽样计划。'})
                sample=api('engineer','POST',npi+'/builds/'+build['id']+'/samples',{'serial_number':'SIM-'+phase.upper()+'-S01','prototype_bom_id':pbom['id'],'notes':'仅存在于隔离演示，无实物。'})
                api('engineer','PUT',npi+'/samples/'+sample['id']+'/build-configuration',{'pcb_version':'SIM-HW1','structure_version':'SIM-MD1','fw_version':'SIM-FW1' if phase=='evt' else 'SIM-FW2','development_bom_id':pbom['id']})
                plan=api('quality','POST',npi+'/test-plans',{'stage_id':stage['id'],'phase':phase,'title':'【模拟】'+phase.upper()+' 验证计划','sample_size':1,'status':'active','scope':'代表性用例演示，不代替自行车泵完整整机/可靠性/认证计划。'})
                titles = ['预设压力自动停机','USB-C充电'] if phase=='evt' else ['整改后自动停机','循环运行功能检查'] if phase=='dvt' else ['首件功能检查','装配与配置一致性']
                cases=[]
                for title in titles:
                    tc=api('quality','POST',npi+'/test-plans/'+plan['id']+'/cases',{'title':'【模拟】'+title,'category':'functional','acceptance_criteria':'模拟压力误差≤±2 psi' if '停机' in title else '模拟检查项全部通过','method':'合成数据，用于流程验证。','sample_ids':[sample['id']]})
                    cases.append(tc)
                if phase=='evt':
                    issue=api('quality','POST',base+'/issues',{'stage_id':stage['id'],'sample_id':sample['id'],'title':'【模拟】自动停机压力超差','issue_type':'test_failure','severity':'high','owner_user_id':str(users['engineer']),'verifier_user_id':str(users['verifier']),'closure_criteria':'【模拟】FW2复测停止压力误差≤±2 psi，独立验证确认。','target_date':'2026-12-01'})
                    api('quality','POST',npi+'/test-cases/'+cases[0]['id']+'/result',{'status':'failed','related_issue_id':issue['id'],'result_notes':'【模拟】品质确认失败并关联整改问题'})
                    failedrun=record_run('quality','POST',npi+'/test-cases/'+cases[0]['id']+'/runs',{'status':'failed','sample_id':sample['id'],'conditions':{'synthetic':True,'fw':'SIM-FW1'},'metrics':[{'name':'停止压力','value':65,'unit':'psi','target':60,'verdict':'fail'}],'result_notes':'【模拟】误差+5 psi，超出演示判据。'},label='品质记录一次失败，保留原始记录')
                    gr=api('pm','POST',base+'/gates/'+gate['id']+'/rounds')
                    negative('pm','POST',base+'/gates/'+gate['id']+'/decisions',{'status':'approved','rationale':'【模拟】故意尝试带问题放行'},'GATE_NOT_READY')
                    api('engineer','POST',base+'/issues/'+issue['id']+'/transitions',{'to_status':'analysis'})
                    api('engineer','PATCH',base+'/issues/'+issue['id'],{'root_cause':'【模拟】压力采样滤波延迟造成停机过冲。','resolution':'【模拟】修订控制逻辑为FW2，重新验证。'})
                    changebase=base+'/changes'
                    ecr=api('engineer','POST',changebase+'/ecrs',{'code':'SIM-ECR-01','title':'【模拟】调整自动停机控制逻辑','reason':'模拟EVT压力超差，关联问题 '+issue['id']})
                    ecrurl=changebase+'/ecrs/'+ecr['id']
                    api('engineer','POST',ecrurl+'/start-impact')
                    api('engineer','POST',ecrurl+'/submit-impact',{'impact_analysis':{'synthetic':True,'firmware':'FW1→FW2','validation':'压力停止与充电功能回归','schedule':'模拟计划内修正'},'affected_bom_ids':[ebom['id']]})
                    # PM is a distinct approver; requester remains Engineer.
                    api('pm','POST',ecrurl+'/decide',{'outcome':'approved','note':'【模拟】独立审批，同意修订及复测。'})
                    ecn=api('engineer','POST',ecrurl+'/ecns',{'code':'SIM-ECN-01','title':'【模拟】发布FW2控制逻辑','implementation_plan':{'firmware':'SIM-FW2','retest_issue_id':issue['id']}})
                    ecnurl=changebase+'/ecns/'+ecn['id']
                    api('engineer','POST',ecnurl+'/submit-effectivity')
                    handoff=api('pm','POST',ecnurl+'/decide-effectivity',{'outcome':'approved','effectivity':{'synthetic':True,'from_lot':'SIM-DVT-01','firmware':'SIM-FW2'},'released_bom_id':ebom['id'],'target_system':'simulation-only'})['handoff']
                    negative('pm','POST',changebase+'/handoffs/'+handoff['id']+'/ready',None,'HANDOFF_PVT_GATE_REQUIRED')
                    api('engineer','POST',base+'/issues/'+issue['id']+'/transitions',{'to_status':'action'})
                    # Submit the remediation for independent verification. The first run stays immutable.
                    api('engineer','POST',base+'/issues/'+issue['id']+'/transitions',{'to_status':'verification'})
                    negative('engineer','POST',base+'/issues/'+issue['id']+'/transitions',{'to_status':'closed'},'ISSUE_CLOSE_REQUIRES_VERIFIER')
                    # Revision recorded in new run; original failed run retains FW1 conditions.
                    api('engineer','PUT',npi+'/samples/'+sample['id']+'/build-configuration',{'pcb_version':'SIM-HW1','structure_version':'SIM-MD1','fw_version':'SIM-FW2','development_bom_id':pbom['id']})
                    retest=record_run('verifier','POST',npi+'/test-cases/'+cases[0]['id']+'/runs',{'status':'passed','sample_id':sample['id'],'conditions':{'synthetic':True,'fw':'SIM-FW2'},'metrics':[{'name':'停止压力','value':61,'unit':'psi','target':60,'verdict':'pass'}],'result_notes':'【模拟】独立复测误差+1 psi，通过演示判据。'},label='独立验证人记录复测')
                    api('verifier','POST',base+'/issues/'+issue['id']+'/transitions',{'to_status':'closed','closure_evidence_ref':'模拟复测运行 '+retest['id']})
                for tc in cases:
                    if phase=='evt' and tc==cases[0]: continue
                    record_run('quality','POST',npi+'/test-cases/'+tc['id']+'/runs',{'status':'passed','sample_id':sample['id'],'conditions':{'synthetic':True,'fw':'SIM-FW2'},'result_notes':'【模拟】功能检查通过，仅验证系统记录链。'})
                report=api('quality','POST',npi+'/test-plans/'+plan['id']+'/reports',{'report_number':'SIM-TR-'+phase.upper(),'title':'【模拟】'+phase.upper()+' 结果报告','result':'pass','summary':'模拟用例通过；EVT首轮失败与复测分别留存。非实测报告。'})
                api('verifier','POST',npi+'/test-reports/'+report['id']+'/review',{'review_status':'approved','note':'【模拟】核对运行记录及问题关闭。'})
                api('engineer','PATCH',npi+'/builds/'+build['id'],{'status':'completed','completed_quantity':1})
                sign=api('engineer','POST',npi+'/sample-signoffs',{'phase':phase,'title':'【模拟】'+phase.upper()+' 内部样机确认','signoff_type':phase+'_sample','audience':'internal','sample_ids':[sample['id']]})
                api('verifier','POST',npi+'/sample-signoffs/'+sign['id']+'/respond',{'status':'approved','note':'【模拟】配置与报告对应。'})
                record=report
            else:
                record=decision('量产稳定观察与移交','【模拟】合成观察记录无新问题，周工接收版本与维护职责；不代表真实量产表现。',[handoff['id'],ebom['id']],actor='receiver')
                api('engineer','POST',base+'/memories',{'title':'【模拟】自动停机超差整改复盘','content':'模拟链：失败运行→Issue→ECR/ECN→独立复测→关闭。仅作流程教学，不是验证过的工程规律。','applicability':'仅本模拟项目','tags':['simulation','workflow']})
            if disciplines:
                disciplines.complete_stage(stage, record)
            finish_task(work,lead,'模拟阶段成果 '+record['id']); previous_task=work
            # Each library item gets its own explicit synthetic evidence, not an exemption.
            stage_checks=[item for item in check_items if item.get('stage_id')==stage['id']]
            for item in stage_checks:
                api(lead,'POST',base+'/deliverable-checks/items/'+item['id']+'/resolve',{'status':'completed','evidence_reference':'SIM-EVIDENCE:'+item['id'],'note':'【模拟占位证据】仅演示本检查项的提交与阻塞解除，不表示真实交付物已制作或业务标准已满足。'},label='模拟交付物检查')
            gateurl=base+'/gates/'+gate['id']
            gr=api('pm','POST',gateurl+'/rounds')
            for slot,actor in [('product','pm'),('engineering','engineer'),('quality','verifier')]:
                api(actor,'PUT',gateurl+'/rounds/'+gr['round']['id']+'/signoffs/'+slot,{'status':'approved','note':'【模拟】按职责检查本阶段记录。'})
            approved=api('pm','POST',gateurl+'/decisions',{'status':'approved','rationale':'【模拟】三方签核和演示记录满足当前硬闸；不构成真实产品放行。'},label=stage['name']+'评审通过')
            out['stage_snapshots'].append({'stage':phase,'name':stage['name'],'gate':approved,'task':api('pm','GET',base+'/tasks/'+work['id']),'record':record,'synthetic_check_count':len(stage_checks)})
            if phase=='pvt':
                hurl=base+'/changes/handoffs/'+handoff['id']
                api('pm','POST',hurl+'/ready')
                api('pm','POST',hurl+'/queue',{'idempotency_key':'sim-bike-manual-handoff-01','mode':'manual'})
                api('pm','POST',hurl+'/export',{'confirmation':'EXPORT_CONFIRMED'},label='模拟人工交接包导出（无外发）')
                api('receiver','POST',hurl+'/reconcile',{'confirmation':'RECONCILE_CONFIRMED','outcome':'confirmed_delivered','external_reference':'SIM-RECEIPT-ONLY-01'},label='模拟接收方核对回执（无真实ERP）')
            if stage['sequence']<7:
                api('pm','POST',base+'/stage-transitions',{'to_stage_id':stages[stage['sequence']]['id']})
        phase='close'
        final_tasks=api('pm','GET',base+'/tasks')['items']
        assert all(t['status']=='done' for t in final_tasks)
        assert all(g['status']=='approved' for g in api('pm','GET',base+'/gates')['items'])
        assert all(i['status']=='closed' for i in api('pm','GET',base+'/issues')['items'])
        decision('项目结项','【模拟】七阶段评审完成，任务全部完成，问题经独立验证关闭，交接包已在本模拟内对账。',[handoff['id'],record['id']])
        api('pm','POST',base+'/transitions',{'to_status':'completed'},label='项目完成')
        final=api('pm','POST',base+'/transitions',{'to_status':'archived'},label='归档保留追溯')
        out['final']={'project':final,'tasks':final_tasks,'gates':api('pm','GET',base+'/gates')['items'],'issues':api('pm','GET',base+'/issues')['items'],'npi':api('pm','GET',npi),'changes':api('pm','GET',base+'/changes'),'decisions':api('pm','GET',base+'/decisions')['items']}
        out['success']=True
    if '--serve' in sys.argv:
        Path('/private/tmp/pdos-lifecycle-browser.json').write_text(json.dumps({'tenant_slug':slug,'project_id':pid,'username':'sim-pm','password':password}))
        print('SIMULATION PASS; serving 127.0.0.1:8320',flush=True)
        import uvicorn
        uvicorn.run(app,host='127.0.0.1',port=8320,log_level='warning')
except BaseException as exc:
    out['error']=str(exc)
    raise
finally:
    out['event_counts']={row[0]:row[1] for row in conn.execute(select(tables.events.c.event_type,func.count()).where(tables.events.c.tenant_id==tenant_id).group_by(tables.events.c.event_type))} if conn.in_transaction() else {}
    transaction.rollback();conn.close()
    app.dependency_overrides.clear();app.dependency_overrides.update(previous)
    with engine.connect() as clean:
        remaining=clean.execute(select(func.count()).select_from(tables.tenants).where(tables.tenants.c.id==tenant_id)).scalar_one()
    out['cleanup']={'transaction_rolled_back':True,'test_tenant_remaining':remaining,'existing_tables_truncated':False}
    assert remaining==0
    out['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target=ROOT/('docs/reports/evidence/2026-09-09-npd-disciplines-simulation.json' if DISCIPLINES else 'docs/reports/evidence/2026-09-09-npd-project-simulation.json')
    if DISCIPLINES:
        out['dependency_template_sha256'] = hashlib.sha256((ROOT/'web/src/components/projects/npd-disciplinary-task-template.json').read_bytes()).hexdigest()
        out['discipline_script_sha256'] = hashlib.sha256((ROOT/'scripts/simulations/disciplinary_tasks.py').read_bytes()).hexdigest()
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
    engine.dispose()
    print(json.dumps({'success':out['success'],'requests':len(out['steps']),'gaps':out['gaps'],'cleanup':out['cleanup']},ensure_ascii=False),flush=True)
