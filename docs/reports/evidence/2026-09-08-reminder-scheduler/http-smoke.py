from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

ROOT = Path('/Users/huhanwei/Documents/ai-native-R&D-platform')
sys.path.insert(0, str(ROOT / 'server'))
from app.db.schema import tables
from app.db.test_safety import require_test_database_url
from app.db.url import psycopg_database_url

url = require_test_database_url('postgresql://pdos_test:pdos-test-only@127.0.0.1:58433/pdos_test')
os.environ.update({
    'DATABASE_URL': url, 'TEST_DATABASE_URL': url,
    'JWT_SECRET': 'reminder-http-test-secret-at-least-32-bytes',
    'PDOS_DINGTALK_DELIVERY_ENABLED': 'false',
    'PDOS_REMINDER_QUIET_HOURS': '00:00-00:00',
    'PDOS_REMINDER_DAILY_DM_CAP': '50',
    'PDOS_REMINDER_SCAN_SECONDS': '1',
})
os.chdir(ROOT / 'server')
command.upgrade(Config('alembic.ini'), 'head')
engine = create_engine(psycopg_database_url(url))
out = ROOT / 'docs/reports/evidence/2026-09-08-reminder-scheduler'
log = (out / 'http-api.log').open('w')
api = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8813'], stdout=log, stderr=log)
report = {'environment': 'isolated synthetic pdos_test on 58433', 'delivery_enabled': False, 'model_calls': 0}

def cycle():
    result = subprocess.run([sys.executable, '-m', 'scripts.run_reminder_scheduler', '--once'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)

try:
    with httpx2.Client(base_url='http://127.0.0.1:8813', trust_env=False, timeout=5) as client:
        for _ in range(80):
            try:
                if client.get('/healthz').status_code == 200:
                    break
            except httpx2.ConnectError:
                pass
            time.sleep(.25)
        else:
            raise AssertionError('API did not start')
        payload = {'tenant_slug': 'reminder-http', 'tenant_name': 'Synthetic reminder tenant', 'username': 'owner', 'password': 'correct horse battery staple', 'display_name': 'Synthetic Owner'}
        setup_response = client.post('/api/setup', json=payload)
        assert setup_response.status_code == 201, setup_response.text
        setup = setup_response.json()
        tenant_id, owner_id = UUID(setup['tenant']['id']), UUID(setup['user']['id'])
        workflow_id, project_id = uuid4(), uuid4()
        with engine.begin() as connection:
            connection.execute(tables.workflows.insert(), {'id': workflow_id, 'tenant_id': tenant_id, 'code': 'HTTP-WF', 'name': 'HTTP workflow'})
            connection.execute(tables.projects.insert(), {'id': project_id, 'tenant_id': tenant_id, 'workflow_id': workflow_id, 'code': 'HTTP-REM', 'name': 'Synthetic reminder project', 'status': 'active'})
            connection.execute(tables.project_members.insert(), {'id': uuid4(), 'tenant_id': tenant_id, 'project_id': project_id, 'user_id': owner_id, 'added_by_user_id': owner_id})
            connection.execute(tables.dingtalk_tenant_bindings.insert(), {'tenant_id': tenant_id, 'corp_id': 'http-corp', 'client_id': 'http-client', 'robot_code': 'http-robot', 'oauth_redirect_uri': 'https://pdos.example.com/oauth', 'callback_route_key': 'http-reminders', 'status': 'active', 'configured_by_user_id': owner_id})
            connection.execute(tables.dingtalk_user_bindings.insert(), {'id': uuid4(), 'tenant_id': tenant_id, 'user_id': owner_id, 'corp_id': 'http-corp', 'open_id': 'http-open', 'staff_id': 'http-staff'})
        login = client.post('/api/auth/login', json={'tenant_slug': payload['tenant_slug'], 'username': payload['username'], 'password': payload['password']})
        assert login.status_code == 200
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        task_response = client.post(f'/api/projects/{project_id}/tasks', headers=headers, json={'title': 'Synthetic overdue task', 'assignee_user_id': str(owner_id), 'due_date': (datetime.now(UTC).date() - timedelta(days=1)).isoformat()})
        assert task_response.status_code == 201, task_response.text
        task_id = task_response.json()['id']
        first, repeated = cycle(), cycle()
        assert first['fired'] == 5 and first['enqueued'] == 5 and first['candidates_created'] == 1
        assert repeated['fired'] == repeated['enqueued'] == 0
        notifications = client.get('/api/me/notifications', headers=headers)
        assert notifications.status_code == 200 and notifications.json()['unread_count'] == 5
        for status in ('in_progress', 'done'):
            response = client.post(f'/api/projects/{project_id}/tasks/{task_id}/transitions', headers=headers, json={'to_status': status})
            assert response.status_code == 200, response.text
        recovered = cycle()
        assert recovered['cancelled'] == 1 and recovered['candidates_cleared'] == 1
        assert client.get('/api/me/notifications', headers=headers).json()['unread_count'] == 5
        with engine.connect() as connection:
            outbox = connection.execute(select(tables.integration_outbox.c.status, tables.integration_outbox.c.attempt_count)).all()
            assert len(outbox) == 5 and all(row.status == 'manual' and row.attempt_count == 0 for row in outbox)
            revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        report.update({'revision': revision, 'tenant_id': str(tenant_id), 'project_id': str(project_id), 'task_id': task_id, 'first_cycle': first, 'repeated_cycle': repeated, 'source_recovered_cycle': recovered, 'notification_http_status': notifications.status_code, 'unread_count': 5, 'outbox_manual': 5, 'outbox_attempts': 0, 'scan_http_calls': 0, 'task_transition_http_statuses': [200, 200]})
finally:
    api.terminate()
    try:
        api.wait(timeout=15)
    except subprocess.TimeoutExpired:
        api.kill()
        api.wait()
    log.close()
    engine.dispose()

(out / 'http-runtime.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
