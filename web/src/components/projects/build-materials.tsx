"use client";

import { useRef, useState } from "react";
import { MaterialAdmissionControl } from "@/components/projects/material-admission-control";
import { BuildSupplyAllocation } from "@/components/projects/build-supply-allocation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type BomItem = { id: string; parent_item_id: string | null; line_number: number; part_number: string; description: string; quantity: string; unit: string; material_reference: string | null };
type Bom = { id: string; code: string; name: string; version: number };
type Node = { id: string; title: string | null };
type Line = { bom_item_id: string; line_number: number; part_number: string; description: string; unit: string; material_reference: string | null; per_build_quantity: string; required_quantity: string; critical: boolean; path: string[] };
type Snapshot = { build: { code: string; phase: string; planned_quantity: number }; bom: { header: Bom; items: BomItem[] }; need_by_node: Node };
type ChangeContext = { ecn: { id: string; code: string; title: string; ecr_id: string; effectivity: Record<string, unknown> }; decision: { decided_at: string; decided_by_user_id: string }; applicability_basis: string };
type Delta = { material_reference: string | null; part_number: string; unit: string; before_quantity: string; after_quantity: string; quantity_delta: string; before_critical: boolean; after_critical: boolean };
type Preview = { previous?: Revision; delta?: Delta[]; change_context?: ChangeContext; digest: string; snapshot: Snapshot; lines: Line[]; selected_item_ids: string[]; warnings: string[] };
type Revision = { previous_revision_id?: string | null; delta?: Delta[] | null; change_context?: ChangeContext | null; id: string; version: number; request_id: string; content_digest: string; snapshot: Snapshot; lines: Line[]; reason: string; created_at: string; created_by_user_id: string; created_by_name?: string };
type State = { can_revise: boolean; ecns: { id: string; code: string; title: string }[]; ecns_has_more: boolean; build: { status: string }; boms: Bom[]; boms_has_more: boolean; nodes: Node[]; revisions: Revision[]; source_is_current: boolean | null; has_more: boolean };
type Selection = { bom_id: string; need_by_node_id: string; selected_item_ids: string[] | null; critical_item_ids: string[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "批次需求暂不可用，请刷新核对记录");
  return value as T;
}
function DemandLines({ lines }: { lines: Line[] }) {
  return <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">BOM项 / 物料</th><th className="p-2">单台展开量</th><th className="p-2">批次需求</th><th className="p-2">物料引用 / 关键件</th></tr></thead><tbody>{lines.map(line => <tr key={line.bom_item_id} className="border-t align-top"><td className="p-2">#{line.line_number} · {line.part_number}<p className="text-muted-foreground">{line.description}</p></td><td className="p-2">{line.per_build_quantity} {line.unit}</td><td className="p-2 font-medium">{line.required_quantity} {line.unit}</td><td className="p-2">{line.material_reference || "待补物料引用"}<p>{line.critical ? "人工列为关键件" : "未列为关键件"}</p></td></tr>)}</tbody></table></div>;
}

function RevisionDelta({ delta }: { delta: Delta[] }) {
  return <div className="space-y-2"><p className="text-xs font-medium">相对上一固定版的计划需求差量 · {delta.length} 项</p>{delta.length === 0 && <p className="text-xs">数量与关键件标记没有差异；仍保留本次BOM、节点及ECN来源修订。</p>}<div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">物料引用 / 料号</th><th className="p-2">原需求 → 新需求</th><th className="p-2">增减 / 单位</th><th className="p-2">关键件</th></tr></thead><tbody>{delta.map((line, index) => <tr key={index} className="border-t"><td className="p-2">{line.material_reference || "引用未核对"} · {line.part_number}</td><td className="p-2">{line.before_quantity} → {line.after_quantity}</td><td className="p-2">{line.quantity_delta} {line.unit}</td><td className="p-2">{line.before_critical ? "是" : "否"} → {line.after_critical ? "是" : "否"}</td></tr>)}</tbody></table></div></div>;
}
function ChangeBasis({ value, projectId }: { value: ChangeContext; projectId: string }) {
  return <section className="space-y-2 rounded-md border p-3 text-xs"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=engineering&ecr=${value.ecn.ecr_id}#ecn-${value.ecn.id}`}>{value.ecn.code} · {value.ecn.title}</a><p>原生效裁决：{new Date(value.decision.decided_at).toLocaleString()} · {value.decision.decided_by_user_id}</p><p className="whitespace-pre-wrap">本批次适用依据：{value.applicability_basis}</p><details><summary className="cursor-pointer">核对原ECN完整生效说明</summary><pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify(value.ecn.effectivity, null, 2)}</pre></details></section>;
}

