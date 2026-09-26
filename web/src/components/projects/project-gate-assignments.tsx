"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import type { GateAssignment, NamedSignerPolicy, ProjectGate } from "./project-gate-document-types";

const labels = { product: "产品", engineering: "工程", quality: "质量" } as const;
type Slot = keyof typeof labels;
const slots = Object.keys(labels) as Slot[];
type Options = {
  required_policy: NamedSignerPolicy;
  requirements: Record<Slot, string>; signing_basis: string;
  members: { user_id: string; display_name: string; role: string; slots: Slot[] }[];
};
type Request = { request_id: string; expected_basis: string; replace_round_id: string | null; signers: Partial<Record<Slot, string>>; reason: string };
type History = {
  id: string; round_number: number; status: string; opened_at: string; opened_by_user_id: string;
  supersede_reason: string | null;
  routing_snapshot: { assignment?: GateAssignment };
  signoffs: { slot: string; status: string; signed_by_user_id: string | null; signed_at: string | null; note: string | null }[];
};
const states: Record<string, string> = { open: "办理中", superseded: "已替代", completed: "已结束", approved: "通过", conditional: "有条件通过", rejected: "不通过", pending: "待签核", not_applicable: "不适用" };
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }

async function read(response: Response): Promise<unknown> {
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = isRecord(value) ? value.detail : null;
    throw new RequestError(isRecord(detail) && typeof detail.message === "string" ? detail.message : "签核安排暂不可用", response.status);
  }
  if (!isRecord(value)) throw new Error("未收到有效回执，请核对轮次历史后重试");
  return value;
}

