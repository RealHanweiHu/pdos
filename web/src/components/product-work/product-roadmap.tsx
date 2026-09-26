"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { emptyFact, FactEditor, type Fact } from "./market-segments";
import { request, type Evidence, type EvidenceContent, type ProductCatalog, type ProductNode, type Workspace } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const kinds: Record<string, string> = { definition: "定义就绪", development: "开发启动", validation: "验证", launch: "上市", retirement: "退市", other: "其他节点" };
type Checkpoint = { key: string; title: string; kind: string; owner_user_id: string; window_start: string | null; window_end: string | null; unknown_reason: string | null; basis: Fact; disposition: "planned" | "cancelled"; cancellation_reason: string | null };
type Content = { scope_note: string; checkpoints: Checkpoint[] };
type Source = { product: ProductNode; release_id: string; definition_id: string; definition_revision: number; released_at: string; launch_window: Fact; target_users: string[]; scenarios: string[] };
export type Roadmap = { id: string; version: number; state: "published" | "withdrawn"; body: Content; source_snapshot: Source; source_digest: string; reason: string; actor_user_id: string; actor_name?: string; created_at: string; source_current?: boolean; source_warnings?: string[] };
type Read = { source: Source | null; source_digest: string | null; product: ProductNode; latest: Roadmap | null; can_manage: boolean; can_publish: boolean; source_warnings: string[] };
type History = { items: Roadmap[]; next_before_version: number | null };

export function RoadmapBoardCard({ roadmap, sourceCurrent }: { roadmap: Roadmap | null; sourceCurrent: boolean }) {
  if (!roadmap) return <p className="text-xs text-muted-foreground">尚未发布路线图</p>;
  return <div className="space-y-1 rounded-md bg-muted p-2 text-xs"><p>路线图 v{roadmap.version} · {roadmap.state === "withdrawn" ? "已撤回" : "已发布计划"}</p>{!sourceCurrent && <p>产品或定义依据已变化，原计划待重核。</p>}{roadmap.state === "published" && roadmap.body.checkpoints.map(item => <p key={item.key}>{item.title} · {item.disposition === "cancelled" ? `已取消：${item.cancellation_reason}` : item.window_start ? `${item.window_start} ～ ${item.window_end}` : `日期未定：${item.unknown_reason}`}</p>)}</div>;
}

export function ProductRoadmap({ base, catalog, workspace, evidence }: { base: string; catalog: ProductCatalog; workspace: Workspace; evidence: Evidence[] }) {
  return <Suspense fallback={<p className="text-sm">正在读取路线图入口…</p>}><RoadmapWorkspace base={base} catalog={catalog} workspace={workspace} evidence={evidence}/></Suspense>;
}

function RoadmapWorkspace({ base, catalog, workspace, evidence }: { base: string; catalog: ProductCatalog; workspace: Workspace; evidence: Evidence[] }) {
  const search = useSearchParams();
  const [selected, setProductId] = useState<string | null>(null);
  const target = search.get("roadmap_product");
  const productId = selected ?? (target && catalog.nodes.some(node => node.id === target) ? target : "");
  return <section id="product-roadmap" className="space-y-4 rounded-lg border p-4"><header><h3 className="font-semibold">产品路线图编排</h3><p className="mt-1 text-sm text-muted-foreground">产品负责人发布计划窗口，保留定义依据与历次取舍。计划节点不表示实际完成，也不改变工程排程、产品生命周期或已发布定义。</p></header><label className="block max-w-xl text-sm">选择产品<select className={field} value={productId} onChange={event => setProductId(event.target.value)}><option value="">选择产品家族、系列、型号或变体</option>{catalog.nodes.map(node => <option key={node.id} value={node.id}>{node.code} · {node.name}</option>)}</select></label>{productId && <RoadmapDetail key={productId} base={base} productId={productId} catalog={catalog} workspace={workspace} evidence={evidence} />}</section>;
}

