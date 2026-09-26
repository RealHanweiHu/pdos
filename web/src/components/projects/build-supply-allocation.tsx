"use client";

import { useRef, useState } from "react";
import { BuildMaterialCoverage } from "@/components/projects/build-material-coverage";
import { MaterialExceptions } from "@/components/projects/material-exceptions";
import { MaterialMovements } from "./material-movements";
import { SupplySourceLink } from "./supply-sharing";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { decimalText } from "@/lib/decimal";

type Source = { id: string; batch_id: string; document_id: string | null; source_grant_id?: string; source_system: string; source_version: string; external_pool_id: string; external_item_id: string; unit: string; quantity: string | null; supply_kind: string; quality_status: string; expected_date: string | null; as_of: string; fresh_until: string };
type Pool = { pending_issue_quantity?: string; state: string; source: Source | null; available_quantity: string | null; reserved_quantity: string | null; allocatable: boolean };
type Line = { bom_item_id: string; part_number: string; material_reference: string | null; unit: string; critical: boolean; required_quantity: string; qualified_allocated: string; qualified_issued: string; expected_allocated: string; unverified_allocated: string; remaining_need: string; status: string; issues: string[] };
type Allocation = { issued_quantity: string; supply_grant_id: string | null; id: string; batch_id: string; revision_id: string; bom_item_id: string; supply_snapshot_id: string; source_system: string; external_pool_id: string; external_item_id: string; unit: string; quantity: string; remaining_quantity: string };
type Receipt = { id: string; action: string; created_at: string; created_by_user_id: string; reason: string; snapshot?: Record<string, unknown> };
type State = { build: { status: string }; revision: { id: string; version: number } | null; lines: Line[]; pools: Pool[]; allocations: Allocation[]; allocation_sources: Source[]; release_basis: string; totals: { line_count: number; ready_count: number; critical_count: number; critical_ready_count: number }; history: Receipt[]; pool_limit_reached: boolean; as_of: string };
type Item = { bom_item_id: string; supply_snapshot_id: string; quantity: string };
type Preview = { digest: string; proposed: (Item & { part_number: string; source_system: string; external_pool_id: string; external_item_id: string; unit: string; supply_kind: string; quality_status: string })[] };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const names: Record<string, string> = { share_no_longer_valid: "原共享已失效，需按当前授权重核", ready: "合格现货/有据净领料已覆盖", mapping_missing: "物料引用待补", source_missing: "无可用来源 / 单位待核对", source_review: "供给依据待重核", awaiting_arrival: "含预计到货占用", awaiting_allocation: "待明确分配", stale: "快照已过期", unknown_quantity: "供给量未知", unit_conflict: "原占用单位冲突", overallocated: "最新量低于总占用", quality_frozen: "质量冻结", quality_unknown: "质量放行未知", current_source_unreadable: "当前来源未获本项目读取授权", current: "读取时有效", on_hand: "现货", expected_receipt: "预计到货", released: "已放行", frozen: "冻结", unknown: "未知", allocate: "分配", release: "释放" };
const label = (value: string) => names[value] ?? value;
const when = (value: string) => new Date(value).toLocaleString();
const ratio = (ready: number, total: number) => total ? `${ready} / ${total} 项 · ${(ready / total * 100).toFixed(1)}%` : "未配置，比例未知";
async function request<T>(url: string, body?: object): Promise<T> {
  const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "分配资料暂不可用，请刷新核对原回执");
  return value as T;
}
function SourceBasis({ source, projectId }: { source: Source; projectId: string }) {
  return <span className="text-xs">{source.source_system} / {source.source_version} · {source.external_pool_id} · {source.external_item_id} · {label(source.supply_kind)} / {label(source.quality_status)}<br />数据截至 {when(source.as_of)} · 有效至 {when(source.fresh_until)}{source.expected_date && <> · 预计到货 {source.expected_date}</>} · <SupplySourceLink projectId={projectId} source={source}/><br />导入批次 {source.batch_id}</span>;
}

