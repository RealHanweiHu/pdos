"use client";

import { useRef, useState } from "react";
import { IssueIntakeCorrectionBatches } from "@/components/projects/issue-intake-correction-batches";
import { IssueIntakeCompensations } from "@/components/projects/issue-intake-compensations";
import { IssueIntakeConfirmation } from "./issue-intake-confirmation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const fields = { title: "标题（必填）", description: "问题说明", external_ref: "历史编号", source_state: "历史状态", root_cause: "历史原因", resolution: "历史处理记录", target_date: "目标日期" };
type Field = keyof typeof fields;
type Mapping = { sheet: string; first_row: number; last_row: number; date_format: string } & Record<Field, string | null>;
type Source = { id: string; filename: string; sheets: string[] };
type History = { id: string; created_at: string; purpose: string };
type Row = { row: number; locator: string; original: Record<string, { cell: string; value: string }>; proposed: Record<string, string | null>; historical_state: string | null; external_ref: string | null; errors: string[] };
type Preview = { project_id: string; request_digest: string; confirmation_receipts: unknown[]; id: string; attachment_id: string; created_at: string; created_by_user_id: string; permission_basis: string; purpose: string; mapping: Mapping; rows: Row[]; source_current: boolean; source_snapshot: { filename: string; sha256: string } };
const blank = (): Mapping => ({ sheet: "", first_row: 2, last_row: 2, date_format: "YYYY-MM-DD", title: "A", description: null, external_ref: null, source_state: null, root_cause: null, resolution: null, target_date: null });
function obj(v: unknown): Record<string, unknown> { if (!isRecord(v)) throw new Error("导入资料不完整"); return v; }
function str(v: unknown): string { if (typeof v !== "string") throw new Error("导入文字不完整"); return v; }
function arr(v: unknown): unknown[] { if (!Array.isArray(v)) throw new Error("导入清单不完整"); return v; }
function nullable(v: unknown): string | null { return v == null ? null : str(v); }
function mapping(v: unknown): Mapping {
  const m = obj(v), result = blank();
  result.sheet = str(m.sheet); result.first_row = Number(m.first_row); result.last_row = Number(m.last_row); result.date_format = str(m.date_format);
  for (const key of Object.keys(fields) as Field[]) result[key] = nullable(m[key]);
  return result;
}
function preview(v: unknown): Preview {
  const p = obj(v), source = obj(p.source_snapshot);
  return { project_id: str(p.project_id), request_digest: str(p.request_digest), confirmation_receipts: Array.isArray(p.confirmation_receipts) ? p.confirmation_receipts : [], id: str(p.id), attachment_id: str(p.attachment_id), created_at: str(p.created_at), created_by_user_id: str(p.created_by_user_id), permission_basis: str(p.permission_basis), purpose: str(p.purpose), mapping: mapping(p.mapping), source_current: p.source_current === true, source_snapshot: { filename: str(source.filename), sha256: str(source.sha256) }, rows: arr(p.rows).map(value => {
    const r = obj(value);
    return { row: Number(r.row), locator: str(r.locator), original: Object.fromEntries(Object.entries(obj(r.original)).map(([key, value]) => { const cell = obj(value); return [key, { cell: str(cell.cell), value: str(cell.value) }]; })), proposed: Object.fromEntries(Object.entries(obj(r.proposed)).map(([key, value]) => [key, nullable(value)])), historical_state: nullable(r.historical_state), external_ref: nullable(r.external_ref), errors: arr(r.errors).map(str) };
  }) };
}
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "问题清单办理未完成，请核对输入或刷新已保存草稿");
  return value;
}
const inputClass = "w-full rounded-md border bg-background p-2 text-sm";
export function ConversationIssueIntake({ conversationId, messageId, archived }: { conversationId: string; messageId: string; archived: boolean }) {
  const [loaded, setLoaded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[]>([]), [history, setHistory] = useState<History[]>([]);
  const [attachment, setAttachment] = useState(""), [map, setMap] = useState<Mapping>(blank);
  const [permission, setPermission] = useState(""), [purpose, setPurpose] = useState("");
  const [current, setCurrent] = useState<Preview | null>(null), [page, setPage] = useState(0);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/conversations/${conversationId}`, listPath = `${base}/messages/${messageId}/issue-intake-previews`;
  async function refresh() {
    const value = obj(await request(listPath));
    setSources(arr(value.sources).map(v => { const s = obj(v); return { id: str(s.id), filename: str(s.filename), sheets: arr(s.sheets).map(str) }; }));
    setHistory(arr(value.items).map(v => { const h = obj(v); return { id: str(h.id), created_at: str(h.created_at), purpose: str(h.purpose) }; })); setLoaded(true);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "问题清单暂不可用"); } finally { setBusy(false); } }
  async function open(id: string) { const p = preview(await request(`${base}/issue-intake-previews/${id}`)); setCurrent(p); setPage(0); }
  async function prepare() {
    const body = { attachment_id: attachment, mapping: map, permission_basis: permission.trim(), purpose: purpose.trim() }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const p = preview(await request(listPath, { ...body, request_id: pending.current.id }));
    setCurrent(p); setPage(0); pending.current = null; await refresh(); await open(p.id);
  }
  const source = sources.find(s => s.id === attachment);
  const valid = !!source && source.sheets.includes(map.sheet) && !!map.title && !!permission.trim() && !!purpose.trim() && Number.isInteger(map.first_row) && Number.isInteger(map.last_row) && map.first_row >= 1 && map.last_row <= 1048576 && map.last_row >= map.first_row && map.last_row - map.first_row < 200 && (Object.keys(fields) as Field[]).every(key => !map[key] || /^[A-Z]{1,3}$/.test(map[key]!));
  return <details className="rounded-lg border bg-background p-3" onToggle={e => { if (e.currentTarget.open && !loaded && !busy) void act(refresh); }}>
    <summary className="cursor-pointer text-sm font-medium">核对这条消息的问题清单</summary>
    <div className="mt-3 space-y-4">
      <p className="text-xs text-muted-foreground">选择已抽取的内部XLSX，填写工作表、数据行及列字母。保存不可变映射草稿后可继续调整并生成新稿。保存映射不代表已导入；核对后可在下方选行确认，并读取实际回执。历史状态及原因记录保留供核对。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await refresh(); if (current) await open(current.id); })}>刷新来源与已保存草稿</Button>
      {loaded && !sources.length && <p className="text-xs">本条消息暂无可用的内部XLSX，请先完成上方附件抽取。</p>}
      {!archived && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(prepare); }}>
        <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs">原问题清单<select className={inputClass} value={attachment} onChange={e => { setAttachment(e.target.value); setMap(m => ({ ...m, sheet: "" })); }}><option value="">选择本条消息的文件</option>{sources.map(s => <option key={s.id} value={s.id}>{s.filename}</option>)}</select></label>
          <label className="text-xs">工作表<select className={inputClass} value={map.sheet} onChange={e => setMap(m => ({ ...m, sheet: e.target.value }))}><option value="">选择工作表</option>{source?.sheets.map(s => <option key={s}>{s}</option>)}</select></label>
          <label className="text-xs">首个数据行<input className={inputClass} type="number" min={1} max={1048576} value={map.first_row} onChange={e => setMap(m => ({ ...m, first_row: Number(e.target.value) }))}/></label>
          <label className="text-xs">最后数据行（每批最多200行）<input className={inputClass} type="number" min={map.first_row} max={Math.min(1048576, map.first_row + 199)} value={map.last_row} onChange={e => setMap(m => ({ ...m, last_row: Number(e.target.value) }))}/></label>
          {(Object.entries(fields) as [Field, string][]).map(([key, label]) => <label key={key} className="text-xs">{label}列<input className={inputClass} placeholder={key === "title" ? "例如 A" : "留空表示不映射"} maxLength={3} value={map[key] ?? ""} onChange={e => setMap(m => ({ ...m, [key]: e.target.value.toUpperCase().trim() || null }))}/></label>)}
          <label className="text-xs">原日期格式<select className={inputClass} value={map.date_format} onChange={e => setMap(m => ({ ...m, date_format: e.target.value }))}>{["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY"].map(f => <option key={f}>{f}</option>)}</select></label>
          <label className="text-xs">资料使用许可依据<textarea className={inputClass} maxLength={2000} value={permission} onChange={e => setPermission(e.target.value)} placeholder="填写资料授权人或原许可依据"/></label>
          <label className="text-xs">本次使用目的<textarea className={inputClass} maxLength={2000} value={purpose} onChange={e => setPurpose(e.target.value)}/></label>
        </fieldset>
        <Button size="sm" disabled={busy || !valid}>保存映射并查看逐行草稿</Button>
      </form>}
      {history.length > 0 && <label className="block text-xs">已保存草稿（最近100份）<select className={inputClass} disabled={busy} value={current?.id ?? ""} onChange={e => { if (e.target.value) void act(() => open(e.target.value)); }}><option value="">选择历史草稿</option>{history.map(h => <option key={h.id} value={h.id}>{new Date(h.created_at).toLocaleString("zh-CN")} · {h.purpose}</option>)}</select></label>}
      {current && <section className="space-y-3 rounded-lg border p-3">
        <p className="text-sm font-medium">映射与逐行核对{current.confirmation_receipts.length ? " · 已有确认回执" : " · 尚未导入问题"} · {current.rows.length}行 · {current.rows.filter(r => r.errors.length).length}行待修正</p>
        <p className="break-all text-xs">{current.source_snapshot.filename} · {current.mapping.sheet} · 第{current.mapping.first_row}–{current.mapping.last_row}行<br/>文件摘要：{current.source_snapshot.sha256}</p>
        <p className="text-xs">{new Date(current.created_at).toLocaleString("zh-CN")} · 保存人：{current.created_by_user_id}<br/>许可依据：{current.permission_basis}<br/>使用目的：{current.purpose}</p>
        <p className="text-xs">列映射：{(Object.keys(fields) as Field[]).filter(key => current.mapping[key]).map(key => `${fields[key]}=${current.mapping[key]}`).join("；")} · 日期：{current.mapping.date_format}</p>
        {!current.source_current && <p role="alert" className="text-xs text-destructive">附件已撤回、不可用或抽取内容已变化，历史回执保留；继续导入须重新准备有效来源。</p>}
        {!archived && <Button size="sm" variant="outline" disabled={busy} onClick={() => { setAttachment(current.attachment_id); setMap({ ...current.mapping }); setPermission(current.permission_basis); setPurpose(current.purpose); }}>将此稿映射载入编辑区</Button>}
        <p className="text-xs text-muted-foreground">下方原值来自已抽取文字；格式、合并单元格和公式结果须回看上方原件。空行与无法转换的日期均保留为待修正项。</p>
        {current.rows.slice(page * 20, page * 20 + 20).map(r => <article key={r.row} className="space-y-2 rounded-md border p-3">
          <p className="text-sm font-medium">第{r.row}行 · {r.proposed.title || "缺少标题"}</p>
          <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">字段 / 单元格</th><th className="p-2">抽取原值</th><th className="p-2">拟录入值 / 历史信息</th></tr></thead><tbody>{Object.entries(r.original).map(([key, cell]) => <tr key={key} className="border-t"><td className="p-2 align-top">{fields[key as Field] ?? key} · {cell.cell}</td><td className="max-w-96 whitespace-pre-wrap break-words p-2 align-top">{cell.value || "空"}</td><td className="max-w-96 whitespace-pre-wrap break-words p-2 align-top">{(key === "source_state" ? r.historical_state : key === "external_ref" ? r.external_ref : r.proposed[key]) ?? "未提供"}{key === "source_state" ? "（仅历史记录）" : ""}</td></tr>)}</tbody></table></div>
          <p className="text-xs">新问题起始状态：开放</p>
          {r.errors.length > 0 && <ul className="list-disc pl-4 text-xs text-destructive">{r.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        </article>)}
        {current.rows.length > 20 && <div className="flex items-center gap-3 text-xs"><Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</Button><span>{page + 1} / {Math.ceil(current.rows.length / 20)}</span><Button size="sm" variant="outline" disabled={(page + 1) * 20 >= current.rows.length} onClick={() => setPage(p => p + 1)}>下一页</Button></div>}
        <IssueIntakeConfirmation key={current.id} conversationId={conversationId} previewId={current.id} digest={current.request_digest} rows={current.rows} receipts={current.confirmation_receipts} disabled={archived || !current.source_current || busy} onRefresh={() => open(current.id)}/>
        <IssueIntakeCorrectionBatches projectId={current.project_id} sourceIds={[...new Set(current.confirmation_receipts.filter(isRecord).flatMap(receipt => isRecord(receipt.current_sources) ? Object.values(receipt.current_sources).filter(isRecord).filter(source => typeof source.source_row_id === "string").map(source => String(source.source_row_id)) : []))]} disabled={archived || busy} onChanged={() => open(current.id)}/>
        <IssueIntakeCompensations projectId={current.project_id} sourceIds={[...new Set(current.confirmation_receipts.filter(isRecord).flatMap(receipt => isRecord(receipt.current_sources) ? Object.values(receipt.current_sources).filter(isRecord).filter(source => Number(source.revision) > 0 && typeof source.source_row_id === "string").map(source => String(source.source_row_id)) : []))]}/>
      </section>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  </details>;
}
