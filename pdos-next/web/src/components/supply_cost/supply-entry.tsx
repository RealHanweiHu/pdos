"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ClipboardText, Eye, Package } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Basis, Panel, Source } from "./display";
import { availabilityLabels, checkPreview, checkReceipt, confirmationFor, failureMessage, poolKey, qualityLabels, quantity, recordLabels, selectablePools, sourceChoiceKey } from "./presentation";
import type { BasisBindingView, MaterialChoice, PoolChoice, SourceChoice, SupplyConfirmation, SupplyDraft, SupplyEntryPort, SupplyEntryPreview, SupplyEntryReceipt } from "./types";

export type SupplyEntryProps = {
  /** This binding and all choices must be generated from the current server scope. */
  binding: BasisBindingView | null;
  sources: SourceChoice[];
  materials: MaterialChoice[];
  pools: PoolChoice[];
  port?: SupplyEntryPort;
  onReceipt?: (receipt: SupplyEntryReceipt) => void | Promise<void>;
};
const blank: SupplyDraft = { record_kind: "receipt", record_id: "", material_id: "", quantity: null, unit: null, source_id: "", source_revision: "", quality: "unknown", availability: "unknown", note: "" };

export function SupplyEntry(props: SupplyEntryProps) {
  return <Entry {...props}/>;
}

