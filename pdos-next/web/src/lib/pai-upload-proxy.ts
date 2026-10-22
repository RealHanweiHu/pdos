import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { MAX_UPLOAD_BASE64, MAX_UPLOAD_BYTES, MAX_UPLOAD_JSON_BYTES, pythonWhitespaceStrip, validUploadBody } from "@/lib/pai-upload";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });
async function auth() {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return { failure: error("请进入有效会话。", 401, "FORBIDDEN_SCOPE") };
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return { failure: error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE") };
  return { token, base };
}
async function forward(base: string, token: string, resource: string, body?: string) {
  try {
    const response = await fetch(`${base}/v1/${resource}`, { method: body === undefined ? "GET" : "POST", headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000) });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error(body === undefined ? "原上传记录暂不可读，请保留原指针核对。" : "上传结果尚未核对，请保留同一请求并先读取回执。", 503, body === undefined ? "SOURCE_UNAVAILABLE" : "EXTERNAL_OUTCOME_UNKNOWN"); }
}

/** No write authority is required to look up the caller's own original nonce. */
export async function paiUploadRead(request: NextRequest, categoryId: string, requestKey?: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if (!uuid.test(categoryId) || requestKey !== undefined && !uuid.test(requestKey)) return error("原上传入口不可用。", 404, "NOT_FOUND");
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    if (query.has(key)) return error("上传读取范围须唯一明确。", 422);
    const valid = ["product_id", "proposal_id"].includes(key) ? uuid.test(value) : key === "request_digest" && requestKey !== undefined && /^[0-9a-f]{64}$/.test(value);
    if (!valid) return error("上传读取范围或原请求摘要无效。", 422);
    query.set(key, value);
  }
  if (requestKey !== undefined && !query.has("request_digest")) return error("请携带原上传请求摘要。", 422);
  const current = await auth(); if (current.failure) return current.failure;
  const resource = `categories/${categoryId}/${requestKey === undefined ? "agent-upload-target" : `agent-upload-receipts/${requestKey}`}`;
  return forward(current.base, current.token, `${resource}${query.size ? `?${query}` : ""}`);
}

/** Read a bounded UTF-8 JSON stream even when Content-Length is absent or false. */
async function uploadText(request: NextRequest): Promise<string | Response> {
  const length = request.headers.get("content-length");
  if (length && /^\d+$/.test(length) && Number(length) > MAX_UPLOAD_JSON_BYTES) return error("上传请求超过接收大小限制。", 413, "FILE_TOO_LARGE");
  if (!request.body) return error("请提交完整原件上传请求。", 422);
  const reader = request.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const next = await reader.read(); if (next.done) break;
      size += next.value.byteLength;
      if (size > MAX_UPLOAD_JSON_BYTES) { await reader.cancel(); return error("上传请求超过接收大小限制。", 413, "FILE_TOO_LARGE"); }
      chunks.push(next.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch { return error("未取得完整 UTF-8 上传请求。", 400); }
  finally { reader.releaseLock(); }
}

/** Preserve the existing three visibility choices; only the UI defaults to private. */
export async function paiOriginalUpload(request: NextRequest, categoryId: string, productId?: string) {
  if (request.method !== "POST") return new Response(null, { status: 405, headers: { ...headers, Allow: "POST" } });
  if (!uuid.test(categoryId) || productId !== undefined && !uuid.test(productId)) return error("原件上传入口不可用。", 404, "NOT_FOUND");
  if (request.nextUrl.searchParams.size) return error("原件上传不接受附加查询范围。", 422);
  if (!sameOrigin(request)) return error("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const current = await auth(); if (current.failure) return current.failure;
  if (!/^application\/json(?:\s*;.*)?$/i.test(request.headers.get("content-type") ?? "")) return error("请提交 JSON 原件上传请求。", 415, "UNSUPPORTED_MEDIA_TYPE");
  const text = await uploadText(request); if (typeof text !== "string") return text;
  let body: unknown; try { body = JSON.parse(text); } catch { return error("上传 JSON 不完整或格式无效。", 422); }
  if (body && typeof body === "object" && !Array.isArray(body) && "content_base64" in body && typeof body.content_base64 === "string") {
    const encoded = pythonWhitespaceStrip(body.content_base64), size = encoded.length / 4 * 3 - (encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0);
    if (encoded.length > MAX_UPLOAD_BASE64 || size > MAX_UPLOAD_BYTES) return error("原件不能超过 8 MiB。", 413, "FILE_TOO_LARGE");
  }
  if (!validUploadBody(body)) return error("原件上传字段、文件格式或编码无效。", 422);
  return forward(current.base, current.token, `categories/${categoryId}/${productId === undefined ? "" : `products/${productId}/`}originals`, text);
}
