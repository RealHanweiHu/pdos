import { isRecord } from "@/components/workspace-api";

export const MAX_CAPTURE_BYTES = 12 * 1024 * 1024;
export type CaptureRecord = Record<string, unknown>;

export async function captureAttachment(file: File) {
  if (!file.size || file.size > MAX_CAPTURE_BYTES) throw new Error("请选择不超过12 MiB的原件");
  const sha = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  const raw = file.type.split(";")[0].toLowerCase();
  const alias: Record<string, string> = { "audio/x-m4a": "audio/mp4", "audio/x-wav": "audio/wav", "audio/wave": "audio/wav", "image/jpg": "image/jpeg" };
  const extension: Record<string, string> = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", webm: "audio/webm", ogg: "audio/ogg" };
  const media = alias[raw] || raw || extension[file.name.split(".").at(-1)?.toLowerCase() ?? ""];
  if (!Object.values(extension).includes(media)) throw new Error("请选择JPEG、PNG、WebP照片或WebM、Ogg、WAV、MP4、MP3录音");
  return { filename: file.name, size_bytes: file.size, media_type: media, sha256: Array.from(new Uint8Array(sha)).map(value => value.toString(16).padStart(2, "0")).join("") };
}

export function uploadCaptureOriginal(path: string, file: File, signal: AbortSignal, progress: (percent: number) => void): Promise<CaptureRecord> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new Error("上传已停止，请核对服务器状态后重试。")); return; }
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const clean = () => signal.removeEventListener("abort", abort);
    xhr.open("PUT", path); xhr.timeout = 90000;
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded * 100 / event.total)); };
    xhr.onload = () => {
      clean();
      let body: unknown;
      try { body = JSON.parse(xhr.responseText); } catch { reject(new Error("未取得上传确认，请保留原件重试。")); return; }
      if (xhr.status >= 200 && xhr.status < 300 && isRecord(body)) { resolve(body); return; }
      const detail = isRecord(body) && isRecord(body.detail) ? body.detail : {};
      reject(new Error(typeof detail.message === "string" ? detail.message : "原件尚未确认保存，请保留本页文件后重试。"));
    };
    xhr.onerror = () => { clean(); reject(new Error("网络中断，原件仍在本页。可重试或先下载备份。")); };
    xhr.ontimeout = () => { clean(); reject(new Error("等待上传确认超时，请保留原件后重试；同一文件不会重复登记。")); };
    xhr.onabort = () => { clean(); reject(new Error("已停止等待上传，原件仍在本页；服务器可能已收到，可按同一记录重试核对。")); };
    signal.addEventListener("abort", abort, { once: true });
    xhr.send(file);
  });
}
