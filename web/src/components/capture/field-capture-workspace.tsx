"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { NewFieldCapture } from "./new-field-capture";
import { uploadCaptureOriginal } from "./capture-original-client";
import { CaptureLocalOriginal } from "./capture-local-original";
import { CaptureRecognition } from "./capture-recognition";
import { CaptureDraftEditor } from "./capture-draft-editor";
import { WorkspaceShell } from "@/components/workspace-shell";
import { Button } from "@/components/ui/button";
import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import type { WorkspaceIdentity } from "@/components/workspace-types";

type Row = Record<string, unknown>;
const txt = (v: unknown) => v == null ? "" : String(v);
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const inputClass = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const MAX_FILE = 12 * 1024 * 1024;
async function api(path: string, init?: RequestInit): Promise<Row> {
  const response = await fetch(path, { cache: "no-store", ...init });
  const body: unknown = await responseBody(response);
  if (!response.ok || !isRecord(body)) throw new Error(txt(obj(obj(body).detail).message) || "办理失败，请保留原输入并刷新记录后重试");
  return body;
}
function Original({ path, media }: { path: string; media: string }) {
  const [url, setUrl] = useState(""), [error, setError] = useState("");
  useEffect(() => { const c = new AbortController(); let objectUrl = "";
    void (async () => { try { const response = await fetch(path, { cache: "no-store", signal: c.signal }); if (!response.ok) throw new Error("原件暂不可读取，请刷新后重试"); const blob = await response.blob(); if (!c.signal.aborted) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); } } catch (e) { if (!c.signal.aborted) setError(e instanceof Error ? e.message : "原件读取失败"); } })();
    return () => { c.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  if (!url) return <p role="status" className="text-sm">{error || "正在读取原件…"}</p>;
  return <div className="space-y-2">{media.startsWith("image/") ? /* eslint-disable-next-line @next/next/no-img-element */
    <img src={url} alt="保存的现场原始照片" className="max-h-96 max-w-full rounded-md object-contain"/> : <audio controls preload="metadata" src={url} className="w-full"/>}<a href={url} download="现场原件" className="text-sm text-primary underline">下载原件</a></div>;
}
function Review({ base, record, updated, own }: { base: string; record: Row; updated: (r: Row) => void; own: boolean }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [showOriginal, setShowOriginal] = useState(false);
  const path = `${base}/${txt(record.id)}`;
  const [retryFile, setRetryFile] = useState<File | null>(null), [percent, setPercent] = useState(0);
  const uploadRequest = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; uploadRequest.current?.abort(); }; }, []);
  async function upload(file: File) {
    if (uploadRequest.current) return;
    const controller = new AbortController(); uploadRequest.current = controller;
    setBusy(true); setError(""); setPercent(0); setRetryFile(file);
    try {
      const result = await uploadCaptureOriginal(`${path}/original`, file, controller.signal, value => { if (mounted.current) setPercent(value); });
      if (mounted.current) updated(result);
    } catch (failure) { if (mounted.current) setError(failure instanceof Error ? failure.message : "补传失败，原文件保留在本页。"); }
    finally { uploadRequest.current = null; if (mounted.current) setBusy(false); }
  }

  const completed = record.submitted_at != null, review = obj(record.review), test = record.test_run_id != null;
  return <section className="space-y-4 rounded-lg border bg-card p-4">
    <h2 className="font-semibold">核对现场记录</h2><p className="text-xs text-muted-foreground">{new Date(txt(record.created_at)).toLocaleString("zh-CN")} · {completed ? test ? "已登记测试" : "已转为问题" : record.status === "awaiting_upload" ? "原件待补传" : "待人工核对"}</p>
    <div className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3 text-sm">{txt(record.original_text) || "保存时未填写说明，请根据原件人工补全办理内容。"}</div>
    {record.filename != null && <div className="space-y-2"><p className="break-all text-sm">原件：{txt(record.filename)} · {Math.ceil(Number(record.size_bytes) / 1024)} KiB</p>{record.status === "awaiting_upload" ? <><p className="text-sm text-primary">原件还未保存成功。请重新选择同一文件补传，原记录编号保持不变。</p>{own && <label className="block text-sm">补传原件<input type="file" disabled={busy} className={inputClass} onChange={e => { const file = e.target.files?.[0]; if (file) { if (file.size > MAX_FILE) setError("原件不能超过12 MiB"); else void upload(file); } }}/></label>}</> : <><Button variant="outline" size="sm" onClick={() => setShowOriginal(v => !v)}>{showOriginal ? "收起原件" : "查看 / 播放原件"}</Button>{showOriginal && <Original path={`${path}/original`} media={txt(record.media_type)}/>}</>}</div>}
    {record.status === "awaiting_upload" && retryFile && <><CaptureLocalOriginal file={retryFile}/>{busy ? <div role="status" className="space-y-2 text-sm"><p>{percent >= 100 ? "已发送，等待服务器确认…" : `正在补传 ${percent}%`}</p><progress value={percent} max={100} aria-label="补传进度" className="w-full accent-primary"/><Button type="button" size="sm" variant="outline" onClick={() => uploadRequest.current?.abort()}>停止等待</Button></div> : <Button type="button" size="sm" variant="outline" onClick={() => void upload(retryFile)}>重试补传当前文件</Button>}</>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {completed && review.recognition_id != null && <><p className="whitespace-pre-wrap text-sm">识别核对记录：{txt(review.recognition_note)}</p><CaptureRecognition path={path} media={txt(record.media_type)} selectedId={txt(review.recognition_id)} editable={false}/></>}
    {completed ? <div className="space-y-2"><h3 className="font-medium">{test ? txt(obj(review.test_case_snapshot).title) : txt(review.title)}</h3><p className="whitespace-pre-wrap text-sm">{txt(review.description)}</p><p className="text-xs text-muted-foreground">核对草稿版本：{txt(review.draft_version) || "原始确认"} · 样机：{review.sample_id ? `已明确关联 ${txt(review.sample_id)}` : `未关联 · ${txt(review.sample_reason)}`}</p>{test && <p className="text-sm">实际测试状态：{({in_progress:"正在进行",passed:"已通过",failed:"已失败",aborted:"已终止"} as Record<string,string>)[txt(review.status)]}。当前状态与后续处理请进入原测试查看。</p>}<Link className="text-sm text-primary underline" href={test ? `/projects?project=${txt(record.project_id)}&tab=quality&test_case_id=${txt(review.test_case_id)}&test_run_id=${txt(record.test_run_id)}` : `/projects?project=${txt(record.project_id)}&tab=work-items&entity_id=${txt(record.issue_id)}`}>{test ? "进入已登记测试" : "进入已登记问题"}</Link></div> : own && <CaptureDraftEditor base={base} record={record} submitted={updated}/>}
  </section>;
}

