"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowClockwise, CheckCircle, WarningCircle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { eventTime, eventTimezone, record, snapshot, same, type MaterialRef } from "./ui-contract";
import { factCanPrepare, factHostBasis, factIdentity, factSourceKey, factRecordTiming, observationOperation, reviewOperation, validFactHost, readFactBusinessReview,
  type FactBusinessReview, type FactCommand, type FactHost, type FactOperation, type FactPayload,
  type FactPrepared, type FactReceipt, type FactEvent, type PairAssessment,
  type ActionAssessment } from "./fact-workflow-contract";
import { blankFactLocal, factBasisChanged, factBegin, factFailure, factInputsCommand, factPrepared, factReceipt,
  factSaved, newFactCommand, restoreFactLocal, selectFactSources, type FactLocal, type FactPending } from "./fact-workflow-state";

export type FactWorkflowProps = {
  host: FactHost | null;
  inputs: (command: FactCommand) => Promise<unknown>;
  preview: (command: FactCommand) => Promise<unknown>;
  execute: (command: FactCommand) => Promise<unknown>;
  /** Inspect actual returned material. Incomplete content never unlocks confirmation. */
  readReview?: (review: Record<string, unknown>, command: FactCommand) => FactBusinessReview | null;
  onSaved: (receipt: FactReceipt) => Promise<void>;
  onRefresh: () => Promise<void>;
  readHistory?: (cursor: string) => Promise<FactHost>;
  onPendingChange?: (locked: boolean) => void;
  onAccessRejected?: (saved: boolean, late?: boolean) => void;
  blocked?: boolean;
  hostAccessRejected?: boolean;
};
const wrap = "min-w-0 [overflow-wrap:anywhere]";
const input = "w-full min-w-0 rounded-lg border border-input bg-background p-2 text-sm";
const opLabel = (op: FactOperation) => op === observationOperation ? "实际观察" : "独立具名复核";
const resultLabels = { applicable: "适用", not_applicable: "不适用", unknown: "尚不能确定" };
const refKey = (ref: MaterialRef) => JSON.stringify(ref);

