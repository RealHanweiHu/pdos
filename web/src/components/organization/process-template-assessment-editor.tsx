"use client";
import { NamedSignerEditor, NamedSignerRehearsal, type NamedSlots, type SignerCase } from "./process-template-named-signers";
import { RiskFieldsEditor, type RiskField } from "./process-template-risk-fields";
import { RiskFieldRehearsalEditor, type RiskFieldCase } from "./process-template-risk-field-rehearsal";
import { TaskFieldsEditor, type TaskField } from "./process-template-task-fields";
import { TaskFieldRehearsalEditor, type TaskFieldCase } from "./process-template-task-field-rehearsal";

import { useState } from "react";
import { FieldRehearsalEditor, type FieldCase } from "./process-template-field-rehearsal";
import { IssueFieldsEditor, type IssueField } from "./process-template-fields";
import { ApprovalRoutesEditor, ApprovalRehearsalEditor, approvalExamples, type ApprovalRoutes, type ApprovalCase } from "./process-template-approval-routes";
import { ReminderPolicyEditor, type ReminderPolicy } from "./process-template-reminders";
import { ReminderRehearsalEditor, type ReminderCase } from "./process-template-reminder-rehearsal";
import { TaskRouteEditor, type TaskRoutes } from "./process-template-routing";
import { RouteRehearsalEditor, normalizedRoutingCases, type RoutingCase } from "./process-template-route-rehearsal";
import { GateRulesEditor, GateRehearsalEditor, gateExamples, type GateRequirements, type GateCheck } from "./process-template-gates";
import { Button } from "@/components/ui/button";

type Task = { code: string; title: string; title_en: string; stage: string; responsibility: string; discipline: string; depends_on: string[]; output: string; receiver: string; required_features: string[]; hard_milestone: boolean; minimum_evidence: string[] };
type Feature = { label: string; label_en: string; default: boolean };
type Stage = { code: string; sequence: number; name: string; name_en: string; description?: string };
type Case = { gate_checks?: GateCheck[]; name: string; features: Record<string, boolean>; completed_codes: string[]; expect_valid: boolean; expected_ready: Record<string, boolean> };
type Explanation = { stage_codes?: string[]; source: "instruction" | "acceptance_criteria"; quote: string; disposition: "configured" | "unchanged" | "extension" | "clarification"; explanation: string; task_codes: string[]; feature_keys: string[] };
export type Assessment = { risk_fields?: RiskField[] | null; risk_field_cases?: RiskFieldCase[]; named_gate_slots?: NamedSlots | null; signer_cases?: SignerCase[]; task_fields?: TaskField[] | null; task_field_cases?: TaskFieldCase[]; issue_fields?: IssueField[] | null; field_cases?: FieldCase[]; approval_routes?: ApprovalRoutes | null; approval_cases?: ApprovalCase[]; reminder_policy?: ReminderPolicy | null; reminder_cases?: ReminderCase[]; task_routes?: TaskRoutes | null; routing_cases?: RoutingCase[]; stage_upserts?: Stage[]; gate_requirements?: GateRequirements | null; summary: string; name: string | null; name_en: string | null; task_upserts: Task[]; task_removals: string[]; feature_upserts: Record<string, Feature>; extension_requests: string[]; open_questions: string[]; requirements: Explanation[]; cases: Case[] };
export type TemplateBase = { risk_fields?: RiskField[]; named_gate_slots?: NamedSlots; task_fields?: TaskField[]; issue_fields?: IssueField[]; approval_routes?: ApprovalRoutes; task_routes?: TaskRoutes; id: string; name: string; name_en: string; tasks: Task[]; features: Record<string, Feature>; stages: Stage[]; gate_requirements?: GateRequirements; contract_tasks?: Record<string, Task> };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const roles: Record<string, string> = { product_management: "产品/项目", industrial_design: "ID", mechanical: "结构", hardware: "硬件", firmware: "固件", design_quality: "DQE", supplier_quality: "SQE", industrial_engineering: "IE" };
const evidence: Record<string, string> = { work_output: "工作输出", versioned_output: "版本化交付", receiver_confirmation: "接收确认" };
const dispositions: Record<Explanation["disposition"], string> = { configured: "已体现在配置中", unchanged: "保持原规则", extension: "待决扩展", clarification: "待澄清" };
const selection = (event: React.ChangeEvent<HTMLSelectElement>) => Array.from(event.target.selectedOptions, item => item.value);

