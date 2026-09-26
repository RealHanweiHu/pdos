"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { RiskFieldsEditor, RiskFieldDifference, type RiskField } from "./process-template-risk-fields";
import { RiskFieldRehearsalEditor, RiskFieldRehearsalResults, type RiskFieldCase } from "./process-template-risk-field-rehearsal";
import { TaskFieldsEditor, TaskFieldDifference, type TaskField } from "./process-template-task-fields";
import { TaskFieldRehearsalEditor, TaskFieldRehearsalResults, type TaskFieldCase } from "./process-template-task-field-rehearsal";
import { FieldRehearsalEditor, FieldRehearsalResults, type FieldCase } from "./process-template-field-rehearsal";
import { IssueFieldsEditor, IssueFieldDifference, type IssueField } from "./process-template-fields";
import { ApprovalRoutesEditor, ApprovalRehearsalEditor, ApprovalRehearsalResults, ApprovalRouteDifference, approvalExamples, type ApprovalRoutes, type ApprovalCase } from "./process-template-approval-routes";
import { ReminderRehearsalEditor, ReminderRehearsalResults, type ReminderCase } from "./process-template-reminder-rehearsal";
import { ReminderPolicyEditor, reminderLabels, reminderValue, type ReminderPolicy } from "./process-template-reminders";
import { RouteRehearsalEditor, RouteRehearsalResults, routingExamples, normalizedRoutingCases, type RoutingCase } from "./process-template-route-rehearsal";
import { TaskRouteEditor, professionalRoles, type TaskRoutes } from "./process-template-routing";
import { NamedSignerEditor, NamedSignerRehearsal, NamedSignerDifference, NamedSignerResults, namedSignerExamples, type NamedSlots, type SignerCase } from "./process-template-named-signers";
import { GateRulesEditor, GateRehearsalEditor, gateExamples, gateSlots, gateRequirements, type GateRequirements, type GateCheck, type GateSlot, type GateRequirement } from "@/components/organization/process-template-gates";
import { ProcessTemplateBriefs } from "@/components/organization/process-template-briefs";

