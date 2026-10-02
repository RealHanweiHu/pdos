"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, field, type Row } from "@/components/quality/fmea-sources";
import { request, ProductRequestError, type Evidence } from "./product-work-api";
import { FactEditor, emptyFact, type Fact } from "./market-segments";

const states: Record<string, string> = { progress: "落实进展 / 待核对", verified: "所选范围已核对", not_implemented: "所选范围未落实", withdrawn: "撤回上次结果" };
const workStates: Record<string, string> = { ready: "待开始", in_progress: "办理中", submitted: "待接收", completed: "已完成", cancelled: "已取消", pending_assignment: "待分派" };
export function ProductMatrixOutcomes({ base, dispositionId }: { base: string; dispositionId: string }) {
  return <MatrixOutcomesPanel key={JSON.stringify([base, dispositionId])} base={base} dispositionId={dispositionId}/>;
}

function MatrixOutcomesPanel({ base, dispositionId }: { base: string; dispositionId: string }) {
  const [data, setData] = useState<Row | null>(null), [evidence, setEvidence] = useState<Evidence[]>([]);
  const [checked, setChecked] = useState<string[]>([]), [chosen, setChosen] = useState<string[]>([]), [state, setState] = useState("progress"), [reason, setReason] = useState("");
  const [verification, setVerification] = useState<Fact>(() => emptyFact());
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const attempt = useRef<{ key: string; body: Row } | null>(null);
  const running = useRef(false);
  const [pending, setPending] = useState(false);
  async function read(before?: number) { const value = await request<Row>(`${base}/matrix-outcomes`, "POST", { disposition_id: dispositionId, before_version: before ?? null }); setData(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function load() { const [value, sources] = await Promise.all([request<Row>(`${base}/matrix-outcomes`, "POST", { disposition_id: dispositionId, before_version: null }), request<{ items: Evidence[] }>(`${base}/evidence`)]); setData(value); setEvidence(sources.items); }
  function resetForm() { setReason(""); setVerification(emptyFact()); setChecked([]); setChosen([]); setState("progress"); }
  async function act(work: () => Promise<void>) {
    if (running.current) return;
    running.current = true; setBusy(true); setError("");
    try { await work(); } catch (failure) {
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) { setData(null); setEvidence([]); setNotice(""); resetForm(); attempt.current = null; setPending(false); }
      setError(failure instanceof Error ? failure.message : "结果记录暂不可用");
    } finally { running.current = false; setBusy(false); }
  }
  async function send() {
    if (!attempt.current) return;
    let saved: Row;
    try { saved = await request<Row>(`${base}/matrix-outcome-save`, "POST", attempt.current.body); }
    catch (failure) {
      if (!(failure instanceof ProductRequestError) || failure.status >= 500) { setPending(true); throw new Error("保存结果尚未确认。请按原请求重试核对回执，避免重复登记。"); }
      setPending(false); throw failure;
    }
    attempt.current = null; setPending(false); resetForm();
    setNotice("已保存结果版本，回执：" + text(saved.id) + "。未选产品保持未核对，原发布流程保持。");
    try { await read(); } catch (failure) {
      if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) throw failure;
      setError("结果已保存，历史暂未刷新。请刷新实际版本与结果，无需再次保存。");
    }
  }
  const source = obj(data?.source), products = rows(source.products), options = rows(source.options), work = obj(source.work);
  const name = (id: unknown) => text(products.find(p => p.id === id)?.name) || text(id);
  const toggle = (values: string[], id: string, selected: boolean) => selected ? [...values, id] : values.filter(v => v !== id);
  async function save() {
    const body = { disposition_id: dispositionId, expected_version: data?.version, expected_source_digest: source.digest, state, checked_product_ids: checked, versions: options.filter(option => chosen.includes(text(option.ref_id))).map(option => ({ product_id: option.product_id, kind: option.kind, ref_id: option.ref_id })), reason, verification };
    if (pending) return;
    const key = JSON.stringify(body); if (attempt.current?.key !== key) attempt.current = { key, body: { ...body, request_id: crypto.randomUUID() } };
    await send();
  }
  return <details className="space-y-3 rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}><summary className="cursor-pointer text-sm font-medium">实际落实、发布版本与核对结果</summary><div className="space-y-3 text-sm"><p>关联实际发布版本与跟进工作，记录本次明确核对的产品。这里确认的是所选处置范围的落实依据；工程复用批准、销量与降本效果仍以原业务验证为准。</p>{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}{pending && <Button variant="outline" disabled={busy} onClick={() => void act(send)}>按原请求重试核对结果</Button>}<Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新实际版本与结果</Button>
    {source.work != null && <div className="rounded-md bg-muted/30 p-3"><p>原跟进工作：{text(work.title)} · {workStates[text(work.state)] ?? text(work.state)}</p><p className="whitespace-pre-wrap">完成判据：{text(work.completion_criteria)}</p>{work.result_note != null && <p className="whitespace-pre-wrap">当前结果：{text(work.result_note)}</p>}{work.accepted_at != null && <p>实际接收：{new Date(text(work.accepted_at)).toLocaleString()}</p>}<p className="text-xs text-muted-foreground">尚未完成接收的工作只能登记进展，不能确认落实。</p></div>}
    {Array.isArray(source.work_warnings) && source.work_warnings.map((warning, index) => <p key={index} className="text-primary">{String(warning)}</p>)}
    {data?.can_record === true && <form className="space-y-3 rounded-md bg-muted/20 p-3" onSubmit={event => { event.preventDefault(); void act(save); }}><fieldset disabled={busy || pending} className="space-y-3"><h6 className="font-medium">登记本次实际结果</h6><div><p>本次核对产品（未选产品保留未核对）</p>{products.map(product => <label key={text(product.id)} className="mr-3 inline-flex items-center gap-1"><input type="checkbox" checked={checked.includes(text(product.id))} onChange={event => { const id = text(product.id); setChecked(toggle(checked, id, event.target.checked)); if (!event.target.checked) setChosen(old => old.filter(ref => options.find(v => v.ref_id === ref)?.product_id !== id)); }}/>{text(product.code)} · {text(product.name)}</label>)}</div><div className="space-y-2"><p>选择实际发布版本</p>{options.filter(option => checked.includes(text(option.product_id))).map(option => <label key={text(option.ref_id)} className="block rounded-md border p-2"><span className="flex items-start gap-2"><input type="checkbox" checked={chosen.includes(text(option.ref_id))} onChange={event => setChosen(toggle(chosen, text(option.ref_id), event.target.checked))}/>{text(option.label)}</span><span className="block text-xs text-muted-foreground">{option.later_than_disposition ? "处置后发布，可核对是否落实本次要求" : "既有发布依据，不能据此声称是处置后的新修订"}</span>{Array.isArray(option.warnings) && option.warnings.map((warning, index) => <span key={index} className="block text-xs text-primary">{String(warning)}</span>)}<a className="inline-flex min-h-9 items-center text-xs underline" href={text(option.href)}>打开原发布记录</a><details className="text-xs"><summary className="cursor-pointer">核对完整原版本</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(option.snapshot, null, 2)}</pre></details></label>)}{checked.some(id => !options.some(option => option.product_id === id)) && <p className="text-primary">部分所选产品当前没有可关联的发布版本，保持缺项。</p>}</div><label className="block">本次结果<select className={field} value={state} onChange={event => setState(event.target.value)}>{Object.entries(states).filter(([key]) => key !== "withdrawn" || Number(data.version) > 0).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="block">核对范围、落实说明及限制<textarea required className={field} maxLength={2048} value={reason} onChange={event => setReason(event.target.value)}/></label><FactEditor label="实际验证依据与原文位置说明" value={verification} evidence={evidence} onChange={setVerification}/>{state === "verified" && verification.fact_kind === "hypothesis" && <p className="text-destructive">确认落实需要观察或推导依据，不能只填写假设。</p>}<label className="flex items-start gap-2"><input required type="checkbox" key={text(source.digest)}/>已核对所选产品、发布时点、实际工作和证据；未选范围保持未核对。</label><Button disabled={!checked.length}>保存新的结果版本</Button></fieldset></form>}
    {data && data.can_record !== true && <p className="text-muted-foreground">当前仅回查原结果。登记须从未撤回的最新处置并具备相应管理权限办理。</p>}
    {rows(data?.items).map(value => <article className="space-y-2 border-t pt-3" key={text(value.id)}><h6 className="font-medium">结果 v{text(value.version)} · {states[text(value.state)]} {value.version === data?.version ? "· 最新结果" : "· 历史结果"}</h6><p className="text-xs text-muted-foreground">{text(value.actor_name)} · {new Date(text(value.created_at)).toLocaleString()}</p><p>已核对范围：{Array.isArray(value.checked_product_ids) ? value.checked_product_ids.map(name).join("；") : ""}</p>{Array.isArray(value.unchecked_product_ids) && value.unchecked_product_ids.length > 0 && <p className="text-primary">未核对：{value.unchecked_product_ids.map(name).join("；")}</p>}<p className="whitespace-pre-wrap">{text(value.reason)}</p><p className="whitespace-pre-wrap">依据说明：{text(obj(value.verification).text)}</p>{value.sources_current !== true && <p className="text-primary">当前处置、工作或发布依据已变化，本结果保留当时范围，请重核。</p>}{Array.isArray(value.evidence_warnings) && value.evidence_warnings.map((warning, index) => <p key={index} className="text-primary">{String(warning)}</p>)}{rows(value.versions).map(version => { const original = obj(version.snapshot); return <div key={`${text(version.product_id)}:${text(version.kind)}`}><p>{text(original.label)}</p><a className="inline-flex min-h-9 items-center text-xs underline" href={text(original.href)}>打开当前原业务</a><details><summary className="cursor-pointer text-xs">保存时的完整版本</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(original.snapshot, null, 2)}</pre></details></div>; })}<details><summary className="cursor-pointer text-xs">原工作、处置和证据记录</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify({ verification: value.verification, source: value.source_snapshot }, null, 2)}</pre></details></article>)}
    {data?.next_before_version != null && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => read(Number(data.next_before_version)))}>更早结果</Button>}
  </div></details>;
}
