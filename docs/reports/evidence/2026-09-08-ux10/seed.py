"""Frozen synthetic UX10 dataset. Requires a disposable, empty pdos_test database."""
from __future__ import annotations
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

SOURCE = Path(os.environ['UX10_SOURCE'])
OUT = Path(os.environ['UX10_EVIDENCE'])
sys.path.insert(0, str(SOURCE / 'server'))
from app.db.test_safety import require_test_database_url
from app.db.url import psycopg_database_url
from app.db.schema import tables
from app.main import app
from tests.test_my_work_api import Seeder, SETUP_PAYLOAD
url = require_test_database_url(os.environ['TEST_DATABASE_URL'])
assert os.environ['DATABASE_URL'] == url
os.chdir(SOURCE / 'server')
command.upgrade(Config('alembic.ini'), 'head')
engine = create_engine(psycopg_database_url(url))
with engine.connect() as con:
    assert con.execute(select(tables.tenants.c.id)).first() is None, 'seed only an empty test database'
with TestClient(app) as client:
    response = client.post('/api/setup', json=SETUP_PAYLOAD)
    assert response.status_code == 201, response.text
    setup = response.json()
seeder = Seeder(url, UUID(setup['tenant']['id']), UUID(setup['user']['id']))
original_insert = seeder._insert
def shared_subscription_insert(table, values):
    if table is tables.agent_subscriptions:
        with engine.connect() as con:
            existing = con.execute(select(table.c.id).where(table.c.tenant_id == seeder.tenant_id, table.c.agent_key == values['agent_key'])).scalar_one_or_none()
            if existing is not None:
                return existing
    return original_insert(table, values)
seeder._insert = shared_subscription_insert
now = datetime(2026, 9, 8, 12, tzinfo=UTC)
manifest = {'dataset': 'ux10-synthetic-v1', 'frozen_at': now.isoformat(), 'tenant_slug': 'beepump', 'role': 'owner', 'projects': [], 'counts': {}}
for p in range(25):
    project = seeder.project(f'UX-{p+1:02}', member_ids=(seeder.owner_id,))
    pid = project['project_id']
    task_ids = [uuid4() for _ in range(500 if p == 0 else 40)]
    with engine.begin() as con:
        con.execute(tables.tasks.insert(), [dict(id=tid, tenant_id=seeder.tenant_id, project_id=pid, assignee_user_id=seeder.owner_id, title=f'UX10 任务 {p+1:02}-{i+1:03}', description='固定数据规模的工程验证任务。' * 24, status='done' if i % 5 == 4 else 'todo', completed_at=now if i % 5 == 4 else None, due_date=now.date()+timedelta(days=(i % 14)-2), created_at=now+timedelta(seconds=i), updated_at=now+timedelta(seconds=i)) for i, tid in enumerate(task_ids)])
        con.execute(tables.task_dependencies.insert(), [dict(id=uuid4(),tenant_id=seeder.tenant_id,project_id=pid,task_id=task_ids[i],depends_on_task_id=task_ids[j]) for i in range(2,len(task_ids)) for j in (i-2,i-1)])
        con.execute(tables.issues.insert(), [dict(id=uuid4(),tenant_id=seeder.tenant_id,project_id=pid,owner_user_id=seeder.owner_id,reported_by_user_id=seeder.owner_id,title=f'UX10 问题 {p+1:02}-{i+1:02}',description='可重现的合成问题。'*24,status='open',target_date=now.date(),created_at=now,updated_at=now) for i in range(20)])
        con.execute(tables.risks.insert(), [dict(id=uuid4(),tenant_id=seeder.tenant_id,project_id=pid,owner_user_id=seeder.owner_id,title=f'UX10 风险 {p+1:02}-{i+1:02}',description='合成风险，仅用于测量。'*24,draft_state='draft' if i<3 else 'confirmed',origin_key=f'ux10:{p}:{i}' if i<3 else None,likelihood=3,impact=4,created_at=now,updated_at=now) for i in range(8)])
    fid = seeder.finding(pid, title=f'UX10 待审建议 {p+1:02}-01')
    with engine.begin() as con:
        event_id = con.execute(tables.events.insert().values(tenant_id=seeder.tenant_id, project_id=pid, event_id=f'ux10:{pid}',event_type='ISSUE_CREATED',schema_version=1,source='ux10_synthetic_fixture',entity='issue',entity_id=uuid4(),payload={},timestamp=now).returning(tables.events.c.id)).scalar_one()
        con.execute(tables.findings.update().where(tables.findings.c.id==fid).values(summary='基于项目事件形成的合成风险建议。'*32,proposed_payload={'title':f'UX10 风险建议 {p+1:02}','description':'用于首屏测量的合成资料。'*24,'likelihood':3,'impact':4},evidence_event_ids=[event_id],created_at=now,updated_at=now))
        base={k:v for k,v in con.execute(select(tables.findings).where(tables.findings.c.id==fid)).mappings().one().items() if v is not None}
        for i in range(1,4):
            row={**base,'id':uuid4(),'title':f'UX10 待审建议 {p+1:02}-{i+1:02}','origin_key':f'ux10:{p}:{i}','status':'archived' if i==3 else 'pending_review','created_at':now+timedelta(seconds=i),'updated_at':now+timedelta(seconds=i)}
            con.execute(tables.findings.insert(),row)
        if p==0:
            con.execute(tables.reminders.insert(),[dict(id=uuid4(),tenant_id=seeder.tenant_id,project_id=pid,recipient_user_id=seeder.owner_id,policy_key='task_overdue',target_entity='task',target_entity_id=task_ids[i],title=f'UX10 通知 {i+1:03}',dedupe_key=f'ux10:notice:{i}',fire_at=now,status='fired',fired_at=now,created_at=now,updated_at=now) for i in range(200)])
    manifest['projects'].append({'id':str(pid),'code':f'UX-{p+1:02}','finding_id':str(fid),'task_id':str(task_ids[0])})
with engine.begin() as con:
    con.execute(text('ANALYZE'))
    for table in (tables.projects,tables.tasks,tables.task_dependencies,tables.issues,tables.risks,tables.findings,tables.reminders):
        manifest['counts'][table.name]=con.execute(text(f'SELECT count(*) FROM {table.schema}.{table.name}')).scalar_one()
    manifest['migration']=con.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'dataset.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'counts':manifest['counts'],'migration':manifest['migration']},ensure_ascii=False))
seeder.dispose()
engine.dispose()