export function BuildSupplyAllocation({ projectId, buildId, canEdit }: { projectId: string; buildId: string; canEdit: boolean }) {
  const path = `/api/projects/${projectId}/npi/builds/${buildId}/supply-allocations`;
  const [data, setData] = useState<State | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]), [preview, setPreview] = useState<Preview | null>(null), [previewKey, setPreviewKey] = useState<string | null>(null);
  const [release, setRelease] = useState<Record<string, string>>({}), [releaseReason, setReleaseReason] = useState("");
  const [reason, setReason] = useState(""), [checked, setChecked] = useState(false), [releaseChecked, setReleaseChecked] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null), [receiptId, setReceiptId] = useState(""), [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const selection = { revision_id: data?.revision?.id, items };
  const current = previewKey === JSON.stringify(selection);
  const releaseItems = Object.entries(release).filter(([, quantity]) => quantity.trim()).map(([allocation_id, quantity]) => ({ allocation_id, quantity }));
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "操作未完成"); } finally { setBusy(false); } }
  async function load() { setData(await request<State>(path)); setPreview(null); setPreviewKey(null); setChecked(false); setReleaseChecked(false); }
  function edit(index: number, change: Partial<Item>) { setItems(items.map((item, i) => i === index ? { ...item, ...change } : item)); setChecked(false); }
  async function apply(action: "allocate" | "release") {
    if (!data || (action === "allocate" && (!preview || !current || !checked)) || (action === "release" && !releaseChecked)) return;
    const body = action === "allocate" ? { ...selection, expected_digest: preview!.digest, reason } : { expected_digest: data.release_basis, items: releaseItems, reason: releaseReason };
    const key = JSON.stringify({ action, body });
    let requestId = ids.current.get(key);
    if (!requestId) { requestId = crypto.randomUUID(); ids.current.set(key, requestId); }
    setNotice(`办理请求 ${requestId}；遇到网络中断，保留相同输入重试可复用原回执。`);
    const value = await request<Receipt>(`${path}/${action}`, { ...body, request_id: requestId });
    setReceipt(value); setReceiptId(value.id);
    setNotice(`${label(action)}已记录。回执 ${value.id}；本次只调整计划占用。`);
    if (action === "allocate") { setItems([]); setReason(""); } else { setRelease({}); setReleaseReason(""); }
    await load();
  }
  return <details className="rounded-md border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">批次供给分配与齐套</summary>
    <div className="mt-3 space-y-4">
      <p className="text-xs text-muted-foreground">按固定需求项核对。齐套仅计当前可读、有效且已放行的现货计划占用；预计到货另列。数量按原单位核算。实物领用、消耗与ERP库存须另行核对。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新供给与占用</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="break-all text-xs">{notice}</p>}
      {data && <><MaterialMovements projectId={projectId} buildId={buildId} canEdit={canEdit} onChanged={() => void act(load)}/>
        <MaterialExceptions key={`exceptions:${data.as_of}`} projectId={projectId} buildId={buildId}/>
        <BuildMaterialCoverage key={`${data.revision?.id ?? "none"}:${data.as_of}`} projectId={projectId} buildId={buildId} />
        <p className="text-xs">读取时点 {when(data.as_of)} · 当前需求 {data.revision ? `v${data.revision.version}` : "尚未固定"}</p>
        <div className="grid gap-3 sm:grid-cols-2"><p className="rounded-md border p-3 text-sm">总齐套：{ratio(data.totals.ready_count, data.totals.line_count)}</p><p className="rounded-md border p-3 text-sm">关键件齐套：{ratio(data.totals.critical_ready_count, data.totals.critical_count)}</p></div>
        <p className="text-xs">比例按完整覆盖的需求项计数，不能直接代表可生产台数或开工许可。未分配量不等于ERP短缺量。</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">物料 / 关键件</th><th className="p-2">固定需求</th><th className="p-2">合格现货 / 预计到货 / 待核对</th><th className="p-2">尚需合格现货 / 状态</th></tr></thead><tbody>{data.lines.map(line => <tr key={line.bom_item_id} className="border-t"><td className="p-2">{line.part_number} {line.critical && "· 关键"}<p>{line.material_reference || "物料引用未填"}</p></td><td className="p-2">{decimalText(line.required_quantity)} {line.unit}</td><td className="p-2">{decimalText(line.qualified_allocated)} / {decimalText(line.expected_allocated)} / {decimalText(line.unverified_allocated)}</td><td className="p-2">{decimalText(line.remaining_need)} {line.unit}<p>{label(line.status)}</p>{line.issues.map(issue => <p key={issue}>{label(issue)}</p>)}</td></tr>)}</tbody></table></div>
        <details><summary className="cursor-pointer text-sm">匹配供给池及全部批次计划占用 · {data.pools.length}</summary><div className="mt-2 space-y-2">{data.pools.map((pool, index) => <section key={pool.source?.id ?? index} className="rounded-md border p-2">{pool.source && <SourceBasis source={pool.source} projectId={projectId} />}<p className="text-xs">{label(pool.state)} · 原供给量 {decimalText(pool.source?.quantity)} · 总计划占用 {decimalText(pool.reserved_quantity, "不可比 / 未授权")} · 计划余量 {decimalText(pool.available_quantity)}</p></section>)}{!data.pools.length && <p className="text-xs">尚无匹配的供给快照。请先在物料·供应页核对原件与物料引用。</p>}</div></details>
        {data.pool_limit_reached && <p className="text-xs">匹配池超过500个，当前列表不是完整供给。可填实际快照标识进行权限与最新版本核对；不能据列表推断总短缺。</p>}
        {canEdit && data.revision && ["planned", "in_progress"].includes(data.build.status) && <fieldset disabled={busy} className="space-y-3 rounded-md border p-3"><legend className="px-1 text-sm font-medium">准备明确分配</legend>
          <p className="text-xs">同一需求可分多个供给池；跨批次、跨导入版本共用余量。旧版占用须明确释放后重新分配。未知放行供给可作计划占用，但不计合格现货。</p>
          {items.map((item, index) => { const line = data.lines.find(row => row.bom_item_id === item.bom_item_id); const choices = data.pools.filter(pool => pool.allocatable && pool.source && pool.source.external_item_id === line?.material_reference && pool.source.unit === line.unit); return <div className="grid gap-2 rounded-md border p-2 sm:grid-cols-3" key={index}>
            <label className="text-xs">需求项<select className={field} value={item.bom_item_id} onChange={event => edit(index, { bom_item_id: event.target.value, supply_snapshot_id: "" })}><option value="">选择固定需求</option>{data.lines.map(row => <option key={row.bom_item_id} value={row.bom_item_id}>{row.part_number} · {row.material_reference || "待补引用"} · {row.unit}</option>)}</select></label>
            <label className="text-xs">当前供给快照<select className={field} value={item.supply_snapshot_id} onChange={event => edit(index, { supply_snapshot_id: event.target.value })}><option value="">选择可计划占用的供给</option>{choices.map(pool => <option key={pool.source!.id} value={pool.source!.id}>{pool.source!.source_system} / {pool.source!.external_pool_id} · 余 {decimalText(pool.available_quantity)} ·{label(pool.source!.supply_kind)} / {label(pool.source!.quality_status)}</option>)}</select>{data.pool_limit_reached && <input aria-label="指定供给快照标识" className={field} placeholder="其他实际快照标识" value={item.supply_snapshot_id} onChange={event => edit(index, { supply_snapshot_id: event.target.value })} />}</label>
            <label className="text-xs">本次分配量 {line?.unit}<input className={field} inputMode="decimal" value={item.quantity} onChange={event => edit(index, { quantity: event.target.value })} /></label>
            <Button size="sm" variant="ghost" onClick={() => { setItems(items.filter((_, i) => i !== index)); setChecked(false); }}>移除此项</Button>
          </div>; })}
          <Button size="sm" variant="outline" disabled={items.length >= 200} onClick={() => { setItems([...items, { bom_item_id: "", supply_snapshot_id: "", quantity: "" }]); setChecked(false); }}>添加分配项</Button>{" "}
          <Button size="sm" variant="outline" disabled={!items.length || items.some(item => !item.bom_item_id || !item.supply_snapshot_id || !item.quantity.trim())} onClick={() => void act(async () => { setChecked(false); setPreviewKey(null); const value = await request<Preview>(`${path}/preview`, selection); setPreview(value); setPreviewKey(JSON.stringify(selection)); })}>核对版本与总占用</Button>
          {preview && <section className="space-y-2 rounded-md border p-3"><p className="text-xs">{current ? "本次分配预览" : "输入已变化，请重新预览"}</p>{preview.proposed.map((row, index) => <p key={index} className="text-xs">{row.part_number} ← {row.source_system} / {row.external_pool_id} · {decimalText(row.quantity)} {row.unit} · {label(row.supply_kind)} / {label(row.quality_status)}</p>)}<label className="block text-xs">分配依据<textarea className={field} maxLength={2048} value={reason} onChange={event => { setReason(event.target.value); setChecked(false); }} /></label><label className="block text-xs"><input type="checkbox" checked={checked} disabled={!current} onChange={event => setChecked(event.target.checked)} /> 已核对本批次、来源、单位和计划用途</label><Button size="sm" disabled={!current || !checked || !reason.trim()} onClick={() => void act(() => apply("allocate"))}>确认计划分配</Button></section>}
        </fieldset>}
        <fieldset disabled={busy || !canEdit} className="space-y-3 rounded-md border p-3"><legend className="px-1 text-sm font-medium">原分配与待领占用 · {data.allocations.length}</legend>
          {!data.allocations.length && <p className="text-xs">暂无占用。</p>}
          {data.allocations.map(allocation => { const source = data.allocation_sources.find(row => row.id === allocation.supply_snapshot_id); return <section key={allocation.id} className="space-y-2 border-b pb-3 text-xs"><p>{allocation.external_item_id} · {allocation.external_pool_id} · 原分配 {decimalText(allocation.quantity)} / 已领 {decimalText(allocation.issued_quantity)} / 待领 {decimalText(allocation.remaining_quantity)} {allocation.unit} · {allocation.revision_id === data.revision?.id ? "当前需求版" : "旧需求版，继续占用原池余量"}</p><p className="break-all">原需求 {allocation.revision_id} · 占用 {allocation.id}</p>{allocation.supply_grant_id && <p><SupplySourceLink projectId={projectId} source={{ document_id: null, source_grant_id: allocation.supply_grant_id }}/></p>}{source && <details><summary className="cursor-pointer">原分配供给依据</summary><SourceBasis source={source} projectId={projectId} /></details>}{canEdit && <label className="block">本次释放量（留空则保留）<input className={field} inputMode="decimal" value={release[allocation.id] ?? ""} onChange={event => { setRelease({ ...release, [allocation.id]: event.target.value }); setReleaseChecked(false); }} /></label>}</section>; })}
          {canEdit && data.allocations.length > 0 && <><label className="block text-xs">释放依据<textarea className={field} maxLength={2048} value={releaseReason} onChange={event => { setReleaseReason(event.target.value); setReleaseChecked(false); }} /></label>{releaseItems.map(item => <p key={item.allocation_id} className="break-all text-xs">释放 {decimalText(item.quantity)} ·{item.allocation_id}</p>)}<label className="block text-xs"><input type="checkbox" checked={releaseChecked} onChange={event => setReleaseChecked(event.target.checked)} /> 已核对逐项释放量；此操作仅减少PDOS计划占用，不代表退库、取消采购或消耗结算</label><Button size="sm" disabled={!releaseItems.length || releaseItems.length > 200 || !releaseReason.trim() || !releaseChecked} onClick={() => void act(() => apply("release"))}>确认释放所列数量</Button>{releaseItems.length > 200 && <p className="text-xs">每次最多释放200项。</p>}</>}
        </fieldset>
        <details><summary className="cursor-pointer text-sm">最近20次分配 / 释放回执</summary><div className="mt-2 space-y-2">{data.history.map(row => <div key={row.id} className="text-xs"><Button size="sm" variant="link" disabled={busy} onClick={() => void act(async () => { setReceipt(await request<Receipt>(`${path}/receipts/${row.id}`)); setReceiptId(row.id); })}>{when(row.created_at)} · {label(row.action)}</Button><p>{row.created_by_user_id} · {row.reason}</p><p className="break-all">{row.id}</p></div>)}<label className="block text-xs">指定历史回执标识<input className={field} value={receiptId} onChange={event => setReceiptId(event.target.value)} /></label><Button size="sm" variant="outline" disabled={busy || !receiptId} onClick={() => void act(async () => setReceipt(await request<Receipt>(`${path}/receipts/${receiptId}`)))}>读取原回执</Button></div></details>
      </>}
      {receipt && <details className="rounded-md border p-3"><summary className="cursor-pointer text-xs">已读取回执 · {label(receipt.action)} · {receipt.id}</summary><p className="text-xs">{when(receipt.created_at)} · {receipt.created_by_user_id} · {receipt.reason}</p><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(receipt.snapshot, null, 2)}</pre></details>}
    </div>
  </details>;
}