export function BuildMaterials({ projectId, buildId, canEdit }: { projectId: string; buildId: string; canEdit: boolean }) {
  const [data, setData] = useState<State | null>(null), [preview, setPreview] = useState<Preview | null>(null);
  const [bomId, setBomId] = useState(""), [nodeId, setNodeId] = useState("");
  const [selected, setSelected] = useState<string[] | null>(null), [critical, setCritical] = useState<string[]>([]);
  const [previewKey, setPreviewKey] = useState<string | null>(null), [reason, setReason] = useState("");
  const [ecnId, setEcnId] = useState(""), [applicability, setApplicability] = useState("");
  const [checked, setChecked] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const path = `/api/projects/${projectId}/npi/builds/${buildId}/materials`;
  const revisionMode = !!data?.revisions.length;
  const selection: Selection & { previous_revision_id?: string; ecn_id?: string; applicability_basis?: string } = { bom_id: bomId, need_by_node_id: nodeId, selected_item_ids: selected, critical_item_ids: critical, ...(revisionMode ? { previous_revision_id: data!.revisions[0].id, ecn_id: ecnId, applicability_basis: applicability } : {}) };
  const current = previewKey === JSON.stringify(selection);
  const editable = canEdit && data?.build.status === "planned";
  async function load() {
    const value = await request<State>(path);
    setData(value); setPreviewKey(null); setChecked(false);
    if (!nodeId && value.nodes.length === 1) setNodeId(value.nodes[0].id);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作未完成"); } finally { setBusy(false); } }
  async function prepare() {
    setChecked(false); setPreviewKey(null); setNotice(null);
    const value = await request<Preview>(`${path}/${revisionMode ? "revision-preview" : "preview"}`, selection);
    setPreview(value); setSelected(value.selected_item_ids);
    setPreviewKey(JSON.stringify({ ...selection, selected_item_ids: value.selected_item_ids }));
  }
  async function freeze() {
    if (!preview || !current || !checked) return;
    const body = { ...selection, expected_digest: preview.digest, reason };
    const signature = JSON.stringify(body);
    let requestId = ids.current.get(signature);
    if (!requestId) { requestId = crypto.randomUUID(); ids.current.set(signature, requestId); }
    try {
      await request<Revision>(`${path}/${revisionMode ? "revise" : "freeze"}`, { ...body, request_id: requestId });
      setNotice(revisionMode ? "已按ECN形成独立需求修订及差量，原版本保留，未写入ERP。" : "本批次需求与BOM快照已固定。原记录保持只读，未写入ERP。");
      await load();
      setPreview(null); setReason(""); setEcnId(""); setApplicability("");
    } catch (failure) {
      setNotice(`请刷新核对实际记录；相同输入重试沿用原请求 ${requestId}。`);
      throw failure;
    }
  }
  return <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}><summary className="cursor-pointer text-sm font-medium">批次物料需求与固定BOM</summary><div className="mt-3 space-y-3">
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新批次记录</Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    <p className="text-xs text-muted-foreground">项目需求保存用量与版本。ERP库存/采购、质量放行、批准替代和实际到货需另行核对；当前不据此判定齐套。</p>
    {data?.revisions.map((revision, index) => <section key={revision.id} className="space-y-2 rounded-md border p-3"><h4 className="text-sm font-medium">{index === 0 ? "当前固定需求" : "历史固定需求"} v{revision.version} · {revision.snapshot.build.code} · {revision.snapshot.build.planned_quantity} 台 · {revision.snapshot.build.phase.toUpperCase()}</h4><p className="text-xs">Prototype BOM {revision.snapshot.bom.header.code} v{revision.snapshot.bom.header.version} · {revision.snapshot.bom.header.name}</p><p className="text-xs">需料节点：{revision.snapshot.need_by_node.title ?? revision.snapshot.need_by_node.id} · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview`}>查看排程中的基线、承诺和预测</a></p><p className="text-xs">{new Date(revision.created_at).toLocaleString()} · {revision.created_by_name ?? revision.created_by_user_id} · {revision.reason}</p>{index === 0 && data.source_is_current === false && <p className="text-xs text-destructive">原BOM当前内容已变化或不可读取，本批次仍使用固定快照。可核对ECN并预览独立修订，原记录保持只读。</p>}{revision.change_context && <ChangeBasis value={revision.change_context} projectId={projectId} />}{revision.delta && <RevisionDelta delta={revision.delta} />}<DemandLines lines={revision.lines} /><details><summary className="cursor-pointer text-xs">固定BOM的原始条目与父子用量</summary><ul className="mt-2 max-h-80 space-y-1 overflow-auto text-xs">{revision.snapshot.bom.items.map(item => <li key={item.id}>#{item.line_number} · {item.part_number} · {item.description} · {item.quantity} {item.unit}{item.parent_item_id ? ` / 父项 #${revision.snapshot.bom.items.find(parent => parent.id === item.parent_item_id)?.line_number ?? "未知"}` : " / 台"} · {item.material_reference || "物料引用未填"}</li>)}</ul></details><details><summary className="cursor-pointer text-xs">固定依据</summary><p className="break-all text-xs">内容摘要：{revision.content_digest}</p><p className="break-all text-xs">请求编号：{revision.request_id}</p></details></section>)}
    {data && <MaterialAdmissionControl projectId={projectId} targetKind="build" targetId={buildId} />}
    {data && <BuildSupplyAllocation key={data.revisions[0]?.id ?? "unfrozen"} projectId={projectId} buildId={buildId} canEdit={canEdit} />}
    {data?.has_more && <p className="text-xs">当前显示最近50个固定版本。</p>}
    {data && data.revisions.length > 0 && data.build.status !== "planned" && <p className="text-xs">整批需求修订限尚未开工批次；在途仍需核对实际领料、装机和剩余适用数量，原需求继续保留。</p>}
    {data && data.revisions.length === 0 && !editable && <p className="text-xs">本批次尚无固定需求。本入口在批次开始前由工程编辑人员冻结；在途或历史批次的原始BOM仍需另行核对。</p>}
    {editable && <fieldset disabled={busy} className="space-y-3">{revisionMode && <section className="space-y-2 rounded-md border p-3"><h4 className="text-sm font-medium">根据ECN准备独立修订 · 原需求 v{data.revisions[0].version}</h4><p className="text-xs">需已批准生效的ECN，且原批准范围明确包含本批次与目标Prototype BOM。请核对生效时间及适用限制，再说明本批次适用依据。</p><label className="block text-xs">生效ECN<select className={field} value={ecnId} onChange={event => { setEcnId(event.target.value); setChecked(false); }}><option value="">选择实际ECN</option>{data.ecns.map(ecn => <option key={ecn.id} value={ecn.id}>{ecn.code} · {ecn.title}</option>)}</select></label>{data.ecns_has_more && <label className="block text-xs">最近200条以外的ECN标识<input className={field} value={ecnId} onChange={event => { setEcnId(event.target.value); setChecked(false); }} /></label>}<label className="block text-xs">本批次适用依据<textarea className={field} maxLength={2048} value={applicability} onChange={event => { setApplicability(event.target.value); setChecked(false); }} /></label>{!data.can_revise && <p className="text-xs">可准备与核对差量；实际形成修订需有变更批准权限。</p>}</section>}<div className="grid gap-3 sm:grid-cols-2"><label className="text-xs">本项目Prototype BOM<select className={field} value={bomId} onChange={event => { setBomId(event.target.value); setSelected(null); setCritical([]); setPreview(null); setPreviewKey(null); setChecked(false); }}><option value="">选择原BOM</option>{data.boms.map(bom => <option key={bom.id} value={bom.id}>{bom.code} v{bom.version} · {bom.name}</option>)}</select></label><label className="text-xs">本批次需料排程节点<select className={field} value={nodeId} onChange={event => { setNodeId(event.target.value); setChecked(false); }}><option value="">选择实际Build节点</option>{data.nodes.map(node => <option key={node.id} value={node.id}>{node.title ?? node.id}</option>)}</select></label></div>
      {!data.boms.length && <p className="text-xs">请先在工程页面登记Prototype BOM及用量。</p>}{data.boms_has_more && <p className="text-xs">显示最近200个BOM；可填写需使用的项目BOM标识。<input className={field} aria-label="指定BOM标识" value={bomId} onChange={event => { setBomId(event.target.value); setPreview(null); setSelected(null); setCritical([]); }} /></p>}{!data.nodes.length && <p className="text-xs">请先在项目概览的正式排程节点中登记本批次Build节点。</p>}
      {preview && <><p className="text-xs">默认展开到末级件；可改选整件供料层级。每条末级路径只能选一个层级；用量相对父项，根项为每台。</p><div className="max-h-80 space-y-2 overflow-y-auto rounded-md border p-2">{preview.snapshot.bom.items.map(item => <div key={item.id} className="flex flex-wrap gap-3 text-xs"><label><input type="checkbox" checked={selected?.includes(item.id) ?? false} onChange={event => { setSelected(event.target.checked ? [...(selected ?? []), item.id] : (selected ?? []).filter(id => id !== item.id)); setCritical(critical.filter(id => id !== item.id)); setChecked(false); }} /> #{item.line_number} · {item.part_number} · {item.quantity} {item.unit}{item.parent_item_id ? ` / 父项 #${preview.snapshot.bom.items.find(parent => parent.id === item.parent_item_id)?.line_number ?? "未知"}` : " / 台"}</label><label><input type="checkbox" disabled={!selected?.includes(item.id)} checked={critical.includes(item.id)} onChange={event => { setCritical(event.target.checked ? [...critical, item.id] : critical.filter(id => id !== item.id)); setChecked(false); }} />关键件</label></div>)}</div></>}
      <Button size="sm" variant="outline" disabled={!bomId || !nodeId || (revisionMode && (!ecnId || !applicability.trim()))} onClick={() => void act(prepare)}>{preview ? "重新计算并预览需求" : "展开BOM并预览需求"}</Button>
      {preview && <div className="space-y-2"><p className="text-sm font-medium">{preview.snapshot.build.code} · {preview.snapshot.build.planned_quantity} 台 · {preview.lines.length} 项需求{!current && "（选择已变化，须重新计算）"}</p>{preview.change_context && <ChangeBasis value={preview.change_context} projectId={projectId} />}{preview.delta && <RevisionDelta delta={preview.delta} />}<DemandLines lines={preview.lines} />{preview.warnings.map(warning => <p className="text-xs text-muted-foreground" key={warning}>{warning}</p>)}<label className="block text-xs">{revisionMode ? "本次修订说明" : "冻结依据"}<textarea className={field} value={reason} maxLength={2048} onChange={event => setReason(event.target.value)} /></label><label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={checked && current} disabled={!current} onChange={event => setChecked(event.target.checked)} />{revisionMode ? "已核对ECN生效范围与期限、本批次适用性、原/新数量、单位、关键件及缺项，按此预览形成独立修订" : "已核对批次/阶段、BOM版本、供料层级、数量单位、关键件及上述缺项，按本预览固定需求"}</label><Button size="sm" disabled={!current || !checked || !reason.trim() || (revisionMode && !data.can_revise)} onClick={() => void act(freeze)}>{revisionMode ? "按ECN形成独立需求修订" : "固定本批次BOM与需求"}</Button></div>}
    </fieldset>}
  </div></details>;
}
