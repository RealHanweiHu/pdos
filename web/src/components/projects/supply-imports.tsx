"use client";

import { useRef, useState } from "react";
import { MaterialReconciliation } from "./material-movements";
import { SupplySharing, SupplyShareOffer } from "./supply-sharing";
import { MaterialExposure } from "./material-exposure";
import { MaterialSupplierAttribution } from "./material-supplier-attribution";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Batch = { id: string; document_id: string; source_system: string; source_version: string; as_of: string; fresh_until: string; captured_at: string; row_count: number; reason: string; created_by_user_id: string; configuration: { coverage: string; authorization_basis: string; sheet: string }; ignored_rows: number[] };
type State = { batches: Batch[]; documents: { id: string; filename: string }[]; has_more: boolean; documents_has_more: boolean; fields: Record<string, string>; now: string };
type Sheet = { name: string; headers: { column: string; label: string }[] };
type Cells = Record<string, { cell: string; value: unknown; type: string }>;
type Supply = { id?: string; external_pool_id: string; external_item_id: string; quantity: string | null; unit: string; supply_kind: string; quality_status: string; expected_date: string | null; lead_time_days: number | null };
type Preview = { document: { id: string; filename: string }; configuration: object; lines: { row: number; values: Supply; raw_cells: Cells }[]; errors: { row: number; message: string; raw_cells: Cells }[]; ignored_rows: number[]; digest: string; stale: boolean };
type Detail = { batch: Batch; items: (Supply & { id: string; source_row: number; raw_cells: Cells })[]; stale: boolean };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const required = ["external_pool_id", "external_item_id", "quantity", "unit", "supply_kind", "quality_status"];
const kind: Record<string, string> = { on_hand: "现货", expected_receipt: "预计到货" };
const quality: Record<string, string> = { released: "已放行", frozen: "冻结", unknown: "未知" };
const when = (value: string) => new Date(value).toLocaleString();
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const result: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(result) && isRecord(result.detail) && typeof result.detail.message === "string" ? result.detail.message : "供给资料暂不可用，请刷新核对");
  return result as T;
}
function SourceCells({ cells }: { cells: Cells }) { return <details><summary className="cursor-pointer text-xs">原单元格</summary>{Object.entries(cells).map(([key, cell]) => <p key={key} className="break-all text-xs">{cell.cell}：{String(cell.value ?? "（空）")}</p>)}</details>; }
function SupplyRows({ items, projectId }: { projectId?: string; items: { row: number; values: Supply; raw_cells: Cells }[] }) {
  const [limit, setLimit] = useState(50);
  return <div className="space-y-2"><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">原行 / 供给池 / 物料</th><th className="p-2">可分配数量 / 单位</th><th className="p-2">类型 / 质量</th><th className="p-2">预计到货 / 交期</th><th className="p-2">出处</th></tr></thead><tbody>{items.slice(0, limit).map(({ row, values, raw_cells }) => <tr className="border-t align-top" key={row}><td className="p-2">#{row} · {values.external_pool_id}<p>{values.external_item_id}</p></td><td className="p-2">{values.quantity === null ? "数量未知" : values.quantity} {values.unit}</td><td className="p-2">{kind[values.supply_kind] ?? values.supply_kind}<p>{quality[values.quality_status] ?? values.quality_status}</p></td><td className="p-2">{values.expected_date || "日期未提供"}<p>{values.lead_time_days === null ? "交期未提供" : `${values.lead_time_days} 天`}</p></td><td className="p-2"><SourceCells cells={raw_cells} />{projectId && values.id && <><MaterialSupplierAttribution projectId={projectId} sourceId={values.id}/><SupplyShareOffer projectId={projectId} sourceId={values.id}/><MaterialReconciliation projectId={projectId} sourceId={values.id}/></>}</td></tr>)}</tbody></table></div>{limit < items.length && <Button size="sm" variant="outline" onClick={() => setLimit(limit + 50)}>继续查看 · 已显示 {limit} / {items.length} 行</Button>}</div>;
}