/** Scope is supplied by the host. This component neither finds routes nor grants roles. */
export function FactWorkflow(props: FactWorkflowProps) {
  const identity = props.host ? factIdentity(props.host) : null;
  if (!identity || !props.host || !validFactHost(props.host)) return <section className="panel space-y-3">
    <h3 className="font-semibold">观察与独立具名复核</h3>
    <p className="text-sm">当前固定问题、整改或访问范围尚不能核对。请先读取当前事实，尚未发起操作。</p>
  </section>;
  return <FactFlow key={identity} {...props} host={props.host} identity={identity}/>;
}
function FactFlow({ host, inputs, preview: requestPreview, execute, readReview, onSaved, onRefresh,
  onPendingChange, onAccessRejected, readHistory, blocked = false, hostAccessRejected = false, identity }: FactWorkflowProps & { host: FactHost; identity: string }) {
  const [local, setLocal] = useState<FactLocal>(() => blankFactLocal(identity));
  const [prepared, setPrepared] = useState<FactPrepared | null>(null), [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false), [readRequired, setReadRequired] = useState(false), [rejected, setRejected] = useState(false);
  const [notice, setNotice] = useState(""), [formEpoch, setFormEpoch] = useState(0);
  const current = useRef(local), live = useRef({ host, basis: factHostBasis(host) });
  const alive = useRef(false), lock = useRef(false), denied = useRef(false), restored = useRef(false);
  const rejectedEpoch = useRef<string | null>(null), lastBasis = useRef<string | undefined>(undefined);
  const dialog = useRef<HTMLDialogElement>(null);
  const storageKey = `pdos-next:capa-facts:${identity}`;
  const basis = factHostBasis(host);
  const save = useCallback((next: FactLocal) => {
    current.current = snapshot(next);
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Exact in-memory recovery remains. */ }
    if (alive.current) setLocal(current.current);
  }, [storageKey]);
  const clearPrivate = useCallback((saved: boolean, late = false) => {
    denied.current = true; rejectedEpoch.current = live.current.host.access_epoch;
    current.current = { ...blankFactLocal(identity), outcome: saved ? "saved" : "none" };
    try { localStorage.removeItem(storageKey); } catch { /* No private fallback. */ }
    if (alive.current) { setLocal(current.current); setPrepared(null); setRejected(true); setFormEpoch(v => v + 1); }
    onAccessRejected?.(saved, late || !alive.current);
  }, [identity, storageKey, onAccessRejected]);
  useLayoutEffect(() => {
    live.current = { host, basis };
    if (hostAccessRejected) {
      if (!denied.current) clearPrivate(current.current.outcome === "saved" || current.current.savedReceipt !== null);
    } else if (denied.current && basis !== null && rejectedEpoch.current !== host.access_epoch) {
      denied.current = false; setRejected(false); setReadRequired(false);
    }
    if (lastBasis.current !== undefined && lastBasis.current !== basis) {
      save(factBasisChanged(current.current)); setPrepared(null); setFormEpoch(v => v + 1);
    }
    lastBasis.current = basis ?? "";
    return () => { live.current = { host, basis: null }; };
  }, [host, basis, hostAccessRejected, clearPrivate, save]);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      if (!restored.current && !denied.current) {
        restored.current = true;
        try { const value = restoreFactLocal(JSON.parse(localStorage.getItem(storageKey) ?? "null"), identity);
          if (value) { current.current = value; setLocal(value); if (value.outcome === "saved") { setReadRequired(true); setNotice("已取得保存回执，请只刷新读取，不重复提交。"); } }
        } catch { /* Invalid or different-scope state never becomes a write. */ }
      }
      setReady(true);
    });
    return () => { alive.current = false; if (restored.current && !denied.current) save(factBasisChanged(current.current)); };
  }, [identity, storageKey, save]);
  useEffect(() => { if (ready) onPendingChange?.(local.pending !== null); }, [ready, local.pending, onPendingChange]);
  useEffect(() => { if (prepared && !rejected) dialog.current?.showModal(); else dialog.current?.close(); }, [prepared, rejected]);

  async function perform(waiting: FactPending, expectedBasis: string | null) {
    if (lock.current || denied.current || hostAccessRejected) return;
    lock.current = true; setBusy(true); setNotice(""); let stage = waiting;
    save(factBegin(current.current, waiting));
    try {
      if (stage.stage === "inputs") {
        const command = factInputsCommand(await inputs(stage.command), stage.command);
        if (denied.current || !alive.current) return;
        if (!command) { save({ ...current.current, pending: null }); setNotice("服务器返回当前缺项，本次尚未提交。请先核对资料与本操作职责。"); return; }
        if (expectedBasis !== live.current.basis) { save(factBasisChanged(current.current)); setNotice("当前范围或事实已变化，旧选择已废弃；尚未提交。"); return; }
        stage = { stage: "preview", command }; save({ ...current.current, pending: stage });
      }
      if (stage.stage === "preview") {
        const value = factPrepared(await requestPreview(stage.command), stage.command);
        if (denied.current || !alive.current) return;
        if (!value) throw new Error("原请求和实际预览不能完整对应。");
        if (expectedBasis !== live.current.basis) { save(factBasisChanged(current.current)); setNotice("当前事实已变化，旧预览已废弃，请重新核对。"); return; }
        setPrepared(value); return;
      }
      const value = await execute(stage.command);
      if (!factReceipt(value, stage.command.operation)) throw new Error("尚未取得本操作明确保存回执。");
      if (denied.current) { clearPrivate(true); if (alive.current) setNotice("已取得保存结果；当前访问不可用，不能重发已保存操作。"); return; }
      save(factSaved(current.current, value));
      if (!alive.current) return;
      setPrepared(null); setFormEpoch(v => v + 1); setReadRequired(true);
      setNotice(`${opLabel(value.operation)}已保存或读取原回执。尚未作有效性或关闭决定。`);
      await onSaved(value);
      if (alive.current) setReadRequired(false);
    } catch (failure) {
      const outcome = factFailure(current.current, failure);
      if (outcome.clearPrivate) clearPrivate(outcome.saved);
      if (!alive.current) return;
      if (outcome.saved) setNotice(outcome.clearPrivate ? "已取得保存结果；当前访问不可用，不能重发已保存操作。" : "已取得保存回执；随后刷新失败，请只重试读取，不能重复提交。");
      else if (outcome.clearPrivate) setNotice("当前访问不可用，私有材料与原预览已清除，请重新核对范围。");
      else if (stage.stage === "execute") { setPrepared(null); setNotice("尚未取得确定保存回执。完整原请求与原标识已保留，只能按原请求恢复，不能另造操作。"); }
      else setNotice("本次来源核对或实质预览尚未完成，请按原请求恢复；尚未提交。");
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function submit(op: FactOperation, payload: FactPayload) {
    if (lock.current || blocked || readRequired || denied.current || current.current.pending) return;
    try { const command = newFactCommand(live.current.host, op, payload, crypto.randomUUID(), crypto.randomUUID());
      void perform({ stage: "inputs", command }, live.current.basis);
    } catch (error) { setNotice(error instanceof Error ? error.message : "请核对实际材料。"); }
  }
  function cancel() {
    if (lock.current || current.current.pending?.stage === "execute") return;
    save({ ...current.current, pending: null }); setPrepared(null);
  }
  async function refresh() {
    if (lock.current) return; lock.current = true; setBusy(true);
    try { await onRefresh(); if (alive.current) { setReadRequired(false); setNotice("已请求重新读取当前事实；读取没有发起业务操作。"); } }
    catch (failure) { const result = factFailure(current.current, failure); if (result.clearPrivate) clearPrivate(result.saved);
      if (alive.current) setNotice(result.saved ? "已取得保存结果，当前事实仍读取失败；不能重复提交。" : "当前事实读取失败，尚未发起操作。"); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const business = prepared && !rejected && !hostAccessRejected ? (readReview ? readReview(prepared.review, prepared.command) : readFactBusinessReview(host, prepared.review, prepared.command)) : null;
  const complete = business?.complete === true && business.sections.length > 0 && business.effect.trim().length > 0;
  const confirm = prepared !== null && complete && !busy && !blocked && !readRequired && !rejected && !hostAccessRejected &&
    factCanPrepare(host, prepared.command.operation) && factPrepared(prepared, local.pending?.command ?? prepared.command) !== null;
  if (!ready) return <section className="panel" aria-busy="true"><p>正在读取本机原请求，尚未发起操作。</p></section>;
  if (rejected || hostAccessRejected) return <section className="panel space-y-3"><h3 className="font-semibold">观察与独立具名复核</h3>
    <p role="status">{local.outcome === "saved" ? "已取得保存结果；当前访问不可用，不能重发已保存操作。" : "当前访问不可用，已隐藏资料与所有办理材料。"}</p>
    <Button variant="outline" disabled={busy} onClick={() => void refresh()}><ArrowClockwise/>重试读取当前事实</Button></section>;
  const disabled = busy || blocked || readRequired || local.pending !== null || prepared !== null;
  return <div className={`space-y-4 ${wrap}`} aria-busy={busy}>
    <section className="panel space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">观察与独立具名复核</h3>
        <Button variant="outline" disabled={busy} onClick={() => void refresh()}><ArrowClockwise/>重试读取当前事实</Button></div>
      <p className="text-sm">记录实际观察与独立专业判断，分别办理。规则仅由可信宿主发布；保存不等于措施有效、问题关闭或成品放行。</p>
      {Object.values(host.operations).some(c => c.authority.synthetic) && <p className="rounded-lg border border-primary p-3 text-sm">本地合成演练：当前事实与资格用于核验流程，不代表真实生产资格。</p>}
      {notice && <p role="status" className="flex items-start gap-2 text-sm">{local.outcome === "saved" ? <CheckCircle className="mt-0.5 size-4 shrink-0 text-primary"/> : <WarningCircle className="mt-0.5 size-4 shrink-0"/>}{notice}</p>}
      {host.missing.length > 0 && <ul className="list-disc pl-5 text-sm">{host.missing.map((m, i) => <li key={`${m.code}:${i}`}>{m.detail}</li>)}</ul>}
      {local.pending && <div className="space-y-2 rounded-lg border border-primary p-3 text-sm">
        <p>{local.pending.stage === "execute" ? "原提交回执尚待核对，原材料与原标识已锁定。" : "原操作核对尚未完成，尚未提交。"}</p>
        <Button disabled={busy} onClick={() => void perform(local.pending!, live.current.basis)}><ArrowClockwise/>按原请求恢复</Button>
        {local.pending.stage !== "execute" && <Button variant="outline" disabled={busy} onClick={cancel}>取消未提交的核对</Button>}
      </div>}
      {local.savedReceipt && <p className="text-sm">已取得{opLabel(local.savedReceipt.operation)}第 {local.savedReceipt.subject_revision} 版回执。请以服务器读取的固定历史为准。</p>}
    </section>
    <FactHistoryReading key={host.access_epoch} host={host} readHistory={readHistory}/>
    <FactForm key={`${basis}:${formEpoch}`} host={host} disabled={disabled} onSubmit={submit}/>
    <dialog ref={dialog} onCancel={e => { e.preventDefault(); cancel(); }} className="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/50">
      {prepared && <div className={`space-y-4 ${wrap}`}><div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">{prepared.write_tier === "T2" ? "具名专业决定：独立复核" : "实际观察：一次确认"}</h3>
        <Button variant="ghost" size="icon" disabled={busy} aria-label="返回核对办理材料" onClick={cancel}><X/></Button></div>
        {complete ? <BusinessReading value={business!}/> : <p role="alert">固定范围、原记录、专业依据与保存后果尚未完整显示，不能确认。</p>}
        <p className="subtle">实际发生时间保留原精度与时区；保存时记录的接收时间不代替事件发生时间。有效性与关闭仍须独立办理。</p>
        <p className="subtle">{prepared.expires_at ? `本次确认有效至 ${prepared.expires_at}。` : "本次具名决定须在提交时重核当前依据。"}提交回执未知时只恢复原请求。</p>
        <div className="flex flex-wrap gap-3"><Button disabled={!confirm} onClick={() => {
          if (confirm && prepared) void perform({ stage: "execute", command: prepared.command }, live.current.basis);
        }}><CheckCircle/>{prepared.write_tier === "T2" ? "以本人姓名作出专业复核决定" : "一次确认保存实际观察"}</Button>
          <Button variant="outline" disabled={busy} onClick={cancel}>返回核对</Button></div></div>}
    </dialog>
  </div>;
}

function BusinessReading({ value }: { value: FactBusinessReview }) {
  return <div className="space-y-4"><p className="font-medium">{value.title}</p>
    {value.synthetic && <p className="text-sm">本地合成事实，不代表真实生产资格。</p>}
    {value.sections.map((s, i) => <section key={`${s.title}:${i}`} className="space-y-2 rounded-lg border p-3"><h4 className="font-medium">{s.title}</h4>
      <dl className="grid gap-2 text-sm">{s.rows.map((r, n) => <div key={`${r.label}:${n}`} className={wrap}><dt className="subtle">{r.label}</dt><dd className="whitespace-pre-wrap">{r.value ?? "尚不能核对，保持未知"}</dd></div>)}</dl></section>)}
    <SourceReading sources={value.sources}/><p className="text-sm">{value.effect}</p></div>;
}
function SourceReading({ sources }: { sources: FactHost["sources"] }) {
  return <div className="space-y-2">{sources.map(s => <blockquote key={factSourceKey(s.source)} className="rounded-lg border p-3 text-sm">
    <p className="font-medium">{s.title} · 第 {s.source.revision} 版 · 原文第 {s.line} 行</p><p className="whitespace-pre-wrap">{s.quote}</p></blockquote>)}</div>;
}
function FactHistoryReading({ host, readHistory }: { host: FactHost; readHistory?: (cursor: string) => Promise<FactHost> }) {
  const [rows, setRows] = useState(host.history), [cursor, setCursor] = useState(host.history_page?.next_cursor ?? null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const more = async () => {
    if (!cursor || !readHistory || busy) return;
    setBusy(true); setError("");
    try {
      const page = await readHistory(cursor);
      if (!alive.current) return;
      setRows(old => [...old, ...page.history.filter(row => !old.some(saved => same(saved.ref, row.ref)))]);
      setCursor(page.history_page?.next_cursor ?? null);
    } catch { if (alive.current) setError("历史读取失败，请重试读取。"); }
    finally { if (alive.current) setBusy(false); }
  };
  return <section className="panel space-y-3"><h3 className="font-semibold">规则、观察与具名复核历史</h3>
    {!rows.length && <p className="text-sm">尚未返回可读的固定历史，不推定已观察或已复核。</p>}
    {rows.map(h => <details key={refKey(h.ref)} className={`rounded-lg border p-3 ${wrap}`}><summary className="cursor-pointer text-sm font-medium">{h.label} · 第 {h.ref.revision} 版</summary>
      <div className="mt-3 space-y-2 text-sm"><p>{h.current_evaluation === "not_evaluated_historical" ? "历史固定版本，当前资格未评估，只读保留。" : h.source_status === "current" ? "按服务器当前来源状态显示。" : "原来源需重核，不据历史结论办理新操作。"}</p>
        <dl className="grid gap-2">{["purpose", "observed_from", "observed_until", "valid_from", "valid_until", "created_at", "reason", "conclusion"].filter(k => Object.hasOwn(h.fact, k)).map(k =>
          <div key={k}><dt className="subtle">{{ purpose: "用途", observed_from: "实际观察开始", observed_until: "实际观察结束", valid_from: "适用开始", valid_until: "适用截止", created_at: "服务器保存时间", reason: "原因", conclusion: "专业结论" }[k]}</dt>
            <dd>{typeof h.fact[k] === "string" ? (k === "conclusion" ? resultLabels[h.fact[k] as keyof typeof resultLabels] ?? "尚不能核对" : h.fact[k]) : "尚不能核对"}</dd></div>)}
          {record(h.fact.at) && <div><dt className="subtle">实际事件时间与原时区</dt><dd>{typeof h.fact.at.occurred_at === "string" ? h.fact.at.occurred_at : "时间待核对"} · {typeof h.fact.at.original_timezone === "string" ? h.fact.at.original_timezone : "时区待核对"}</dd></div>}
        </dl>{h.missing.map((m, i) => <p key={`${m.code}:${i}`}>{m.detail}</p>)}
        <SavedFactDetails host={host} fact={h.fact}/>
        <details><summary className="cursor-pointer subtle">固定记录对账</summary><p>{h.ref.id} · 第 {h.ref.revision} 版</p></details></div></details>)}
    {error && <p role="alert" className="text-sm">{error}</p>}
    {cursor && readHistory && <Button variant="outline" disabled={busy} onClick={() => void more()}>读取更多固定历史</Button>}
  </section>;
}

function SavedFactDetails({ host, fact }: { host: FactHost; fact: Record<string, unknown> }) {
  const quoteRefs = (value: unknown) => Array.isArray(value) ? host.sources.filter(choice => value.some(ref => same(ref, choice.source))) : [];
  const strings = (value: Record<string, unknown>, fields: Record<string, string>) => <dl className="grid gap-2 text-sm">{Object.entries(fields).filter(([key]) => Object.hasOwn(value, key)).map(([key, label]) =>
    <div key={key}><dt className="subtle">{label}</dt><dd className="whitespace-pre-wrap">{value[key] === null ? "未提供，保持未知" : typeof value[key] === "string" || typeof value[key] === "number" ? String(value[key]) : "材料已固定，正文需核对原文"}</dd></div>)}</dl>;
  const sampling = record(fact.sampling) ? fact.sampling : null;
  return <div className="space-y-3">
    {sampling && <div className="space-y-2 rounded-lg border p-3"><h4 className="font-medium">固定抽样要求</h4>
      {strings(sampling, { minimum_records: "要求最少记录", observation_from: "规则观察开始", observation_until: "规则观察截止" })}
      <p>实际固定目标：{Array.isArray(sampling.targets) ? `${sampling.targets.length} 个` : "未返回，需核对"}。原样件、批次或总体身份均由服务器固定，界面不改写。</p></div>}
    {Array.isArray(fact.records) && fact.records.filter(record).map((r, i) => <div key={i} className="space-y-2 rounded-lg border p-3"><h4 className="font-medium">实际原观察记录 {i + 1}</h4>
      {strings(r, { occurred_at: "原事件发生时间", original_timezone: "原IANA时区" })}
      {record(r.raw_material) && strings(r.raw_material, { raw_value: "原值", value: "原值", unit: "单位", conditions: "实际工况", environment: "实际环境", equipment_label: "设备", text: "原事实说明", note: "原备注" })}
      {Array.isArray(r.missing_fields) && r.missing_fields.length > 0 && <p>原记录仍有 {r.missing_fields.length} 项字段缺失，保存不等于观察完整。</p>}
      <SourceReading sources={quoteRefs(r.sources)}/></div>)}
    {Array.isArray(fact.pair_applicability) && fact.pair_applicability.filter(record).map((r, i) => <div key={i} className="space-y-2 rounded-lg border p-3"><h4 className="font-medium">实际配对复核 {i + 1}</h4>
      <p>专业结论：{typeof r.conclusion === "string" ? resultLabels[r.conclusion as keyof typeof resultLabels] ?? "尚不能核对" : "尚不能核对"}</p>{strings(r, { reason: "本人结论说明" })}<SourceReading sources={quoteRefs(r.sources)}/></div>)}
    {Array.isArray(fact.action_fulfillment) && fact.action_fulfillment.filter(record).map((r, i) => <div key={i} className="space-y-2 rounded-lg border p-3"><h4 className="font-medium">措施履行复核 {i + 1}</h4>
      <p>材料类型：{r.classification === "investigation" ? "调查性措施" : r.classification === "formal_change" ? "正式变更材料" : "尚不能核对"}</p>
      <p>履行结论：{typeof r.conclusion === "string" ? resultLabels[r.conclusion as keyof typeof resultLabels] ?? "尚不能核对" : "尚不能核对"}</p>
      {strings(r, { reason: "本人结论说明" })}<SourceReading sources={quoteRefs(r.owner_refs)}/></div>)}
    {Array.isArray(fact.participants) && <p>固定记录保留 {fact.participants.length} 名实际参与者的owner材料；当前独立资格仍由服务器重新核对，不能据历史名单自授。</p>}
    <SourceReading sources={quoteRefs(fact.sources)}/>
  </div>;
}

function SourcePicker({ host, label, value, onChange }: { host: FactHost; label: string; value: string[]; onChange: (value: string[]) => void }) {
  return <fieldset className="min-w-0 space-y-2 rounded-lg border p-3"><legend className="px-1 text-sm font-medium">{label}</legend>
    {!host.sources.length && <p className="text-sm">暂无可选的真实原文出处。</p>}
    {host.sources.map(s => <div key={factSourceKey(s.source)} className={`space-y-1 text-sm ${wrap}`}>
      <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 accent-orange-700" checked={value.includes(factSourceKey(s.source))} onChange={e => onChange(e.target.checked ? [...value, factSourceKey(s.source)] : value.filter(k => k !== factSourceKey(s.source)))}/>
        <span className={wrap}>{s.title} · 第 {s.source.revision} 版 · 原文第 {s.line} 行</span></label>
      <details className="ml-6"><summary className="cursor-pointer subtle">查看完整原文</summary><p className={`whitespace-pre-wrap ${wrap}`}>{s.quote}</p></details></div>)}
  </fieldset>;
}
function FactForm({ host, disabled, onSubmit }: { host: FactHost; disabled: boolean; onSubmit: (op: FactOperation, payload: FactPayload) => void }) {
  const [operation, setOperation] = useState<FactOperation>(observationOperation), [ruleKey, setRuleKey] = useState("");
  const [recordKeys, setRecordKeys] = useState<string[]>([]), [observationKeys, setObservationKeys] = useState<string[]>([]);
  const [from, setFrom] = useState(""), [until, setUntil] = useState(""), [occurred, setOccurred] = useState(""), [timezone, setTimezone] = useState("");
  const [eventSource, setEventSource] = useState(""), [sources, setSources] = useState<string[]>([]), [coverage, setCoverage] = useState<string[]>([]);
  const [pairs, setPairs] = useState<Record<string, { conclusion: string; reason: string; sources: string[] }>>({});
  const [actions, setActions] = useState<Record<string, { conclusion: string; reason: string; sources: string[] }>>({});
  const [conclusion, setConclusion] = useState(""), [reason, setReason] = useState(""), [error, setError] = useState("");
  const [visibility, setVisibility] = useState<"private" | "category" | "audience">("private");
  const capability = host.operations[operation], rule = host.rules.find(r => refKey(r.ref) === ruleKey);
  const choose = (value: string[], key: string, checked: boolean) => checked ? [...value, key] : value.filter(k => k !== key);
  function selectRecord(key: string, checked: boolean) {
    const choice = host.records.find(r => r.key === key);
    if (disabled || !choice) return;
    const timing = checked && recordKeys.length === 0 ? factRecordTiming(choice) : null;
    if (timing) {
      setFrom(timing.observed_from); setUntil(timing.observed_until);
      setOccurred(timing.at.occurred_at); setTimezone(timing.at.original_timezone);
      const sourceKey = factSourceKey(timing.at.source); setEventSource(sourceKey);
      if (!sources.length) setSources([sourceKey]);
      if (!coverage.length) setCoverage([sourceKey]);
    }
    setRecordKeys(choose(recordKeys, key, checked));
  }
  function payload(): FactPayload {
    if (!rule || !eventTime(occurred) || !eventTimezone(timezone)) throw new Error("请选择固定规则并填写带时区的实际发生时间及原IANA时区。");
    const at: FactEvent = { occurred_at: occurred, original_timezone: timezone, source: selectFactSources(host, [eventSource])[0], effective_at: null };
    const common = { issue_id: host.binding.issue_id, expected_issue_revision: host.binding.current_issue.revision, capa_id: host.binding.capa_id,
      rule: rule.ref, at, sources: selectFactSources(host, sources), reason, visibility };
    if (operation === observationOperation) {
      const records = recordKeys.map(k => { const r = host.records.find(c => c.key === k); if (!r) throw new Error("原观察选项已变化。"); return r.record; });
      if (!records.some(r => r.sources.some(s => same(s, at.source)))) throw new Error("实际观察事件应选择本次原观察记录中的精确出处。");
      return { ...common, previous: rule.previous, target_keys: [...new Set(records.map(r => r.target_key))], observed_from: from,
        observed_until: until, records, coverage_sources: selectFactSources(host, coverage) };
    }
    if (!host.candidate) throw new Error("缺少可核对的真实固定候选。");
    const pair_applicability: PairAssessment[] = host.pairs.map(p => ({ mapping: p.mapping, method: p.method, criterion: p.criterion,
      conclusion: pairs[p.key]?.conclusion as PairAssessment["conclusion"], reason: pairs[p.key]?.reason ?? "", sources: selectFactSources(host, pairs[p.key]?.sources ?? []) }));
    const action_fulfillment: ActionAssessment[] = host.actions.map(a => ({ action_id: a.action_id, conclusion: actions[a.action_id]?.conclusion as ActionAssessment["conclusion"],
      reason: actions[a.action_id]?.reason ?? "", sources: selectFactSources(host, actions[a.action_id]?.sources ?? []) }));
    return { ...common, candidate: host.candidate, observations: observationKeys.map(k => { const r = host.observations.find(o => refKey(o) === k); if (!r) throw new Error("固定观察版本已变化。"); return r; }),
      pair_applicability, action_fulfillment, conclusion: conclusion as PairAssessment["conclusion"] };
  }
  return <form className={`panel space-y-4 ${wrap}`} onSubmit={e => { e.preventDefault(); if (disabled || !factCanPrepare(host, operation)) return;
    try { setError(""); onSubmit(operation, payload()); } catch (failure) { setError(failure instanceof Error ? failure.message : "请核对真实材料。"); } }}>
    <h3 className="font-semibold">办理材料</h3><p className="text-sm">用途：{host.binding.purpose}。受众：{host.binding.visibility === "private" ? "私人固定范围" : "品类共享固定范围"}。当前问题第 {host.binding.current_issue.revision} 版，不能以原失败版本替代当前核对。</p>
    <label className="block space-y-1 text-sm"><span>本次操作</span><select disabled={disabled} className={input} value={operation} onChange={e => setOperation(e.target.value as FactOperation)}><option value={observationOperation}>记录实际观察 · 一次确认</option><option value={reviewOperation}>独立具名专业复核 · 具名决定</option></select></label>
    <fieldset disabled={disabled || !factCanPrepare(host, operation)} className="min-w-0 space-y-4">
      <label className="block space-y-1 text-sm"><span>本次保存受众（默认私人）</span><select className={input} value={visibility} onChange={e => setVisibility(e.target.value as "private" | "category" | "audience")}><option value="private">私人固定范围</option>{host.binding.visibility === "category" && <option value="product">品类共享固定范围</option>}</select></label>
      <p className="subtle">必须与服务器固定的原问题受众一致。共享原问题需要本人明确选择共享；私人材料不能扩大受众。</p>
      <label className="block space-y-1 text-sm"><span>固定已发布规则</span><select className={input} value={ruleKey} onChange={e => setRuleKey(e.target.value)}><option value="">请选择真实固定规则</option>{host.rules.map(r => <option key={refKey(r.ref)} value={refKey(r.ref)}>{r.label} · 第 {r.ref.revision} 版</option>)}</select></label>
      {operation === observationOperation ? <>
        <label className="block space-y-1 text-sm"><span>实际观察开始（带UTC偏移的ISO时间，保留原精度）</span><input className={input} value={from} onChange={e => setFrom(e.target.value)} placeholder="2026-10-03T09:00:00.123456-07:00"/></label>
        <label className="block space-y-1 text-sm"><span>实际观察结束</span><input className={input} value={until} onChange={e => setUntil(e.target.value)}/></label>
        <fieldset className="min-w-0 space-y-2 rounded-lg border p-3"><legend className="px-1 text-sm font-medium">已核的原观察记录</legend><p className="subtle">选择首条原记录时采用服务器核对的原范围与事件时钟，请本人再次核对，不自动产生新的发生时间。</p>
          {!host.records.length && <p className="text-sm">暂无可选择的原观察记录。不能补造数值或以填写表单推定观察完整。</p>}
          {host.records.map(r => <label key={r.key} className={`flex items-start gap-2 text-sm ${wrap}`}><input type="checkbox" className="mt-1 accent-orange-700" checked={recordKeys.includes(r.key)} onChange={e => selectRecord(r.key, e.target.checked)}/>
            <span>{r.label}<span className="block subtle">{r.detail}</span><span className="block">{r.record.occurred_at} · {r.record.original_timezone}</span></span></label>)}</fieldset>
        <SourcePicker host={host} label="抽样与覆盖依据" value={coverage} onChange={setCoverage}/>
      </> : <>
        <p className="text-sm">仅复核服务器给出的固定候选、真实配对与整改措施。独立性与专业资格由服务器核对，不从填写结论取得。</p>
        <fieldset className="min-w-0 space-y-2 rounded-lg border p-3"><legend className="px-1 text-sm font-medium">采用的固定观察版本</legend>{host.observations.map(o => <label key={refKey(o)} className="flex gap-2 text-sm"><input type="checkbox" checked={observationKeys.includes(refKey(o))} onChange={e => setObservationKeys(choose(observationKeys, refKey(o), e.target.checked))}/><span>固定观察第 {o.revision} 版</span></label>)}</fieldset>
        {host.pairs.map(p => <AssessmentFields key={p.key} host={host} title={p.label} detail={p.detail} value={pairs[p.key] ?? { conclusion: "", reason: "", sources: [] }} onChange={v => setPairs(old => ({ ...old, [p.key]: v }))}/>)}
        {host.actions.map(a => <AssessmentFields key={a.action_id} host={host} title={a.label} detail={a.detail} value={actions[a.action_id] ?? { conclusion: "", reason: "", sources: [] }} onChange={v => setActions(old => ({ ...old, [a.action_id]: v }))}/>)}
        <label className="block space-y-1 text-sm"><span>本人总体专业结论</span><ConclusionSelect value={conclusion} onChange={setConclusion}/></label>
      </>}
      <label className="block space-y-1 text-sm"><span>{operation === observationOperation ? "记录实际观察的事件发生时间" : "实际作出本次专业决定的时间"}</span><input className={input} value={occurred} onChange={e => setOccurred(e.target.value)} placeholder="带UTC偏移的ISO时间，保留微秒"/></label>
      <label className="block space-y-1 text-sm"><span>事件原IANA时区</span><input className={input} value={timezone} onChange={e => setTimezone(e.target.value)} placeholder="America/Los_Angeles"/></label>
      <label className="block space-y-1 text-sm"><span>实际事件精确出处</span><select className={input} value={eventSource} onChange={e => setEventSource(e.target.value)}><option value="">请选择发生时间的真实原文行</option>{host.sources.filter(s => operation !== observationOperation || host.records.some(r => recordKeys.includes(r.key) && r.record.sources.some(ref => same(ref, s.source)))).map(s => <option key={factSourceKey(s.source)} value={factSourceKey(s.source)}>{s.title} · 第 {s.source.revision} 版 · 原文第 {s.line} 行</option>)}</select></label>
      <SourcePicker host={host} label="本次通用精确来源" value={sources} onChange={setSources}/>
      <label className="block space-y-1 text-sm"><span>本人事实说明与办理原因</span><textarea className={input} rows={3} value={reason} maxLength={2000} onChange={e => setReason(e.target.value)}/></label>
      <Button type="submit" disabled={!factCanPrepare(host, operation)}><CheckCircle/>{operation === observationOperation ? "核对观察材料并预览" : "核对专业结论并具名预览"}</Button>
    </fieldset>
    {!factCanPrepare(host, operation) && <div className="space-y-1 text-sm"><p>{capability.authority.qualified === null ? "当前专业资格尚不能核对，暂不能办理。" : "当前范围、职责或独立资格不满足，暂不能办理。"}</p>{capability.missing.map((m, i) => <p key={`${m.code}:${i}`}>{m.detail}</p>)}</div>}
    {error && <p role="alert" className="text-sm">{error}</p>}
  </form>;
}
function ConclusionSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <select className={input} value={value} onChange={e => onChange(e.target.value)}><option value="">请明确选择本人结论</option>{Object.entries(resultLabels).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select>;
}
function AssessmentFields({ host, title, detail, value, onChange }: { host: FactHost; title: string; detail: string;
  value: { conclusion: string; reason: string; sources: string[] }; onChange: (value: { conclusion: string; reason: string; sources: string[] }) => void }) {
  return <fieldset className={`min-w-0 space-y-3 rounded-lg border p-3 ${wrap}`}><legend className="px-1 text-sm font-medium">{title}</legend><p className="text-sm subtle">{detail}</p>
    <label className="block space-y-1 text-sm"><span>本项专业结论</span><ConclusionSelect value={value.conclusion} onChange={conclusion => onChange({ ...value, conclusion })}/></label>
    <label className="block space-y-1 text-sm"><span>结论说明</span><textarea className={input} rows={2} value={value.reason} maxLength={2000} onChange={e => onChange({ ...value, reason: e.target.value })}/></label>
    <SourcePicker host={host} label="本项结论精确依据" value={value.sources} onChange={sources => onChange({ ...value, sources })}/></fieldset>;
}
