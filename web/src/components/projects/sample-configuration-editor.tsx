"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Field = "pcb_version" | "structure_version" | "fw_version" | "development_bom_id" | "build_date" | "key_component_suppliers";
type Mode = "keep" | "set" | "clear";
type Supplier = { component: string; value: unknown; text: string; edited: boolean };
const fields: Record<Field, string> = { pcb_version: "PCB版本", structure_version: "结构版本", fw_version: "固件版本", development_bom_id: "实际装机BOM版本", build_date: "实际装机日期", key_component_suppliers: "关键件供应商" };
const modes = (): Record<Field, Mode> => ({ pcb_version: "keep", structure_version: "keep", fw_version: "keep", development_bom_id: "keep", build_date: "keep", key_component_suppliers: "keep" });
const input = "mt-1 w-full rounded-md border bg-background p-2 text-xs";
function text(v: unknown): string { if (v === null || v === undefined || v === "") return "未知"; if (isRecord(v)) return Object.entries(v).map(([key, value]) => `${key}：${text(value)}`).join("；") || "未知"; if (Array.isArray(v)) return v.map(text).join("；"); return String(v); }
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "PUT" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "配置保存未完成，请重新核对当前资料");
  return value;
}
export function SampleConfigurationEditor({ projectId, sampleId, disabled, onDirtyChange, onSaved }: { projectId: string; sampleId: string; disabled: boolean; onDirtyChange: (dirty: boolean) => void; onSaved: () => Promise<void> }) {
  const [options, setOptions] = useState<{ current: Row; boms: Row[]; firmware: Row[]; digest: string; canEdit: boolean } | null>(null);
  const [mode, setMode] = useState(modes), [values, setValues] = useState<Record<string, string>>({}), [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [reason, setReason] = useState(""), [ack, setAck] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [saved, setSaved] = useState<string | null>(null);
  const base = `/api/projects/${projectId}/npi/samples/${sampleId}`;
  const changed = (Object.keys(fields) as Field[]).filter(field => mode[field] !== "keep");
  function dirty() { onDirtyChange(true); setAck(false); setSaved(null); }
  async function open() {
    setBusy(true); setError(null); onDirtyChange(true);
    try { const value = await request(`${base}/configuration-edit-options`); if (!isRecord(value) || !Array.isArray(value.boms) || !Array.isArray(value.firmware) || typeof value.digest !== "string") throw new Error("当前配置资料不完整"); const current = isRecord(value.current) ? value.current : {}; setOptions({ current, boms: value.boms.filter(isRecord), firmware: value.firmware.filter(isRecord), digest: value.digest, canEdit: value.can_edit === true }); setValues(Object.fromEntries(Object.keys(fields).filter(k => k !== "key_component_suppliers").map(k => [k, current[k] === null || current[k] === undefined ? "" : String(current[k])]))); const raw = isRecord(current.key_component_suppliers) ? current.key_component_suppliers : {}; setSuppliers(Object.entries(raw).map(([component, stored]) => ({ component, value: stored, text: typeof stored === "string" ? stored : "", edited: false }))); setMode(modes()); setReason(""); setAck(false); onDirtyChange(false); }
    catch (e) { setError(e instanceof Error ? e.message : "配置读取未完成"); } finally { setBusy(false); onDirtyChange(false); }
  }
  function supplierValues(): Record<string, unknown> { const result: Record<string, unknown> = {}; for (const row of suppliers) { const key = row.component.trim(); if (!key || Object.hasOwn(result, key)) throw new Error("关键件名称不能为空或重复"); if (row.edited && !row.text.trim()) throw new Error("请填写供应商，或移除该关键件记录"); result[key] = row.edited ? row.text.trim() : row.value; } return result; }
  function currentValue(field: Field): string { if (field === "development_bom_id" && options?.current.development_bom_id) return `${text(options.current.bom_code)} · 版本${text(options.current.bom_version)}`; return text(options?.current[field]); }
  async function save() {
    if (!options) return;
    setBusy(true); setError(null);
    try {
      const body: Row = { expected_digest: options.digest, reason: reason.trim(), clear_fields: changed.filter(field => mode[field] === "clear") };
      for (const field of changed.filter(f => mode[f] === "set")) {
        if (field === "key_component_suppliers") body[field] = supplierValues();
        else { const value = values[field]?.trim(); if (!value) throw new Error(`请填写${fields[field]}，或明确选择标为未知`); body[field] = value; }
      }
      const result = await request(`${base}/build-configuration`, body); if (!isRecord(result)) throw new Error("保存回执不完整，请刷新当前配置");
      setOptions(null); onDirtyChange(false); setSaved("当前配置已保存；相同内容复用已有版本。历史测试继续使用原先绑定的配置。"); await onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "配置保存未完成"); } finally { setBusy(false); }
  }
  return <div className="space-y-3 rounded-md border p-3 text-xs">
    {!options ? <Button type="button" size="sm" variant="outline" disabled={disabled || busy} onClick={() => void open()}>维护当前样机配置</Button> : <>
      <p className="font-medium">维护当前样机配置</p><p>请选择实际装机所用版本。计划BOM继续单独保留；保存会记录当前配置版本及修改依据，历史测试的配置绑定保持原样。</p>
      {!options.canEdit ? <p>当前账号只能查看配置。</p> : <><div className="grid gap-3 md:grid-cols-2">{(Object.entries(fields) as [Field, string][]).map(([field, title]) => <div key={field} className={`space-y-2 rounded-md border p-2 ${field === "key_component_suppliers" ? "md:col-span-2" : ""}`}><p className="font-medium">{title}</p><p className="break-words text-muted-foreground">当前：{currentValue(field)}</p><label className="block">本次操作<select className={input} value={mode[field]} disabled={busy || disabled} onChange={e => { setMode({ ...mode, [field]: e.target.value as Mode }); dirty(); }}><option value="keep">保留原值</option><option value="set">更新值</option><option value="clear">清除并标为未知</option></select></label>
        {mode[field] === "set" && (field === "development_bom_id" ? <label className="block">实际BOM版本<select className={input} value={values[field] ?? ""} disabled={busy || disabled} onChange={e => { setValues({ ...values, [field]: e.target.value }); dirty(); }}><option value="">请选择</option>{options.boms.map(b => <option key={String(b.id)} value={String(b.id)}>{text(b.code)} · 版本{text(b.version)} · {b.bom_type === "prototype" ? "样机BOM" : b.bom_type === "ebom" ? "工程BOM" : b.bom_type === "cost" ? "成本BOM" : text(b.bom_type)}</option>)}</select></label> : field === "key_component_suppliers" ? <div className="space-y-2">{suppliers.map((row, index) => <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-3" key={index}><label>关键件<input className={input} value={row.component} maxLength={128} disabled={busy || disabled} onChange={e => { setSuppliers(suppliers.map((s, i) => i === index ? { ...s, component: e.target.value } : s)); dirty(); }} /></label><label>供应商<input className={input} value={row.text} maxLength={512} placeholder={typeof row.value === "string" ? "供应商名称" : "保留详细记录；填写后替换"} disabled={busy || disabled} onChange={e => { setSuppliers(suppliers.map((s, i) => i === index ? { ...s, text: e.target.value, edited: true } : s)); dirty(); }} />{typeof row.value !== "string" && !row.edited && <p className="mt-1 text-muted-foreground">已保存：{text(row.value)}</p>}</label><Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => { setSuppliers(suppliers.filter((_, i) => i !== index)); dirty(); }}>移除此关键件</Button></div>)}<Button type="button" size="sm" variant="outline" disabled={busy || disabled || suppliers.length >= 50} onClick={() => { setSuppliers([...suppliers, { component: "", value: "", text: "", edited: true }]); dirty(); }}>添加关键件</Button></div> : <label className="block">更新后的值<input className={input} type={field === "build_date" ? "date" : "text"} maxLength={64} list={field === "fw_version" ? `firmware-${sampleId}` : undefined} value={values[field] ?? ""} disabled={busy || disabled} onChange={e => { setValues({ ...values, [field]: e.target.value }); dirty(); }} /></label>)}
      </div>)}</div><datalist id={`firmware-${sampleId}`}>{options.firmware.map(f => <option key={String(f.id)} value={String(f.version)} />)}</datalist>
      <label className="block">更新依据或清除原因<textarea className={input} value={reason} maxLength={2000} disabled={busy || disabled} onChange={e => { setReason(e.target.value); dirty(); }} /></label>
      <p>本次将处理：{changed.map(f => `${fields[f]}（${mode[f] === "clear" ? "标为未知" : "更新"}）`).join("、") || "尚未选择修改项"}</p>
      <label className="flex gap-2"><input type="checkbox" checked={ack} disabled={busy || disabled} onChange={e => setAck(e.target.checked)} />已核对本次修改与实际装机状态一致，确认保存当前配置。</label><Button type="button" size="sm" disabled={busy || disabled || !ack || !changed.length || !reason.trim()} onClick={() => void save()}>保存当前配置</Button></>}
      <Button type="button" size="sm" variant="outline" disabled={busy || disabled} onClick={() => { setOptions(null); onDirtyChange(false); setError(null); }}>取消并放弃本次编辑</Button>
    </>}
    {saved && <p role="status">{saved}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
  </div>;
}
