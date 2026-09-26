"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { CaptureAudioRecorder } from "./capture-audio-recorder";
import { CaptureLocalOriginal } from "./capture-local-original";
import { captureAttachment, uploadCaptureOriginal, type CaptureRecord } from "./capture-original-client";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

export function NewFieldCapture({ base, saved }: { base: string; saved: (record: CaptureRecord) => void }) {
  const [note, setNote] = useState(""), [file, setFile] = useState<File | null>(null);
  const [recording, setRecording] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [stage, setStage] = useState(""), [percent, setPercent] = useState(0), [selection, setSelection] = useState(0);
  const [pending, setPending] = useState<CaptureRecord | null>(null);
  const attempt = useRef({ signature: "", id: "" }), mounted = useRef(true);
  const upload = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; upload.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!note.trim() && !file && !busy) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [note, file, busy]);
  function choose(next: File | null) { setFile(next); setSelection(value => value + 1); setError(""); }
  async function save() {
    if (busy || recording || upload.current) return;
    const controller = new AbortController(); upload.current = controller;
    setBusy(true); setError(""); setPercent(0); setStage("正在保存原始说明…");
    try {
      let record = pending;
      if (!record) {
        const original = file ? await captureAttachment(file) : null;
        if (controller.signal.aborted) { if (mounted.current) setError("已停止保存，原件仍在本页。"); return; }
        const data = { original_text: note, attachment: original }, signature = JSON.stringify(data);
        if (signature !== attempt.current.signature) attempt.current = { signature, id: crypto.randomUUID() };
        const response = await fetch(base, { method: "POST", cache: "no-store", signal: controller.signal,
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...data, request_id: attempt.current.id }),
        });
        const body: unknown = await responseBody(response);
        if (!response.ok || !isRecord(body)) {
          const detail = isRecord(body) && isRecord(body.detail) ? body.detail : {};
          throw new Error(typeof detail.message === "string" ? detail.message : "保存暂未确认，请保留输入后重试。");
        }
        record = body;
        if (mounted.current) setPending(record);
      }
      if (file && record.status === "awaiting_upload") {
        setStage("正在上传原件…");
        record = await uploadCaptureOriginal(`${base}/${String(record.id)}/original`, file, controller.signal,
          value => { if (mounted.current) setPercent(value); });
      }
      if (mounted.current) saved(record);
    } catch (failure) {
      if (mounted.current) setError(controller.signal.aborted ? "已停止等待。说明或原件可能已保存；请保留当前内容，用同一记录重试核对。" : failure instanceof Error ? failure.message : "保存失败，请保留当前文件后重试。");
    } finally {
      if (upload.current === controller) upload.current = null;
      if (mounted.current) { setBusy(false); setStage(""); }
    }
  }
  const locked = busy || pending !== null;
  return <form className="space-y-4 rounded-lg border bg-card p-4" onSubmit={event => { event.preventDefault(); void save(); }}>
    <h2 className="font-semibold">保存一条现场记录</h2>
    <label className="block text-sm">原始说明<textarea className={field} rows={5} maxLength={20000} value={note} disabled={locked} onChange={event => setNote(event.target.value)} placeholder="记录看到的现象、时间、样机编号及尚不确定的内容。"/></label>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block text-sm">拍照 / 选择照片<input key={`photo-${selection}`} className={field} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" disabled={locked || recording} onChange={event => { if (event.target.files?.[0]) choose(event.target.files[0]); }}/></label>
      <label className="block text-sm">选择已有录音<input key={`audio-${selection}`} className={field} type="file" accept="audio/webm,audio/ogg,audio/wav,audio/mp4,audio/mpeg,.m4a,.wav" disabled={locked || recording} onChange={event => { if (event.target.files?.[0]) choose(event.target.files[0]); }}/></label>
    </div>
    <CaptureAudioRecorder disabled={locked} onReady={choose} onActivity={setRecording}/>
    <p className="text-xs text-muted-foreground">每条记录保留一份原件，最大12 MiB。新选择的文件或完成的新录音会替换当前选择。录音转写限5分钟；拍摄、录音和上传时间不代替实际测试时间。</p>
    {file && <><CaptureLocalOriginal file={file}/><Button type="button" variant="ghost" size="sm" disabled={locked || recording} onClick={() => choose(null)}>移除此原件</Button></>}
    {pending && <div className="space-y-2 rounded-md border p-3 text-sm"><p>记录编号已保存，继续补传原件。失败或停止后重试会复用同一条记录。</p>
      {!busy && <Button type="button" size="sm" variant="ghost" onClick={() => saved(pending)}>稍后补传，先打开已保存记录</Button>}
      <p className="text-xs text-muted-foreground">稍后补传前，请先下载当前原件备份。</p>
    </div>}
    {busy && <div role="status" className="space-y-2 text-sm"><p>{stage}{stage.includes("上传") ? percent >= 100 ? "已发送，等待服务器确认…" : `${percent}%` : ""}</p>{stage.includes("上传") && <progress value={percent} max={100} aria-label="原件上传进度" className="w-full accent-primary"/>}<Button type="button" variant="outline" size="sm" onClick={() => upload.current?.abort()}>停止等待，保留当前文件</Button></div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button disabled={busy || recording || (!note.trim() && !file)}>{busy ? "正在保存…" : pending ? "重试补传并核对" : "保存并核对"}</Button>
  </form>;
}