type Row = Record<string, unknown>;
type Task = { code: string; title: string; title_en: string; stage: string; responsibility: string; discipline: string; depends_on: string[]; output: string; receiver: string; required_features: string[]; hard_milestone: boolean; minimum_evidence: string[] };
type Stage = { code: string; sequence: number; name: string; name_en: string; description?: string };
type Feature = { label: string; label_en: string; default: boolean };
type Template = { risk_fields?: RiskField[]; named_gate_slots?: NamedSlots; task_fields?: TaskField[]; issue_fields?: IssueField[]; approval_routes?: ApprovalRoutes; reminder_policy?: ReminderPolicy; task_routes?: TaskRoutes; gate_baseline: GateRequirements; gate_requirements?: GateRequirements; id: string; version: number; name: string; name_en: string; source_digest: string; release_id: string | null; contract_tasks?: Record<string, Task>; tasks: Task[]; stages: Stage[]; features: Record<string, Feature> };
type Configuration = { risk_fields?: RiskField[] | null; named_gate_slots?: NamedSlots | null; task_fields?: TaskField[] | null; issue_fields?: IssueField[] | null; approval_routes?: ApprovalRoutes | null; reminder_policy?: ReminderPolicy | null; task_routes?: TaskRoutes | null; gate_requirements?: GateRequirements | null; stages?: Stage[] | null; name: string; name_en: string; tasks: Task[]; features: Record<string, Feature>; extension_requests: string[] };
type Case = { gate_checks?: GateCheck[]; name: string; features: Record<string, boolean>; completed_codes: string[]; expect_valid: boolean; expected_ready: Record<string, boolean> };
const txt = (value: unknown) => value == null ? "" : String(value);
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const basePath = "/api/admin/organization/process-templates";
const roles: Record<string, string> = { product_management: "产品/项目", industrial_design: "ID", mechanical: "结构", hardware: "硬件", firmware: "固件", design_quality: "DQE", supplier_quality: "SQE", industrial_engineering: "IE" };
const labels: Record<string, string> = { title: "任务名称", title_en: "英文名称", stage: "阶段", responsibility: "专业职责", discipline: "专业说明", depends_on: "前置任务", output: "交付内容", receiver: "接收要求", required_features: "适用功能", hard_milestone: "必须冻结/接收", minimum_evidence: "最低证据" };
const evidence: Record<string, string> = { work_output: "工作输出", versioned_output: "版本化交付", receiver_confirmation: "接收确认" };
function display(value: unknown) { return Array.isArray(value) ? value.join("、") || "无" : typeof value === "boolean" ? value ? "是" : "否" : txt(value) || "无"; }
async function api(path: string, body?: unknown): Promise<Row> {
  const response = await fetch(path, { cache: "no-store", ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(txt(obj(obj(value).detail).message) || "组织模板暂不可用，请保留输入后重试");
  return value;
}
function examples(template: Template): Case[] {
  const features = Object.fromEntries(Object.entries(template.features).map(([key, item]) => [key, item.default]));
  const tasks = template.tasks.filter(task => task.required_features.every(key => features[key]));
  const first = tasks.find(task => !task.depends_on.length), blocked = tasks.find(task => task.depends_on.length);
  const [gatePositive, gateNegative] = gateExamples(template.gate_baseline, template.gate_requirements ?? template.gate_baseline);
  return [
    { gate_checks: gatePositive, name: "初始条件下可启动", features, completed_codes: [], expect_valid: true, expected_ready: first ? { [first.code]: true } : {} },
    { gate_checks: gateNegative, name: "缺少前置时不可启动", features, completed_codes: [], expect_valid: true, expected_ready: blocked ? { [blocked.code]: false } : {} },
  ];
}

export function ProcessTemplateLibrary() {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [source, setSource] = useState<Template | null>(null), [configuration, setConfiguration] = useState<Configuration | null>(null);
  const [copy, setCopy] = useState(true), [code, setCode] = useState(""), [reason, setReason] = useState("");
  const [sourceBrief, setSourceBrief] = useState<Row | null>(null);
  const [taskCode, setTaskCode] = useState(""), [featureCode, setFeatureCode] = useState("");
  const [detail, setDetail] = useState<Row | null>(null), [cases, setCases] = useState<Case[]>([]), [preview, setPreview] = useState<Row | null>(null);
  const [signerCases, setSignerCases] = useState<SignerCase[]>([]);
  const [riskFieldCases, setRiskFieldCases] = useState<RiskFieldCase[]>([]);
  const [taskFieldCases, setTaskFieldCases] = useState<TaskFieldCase[]>([]);
  const [fieldCases, setFieldCases] = useState<FieldCase[]>([]);
  const [approvalCases, setApprovalCases] = useState<ApprovalCase[]>([]);
  const [reminderCases, setReminderCases] = useState<ReminderCase[]>([]);
  const [routingCases, setRoutingCases] = useState<RoutingCase[]>([]);
  const [releaseReason, setReleaseReason] = useState(""), [confirmed, setConfirmed] = useState(false), [notice, setNotice] = useState("");
  const saveAttempt = useRef({ signature: "", id: "" }), releaseAttempt = useRef({ signature: "", id: "" });
  const templates = (data?.catalog ?? []) as Template[];
  const selectedTask = configuration?.tasks.find(task => task.code === taskCode);
  const baseTask = source?.tasks.find(task => task.code === taskCode);
  const originalTask = baseTask?.hard_milestone ? baseTask : source?.contract_tasks?.[taskCode] ?? (!source?.id.startsWith("org-") ? baseTask : undefined);
  const revision = obj(detail?.revision), snapshot = revision.snapshot ? { ...(revision.snapshot as Template), gate_baseline: detail?.gate_baseline as GateRequirements } : undefined;
  const briefSource = source && (!copy || code.trim()) ? { template_id: copy ? `org-${code}` : source.id, base_template_id: source.id, base_version: source.version, base_digest: source.source_digest, expected_release_id: copy ? null : source.release_id } : null;
  const briefMatches = !sourceBrief || (briefSource && sourceBrief.template_id === briefSource.template_id && sourceBrief.base_template_id === briefSource.base_template_id && sourceBrief.base_version === briefSource.base_version && sourceBrief.base_digest === briefSource.base_digest && sourceBrief.base_release_id === briefSource.expected_release_id);
  const load = async () => setData(await api(basePath));
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "办理失败"); } finally { setBusy(false); } }
  function selectSource(template: Template) {
    setSourceBrief(null);
    setSource(template); setCopy(!template.id.startsWith("org-")); setCode(template.id.replace(/^org-/, ""));
    setConfiguration({ risk_fields: structuredClone(template.risk_fields ?? []), named_gate_slots: structuredClone(template.named_gate_slots ?? {}), task_fields: structuredClone(template.task_fields ?? []), issue_fields: structuredClone(template.issue_fields ?? []), approval_routes: structuredClone(template.approval_routes ?? {}), reminder_policy: structuredClone(template.reminder_policy ?? data?.reminder_defaults as ReminderPolicy), task_routes: structuredClone(template.task_routes ?? {}), gate_requirements: structuredClone(template.gate_requirements ?? template.gate_baseline), stages: structuredClone(template.stages), name: template.name, name_en: template.name_en, tasks: structuredClone(template.tasks), features: structuredClone(template.features), extension_requests: [] });
    setTaskCode(template.tasks[0]?.code ?? ""); setReason(""); setNotice("");
  }
  function editTask(change: Partial<Task>) { if (configuration) setConfiguration({ ...configuration, tasks: configuration.tasks.map(task => task.code === taskCode ? { ...task, ...change } : task) }); }
  async function open(id: string) {
    const value = await api(`${basePath}/revisions/${id}`);
    const accepted = obj(value.accepted_rehearsal);
    const template = obj(value.revision).snapshot as Template;
    setSignerCases(Array.isArray(accepted.signer_cases) ? accepted.signer_cases as SignerCase[] : namedSignerExamples(template.named_gate_slots ?? {}));
    setApprovalCases(Array.isArray(accepted.approval_cases) ? accepted.approval_cases as ApprovalCase[] : approvalExamples(template.approval_routes ?? {}, template.gate_requirements ?? value.gate_baseline as GateRequirements));
    setRiskFieldCases(Array.isArray(accepted.risk_field_cases) ? accepted.risk_field_cases as RiskFieldCase[] : value.risk_field_examples as RiskFieldCase[]);
    setTaskFieldCases(Array.isArray(accepted.task_field_cases) ? accepted.task_field_cases as TaskFieldCase[] : value.task_field_examples as TaskFieldCase[]);
    setFieldCases(Array.isArray(accepted.field_cases) ? accepted.field_cases as FieldCase[] : value.field_examples as FieldCase[]);
    setDetail(value); setPreview(null); setConfirmed(false); setReleaseReason("");
    setCases(Array.isArray(accepted.cases) ? accepted.cases as Case[] : examples({ ...template, gate_baseline: value.gate_baseline as GateRequirements }));
    setRoutingCases(Array.isArray(accepted.routing_cases) ? accepted.routing_cases as RoutingCase[] : routingExamples(template));
    setReminderCases(Array.isArray(accepted.reminder_cases) ? accepted.reminder_cases as ReminderCase[] : value.reminder_examples as ReminderCase[]);
  }

  function editCase(index: number, change: Partial<Case>) { setCases(current => current.map((item, n) => n === index ? { ...item, ...change } : item)); setPreview(null); setConfirmed(false); }
  async function save() {
    if (!source || !configuration) return;
    if (!briefMatches) throw new Error("当前来源与关联管理要求不同，请恢复原来源，或明确解除关联后继续。");
    const payload = { template_id: copy ? `org-${code}` : source.id, base_template_id: source.id, base_version: source.version, base_digest: source.source_digest, expected_release_id: copy ? null : source.release_id, source_brief_id: sourceBrief?.id ?? null, reason, configuration: { ...configuration, extension_requests: configuration.extension_requests.map(item => item.trim()).filter(Boolean) } };
    const signature = JSON.stringify(payload);
    if (saveAttempt.current.signature !== signature) saveAttempt.current = { signature, id: crypto.randomUUID() };
    const value = await api(`${basePath}/revisions`, { ...payload, request_id: saveAttempt.current.id });
    await load(); await open(txt(value.id)); setNotice("配置候选已保存，尚未发布。请核对差异并演练。");
  }
  async function release(action: "publish" | "rollback") {
    if (!preview) return;
    const payload = { cases, risk_field_cases: riskFieldCases, signer_cases: signerCases, task_field_cases: taskFieldCases, field_cases: fieldCases, approval_cases: approvalCases, reminder_cases: reminderCases, routing_cases: normalizedRoutingCases(routingCases), expected_release_id: preview.current_release_id, preview_digest: preview.preview_digest, action, reason: releaseReason, confirmed: true };
    const signature = JSON.stringify([revision.id, payload]);
    if (releaseAttempt.current.signature !== signature) releaseAttempt.current = { signature, id: crypto.randomUUID() };
    await api(`${basePath}/revisions/${txt(revision.id)}/release`, { ...payload, request_id: releaseAttempt.current.id });
    await load(); await open(txt(revision.id)); setNotice(action === "publish" ? "已发布组织模板。后续项目可选择，在途项目保留原版。" : "已回退组织模板的当前发布版，在途项目保留原版。");
  }

  return <details className="mt-6 rounded-lg border bg-card p-4" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer font-semibold">组织流程模板与发布</summary>
    <div className="mt-4 space-y-4">
      <p className="text-sm text-muted-foreground">把管理要求转为可审阅的版本配置。可人工调整任务、专业职责、前置、功能条件、阶段名称、签核要求、办理路由和提醒节奏；智能建议需开放后单独请求并审阅。原有阶段类型、顺序、审批权限和最低硬闸保留，额外规则列为待决扩展。</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <fieldset disabled={busy} className="space-y-4">
        <Button type="button" size="sm" variant="outline" onClick={() => void act(load)}>刷新模板库</Button>
        {data && <>
          <label className="block text-sm">配置依据<select className={field} value={source ? `${source.id}:${source.version}` : ""} onChange={event => { const selected = templates.find(item => `${item.id}:${item.version}` === event.target.value); if (selected) selectSource(selected); }}><option value="">选择当前模板</option>{templates.map(item => <option key={item.id} value={`${item.id}:${item.version}`}>{item.name} · v{item.version}</option>)}</select></label>
          <ProcessTemplateBriefs source={briefSource} onOpenRevision={open} onConfigure={brief => {
            const base = templates.find(item => item.id === brief.base_template_id && item.version === brief.base_version && item.source_digest === brief.base_digest);
            if (!base) throw new Error("模板库已有变化，请先刷新模板库，再载入要求。");
            selectSource(base); setCopy(brief.template_id !== base.id); setCode(txt(brief.template_id).replace(/^org-/, "")); setSourceBrief(brief); setNotice("已关联原始管理要求并载入配置依据。请人工调整配置并填写本次修改说明。");
          }}/>
          {source && configuration && <div className="space-y-3 rounded-md border p-3">
            {sourceBrief && <div className="rounded-md bg-muted p-3 text-sm"><p>本次配置关联管理要求：{txt(sourceBrief.template_id)} · {new Date(txt(sourceBrief.created_at)).toLocaleString("zh-CN")}</p><details><summary className="cursor-pointer">查看关联原文与预期</summary><p className="mt-2 whitespace-pre-wrap break-words">{txt(sourceBrief.instruction)}</p><p className="mt-2 whitespace-pre-wrap break-words">{txt(sourceBrief.acceptance_criteria)}</p></details>{!briefMatches && <p className="text-destructive">目标或来源已变更，与关联要求不一致，暂不能保存。</p>}<Button type="button" size="sm" variant="ghost" onClick={() => setSourceBrief(null)}>解除本次候选与要求的关联</Button></div>}
            {source.id.startsWith("org-") && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={copy} onChange={event => setCopy(event.target.checked)}/>以此为基础新建独立模板</label>}
            {copy && <label className="block text-sm">新模板短码（英文字母、数字和连字符）<input className={field} maxLength={120} value={code} onChange={event => setCode(event.target.value)} placeholder="bicycle-team"/></label>}
            <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">模板名称<input className={field} maxLength={200} value={configuration.name} onChange={event => setConfiguration({ ...configuration, name: event.target.value })}/></label><label className="text-sm">英文名称<input className={field} maxLength={200} value={configuration.name_en} onChange={event => setConfiguration({ ...configuration, name_en: event.target.value })}/></label></div>
            <label className="block text-sm">管理要求及本次配置依据<textarea className={field} maxLength={5000} rows={3} value={reason} onChange={event => setReason(event.target.value)} placeholder="说明要怎样调整、为什么调整，以及适用的产品或团队。"/></label>
            <details><summary className="cursor-pointer text-sm font-medium">功能及默认适用条件</summary><div className="mt-2 space-y-3">{Object.entries(configuration.features).map(([key, feature]) => <div key={key} className="grid gap-2 rounded-md border p-2 sm:grid-cols-3"><label className="text-sm">{key} · 功能名称<input className={field} value={feature.label} maxLength={200} onChange={event => setConfiguration({ ...configuration, features: { ...configuration.features, [key]: { ...feature, label: event.target.value } } })}/></label><label className="text-sm">英文名称<input className={field} value={feature.label_en} maxLength={200} onChange={event => setConfiguration({ ...configuration, features: { ...configuration.features, [key]: { ...feature, label_en: event.target.value } } })}/></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={feature.default} onChange={event => setConfiguration({ ...configuration, features: { ...configuration.features, [key]: { ...feature, default: event.target.checked } } })}/>默认具有此功能</label></div>)}<label className="block text-sm">新功能标识（英文、数字、下划线）<input className={field} maxLength={64} value={featureCode} onChange={event => setFeatureCode(event.target.value)}/></label><Button type="button" size="sm" variant="outline" disabled={!featureCode || Boolean(configuration.features[featureCode]) || Object.keys(configuration.features).length >= 30} onClick={() => { setConfiguration({ ...configuration, features: { ...configuration.features, [featureCode]: { label: featureCode, label_en: featureCode, default: false } } }); setFeatureCode(""); }}>增加功能条件</Button></div></details>
            <ReminderPolicyEditor value={configuration.reminder_policy ?? source.reminder_policy ?? data.reminder_defaults as ReminderPolicy} onChange={reminder_policy => setConfiguration({ ...configuration, reminder_policy })}/>
            <details><summary className="cursor-pointer text-sm font-medium">项目阶段名称与办理说明</summary><p className="mt-2 text-xs text-muted-foreground">选择本发布版创建的新项目会采用这些名称和说明。阶段类型、先后顺序及原有硬闸保留；在途项目保留创建时的阶段。</p><div className="mt-3 space-y-3">{(configuration.stages ?? source.stages).map((stage, index) => <div key={stage.code} className="rounded-md border p-3"><p className="text-xs text-muted-foreground">阶段 {stage.sequence} · {stage.code}</p>{([['name','中文名称'],['name_en','英文名称'],['description','办理说明']] as const).map(([key, label]) => <label key={key} className="mt-2 block text-sm">{label}<textarea className={field} rows={key === "description" ? 2 : 1} maxLength={key === "description" ? 5000 : 200} value={stage[key] ?? ""} onChange={event => setConfiguration({ ...configuration, stages: (configuration.stages ?? source.stages).map((item, n) => n === index ? { ...item, [key]: event.target.value } : item) })}/></label>)}</div>)}</div></details>
            <RiskFieldsEditor value={configuration.risk_fields ?? source.risk_fields ?? []} onChange={risk_fields => setConfiguration({ ...configuration, risk_fields })}/>
            <TaskFieldsEditor value={configuration.task_fields ?? source.task_fields ?? []} onChange={task_fields => setConfiguration({ ...configuration, task_fields })}/>
            <IssueFieldsEditor value={configuration.issue_fields ?? source.issue_fields ?? []} onChange={issue_fields => setConfiguration({ ...configuration, issue_fields })}/>
            <ApprovalRoutesEditor stages={configuration.stages ?? source.stages} requirements={configuration.gate_requirements ?? source.gate_requirements ?? source.gate_baseline} value={configuration.approval_routes ?? source.approval_routes ?? {}} onChange={approval_routes => setConfiguration({ ...configuration, approval_routes })}/>
            <NamedSignerEditor stages={configuration.stages ?? source.stages} requirements={configuration.gate_requirements ?? source.gate_requirements ?? source.gate_baseline} value={configuration.named_gate_slots ?? source.named_gate_slots ?? {}} onChange={named_gate_slots => setConfiguration({ ...configuration, named_gate_slots })}/>
            <GateRulesEditor stages={configuration.stages ?? source.stages} minimum={source.gate_requirements ?? source.gate_baseline} value={configuration.gate_requirements ?? source.gate_requirements ?? source.gate_baseline} onChange={value => setConfiguration({ ...configuration, gate_requirements: value })}/>
            <label className="block text-sm">选择任务配置<select className={field} value={taskCode} onChange={event => setTaskCode(event.target.value)}>{configuration.tasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label>
            {selectedTask && <div className="space-y-3 rounded-md bg-muted/30 p-3">
              <TaskRouteEditor code={selectedTask.code} routes={configuration.task_routes ?? source.task_routes ?? {}} onChange={task_routes => setConfiguration({ ...configuration, task_routes })}/>
              <div className="grid gap-3 sm:grid-cols-2">{([['title','任务名称'],['title_en','英文名称'],['output','交付内容'],['receiver','接收要求']] as const).map(([key,label]) => <label key={key} className="text-sm">{label}<textarea className={field} rows={2} maxLength={key === "output" ? 5000 : key === "receiver" ? 2000 : 512} value={selectedTask[key]} onChange={event => editTask({ [key]: event.target.value })}/></label>)}</div>
              <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">阶段<select className={field} disabled={Boolean(originalTask)} value={selectedTask.stage} onChange={event => editTask({ stage: event.target.value })}>{source.stages.map(stage => <option key={stage.code} value={stage.code}>{stage.name}</option>)}</select></label><label className="text-sm">专业职责<select className={field} value={selectedTask.responsibility} onChange={event => editTask({ responsibility: event.target.value, discipline: roles[event.target.value] })}>{Object.entries(roles).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
              <details><summary className="cursor-pointer text-sm">前置任务（已要求的前置保留）</summary><div className="mt-2 max-h-52 space-y-2 overflow-auto">{configuration.tasks.filter(task => task.code !== taskCode).map(task => <label className="flex items-start gap-2 text-sm" key={task.code}><input type="checkbox" checked={selectedTask.depends_on.includes(task.code)} disabled={originalTask?.depends_on.includes(task.code)} onChange={event => editTask({ depends_on: event.target.checked ? [...selectedTask.depends_on, task.code] : selectedTask.depends_on.filter(code => code !== task.code) })}/>{task.code} · {task.title}</label>)}</div></details>
              <div className="flex flex-wrap gap-3">{Object.entries(configuration.features).map(([key, feature]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selectedTask.required_features.includes(key)} disabled={!!originalTask && !originalTask.required_features.includes(key)} onChange={event => editTask({ required_features: event.target.checked ? [...selectedTask.required_features,key] : selectedTask.required_features.filter(value => value !== key) })}/>仅在具有{feature.label}时适用</label>)}</div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selectedTask.hard_milestone} disabled={originalTask?.hard_milestone} onChange={event => editTask({ hard_milestone: event.target.checked })}/>必须完成冻结或接收，不以跳过替代</label>
              {!originalTask && <Button type="button" size="sm" variant="ghost" onClick={() => { setConfiguration({ ...configuration, tasks: configuration.tasks.filter(task => task.code !== taskCode), task_routes: Object.fromEntries(Object.entries(configuration.task_routes ?? source.task_routes ?? {}).filter(([code]) => code !== taskCode)) }); setTaskCode(configuration.tasks.find(task => task.code !== taskCode)?.code ?? ""); }}>从本次候选移除此普通任务（仍有前置引用时不能保存）</Button>}
              <div className="flex flex-wrap gap-3">{Object.entries(evidence).map(([key,label]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={selectedTask.minimum_evidence.includes(key)} disabled={originalTask?.minimum_evidence.includes(key)} onChange={event => editTask({ minimum_evidence: event.target.checked ? [...selectedTask.minimum_evidence,key] : selectedTask.minimum_evidence.filter(value => value !== key) })}/>{label}</label>)}</div>
            </div>}
            <Button type="button" size="sm" variant="outline" disabled={configuration.tasks.length >= 200} onClick={() => { let n=configuration.tasks.length+1; while(configuration.tasks.some(task => task.code === `CUSTOM-${n}`)) n++; const code=`CUSTOM-${n}`; setConfiguration({ ...configuration, tasks: [...configuration.tasks, { code, title: "新增任务", title_en: "New task", stage: source.stages[0].code, responsibility: "product_management", discipline: "产品/项目", depends_on: [], output: "请填写交付要求", receiver: "请填写接收要求", required_features: [], hard_milestone: false, minimum_evidence: ["work_output"] }] }); setTaskCode(code); }}>增加任务</Button>
            <label className="block text-sm">待决扩展（每行一项，未解决前不能发布）<textarea className={field} rows={3} maxLength={20000} value={configuration.extension_requests.join("\n")} onChange={event => setConfiguration({ ...configuration, extension_requests: event.target.value.split("\n") })} placeholder="例如需要新的审批方式、阶段类型或编号行为，请写明要求。"/></label>
            <Button type="button" size="sm" disabled={!reason.trim() || !code.trim() || !briefMatches} onClick={() => void act(save)}>保存人工配置候选</Button>
          </div>}
          <details><summary className="cursor-pointer text-sm font-medium">最近100个配置候选</summary><div className="mt-2 max-h-64 space-y-2 overflow-auto">{rows(data.revisions).map(item => <Button type="button" key={txt(item.id)} size="sm" variant="outline" className="block h-auto whitespace-normal text-left" onClick={() => void act(() => open(txt(item.id)))}>{txt(item.template_id)} · v{txt(item.version)} · {txt(item.reason)}</Button>)}</div></details>
        </>}
        {snapshot && <section className="space-y-4 border-t pt-4">
          <Button type="button" size="sm" variant="outline" onClick={() => {
            const base = templates.find(item => item.id === revision.base_template_id && item.version === revision.base_version && item.source_digest === revision.base_digest);
            const latest = templates.find(item => item.id === revision.template_id);
            if (!base || (latest && latest.release_id !== revision.base_release_id)) { setError("此候选依据已有新发布版，请先选择当前模板作为修改依据，再迁入需要保留的差异。"); return; }
            setSource(base); setSourceBrief(isRecord(detail?.source_brief) ? detail.source_brief : null); setCopy(revision.template_id !== base.id); setCode(txt(revision.template_id).replace(/^org-/, "")); setConfiguration(structuredClone(revision.configuration) as Configuration); setTaskCode(snapshot.tasks[0]?.code ?? ""); setReason(txt(revision.reason)); setNotice("已载入候选内容；修改并保存会生成独立新版本。");
          }}>载入此候选继续修改</Button>
          <h3 className="font-semibold">{snapshot.name} · 候选 v{txt(revision.version)}</h3><p className="text-sm">{txt(revision.reason)}</p>
          {isRecord(detail?.source_brief) && <details className="rounded-md bg-muted p-3 text-sm"><summary className="cursor-pointer font-medium">本候选对应的原始管理要求</summary><p className="mt-2 whitespace-pre-wrap break-words">{txt(detail.source_brief.instruction)}</p><p className="mt-2 font-medium">原验收预期</p><p className="whitespace-pre-wrap break-words">{txt(detail.source_brief.acceptance_criteria)}</p><p className="mt-2 text-xs text-muted-foreground">{new Date(txt(detail.source_brief.created_at)).toLocaleString("zh-CN")} · 来源 {txt(detail.source_brief.base_template_id)} v{txt(detail.source_brief.base_version)}</p></details>}
          <p className="text-xs text-muted-foreground">以下预填演练是可编辑示例。请按实际流程填写功能、已完成任务和预期判断；它演练任务适用性/前置与签核状态，不等于Gate批准或项目验收。</p>
          {cases.map((item,index) => <details key={index} open={index < 2} className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">演练 {index+1} · {item.name}</summary><div className="mt-3 space-y-3">
            <label className="block text-sm">场景名称<input className={field} maxLength={200} value={item.name} onChange={event => editCase(index,{ name: event.target.value })}/></label>
            <div className="flex flex-wrap gap-3">{Object.entries(snapshot.features).map(([key,feature]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={item.features[key] ?? feature.default} onChange={event => editCase(index,{ features: { ...item.features, [key]: event.target.checked } })}/>{feature.label}</label>)}</div>
            <label className="block text-sm">模拟已完成的任务（可多选）<select multiple className={`${field} h-32`} value={item.completed_codes} onChange={event => editCase(index,{ completed_codes: Array.from(event.target.selectedOptions, option => option.value) })}>{snapshot.tasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label>
            <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">要判断的任务<select className={field} value={Object.keys(item.expected_ready)[0] ?? ""} onChange={event => editCase(index,{ expected_ready: { [event.target.value]: Object.values(item.expected_ready)[0] ?? true } })}><option value="">请选择</option>{snapshot.tasks.map(task => <option key={task.code} value={task.code}>{task.code} · {task.title}</option>)}</select></label><label className="text-sm">预期是否可启动<select className={field} value={String(Object.values(item.expected_ready)[0] ?? true)} onChange={event => { const key = Object.keys(item.expected_ready)[0]; if (key) editCase(index,{ expected_ready: { [key]: event.target.value === "true" } }); }}><option value="true">可启动</option><option value="false">不可启动</option></select></label></div>
            <GateRehearsalEditor stages={snapshot.stages} value={item.gate_checks ?? []} onChange={value => editCase(index, { gate_checks: value })}/>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!item.expect_valid} onChange={event => editCase(index,{ expect_valid: !event.target.checked })}/>此场景的输入应被判定为无效</label>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setCases(cases.filter((_,n) => n !== index)); setPreview(null); setConfirmed(false); }}>移除此演练</Button>
          </div></details>)}
          <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={cases.length >= 20} onClick={() => { setCases([...cases, { ...examples(snapshot)[0], name: "新演练" }]); setPreview(null); setConfirmed(false); }}>增加演练</Button><Button type="button" size="sm" disabled={!cases.length} onClick={() => void act(async () => { setPreview(await api(`${basePath}/revisions/${txt(revision.id)}/preview`, { cases, risk_field_cases: riskFieldCases, signer_cases: signerCases, task_field_cases: taskFieldCases, field_cases: fieldCases, approval_cases: approvalCases, reminder_cases: reminderCases, routing_cases: normalizedRoutingCases(routingCases) })); setConfirmed(false); })}>预览差异、影响与演练</Button></div>
          <NamedSignerRehearsal stages={snapshot.stages} policy={snapshot.named_gate_slots ?? {}} value={signerCases} onChange={value => { setSignerCases(value); setPreview(null); setConfirmed(false); }}/>
          <RiskFieldRehearsalEditor fields={snapshot.risk_fields ?? []} value={riskFieldCases} onChange={value => { setRiskFieldCases(value); setPreview(null); setConfirmed(false); }}/>
          <TaskFieldRehearsalEditor fields={snapshot.task_fields ?? []} value={taskFieldCases} onChange={value => { setTaskFieldCases(value); setPreview(null); setConfirmed(false); }}/>
          <FieldRehearsalEditor fields={snapshot.issue_fields ?? []} value={fieldCases} onChange={value => { setFieldCases(value); setPreview(null); setConfirmed(false); }}/>
          <ApprovalRehearsalEditor stages={snapshot.stages} value={approvalCases} onChange={value => { setApprovalCases(value); setPreview(null); setConfirmed(false); }}/>
          <ReminderRehearsalEditor policy={snapshot.reminder_policy ?? data?.reminder_defaults as ReminderPolicy} value={reminderCases} onChange={value => { setReminderCases(value); setPreview(null); setConfirmed(false); }}/>
          <RouteRehearsalEditor template={snapshot} value={routingCases} onChange={value => { setRoutingCases(value); setPreview(null); setConfirmed(false); }}/>
          {preview && <Preview value={preview}/>}
          {preview && <div className="space-y-3 rounded-md border p-3"><label className="block text-sm">发布或回退依据<textarea className={field} maxLength={5000} value={releaseReason} onChange={event => setReleaseReason(event.target.value)}/></label><label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>已核对差异、正反例和影响范围，确认本次操作仅改变后续可选模板；在途项目另行办理。</label><div className="flex flex-wrap gap-2"><Button type="button" size="sm" disabled={!preview.can_publish || !confirmed || !releaseReason.trim()} onClick={() => void act(() => release("publish"))}>发布此模板版本</Button><Button type="button" size="sm" variant="outline" disabled={!preview.can_rollback || !confirmed || !releaseReason.trim()} onClick={() => void act(() => release("rollback"))}>回退到此已发布版本</Button></div></div>}
          <details><summary className="cursor-pointer text-sm">发布与回退记录（最近50次）</summary><div className="mt-2 space-y-2">{rows(detail?.releases).map(item => <div key={txt(item.id)} className="rounded-md border p-2 text-sm"><p>第{txt(item.sequence)}次 · {item.action === "rollback" ? "回退" : "发布"} · {new Date(txt(item.created_at)).toLocaleString("zh-CN")}</p><p>{txt(item.reason)}</p><Button type="button" size="sm" variant="ghost" onClick={() => void act(() => open(txt(item.revision_id)))}>查看对应配置</Button></div>)}</div></details>
        </section>}
      </fieldset>
    </div>
  </details>;
}