function RoadmapDetail({ base, productId, catalog, workspace, evidence }: { base: string; productId: string; catalog: ProductCatalog; workspace: Workspace; evidence: Evidence[] }) {
  const [data, setData] = useState<Read | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState<EvidenceContent | null>(null);
  const [reading, setReading] = useState(false);
  const lastRequest = useRef({ body: "", id: "" });
  useEffect(() => {
    let live = true;
    void request<Read>(`${base}/product-roadmap`, "POST", { product_id: productId }).then(value => { if (live) setData(value); }).catch(failure => { if (live) setError(failure.message); }).finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [base, productId]);
  const load = async () => { setData(await request<Read>(`${base}/product-roadmap`, "POST", { product_id: productId })); };
  const read = (id: string) => {
    if (reading) return;
    setReading(true); setContent(null); setError(null);
    void request<EvidenceContent>(`${base}/evidence/${id}/content`).then(setContent).catch(failure => setError(failure.message)).finally(() => setReading(false));
  };
  const loadHistory = async (before: number | null = null) => {
    setBusy(true); setError(null);
    try { const value = await request<History>(`${base}/product-roadmap-history`, "POST", { product_id: productId, before_version: before }); setHistory(old => before && old ? { ...value, items: [...old.items, ...value.items] } : value); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "历史暂不可用"); }
    finally { setBusy(false); }
  };
  const save = async (action: "publish" | "withdraw", body: Content | null, note: string) => {
    if (!data) return;
    const command = { product_id: productId, expected_version: data.latest?.version ?? 0, expected_source_digest: action === "publish" ? data.source_digest : null, action, body, reason: note.trim() };
    const signature = JSON.stringify(command);
    if (signature !== lastRequest.current.body) lastRequest.current = { body: signature, id: crypto.randomUUID() };
    setBusy(true); setError(null);
    try { await request(`${base}/product-roadmap-save`, "POST", { ...command, request_id: lastRequest.current.id }); setEditing(false); setReason(""); setHistory(null); await load(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "路线图未保存，请重试"); }
    finally { setBusy(false); }
  };
  const name = (id: string) => workspace.members.find(member => member.id === id)?.display_name ?? `原负责人 ${id}`;
  return <div className="space-y-3"><Button size="sm" variant="outline" disabled={busy || editing} onClick={() => { setBusy(true); setError(null); void load().catch(failure => setError(failure.message)).finally(() => setBusy(false)); }}>刷新当前依据与路线图</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{reading && <p role="status" className="text-sm">正在读取依据…</p>}{content && <section className="space-y-2 rounded-md bg-muted p-3"><div className="flex justify-between"><h4 className="font-medium">日期依据原文</h4><Button size="sm" variant="ghost" onClick={() => setContent(null)}>关闭</Button></div><p className="break-all text-xs">{content.snapshot_id} · {content.content_digest}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm">{content.content}</pre></section>}
    {data && <><p className="text-sm">{data.product.code} · {data.product.name} · 地区 {data.product.regions.join("、") || "未声明"} · 渠道 {data.product.channels.join("、") || "未声明"}</p>{data.source ? <div className="space-y-1 text-sm"><p>当前发布定义 v{data.source.definition_revision} · {new Date(data.source.released_at).toLocaleString()}</p><p>原上市窗口：{data.source.launch_window.text}（{({ hypothesis: "假设", observed: "观察事实", derived: "推导" })[data.source.launch_window.fact_kind]}）</p><a className="underline" href={`/product-work?space=${workspace.space.id}&tab=definitions#definition-${data.source.definition_id}`}>打开原定义</a>{data.source_warnings.map(warning => <p key={warning}>{warning}</p>)}</div> : <p className="text-sm">当前没有有效发布定义，可查看和撤回原路线图；新增发布需先完成产品定义发布。</p>}
      {data.latest ? <RoadmapRecord value={data.latest} spaceId={workspace.space.id} name={name} onRead={read} /> : <p className="text-sm text-muted-foreground">尚未发布此产品的路线图。</p>}
      {!editing && data.can_publish && <Button disabled={busy} onClick={() => setEditing(true)}>{data.latest ? "修订并发布路线图" : "编排并发布路线图"}</Button>}
      {editing && <RoadmapForm key={`${data.latest?.version ?? 0}:${data.source_digest}`} current={data} workspace={workspace} catalog={catalog} evidence={evidence} busy={busy} onSave={(body, note) => void save("publish", body, note)} onCancel={() => setEditing(false)} />}
      {!editing && data.can_manage && data.latest?.state === "published" && <form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void save("withdraw", null, reason); }}><label className="min-w-64 flex-1 text-sm">撤回原因<input required maxLength={2048} className={field} value={reason} onChange={event => setReason(event.target.value)} /></label><Button variant="outline" disabled={busy || !reason.trim()}>撤回并保留历史</Button></form>}
      <Button variant="outline" disabled={busy || editing} onClick={() => void loadHistory()}>读取 / 刷新完整历史</Button>{history && <div className="space-y-3">{history.items.map(value => <details key={value.id} className="rounded-md border p-3"><summary className="cursor-pointer text-sm">v{value.version} · {value.state === "published" ? "发布" : "撤回"} · {value.actor_name} · {new Date(value.created_at).toLocaleString()}</summary><RoadmapRecord value={value} spaceId={workspace.space.id} name={name} onRead={read}/></details>)}{!history.items.length && <p className="text-sm">没有路线图历史。</p>}{history.next_before_version !== null && <Button variant="outline" disabled={busy || editing} onClick={() => void loadHistory(history.next_before_version)}>读取更早版本</Button>}</div>}
    </>}{!data && <p className="text-sm">{busy ? "正在读取产品和原路线图…" : "数据暂不可用，请刷新重试。"}</p>}
  </div>;
}

