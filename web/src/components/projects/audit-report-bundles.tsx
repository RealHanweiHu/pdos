"use client";

import { useRef, useState } from "react";
import { AuditBundleManifest } from "./audit-bundle-manifest";
import { Button } from "@/components/ui/button";
import { field, obj, rows, text, type Row } from "@/components/quality/fmea-sources";

export function AuditReportBundles({ projectId, reportId, withdrawn }: { projectId: string; reportId: string; withdrawn: boolean }) {
  const [preview, setPreview] = useState<Row | null>(null), [history, setHistory] = useState<Row | null>(null);
  const [reason, setReason] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const requestIds = useRef(new Map<string, string>());
  const base = "/api/project-reports/" + projectId;
  const stopped = withdrawn || history?.withdrawal != null;
  async function request(path: string, body: unknown): Promise<Row> {
    const response = await fetch(base + "/" + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(text(obj(obj(value).detail).message) || text(obj(value).message) || "附件包操作未完成");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "附件包暂不可用"); } finally { setBusy(false); } }
  async function loadHistory(before?: string) { const value = await request("bundle-history", { report_id: reportId, before_id: before ?? null }); setHistory(old => before ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
  async function save() {
    const body = { report_id: reportId, expected_digest: preview?.digest, reason }, key = JSON.stringify(body);
    let requestId = requestIds.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); requestIds.current.set(key, requestId); }
    await request("bundle-save", { ...body, request_id: requestId }); setNotice("报告、全部所选原件和条款清单已组包保存，仅供内部审阅。未作客户披露批准或外发。"); setPreview(null); await loadHistory();
  }
  return <details className="space-y-3 rounded-md border p-3 text-sm">
    <summary className="cursor-pointer font-medium">报告与完整原件打包</summary>
    <p className="text-muted-foreground">只加入本报告条款明确选择的项目文件；引用位置不会裁切原件。Gate、ECN 中间接提到的其他文件不自动加入。单文件最多 20 MiB，报告与原件合计最多 50 MiB。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    {stopped && <p className="text-primary">原报告已撤回，相关附件包停止生成与下载；历史清单保留。</p>}
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || stopped} onClick={() => void act(async () => setPreview(await request("bundle-preview", { report_id: reportId })))}>预览原件范围与大小</Button><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory())}>查看已保存附件包</Button></div>
    {preview && !stopped && <section className="space-y-3 rounded-md bg-muted/30 p-3">
      <p className="font-medium">原报告 + {rows(preview.documents).length} 份完整原件 · 合计 {(Number(preview.source_size_bytes) / 1048576).toFixed(2)} MiB</p>
      <a className="inline-flex min-h-11 items-center underline" href={base + "/" + reportId + "/download"}>回看将装入的原报告</a>
      {!rows(preview.documents).length && <p>本报告没有显式选择项目文件。附件包仅含原报告、清单与适用说明。</p>}
      {rows(preview.documents).map(v => <article className="space-y-1 border-t pt-2" key={text(v.id)}><p className="break-words font-medium">{text(v.filename)}</p><p>{Math.ceil(Number(v.size_bytes) / 1024)} KB · {({ internal: "内部", confidential: "机密", restricted: "受限" } as Record<string, string>)[text(v.classification)] || text(v.classification)}</p><a className="inline-flex min-h-11 items-center underline" href={"/api/document-previews/projects/" + projectId + "/" + text(v.id) + "/original"}>核对完整原件</a><p className="break-all text-xs">原件校验：{text(v.sha256)}</p></article>)}
      <p className="text-muted-foreground">此处按登记信息预览，保存时才实际读取并核对每份原件。任何原件缺失或校验不符都会停止组包。</p>
      <form className="space-y-3" onSubmit={event => { event.preventDefault(); void act(save); }}><label className="block">本次内部组包用途<textarea required maxLength={2048} disabled={busy} className={field} value={reason} onChange={e => setReason(e.target.value)}/></label><label className="flex items-start gap-2"><input required type="checkbox" disabled={busy} key={text(preview.digest)}/>已核对所选完整文件及范围，确认用于内部审阅。</label><Button disabled={busy}>{busy ? "正在读取和组包…" : "读取原件并保存 ZIP 附件包"}</Button></form>
    </section>}
    {rows(history?.items).map(v => <article className="space-y-2 rounded-md border p-3" key={text(v.id)}><p className="font-medium">{new Date(text(v.created_at)).toLocaleString()} · {(Number(v.byte_size) / 1048576).toFixed(2)} MiB</p><p>{text(v.reason)}</p><p className="break-all text-xs">附件包校验：{text(v.content_digest)}</p>{!stopped && <a className="inline-flex min-h-11 items-center underline" href={base + "/" + text(v.id) + "/bundle-download"}>下载原附件包（下载时复核来源）</a>}<details><summary className="cursor-pointer">原文件清单与条款对应</summary><AuditBundleManifest manifest={obj(v.manifest)} /></details></article>)}
    {history?.next_before_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory(text(history.next_before_id)))}>更多附件包历史</Button>}
  </details>;
}
