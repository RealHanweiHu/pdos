"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Usage = { input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_creation_tokens: number };
type Call = { call_id: string; run_id: string; revision: number; status: string; held_tokens: number; charged_tokens: number | null; usage: Usage | null; request_id: string | null; provider_version: string | null; protocol: string | null; budget_exceeded: boolean; history: { actor_id: string; resolution: string; evidence_ref: string; occurred_at: string }[] };
type Review = { before: Call; after: { resolution: string; usage: Usage | null; charged_tokens: number | null; held_tokens: number; reason_code: string; evidence_ref: string }; effect: string };
type Prepared = { command: Record<string, unknown>; review: Review; expires_at: string };

export function ModelAccounting({ product, principalId, api, onSaved }: { product: { id: string; revision: number }; principalId: string; api: Api; onSaved: () => Promise<void> }) {
  const [calls, setCalls] = useState<Call[]>([]);
  const [selected, setSelected] = useState("");
  const [resolution, setResolution] = useState("unknown");
  const [values, setValues] = useState(["", "", "", ""]);
  const [requestId, setRequestId] = useState("");
  const [evidence, setEvidence] = useState("");
  const [review, setReview] = useState<Prepared | null>(null);
  const [pending, setPending] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const storageKey = `pdos-next:accounting:${principalId}:${product.id}`;
  const call = calls.find((item) => item.call_id === selected);
  const load = useCallback(async () => {
    const result = await api<{ items: Call[] }>(`v1/products/${product.id}/model-calls`);
    setCalls(result.items);
    setSelected((current) => result.items.some((item) => item.call_id === current) ? current : result.items[0]?.call_id ?? "");
  }, [api, product.id]);
  useEffect(() => { let active = true; void Promise.resolve().then(async () => {
    if (!active) return;
    try { const saved = localStorage.getItem(storageKey); if (saved) setPending(JSON.parse(saved)); await load(); }
    catch (e) { if (active) setError((e as Error).message); }
  }); return () => { active = false; }; }, [load, storageKey]);
  useEffect(() => { if (review && !dialog.current?.open) dialog.current?.showModal(); }, [review]);
  async function submit(command: Record<string, unknown>) {
    setBusy(true); setError(""); setPending(command); localStorage.setItem(storageKey, JSON.stringify(command));
    try { await api("v1/commands", command); setPending(null); localStorage.removeItem(storageKey); setReview(null); dialog.current?.close(); setNotice("对账已记录，原模型结果和运行状态保留。"); await load(); await onSaved(); }
    catch (e) { const failure = e as Error & { status?: number }; setError(failure.message); if (failure.status && [403, 409, 422].includes(failure.status)) { setPending(null); localStorage.removeItem(storageKey); setReview(null); dialog.current?.close(); } } finally { setBusy(false); }
  }
  if (!calls.length && !pending) return <section className="panel mb-6"><h2 className="font-semibold">调用与费用核对</h2><p className="subtle mt-3">当前没有已登记的模型调用。可在模型设置中核对配置与权限。</p>{error && <p role="alert" className="mt-3 text-destructive">{error}</p>}</section>;
  return <section className="panel mb-6">
    <h2 className="font-semibold">调用与费用核对</h2><p className="subtle my-3">费用未知时继续保留预留用量。只有拿到原调用的真实用量凭证后，才能记录已知费用；对账不会重发模型请求。</p>
    {error && <p role="alert" className="my-3 text-destructive">{error}</p>}{notice && <p role="status" className="my-3">{notice}</p>}
    {pending && <div className="mb-4 rounded-lg border border-border p-3"><p className="subtle mb-2">提交结果待核对，原请求已保存在本机。</p><Button disabled={busy} onClick={() => void submit(pending)}>核对原对账请求</Button></div>}
    <label>原调用<select value={selected} disabled={busy || !!pending} onChange={(e) => { setSelected(e.target.value); setValues(["", "", "", ""]); setRequestId(""); setEvidence(""); }}>{calls.map((item) => <option key={item.call_id} value={item.call_id}>{item.provider_version ?? "已登记调用"} · {item.status === "unknown" ? "费用待对账" : item.status === "reserved" ? "用量仍预留" : "费用已登记"} · {item.call_id.slice(0, 8)}</option>)}</select></label>
    {call && <><p className="subtle my-3">预留：{call.held_tokens} · 已登记：{call.charged_tokens ?? "未知"}{call.budget_exceeded && " · 已超预算，后续自动执行保持停止"}</p>
      <form onSubmit={(event) => { event.preventDefault(); if (!call) return; void (async () => { setBusy(true); setError(""); try {
        const payload = { call_id: call.call_id, expected_revision: call.revision, resolution, reason_code: resolution === "known" ? "provider_usage_verified" : "provider_usage_unavailable", evidence_ref: evidence, ...(requestId ? { request_id: requestId } : {}), ...(resolution === "known" ? { usage: { input_tokens: Number(values[0]), output_tokens: Number(values[1]), cache_read_tokens: Number(values[2] || 0), cache_creation_tokens: Number(values[3] || 0) } } : {}) };
        setReview(await api<Prepared>("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "ai.model_call.reconcile", product_id: product.id, expected_revision: product.revision, source_read_set: [], payload }));
      } catch (e) { setError((e as Error).message); } finally { setBusy(false); } })(); }}>
        <label>本次核对结果<select value={resolution} disabled={busy || !!pending} onChange={(e) => setResolution(e.target.value)}><option value="unknown">凭证不足，费用仍未知</option><option value="known">凭证已核对，登记已知用量</option></select></label>
        {resolution === "known" && <div className="grid gap-x-4 sm:grid-cols-2">{["输入用量（含缓存）", "输出用量", "其中缓存读取", "其中缓存创建"].map((label, index) => <label key={label}>{label}<input type="number" min="0" step="1" max="2147483647" required={index < 2} value={values[index]} disabled={busy || !!pending} onChange={(e) => setValues(values.map((value, i) => i === index ? e.target.value : value))} /></label>)}</div>}
        <label>服务方原调用编号（如已取得）<input value={requestId} maxLength={200} pattern="[A-Za-z0-9:_.-]+" disabled={busy || !!pending} onChange={(e) => setRequestId(e.target.value)} /></label>
        <label>已核对凭证编号<input required minLength={3} maxLength={200} pattern="[A-Za-z0-9][A-Za-z0-9:_.-]+" value={evidence} placeholder="例如 provider-statement-001" disabled={busy || !!pending} onChange={(e) => setEvidence(e.target.value)} /></label><p className="subtle mb-3">使用凭证编号定位已核对记录；这里无需粘贴业务资料或密钥。</p>
        <Button disabled={busy || !!pending}>查看对账变更</Button>
      </form>
      {!!call.history.length && <details className="mt-4"><summary>已登记的核对历史</summary>{call.history.map((item, index) => <p className="subtle mt-2 break-all" key={index}>{new Date(item.occurred_at).toLocaleString()} · {item.resolution === "known" ? "已知费用" : "仍未知"} · {item.evidence_ref}</p>)}</details>}
    </>}
    <dialog ref={dialog} className="w-[min(40rem,calc(100vw-2rem))] rounded-lg border border-border bg-background p-5 text-foreground backdrop:bg-black/40" onCancel={(event) => { if (busy || pending) event.preventDefault(); else setReview(null); }}>
      {review && <><h3 className="text-lg font-semibold">确认原调用的费用变更</h3><p className="subtle mt-3">{review.review.effect}</p><dl className="my-4 grid grid-cols-2 gap-2"><dt>预留用量</dt><dd>{review.review.before.held_tokens} → {review.review.after.held_tokens}</dd><dt>已登记用量</dt><dd>{review.review.before.charged_tokens ?? "未知"} → {review.review.after.charged_tokens ?? "未知"}</dd><dt>凭证</dt><dd className="break-all">{review.review.after.evidence_ref}</dd></dl>{review.review.after.usage && <p className="subtle mb-4">输入 {review.review.after.usage.input_tokens}；输出 {review.review.after.usage.output_tokens}；缓存读取 {review.review.after.usage.cache_read_tokens}；缓存创建 {review.review.after.usage.cache_creation_tokens}。</p>}<div className="flex flex-wrap gap-2"><Button disabled={busy || !!pending} onClick={() => void submit(review.command)}>确认并记录对账</Button><Button variant="outline" disabled={busy || !!pending} onClick={() => { dialog.current?.close(); setReview(null); }}>返回修改</Button>{pending && <Button disabled={busy} onClick={() => void submit(pending)}>核对原请求</Button>}</div></>}
    </dialog>
  </section>;
}