function RoadmapRecord({ value, spaceId, name, onRead }: { value: Roadmap; spaceId: string; name: (id: string) => string; onRead: (id: string) => void }) {
  return <article className="space-y-2 rounded-md border p-3 text-sm"><p className="font-medium">路线图 v{value.version} · {value.state === "published" ? "已发布计划" : "已撤回"}</p><p>{value.actor_name} · {new Date(value.created_at).toLocaleString()} · {value.reason}</p><p>适用范围：{value.body.scope_note}</p><p>当时产品：{value.source_snapshot.product.code} · {value.source_snapshot.product.name}；定义 v{value.source_snapshot.definition_revision}</p><a className="underline" href={`/product-work?space=${spaceId}&tab=definitions#definition-${value.source_snapshot.definition_id}`}>原发布定义</a>{!value.source_current && <p className="text-destructive">产品范围或当前发布定义已变化，原路线图待重核；历史内容保留。</p>}{value.source_warnings?.map(warning => <p key={warning}>{warning}</p>)}{value.body.checkpoints.map(item => <div key={item.key} className="space-y-1 border-t pt-2"><p>{item.key} · {item.title} · {kinds[item.kind]} · {name(item.owner_user_id)}</p><p>{item.disposition === "cancelled" ? `已取消：${item.cancellation_reason}` : item.window_start ? `计划窗口 ${item.window_start} ～ ${item.window_end}` : `日期未定：${item.unknown_reason}`}</p><p>依据：{item.basis.text} · {({ hypothesis: "假设", observed: "观察事实", derived: "推导" })[item.basis.fact_kind]}</p>{item.basis.derivation_version && <p>推导方法：{item.basis.derivation_version}</p>}{item.basis.sources.map((ref, index) => <button type="button" className="mr-2 text-xs underline" key={`${ref.ref_id}:${index}`} onClick={() => onRead(ref.ref_id)}>原依据 {index + 1}</button>)}</div>)}</article>;
}

