"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 12 * 1024 * 1024;
// Leave room for browser stop delivery and codec padding below the five-minute extraction limit.
const MAX_SECONDS = 290;
const TYPES = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"];
type Session = {
  recorder: MediaRecorder | null; stream: MediaStream | null; chunks: Blob[];
  size: number; discard: boolean; stopping: boolean; started: number;
  timer: ReturnType<typeof setInterval> | null;
};

function release(session: Session) {
  if (session.timer) clearInterval(session.timer);
  session.timer = null;
  session.stream?.getTracks().forEach(track => track.stop());
}

export function CaptureAudioRecorder({ disabled, onReady, onActivity }: {
  disabled: boolean; onReady: (file: File) => void; onActivity: (active: boolean) => void;
}) {
  const [phase, setPhase] = useState<"idle" | "requesting" | "recording" | "stopping">("idle");
  const [seconds, setSeconds] = useState(0), [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const live = useRef<Session | null>(null), mounted = useRef(true);
  const callbacks = useRef({ onReady, onActivity });
  useEffect(() => { callbacks.current = { onReady, onActivity }; }, [onReady, onActivity]);

  const stop = useCallback((discard = false, reason = "") => {
    const session = live.current;
    if (!session) return;
    session.discard ||= discard;
    if (session.stopping) return;
    session.stopping = true;
    if (mounted.current) { setNotice(reason); setPhase("stopping"); }
    if (session.recorder && session.recorder.state !== "inactive") {
      try { session.recorder.stop(); } catch {
        session.discard = true; live.current = null;
        if (mounted.current) { setPhase("idle"); callbacks.current.onActivity(false); setError("未能完成本次录音，请重录或选择已有录音文件。"); }
      }
      release(session);
    } else {
      release(session); live.current = null;
      if (mounted.current) { setPhase("idle"); callbacks.current.onActivity(false); }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const hidden = () => { if (document.hidden) stop(false, "页面进入后台，录音已停止。请回听后保存。"); };
    const leaving = (event: BeforeUnloadEvent) => {
      if (live.current) { event.preventDefault(); event.returnValue = ""; }
    };
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("beforeunload", leaving);
    return () => {
      mounted.current = false; stop(true); live.current = null;
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("beforeunload", leaving);
    };
  }, [stop]);

  async function start() {
    if (disabled || live.current) return;
    setError(""); setNotice("");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("此浏览器或页面暂不支持直接录音。请使用手机录音应用，再选择录音文件上传。"); return;
    }
    const mimeType = TYPES.find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) { setError("此浏览器未提供支持的录音格式，请选择已有录音文件。"); return; }
    const session: Session = { recorder: null, stream: null, chunks: [], size: 0, discard: false, stopping: false, started: 0, timer: null };
    live.current = session; setPhase("requesting"); setSeconds(0); callbacks.current.onActivity(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      if (live.current !== session || !mounted.current || session.stopping) { stream.getTracks().forEach(track => track.stop()); return; }
      session.stream = stream;
      const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 });
      session.recorder = recorder;
      recorder.ondataavailable = event => {
        if (session.discard || !event.data.size) return;
        session.size += event.data.size;
        if (session.size > MAX_BYTES) {
          session.discard = true; session.chunks = [];
          if (mounted.current) setError("录音超过12 MiB，请分段重录；原先选择的文件仍保留。");
          stop(true); return;
        }
        session.chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (live.current !== session) return;
        if (mounted.current) setError("录音被设备中断，请重录或选择已有录音文件。");
        stop(true);
      };
      recorder.onstop = () => {
        release(session);
        if (live.current !== session) return;
        live.current = null;
        if (!mounted.current) return;
        setPhase("idle"); callbacks.current.onActivity(false);
        if (session.discard) return;
        const actualType = (recorder.mimeType || session.chunks[0]?.type || "").split(";")[0].trim().toLowerCase();
        const extension = ({ "audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg" } as Record<string, string>)[actualType];
        const blob = new Blob(session.chunks, { type: actualType });
        session.chunks = [];
        if (!extension || !blob.size || blob.size > MAX_BYTES) { setError("未取得可用录音，请重录或选择已有文件。"); return; }
        const name = `现场录音-${new Date().toISOString().replace(/[:.]/g, "-")}.${extension}`;
        callbacks.current.onReady(new File([blob], name, { type: actualType }));
      };
      stream.getAudioTracks().forEach(track => track.addEventListener("ended", () => {
        if (live.current === session && !session.stopping) stop(false, "麦克风连接已结束，请回听已录制的内容。");
      }));
      session.started = performance.now(); recorder.start(1000); setPhase("recording");
      session.timer = setInterval(() => {
        const elapsed = Math.floor((performance.now() - session.started) / 1000);
        if (mounted.current) setSeconds(Math.min(elapsed, MAX_SECONDS));
        if (elapsed >= MAX_SECONDS) stop(false, "已达到单次录音时长，请保存后新建下一段。");
      }, 250);
    } catch (failure) {
      release(session);
      if (live.current !== session || !mounted.current) return;
      live.current = null; setPhase("idle"); callbacks.current.onActivity(false);
      const name = failure instanceof DOMException ? failure.name : "";
      setError(name === "NotAllowedError" ? "尚未取得麦克风权限，可在浏览器中允许后重试，或选择已有录音。" : name === "NotFoundError" ? "没有找到麦克风，请连接设备或选择已有录音。" : "暂时无法开始录音，请检查麦克风是否被其他应用占用。");
    }
  }

  return <section className="space-y-2 rounded-md border p-3">
    <h3 className="text-sm font-medium">直接录音</h3>
    <p className="text-xs text-muted-foreground">点击后由浏览器询问麦克风权限。单次最多4分50秒；切到后台会停止录音。录音先保留在当前页面，保存记录后才上传。</p>
    {phase === "idle" ? <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void start()}>开始录音</Button> : <div className="flex flex-wrap items-center gap-2">
      <p role="status" className="text-sm tabular-nums">{phase === "requesting" ? "等待麦克风授权…" : phase === "stopping" ? "正在整理录音…" : `录音中 ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</p>
      {phase === "recording" && <Button type="button" size="sm" onClick={() => stop(false)}>停止并回听</Button>}
      {phase !== "stopping" && <Button type="button" size="sm" variant="ghost" onClick={() => stop(true, "已取消本次录音，原先选择的文件保留。")}>取消本次录音</Button>}
    </div>}
    {notice && <p role="status" className="text-xs text-muted-foreground">{notice}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