export function SupplyImports({ projectId, canEdit }: { projectId: string; canEdit: boolean }) {
  const [data, setData] = useState<State | null>(null), [detail, setDetail] = useState<Detail | null>(null);
  const [historyId, setHistoryId] = useState("");
  const [documentId, setDocumentId] = useState(""), [sheets, setSheets] = useState<Sheet[]>([]), [sheet, setSheet] = useState("");
  const [columns, setColumns] = useState<Record<string, string>>({}), [headerRow, setHeaderRow] = useState("1");
  const [source, setSource] = useState(""), [version, setVersion] = useState(""), [coverage, setCoverage] = useState("");
  const [authorization, setAuthorization] = useState(""), [asOf, setAsOf] = useState(""), [freshUntil, setFreshUntil] = useState("");
  const [reason, setReason] = useState(""), [checked, setChecked] = useState(false), [preview, setPreview] = useState<Preview | null>(null);
  const [previewKey, setPreviewKey] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const ids = useRef(new Map<string, string>());
  const path = `/api/projects/${projectId}/npi/supply-imports`;
  function body() {
    if (!asOf || !freshUntil || !Number.isFinite(new Date(asOf).valueOf()) || !Number.isFinite(new Date(freshUntil).valueOf())) throw new Error("请填写来源数据时点和有效期");
    return { document_id: documentId, source_system: source, source_version: version, coverage, authorization_basis: authorization, as_of: new Date(asOf).toISOString(), fresh_until: new Date(freshUntil).toISOString(), sheet, header_row: Number(headerRow), columns };
  }
  const inputsKey = JSON.stringify({ documentId, source, version, coverage, authorization, asOf, freshUntil, sheet, headerRow, columns });
  const current = previewKey === inputsKey;
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "供给资料未完成"); } finally { setBusy(false); } }
  async function load() { setData(await request<State>(path)); }
  function chooseSheet(name: string, choices = sheets) {
    setSheet(name); setChecked(false); setPreviewKey(null);
    const guessed: Record<string, string> = {};
    for (const [key, label] of Object.entries(data?.fields ?? {})) {
      const header = choices.find(item => item.name === name)?.headers.find(item => item.label.trim() === key || item.label.trim() === label);
      if (header) guessed[key] = header.column;
    }
    setColumns(guessed);
  }
  async function inspect() {
    setPreview(null); setPreviewKey(null); setChecked(false);
    const value = await request<{ sheets: Sheet[] }>(`${path}/inspect`, { document_id: documentId });
    setSheets(value.sheets); chooseSheet(value.sheets[0]?.name ?? "", value.sheets);
  }
  async function prepare() {
    setChecked(false); setPreviewKey(null); setNotice(null);
    setPreview(await request<Preview>(`${path}/preview`, body())); setPreviewKey(inputsKey);
  }
  async function confirm() {
    if (!preview || !current || preview.errors.length || !checked) return;
    const payload = { ...body(), expected_digest: preview.digest, reason };
    const signature = JSON.stringify(payload); let requestId = ids.current.get(signature);
    if (!requestId) { requestId = crypto.randomUUID(); ids.current.set(signature, requestId); }
    try {
      const saved = await request<Batch>(`${path}/confirm`, { ...payload, request_id: requestId });
      setNotice("供给快照已记录或复用原记录，未写回ERP。原时点、映射及单元格出处已保留。");
      setDetail(await request<Detail>(`${path}/${saved.id}`)); await load(); setPreview(null); setChecked(false);
    } catch (failure) { setNotice(`请刷新实际记录核对结果；相同输入重试沿用请求 ${requestId}。`); throw failure; }
  }
  const selectedSheet = sheets.find(value => value.name === sheet);
  return <section className="space-y-4"><SupplySharing projectId={projectId}/><MaterialExposure projectId={projectId}/><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">物料·供应</h2><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>读取当前资料</Button></div><p className="text-sm text-muted-foreground">从项目已保存的XLSX原件登记有时点的供给快照。库存/采购真值仍归ERP；在试制批次中可明确分配、释放计划占用并核对固定需求齐套。完整短缺、消耗结算及交期评估继续接入。</p><p className="text-xs"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents`}>上传或查看供给原件</a> · <a className="text-primary underline" href={`/projects?project=${projectId}&tab=quality`}>查看试制批次需求、分配与齐套</a></p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    {data && <><section className="space-y-2"><h3 className="font-medium">已记录供给快照</h3>{data.batches.length === 0 && <p className="text-sm">暂无供给数据；缺失不能按零库存或已齐套处理。</p>}{data.batches.map(batch => <div key={batch.id} className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm"><span>{batch.source_system} · {batch.source_version} · {batch.row_count} 行</span><span className="text-xs text-muted-foreground">数据截至 {when(batch.as_of)} · 有效至 {when(batch.fresh_until)} · {new Date(batch.fresh_until) <= new Date(data.now) ? "读取时已过期" : "读取时在有效期内"}</span><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => setDetail(await request<Detail>(`${path}/${batch.id}`)))}>查看原行</Button></div>)}{data.has_more && <div className="flex flex-wrap items-end gap-2 text-xs"><label>显示最近50次记录，查找历史记录标识<input className={field} value={historyId} onChange={event => setHistoryId(event.target.value)} /></label><Button size="sm" variant="outline" disabled={busy || !/^[0-9a-f-]{36}$/i.test(historyId)} onClick={() => void act(async () => setDetail(await request<Detail>(`${path}/${historyId}`)))}>读取历史记录</Button></div>}</section>
    {canEdit && <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">从原件准备供给快照</summary><fieldset disabled={busy} className="mt-3 space-y-3"><label className="block text-xs">项目XLSX原件<select className={field} value={documentId} onChange={event => { setDocumentId(event.target.value); setSheets([]); setPreview(null); setChecked(false); }}><option value="">选择已有原件</option>{data.documents.map(document => <option key={document.id} value={document.id}>{document.filename}</option>)}</select></label>{data.documents_has_more && <label className="block text-xs">最近200份以外的原件标识<input className={field} value={documentId} onChange={event => { setDocumentId(event.target.value); setSheets([]); setPreview(null); }} /></label>}<Button size="sm" variant="outline" disabled={!documentId} onClick={() => void act(inspect)}>读取工作表与列</Button>
    {sheets.length > 0 && <><div className="grid gap-2 sm:grid-cols-2"><label className="text-xs">工作表<select className={field} value={sheet} onChange={event => chooseSheet(event.target.value)}>{sheets.map(item => <option key={item.name}>{item.name}</option>)}</select></label><label className="text-xs">表头行号（其后为数据）<input className={field} type="number" min="1" max="100" value={headerRow} onChange={event => setHeaderRow(event.target.value)} /></label></div><p className="text-xs">列标签显示首行内容，按原列字母核对；本次最多2000个数据行、100列。只映射所选字段，原件完整保留。</p><div className="grid gap-2 sm:grid-cols-2">{Object.entries(data.fields).map(([key, label]) => <label key={key} className="text-xs">{label}{required.includes(key) ? "（必需列）" : "（可选）"}<select className={field} value={columns[key] ?? ""} onChange={event => { const next = { ...columns }; if (event.target.value) next[key] = event.target.value; else delete next[key]; setColumns(next); setChecked(false); }}><option value="">不映射</option>{selectedSheet?.headers.map(header => <option key={header.column} value={header.column}>{header.column} · {header.label || "首行为空"}</option>)}</select></label>)}</div><p className="text-xs">供给池填写库位/批号/采购行的稳定标识。同池同物料不能重复；数量为空表示未知，0为真实零。类型使用“现货/预计到货”，质量使用“已放行/冻结/未知”（或对应英文值）；质量空值按未知。日期列为预计日期，不代表实际到货。</p>
    <div className="grid gap-2 sm:grid-cols-2"><label className="text-xs">来源系统标识<input className={field} maxLength={128} pattern="[a-zA-Z0-9_.:-]+" value={source} onChange={event => setSource(event.target.value)} placeholder="ERP来源的固定标识" /></label><label className="text-xs">导出批次/版本编号（来源内唯一）<input className={field} maxLength={256} value={version} onChange={event => setVersion(event.target.value)} /></label><label className="text-xs">来源数据截至时点（本地时间）<input className={field} type="datetime-local" value={asOf} onChange={event => setAsOf(event.target.value)} /></label><label className="text-xs">数据有效至（本地时间）<input className={field} type="datetime-local" value={freshUntil} onChange={event => setFreshUntil(event.target.value)} /></label></div><label className="block text-xs">导出范围与未覆盖部分<textarea className={field} maxLength={2048} value={coverage} onChange={event => setCoverage(event.target.value)} /></label><label className="block text-xs">原件来源、使用授权及负责人核对依据<textarea className={field} maxLength={2048} value={authorization} onChange={event => setAuthorization(event.target.value)} /></label><Button size="sm" variant="outline" disabled={!source.trim() || !version.trim() || !coverage.trim() || !authorization.trim() || !asOf || !freshUntil || !required.every(key => columns[key])} onClick={() => void act(prepare)}>预览原行与规范值</Button></>}
    {preview && <section className="space-y-3 rounded-md border p-3"><h4 className="font-medium">{preview.document.filename} · {preview.lines.length} 有效行 / {preview.errors.length} 错误行{!current && " · 输入已变化，须重新预览"}</h4><p className="text-xs">{preview.stale ? "该资料已过有效期，仅作为历史时点记录。" : "当前在人工给定的有效期内，不代表实时库存。"}映射字段为空的行共忽略 {preview.ignored_rows.length} 行。</p>{preview.ignored_rows.length > 0 && <details><summary className="cursor-pointer text-xs">查看忽略行号</summary><p className="break-all text-xs">{preview.ignored_rows.join("、")}</p></details>}<SupplyRows key={preview.digest} items={preview.lines} />{preview.errors.length > 0 && <details open><summary className="cursor-pointer text-sm text-destructive">先修正全部原行错误，再确认</summary>{preview.errors.map(row => <div key={row.row} className="my-2 text-xs"><p className="whitespace-pre-wrap">原行 {row.row}：{row.message}</p><SourceCells cells={row.raw_cells} /></div>)}</details>}<label className="block text-xs">本次确认说明<textarea className={field} maxLength={2048} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="flex gap-2 text-xs"><input type="checkbox" checked={current && checked} disabled={!current || preview.errors.length > 0} onChange={event => setChecked(event.target.checked)} />已核对原件、导出范围、时点/有效期、映射、数量/单位及忽略行，确认保存此供给快照</label><Button size="sm" disabled={!current || !checked || !!preview.errors.length || !reason.trim()} onClick={() => void act(confirm)}>确认记录快照</Button></section>}
    </fieldset></details>}</>}
    {detail && <section className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">{detail.batch.source_system} · {detail.batch.source_version} · {detail.stale ? "已过期" : "读取时在有效期内"}</h3><p className="text-xs">数据时点 {when(detail.batch.as_of)} · 有效至 {when(detail.batch.fresh_until)} · 记录于 {when(detail.batch.captured_at)}</p><p className="whitespace-pre-wrap text-xs">导出范围：{detail.batch.configuration.coverage}</p><p className="whitespace-pre-wrap text-xs">来源授权：{detail.batch.configuration.authorization_basis}</p><p className="text-xs">记录人 {detail.batch.created_by_user_id} · {detail.batch.reason} · 记录标识 {detail.batch.id}</p><a className="text-xs text-primary underline" href={`/api/document-previews/projects/${projectId}/${detail.batch.document_id}/original`}>下载核对原件 · {detail.batch.configuration.sheet}</a><SupplyRows projectId={projectId} key={detail.batch.id} items={detail.items.map(item => ({ row: item.source_row, values: item, raw_cells: item.raw_cells }))} /></section>}
  </section>;
}