function RoadmapForm({ current, workspace, catalog, evidence, busy, onSave, onCancel }: { current: Read; workspace: Workspace; catalog: ProductCatalog; evidence: Evidence[]; busy: boolean; onSave: (body: Content, reason: string) => void; onCancel: () => void }) {
  const createCheckpoint = (): Checkpoint => ({ key: `node-${crypto.randomUUID().slice(0, 8)}`, title: "", kind: "other", owner_user_id: current.product.owner_user_id, window_start: null, window_end: null, unknown_reason: "", basis: emptyFact(), disposition: "planned", cancellation_reason: null });
  const [body, setBody] = useState<Content>(() => current.latest?.body ?? { scope_note: "", checkpoints: [{ key: "launch", title: "计划上市", kind: "launch", owner_user_id: current.product.owner_user_id, window_start: null, window_end: null, unknown_reason: "", basis: current.source?.launch_window ?? emptyFact(), disposition: "planned", cancellation_reason: null }] });
  const [reason, setReason] = useState("");
  const oldKeys = new Set(current.latest?.body.checkpoints.map(item => item.key) ?? []);
  const members = workspace.members.filter(member => member.access !== "viewer" && catalog.members.some(grant => grant.product_line_id === current.product.product_line_id && grant.user_id === member.id && grant.access !== "viewer"));
  const update = (index: number, change: Partial<Checkpoint>) => setBody({ ...body, checkpoints: body.checkpoints.map((item, i) => i === index ? { ...item, ...change } : item) });
  return <form className="space-y-4 rounded-md border p-4" onSubmit={event => { event.preventDefault(); onSave(body, reason); }}><fieldset disabled={busy} className="space-y-4"><label className="block text-sm">适用市场、地区、渠道与范围<textarea required maxLength={2048} className={field} value={body.scope_note} onChange={event => setBody({ ...body, scope_note: event.target.value })}/></label><p className="text-xs text-muted-foreground">以当前发布定义和当前产品范围为依据。按节点逐项填写计划窗口或未定原因，节点类型不是实际业务完成状态。</p>{body.checkpoints.map((item, index) => <section key={index} className="space-y-3 rounded-md bg-muted p-3"><div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">节点标识<input required disabled={oldKeys.has(item.key)} pattern="[a-zA-Z0-9_.:-]+" maxLength={128} className={field} value={item.key} onChange={event => update(index, { key: event.target.value })}/></label><label className="text-sm">节点名称<input required maxLength={2048} className={field} value={item.title} onChange={event => update(index, { title: event.target.value })}/></label><label className="text-sm">节点类型<select className={field} disabled={oldKeys.has(item.key)} value={item.kind} onChange={event => update(index, { kind: event.target.value })}>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="text-sm">负责人<select required className={field} value={item.owner_user_id} onChange={event => update(index, { owner_user_id: event.target.value })}><option value="">选择有效协作成员</option>{!members.some(member => member.id === item.owner_user_id) && item.owner_user_id && <option value={item.owner_user_id}>原负责人（需核对）</option>}{members.map(member => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label><label className="text-sm">办理方式<select className={field} value={item.disposition} onChange={event => update(index, { disposition: event.target.value as Checkpoint["disposition"], cancellation_reason: event.target.value === "cancelled" ? "" : null })}><option value="planned">仍列入计划</option><option value="cancelled">明确取消，保留原节点</option></select></label>{item.disposition === "cancelled" && <label className="text-sm">取消原因<input required maxLength={2048} className={field} value={item.cancellation_reason ?? ""} onChange={event => update(index, { cancellation_reason: event.target.value })}/></label>}
        <label className="text-sm">窗口开始日期<input type="date" className={field} value={item.window_start ?? ""} onChange={event => update(index, { window_start: event.target.value || null, unknown_reason: event.target.value ? null : "" })}/></label><label className="text-sm">窗口结束日期<input type="date" className={field} value={item.window_end ?? ""} onChange={event => update(index, { window_end: event.target.value || null })}/></label>{!item.window_start && <label className="text-sm sm:col-span-2">日期未定原因<input required maxLength={2048} className={field} value={item.unknown_reason ?? ""} onChange={event => update(index, { unknown_reason: event.target.value })}/></label>}</div><FactEditor label="日期 / 取消依据（区分假设、观察与推导）" value={item.basis} evidence={evidence} onChange={basis => update(index, { basis })}/>{!oldKeys.has(item.key) && body.checkpoints.length > 1 && <Button type="button" variant="ghost" onClick={() => setBody({ ...body, checkpoints: body.checkpoints.filter((_, i) => i !== index) })}>移除此新增节点</Button>}</section>)}<Button type="button" variant="outline" disabled={body.checkpoints.length >= 30} onClick={() => setBody({ ...body, checkpoints: [...body.checkpoints, createCheckpoint()] })}>增加节点</Button><label className="block text-sm">本次发布 / 修订原因<textarea required maxLength={2048} className={field} value={reason} onChange={event => setReason(event.target.value)}/></label><div className="flex gap-2"><Button disabled={!reason.trim()}>具名发布路线图</Button><Button type="button" variant="outline" onClick={onCancel}>取消编辑</Button></div></fieldset></form>;
}
