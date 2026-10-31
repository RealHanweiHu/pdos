"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { agreementCategories, agreementPendingKey, matchAgreementReceipt, parseAgreementPending, validateAgreement, type Agreement, type AgreementCategory, type AgreementReading, type AgreementReceipt, type AgreementRequest } from "@/lib/provider-agreements";
import type { WorkspaceTransport } from "@/lib/workspace-api";

type Draft = { provider: string; signed: string; expires: string; categories: AgreementCategory[]; retention: string; training: string; active: boolean; promptCacheAllowed: boolean };
const empty: Draft = { provider: "", signed: "", expires: "", categories: [], retention: "", training: "", active: true, promptCacheAllowed: false };
const statusText = { active: "有效", inactive: "已停用", expired: "已到期", not_started: "未生效" };
const inputClass = "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm";
function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function dateText(value: string) { return new Date(value).toLocaleString("zh-CN"); }
function cacheText(value: boolean | null | undefined) { return value === true ? "允许" : value === false ? "关闭" : "未取得明确允许（关闭）"; }

function Review({ request }: { request: AgreementRequest }) {
  return <div className="space-y-2 break-words text-sm">
    <p className="font-medium">{request.provider} · 第 {request.expected_revision + 1} 版 · {request.active ? "登记为有效" : "停用"}</p>
    <p>签约：{dateText(request.signed_on)}<br />到期：{dateText(request.expires_at)}</p>
    <p>允许数据：{request.data_categories.map(key => agreementCategories[key]).join("、")}</p>
    <p className="whitespace-pre-wrap">留存条款：{request.retention_terms}</p>
    <p className="whitespace-pre-wrap">训练条款：{request.training_terms}</p>
    <p>可控提示缓存：{cacheText(request.prompt_cache_allowed)}</p>
  </div>;
}