function Entry({ binding, sources, materials, pools, port, onReceipt }: SupplyEntryProps) {
  const [draft, setDraft] = useState<SupplyDraft>(blank);
  const [preview, setPreview] = useState<SupplyEntryPreview | null>(null);
  const [attempted, setAttempted] = useState<SupplyConfirmation | null>(null);
  const [receipt, setReceipt] = useState<SupplyEntryReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const lock = useRef(false);
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const previewTitleId = useId();
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => { if (preview) previewHeading.current?.focus(); }, [preview]);
  const connected = !!binding && !!port;
  const editable = connected && !busy && !preview && !attempted && !receipt;
  const chosenSource = sources.find(item => item.ref.source_id === draft.source_id && item.ref.version === draft.source_revision);
  const poolChoices = selectablePools(pools, draft.material_id);

  function edit(changes: Partial<SupplyDraft>) { setDraft(current => ({ ...current, ...changes })); setError(""); }
  async function prepare() {
    if (!binding || !port || lock.current) return;
    if (!chosenSource || chosenSource.ref.state !== "current" || !materials.some(item => item.id === draft.material_id) || !draft.record_id.trim()) { setError("请选择当前来源、真实物料并填写来源记录标识。"); return; }
    if (draft.quantity !== null && !/^\d+(?:\.\d{1,8})?$/.test(draft.quantity)) { setError("数量使用非负十进制数字，最多8位小数；未知时留空。"); return; }
    if (draft.pool_id && !poolChoices.some(pool => pool.key.pool_id === draft.pool_id && !pool.ambiguous)) { setError("物理池身份已变化或同名冲突，请重新核对服务器池绑定。"); return; }
    lock.current = true; setBusy(true); setError("");
    try {
      const result = await port.prepare({ ...draft, record_id: draft.record_id.trim(), unit: draft.unit?.trim() || null });
      checkPreview(result, draft, binding);
      if (active.current) setPreview(result);
    } catch (failure) { if (active.current) setError(failureMessage(failure)); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function acceptResult(result: SupplyEntryReceipt, reviewed: SupplyEntryPreview) {
    checkReceipt(result, reviewed);
    if (!active.current) return;
    setReceipt(result); setError("");
    try { await onReceipt?.(result); }
    catch (failure) { if (active.current) setError(`快照已保存，最新结果读取失败：${failureMessage(failure)}`); }
  }
  async function confirm() {
    if (!binding || !port || !preview || lock.current || attempted || receipt) return;
    let confirmation: SupplyConfirmation;
    try {
      checkPreview(preview, draft, binding);
      if (!chosenSource || chosenSource.ref.state !== "current" || chosenSource.ref.sha256 !== preview.source.sha256) throw new Error("来源内容已变化，请返回编辑并重新取得预览。");
      confirmation = confirmationFor(preview);
    } catch (failure) { setError(failureMessage(failure)); return; }
    lock.current = true; setBusy(true); setError(""); setAttempted(confirmation);
    try { await acceptResult(await port.confirm(confirmation), preview); }
    catch (failure) { if (active.current) setError(`本次确认结果未明：${failureMessage(failure)}`); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function resolve() {
    if (!port?.resolve || !attempted || !preview || lock.current || receipt) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const result = await port.resolve(attempted);
      if (result) await acceptResult(result, preview);
      else if (active.current) setError("尚未取得本次确认的持久回执，请继续按原确认凭据回查。");
    } catch (failure) { if (active.current) setError(failureMessage(failure)); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }

  return <Panel title="录入供给来源" note="记录来源中的承诺、在途、实际到货或限制；正式供方承诺和质量放行分别由具名流程办理。">
    {binding ? <><Basis basis={binding.basis}/><p className="subtle"><Source source={binding.manufacturing_configuration}/> · 固定制造配置</p></> : <p role="status" className="subtle">Build 与权威需求接口待接入。</p>}
    {!port && <p role="status" className="subtle">供给办理接口待接入，当前不能提交。</p>}
    <form onSubmit={event => { event.preventDefault(); void prepare(); }}>
      <fieldset disabled={!editable} className="min-w-0">
        <div className="grid gap-x-4 sm:grid-cols-2">
          <label>记录类别<select value={draft.record_kind} onChange={event => edit({ record_kind: event.target.value as SupplyDraft["record_kind"] })}>{Object.entries(recordLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>当前来源<select value={sourceChoiceKey({ source_id: draft.source_id, version: draft.source_revision })} onChange={event => { const source = sources.find(item => sourceChoiceKey(item.ref) === event.target.value); edit({ source_id: source?.ref.source_id ?? "", source_revision: source?.ref.version ?? "" }); }}><option value={sourceChoiceKey({ source_id: "", version: "" })}>选择来源版本</option>{sources.map(item => <option key={sourceChoiceKey(item.ref)} value={sourceChoiceKey(item.ref)} disabled={item.ref.state !== "current"}>{item.title} · v{item.ref.version}{item.ref.state !== "current" ? " · 待重核" : ""}</option>)}</select></label>
          <label>来源记录标识<input value={draft.record_id} maxLength={500} onChange={event => edit({ record_id: event.target.value })} autoComplete="off"/></label>
          <label>物料<select value={draft.material_id} onChange={event => { const material = materials.find(item => item.id === event.target.value); edit({ material_id: material?.id ?? "", unit: material?.unit ?? null, pool_id: undefined }); }}><option value="">选择物料</option>{materials.map(item => <option key={item.id} value={item.id}>{item.title} · {item.id}</option>)}</select></label>
          <label>来源数量（未知留空）<input inputMode="decimal" value={draft.quantity ?? ""} maxLength={32} onChange={event => edit({ quantity: event.target.value.trim() || null })}/></label>
          <label>来源单位（未知留空）<input value={draft.unit ?? ""} maxLength={80} onChange={event => edit({ unit: event.target.value || null })}/></label>
          <label>已有物理池<select value={draft.pool_id ?? ""} onChange={event => edit({ pool_id: event.target.value || undefined })}><option value="">未绑定 · 由服务器核对</option>{poolChoices.map(item => <option key={poolKey(item.key)} value={item.key.pool_id} disabled={item.ambiguous}>{item.title} · {item.key.source_system} · {item.key.pool_id}{item.ambiguous ? " · 同名池待明确绑定" : ""}</option>)}</select></label>
          <label>来源质量状态<select value={draft.quality} onChange={event => edit({ quality: event.target.value as SupplyDraft["quality"] })}>{Object.entries(qualityLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>来源可用状态<select value={draft.availability} onChange={event => edit({ availability: event.target.value as SupplyDraft["availability"] })}>{Object.entries(availabilityLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        </div>
        <label>来源说明<textarea value={draft.note} maxLength={4000} onChange={event => edit({ note: event.target.value })}/></label>
        <Button type="submit" disabled={!chosenSource || !draft.material_id || !draft.record_id.trim()}><Eye/>查看录入范围…</Button>
      </fieldset>
    </form>
    {busy && <p role="status" className="subtle">正在办理，等待服务器回执…</p>}
    {error && <p role="alert" className="text-destructive text-sm break-words">{error}</p>}
    {preview && <section className="space-y-4 rounded-lg border border-border p-4" aria-labelledby={previewTitleId}>
      <h3 id={previewTitleId} ref={previewHeading} tabIndex={-1} className="flex items-center gap-2 font-semibold"><ClipboardText/>核对服务器录入预览</h3>
      <Basis basis={preview.basis_binding.basis}/>
      <p className="subtle"><Source source={preview.basis_binding.manufacturing_configuration}/> · 本次预览固定制造配置</p>
      <p className="text-sm break-words">{recordLabels[preview.record.record_kind]} · {preview.record.material_id} · {quantity(preview.record.quantity, preview.record.unit)}</p>
      <p className="text-sm">{qualityLabels[preview.record.quality]} · {availabilityLabels[preview.record.availability]}</p>
      <p><Source source={preview.source}/></p>
      <dl className="space-y-3">{preview.changes.map((item, index) => <div key={`${item.field}:${index}`} className="text-sm"><dt className="font-medium">{item.label}</dt><dd className="mt-1 grid gap-2 sm:grid-cols-2"><span className="break-words">原值：{item.before ?? "未记录"}</span><span className="break-words">录入：{item.after ?? "未知"}</span></dd></div>)}</dl>
      {preview.record.note && <p className="text-sm break-words">说明：{preview.record.note}</p>}
      {preview.warnings.length > 0 && <ul className="space-y-1 text-sm">{preview.warnings.map((warning, index) => <li key={index} className="break-words">{warning}</li>)}</ul>}
      {!preview.allowed_to_confirm && <p className="text-sm">该记录需另行具名办理，当前不能确认。</p>}
      {attempted && !receipt && <p role="status" className="text-sm">已发送一次确认，保留本次凭据等待持久回执。</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={busy || !!attempted || !!receipt} onClick={() => { setPreview(null); setError(""); }}>返回编辑</Button>
        {!attempted && <Button type="button" disabled={busy || !preview.allowed_to_confirm} onClick={() => { void confirm(); }}>确认保存此来源记录</Button>}
        {attempted && !receipt && port?.resolve && <Button type="button" variant="outline" disabled={busy} onClick={() => { void resolve(); }}>回查本次确认</Button>}
      </div>
    </section>}
    {receipt && <div className="space-y-3 text-sm"><div role="status" className="space-y-1"><p className="flex items-center gap-2"><Package/>已保存供给快照 v{receipt.snapshot_revision}</p><p className="subtle break-words">快照：{receipt.snapshot_id} · 回执：{receipt.receipt_id}</p></div><Button type="button" variant="outline" disabled={busy || !connected} onClick={() => { setDraft(blank); setPreview(null); setAttempted(null); setReceipt(null); setError(""); }}>录入下一条来源记录</Button></div>}
  </Panel>;
}