export function normalizedAssessment(value: Assessment): Assessment {
  return { ...value, ...(value.routing_cases ? { routing_cases: normalizedRoutingCases(value.routing_cases) } : {}), extension_requests: value.extension_requests.map(item => item.trim()).filter(Boolean), open_questions: value.open_questions.map(item => item.trim()).filter(Boolean) };
}

export function ProcessTemplateAssessmentEditor({ value, base, gateBaseline, reminderBaseline, contractVersion, onChange }: {
  value: Assessment; base: TemplateBase; reminderBaseline: ReminderPolicy; gateBaseline: GateRequirements; contractVersion: string; onChange: (value: Assessment) => void;
}) {
  const [code, setCode] = useState(value.task_upserts[0]?.code ?? base.tasks[0]?.code ?? "");
  const [featureKey, setFeatureKey] = useState("");
  const tasks = [...base.tasks.filter(task => !value.task_upserts.some(item => item.code === task.code)), ...value.task_upserts];
  const effectiveTasks = tasks.filter(task => !value.task_removals.includes(task.code));
  const current = value.task_upserts.find(task => task.code === code);
  const original = base.tasks.find(task => task.code === code);
  const protectedTask = original?.hard_milestone ? original : base.contract_tasks?.[code] ?? (!base.id.startsWith("org-") ? original : undefined);
  const features = { ...base.features, ...value.feature_upserts };
  const riskFieldsEnabled = contractVersion === "process-template-configuration-v9";
  const namedSignersEnabled = riskFieldsEnabled || contractVersion === "process-template-configuration-v8";
  const taskFieldsEnabled = namedSignersEnabled || contractVersion === "process-template-configuration-v7";
  const fieldsEnabled = taskFieldsEnabled || contractVersion === "process-template-configuration-v6";
  const approvalEnabled = fieldsEnabled || contractVersion === "process-template-configuration-v5";
  const reminderEnabled = approvalEnabled || contractVersion === "process-template-configuration-v4";
  const routingEnabled = reminderEnabled || contractVersion === "process-template-configuration-v3";
  const extended = routingEnabled || contractVersion === "process-template-configuration-v2";
  const stages = base.stages.map(stage => value.stage_upserts?.find(item => item.code === stage.code) ?? stage);
  const minimumGates = base.gate_requirements ?? gateBaseline;
  const configuredGates = value.gate_requirements ?? minimumGates;
  const edit = (change: Partial<Assessment>) => onChange({ ...value, ...change });
  const editTask = (change: Partial<Task>) => edit({ task_upserts: value.task_upserts.map(task => task.code === code ? { ...task, ...change } : task) });
  const editFeature = (key: string, change: Partial<Feature>) => edit({ feature_upserts: { ...value.feature_upserts, [key]: { ...features[key], ...change } } });
  const editCase = (index: number, change: Partial<Case>) => edit({ cases: value.cases.map((item, n) => n === index ? { ...item, ...change } : item) });
  const editExplanation = (index: number, change: Partial<Explanation>) => edit({ requirements: value.requirements.map((item,n) => n === index ? { ...item, ...change } : item) });

  return <div className="space-y-4 rounded-md border p-3">
    <p className="text-sm text-muted-foreground">在此修改将要接受的建议。原 AI 建议保留；每次修改后须重新预览，接受后仍需单独应用。</p>
    <label className="block text-sm">建议摘要<textarea className={field} rows={3} maxLength={2000} value={value.summary} onChange={event => edit({ summary: event.target.value })}/></label>
    <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">模板名称<input className={field} maxLength={200} value={value.name ?? base.name} onChange={event => edit({ name: event.target.value })}/></label><label className="text-sm">英文名称<input className={field} maxLength={200} value={value.name_en ?? base.name_en} onChange={event => edit({ name_en: event.target.value })}/></label></div>
    {extended && <>
      <details><summary className="cursor-pointer text-sm font-medium">阶段名称与办理说明</summary><p className="mt-2 text-xs text-muted-foreground">仅调整现有阶段名称和说明。阶段类型、顺序及在途项目保留。</p>{stages.map(stage => <div key={stage.code} className="mt-3 rounded-md border p-3"><p className="text-sm">阶段 {stage.sequence} · {stage.code}</p>{([['name','中文名称'],['name_en','英文名称'],['description','办理说明']] as const).map(([key,label]) => <label key={key} className="mt-2 block text-sm">{label}<textarea className={field} rows={key === "description" ? 2 : 1} maxLength={key === "description" ? 5000 : 200} value={stage[key] ?? ""} onChange={event => edit({ stage_upserts: [...(value.stage_upserts ?? []).filter(item => item.code !== stage.code), { ...stage, [key]: event.target.value }] })}/></label>)}{value.stage_upserts?.some(item => item.code === stage.code) && <Button type="button" size="sm" variant="ghost" onClick={() => edit({ stage_upserts: value.stage_upserts?.filter(item => item.code !== stage.code) })}>保留此阶段的原配置</Button>}</div>)}</details>
      <GateRulesEditor stages={stages} minimum={minimumGates} value={configuredGates} onChange={gate_requirements => edit({ gate_requirements })}/>
    </>}
    <details open><summary className="cursor-pointer text-sm font-medium">任务内容与依赖</summary><div className="mt-3 space-y-3">
      <label className="block text-sm">任务<select className={field} value={code} onChange={event => setCode(event.target.value)}>{tasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}{value.task_removals.includes(task.code) ? "（拟移除）" : ""}</option>)}</select></label>
      {routingEnabled && !value.task_removals.includes(code) && <TaskRouteEditor code={code} routes={value.task_routes ?? base.task_routes ?? {}} onChange={task_routes => edit({ task_routes })}/>}
      {!current && original && !value.task_removals.includes(code) && <Button type="button" size="sm" variant="outline" onClick={() => edit({ task_upserts: [...value.task_upserts, structuredClone(original)] })}>修改此任务</Button>}
      {current && <div className="space-y-3 rounded-md bg-muted/30 p-3">
        <div className="grid gap-3 sm:grid-cols-2">{([['title','名称'],['title_en','英文名称'],['output','交付内容'],['receiver','接收要求']] as const).map(([key,label]) => <label key={key} className="text-sm">{label}<textarea className={field} maxLength={key === "output" ? 5000 : key === "receiver" ? 2000 : 512} value={current[key]} onChange={event => editTask({ [key]: event.target.value })}/></label>)}</div>
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">阶段<select className={field} value={current.stage} disabled={!!protectedTask} onChange={event => editTask({ stage: event.target.value })}>{base.stages.map(stage => <option key={stage.code} value={stage.code}>{stage.name}</option>)}</select></label><label className="text-sm">专业职责<select className={field} value={current.responsibility} onChange={event => editTask({ responsibility: event.target.value, discipline: roles[event.target.value] })}>{Object.entries(roles).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <details><summary className="cursor-pointer text-sm">前置任务</summary><div className="mt-2 max-h-52 space-y-2 overflow-auto">{effectiveTasks.filter(task => task.code !== code).map(task => <label key={task.code} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={current.depends_on.includes(task.code)} disabled={protectedTask?.depends_on.includes(task.code)} onChange={event => editTask({ depends_on: event.target.checked ? [...current.depends_on,task.code] : current.depends_on.filter(key => key !== task.code) })}/>{task.code} · {task.title}</label>)}</div></details>
        <div className="flex flex-wrap gap-3">{Object.entries(features).map(([key,feature]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={current.required_features.includes(key)} disabled={!!protectedTask && !protectedTask.required_features.includes(key)} onChange={event => editTask({ required_features: event.target.checked ? [...current.required_features,key] : current.required_features.filter(item => item !== key) })}/>仅在具有{feature.label}时适用</label>)}</div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={current.hard_milestone} disabled={protectedTask?.hard_milestone} onChange={event => editTask({ hard_milestone: event.target.checked })}/>必须完成冻结或接收</label>
        <div className="flex flex-wrap gap-3">{Object.entries(evidence).map(([key,label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={current.minimum_evidence.includes(key)} disabled={protectedTask?.minimum_evidence.includes(key)} onChange={event => editTask({ minimum_evidence: event.target.checked ? [...current.minimum_evidence,key] : current.minimum_evidence.filter(item => item !== key) })}/>{label}</label>)}</div>
        <Button type="button" size="sm" variant="ghost" onClick={() => { edit({ task_upserts: value.task_upserts.filter(task => task.code !== code), ...(routingEnabled && !original ? { task_routes: Object.fromEntries(Object.entries(value.task_routes ?? base.task_routes ?? {}).filter(([key]) => key !== code)) } : {}) }); if(!original) setCode(base.tasks[0]?.code ?? ""); }}>{original ? "撤销对此任务的修改" : "取消本次新增任务"}</Button>
      </div>}
      {original && !protectedTask && <Button type="button" size="sm" variant="outline" onClick={() => edit({ task_removals: value.task_removals.includes(code) ? value.task_removals.filter(item => item !== code) : [...value.task_removals,code], task_upserts: value.task_upserts.filter(task => task.code !== code), ...(routingEnabled && !value.task_removals.includes(code) ? { task_routes: Object.fromEntries(Object.entries(value.task_routes ?? base.task_routes ?? {}).filter(([key]) => key !== code)) } : {}) })}>{value.task_removals.includes(code) ? "保留此普通任务" : "建议移除此普通任务"}</Button>}
      <Button type="button" size="sm" variant="outline" disabled={effectiveTasks.length >= 200} onClick={() => {
        let index=tasks.length+1; while(tasks.some(task => task.code === `CUSTOM-${index}`)) index++;
        const next=`CUSTOM-${index}`;
        edit({ task_upserts: [...value.task_upserts, { code: next, title: "新增任务", title_en: "New task", stage: base.stages[0].code, responsibility: "product_management", discipline: "产品/项目", depends_on: [], output: "请填写交付要求", receiver: "请填写接收要求", required_features: [], hard_milestone: false, minimum_evidence: ["work_output"] }] }); setCode(next);
      }}>新增任务</Button>
    </div></details>
    <details><summary className="cursor-pointer text-sm font-medium">功能配置</summary><div className="mt-3 space-y-3">
      {Object.entries(value.feature_upserts).map(([key,feature]) => <div key={key} className="space-y-2 rounded-md border p-2"><p className="text-sm">{key}</p><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">名称<input className={field} maxLength={200} value={feature.label} onChange={event => editFeature(key,{ label: event.target.value })}/></label><label className="text-sm">英文名称<input className={field} maxLength={200} value={feature.label_en} onChange={event => editFeature(key,{ label_en: event.target.value })}/></label></div><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={feature.default} onChange={event => editFeature(key,{ default: event.target.checked })}/>默认适用</label><Button type="button" size="sm" variant="ghost" onClick={() => edit({ feature_upserts: Object.fromEntries(Object.entries(value.feature_upserts).filter(([name]) => name !== key)) })}>撤销本项功能配置</Button></div>)}
      <label className="block text-sm">已有功能<select className={field} value="" onChange={event => { const key=event.target.value; if(key) editFeature(key,{}); }}><option value="">选择要修改的功能</option>{Object.entries(base.features).map(([key,feature]) => <option key={key} value={key}>{feature.label}</option>)}</select></label>
      <label className="block text-sm">新增功能标识<input className={field} maxLength={64} value={featureKey} onChange={event => setFeatureKey(event.target.value)}/></label><Button type="button" size="sm" variant="outline" disabled={!featureKey || Boolean(features[featureKey]) || Object.keys(features).length >= 30} onClick={() => { edit({ feature_upserts: { ...value.feature_upserts, [featureKey]: { label: featureKey, label_en: featureKey, default: false } } }); setFeatureKey(""); }}>增加功能条件</Button>
    </div></details>
    <label className="block text-sm">待决扩展（每行一项）<textarea className={field} rows={3} value={value.extension_requests.join("\n")} maxLength={40000} onChange={event => edit({ extension_requests: event.target.value.split("\n") })}/></label>
    <label className="block text-sm">待澄清的问题（每行一项）<textarea className={field} rows={3} value={value.open_questions.join("\n")} maxLength={20000} onChange={event => edit({ open_questions: event.target.value.split("\n") })}/></label>
    <details><summary className="cursor-pointer text-sm font-medium">原始要求逐项说明</summary><div className="mt-3 space-y-3">
      {value.requirements.map((item,index) => <div key={index} className="space-y-2 rounded-md border p-3"><label className="block text-sm">引用来源<select className={field} value={item.source} onChange={event => editExplanation(index,{ source: event.target.value as Explanation["source"] })}><option value="instruction">原管理要求</option><option value="acceptance_criteria">原验收预期</option></select></label><label className="block text-sm">原文引用<textarea className={field} maxLength={2000} value={item.quote} onChange={event => editExplanation(index,{ quote: event.target.value })}/></label><label className="block text-sm">处理方式<select className={field} value={item.disposition} onChange={event => editExplanation(index,{ disposition: event.target.value as Explanation["disposition"] })}>{Object.entries(dispositions).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="block text-sm">处理说明<textarea className={field} maxLength={2000} value={item.explanation} onChange={event => editExplanation(index,{ explanation: event.target.value })}/></label><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">关联任务（可多选）<select multiple className={`${field} h-24`} value={item.task_codes} onChange={event => editExplanation(index,{ task_codes: selection(event) })}>{tasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label><label className="text-sm">关联功能（可多选）<select multiple className={`${field} h-24`} value={item.feature_keys} onChange={event => editExplanation(index,{ feature_keys: selection(event) })}>{Object.entries(features).map(([key,feature]) => <option key={key} value={key}>{feature.label}</option>)}</select></label></div>{extended && <label className="block text-sm">关联阶段（含签核配置，可多选）<select multiple className={`${field} h-24`} value={item.stage_codes ?? []} onChange={event => editExplanation(index, { stage_codes: selection(event) })}>{stages.map(stage => <option key={stage.code} value={stage.code}>{stage.name}</option>)}</select></label>}<Button type="button" size="sm" variant="ghost" disabled={value.requirements.length <= 1} onClick={() => edit({ requirements: value.requirements.filter((_,n) => n !== index) })}>移除此项说明</Button></div>)}
      <Button type="button" size="sm" variant="outline" disabled={value.requirements.length >= 50} onClick={() => edit({ requirements: [...value.requirements, { source: "instruction", quote: "", disposition: "configured", explanation: "", task_codes: [], feature_keys: [] }] })}>补充一条要求说明</Button>
    </div></details>
    {namedSignersEnabled && <>
      <NamedSignerEditor stages={stages} requirements={configuredGates} value={value.named_gate_slots ?? base.named_gate_slots ?? {}} onChange={named_gate_slots => edit({ named_gate_slots })}/>
      <NamedSignerRehearsal stages={stages} policy={value.named_gate_slots ?? base.named_gate_slots ?? {}} value={value.signer_cases ?? []} onChange={signer_cases => edit({ signer_cases })}/>
    </>}
    {riskFieldsEnabled && <>
      <RiskFieldsEditor value={value.risk_fields ?? base.risk_fields ?? []} onChange={risk_fields => edit({ risk_fields })}/>
      <RiskFieldRehearsalEditor fields={value.risk_fields ?? base.risk_fields ?? []} value={value.risk_field_cases ?? []} onChange={risk_field_cases => edit({ risk_field_cases })}/>
    </>}
    {taskFieldsEnabled && <>
      <TaskFieldsEditor value={value.task_fields ?? base.task_fields ?? []} onChange={task_fields => edit({ task_fields })}/>
      <TaskFieldRehearsalEditor fields={value.task_fields ?? base.task_fields ?? []} value={value.task_field_cases ?? []} onChange={task_field_cases => edit({ task_field_cases })}/>
    </>}
    {fieldsEnabled && <>
      <IssueFieldsEditor value={value.issue_fields ?? base.issue_fields ?? []} onChange={issue_fields => edit({ issue_fields })}/>
      <FieldRehearsalEditor fields={value.issue_fields ?? base.issue_fields ?? []} value={value.field_cases ?? []} onChange={field_cases => edit({ field_cases })}/>
    </>}
    {approvalEnabled && <>
      <ApprovalRoutesEditor stages={stages} requirements={configuredGates} value={value.approval_routes ?? base.approval_routes ?? {}} onChange={approval_routes => edit({ approval_routes })}/>
      <ApprovalRehearsalEditor stages={stages} value={value.approval_cases ?? []} onChange={approval_cases => edit({ approval_cases })}/>
      <Button type="button" size="sm" variant="outline" onClick={() => edit({ approval_cases: approvalExamples(value.approval_routes ?? base.approval_routes ?? {}, configuredGates) })}>以当前签核依赖示例替换演练场景</Button>
    </>}
    {reminderEnabled && <>
      <ReminderPolicyEditor value={value.reminder_policy ?? reminderBaseline} onChange={reminder_policy => edit({ reminder_policy })}/>
      <ReminderRehearsalEditor policy={value.reminder_policy ?? reminderBaseline} value={value.reminder_cases ?? []} onChange={reminder_cases => edit({ reminder_cases })}/>
    </>}
    {routingEnabled && <RouteRehearsalEditor template={{ features, tasks: effectiveTasks, task_routes: value.task_routes ?? base.task_routes }} value={value.routing_cases ?? []} onChange={routing_cases => edit({ routing_cases })}/>}
    <details><summary className="cursor-pointer text-sm font-medium">修改模拟场景与预期</summary><div className="mt-3 space-y-3">
      {extended && <Button type="button" size="sm" variant="outline" onClick={() => { const checks = gateExamples(gateBaseline, configuredGates); edit({ cases: value.cases.map((item, index) => index < 2 ? { ...item, gate_checks: checks[index] } : item) }); }}>用签核正反例示例替换前两个场景的签核输入</Button>}
      {value.cases.map((item,index) => <div key={index} className="space-y-2 rounded-md border p-3"><label className="block text-sm">场景名称<input className={field} maxLength={200} value={item.name} onChange={event => editCase(index,{ name: event.target.value })}/></label><div className="flex flex-wrap gap-3">{Object.entries(features).map(([key,feature]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={item.features[key] ?? feature.default} onChange={event => editCase(index,{ features: { ...item.features,[key]: event.target.checked } })}/>{feature.label}</label>)}</div><label className="block text-sm">模拟已完成任务（可多选）<select multiple className={`${field} h-24`} value={item.completed_codes} onChange={event => editCase(index,{ completed_codes: selection(event) })}>{effectiveTasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label>
        {extended && <GateRehearsalEditor stages={stages} value={item.gate_checks ?? []} onChange={gate_checks => editCase(index, { gate_checks })}/>}
        {Object.entries(item.expected_ready).map(([key,ready]) => <div key={key} className="flex flex-wrap items-center gap-2 text-sm"><span>{tasks.find(task => task.code === key)?.title ?? key}</span><select className="rounded-md border bg-background p-2" aria-label={`${key}预期`} value={String(ready)} onChange={event => editCase(index,{ expected_ready: { ...item.expected_ready,[key]: event.target.value === "true" } })}><option value="true">应可启动</option><option value="false">应不可启动</option></select><Button type="button" size="sm" variant="ghost" onClick={() => editCase(index,{ expected_ready: Object.fromEntries(Object.entries(item.expected_ready).filter(([code]) => code !== key)) })}>移除此判断</Button></div>)}
        <label className="block text-sm">增加一个判断<select className={field} value="" onChange={event => { if(event.target.value) editCase(index,{ expected_ready: { ...item.expected_ready,[event.target.value]: true } }); }}><option value="">选择任务</option>{effectiveTasks.filter(task => !(task.code in item.expected_ready)).map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!item.expect_valid} onChange={event => editCase(index,{ expect_valid: !event.target.checked })}/>此场景应拒绝无效输入</label><Button type="button" size="sm" variant="ghost" disabled={value.cases.length <= 2} onClick={() => edit({ cases: value.cases.filter((_,n) => n !== index) })}>移除此场景</Button>
      </div>)}
      <Button type="button" size="sm" variant="outline" disabled={value.cases.length >= 20} onClick={() => edit({ cases: [...value.cases, { name: "新场景", features: {}, completed_codes: [], expect_valid: true, expected_ready: {} }] })}>增加模拟场景</Button>
    </div></details>
  </div>;
}
