"use client";
// D47 supplier commitments for one fixed Build (F25, AT-20). T0: a named person
// records directly; the board shows demand, commitment and actual side by side.
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, ClockCountdown, Handshake } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { MaterialOption, SupplyApi } from "@/lib/build-supply-view";
import { actionNames, actualText, basisNames, blankPromise, canMaintain, checkBoard, closeCommand, createCommand, draftFrom, followUpNames, localZone, quantityText, reopenCommand, reviseCommand, timeText, type CommitmentBoard, type CommitmentCommand, type PromiseDraft } from "@/lib/supply-commitments";

type Props = { api: SupplyApi; product: { id: string; revision: number }; build: { id: string; revision: number; owner_id: string; name: string }; principalId: string; materials: MaterialOption[]; projectOwnerId?: string | null };
type Receipt = { id: string; subject_id: string; subject_type: string; result?: { state?: string } };
type Editing = { id: string; mode: "revise" | "close" | "reopen"; draft: PromiseDraft; note: string };

function PromiseFields({ draft, onChange, materials, withMaterial }: { draft: PromiseDraft; onChange: (draft: PromiseDraft) => void; materials: MaterialOption[]; withMaterial: boolean }) {
  return <div className="grid gap-3 sm:grid-cols-2">
    {withMaterial && <label>固定需求物料<select value={draft.materialId} onChange={event => onChange({ ...draft, materialId: event.target.value })}><option value="">选择物料</option>{materials.map(material => <option key={material.id} value={material.id}>{material.name}</option>)}</select></label>}
    {withMaterial && <label>外部供方标识<input value={draft.supplierRef} maxLength={120} placeholder="照来源原样，如 ACME-01" onChange={event => onChange({ ...draft, supplierRef: event.target.value })}/></label>}
    <label>承诺数量<input inputMode="decimal" value={draft.quantity} placeholder="未知可留空" onChange={event => onChange({ ...draft, quantity: event.target.value })}/></label>
    <label>单位<input value={draft.unit} maxLength={80} placeholder="如 ea" onChange={event => onChange({ ...draft, unit: event.target.value })}/></label>
    <label className="sm:col-span-2">承诺到货时间<input type="datetime-local" value={draft.promisedLocal} onChange={event => onChange({ ...draft, promisedLocal: event.target.value })}/><span className="subtle text-xs">按本机时区 {localZone()} 记录；未给日期可留空，不设检查日。</span></label>
    <label className="sm:col-span-2">供方原话或要点<textarea rows={2} maxLength={4000} value={draft.text} onChange={event => onChange({ ...draft, text: event.target.value })}/></label>
  </div>;
}

