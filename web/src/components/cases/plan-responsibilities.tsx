"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "./case-requirements";

type Outcome = "confirmed" | "changes_requested" | "withdrawn";
type Receipt = { id: string; node_key: string; slot: "owner" | "receiver"; outcome: Outcome; reason: string; created_at: string; sequence: number };
type Assignment = { node_key: string; title: string; slot: "owner" | "receiver"; display_name: string; eligible: boolean; mine: boolean; response: Receipt | null };
type State = { candidate_digest: string; version: number; assignments: Assignment[]; all_confirmed: boolean; is_latest: boolean; source_is_current: boolean; template_is_current: boolean; ready_for_plan_review: boolean; current_missing: { node_key: string; reason: string }[]; history?: Receipt[]; has_more_history?: boolean };
const outcomeLabel: Record<Outcome, string> = { confirmed: "已确认", changes_requested: "请求调整", withdrawn: "已撤回确认" };
const slotLabel = { owner: "负责人", receiver: "接收人" };
const keyOf = (item: { node_key: string; slot: string }) => JSON.stringify([item.node_key, item.slot]);

export function PlanResponsibilities({ candidateId }: { candidateId: string }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const stable = useRef({ body: "", id: "" });
  const path = `initial-plans/${candidateId}/responsibilities`;
  async function load() {
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await caseLinkRequest(path) as State;
      setState(result);
      setSelected(result.assignments.filter((item) => item.mine && item.eligible).map(keyOf));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "责任确认记录暂不可用"); }
    finally { setBusy(false); }
  }
  const chosen = state?.assignments.filter((item) => selected.includes(keyOf(item)) && item.mine && item.eligible) ?? [];
  const current = state?.is_latest && state.source_is_current && state.template_is_current;
  async function respond(outcome: Outcome) {
    if (!state || !chosen.length || !reason.trim()) return;
    setBusy(true); setError(null); setNotice(null);
    const body = { candidate_digest: state.candidate_digest, targets: chosen.map((item) => ({ node_key: item.node_key, slot: item.slot, previous_response_id: item.response?.id ?? null })), outcome, reason: reason.trim() };
    const serialized = JSON.stringify(body);
    if (stable.current.body !== serialized) stable.current = { body: serialized, id: crypto.randomUUID() };
    try {
      const updated = await caseLinkRequest(path, { ...body, request_id: stable.current.id }) as State;
      setState(updated); setReason(""); setSelected([]);
      setNotice(`已保存 ${chosen.length} 项职责答复：${outcomeLabel[outcome]}。`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "答复未保存，请刷新后重试"); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 border-t pt-3">
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void load(); }}>{open ? "收起责任确认" : "计划责任确认"}</Button>
    {open && <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>刷新答复</Button>
      {state && <>
        <p className="text-sm">候选版本 {state.version} · {state.all_confirmed ? "所有职责已确认" : "职责待确认"} · {state.ready_for_plan_review ? "可进入计划审阅" : "仍有审阅准备事项"}</p>
        <p className="text-xs text-muted-foreground">请结合本候选的任务、交付内容、完成判据和投入依据确认本人职责。新修订需要重新确认；正式应用还需完成容量检查、计划接受及项目执行批准。</p>
        {!current && <p className="text-sm text-destructive">候选、来源或模板已有变化，请在新的候选版本确认。此处仍可留下调整意见或撤回原确认。</p>}
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setSelected(state.assignments.filter((item) => item.mine && item.eligible).map(keyOf))}>选择本人全部职责</Button>
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSelected(state.assignments.filter((item) => item.mine && item.eligible && item.response?.outcome === "confirmed").map(keyOf))}>仅选择本人已确认项</Button>
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSelected([])}>清空选择</Button>
        </div>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">选择</th><th className="p-2">任务 / 职责</th><th className="p-2">人员</th><th className="p-2">当前答复</th></tr></thead><tbody>
          {state.assignments.map((item) => <tr className="border-b align-top" key={keyOf(item)}>
            <td className="p-2"><input type="checkbox" aria-label={`选择${item.title}的${slotLabel[item.slot]}职责`} disabled={busy || !item.mine || !item.eligible} checked={selected.includes(keyOf(item))} onChange={(event) => setSelected(event.target.checked ? [...selected, keyOf(item)] : selected.filter((key) => key !== keyOf(item)))} /></td>
            <td className="p-2">{item.title}<div className="text-xs text-muted-foreground">{item.node_key} · {slotLabel[item.slot]}</div></td>
            <td className="p-2">{item.display_name}{item.mine ? "（本人）" : ""}{!item.eligible && <div className="text-xs text-destructive">需补充有效责任人</div>}</td>
            <td className="p-2">{item.response ? <>{outcomeLabel[item.response.outcome]}<p className="whitespace-pre-wrap text-xs text-muted-foreground">{item.response.reason}</p><time className="text-xs">{new Date(item.response.created_at).toLocaleString()}</time></> : "待答复"}</td>
          </tr>)}
        </tbody></table></div>
        <label className="block text-sm">答复说明（应用于所选 {chosen.length} 项）<textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" maxLength={2048} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="填写承担依据，或说明需要调整的资源、输入、交付范围等。" /></label>
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" disabled={busy || !chosen.length || !reason.trim() || !current} onClick={() => void respond("confirmed")}>确认所选职责</Button>
          <Button type="button" size="sm" variant="outline" disabled={busy || !chosen.length || !reason.trim()} onClick={() => void respond("changes_requested")}>请求调整</Button>
          <Button type="button" size="sm" variant="outline" disabled={busy || !chosen.length || !reason.trim() || chosen.some((item) => item.response?.outcome !== "confirmed")} onClick={() => void respond("withdrawn")}>撤回所选确认</Button>
        </div>
        {!!state.current_missing.length && <details><summary className="cursor-pointer text-sm">计划准备缺项（{state.current_missing.length}）</summary><ul className="list-disc space-y-1 pl-5 text-xs">{state.current_missing.map((item, index) => <li key={index}>{item.node_key}：{item.reason}</li>)}</ul></details>}
        {state.history ? <details><summary className="cursor-pointer text-sm">答复历史{state.has_more_history ? "（最近 200 条）" : ""}</summary><ol className="space-y-2 text-xs">{state.history.map((receipt) => <li className="border-b py-2" key={receipt.id}>#{receipt.sequence} · {receipt.node_key} / {slotLabel[receipt.slot]} · {outcomeLabel[receipt.outcome]} · {new Date(receipt.created_at).toLocaleString()}<p className="whitespace-pre-wrap">{receipt.reason}</p></li>)}</ol></details> : <p className="text-xs text-muted-foreground">已更新当前答复；刷新可查看完整的最近历史。</p>}
      </>}
    </div>}
  </section>;
}
