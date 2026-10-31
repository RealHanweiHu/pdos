"use client";

import { useEffect, useRef, useState } from "react";
import { browserApi } from "@/lib/browser-api";
import { bindingCallback, bindingStorageKey, parseBindStart, parseDingPreview, parseDingSettings, prepareBindStart, removeCallback, validDingBody, type DingApi, type DingBinding, type DingPreview, type DingSettings } from "@/lib/dingtalk";
import { Button } from "./ui/button";

type Pending = { path: string; body: Record<string, unknown> };
type Receipt = { delivery_id: string; state: string; phase: string; attempts: number; error_code: string | null };
const stateName: Record<string, string> = { planned: "待投递", sending: "发送结果待核对", unknown: "发送结果未知；不会自动重发", delivered: "已确认发送成功", blocked: "已阻止投递", cancelled: "已取消" };
const pendingKey = (principalId: string) => `pdos-next:dingtalk-request:${principalId}`;
const blank = { corp_id: "", client_id: "", robot_code: "", secret_arn: "", secret_version: "", active: false };
const message = (e: unknown) => e instanceof Error ? e.message : "操作尚未核实。";

export function DingTalkSettings({ principalId, api = browserApi }: { principalId: string; api?: DingApi }) {
  const [reading, setReading] = useState<DingSettings | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<Pending | null>(null);
  const [callback, setCallback] = useState<Record<string, string> | null>(null), [notice, setNotice] = useState("");
  const [form, setForm] = useState(blank), [reason, setReason] = useState("");
  const [receipts, setReceipts] = useState<Receipt[] | null>(null), [runId, setRunId] = useState("");
  const [quotes, setQuotes] = useState(false), [preview, setPreview] = useState<DingPreview | null>(null);
  const active = useRef(true), requestBusy = useRef(false);
  function applyReading(value: DingSettings) {
    if (!active.current) return;
    setReading(value);
    const a = value.application;
    if (value.can_manage) setForm({ corp_id: a?.corp_id ?? "", client_id: a?.client_id ?? "", robot_code: a?.robot_code ?? "", secret_arn: a?.secret_arn ?? "", secret_version: a?.secret_version ?? "", active: a?.active ?? false });
  }
  async function refresh() {
    const value = parseDingSettings(await api<unknown>("v1/personal/dingtalk/settings"), principalId);
    applyReading(value);
    return value;
  }
  useEffect(() => {
    active.current = true;
    // Loading never binds, saves, sends, confirms or reconciles automatically.
    void api<unknown>("v1/personal/dingtalk/settings").then(raw => {
      if (!active.current) return;
      const value = parseDingSettings(raw, principalId);
      applyReading(value);
      try {
        const saved = sessionStorage.getItem(pendingKey(principalId));
        const original = saved ? JSON.parse(saved) : null;
        if (original?.principalId === principalId && typeof original.path === "string" && /\/(?:revoke|confirm)$/.test(original.path) && validDingBody(original.path, original.body)) setPending({ path: original.path, body: original.body });
      } catch { setError("原操作恢复记录不可用，请先读取当前状态。"); }
      if (new URLSearchParams(window.location.search).get("dingtalk_callback") !== "1") return;
      try {
        const raw = sessionStorage.getItem(bindingStorageKey(principalId));
        const intent = parseBindStart(raw ? JSON.parse(raw) : null, principalId);
        const returned = bindingCallback(window.location.search, intent);
        if (returned) setCallback(returned);
      } catch (e) { setError(message(e)); }
      finally { window.history.replaceState(window.history.state, "", removeCallback(window.location.search)); }
    }).catch(e => { if (active.current) setError(message(e)); });
    return () => { active.current = false; };
    // Scope changes remount through PlatformSettings' principal key.
  }, [principalId, api]);
  async function work(fn: () => Promise<void>) {
    if (requestBusy.current) return;
    requestBusy.current = true; setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { if (active.current) setError(message(e)); }
    finally { requestBusy.current = false; if (active.current) setBusy(false); }
  }
  async function submit(original: Pending) {
    sessionStorage.setItem(pendingKey(principalId), JSON.stringify({ ...original, principalId }));
    setPending(original);
    const value = await api<unknown>(original.path, original.body);
    if (!active.current) return;
    if (original.path.endsWith("/revoke")) {
      const row = value as { binding_id?: string; active?: boolean };
      if (row.binding_id !== original.body.binding_id || row.active !== false) throw new Error("撤绑回执尚未核实，请保留原请求。");
    } else if (original.path.endsWith("/confirm")) {
      const row = value as { consent_id?: string; state?: string };
      if (!row.consent_id || !row.state) throw new Error("分享受理回执尚未核实，请保留原请求。");
      setPreview(null);
    }
    sessionStorage.removeItem(pendingKey(principalId));
    setPending(null); setNotice(original.path.endsWith("/confirm") ? "分享已受理；请读取投递回执核对实际结果。" : "已撤销绑定，未完成的工作将按原守卫取消。");
    await refresh();
  }
  function revoke(row: DingBinding) {
    if (!reason.trim()) { setError("请填写本次撤绑原因。"); return; }
    void work(() => submit({ path: "v1/personal/dingtalk/bindings/revoke", body: { binding_id: row.binding_id, expected_epoch: row.epoch, reason: reason.trim(), request_key: crypto.randomUUID() } }));
  }
  const own = reading?.bindings.filter(b => b.owner_id === principalId) ?? [];
  const bound = own.some(b => b.active), disabled = busy || pending !== null;
  return <section className="panel mt-6 space-y-5" aria-label="钉钉账号与投递">
    <header><h2 className="text-lg font-semibold">钉钉与本人账号</h2><p className="subtle mt-1">单聊或群里 @小Pai 后，答案默认私发本人。业务操作请回到 PDOS 办理。</p></header>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!reading ? <p role="status">正在读取本人绑定状态…</p> : <>
      {!reading.configured && <p role="status">钉钉协议端口尚未配置，当前不能绑定或发送。已登记状态仅供核对。</p>}
      {reading.application ? <p>应用登记第 {reading.application.revision} 版 · {reading.application.active ? "启用" : "停用"}</p> : <p>尚未登记钉钉应用。</p>}
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void work(async () => { await refresh(); })}>重新读取当前状态</Button>
      <Button disabled={disabled || bound || !reading.configured || !reading.application?.active} onClick={() => void work(async () => {
        const appId = reading.application!.application_id;
        const value = await api<unknown>("v1/personal/dingtalk/bindings/begin", { application_id: appId });
        if (!active.current) return;
        const started = prepareBindStart(value, principalId, appId, window.location.origin);
        sessionStorage.setItem(bindingStorageKey(principalId), JSON.stringify(started.pending));
        window.location.assign(started.url);
      })}>验证并绑定我的钉钉账号</Button></div>
      {callback && <div className="rounded-lg border p-3 space-y-2"><p>钉钉授权已返回。请确认绑定到当前登录的 PDOS 本人账号。</p><Button disabled={disabled} onClick={() => void work(async () => {
        const original = callback;
        // The server consumes the nonce before exchanging the code. Do not retry
        // this code after an uncertain outcome; read the actual binding instead.
        setCallback(null); sessionStorage.removeItem(bindingStorageKey(principalId));
        try {
          const result = await api<{ binding_id: string; epoch: number; active: boolean }>("v1/personal/dingtalk/bindings/finish", original);
          const current = await refresh();
          if (!result || !current.bindings.some(b => b.binding_id === result.binding_id && b.application_id === original.application_id && b.owner_id === principalId && b.epoch === result.epoch && b.active && result.active)) throw new Error("尚未读回匹配的本人绑定，请重新读取状态。");
          setNotice("账号绑定已完成。");
        } catch (e) { await refresh(); throw e; }
      })}>确认绑定到当前本人</Button></div>}
      <label className="block text-sm">撤绑原因<input className="mt-1 block w-full rounded-lg border p-2" value={reason} maxLength={500} onChange={e => setReason(e.target.value)}/></label>
      <ul className="space-y-2">{reading.bindings.map(row => <li key={row.binding_id} className="rounded-lg border p-3 flex flex-wrap items-center gap-3"><span>{row.owner_id === principalId ? "本人" : `成员 ${row.owner_id}`} · {row.active ? "已绑定" : "已撤销"} · 第 {row.epoch} 版</span>{row.active && <Button variant="outline" disabled={disabled} onClick={() => revoke(row)}>撤销此账号绑定</Button>}</li>)}</ul>
      {reading.has_more_bindings && <p className="subtle">这里只显示最近 100 条绑定；其余记录尚未载入。</p>}
      {reading.can_manage && <details><summary>管理员应用登记</summary><form className="mt-3 space-y-3" onSubmit={e => { e.preventDefault(); void work(async () => {
        await api("v1/dingtalk/application", { ...form, expected_revision: reading.application?.revision ?? 0 });
        await refresh(); setNotice("已保存应用登记；运行时是否可用请以当前状态为准。");
      }); }}>
        <p className="subtle">只登记 KMS 凭据引用及版本。不要在这里填写 Client Secret 或令牌。</p>
        {([ ["corp_id", "企业 CorpId"], ["client_id", "应用 ClientId"], ["robot_code", "机器人 RobotCode"], ["secret_arn", "KMS Secret ARN"], ["secret_version", "KMS 凭据版本"] ] as const).map(([key, label]) => <label key={key} className="block text-sm">{label}<input className="mt-1 block w-full rounded-lg border p-2" required value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}/></label>)}
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.active} disabled={!reading.configured && !form.active} onChange={e => setForm(f => ({ ...f, active: e.target.checked }))}/>启用当前登记</label><Button disabled={disabled || form.active && !reading.configured}>保存应用登记</Button>
      </form></details>}
      <details><summary>将已有回答分享到原群</summary><div className="mt-3 space-y-3"><p className="subtle">只处理本人在该群发起的原运行。默认分享正文与 PDOS 继续链接；客户来源派生内容仅给本地链接。</p>
        <label className="block text-sm">原运行 ID<input className="mt-1 block w-full rounded-lg border p-2" value={runId} onChange={e => { setRunId(e.target.value); setPreview(null); }}/></label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={quotes} disabled={!reading.group_citations_available || disabled} onChange={e => { setQuotes(e.target.checked); setPreview(null); }}/>包括引文面板</label>{!reading.group_citations_available && <p className="subtle">当前协议无法核实全员受众，不能分享引文面板。</p>}
        <Button variant="outline" disabled={disabled || !reading.configured} onClick={() => void work(async () => { const value = await api<unknown>("v1/personal/dingtalk/share/preview", { run_id: runId, include_citations: quotes }); if (active.current) setPreview(parseDingPreview(value, runId, window.location.origin)); })}>预览原群实际分享内容</Button>
        {preview && <div className="rounded-lg border p-3 space-y-3"><p className="text-sm">目标群：{preview.payload.target_id}</p><p className="whitespace-pre-wrap">{preview.payload.text}</p><p className="break-all text-sm">{preview.payload.url}</p>{preview.payload.citations?.map((c, i) => <blockquote className="border-l-2 pl-3" key={i}>{c.title}<p>{c.quote}</p></blockquote>)}{preview.withheld_reason && <p className="subtle">正文已按当前来源边界收起：{preview.withheld_reason}</p>}<Button disabled={disabled} onClick={() => void work(() => submit({ path: "v1/personal/dingtalk/share/confirm", body: { run_id: preview.run_id, include_citations: quotes, preview_digest: preview.preview_digest, request_key: crypto.randomUUID() } }))}>确认将此预览发到原群</Button></div>}
      </div></details>
    </>}
    {pending && <div className="space-y-2"><p>原操作尚未取得匹配回执。不会创建新的分享或撤绑请求。</p><Button disabled={busy} variant="outline" onClick={() => void work(() => submit(pending))}>核对并重试原请求</Button></div>}
    <div className="space-y-3"><Button variant="outline" disabled={busy} onClick={() => void work(async () => { const v = await api<{ items: Receipt[] }>("v1/personal/dingtalk/deliveries"); if (!Array.isArray(v.items)) throw new Error("投递回执尚未核实。"); if (active.current) setReceipts(v.items); })}>读取本人投递回执</Button>
      {receipts && <ul className="space-y-2">{receipts.map(row => <li className="rounded-lg border p-3 space-y-1" key={row.delivery_id}><p>{row.phase} · {stateName[row.state] ?? "状态待核对"} · 发送尝试 {row.attempts}</p>{row.error_code && <p className="subtle">{row.error_code}</p>}{["unknown", "sending"].includes(row.state) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void work(async () => { const next = await api<Receipt>(`v1/personal/dingtalk/deliveries/${row.delivery_id}/reconcile`, {}); if (next.delivery_id !== row.delivery_id) throw new Error("核对结果不属于原投递。"); setReceipts(old => old?.map(r => r.delivery_id === next.delivery_id ? next : r) ?? null); })}>只核对原投递结果</Button>}</li>)}</ul>}
    </div>
  </section>;
}
