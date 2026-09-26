"use client";

import { useRef, useState, useSyncExternalStore } from "react";
import { WorkResponsibility } from "@/components/product-work/work-responsibility";
import { ProjectIdCheckpoints } from "./project-id-checkpoints";
import { ProjectIdFreeze } from "./project-id-freeze";
import { Button } from "@/components/ui/button";
import { caseLinkRequest } from "@/components/cases/case-requirements";

type Revision = { id: string; variant_id: string; version: number; owner_user_id: string; brief: string; envelope: string | null; cmf: string | null; layout: string | null; interfaces: string | null; document_id: string | null; external_file_reference_id: string | null; artifact_snapshot: { filename?: string }; payload_digest: string; reason: string; created_at: string };
type Decision = { id: string; feedback_id: string; version: number; action: string; reason: string; resolution_revision_id: string | null; created_at: string };
type Feedback = { id: string; revision_id: string; topic: string; source_kind: string; source_reference: string; reported_at: string | null; content: string; decision: Decision | null };
type State = { frozen_variant_ids: string[]; variants: { id: string; title: string }[]; revisions: Revision[]; feedback: Feedback[]; decision_history: Decision[]; people: { id: string; display_name: string }[]; artifacts: { id: string; kind: string; filename: string }[]; has_more: boolean; current_user_id: string; can_manage: boolean; can_revise: boolean; can_decide: boolean; can_feedback: boolean };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const fields = { brief: "设计方向与简报", envelope: "关键尺寸 / 包络", cmf: "CMF（色彩、材料、表面处理）", layout: "操作布局及版本", interfaces: "结构 / 硬件接口约束" };
const topics: Record<string, string> = { appearance: "外观", ergonomics: "人机操作", cmf: "CMF", interface: "接口", cost: "成本", other: "其他" };
const actions: Record<string, string> = { planned: "安排后续修订", needs_decision: "冲突 / 等待决定", rejected: "不采纳", addressed: "已在后续版本处理" };
const blank = { title: "", owner_user_id: "", brief: "", envelope: "", cmf: "", layout: "", interfaces: "", artifact: "", reason: "" };

function subscribeOwnerLocation(callback:()=>void) { window.addEventListener("popstate",callback);return ()=>window.removeEventListener("popstate",callback); }
function selectedOwnerRevision() {const value=new URLSearchParams(window.location.search).get("id_owner_revision");return value && /^[0-9a-f-]{36}$/.test(value) ? value : null;}

