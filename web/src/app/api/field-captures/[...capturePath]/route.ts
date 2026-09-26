import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ capturePath: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_FILE = 12 * 1024 * 1024;
async function forward(method: "GET" | "POST" | "PUT", request: Request, context: Context) {
  const path = (await context.params).capturePath;
  const shapes = method === "GET" ? [["projects", "#", "#", "recognitions"], ["projects", "#", "#", "recognitions", "#"], ["projects", "#"], ["projects", "#", "samples"], ["projects", "#", "test-cases"], ["projects", "#", "#", "drafts"], ["projects", "#", "#"], ["projects", "#", "#", "original"]] : method === "PUT" ? [["projects", "#", "#", "original"]] : [["projects", "#", "#", "recognitions"], ["projects", "#", "#", "recognitions", "#", "cancel"], ["projects", "#"], ["projects", "#", "#", "issue"], ["projects", "#", "#", "drafts"], ["projects", "#", "#", "submit"]];
  if (!shapes.some(shape => shape.length === path.length && shape.every((part, i) => part === "#" ? uuid.test(path[i]) : part === path[i]))) return sessionError(404, "CAPTURE_NOT_FOUND", "现场采集入口不存在");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  try {
    let body: BodyInit | undefined;
    if (method === "PUT") {
      if (!request.body) return sessionError(400, "ORIGINAL_REQUIRED", "请选择原文件");
      const reader = request.body.getReader(); const chunks: Uint8Array<ArrayBuffer>[] = []; let size = 0;
      try { while (true) { const item = await reader.read(); if (item.done) break; size += item.value.byteLength;
        if (size > MAX_FILE) { await reader.cancel(); return sessionError(413, "ORIGINAL_TOO_LARGE", "原件不能超过12 MiB"); }
        chunks.push(new Uint8Array(item.value));
      } } finally { reader.releaseLock(); }
      body = new Blob(chunks);
    } else if (method === "POST") body = JSON.stringify(await readBoundedJson(request, 131072));
    const query = new URLSearchParams(); const q = new URL(request.url).searchParams.get("q"); if (["samples", "test-cases"].includes(path.at(-1) ?? "") && q) query.set("q", q);
    const before = new URL(request.url).searchParams.get("before"); if (path.at(-1) === "drafts" && before) query.set("before", before);
    const upstream = await pdosApiFetch(`/api/field-captures/${path.map(encodeURIComponent).join("/")}${query.size ? `?${query}` : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": method === "PUT" ? "application/octet-stream" : "application/json" } : {}) }, body,
    }, 60000);
    if (method === "GET" && path.at(-1) === "original" && upstream.ok) {
      return new Response(upstream.body, { status: upstream.status, headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline" } });
    }
    return forwardJson(upstream);
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_CAPTURE", "输入无效或过长");
    return sessionError(503, "CAPTURE_UNAVAILABLE", "现场采集暂不可用，请保留原文件并刷新已保存记录后重试");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
export const PUT = (request: Request, context: Context) => forward("PUT", request, context);