export function FieldCaptureWorkspace() {
  const router = useRouter(), params = useSearchParams(); const project = params.get("project") ?? "", capture = params.get("capture") ?? "";
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null), [projects, setProjects] = useState<Project[]>([]), [items, setItems] = useState<Row[]>([]), [record, setRecord] = useState<Row | null>(null);
  const [error, setError] = useState(""), [loggingOut, setLoggingOut] = useState(false), [refresh, setRefresh] = useState(0);
  const [loadedScope, setLoadedScope] = useState(""); const scope = `${project}:${capture}`; const base = `/api/field-captures/projects/${project}`;
  useEffect(() => { let active = true; void (async () => { try { const user = await requestIdentity(); if (!user) { router.replace("/login"); return; } const available = await requestProjectList(); if (active) { setIdentity(user); setProjects(available ?? []); } } catch (e) { if (active) setError(e instanceof Error ? e.message : "入口暂不可用"); } })(); return () => { active = false; }; }, [router]);
  useEffect(() => { if (!identity || !project) return; const controller = new AbortController();
    void Promise.all([api(base, { signal: controller.signal }), capture ? api(`${base}/${capture}`, { signal: controller.signal }) : Promise.resolve(null)]).then(([list, selected]) => { if (!controller.signal.aborted) { setItems(rows(list.items)); setRecord(selected); setLoadedScope(scope); setError(""); } }).catch(e => { if (!controller.signal.aborted) { setItems([]); setRecord(null); setLoadedScope(scope); setError(e instanceof Error ? e.message : "读取失败"); } }); return () => controller.abort();
  }, [identity, project, capture, base, scope, refresh]);
  function saved(r: Row) { setRecord(r); router.push(`/capture?project=${project}&capture=${txt(r.id)}`); setRefresh(v => v + 1); }
  if (!identity) return <p role="status" className="p-6">{error || "正在读取现场采集入口…"}</p>;
  return <WorkspaceShell active="capture" identity={identity} loggingOut={loggingOut} onLogout={() => { setLoggingOut(true); void fetch("/api/session/logout", { method: "POST" }).finally(() => router.replace("/login")); }}>
    <main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6"><header><h1 className="text-2xl font-semibold">现场采集</h1><p className="mt-2 text-sm text-muted-foreground">保存原件与说明，人工核对后登记问题或测试。尚未提交的记录仅本人可见。</p></header>
      <label className="block text-sm">所属项目<select value={project} className={inputClass} onChange={e => router.push(`/capture?project=${e.target.value}`)}><option value="">请选择项目</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {project && loadedScope !== scope && <p role="status" className="text-sm">正在读取记录…</p>}
      {project && loadedScope === scope && <><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => { router.push(`/capture?project=${project}`); setRefresh(v => v + 1); }}>新建记录</Button><Button variant="ghost" size="sm" onClick={() => setRefresh(v => v + 1)}>刷新已保存记录</Button></div>
        {record ? <Review key={txt(record.id)} base={base} record={record} own={txt(record.created_by_user_id) === identity.user.id} updated={saved}/> : !capture && <NewFieldCapture key={project} base={base} saved={saved}/>}
        <section className="space-y-2"><h2 className="font-medium">本人最近100条记录</h2>{!items.length && <p className="text-sm text-muted-foreground">还没有已保存的记录。</p>}{items.map(r => <Link key={txt(r.id)} href={`/capture?project=${project}&capture=${txt(r.id)}`} className="block rounded-lg border p-3 text-sm"><p className="truncate">{txt(obj(r.review).title) || txt(r.original_text) || txt(r.filename)}</p><p className="mt-1 text-xs text-muted-foreground">{new Date(txt(r.created_at)).toLocaleString("zh-CN")} · {r.test_run_id ? "已登记测试" : r.issue_id ? "已登记问题" : r.status === "awaiting_upload" ? "待补传原件" : "待人工核对"}</p></Link>)}</section>
      </>}
    </main>
  </WorkspaceShell>;
}
