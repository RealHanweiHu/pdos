"use client";

import { EmailDocumentText } from "./email-document-text";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import type { ProjectDocument } from "./project-gate-document-types";

const DrawingPreview = dynamic(() => import("./drawing-preview"), { ssr: false });
const drawingKind = (media: string) => media === "application/step" ? "step" : media === "application/x-gerber" ? "gerber" : null;
type Row = Record<string, unknown>;
const txt = (v: unknown) => v == null ? "" : String(v);
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const lines = (v: unknown): string[] => Array.isArray(v) ? v.map(String) : [];
const field = "min-h-10 rounded-md border bg-background p-2 text-sm";
async function read(path: string, signal?: AbortSignal): Promise<Row> {
  const r = await fetch(path, { cache: "no-store", signal }); const body: unknown = await responseBody(r);
  if (!r.ok || !isRecord(body)) throw new Error(txt(obj(obj(body).detail).message) || "资料暂不可读取"); return body;
}
function PageText({ base, page }: { base: string; page: number }) {
  const [data, setData] = useState<Row | null>(null), [offset, setOffset] = useState(0), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function load(next = 0) { controller.current?.abort(); const c = new AbortController(); controller.current = c; setBusy(true); setError(""); try { const result = await read(`${base}/text?page=${page}&offset=${next}`, c.signal); if (!c.signal.aborted) { setData(result); setOffset(next); } } catch (e) { if (!c.signal.aborted) setError(e instanceof Error ? e.message : "正文暂不可读"); } finally { if (!c.signal.aborted) setBusy(false); } }
  return <div className="space-y-2"><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void load()}>读取此页抽取文字</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{data && <><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3 font-sans text-sm">{txt(data.text) || "此页没有已存储的可读文字，需查看原图或补充文字识别。"}</pre><p className="text-xs text-muted-foreground">当前显示本页 {offset + (txt(data.text) ? 1 : 0)}–{offset + txt(data.text).length} 字，已抽取共 {String(data.total_characters)} 字。抽取文字可能遗漏图形、符号或版面关系。</p><div className="flex gap-2">{offset > 0 && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(Math.max(0,offset-20000))}>上一段文字</Button>}{typeof data.next_offset === "number" && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(Number(data.next_offset))}>下一段文字</Button>}</div></>}</div>;
}
function OriginalPane({ document, label, page, onPage, onReady }: { document: ProjectDocument; label: string; page: number; onPage: (n: number) => void; onReady: (ready: boolean) => void }) {
  const [url, setUrl] = useState(""), [pages, setPages] = useState(0), [progress, setProgress] = useState(0), [loaded, setLoaded] = useState(false), [error, setError] = useState("");
  const [source, setSource] = useState<Blob | null>(null);
  const [zoom, setZoom] = useState("page-width"), [attempt, setAttempt] = useState(0);
  const base = `/api/document-previews/projects/${document.project_id}/${document.document_id}`;
  const pdf = document.media_type === "application/pdf";
  useEffect(() => {
    const c = new AbortController(); let objectUrl = "";
    void (async () => { try {
      const response = await fetch(`${base}/original`, { cache: "no-store", signal: c.signal });
      if (!response.ok) { const body: unknown = await responseBody(response); throw new Error(txt(obj(obj(body).detail).message) || "原件读取失败"); }
      if (!response.body || response.headers.get("x-document-sha256") !== document.sha256) throw new Error("原件与选定文档摘要不一致，请刷新文档列表");
      const reader = response.body.getReader(), chunks: Uint8Array<ArrayBuffer>[] = []; let total = 0;
      try { while (true) { const chunk = await reader.read(); if (chunk.done) break; total += chunk.value.byteLength; if (total > 20 * 1024 * 1024) { await reader.cancel(); throw new Error("原件超过当前20 MiB查看范围"); } chunks.push(new Uint8Array(chunk.value)); if (!c.signal.aborted) setProgress(total); } } finally { reader.releaseLock(); }
      if (total !== document.size_bytes) throw new Error("原件未完整传输，请重试");
      if (!c.signal.aborted) { const original = new Blob(chunks, { type: document.media_type }); setSource(original); objectUrl = URL.createObjectURL(original); setUrl(objectUrl); setPages(Number(response.headers.get("x-document-pages")) || 0); setLoaded(true); onReady(true); setError(""); }
    } catch (e) { if (!c.signal.aborted) { setError(e instanceof Error ? e.message : "读取失败"); setLoaded(false); onReady(false); } } })();
    return () => { c.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [base, document.sha256, document.size_bytes, document.media_type, onReady, attempt]);
  useEffect(() => { if (pages && page>pages) onPage(pages); }, [pages, page, onPage]);
  const viewUrl = `${url}#page=${page}&zoom=${zoom}`;
  return <section className="min-w-0 space-y-3 rounded-lg border bg-card p-3" aria-label={`${label}原件`}><div><p className="text-xs font-medium text-primary">{label}</p><h4 className="break-all font-medium">{document.filename}</h4><p className="mt-1 text-xs text-muted-foreground">{new Date(document.created_at).toLocaleString("zh-CN")} · {(document.size_bytes/1024/1024).toFixed(2)} MiB · {({internal:"内部",confidential:"机密",restricted:"受限"} as Record<string,string>)[document.classification] ?? document.classification}</p><details className="mt-1 text-xs text-muted-foreground"><summary>文件身份与内容摘要</summary><p className="break-all">{document.document_id}<br/>SHA-256 {document.sha256}</p></details></div>
    {!loaded && !error && <p role="status" className="text-sm">正在读取原件：{Math.min(100,Math.floor(progress/document.size_bytes*100))}% · {(progress/1024/1024).toFixed(2)} / {(document.size_bytes/1024/1024).toFixed(2)} MiB</p>}
    {error && <div className="space-y-2"><p role="alert" className="text-sm text-destructive">{error}</p><Button type="button" size="sm" variant="outline" onClick={() => { setError(""); setProgress(0); setAttempt(v => v+1); }}>重新读取原件</Button></div>}
    {loaded && url && <>{pdf && <div className="flex flex-wrap items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={page<=1} onClick={() => onPage(page-1)}>上一页</Button><label className="text-sm">页码 <input aria-label={`${label}页码`} className={`${field} w-20`} type="number" min={1} max={pages} value={page} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n>=1 && n<=pages) onPage(n); }}/></label><span className="text-xs">/ {pages}</span><Button type="button" size="sm" variant="outline" disabled={page>=pages} onClick={() => onPage(page+1)}>下一页</Button><label className="text-sm">显示 <select className={field} value={zoom} onChange={e => setZoom(e.target.value)}><option value="page-width">适合宽度</option><option value="page-fit">整页</option><option value="100">100%</option><option value="150">150%</option><option value="200">200%</option></select></label></div>}
      {pdf ? <iframe key={viewUrl} src={viewUrl} title={`${label} · ${document.filename} · 第${page}页`} className="h-[65vh] min-h-80 w-full rounded-md border bg-white"/> : drawingKind(document.media_type) && source ? <DrawingPreview source={source} kind={drawingKind(document.media_type)!}/> : <p className="text-sm">此格式可下载原件，尚未接入内嵌预览。</p>}
      <div className="flex flex-wrap gap-4 text-sm"><a className="text-primary underline" href={pdf ? viewUrl : url} target="_blank" rel="noreferrer">在新标签打开</a><a className="text-primary underline" href={url} download={document.filename}>下载原件</a></div>
      {document.media_type === "message/rfc822" && <EmailDocumentText base={base}/>}
      {pdf && <><p className="text-xs text-muted-foreground">页码按PDF文件顺序，文字对照使用上方所选页码；阅读器内滚动不会更改对照页码。若设备未显示或未跳到指定页，请在新标签打开并使用阅读器页码；已读取的原件在本次查看中复用。</p><PageText key={`${document.document_id}:${page}`} base={base} page={page}/></>}
    </>}
  </section>;
}
export function ProjectDocumentPreview({ document, documents, onClose, initialPage = 1 }: { document: ProjectDocument; documents: ProjectDocument[]; onClose: () => void; initialPage?: number }) {
  const [leftReady, setLeftReady] = useState(false), [rightReady, setRightReady] = useState(false);
  const [other, setOther] = useState(""), [leftPage, setLeftPage] = useState(initialPage), [rightPage, setRightPage] = useState(1);
  const [data, setData] = useState<Row | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const sequence = useRef(0); const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const right = documents.find(d => d.document_id === other && d.project_id === document.project_id);
  const changeLeft = useCallback((n: number) => { setLeftPage(n); setData(null); sequence.current++; setBusy(false); }, []);
  const changeRight = useCallback((n: number) => { setRightPage(n); setData(null); sequence.current++; setBusy(false); }, []);
  async function compare() { if (!right) return; pending.current?.abort(); const c = new AbortController(); pending.current = c; const seq = ++sequence.current; setBusy(true); setError(""); setData(null); try { const result = await read(`/api/document-previews/projects/${document.project_id}/compare?left=${document.document_id}&right=${right.document_id}&left_page=${leftPage}&right_page=${rightPage}`, c.signal); if (seq === sequence.current) setData(result); } catch (e) { if (!c.signal.aborted && seq === sequence.current) setError(e instanceof Error ? e.message : "对照失败"); } finally { if (seq === sequence.current) setBusy(false); } }
  return <section className="col-span-full space-y-4 rounded-lg border bg-muted/10 p-3 sm:p-4" aria-label="原件预览与对照"><div className="flex items-center justify-between gap-3"><h3 className="font-semibold">原件预览与版本对照</h3><Button type="button" size="sm" variant="ghost" onClick={onClose}>收起</Button></div>
    {["application/pdf", "application/step", "application/x-gerber"].includes(document.media_type) && <label className="block text-sm">选择另一份同格式文件进行对照<select className={`${field} mt-1 w-full`} value={other} onChange={e => { setOther(e.target.value); setRightPage(1); setRightReady(false); setData(null); setError(""); sequence.current++; setBusy(false); }}><option value="">仅查看当前原件</option>{documents.filter(d => d.project_id === document.project_id && d.document_id !== document.document_id && d.media_type === document.media_type).map(d => <option key={d.document_id} value={d.document_id}>{d.filename} · {new Date(d.created_at).toLocaleString("zh-CN")}</option>)}</select></label>}
    {right && <p className="text-sm text-muted-foreground">A、B由你选择，请先核对文件身份，PDF需分别定位到要对照的页面。上传先后和同名不构成正式替代关系；此处不会改变业务版本或批准状态。</p>}
    <div className={`grid gap-4 ${right ? "2xl:grid-cols-2" : ""}`}><OriginalPane key={document.document_id} document={document} label={right ? "文件 A" : "当前文件"} page={leftPage} onPage={changeLeft} onReady={setLeftReady}/>{right && <OriginalPane key={right.document_id} document={right} label="文件 B" page={rightPage} onPage={changeRight} onReady={setRightReady}/>}</div>
    {right && document.media_type !== "application/pdf" && <p className="text-sm text-muted-foreground">{right.sha256 === document.sha256 ? "两份原件内容摘要相同。" : "两份原件内容摘要不同。"}两侧独立适合窗口，核对尺寸时请结合各自单位、坐标和外框；当前不自动判断几何变化或工程影响。</p>}
    {right && document.media_type === "application/pdf" && <div className="space-y-3"><Button type="button" variant="outline" disabled={busy || !leftReady || !rightReady} onClick={() => void compare()}>{busy ? "正在读取所选页差异…" : `比较 A 第${leftPage}页与 B 第${rightPage}页的文字`}</Button><p className="text-xs text-muted-foreground">比较已抽取的所选页文字，每侧最多前20,000字、1,000行。不会识别图形、尺寸标注的视觉变化；扫描件需文字识别或人工核对原图。</p>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{data && <><p className="text-sm">{data.same_original ? "两份文件的内容摘要相同。" : "两份原件内容摘要不同。"}{data.comparable_text ? data.text_equal ? "本次选中范围的抽取文字相同。" : "本次选中范围存在文字差异。" : "一侧或两侧缺少可读抽取文字，不能据此判断版本差异。"}{data.limited === true ? "本次仅显示部分文字，请继续核对完整原件。" : ""}</p><div className="max-h-[65vh] space-y-2 overflow-auto">{rows(data.changes).map((change,i) => <details key={i} open={change.kind !== "equal"} className="rounded-md border bg-background p-3"><summary className="text-sm">{({equal:"相同文字",replace:"修改",insert:"B 新增文字",delete:"A 独有文字"} as Record<string,string>)[txt(change.kind)]} · A {lines(change.left).length ? `${String(change.left_start)}–${String(change.left_end)}` : "—"} / B {lines(change.right).length ? `${String(change.right_start)}–${String(change.right_end)}` : "—"}</summary><div className="mt-2 grid gap-2 lg:grid-cols-2"><pre className={`overflow-auto whitespace-pre-wrap break-words p-2 font-sans text-xs ${change.kind !== "equal" ? "bg-destructive/10" : "bg-muted/20"}`}>{lines(change.left).join("\n") || "（无对应文字）"}</pre><pre className={`overflow-auto whitespace-pre-wrap break-words p-2 font-sans text-xs ${change.kind !== "equal" ? "bg-primary/10" : "bg-muted/20"}`}>{lines(change.right).join("\n") || "（无对应文字）"}</pre></div></details>)}</div></>}</div>}
  </section>;
}
