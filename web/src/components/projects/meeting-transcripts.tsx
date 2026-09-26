"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { MeetingReadingPanel } from "./meeting-reading";

const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const sources: Record<string, string> = { manual_upload: "手工整理的会议转写", dingtalk_export: "钉钉会议导出", tencent_meeting_export: "腾讯会议导出" };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("转写资料不完整"); return value; }
function id(value: unknown): string { const result = text(value); if (!/^[0-9a-f-]{36}$/.test(result)) throw new Error("转写标识不完整"); return result; }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("转写清单不完整"); return value; }
function nullable(value: unknown): string | null { return value === null ? null : text(value); }
function number(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("转写序号或时间不完整"); return value; }
function record(value: unknown) {
  if (!isRecord(value)) throw new Error("转写记录不完整");
  return { id: id(value.id), source: text(value.source), time: text(value.uploaded_at), count: number(value.segment_count) };
}
type Transcript = ReturnType<typeof record>;
type Binding = { segment_id: string; speaker_label: string; speaker_user_id: string };
function bindings(value: unknown): Binding[] {
  return list(value).map(item => { if (!isRecord(item)) throw new Error("说话人记录不完整"); return { segment_id: id(item.segment_id), speaker_label: nullable(item.speaker_label) ?? "", speaker_user_id: nullable(item.speaker_user_id) ?? "" }; });
}
function detail(value: unknown) {
  if (!isRecord(value) || typeof value.source_complete !== "boolean" || typeof value.editable !== "boolean") throw new Error("原文资料不完整");
  return { digest: text(value.digest), content: nullable(value.content), complete: value.source_complete, editable: value.editable,
    segments: list(value.segments).map(row => {
      if (!isRecord(row)) throw new Error("引用片段不完整");
      return { id: id(row.id), sequence: number(row.sequence), content: text(row.content), label: nullable(row.speaker_label), userId: nullable(row.speaker_user_id), start: number(row.started_offset_ms), end: row.ended_offset_ms === null ? null : number(row.ended_offset_ms) };
    }),
    members: list(value.members).map(row => { if (!isRecord(row)) throw new Error("说话人成员选项不完整"); return { id: id(row.id), name: text(row.display_name) }; }),
    history: list(value.history).map(row => {
      if (!isRecord(row) || !isRecord(row.context)) throw new Error("说话人校正历史不完整");
      return { name: text(row.confirmed_by), time: text(row.timestamp), reason: text(row.context.reason), before: bindings(row.context.before_bindings), after: bindings(row.context.after_bindings) };
    }),
  };
}
type Detail = ReturnType<typeof detail>;
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "转写办理暂不可用，请刷新核对结果");
  return value;
}