export function ProjectGateAssignments({ gate, canManage, busy: parentBusy, onChanged, handoverRoundId, handoverUserId }: {
  gate: ProjectGate; canManage: boolean; busy: boolean; onChanged: () => void; handoverRoundId?: string; handoverUserId?: string;
}) {
  const [options, setOptions] = useState<Options | null>(null);
  const [signers, setSigners] = useState<Partial<Record<Slot, string>>>({});
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<Request | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [historyTarget, setHistoryTarget] = useState<string | null>(null);
  const [history, setHistory] = useState<History[] | null>(null), [before, setBefore] = useState<number | null>(null);
  const path = `/api/projects/${encodeURIComponent(gate.project_id)}/gates/${encodeURIComponent(gate.id)}`;
  const current = gate.round?.routing_snapshot?.assignment;
  const replacing = gate.round?.status === "open";
  const disabled = busy || parentBusy;
  const policy = options?.required_policy ?? gate.named_signer_policy;
  const required = policy?.required_slots ?? [];
  const complete = required.every(slot => Boolean(signers[slot as Slot]));

  async function loadOptions() {
    setBusy(true); setError("");
    try {
      const data = await read(await fetch(`${path}/assignment-options`, { cache: "no-store" })) as Options;
      if (!isRecord(data.requirements) || !Array.isArray(data.members) || data.signing_basis !== gate.signing_basis) throw new Error("轮次或签核材料已变化，请刷新 Gate 后重新安排");
      setOptions(data);
      setSigners(Object.fromEntries(Object.entries(current?.signers ?? {}).map(([slot, person]) => [slot, person.user_id])));
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!options) return;
    const request = pending ?? { request_id: crypto.randomUUID(), expected_basis: options.signing_basis, replace_round_id: replacing ? gate.round!.id : null, signers, reason: reason.trim() };
    setPending(request); setBusy(true); setError("");
    try {
      const result = await read(await fetch(`${path}/rounds`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) }));
      if (!isRecord(result) || !isRecord(result.round) || !isRecord(result.round.routing_snapshot) || !isRecord(result.round.routing_snapshot.assignment) || result.round.routing_snapshot.assignment.request_id !== request.request_id) throw new Error("结果待核对，请回看历史或重试原请求");
      setPending(null); setOptions(null); onChanged();
    } catch (e) {
      if (e instanceof RequestError && e.status >= 400 && e.status < 500) setPending(null);
      setError(e instanceof Error ? e.message : "结果未知，可使用原请求重试");
    } finally { setBusy(false); }
  }
  async function loadHistory(append = false, roundId?: string) {
    setBusy(true); setError("");
    try {
      const data = await read(await fetch(`${path}/rounds${roundId ? `?round_id=${encodeURIComponent(roundId)}` : append && before ? `?before=${before}` : ""}`, { cache: "no-store" }));
      if (!isRecord(data) || !Array.isArray(data.items) || !(data.next_before === null || typeof data.next_before === "number")) throw new Error("历史回执无效");
      setHistory(previous => append ? [...previous ?? [], ...data.items as History[]] : data.items as History[]);
      setBefore(data.next_before);
      setHistoryTarget(roundId ?? null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <div className="mt-3 space-y-3 rounded-md border p-3">
    <p className="text-sm font-medium">本轮签核安排</p>
    {handoverRoundId && <div className="space-y-2 rounded-md border border-primary/30 p-3 text-sm">
      <p>{gate.round?.id === handoverRoundId && gate.round.status === "open" ? "正在核对移交清单中的原轮次。更换人员会保留旧签名，并要求新轮次全部适用槽位重新签核。" : "移交清单中的原轮次已结束或被替代。下面是当前资料；请先回看原轮次，刷新移交清单后再决定后续办理。"}</p>
      <p className="text-xs">已签署槽位在轮次结束前仍可能被要求重新核对。可先完成本轮，或由项目负责人另开具名轮次；移交本身不代签。</p>
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => void loadHistory(false, handoverRoundId)}>查看移交原轮次</Button>
    </div>}
    <div className="space-y-1 text-xs">{slots.map(slot => <p key={slot}>{labels[slot]}：{gate.round?.signoffs.find(s => s.slot === slot)?.requirement === "not_applicable" ? "不适用" : current?.signers[slot]?.display_name ?? (required.includes(slot) ? "本项目要求指定签核人" : "由具备本槽位权限的人员办理")}{handoverUserId && current?.signers[slot]?.user_id === handoverUserId ? " · 待移交人员" : ""}</p>)}</div>
    {policy?.source && <p className="text-xs text-muted-foreground">固定于创建版 {policy.source.template_id} v{policy.source.template_version}：{required.map(slot => labels[slot as Slot]).join("、")}须具名分派。</p>}
    {current && <p className="text-xs text-muted-foreground">安排依据：{current.reason}</p>}
    <div className="flex flex-wrap gap-2">
      {canManage && gate.is_current && gate.status !== "approved" && !options && <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => void loadOptions()}>{replacing ? "更换签核人并重开轮次" : "安排签核人并开启轮次"}</Button>}
      <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={() => void loadHistory()}>查看轮次历史</Button>
      <Button type="button" variant="ghost" size="sm" disabled={disabled || Boolean(pending)} onClick={onChanged}>刷新 Gate</Button>
    </div>
    {options && <div className="space-y-3 border-t pt-3">
      <p className="text-xs text-muted-foreground">指定人员须仍是本项目成员，并具备相应专业签核权限。标明必选的槽位须指定人员；其他槽位留空沿用原权限办理方式。{replacing && "提交后原轮次停止办理，已有签名留在历史中；新轮次所有适用槽位重新签核。"}</p>
      {slots.filter(slot => options.requirements[slot] !== "not_applicable").map(slot => <label className="block space-y-1 text-sm" key={slot}><span>{labels[slot]}签核人{required.includes(slot) ? "（必选）" : ""}</span><select className="block w-full rounded-md border bg-background p-2" disabled={disabled || Boolean(pending)} value={signers[slot] ?? ""} onChange={e => setSigners(old => { const next = { ...old }; if (e.target.value) next[slot] = e.target.value; else delete next[slot]; return next; })}>
        <option value="">{required.includes(slot) ? "请选择实际签核人" : "保留本槽位原权限办理"}</option>
        {signers[slot] && !options.members.some(p => p.user_id === signers[slot] && p.slots.includes(slot)) && <option value={signers[slot]} disabled>原指定人员已不具备资格，请重新选择</option>}
        {options.members.filter(p => p.slots.includes(slot)).map(p => <option key={p.user_id} value={p.user_id}>{p.display_name} · {p.user_id.slice(0, 8)}</option>)}
      </select>{!options.members.some(p => p.slots.includes(slot)) && <span className="text-xs text-primary">当前没有具备该槽位权限的项目成员，请先补齐人员。</span>}</label>)}
      <label className="block space-y-1 text-sm"><span>{replacing ? "更换及重新签核原因" : "签核安排依据"}</span><textarea className="block min-h-20 w-full rounded-md border bg-background p-2" maxLength={2000} disabled={disabled || Boolean(pending)} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <p className="text-xs">将安排：{slots.filter(slot => options.requirements[slot] !== "not_applicable").map(slot => `${labels[slot]}—${signers[slot] ? options.members.find(p => p.user_id === signers[slot])?.display_name ?? "须重新选择" : "原权限办理"}`).join("；")}。</p>
      {pending && <p className="break-all text-xs">原请求 {pending.request_id}：结果待核对，重试将使用相同人员及原因。</p>}
      <Button type="button" disabled={disabled || !reason.trim() || !complete} onClick={() => void save()}>{pending ? "重试原分派请求" : replacing ? "确认安排并重新开启签核" : "确认安排并开启签核"}</Button>
      {!pending && <Button type="button" variant="ghost" disabled={disabled} onClick={() => setOptions(null)}>取消编辑</Button>}
    </div>}
    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    {history && <div className="space-y-2 border-t pt-3"><p className="text-xs">轮次保留原指定人员及签名；人员名称为当时快照。未具名的历史签名显示账号编号。</p>{historyTarget && <p className="text-xs">正在查看移交原轮次，实际是否仍可办理以上方当前资料为准。</p>}{history.length === 0 && <p className="text-sm">{historyTarget ? "未找到指定原轮次，请核对移交记录。" : "尚无签核轮次。"}</p>}{history.map(round => <details className="rounded-md border p-2" key={round.id}><summary className="cursor-pointer text-sm">第 {round.round_number} 轮 · {states[round.status] ?? round.status} · {new Date(round.opened_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</summary><div className="mt-2 space-y-1 text-xs">
      {round.routing_snapshot.assignment?.required_policy?.source && <p>创建版要求：{round.routing_snapshot.assignment.required_policy.source.template_id} v{round.routing_snapshot.assignment.required_policy.source.template_version}，{round.routing_snapshot.assignment.required_policy.required_slots?.map(slot => labels[slot as Slot]).join("、")}须具名。</p>}
      {round.routing_snapshot.assignment && <p>安排依据：{round.routing_snapshot.assignment.reason}</p>}
      {round.supersede_reason && <p>替代原因：{round.supersede_reason}</p>}
      {round.signoffs.map(signoff => { const person = round.routing_snapshot.assignment?.signers[signoff.slot]; return <div className="border-t pt-1" key={signoff.slot}><p>{labels[signoff.slot as Slot]}：{person?.display_name ?? "原权限办理"}{handoverUserId && person?.user_id === handoverUserId ? " · 移交清单原人员" : ""} · {states[signoff.status] ?? signoff.status}</p>{signoff.signed_by_user_id && <p>签署人：{person?.user_id === signoff.signed_by_user_id ? person.display_name : signoff.signed_by_user_id} · {signoff.signed_at ? new Date(signoff.signed_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" }) : ""}</p>}{signoff.note && <p className="whitespace-pre-wrap">意见：{signoff.note}</p>}</div>; })}
    </div></details>)}{before && <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => void loadHistory(true)}>更早轮次</Button>}</div>}
  </div>;
}
