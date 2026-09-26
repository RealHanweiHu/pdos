"use client";

import { useState } from "react";
import { ReminderPolicySummary, type ReminderPolicy } from "@/components/organization/process-template-reminders";
import { Button } from "@/components/ui/button";

type Node = { code: string; stage: string; title: string; title_en: string; responsibility: string; depends_on: string[]; output: string; receiver: string; hard_milestone: boolean };
type Template = { id: string; version: number; name: string; name_en: string; product_type: string; evidence_status: string;
  features: Record<string, { label: string; label_en: string; default: boolean }>;
  feature_values?: Record<string, boolean>; language?: string; tasks: Node[];
  stages: { code: string; name: string; name_en: string }[]; initiation_checks: string[];
  numbering: Record<string, string | string[]>; handoff_items: string[] };
type Revision = { id: string; revision: number; template_id: string; status: string; reason: string; snapshot: Template;
  difference: { features: { key: string; before: boolean | null; after: boolean }[]; added_tasks: string[]; removed_tasks: string[]; changed_tasks: string[]; existing_plan_policy: string } };
type Data = { creation_reminder_policy?: ReminderPolicy; creation_reminder_source?: { template_id: string; template_version: number } | null; active: Revision | null; versions: Revision[]; catalog: Template[] };
const field = "w-full rounded-md border bg-background p-2 text-sm";
const statuses: Record<string, string> = { proposed: "待确认", active: "当前采用", rejected: "已拒绝", superseded: "历史版本" };
const roles: Record<string, string> = { product_management: "产品/项目", industrial_design: "ID", mechanical: "结构", hardware: "硬件", firmware: "固件", design_quality: "DQE", supplier_quality: "SQE", industrial_engineering: "IE" };
async function read(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body?.detail?.message ?? "产品模板暂不可用");
  return body;
}