function TranscriptSource({ projectId, meetingId, transcript, canEdit }: { projectId: string; meetingId: string; transcript: Transcript; canEdit: boolean }) {
  const [data, setData] = useState<Detail | null>(null);
  const [draft, setDraft] = useState<Record<string, Binding>>({});
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const retry = useRef<{ signature: string; id: string } | null>(null);
  const path = `/api/projects/${projectId}/meetings/${meetingId}/transcripts/${transcript.id}`;
  const changed = Object.values(draft).filter(item => {
    const original = data?.segments.find(segment => segment.id === item.segment_id);
    return original && (item.speaker_label.trim() !== (original.label ?? "") || item.speaker_user_id !== (original.userId ?? ""));
  });
  async function load() { setData(detail(await request(path))); setDraft({}); setReason(""); }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "转写办理未完成"); } finally { setBusy(false); }
  }
  async function save() {
    if (!data) return;
    const body = { expected_digest: data.digest, reason: reason.trim(), bindings: changed.map(item => ({ segment_id: item.segment_id, speaker_label: item.speaker_label.trim() || null, speaker_user_id: item.speaker_user_id || null })) };
    const signature = JSON.stringify(body);
    if (retry.current?.signature !== signature) retry.current = { signature, id: crypto.randomUUID() };
    await request(`${path}/speakers`, { ...body, request_id: retry.current.id });
    setNotice("说话人校正已留痕，片段原文保持可追溯。该校正不等于承诺任务或批准业务。");
    await load();
  }
  function name(value: Binding | undefined): string {
    if (!value) return "无原记录";
    return `${value.speaker_label || "未标明"} · ${value.speaker_user_id ? data?.members.find(member => member.id === value.speaker_user_id)?.name ?? "历史项目成员" : "身份未绑定"}`;
  }
  const editable = canEdit && data?.editable && !busy;
  return <details className="rounded-lg border p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm">{sources[transcript.source] ?? transcript.source} · {new Date(transcript.time).toLocaleString("zh-CN")} · {transcript.count} 个片段</summary>
    <div className="mt-3 space-y-3">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>{changed.length ? "放弃校正草稿并刷新" : "刷新原文与校正记录"}</Button>
      {busy && <p role="status" className="text-xs">正在读取或保存转写资料…</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}
      {data && <>
        <MeetingReadingPanel projectId={projectId} meetingId={meetingId} transcriptId={transcript.id} sourceDigest={data.digest} canGenerate={!!editable} dirty={changed.length > 0} />
        {!data.complete && <p className="text-xs text-destructive">原文缺失或历史片段无法与原文对应，尚不能作为完整纪要依据。原文缺失时可重传相同转写文本补齐；已有引用片段会保留。</p>}
        <details className="rounded-md bg-muted/30 p-2"><summary className="cursor-pointer text-xs">查看保存的完整原文</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{data.content ?? "此历史记录未保存原文。"}</pre></details>
        <p className="text-xs text-muted-foreground">引用片段保留原话。说话人标签和具名归属由人员核对；无法确定时保留未绑定，不能据此认定他人的承诺或审批。</p>
        <div className="max-h-[36rem] space-y-3 overflow-auto">{data.segments.map(segment => {
          const value = draft[segment.id] ?? { segment_id: segment.id, speaker_label: segment.label ?? "", speaker_user_id: segment.userId ?? "" };
          function patch(update: Partial<Binding>) { setDraft(current => ({ ...current, [segment.id]: { ...value, ...update } })); }
          return <article key={segment.id} id={`transcript-segment-${segment.id}`} className="space-y-2 rounded-md border p-3">
            <p className="text-xs font-medium">片段 {segment.sequence} · {segment.start > 0 || segment.end !== null ? `${segment.start / 1000} 秒${segment.end === null ? "起" : `至 ${segment.end / 1000} 秒`}` : "原稿未提供时间"}</p>
            <p className="whitespace-pre-wrap break-words text-sm">{segment.content}</p>
            <div className="grid gap-2 sm:grid-cols-2"><label className="block text-xs">原稿标签或核对后的发言人标记<input className={input} maxLength={128} disabled={!editable} value={value.speaker_label} onChange={event => patch({ speaker_label: event.target.value })} placeholder="不确定时留空" /></label>
              <label className="block text-xs">具名归属<select className={input} disabled={!editable} value={value.speaker_user_id} onChange={event => patch({ speaker_user_id: event.target.value })}><option value="">身份未绑定</option>{value.speaker_user_id && !data.members.some(member => member.id === value.speaker_user_id) && <option value={value.speaker_user_id}>原归属已不在当前成员中</option>}{data.members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>
            </div>
          </article>;
        })}</div>
        {canEdit && data.editable && <form className="space-y-2" onSubmit={event => { event.preventDefault(); void act(save); }}>
          <label className="block text-xs">说话人核对依据<textarea className={input} required maxLength={3000} disabled={busy} value={reason} onChange={event => setReason(event.target.value)} /></label>
          <Button size="sm" disabled={busy || !changed.length || !reason.trim() || changed.some(item => item.speaker_user_id && !item.speaker_label.trim())}>保存 {changed.length} 处说话人校正</Button>
        </form>}
        {data.history.length > 0 && <details className="rounded-md border p-2"><summary className="cursor-pointer text-xs">最近20次说话人校正</summary><div className="mt-2 space-y-3">{data.history.map((entry, index) => <div key={index} className="space-y-1 text-xs"><p>{entry.name} · {new Date(entry.time).toLocaleString("zh-CN")}</p><p className="whitespace-pre-wrap">{entry.reason}</p>{entry.after.map(binding => <p key={binding.segment_id}>片段 {data.segments.find(segment => segment.id === binding.segment_id)?.sequence ?? "历史"}：{name(entry.before.find(item => item.segment_id === binding.segment_id))} → {name(binding)}</p>)}</div>)}</div></details>}
      </>}
    </div>
  </details>;
}