function Preview({ value }: { value: Row }) {
  const rehearsal = obj(value.rehearsal), diff = obj(value.difference);
  return <div className="space-y-3 rounded-md bg-muted/30 p-3 text-sm">
    <p className="font-medium">正反例演练：{rehearsal.passed ? "预期相符" : "尚未满足发布条件"}</p>
    {rows(rehearsal.cases).map((item,index) => <div key={index}><p>{txt(item.name)}：{item.passed ? "预期相符" : "预期不符或缺少判断"} {txt(item.error)}</p>{rows(item.checks).map(check => <p key={txt(check.code)} className="text-xs text-muted-foreground">{txt(check.code)} · 预期{check.expected_ready ? "可启动" : "不可启动"}，实际{check.actual_ready ? "可启动" : "不可启动"}</p>)}</div>)}
    {rows(rehearsal.cases).map((item,index) => <div key={index}>{rows(item.gate_checks).map((check,n) => <div className="mt-2 rounded-md border p-2" key={n}><p>{txt(item.name)} · {txt(check.stage)} · 签核预期{check.expected_ready ? "满足" : "不满足"}，实际{check.actual_ready ? "满足" : "不满足"}</p>{Object.entries(gateSlots).map(([slot,label]) => <p key={slot} className="text-xs">{label}要求：{gateRequirements[obj(check.requirements)[slot] as GateRequirement]} · 模拟状态：{({ pending: "待签核", approved: "批准", conditional: "有条件批准", rejected: "拒绝", not_applicable: "不适用" } as Record<string,string>)[txt(obj(check.signoffs)[slot])] ?? "待签核"}</p>)}</div>)}</div>)}
    {rows(rehearsal.gate_coverage).map(item => <p key={`${txt(item.stage)}:${txt(item.slot)}`} className="text-xs">{txt(item.stage)} · {gateSlots[item.slot as GateSlot]}加签：正例{item.positive ? "已覆盖" : "缺失"}，规则差异反例{item.negative ? "已覆盖" : "缺失"}</p>)}
    <NamedSignerResults value={value.signer_rehearsal}/>
    <NamedSignerDifference value={diff.named_signer_changes}/>
    <RiskFieldRehearsalResults value={value.risk_field_rehearsal}/>
    <RiskFieldDifference value={diff.risk_field_changes}/>
    <TaskFieldRehearsalResults value={value.task_field_rehearsal}/>
    <TaskFieldDifference value={diff.task_field_changes}/>
    <FieldRehearsalResults value={value.field_rehearsal}/>
    <IssueFieldDifference value={diff.issue_field_changes}/>
    <ApprovalRouteDifference value={diff.approval_route_changes}/>
    <ApprovalRehearsalResults value={value.approval_rehearsal}/>
    <ReminderRehearsalResults value={value.reminder_rehearsal}/>
    <RouteRehearsalResults value={value.routing_rehearsal}/>
    <p className="text-xs text-muted-foreground">{txt(rehearsal.scope)}</p>
    {!value.base_current && <p>候选所依据的当前模板已变化；新发布须重新准备。回退须选择曾发布的版本。</p>}
    {Array.isArray(value.pending_extensions) && value.pending_extensions.length > 0 && <div><p className="font-medium">仍待决定的扩展，不能发布：</p>{value.pending_extensions.map((item,index) => <p key={index}>{txt(item)}</p>)}</div>}
    <details open><summary className="cursor-pointer font-medium">本次实际配置差异</summary><p className="mt-2">名称：{txt(obj(diff.name).before)} → {txt(obj(diff.name).after)}</p>{rows(diff.feature_definitions).map(item => <div key={txt(item.key)}><p>功能 {txt(item.key)}：{txt(obj(item.before).label) || "新增"} → {txt(obj(item.after).label) || "移除"}；默认：{display(obj(item.before).default)} → {display(obj(item.after).default)}</p></div>)}{rows(diff.reminder_changes).map(item => <p key={txt(item.key)} className="mt-2">{reminderLabels[txt(item.key)]}：{reminderValue(txt(item.key), item.before)} → {reminderValue(txt(item.key),item.after)}</p>)}{rows(diff.route_changes).map(item => <div key={txt(item.code)} className="mt-2 rounded-md border p-2"><p className="font-medium">{txt(item.code)} · 办理路由</p>{([['owner','负责人'],['receiver','接收人']] as const).map(([slot,label]) => <p key={slot}>{label}：{professionalRoles[txt(obj(item.before)[slot])] ?? "逐项指定"} → {professionalRoles[txt(obj(item.after)[slot])] ?? "逐项指定"}</p>)}</div>)}{rows(diff.gate_changes).map(item => <p key={`${txt(item.stage)}:${txt(item.slot)}`} className="mt-2">{txt(item.stage)} · {gateSlots[item.slot as GateSlot]}签核：{gateRequirements[item.before as GateRequirement]} → {gateRequirements[item.after as GateRequirement]}</p>)}{rows(diff.stage_changes).map(item => <div key={txt(item.code)} className="mt-2 rounded-md border p-2"><p className="font-medium">阶段 {txt(item.code)}</p>{([['name','中文名称'],['name_en','英文名称'],['description','办理说明']] as const).filter(([key]) => obj(item.before)[key] !== obj(item.after)[key]).map(([key,label]) => <p key={key} className="whitespace-pre-wrap break-words">{label}：{display(obj(item.before)[key])} → {display(obj(item.after)[key])}</p>)}</div>)}{rows(diff.task_changes).map(item => <details key={txt(item.code)} className="mt-2 rounded-md border p-2"><summary className="cursor-pointer">{txt(item.code)} · {txt(obj(item.after).title) || txt(obj(item.before).title)} · {!item.before ? "新增" : !item.after ? "移除" : "调整"}</summary>{Object.entries(labels).filter(([key]) => JSON.stringify(obj(item.before)[key]) !== JSON.stringify(obj(item.after)[key])).map(([key,label]) => <div key={key} className="mt-2 whitespace-pre-wrap break-words"><p className="font-medium">{label}</p><p>原：{display(obj(item.before)[key])}</p><p>新：{display(obj(item.after)[key])}</p></div>)}</details>)}</details>
    <p>{txt(value.migration_policy)}</p><p>当前关联项目共{txt(value.project_count)}个{value.projects_truncated ? "，以下列出前50个" : ""}：</p>
    {rows(value.projects).map(item => <Link key={txt(item.id)} className="block text-primary underline" href={`/projects?project=${txt(item.id)}`}>{txt(item.code)} · {txt(item.name)} · 采用模板 v{txt(item.template_version)} / 项目配置 v{txt(item.revision)}</Link>)}
  </div>;
}
