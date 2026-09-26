"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Node = { id: string; title: string; kind: string; calendar_version_id: string };
type Policy = { id: string; version: number; authority_basis: string; four_eyes: boolean };
type Side = { project_id: string; project_name: string; baseline_id: string | null; baseline_version: number | null; policy: Policy | null; approver: { id: string; display_name: string } | null };
type Endpoint = Side & { nodes: Node[]; payload_digest: string; ready: boolean };
type Decision = { id: string; project_id: string; action: string; reason: string; created_at: string };
type Proposal = { access_mode: "both_projects" | "proposal_only"; operation: "add" | "remove" | "replace"; destination_application_id: string | null; can_request_removal: boolean; can_apply: boolean; current_relation_application_id: string | null; application: { id: string; created_at: string; reason: string; replaces_application_id: string | null } | null; id: string; payload_digest: string; reason: string; relation: string; lag: string; lag_unit: string; is_current: boolean; can_decide: boolean; can_approve: boolean; can_withdraw: boolean; status: string; decisions: Decision[]; snapshot: { previous_relation?: { application_id: string; relation: string; lag: string; lag_unit: string; predecessor: Side & { node: Node }; successor: Side & { node: Node } }; predecessor: Side & { node: Node }; successor: Side & { node: Node } } };
type State = { endpoint: Endpoint; items: Proposal[]; has_more: boolean; can_prepare: boolean };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const relations: Record<string, string> = { fs: "前序完成 → 后序开始", ss: "前序开始 → 后序开始", ff: "前序完成 → 后序完成", sf: "前序开始 → 后序完成" };
const labels: Record<string, string> = { approve: "已批准", reject: "已拒绝", withdraw: "已撤回" };
const statusLabels: Record<string, string> = { removed: "已按双方批准解除依赖", applied: "已应用到执行依赖", superseded: "已由后续批准关系替换", pending: "等待双方确认", closed: "已结束", approved_pending_application: "双方已批准，等待独立应用" };

