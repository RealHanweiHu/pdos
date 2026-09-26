"""Instantiate the shared four-discipline baseline inside the rollback-only demo."""
import json


class DisciplineSimulation:
    def __init__(self, root, api, negative, base, stages, users, out):
        self.api, self.negative, self.base, self.out = api, negative, base, out
        self.template = json.loads((root / 'web/src/components/projects/npd-disciplinary-task-template.json').read_text())
        self.definitions = {item['code']: item for item in self.template['tasks']}
        self.tasks = {}
        self.started = set()
        by_stage = {stage['code']: stage for stage in stages}
        for item in self.template['tasks']:
            code = item['code']
            self.tasks[code] = api('pm', 'POST', base + '/tasks', {
                'title': '【模拟四专业】' + code + ' ' + item['title'],
                'stage_id': by_stage[item['stage']]['id'],
                'assignee_user_id': str(users[item['owner']]),
                'description': '输入与交付需经接收方核对。接收：' + item['receiver'],
                'expected_output': '【模拟占位】' + item['output'],
                'dependency_task_ids': [self.tasks[dependency]['id'] for dependency in item['depends_on']],
                'start_date': '2026-09-09', 'due_date': '2026-12-31', 'priority': 'high' if code.startswith('ID-') else 'medium',
            }, label='实例化四专业依赖：' + code)
        # Demonstration dates, deliberately separate the ID effort, external wait,
        # and freeze target; the remaining tasks retain a broad scenario window.
        api('pm', 'PATCH', self.url('ID-CONCEPT'), {'start_date': '2026-09-14', 'due_date': '2026-10-02'})
        api('pm', 'PATCH', self.url('ID-FREEZE'), {'start_date': '2026-10-05', 'due_date': '2026-10-16'})
        out['discipline_simulation'] = {'template_id': self.template['id'], 'task_ids': {k: v['id'] for k, v in self.tasks.items()}, 'checks': [], 'snapshots': [], 'date_scope': '仅为演示日期，ID 方案与冻结单列；没有模拟真实工期或自动排程。'}

    def url(self, code):
        return self.base + '/tasks/' + self.tasks[code]['id']

    def start(self, code):
        result = self.api(self.definitions[code]['owner'], 'POST', self.url(code) + '/transitions', {'to_status': 'in_progress'})
        self.started.add(code)
        return result

    def finish(self, code, ref):
        if code not in self.started:
            self.start(code)
        return self.api(self.definitions[code]['owner'], 'POST', self.url(code) + '/transitions', {'to_status': 'done', 'completion_evidence_ref': '【模拟】' + code + ' / ' + ref})

    def blocked(self, code):
        self.negative(self.definitions[code]['owner'], 'POST', self.url(code) + '/transitions', {'to_status': 'in_progress'}, 'TASK_DEPENDENCIES_INCOMPLETE')
        self.out['discipline_simulation']['checks'].append(code + ' rejects premature start')

    def snapshot(self, label, codes):
        values = {code: self.api('pm', 'GET', self.url(code)) for code in codes}
        self.out['discipline_simulation']['snapshots'].append({'label': label, 'tasks': values})
        return values

    def complete_stage(self, stage, record):
        phase = stage['code']
        ref = record['id']
        if phase == 'concept':
            self.finish('REQ', ref)
            plan = self.api('pm', 'POST', self.base + '/decisions', {
                'decision_kind': 'process_decision', 'title': '【模拟】立项确认 ID 专项计划',
                'context': '全新 ID，自行车泵，无照明。孙工负责 ID，林经理确认，结构钱工/硬件陈工/嵌入式刘工共同评审。',
                'outcome': '【模拟】批准 ID 专项计划；不等于方案冻结。方案9/14–10/02，冻结目标10/16。',
                'rationale': '【模拟估算】设计10个工作日、产品/客户反馈5个工作日、2轮评审、另留修改缓冲；预算仅记录模拟额度10000元，不构成采购授权。',
                'consequence': 'ID 冻结影响结构板框、PCB 和整机样机；预研并行。延期保留原计划，评估后单独确认后续日期。',
                'evidence_refs': [self.tasks['ID-PLAN']['id'], ref],
            }, label='立项确认ID周期、资源和冻结节点')
            self.finish('ID-PLAN', plan['id'])
        elif phase == 'planning':
            self.start('ID-CONCEPT')
            self.finish('ARCH', ref)
            for code in ['MD-PRE', 'EE-PRE', 'FW-PRE']:
                self.start(code)
            values = self.snapshot('ID方案进行中，结构/硬件/嵌入式预研同时进行', ['ID-CONCEPT', 'MD-PRE', 'EE-PRE', 'FW-PRE'])
            assert all(task['status'] == 'in_progress' for task in values.values())
            for code in ['MD-PRE', 'EE-PRE', 'FW-PRE']:
                self.finish(code, ref)
            self.blocked('INTERFACE')
            delay = self.api('pm', 'POST', self.base + '/decisions', {
                'decision_kind': 'rebaseline', 'title': '【模拟】ID客户反馈延期的影响评估',
                'outcome': '方案确认从10/02调整至10/09；ID冻结目标从10/16调整至10/23。',
                'context': '仅为情景演示，无真实客户。ID方案尚未完成，三专业预研已经完成。',
                'rationale': '保留原计划及修改原因；先核对结构板框、PCB、样机受影响范围。',
                'consequence': '项目经理与接收方另行确认板框/PCB/EVT日期；不会自动顺延所有任务，也不能提前开展依赖冻结输入的工作。',
                'evidence_refs': [self.tasks['ID-CONCEPT']['id'], self.tasks['ID-FREEZE']['id']],
            }, label='模拟ID延期，保留原计划与影响决策')
            self.api('pm', 'PATCH', self.url('ID-CONCEPT'), {'due_date': '2026-10-09'})
            self.api('pm', 'PATCH', self.url('ID-FREEZE'), {'start_date': '2026-10-12', 'due_date': '2026-10-23'})
            self.finish('ID-CONCEPT', delay['id'])
            self.finish('INTERFACE', ref)
        elif phase == 'design':
            self.blocked('MD-ENVELOPE')
            self.blocked('EE-PCB')
            self.start('FW-BASE')
            values = self.snapshot('ID尚未冻结，固件基础开发可开展，结构板框等待', ['ID-FREEZE', 'FW-BASE', 'MD-ENVELOPE'])
            assert values['ID-FREEZE']['status'] == 'todo'
            assert values['FW-BASE']['status'] == 'in_progress'
            assert values['MD-ENVELOPE']['readiness'] == 'waiting'
            self.finish('FW-BASE', ref)
            self.finish('ID-FREEZE', ref)
            self.finish('MD-ENVELOPE', ref)
            self.start('MD-DETAIL')
            self.start('EE-PCB')
            values = self.snapshot('板框基线发布后，结构细化与PCB并行', ['MD-DETAIL', 'EE-PCB'])
            assert all(task['status'] == 'in_progress' for task in values.values())
            self.blocked('FW-BRINGUP')
            self.finish('MD-DETAIL', ref)
            self.finish('EE-PCB', ref)
            self.finish('FW-BRINGUP', ref)
            self.finish('DESIGN-REVIEW', ref)
        else:
            for item in self.template['tasks']:
                if item['stage'] == phase:
                    self.finish(item['code'], ref)
