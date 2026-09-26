"use client";

import { useRef, useState } from "react";
import { IssueIntakeReuse, type IssueReuseChoice, type IntakeSourceRow } from "./issue-intake-reuse";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Result = { current: Record<string, unknown> | null; reason: string | null; row: number; status: string; errors: string[]; issueHref: string | null; documentHref: string | null };
type Receipt = { id: string; time: string; actor: string; results: Result[] };
function parse(value: unknown): Receipt {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.created_at !== "string" || !Array.isArray(value.results)) throw new Error("确认回执不完整，请刷新原草稿");
  const sources = isRecord(value.current_sources) ? value.current_sources : {};
  return { id: value.id, time: value.created_at, actor: String(value.created_by_user_id), results: value.results.map(v => {
    if (!isRecord(v) || typeof v.row !== "number" || typeof v.status !== "string" || !Array.isArray(v.errors)) throw new Error("逐行回执不完整");
    const currentSource = sources[String(v.row)];
    return { current: isRecord(currentSource) ? currentSource : null, reason: typeof v.reuse_reason === "string" ? v.reuse_reason : null, row: v.row, status: v.status, errors: v.errors.map(String), issueHref: typeof v.issue_href === "string" && v.issue_href.startsWith("/projects?") ? v.issue_href : null, documentHref: typeof v.document_href === "string" && v.document_href.startsWith("/projects?") ? v.document_href : null };
  }) };
}
export function IssueIntakeConfirmation({ conversationId, previewId, digest, rows, receipts, disabled, onRefresh, onBusyChange }: { conversationId: string; previewId: string; digest: string; rows: IntakeSourceRow[]; receipts: unknown[]; disabled: boolean; onRefresh: () => Promise<void>; onBusyChange?: (busy: boolean) => void }) {
  const [selected, setSelected] = useState<number[]>([]), [issueType, setIssueType] = useState("engineering"), [severity, setSeverity] = useState("medium");
  const [reviewed, setReviewed] = useState(false), [publish, setPublish] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState<Record<number, boolean>>({});
  const [reuse, setReuse] = useState<Record<number, IssueReuseChoice | undefined>>({});
  const [latest, setLatest] = useState<Receipt | null>(null);
  const pending = useRef<{ signature: string; requestId: string } | null>(null);
  const stored = receipts.map(parse), all = latest && !stored.some(r => r.id === latest.id) ? [latest, ...stored] : stored;
  const done = new Set(all.flatMap(r => r.results.filter(item => ["created", "linked", "reused"].includes(item.status)).map(item => item.row)));
  const unavailable = disabled || busy;
  const reuseBusy = selected.some(row => reading[row]);
  const choicesValid = selected.every(row => !reuse[row] || !!reuse[row]?.target && !!reuse[row]?.reason.trim());
  async function confirm() {
    setBusy(true); onBusyChange?.(true); setError(null);
    const reuseItems = selected.filter(row => reuse[row]?.target).map(row => ({ row, issue_id: reuse[row]!.target!.id, expected_updated_at: reuse[row]!.target!.updated_at, reason: reuse[row]!.reason.trim() })).sort((a, b) => a.row - b.row);
    const body = { ...(reuseItems.length ? { reuse: reuseItems } : {}), rows: [...selected].sort((a, b) => a - b), expected_digest: digest, issue_type: issueType, severity, publish_to_project: true, reviewed: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, requestId: crypto.randomUUID() };
    try {
      const response = await fetch(`/api/conversations/${conversationId}/issue-intake-previews/${previewId}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, request_id: pending.current.requestId }) });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "确认未完成，请刷新回执；重试相同选择会复用原请求");
      setLatest(parse(value)); pending.current = null; setSelected([]); setReviewed(false); setPublish(false); await onRefresh();
    } catch (e) { setError(e instanceof Error ? e.message : "确认未完成"); } finally { setBusy(false); onBusyChange?.(false); }
  }
  return <section className="space-y-3 border-t pt-3">
    <p className="text-sm font-medium">批量确认 · 当前草稿已登记或复用{done.size} / {rows.length}行</p>
    {!disabled && <>
      <p className="text-xs text-muted-foreground">先核对上方逐行原值，再选择本次录入行。同原件同一来源位置已导入会复用原问题；映射值或分类不同会返回待核对项。跨文件的相似内容可在下方逐行选择原问题并说明依据。负责人、验证人、样机和关闭条件可进入原问题继续补齐。</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={unavailable} onClick={() => { setSelected(rows.filter(r => !r.errors.length && !done.has(r.row)).map(r => r.row)); setReviewed(false); }}>选择未登记且无错误的行</Button><Button size="sm" variant="outline" disabled={unavailable} onClick={() => { setSelected([]); setReviewed(false); }}>清空选择</Button></div>
      <fieldset disabled={unavailable} className="flex max-h-44 flex-wrap gap-3 overflow-y-auto rounded-md border p-3">{rows.map(r => <label key={r.row} className="flex gap-1 text-xs"><input type="checkbox" checked={selected.includes(r.row)} disabled={done.has(r.row)} onChange={e => { setSelected(s => e.target.checked ? [...s, r.row] : s.filter(n => n !== r.row)); setReviewed(false); }}/>第{r.row}行{done.has(r.row) ? "（已登记/复用）" : r.errors.length ? "（待修正）" : ""}</label>)}</fieldset>
      <div className="flex flex-wrap gap-3 text-xs"><label>新建问题类型<select className="ml-2 rounded-md border bg-background p-2" disabled={unavailable} value={issueType} onChange={e => { setIssueType(e.target.value); setReviewed(false); }}>{Object.entries({ engineering: "工程", quality: "质量", supplier: "供应商", test_failure: "测试失败", certification: "认证" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label>严重度<select className="ml-2 rounded-md border bg-background p-2" disabled={unavailable} value={severity} onChange={e => { setSeverity(e.target.value); setReviewed(false); }}>{Object.entries({ low: "低", medium: "中", high: "高", critical: "严重" }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
      {rows.filter(row => selected.includes(row.row)).map(row => <IssueIntakeReuse key={row.row} base={`/api/conversations/${conversationId}/issue-intake-previews/${previewId}`} row={row} value={reuse[row.row]} disabled={unavailable} onBusyChange={busy => setReading(old => ({ ...old, [row.row]: busy }))} onChange={value => { setReuse(old => ({ ...old, [row.row]: value })); setReviewed(false); }}/>) }
      <p className="text-xs">人工关联的行保留所选问题当前类型、严重度和状态；上方类型、严重度仅用于新建问题。</p>
      <p className="text-xs">本次选择{selected.length}行；所选错行会保留错误回执，无错误行继续录入。未选行留在草稿中，可分批办理。</p>
      <label className="flex gap-2 text-xs"><input type="checkbox" disabled={unavailable} checked={publish} onChange={e => setPublish(e.target.checked)}/>同意将完整原文件及所选行的许可、用途、映射和确认记录登记到本项目，供有权限成员核对。停止私人附件引用不会撤销已登记的项目资料。</label>
      <label className="flex gap-2 text-xs"><input type="checkbox" disabled={unavailable || reuseBusy} checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已核对所选行原值、目标日期、类型和严重度；新问题以开放状态登记，人工关联行已核对原问题内容及对应依据，历史状态保留为来源。</label>
      <Button size="sm" disabled={unavailable || !selected.length || !publish || !reviewed || !choicesValid || reuseBusy} onClick={() => void confirm()}>{busy ? "正在确认，请保留此页…" : `确认录入所选${selected.length}行`}</Button>
    </>}
    {all.map(receipt => <details key={receipt.id} open className="rounded-md border p-3"><summary className="text-xs">{new Date(receipt.time).toLocaleString("zh-CN")} · 新建{receipt.results.filter(r => r.status === "created").length} / 关联已有{receipt.results.filter(r => r.status === "linked").length} / 精确复用{receipt.results.filter(r => r.status === "reused").length} / 待处理{receipt.results.filter(r => r.status === "error").length}</summary><p className="mt-2 break-all text-xs">确认人：{receipt.actor}</p><ul className="mt-2 space-y-2 text-xs">{receipt.results.map(result => <li key={result.row}>第{result.row}行：{({ created: "已新建开放问题", linked: "已关联原问题并保留当前内容及状态", reused: "已复用原问题，未改写当前内容或状态", error: "未录入" } as Record<string, string>)[result.status] ?? result.status}{result.issueHref && <a className="ml-2 text-primary underline" href={result.issueHref}>办理原问题</a>}{result.documentHref && <a className="ml-2 text-primary underline" href={result.documentHref}>查看项目原件</a>}{result.current && Number(result.current.revision) > 0 && <p className="text-destructive">原回执保留；此来源后续{result.current.state === "withdrawn" ? "已撤回关联" : "已重新关联"}（版本 {String(result.current.revision)}）。{typeof result.current.current_issue_href === "string" && result.current.current_issue_href.startsWith("/projects?") && <a className="ml-2 underline" href={result.current.current_issue_href}>当前关联问题</a>}</p>}{result.reason && <p>关联依据：{result.reason}</p>}{result.errors.map((e, i) => <p key={i} className="text-destructive">{e}</p>)}</li>)}</ul></details>)}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