export function ConnectedProviderAgreements({ api, principalId, categoryId }: { api: WorkspaceTransport; principalId: string; categoryId: string }) {
  const prefix = useId(), epoch = useRef(0), locked = useRef(false);
  const key = agreementPendingKey(principalId, categoryId);
  const [reading, setReading] = useState<AgreementReading | null>(null);
  const [draft, setDraft] = useState<Draft>(empty);
  const [preview, setPreview] = useState<AgreementRequest | null>(null);
  const [pending, setPending] = useState<AgreementRequest | null>(null);
  const [receipt, setReceipt] = useState<AgreementReceipt | null>(null);
  const [busy, setBusy] = useState(true), [error, setError] = useState("");
  const [broken, setBroken] = useState(false);

  async function load(current: number, cursor?: string) {
    const value = await api<AgreementReading>(`v1/provider-agreements?page_size=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    if (epoch.current === current) setReading(previous => cursor && previous ? { ...value, items: [...previous.items, ...value.items] } : value);
    return value;
  }

  function accept(original: AgreementRequest, value: AgreementReceipt, current: number) {
    if (!matchAgreementReceipt(value, original, principalId, categoryId)) throw new Error("回执与原登记范围不一致，请继续核对原请求。");
    if (epoch.current !== current) return;
    setReceipt(value); setPending(null); setPreview(null);
    try { localStorage.removeItem(key); }
    catch { setError("登记已取得回执；本地恢复记录未清除，重新打开时会再次只读核对。"); }
  }

  useEffect(() => {
    const current = ++epoch.current;
    locked.current = true;
    async function open() {
      try {
        const raw = localStorage.getItem(key);
        if (raw) {
          let original: AgreementRequest;
          try { original = parseAgreementPending(raw); }
          catch (failure) { setBroken(true); throw failure; }
          if (epoch.current !== current) return;
          setPending(original);
          const result = await api<{ receipt: AgreementReceipt | null }>("v1/provider-agreements/recover", original);
          if (result.receipt) accept(original, result.receipt, current);
        }
      } catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      try { await load(current); }
      catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
      finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
    }
    void open();
    return () => { epoch.current = current + 1; };
    // Scope-owned component remounts when the person or category changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key]);

  async function run(action: (current: number) => Promise<void>) {
    if (locked.current) return;
    const current = epoch.current;
    locked.current = true; setBusy(true); setError("");
    try { await action(current); }
    catch (failure) { if (epoch.current === current) setError((failure as Error).message); }
    finally { if (epoch.current === current) { locked.current = false; setBusy(false); } }
  }

  function prepare(event: FormEvent) {
    event.preventDefault();
    if (!reading?.can_edit || pending || broken) return;
    void run(async current => {
      const original: AgreementRequest = {
        provider: draft.provider.trim(), expected_revision: 0, signed_on: new Date(draft.signed).toISOString(),
        expires_at: new Date(draft.expires).toISOString(), data_categories: [...draft.categories],
        retention_terms: draft.retention.trim(), training_terms: draft.training.trim(), active: draft.active,
        prompt_cache_allowed: draft.promptCacheAllowed,
        decision: "批准", idempotency_key: crypto.randomUUID(),
      };
      const invalid = validateAgreement(original);
      if (invalid) throw new Error(invalid);
      const value = await api<AgreementReading>(`v1/provider-agreements?provider=${encodeURIComponent(original.provider)}`);
      if (!value.can_edit) { if (epoch.current === current) setReading(value); throw new Error("当前身份已无协议登记权限。"); }
      original.expected_revision = value.items[0]?.revision ?? 0;
      if (epoch.current === current) { setPreview(original); setReceipt(null); }
    });
  }

  async function save(original: AgreementRequest, current: number) {
    // Persist only the person's approved original before its first write.
    localStorage.setItem(key, JSON.stringify(original));
    if (epoch.current === current) { setPending(original); setPreview(null); }
    let value: AgreementReceipt;
    try { value = await api<AgreementReceipt>("v1/provider-agreements", original); }
    catch (failure) {
      const status = (failure as { status?: number }).status;
      if (epoch.current === current && status !== undefined && status >= 400 && status < 500) {
        localStorage.removeItem(key); setPending(null);
      }
      throw failure;
    }
    accept(original, value, current);
    try { await load(current); }
    catch { if (epoch.current === current) setError("登记已取得回执；当前协议列表读取失败，请刷新。"); }
  }

  function reuse(row: Agreement) {
    setDraft({ provider: row.provider, signed: localDate(row.signed_on), expires: localDate(row.expires_at),
      categories: [...row.data_categories], retention: row.retention_terms, training: row.training_terms, active: row.active, promptCacheAllowed: row.prompt_cache_allowed === true });
    setError(""); setReceipt(null);
  }

  const disabled = busy || !reading?.can_edit || !!preview || !!pending || broken;
  return <section aria-label="服务商数据协议" className="provider-agreements space-y-4 rounded-lg border p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">服务商数据协议</h2><Button variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current); })}>刷新协议登记</Button></div>
    <p className="text-sm text-muted-foreground">按已签约协议登记允许接收的数据和条款，由租户管理员本人批准。登记在当前租户的所有品类共用；服务商标识须与服务端模型、搜索或读取配置一致。</p>
    {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
    {busy && <p role="status" className="text-sm">正在核对协议和回执…</p>}
    {receipt && <p role="status" className="break-all text-sm">协议登记已完成 · {receipt.result.provider} · 第 {receipt.subject_revision} 版<br />回执：{receipt.id}</p>}
    {reading && <div className="space-y-3">
      {!reading.items.length && <p className="text-sm text-muted-foreground">当前租户尚无服务商协议登记。协议是可选治理工具，登记后按有效条款约束数据类别和可控提示缓存。</p>}
      {reading.items.map(row => <article key={row.id} className="space-y-2 rounded-lg border bg-muted/20 p-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><h3 className="break-all font-medium">{row.provider} · 第 {row.revision} 版</h3><span>{statusText[row.status]}</span></div>
        <p>允许数据：{row.data_categories.map(value => agreementCategories[value]).join("、")}</p>
        <p>协议可控提示缓存：{cacheText(row.prompt_cache_allowed)}{row.status !== "active" && "（此协议当前未生效）"}</p>
        <p>到期：{dateText(row.expires_at)} · 登记人：{row.registered_by_name ?? row.registered_by}</p>
        <details><summary className="cursor-pointer">查看条款与回执</summary><div className="mt-2 space-y-2 whitespace-pre-wrap break-words"><p>签约：{dateText(row.signed_on)}</p><p>留存条款：{row.retention_terms}</p><p>训练条款：{row.training_terms}</p><p className="break-all">回执：{row.receipt_id ?? "尚无回执"}</p></div></details>
        {reading.can_edit && <Button variant="outline" disabled={disabled} onClick={() => reuse(row)}>以此协议续版</Button>}
      </article>)}
      {reading.next_cursor && <Button variant="outline" disabled={busy} onClick={() => void run(async current => { await load(current, reading.next_cursor!); })}>读取更多协议</Button>}
      {!reading.can_edit && <p className="text-sm text-muted-foreground">当前可读取协议；登记和变更须由有品类写入权限的租户管理员本人办理。</p>}
    </div>}
    {pending && <section aria-label="恢复原协议登记" className="space-y-3 rounded-lg border border-primary/40 p-3">
      <h3 className="font-medium">原登记结果待核对</h3><Review request={pending} />
      <p className="text-sm text-muted-foreground">重新打开会先查询原回执。点击下方按钮会再次核对；尚无回执且当前仍有权限时，沿用本人已批准的同一请求重试。</p>
      <Button className="h-auto whitespace-normal" disabled={busy} onClick={() => void run(async current => {
        const result = await api<{ receipt: AgreementReceipt | null }>("v1/provider-agreements/recover", pending);
        if (result.receipt) { accept(pending, result.receipt, current); await load(current); }
        else {
          const value = await load(current);
          if (!value.can_edit) throw new Error("尚未取得原回执，当前身份已无登记权限。请由管理员核对现有协议。");
          await save(pending, current);
        }
      })}>核对并重试原登记</Button>
    </section>}
    {broken && <Button variant="outline" disabled={busy} onClick={() => {
      try { localStorage.removeItem(key); setBroken(false); setError(""); }
      catch { setError("本地恢复记录暂时无法移除。"); }
    }}>已核对当前登记，移除损坏的恢复记录</Button>}
    <form onSubmit={prepare} className="space-y-4">
      <h3 className="font-medium">登记或变更协议</h3>
      <fieldset disabled={disabled} className="grid gap-4 sm:grid-cols-2">
        <label htmlFor={`${prefix}-provider`} className="grid gap-1 text-sm sm:col-span-2">服务商标识<input id={`${prefix}-provider`} value={draft.provider} onChange={event => setDraft({ ...draft, provider: event.target.value })} required maxLength={160} autoComplete="off" className={inputClass} /></label>
        <label htmlFor={`${prefix}-signed`} className="grid gap-1 text-sm">签约时间（本地时区）<input id={`${prefix}-signed`} type="datetime-local" value={draft.signed} onChange={event => setDraft({ ...draft, signed: event.target.value })} required className={`${inputClass} min-w-0`} /></label>
        <label htmlFor={`${prefix}-expires`} className="grid gap-1 text-sm">到期时间（本地时区）<input id={`${prefix}-expires`} type="datetime-local" value={draft.expires} onChange={event => setDraft({ ...draft, expires: event.target.value })} required className={`${inputClass} min-w-0`} /></label>
        <div className="space-y-2 sm:col-span-2"><p className="text-sm font-medium">协议允许的数据类别</p>{Object.entries(agreementCategories).map(([value, label]) => <label htmlFor={`${prefix}-${value}`} key={value} className="agreement-check text-sm"><input id={`${prefix}-${value}`} type="checkbox" checked={draft.categories.includes(value as AgreementCategory)} onChange={event => setDraft({ ...draft, categories: event.target.checked ? [...draft.categories, value as AgreementCategory] : draft.categories.filter(item => item !== value) })} />{label}</label>)}</div>
        <label htmlFor={`${prefix}-retention`} className="grid gap-1 text-sm sm:col-span-2">留存条款<textarea id={`${prefix}-retention`} value={draft.retention} onChange={event => setDraft({ ...draft, retention: event.target.value })} required minLength={3} rows={3} className={inputClass} /></label>
        <label htmlFor={`${prefix}-training`} className="grid gap-1 text-sm sm:col-span-2">训练条款<textarea id={`${prefix}-training`} value={draft.training} onChange={event => setDraft({ ...draft, training: event.target.value })} required minLength={3} rows={3} className={inputClass} /></label>
        <div className="space-y-1 sm:col-span-2"><label htmlFor={`${prefix}-prompt-cache`} className="agreement-check text-sm"><input id={`${prefix}-prompt-cache`} type="checkbox" checked={draft.promptCacheAllowed} onChange={event => setDraft({ ...draft, promptCacheAllowed: event.target.checked })} />协议明确允许提示缓存</label><p className="text-xs text-muted-foreground">仅在协议允许短期留存时勾选。只控制服务商接口支持的提示缓存，不改变其他留存条款。</p></div>
        <label htmlFor={`${prefix}-active`} className="agreement-check text-sm sm:col-span-2"><input id={`${prefix}-active`} type="checkbox" checked={draft.active} onChange={event => setDraft({ ...draft, active: event.target.checked })} />启用此协议登记（取消勾选以停用）</label>
      </fieldset>
      <Button disabled={disabled} type="submit">核对协议并预览</Button>
    </form>
    {preview && <section aria-label="本人批准协议登记" className="space-y-3 rounded-lg border border-primary/40 p-3">
      <h3 className="font-medium">确认按已签约协议登记</h3><Review request={preview} />
      <p className="text-sm text-muted-foreground">点击批准将记录你的具名决定，适用于当前租户的所有品类。登记本身不调用外部服务，实际调用仍会核对当前范围、资格和预算。</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy || !reading?.can_edit} onClick={() => void run(current => save(preview, current))}>本人批准登记</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button></div>
    </section>}
  </section>;
}