export function ProjectIdDesign({ projectId }: { projectId: string }) {
  const focusedRevision=useSyncExternalStore(subscribeOwnerLocation,selectedOwnerRevision,()=>null);
  const [ownerLocked,setOwnerLocked]=useState(false);
  const [open, setOpen] = useState(false); const [data, setData] = useState<State | null>(null);
  const [variant, setVariant] = useState(""); const [revisionId, setRevisionId] = useState(""); const [compareId, setCompareId] = useState("");
  const [draft, setDraft] = useState(blank); const [editing, setEditing] = useState<Revision | null>(null);
  const [feedback, setFeedback] = useState({ source_kind: "customer", source_reference: "", topic: "appearance", content: "", reported_at: "" });
  const [decision, setDecision] = useState<Record<string, { action: string; resolution: string; reason: string }>>({});
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>()); const path = `projects/${projectId}/execution/id-design`;
  const revisions = (data?.revisions.filter((row) => row.variant_id === variant) ?? []).sort((a, b) => b.version - a.version);
  const selected = revisions.find((row) => row.id === revisionId) ?? revisions[0];
  const compared = data?.revisions.find((row) => row.id === compareId);
  const ownFeedback = data?.feedback.filter((row) => revisions.some((revision) => revision.id === row.revision_id)) ?? [];
  const canEdit = data?.can_revise && !data.frozen_variant_ids.includes(variant) && (!variant || data.can_manage || revisions[0]?.owner_user_id === data.current_user_id);
  const canDecide = data?.can_decide && (data.can_manage || revisions[0]?.owner_user_id === data.current_user_id);
  const title = (id: string) => data?.variants.find((row) => row.id === id)?.title ?? "方案";
  async function load() { const value = await caseLinkRequest<State>(path); setData(value); return value; }
  async function refresh() { setBusy(true); setError(null); try { await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "ID方案读取失败"); } finally { setBusy(false); } }
  async function send<T>(endpoint: string, body: object, message: string): Promise<T | null> {
    const key = JSON.stringify({ endpoint, body }); let requestId = ids.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); ids.current.set(key, requestId); }
    setBusy(true); setError(null); setNotice(null);
    try { const result = await caseLinkRequest<T>(endpoint, { ...body, request_id: requestId }); await load(); setNotice(message); return result; }
    catch (failure) { setError(failure instanceof Error ? failure.message : "办理未完成"); return null; }
    finally { setBusy(false); }
  }
  function edit(revision?: Revision) {
    setEditing(revision ?? null);
    setDraft(revision ? { title: title(revision.variant_id), owner_user_id: revision.owner_user_id, brief: revision.brief, envelope: revision.envelope ?? "", cmf: revision.cmf ?? "", layout: revision.layout ?? "", interfaces: revision.interfaces ?? "", artifact: revision.document_id ? `document:${revision.document_id}` : revision.external_file_reference_id ? `external:${revision.external_file_reference_id}` : "", reason: "" } : { ...blank, owner_user_id: data?.current_user_id ?? "" });
  }
  async function saveRevision() {
    const [kind, id] = draft.artifact.split(":");
    const result = await send<Revision>(path, { variant_id: editing?.variant_id ?? null, expected_version: editing?.version ?? 0,
      title: draft.title, owner_user_id: draft.owner_user_id, brief: draft.brief, envelope: draft.envelope.trim() || null, cmf: draft.cmf.trim() || null, layout: draft.layout.trim() || null, interfaces: draft.interfaces.trim() || null,
      document_id: kind === "document" ? id : null, external_file_reference_id: kind === "external" ? id : null, reason: draft.reason }, "新版本已保存，原版本及其反馈保持不变。");
    if (result) { setVariant(result.variant_id); setRevisionId(result.id); setEditing(null); setDraft({ ...blank, owner_user_id: data?.current_user_id ?? "" }); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <Button type="button" size="sm" variant="outline" disabled={busy || ownerLocked} onClick={() => { setOpen(!open); if (!open) void refresh(); }}>{open ? "收起ID方案与反馈" : "ID方案版本、比较与客户反馈"}</Button>
    {(focusedRevision || selected) && <WorkResponsibility key={focusedRevision || selected?.id} spaceId={projectId} kind="design" recordId={focusedRevision || selected!.id} initiallyOpen={!!focusedRevision} disabled={busy} onLock={setOwnerLocked} onChanged={async()=>{if(selected && !focusedRevision)setRevisionId(selected.id);await load();}}/>}
    {open && <fieldset disabled={ownerLocked} className="space-y-3">
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
      <p className="text-xs text-muted-foreground">各方向保留独立方案，每次修订生成新版本。反馈按实际评审版本记录；保存版本不表示设计冻结或交接通过。</p>
      <label className="block text-sm">方案<select className={field} value={variant} disabled={busy || ownerLocked} onChange={(e) => { setVariant(e.target.value); setRevisionId(""); setCompareId(""); edit(); }}><option value="">新建独立方案</option>{data?.variants.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></label>
      {selected && <>
        <label className="block text-sm">评审版本<select className={field} value={selected.id} disabled={busy || ownerLocked} onChange={(e) => setRevisionId(e.target.value)}>{revisions.map((row) => <option key={row.id} value={row.id}>v{row.version} · {new Date(row.created_at).toLocaleString()}</option>)}</select></label>
        <p className="text-xs">负责人：{data?.people.find((person) => person.id === selected.owner_user_id)?.display_name ?? "原负责人"} · {selected.reason}</p>
        <label className="block text-sm">与另一方案 / 版本比较<select className={field} value={compareId} disabled={busy || ownerLocked} onChange={(e) => setCompareId(e.target.value)}><option value="">不比较</option>{data?.revisions.filter((row) => row.id !== selected.id).map((row) => <option key={row.id} value={row.id}>{title(row.variant_id)} · v{row.version}</option>)}</select></label>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">内容</th><th className="p-2">{title(selected.variant_id)} · v{selected.version}</th>{compared && <th className="p-2">{title(compared.variant_id)} · v{compared.version}</th>}</tr></thead><tbody>{Object.entries(fields).map(([key, label]) => <tr className="border-t" key={key}><th className="p-2 align-top">{label}</th><td className="whitespace-pre-wrap p-2 align-top">{selected[key as keyof typeof fields] || "尚未明确"}</td>{compared && <td className="whitespace-pre-wrap p-2 align-top">{compared[key as keyof typeof fields] || "尚未明确"}</td>}</tr>)}<tr className="border-t"><th className="p-2">主图档</th><td className="p-2">{selected.artifact_snapshot.filename ?? "尚未关联"}</td>{compared && <td className="p-2">{compared.artifact_snapshot.filename ?? "尚未关联"}</td>}</tr></tbody></table></div>
        {canEdit && <Button type="button" size="sm" variant="outline" disabled={busy || ownerLocked} onClick={() => edit(revisions[0])}>基于最新版本继续修订</Button>}
      </>}
      {data?.can_revise && !data.frozen_variant_ids.includes(variant) && (!variant || editing) && <form className="space-y-3 rounded-md border p-3" onSubmit={(e) => { e.preventDefault(); void saveRevision(); }}>
        <p className="text-sm font-medium">{editing ? `修订 v${editing.version} → v${editing.version + 1}` : "编制新方案"}</p>
        <label className="block text-sm">方案名称<input className={field} required maxLength={512} disabled={busy || !!editing} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
        <label className="block text-sm">设计负责人<select className={field} required disabled={busy || ownerLocked} value={draft.owner_user_id} onChange={(e) => setDraft({ ...draft, owner_user_id: e.target.value })}><option value="">选择实际成员</option>{data.people.map((row) => <option key={row.id} value={row.id}>{row.display_name}</option>)}</select></label>
        {Object.entries(fields).map(([key, label]) => <label className="block text-sm" key={key}>{label}<textarea className={field} required={key === "brief"} maxLength={2048} disabled={busy || ownerLocked} value={draft[key as keyof typeof fields]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />{key !== "brief" && <span className="text-xs text-muted-foreground">未明确可留空。</span>}</label>)}
        <label className="block text-sm">本版本主图档<select className={field} disabled={busy || ownerLocked} value={draft.artifact} onChange={(e) => setDraft({ ...draft, artifact: e.target.value })}><option value="">尚未关联</option>{data.artifacts.map((row) => <option key={`${row.kind}:${row.id}`} value={`${row.kind}:${row.id}`}>{row.filename}</option>)}</select></label>
        <label className="block text-sm">编制 / 修订依据<textarea className={field} required maxLength={2048} disabled={busy || ownerLocked} value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} /></label>
        <Button size="sm" disabled={busy || ownerLocked}>保存新版本</Button>{editing && <Button type="button" size="sm" variant="ghost" disabled={busy || ownerLocked} onClick={() => setEditing(null)}>取消修订</Button>}
      </form>}
      {selected && data?.can_feedback && <form className="space-y-2 rounded-md border p-3" onSubmit={(e) => { e.preventDefault(); void send(`${path}/revisions/${selected.id}/feedback`, { ...feedback, reported_at: feedback.reported_at ? new Date(feedback.reported_at).toISOString() : null, expected_revision_digest: selected.payload_digest }, `反馈已绑定 ${title(selected.variant_id)} v${selected.version}。`); }}>
        <p className="text-sm font-medium">记录 v{selected.version} 的反馈</p>
        <div className="grid gap-2 sm:grid-cols-2"><label className="text-sm">来源<select className={field} disabled={busy || ownerLocked} value={feedback.source_kind} onChange={(e) => setFeedback({ ...feedback, source_kind: e.target.value })}><option value="customer">客户反馈</option><option value="internal">内部评审</option></select></label><label className="text-sm">主题<select className={field} disabled={busy || ownerLocked} value={feedback.topic} onChange={(e) => setFeedback({ ...feedback, topic: e.target.value })}>{Object.entries(topics).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <label className="block text-sm">来源依据<input className={field} required maxLength={2048} disabled={busy || ownerLocked} value={feedback.source_reference} onChange={(e) => setFeedback({ ...feedback, source_reference: e.target.value })} /></label>
        <label className="block text-sm">反馈发生时间（未知可留空）<input className={field} type="datetime-local" disabled={busy || ownerLocked} value={feedback.reported_at} onChange={(e) => setFeedback({ ...feedback, reported_at: e.target.value })} /></label>
        <label className="block text-sm">原始意见<textarea className={field} required maxLength={2048} disabled={busy || ownerLocked} value={feedback.content} onChange={(e) => setFeedback({ ...feedback, content: e.target.value })} /></label><Button size="sm" disabled={busy || ownerLocked}>记录此版本反馈</Button>
      </form>}
      {ownFeedback.map((item) => { const source = revisions.find((row) => row.id === item.revision_id); const input = decision[item.id] ?? { action: "planned", resolution: "", reason: "" }; return <article key={item.id} className="space-y-2 border-t pt-3 text-sm"><p className="font-medium">v{source?.version ?? "—"} · {topics[item.topic]} · {item.source_kind === "customer" ? "客户" : "内部"}反馈</p><p className="whitespace-pre-wrap">{item.content}</p><p className="text-xs text-muted-foreground">{item.source_reference}{item.reported_at && ` · ${new Date(item.reported_at).toLocaleString()}`}</p><p className="text-xs">{item.decision ? `${actions[item.decision.action]}：${item.decision.reason}` : "尚未处理"}</p>
        {canDecide && <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void send(`${path}/feedback/${item.id}`, { expected_version: item.decision?.version ?? 0, action: input.action, resolution_revision_id: input.action === "addressed" ? input.resolution : null, reason: input.reason }, "处理意见已追加，原始反馈与旧意见继续保留。"); }}><label className="block text-xs">处理意见<select className={field} disabled={busy || ownerLocked} value={input.action} onChange={(e) => setDecision({ ...decision, [item.id]: { ...input, action: e.target.value } })}>{Object.entries(actions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>{input.action === "addressed" && <label className="block text-xs">实际落实版本<select className={field} required disabled={busy || ownerLocked} value={input.resolution} onChange={(e) => setDecision({ ...decision, [item.id]: { ...input, resolution: e.target.value } })}><option value="">选择实际后续版本</option>{revisions.filter((row) => row.version > (source?.version ?? Infinity)).map((row) => <option key={row.id} value={row.id}>v{row.version}</option>)}</select></label>}<label className="block text-xs">处理依据<textarea className={field} required maxLength={2048} disabled={busy || ownerLocked} value={input.reason} onChange={(e) => setDecision({ ...decision, [item.id]: { ...input, reason: e.target.value } })} /></label><Button size="sm" disabled={busy || ownerLocked}>记录处理意见</Button></form>}
        <details><summary className="cursor-pointer text-xs">处理历史</summary>{data?.decision_history.filter((row) => row.feedback_id === item.id).map((row) => <p key={row.id} className="mt-1 text-xs">意见 v{row.version} · {actions[row.action]} · {row.reason}{row.resolution_revision_id && ` · 落实于方案 v${revisions.find((rev) => rev.id === row.resolution_revision_id)?.version ?? "—"}`} · {new Date(row.created_at).toLocaleString()}</p>)}</details>
      </article>; })}
      {selected && data && <ProjectIdFreeze key={selected.id} projectId={projectId} revision={selected} people={data.people} artifacts={data.artifacts} currentUserId={data.current_user_id} canManage={data.can_manage && data.can_revise} canDecide={data.can_decide} onOpenVariant={(id) => { setVariant(id); setRevisionId(""); setCompareId(""); setEditing(null); void refresh(); }} />}
      {data && <ProjectIdCheckpoints projectId={projectId} variants={data.variants} />}
      {data?.has_more && <p className="text-xs text-muted-foreground">当前展示最近200个方案、1000个版本和500条反馈；更早历史仍保留。</p>}
      <Button type="button" size="sm" variant="ghost" disabled={busy || ownerLocked} onClick={() => void refresh()}>刷新方案与反馈</Button>
    </fieldset>}
  </section>;
}
