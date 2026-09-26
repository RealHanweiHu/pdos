import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ conversationPath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAX_FILE = 20 * 1024 * 1024;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const path = (await context.params).conversationPath ?? [];
  const isAttachment = path[1] === "attachments";
  const shapes = method === "GET" ? [[], ["#"], ["#", "attachments"], ["#", "attachments", "#"], ["#", "attachments", "#", "email-parts"], ["#", "attachments", "#", "email-origins"],
    ["#", "messages", "#", "intake-ai-sources"], ["#", "messages", "#", "report-imports"], ["#", "intake-ai-sources", "#"], ["#", "intake-ai-findings", "#"], ["#", "intake-ai-sources", "#", "runs"], ["#", "report-imports", "#"],
    ["#", "messages", "#", "email-intake-previews"], ["#", "messages", "#", "pdf-intake-previews"], ["#", "messages", "#", "decision-intake-previews"], ["#", "messages", "#", "issue-intake-previews"], ["#", "decision-intake-previews", "#"], ["#", "decision-intake-previews", "#", "target-options"], ["#", "issue-intake-previews", "#"], ["#", "issue-intake-previews", "#", "issue-options"]] :
    [[], ["#", "intake-ai-findings", "#", "prepare-import"], ["#", "intake-ai-findings", "#", "observation-preview"], ["#", "intake-ai-findings", "#", "adopt-observations"], ["#", "intake-ai-findings", "#", "preview"], ["#", "intake-ai-findings", "#", "review"], ["#", "intake-ai-sources", "#", "runs"], ["#", "messages"], ["#", "archive"], ["#", "attachments"], ["#", "messages", "#", "run"],
      ["#", "attachments", "#", "email-parts"], ["#", "attachments", "#", "content"], ["#", "attachments", "#", "parse"], ["#", "attachments", "#", "revoke"],
      ["#", "messages", "#", "intake-ai-sources"], ["#", "messages", "#", "report-imports"], ["#", "report-imports", "#", "prepare"], ["#", "messages", "#", "email-intake-previews"], ["#", "messages", "#", "pdf-intake-previews"], ["#", "messages", "#", "decision-intake-previews"], ["#", "messages", "#", "issue-intake-previews"], ["#", "issue-intake-previews", "#", "confirm"], ["#", "decision-intake-previews", "#", "confirm"]];
  const valid = (method === "GET" && path.length === 4 && path[0] === "work-context" && uuid.test(path[1]) && ["task", "issue", "risk", "capa", "gate"].includes(path[2]) && uuid.test(path[3])) || shapes.some(shape => shape.length === path.length && shape.every((part, index) => part === "#" ? uuid.test(path[index]) : part === path[index]));
  if (!valid) return sessionError(404, "CONVERSATION_ROUTE_NOT_FOUND", "Conversation route not found");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const query = new URLSearchParams();
    if (method === "GET") for (const key of path.length ? (isAttachment ? ["after_ordinal", "before_id"] : ["pdf-intake-previews", "email-intake-previews"].includes(path.at(-1) ?? "") ? ["kind"] : path.at(-1) === "target-options" ? ["kind", "search", "target_id", "before_updated_at", "before_id"] : path.at(-1) === "issue-options" ? ["search", "issue_id", "before_updated_at", "before_id"] : ["before_sequence", "before_revision"]) : ["project_id", "meeting_id"]) {
      const value = new URL(request.url).searchParams.get(key); if (value) query.set(key, value);
    }
    let body: BodyInit | undefined;
    let contentType: string | undefined;
    if (method === "POST" && path.at(-1) === "content") {
      if (!request.body || Number(request.headers.get("content-length") ?? 0) > MAX_FILE) return sessionError(413, "DOCUMENT_TOO_LARGE", "文件不能超过20 MiB");
      const reader = request.body.getReader(); const chunks: Uint8Array<ArrayBuffer>[] = []; let total = 0;
      try { while (true) { const item = await reader.read(); if (item.done) break; total += item.value.byteLength;
        if (total > MAX_FILE) { await reader.cancel(); return sessionError(413, "DOCUMENT_TOO_LARGE", "文件不能超过20 MiB"); }
        chunks.push(new Uint8Array(item.value));
      } } finally { reader.releaseLock(); }
      body = new Blob(chunks); contentType = "application/octet-stream";
    } else if (method === "POST" && !["run", "parse", "revoke", "prepare"].includes(path.at(-1) ?? "")) {
      body = JSON.stringify(await readBoundedJson(request, (["pdf-intake-previews", "email-intake-previews"].includes(path.at(-1) ?? "") || path[1] === "decision-intake-previews" && path.at(-1) === "confirm") ? 2 * 1024 * 1024 : 131072)); contentType = "application/json";
    }
    return forwardJson(await pdosApiFetch(`/api/conversations${path.length ? `/${path.map(encodeURIComponent).join("/")}` : ""}${query.size ? `?${query}` : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(contentType ? { "Content-Type": contentType } : {}) }, body,
    }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST_BODY", "Message body is invalid or too large");
    return sessionError(503, "CONVERSATION_UNAVAILABLE", "会话暂不可用，请刷新查询已保存消息或附件后继续");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
