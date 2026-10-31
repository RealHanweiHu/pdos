import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });
const MAX_BODY_BYTES = 8192;

async function authentication() {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return { failure: error("请进入有效会话。", 401, "FORBIDDEN_SCOPE") };
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return { failure: error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE") };
  return { token, base };
}

async function forward(base: string, token: string, resource: string, body?: string) {
  try {
    const response = await fetch(`${base}/v1/${resource}`, {
      method: body === undefined ? "GET" : "POST", headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, body,
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error(body === undefined ? "会话管理记录暂不可读，请保留原请求核对。" : "会话修改结果尚未核对，请保留原请求并先查回执。", 503, body === undefined ? "SOURCE_UNAVAILABLE" : "EXTERNAL_OUTCOME_UNKNOWN"); }
}

/** Bound the actual stream; a missing or false Content-Length grants no exception. */
async function boundedJson(request: NextRequest): Promise<string | Response> {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_BODY_BYTES)) return error("会话管理请求超过大小限制或长度无效。", 413, "PAYLOAD_TOO_LARGE");
  if (!request.body) return error("请提交完整会话管理请求。", 422);
  const reader = request.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > MAX_BODY_BYTES) { await reader.cancel(); return error("会话管理请求超过大小限制。", 413, "PAYLOAD_TOO_LARGE"); } chunks.push(next.value); }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch { return error("未取得完整 UTF-8 会话管理请求。", 400); }
  finally { reader.releaseLock(); }
}

function queryFor(request: NextRequest, categoryId: string | undefined, list: boolean): URLSearchParams | Response {
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    if (query.has(key)) return error("会话参数必须唯一。", 422);
    const valid = key === "proposal_id" || list && key === "project_id" ? categoryId !== undefined && uuid.test(value)
      : !list ? false : key === "view" ? value === "active" || value === "archived"
      : key === "q" ? [...value].length <= 160 : key === "cursor" ? uuid.test(value)
      : key === "page_size" ? /^(?:[1-9]|[1-4][0-9]|50)$/.test(value) : false;
    if (!valid) return error("请使用有效的会话范围、视图或分页参数。", 422);
    query.set(key, value);
  }
  return query;
}
const suffix = (query: URLSearchParams) => query.size ? `?${query}` : "";
const scope = (categoryId?: string) => categoryId === undefined ? "personal" : `categories/${categoryId}`;
export async function paiConversationsRead(request: NextRequest, categoryId?: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if (categoryId !== undefined && !uuid.test(categoryId)) return error("此会话入口不可用。", 404, "NOT_FOUND");
  const query = queryFor(request, categoryId, true); if (query instanceof Response) return query;
  const auth = await authentication(); if (auth.failure) return auth.failure;
  return forward(auth.base!, auth.token!, `${scope(categoryId)}/agent-conversations${suffix(query)}`);
}
export async function paiPresentation(request: NextRequest, categoryId: string | undefined, sessionId: string, requestKey?: string) {
  const method = requestKey === undefined ? "POST" : "GET";
  if (request.method !== method) return new Response(null, { status: 405, headers: { ...headers, Allow: method } });
  if (categoryId !== undefined && !uuid.test(categoryId) || !uuid.test(sessionId) || requestKey !== undefined && !uuid.test(requestKey)) return error("此会话入口不可用。", 404, "NOT_FOUND");
  const query = queryFor(request, categoryId, false); if (query instanceof Response) return query;
  if (method === "POST" && !sameOrigin(request)) return error("请从当前站点提交会话修改。", 403, "FORBIDDEN_SCOPE");
  const auth = await authentication(); if (auth.failure) return auth.failure;
  let body: string | undefined;
  if (method === "POST") {
    if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) return error("请提交 JSON 会话管理请求。", 415);
    const raw = await boundedJson(request); if (raw instanceof Response) return raw;
    let value: unknown; try { value = JSON.parse(raw); } catch { return error("会话管理请求不是有效 JSON。", 400); }
    if (value === null || typeof value !== "object" || Array.isArray(value)) return error("请提交完整会话管理请求。", 422);
    const record = value as Record<string, unknown>, fields = ["expected_revision", "request_key", "action", ...(record.action === "rename" ? ["title"] : [])];
    if (Object.keys(record).length !== fields.length || !fields.every(key => Object.hasOwn(record, key)) || !Number.isSafeInteger(record.expected_revision) || (record.expected_revision as number) < 0
      || typeof record.request_key !== "string" || !uuid.test(record.request_key) || !["rename", "pin", "unpin", "archive", "restore"].includes(String(record.action))
      || record.action === "rename" && !(record.title === null || typeof record.title === "string" && record.title === record.title.trim() && [...record.title].length > 0 && [...record.title].length <= 160)) return error("请提交有效的会话修改与原修订号。", 422);
    body = raw;
  }
  return forward(auth.base!, auth.token!, `${scope(categoryId)}/agent-sessions/${sessionId}/presentation${requestKey === undefined ? "" : `/requests/${requestKey}`}${suffix(query)}`, body);
}