export function MeetingTranscripts({ projectId, meetingId, canUpload, isActive }: { projectId: string; meetingId: string; canUpload: boolean; isActive: boolean }) {
  const [items, setItems] = useState<Transcript[] | null>(null);
  const [content, setContent] = useState("");
  const [source, setSource] = useState("manual_upload");
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const path = `/api/projects/${projectId}/meetings/${meetingId}/transcripts`;
  async function load() {
    const value = await request(path); if (!isRecord(value)) throw new Error("转写清单不完整");
    setItems(list(value.items).map(record));
  }
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "转写办理未完成"); } finally { setBusy(false); }
  }
  function changeContent(value: string) { setContent(value); setAuthorized(false); }
  async function readFile(file: File) {
    if (file.size > 524288) throw new Error("请选择不超过512KB的UTF-8转写文本");
    const value = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
    if (value.length > 200000 || value.includes("\0")) throw new Error("转写文本过长或包含无效字符");
    changeContent(value);
  }
  async function upload() {
    if (new TextEncoder().encode(content).length > 524288) throw new Error("转写原文不能超过512KB");
    const value = await request(path, { content, source, language: "zh-CN", segments: [], authorized_source: authorized });
    if (!isRecord(value)) throw new Error("上传回执不完整，请刷新核对结果");
    setNotice(value.reused_existing ? "相同原文已复用原记录；已有说话人校正和引用不被覆盖。若补齐了历史原文，请刷新该记录后核对。" : "原文及引用片段已保存，可继续核对说话人。尚未生成AI纪要或业务对象。");
    changeContent(""); await load();
  }
  return <details className="rounded-lg border p-3" onToggle={event => { if (event.currentTarget.open && !items && !busy) void act(load); }}>
    <summary className="cursor-pointer text-sm font-medium">会议转写原文与说话人核对</summary>
    <div className="mt-3 space-y-3">
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新已上传转写</Button>
      {canUpload && isActive && <form className="space-y-3 rounded-md border p-3" onSubmit={event => { event.preventDefault(); void act(upload); }}>
        <p className="text-xs text-muted-foreground">仅录入明确纳入本项目的获授权会议转写，可选择UTF-8文本或粘贴原文。原文自动按行保留引用片段，时间和说话人不作推断。</p>
        <label className="block text-xs">会议转写来源<select className={input} disabled={busy} value={source} onChange={event => { setSource(event.target.value); setAuthorized(false); }}>{Object.entries(sources).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label className="block text-xs">选择转写文本<input className={input} type="file" accept=".txt,.srt,.vtt,text/plain" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void act(() => readFile(file)); event.target.value = ""; }} /></label>
        <label className="block text-xs">转写原文<textarea className={`${input} min-h-40`} required maxLength={200000} disabled={busy} value={content} onChange={event => changeContent(event.target.value)} /></label>
        <label className="flex items-start gap-2 text-xs"><input type="checkbox" className="mt-0.5" disabled={busy} checked={authorized} onChange={event => setAuthorized(event.target.checked)} />我确认本稿来自已获授权、明确纳入当前项目的会议。</label>
        <Button size="sm" disabled={busy || !authorized || !content.trim()}>保存原文与引用片段</Button>
      </form>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}{notice && <p role="status" className="text-xs">{notice}</p>}
      {items?.length === 0 && <p className="text-xs text-muted-foreground">尚未上传会议转写。</p>}
      {items?.map(item => <TranscriptSource key={item.id} projectId={projectId} meetingId={meetingId} transcript={item} canEdit={canUpload && isActive && !busy} />)}
    </div>
  </details>;
}