export function ProjectTemplatePanel({ projectId, canManage, stageCode }: { projectId: string; canManage: boolean; stageCode: string }) {
  const base = `/api/projects/${projectId}/product-template`;
  const [data, setData] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [features, setFeatures] = useState<Record<string, boolean>>({});
  const [language, setLanguage] = useState("zh-CN");
  const [reason, setReason] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const load = async () => setData(await read(await fetch(base, { cache: "no-store" })));
  const act = async (work: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const selectedTemplate = data?.catalog.find((item) => item.id === selected);
  const preview = data?.versions.find((item) => item.id === previewId) ?? data?.active;
  const snapshot = preview?.snapshot;
  const english = snapshot?.language === "en";
  return <details className="mt-6 rounded-lg border p-4" onToggle={(event) => { if (event.currentTarget.open && data === null && !busy) void act(load); }}>
    <summary className="cursor-pointer font-semibold">产品模板与功能范围</summary>
    <div className="mt-4 space-y-4">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新模板</Button>
      {data && <>
        <p className="text-sm">{data.active ? `当前采用：${data.active.snapshot.name} · 项目配置 v${data.active.revision}` : "项目尚未采用产品模板。选择产品类型并核对功能范围后，可预览专业依赖与测试适用性。"}</p>
        {data.creation_reminder_policy && <div className="space-y-2 rounded-md border p-3"><p className="text-xs text-muted-foreground">{data.creation_reminder_source ? `提醒固定采用创建时的 ${data.creation_reminder_source.template_id} v${data.creation_reminder_source.template_version}，后续模板切换不自动改变。` : "提醒沿用原系统规则，后续选择产品模板不自动改写。"}</p><ReminderPolicySummary value={data.creation_reminder_policy}/></div>}
        {canManage && <form className="space-y-3 rounded-md border p-3" onSubmit={(event) => { event.preventDefault(); if (!selectedTemplate) return; void act(async () => {
          const proposal = await read(await fetch(`${base}/proposals`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_id: selectedTemplate.id, version: selectedTemplate.version, features, language, reason, source_version_id: data.active?.id ?? null }) }));
          await load(); setPreviewId(proposal.id);
        }); }}>
          <label className="block text-sm">产品类型与模板<select required className={field} value={selected} onChange={(event) => {
            const template = data.catalog.find((item) => item.id === event.target.value);
            setSelected(event.target.value); setFeatures(Object.fromEntries(Object.entries(template?.features ?? {}).map(([key, value]) => [key, data.active && data.active.template_id === template?.id ? data.active.snapshot.feature_values?.[key] ?? value.default : value.default])));
          }}><option value="">选择模板</option>{data.catalog.map((template) => <option key={template.id} value={template.id}>{template.name} · v{template.version}</option>)}</select></label>
          {selectedTemplate?.evidence_status === "simulation" && <p className="text-sm text-muted-foreground">此类型为模拟试配，验证方法、数值判据与认证适用性需要专业确认。</p>}
          {Object.entries(selectedTemplate?.features ?? {}).map(([key, value]) => <label key={key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={features[key] ?? value.default} onChange={(event) => setFeatures({ ...features, [key]: event.target.checked })} />{value.label}</label>)}
          <label className="block text-sm">内容语言<select className={field} value={language} onChange={(event) => setLanguage(event.target.value)}><option value="zh-CN">中文</option><option value="en">English · 原始证据保留原文</option></select></label>
          <label className="block text-sm">采用或调整依据<textarea required maxLength={5000} className={field} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="产品范围、客户要求及来源版本" /></label>
          <Button size="sm" disabled={busy || !selectedTemplate || !reason.trim()}>生成模板差异</Button>
        </form>}
        {data.versions.length > 0 && <div className="flex flex-wrap gap-2">{data.versions.map((version) => <Button key={version.id} size="sm" variant={preview?.id === version.id ? "default" : "outline"} onClick={() => setPreviewId(version.id)}>v{version.revision} · {statuses[version.status]}</Button>)}</div>}
        {preview && snapshot && <section className="space-y-4 border-t pt-3">
          <h3 className="font-semibold">{english ? snapshot.name_en : snapshot.name} · v{preview.revision} · {statuses[preview.status]}</h3>
          <p className="text-sm">{preview.reason}</p>
          <div className="rounded-md bg-muted p-3 text-sm"><p>新增任务：{preview.difference.added_tasks.join("、") || "无"}</p><p>移除任务：{preview.difference.removed_tasks.join("、") || "无"}</p><p>调整任务：{preview.difference.changed_tasks.join("、") || "无"}</p>{preview.difference.features.map((change) => <p key={change.key}>{snapshot.features[change.key]?.label ?? change.key}：{change.before == null ? "未配置" : change.before ? "启用" : "无此功能"} → {change.after ? "启用" : "无此功能"}</p>)}<p className="mt-2 text-muted-foreground">{preview.difference.existing_plan_policy}</p></div>
          {canManage && preview.status === "proposed" && <div className="flex gap-2">{[true, false].map((confirm) => <Button key={String(confirm)} size="sm" variant={confirm ? "default" : "outline"} disabled={busy} onClick={() => void act(async () => { await read(await fetch(`${base}/versions/${preview.id}/decision`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm }) })); await load(); })}>{confirm ? "确认采用模板配置" : "拒绝此候选"}</Button>)}</div>}
          <details><summary className="cursor-pointer text-sm font-medium">{english ? "Initiation inputs" : "立项输入与 ID 专项计划"}</summary><ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{snapshot.initiation_checks.map((item) => <li key={item}>{item}</li>)}</ul>{english && <p className="text-xs text-muted-foreground">Source text is retained; translated evidence has not been supplied.</p>}</details>
          {snapshot.stages.map((stage) => <details key={stage.code} open={stage.code === stageCode}><summary className="cursor-pointer text-sm font-medium">{english ? stage.name_en : stage.name} · {snapshot.tasks.filter((task) => task.stage === stage.code).length}</summary><ul className="mt-2 space-y-3">{snapshot.tasks.filter((task) => task.stage === stage.code).map((task) => <li key={task.code} className="rounded-md border p-3 text-sm"><p className="font-medium">{task.code} · {english ? task.title_en : task.title}{task.hard_milestone ? (english ? " · Required freeze / acceptance" : " · 必须冻结或接收") : ""}</p><p>{english ? "Responsibility" : "负责专业"}：{roles[task.responsibility] ?? task.responsibility}</p><p>{english ? "Dependencies" : "前置"}：{task.depends_on.join("、") || "—"}</p><p>{english ? "Required output (source text)" : "交付"}：{task.output}</p><p>{english ? "Receiver (source text)" : "接收"}：{task.receiver}</p></li>)}</ul></details>)}
          <details><summary className="cursor-pointer text-sm font-medium">编号与交接约定</summary><ul className="mt-2 space-y-1 text-sm">{Object.entries(snapshot.numbering).map(([key, value]) => <li key={key}>{key}：{Array.isArray(value) ? value.join(" / ") : value}</li>)}</ul><p className="mt-2 text-sm">交接覆盖配置、BOM、工艺检验、测试认证、培训、遗留项与持续品质责任。</p></details>
        </section>}
      </>}
    </div>
  </details>;
}