export function BuildSupplyCommitments({ api, product, build, principalId, materials, projectOwnerId }: Props) {
  const [board, setBoard] = useState<CommitmentBoard | null>(null), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [draft, setDraft] = useState<PromiseDraft>(blankPromise), [editing, setEditing] = useState<Editing | null>(null);
  const [pending, setPending] = useState<CommitmentCommand | null>(null);
  const alive = useRef(true), lock = useRef(false);
  const names = new Map(materials.map(material => [material.id, material.name]));
  const refresh = useCallback(async () => {
    setLoading(true);
    try { const value = await api<CommitmentBoard>(`v1/products/${product.id}/builds/${build.id}/supply-commitments`); checkBoard(value, build.id); if (alive.current) setBoard(value); }
    finally { if (alive.current) setLoading(false); }
  }, [api, product.id, build.id]);
  useEffect(() => { alive.current = true; void Promise.resolve().then(() => { if (alive.current) return refresh(); }).catch(failure => { if (alive.current) { setBoard(null); setError((failure as Error).message); } }); return () => { alive.current = false; }; }, [refresh]);

  async function send(command: CommitmentCommand, done: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice(""); setPending(command);
    try {
      const receipt = await api<Receipt>("v1/commands", command);
      if (!receipt.id || receipt.subject_type !== "supply_commitment") throw new Error("本次回执尚未确认，请按原请求重试。");
      if (!alive.current) return;
      setPending(null); setEditing(null); setNotice(done);
      if (command.payload.record.action === "create") setDraft(blankPromise());
      try { await refresh(); } catch (failure) { if (alive.current) setError(`已登记；最新结果读取失败，可刷新。${(failure as Error).message}`); }
    } catch (failure) {
      if (!alive.current) return;
      const failed = failure as Error & { status?: number };
      if ([400, 401, 403, 404, 409, 422].includes(failed.status ?? 0)) setPending(null);
      setError(failed.message);
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function attempt(make: () => CommitmentCommand, done: string) { setError(""); try { void send(make(), done); } catch (failure) { setError((failure as Error).message); } }

  const items = board?.commitments ?? [];
  return <section className="panel min-w-0 space-y-4" aria-label="供方承诺与实到">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="flex items-center gap-2 font-semibold"><Handshake aria-hidden size={18}/>供方承诺（声称）与实到</h3><p className="subtle mt-1 text-sm">{board?.kit_rule ?? "承诺不计入库存与齐套；实到以供给快照的到货记录为准。"} 检查日是承诺日的次日，只是内部跟进点。</p></div>
      <Button variant="outline" size="sm" disabled={busy || loading} onClick={() => { setError(""); void refresh().catch(failure => setError((failure as Error).message)); }}><ArrowClockwise aria-hidden/>刷新</Button>
    </header>
    {error && <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-border p-3 text-sm">{notice}</p>}
    {pending && <div className="rounded-lg border border-primary p-3 text-sm"><p>上一次登记的结果尚未确认；原请求与原标识已保留，重试不会重复登记。</p><Button className="mt-2" size="sm" disabled={busy} onClick={() => void send(pending, "已按原请求完成登记。")}>按原请求重试</Button></div>}
    {loading && !board && <p role="status" className="subtle text-sm">正在读取本轮的需求、承诺与实到…</p>}
    {board && <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-sm"><thead><tr className="text-left subtle"><th className="py-2 pr-3 font-medium">物料</th><th className="py-2 pr-3 font-medium">本轮需求</th><th className="py-2 pr-3 font-medium">供方承诺</th><th className="py-2 font-medium">实到（快照）</th></tr></thead><tbody>
      {board.lines.map(line => <tr key={line.item_id} className="border-t border-border align-top"><td className="py-2 pr-3">{(line.material_id && names.get(line.material_id)) ?? line.item_id}</td><td className="py-2 pr-3">{quantityText(line.required_quantity, line.unit)}</td><td className="py-2 pr-3">{line.commitments.length ? `${line.open_commitments} 条跟进中${line.check_due ? ` · ${line.check_due} 条已到检查日` : ""}` : "无"}</td><td className="py-2">到货：{actualText(line.actual.received)}<br/><span className="subtle">库存：{actualText(line.actual.on_hand)}</span></td></tr>)}
      {!board.lines.length && <tr><td colSpan={4} className="py-2 subtle">本轮固定需求暂不可读（{board.demand_status}），不以零代替。</td></tr>}
    </tbody></table></div>}
    {board && <ul className="space-y-3">{items.map(item => {
      const zone = item.body.original_timezone, mine = canMaintain(item, principalId, build, projectOwnerId), open = editing?.id === item.commitment_id ? editing : null;
      return <li key={item.commitment_id} className="rounded-lg border border-border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium [overflow-wrap:anywhere]">{item.body.supplier_ref} · {names.get(item.material_id) ?? "固定物料"} · {quantityText(item.body.quantity, item.body.unit)}</p><span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${item.follow_up.status === "check_due" ? "border-primary text-primary" : "border-border"}`}><ClockCountdown aria-hidden size={14}/>{followUpNames[item.follow_up.status]}</span></div>
        <p className="mt-1 text-sm">承诺 {timeText(item.body.promised_at, zone)} · 检查日 {timeText(item.body.check_at, zone)}（{zone}）</p>
        <p className="mt-1 text-sm whitespace-pre-wrap [overflow-wrap:anywhere]">{item.body.text}</p>
        <p className="subtle mt-1 text-xs">依据：{basisNames[item.body.time_basis]}{item.body.statement ? ` · “${item.body.statement}”` : ""}{item.ai_written ? " · AI 起草" : ""}{item.source_status !== "current" ? " · 来源需重核" : ""}</p>
        {item.body.last_closure && <p className="subtle mt-1 text-xs">关闭：{item.body.last_closure.result}</p>}
        <details className="mt-2 text-xs"><summary className="cursor-pointer subtle">版本记录 {item.history.length} 条</summary><ol className="mt-1 space-y-1">{item.history.map(row => <li key={row.id}>v{row.revision} {actionNames[row.action]} · {timeText(row.promised_at, zone)} · {quantityText(row.quantity, row.unit)}{row.ai_written ? " · AI 起草" : ""}</li>)}</ol></details>
        {mine && !open && <div className="mt-2 flex flex-wrap gap-2">{item.state === "open" ? <><Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing({ id: item.commitment_id, mode: "revise", draft: draftFrom(item), note: "" })}>改期或改量</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing({ id: item.commitment_id, mode: "close", draft: draftFrom(item), note: "" })}>关闭跟进</Button></> : <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing({ id: item.commitment_id, mode: "reopen", draft: draftFrom(item), note: "" })}>重开</Button>}</div>}
        {open && <form className="mt-3 space-y-3" noValidate onSubmit={event => { event.preventDefault(); if (open.mode === "revise") attempt(() => reviseCommand(item, open.draft, product), "已登记新的承诺版本；原版本保留。"); else if (open.mode === "close") attempt(() => closeCommand(item, open.note, open.draft.statement, product), "已关闭内部跟进；不代表到货。"); else attempt(() => reopenCommand(item, open.note, open.draft.statement, product), "已重开跟进。"); }}>
          {open.mode === "revise" && <PromiseFields draft={open.draft} materials={materials} withMaterial={false} onChange={next => setEditing({ ...open, draft: next })}/>}
          {open.mode !== "revise" && <label>{open.mode === "close" ? "关闭原因" : "重开原因"}<input value={open.note} maxLength={4000} onChange={event => setEditing({ ...open, note: event.target.value })}/></label>}
          <label>依据（本人陈述）<input value={open.draft.statement} maxLength={4000} placeholder="例如：供方邮件今天确认改期" onChange={event => setEditing({ ...open, draft: { ...open.draft, statement: event.target.value } })}/></label>
          <div className="flex gap-2"><Button type="submit" size="sm" disabled={busy}>保存</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(null)}>取消</Button></div>
        </form>}
      </li>; })}{!items.length && <li className="subtle text-sm">本轮还没有登记供方承诺。</li>}</ul>}
    {board && <form className="space-y-3 border-t border-border pt-4" noValidate onSubmit={event => { event.preventDefault(); attempt(() => createCommand(draft, build, product), "已登记供方承诺；不计入库存与齐套。"); }}>
      <h4 className="font-medium">登记供方承诺</h4>
      <PromiseFields draft={draft} materials={materials} withMaterial onChange={setDraft}/>
      <label>依据（本人陈述）<input value={draft.statement} maxLength={4000} placeholder="例如：我与供方电话确认" onChange={event => setDraft({ ...draft, statement: event.target.value })}/></label>
      <Button type="submit" disabled={busy || !!pending}>登记承诺</Button>
    </form>}
  </section>;
}