export function ProjectCrossDependencies({ projectId, focusProposalId, onChanged }: { projectId: string; focusProposalId?: string; onChanged?: () => void }) {
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [otherId, setOtherId] = useState(""); const [other, setOther] = useState<Endpoint | null>(null);
  const [ownNode, setOwnNode] = useState(""); const [otherNode, setOtherNode] = useState("");
  const [transferTarget, setTransferTarget] = useState<Proposal | null>(null);
  const [direction, setDirection] = useState("incoming"); const [relation, setRelation] = useState("fs"); const [lag, setLag] = useState("0"); const [unit, setUnit] = useState("working_hours"); const [reason, setReason] = useState("");
  const [read, setRead] = useState<Record<string, boolean>>({}); const [reasons, setReasons] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>()); const path = `projects/${projectId}/execution/cross-project-dependencies`;
  useEffect(() => {
    if (!focusProposalId) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setOpen(true); setBusy(true); setError(null);
      try { const value = await caseLinkRequest<State>(`projects/${projectId}/execution/cross-project-dependencies/${focusProposalId}`); if (active) setData(value); }
      catch (failure) { if (active) setError(failure instanceof Error ? failure.message : "待确认申请读取失败"); }
      finally { if (active) setBusy(false); }
    });
    return () => { active = false; };
  }, [projectId, focusProposalId]);
  async function load() {
    const value = await caseLinkRequest<State>(focusProposalId ? `${path}/${focusProposalId}` : path); setData(value); setRead({});
    if (otherId) setOther((await caseLinkRequest<State>(`projects/${otherId}/execution/cross-project-dependencies`)).endpoint);
  }
  async function refresh() {
    setBusy(true); setError(null); setOther(null);
    try { await load(); const list = await caseLinkRequest<{ items: { id: string; name: string }[] }>("projects"); setProjects(list.items.filter((p) => p.id !== projectId)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "跨项目依赖读取失败"); }
    finally { setBusy(false); }
  }
  async function chooseProject(id: string) {
    setOtherId(id); setOther(null); setOtherNode(""); setError(null);
    if (!id) return;
    setBusy(true);
    try { setOther((await caseLinkRequest<State>(`projects/${id}/execution/cross-project-dependencies`)).endpoint); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "对方计划读取失败"); }
    finally { setBusy(false); }
  }
  async function send(endpoint: string, body: object, message: string) {
    const key = JSON.stringify({ endpoint, body }); let id = ids.current.get(key); if (!id) { id = crypto.randomUUID(); ids.current.set(key, id); }
    setBusy(true); setError(null); setNotice(null);
    try { await caseLinkRequest(endpoint, { ...body, request_id: id }); await load(); setNotice(message); onChanged?.(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "跨项目办理未完成"); }
    finally { setBusy(false); }
  }
  async function requestRemoval(item: Proposal) {
    if (!item.application || busy) return;
    setBusy(true); setError(null);
    try {
      const left = (await caseLinkRequest<State>(`projects/${item.snapshot.predecessor.project_id}/execution/cross-project-dependencies`)).endpoint;
      const right = (await caseLinkRequest<State>(`projects/${item.snapshot.successor.project_id}/execution/cross-project-dependencies`)).endpoint;
      await send(path, { operation: "remove", target_application_id: item.application.id,
        predecessor_project_id: left.project_id, successor_project_id: right.project_id,
        predecessor_node_id: item.snapshot.predecessor.node.id, successor_node_id: item.snapshot.successor.node.id,
        predecessor_digest: left.payload_digest, successor_digest: right.payload_digest,
        relation: item.relation, lag: item.lag, lag_unit: item.lag_unit, reason: reasons[item.id] }, "解除申请已保存，待双方批准并独立应用后生效。");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "解除申请未完成"); }
    finally { setBusy(false); }
  }
  async function beginTransfer(item: Proposal) {
    setTransferTarget(item); setReason("");
    const ownIsPredecessor = item.snapshot.predecessor.project_id === projectId;
    setDirection(ownIsPredecessor ? "outgoing" : "incoming"); setRelation(item.relation); setLag(item.lag); setUnit(item.lag_unit);
    setOwnNode((ownIsPredecessor ? item.snapshot.predecessor : item.snapshot.successor).node.id);
    await chooseProject((ownIsPredecessor ? item.snapshot.successor : item.snapshot.predecessor).project_id);
    setOtherNode((ownIsPredecessor ? item.snapshot.successor : item.snapshot.predecessor).node.id);
  }
  function prepare() {
    if (!data || !other || busy) return;
    const predecessor = direction === "incoming" ? other : data.endpoint;
    const successor = direction === "incoming" ? data.endpoint : other;
    void send(path, { operation: transferTarget ? "replace" : "add", target_application_id: transferTarget?.application?.id ?? null, predecessor_project_id: predecessor.project_id, successor_project_id: successor.project_id,
      predecessor_node_id: direction === "incoming" ? otherNode : ownNode, successor_node_id: direction === "incoming" ? ownNode : otherNode,
      predecessor_digest: predecessor.payload_digest, successor_digest: successor.payload_digest, relation, lag, lag_unit: unit, reason }, "申请已保存，等待双方具名确认。");
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起跨项目依赖" : "跨项目依赖申请与确认"}</Button>
    {open && <>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-xs text-muted-foreground">双方确认同一组节点、依赖条件与基线版本。批准后由项目管理人员独立应用，届时复核双方版本与整体依赖关系。申请和应用需具备两侧项目权限；这份申请的具名批准人可凭本侧项目权限确认本侧决定。</p>
      {data && <p className="text-xs">本项目基线 {data.endpoint.baseline_version ? `v${data.endpoint.baseline_version}` : "尚未建立"} · 批准人 {data.endpoint.approver?.display_name ?? "尚未有效指定"}</p>}
      {data?.can_prepare && !focusProposalId && <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); prepare(); }}>
        {transferTarget && <div className="space-y-1 rounded-md border p-2 text-xs"><p>正在准备转接：{transferTarget.snapshot.predecessor.node.title} → {transferTarget.snapshot.successor.node.title}。请选择新节点和条件，原关系会保持生效直到双方批准并独立应用。</p><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setTransferTarget(null)}>取消转接编辑</Button></div>}
        <label className="block text-sm">另一个项目<select className={field} required disabled={busy || !!transferTarget} value={otherId} onChange={(event) => void chooseProject(event.target.value)}><option value="">选择可访问项目</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        {other && <p className="text-xs">对方基线 {other.baseline_version ? `v${other.baseline_version}` : "尚未建立"} · 批准人 {other.approver?.display_name ?? "尚未有效指定"}</p>}
        <label className="block text-sm">依赖方向<select className={field} value={direction} disabled={busy} onChange={(e) => setDirection(e.target.value)}><option value="incoming">本项目依赖对方</option><option value="outgoing">对方依赖本项目</option></select></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm">本项目节点<select className={field} required disabled={busy} value={ownNode} onChange={(e) => setOwnNode(e.target.value)}><option value="">选择正式节点</option>{data.endpoint.nodes.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}</select></label><label className="block text-sm">对方节点<select className={field} required disabled={busy || !other} value={otherNode} onChange={(e) => setOtherNode(e.target.value)}><option value="">选择正式节点</option>{other?.nodes.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}</select></label></div>
        <label className="block text-sm">依赖条件<select className={field} disabled={busy} value={relation} onChange={(e) => setRelation(e.target.value)}>{Object.entries(relations).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="block text-sm">间隔（负数表示提前）<input className={field} type="number" step="any" required disabled={busy} value={lag} onChange={(e) => setLag(e.target.value)} /></label><label className="block text-sm">间隔单位<select className={field} value={unit} disabled={busy} onChange={(e) => setUnit(e.target.value)}><option value="working_hours">后序执行日历的工作小时</option><option value="calendar_days">自然日</option></select></label></div>
        <p className="text-xs text-muted-foreground">提交时，将本申请中的两侧节点、基线版本、批准依据和办理意见共享给双方具名批准人。</p><label className="block text-sm">申请依据<textarea className={field} required maxLength={2048} disabled={busy} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        {(!data.endpoint.ready || (other && !other.ready)) && <p className="text-xs">两侧均需正式基线、有效具名批准政策及可办理的项目状态。</p>}
        <Button size="sm" disabled={busy || !data.endpoint.ready || !other?.ready || !ownNode || !otherNode || !reason.trim()}>提交双方确认</Button>
      </form>}
      {data?.items.filter((item) => !focusProposalId || item.id === focusProposalId).map((item) => <article className="space-y-2 border-t pt-3 text-sm" key={item.id}>
        <p className="font-medium">{item.operation === "remove" ? "解除申请 · " : item.operation === "replace" ? "转接申请 · " : ""}{item.snapshot.predecessor.project_name} · {item.snapshot.predecessor.node.title} → {item.snapshot.successor.project_name} · {item.snapshot.successor.node.title}</p>
        {item.snapshot.previous_relation && <p className="text-xs text-muted-foreground">原关系：{item.snapshot.previous_relation.predecessor.project_name} · {item.snapshot.previous_relation.predecessor.node.title} → {item.snapshot.previous_relation.successor.project_name} · {item.snapshot.previous_relation.successor.node.title} · {relations[item.snapshot.previous_relation.relation]} · 间隔 {item.snapshot.previous_relation.lag} {item.snapshot.previous_relation.lag_unit === "working_hours" ? "工作小时" : "自然日"}</p>}
        <p>{relations[item.relation]} · 间隔 {item.lag} {item.lag_unit === "working_hours" ? "后序工作小时" : "自然日"}</p>
        <p>{item.access_mode === "proposal_only" && "本侧批准人专用视图 · "}{statusLabels[item.status]}{!item.is_current && ["pending", "approved_pending_application", "applied"].includes(item.status) && " · 两侧依据已变化，需重新申请"}</p><p>{item.reason}</p>
        <details><summary className="cursor-pointer">查看双方固定版本和批准权限</summary>{(["predecessor", "successor"] as const).map((side) => <p key={side} className="mt-1 text-xs">{item.snapshot[side].project_name} · 基线 v{item.snapshot[side].baseline_version} · 批准人 {item.snapshot[side].approver?.display_name} · 政策 v{item.snapshot[side].policy?.version}：{item.snapshot[side].policy?.authority_basis}{item.snapshot[side].policy?.four_eyes && "（提交与批准分人）"}</p>)}</details>
        {item.decisions.map((decision) => <p key={decision.id} className="text-xs">{decision.project_id === item.snapshot.predecessor.project_id ? item.snapshot.predecessor.project_name : item.snapshot.successor.project_name}：{labels[decision.action]} · {decision.reason} · {new Date(decision.created_at).toLocaleString()}</p>)}
        {item.application && <p className="text-xs">应用于 {new Date(item.application.created_at).toLocaleString()} · {item.application.reason}{item.application.replaces_application_id && " · 已保留被替换关系的历史"}</p>}
        {item.can_apply && <div className="space-y-2"><p className="text-xs">{item.operation === "remove" ? "将解除本申请指定的有效依赖，历史批准与应用记录继续保留。" : item.operation === "replace" ? "将在一次事务中关闭原关系并建立本申请的新关系，保留完整历史。" : item.current_relation_application_id ? "将替换同节点、同类型关系的当前版本，保留原应用历史。" : "将新增执行依赖，并更新后序项目预测。"}应用不会改写双方已批准的基线日期或资源预约。</p><label className="block text-sm">应用依据<textarea className={field} disabled={busy} value={reasons[item.id] ?? ""} maxLength={2048} onChange={(e) => setReasons({ ...reasons, [item.id]: e.target.value })} /></label><label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={busy} checked={read[item.id] ?? false} onChange={(e) => setRead({ ...read, [item.id]: e.target.checked })} />已核对双方批准版本及实际生效条件</label><Button type="button" size="sm" disabled={busy || !read[item.id] || !(reasons[item.id] ?? "").trim()} onClick={() => void send(`${path}/${item.id}/application`, { expected_digest: item.payload_digest, expected_previous_application_id: item.current_relation_application_id, expected_destination_application_id: item.destination_application_id, reason: reasons[item.id] }, item.operation === "remove" ? "依赖已按双方批准解除，后序约束与预测已更新。" : "跨项目依赖已应用，后序执行约束与预测已更新。")}>{item.operation === "remove" ? "独立应用已批准解除" : item.operation === "replace" ? "原子应用已批准转接" : "独立应用已批准依赖"}</Button></div>}
        {item.can_request_removal && <div className="space-y-2"><label className="block text-sm">解除依赖的依据<textarea className={field} maxLength={2048} disabled={busy} value={reasons[item.id] ?? ""} onChange={(e) => setReasons({ ...reasons, [item.id]: e.target.value })} /></label><Button type="button" size="sm" variant="outline" disabled={busy || !(reasons[item.id] ?? "").trim()} onClick={() => void requestRemoval(item)}>申请双方解除此依赖</Button>{!focusProposalId && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void beginTransfer(item)}>调整或转接到其他节点</Button>}</div>}
        {(item.can_decide || item.can_withdraw) && <><label className="block text-sm">本次办理依据<textarea className={field} maxLength={2048} value={reasons[item.id] ?? ""} disabled={busy} onChange={(e) => setReasons({ ...reasons, [item.id]: e.target.value })} /></label>{item.can_approve && <label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={busy} checked={read[item.id] ?? false} onChange={(e) => setRead({ ...read, [item.id]: e.target.checked })} />已核对两侧节点、基线与依赖条件</label>}<div className="flex flex-wrap gap-2">{([...(item.can_approve ? ["approve"] : []), ...(item.can_decide ? ["reject"] : []), ...(item.can_withdraw ? ["withdraw"] : [])]).map((action) => <Button key={action} type="button" size="sm" variant={action === "approve" ? "default" : "outline"} disabled={busy || !(reasons[item.id] ?? "").trim() || (action === "approve" && !read[item.id])} onClick={() => void send(`${path}/${item.id}`, { action, expected_digest: item.payload_digest, reason: reasons[item.id] }, "本项目意见已保存；双方批准后仍需独立应用。")}>
          {action === "approve" ? "确认本项目批准" : action === "reject" ? "拒绝申请" : "撤回申请"}</Button>)}</div></>}
      </article>)}
      {data && !data.items.some((item) => !focusProposalId || item.id === focusProposalId) && <p className="text-xs text-muted-foreground">暂无你可查看或办理的跨项目申请。</p>}
      {data?.has_more && <p className="text-xs text-muted-foreground">仅显示最近 200 项范围内可访问的申请。</p>}
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void refresh()}>刷新双方依据与申请</Button>
    </>}
  </section>;
}
