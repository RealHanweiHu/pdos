import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/server/request-origin";

/**
 * Sign-in BFF (D214). The API returns the session token to this server only; it goes
 * straight into an HttpOnly, SameSite=Strict cookie and never into a response body.
 */
const SESSION = "pdos-next-session";
const MAX_AGE = 7 * 86400;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const token = /^[A-Za-z0-9_-]{32,128}$/;
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const fail = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** The address our own proxy saw: X-Real-IP, else the right-most forwarded hop. Only a throttle key. */
export function clientAddress(request: NextRequest): string {
  const real = request.headers.get("x-real-ip")?.trim();
  if (real) return real.slice(0, 200);
  const hops = (request.headers.get("x-forwarded-for") ?? "").split(",").map(hop => hop.trim()).filter(Boolean);
  return (hops.at(-1) ?? "unknown").slice(0, 200);
}

async function fields(request: NextRequest, limits: Record<string, number>): Promise<Record<string, string> | null> {
  let value: unknown;
  try { value = await request.json(); } catch { return null; }
  if (!isRecord(value) || Object.keys(value).length !== Object.keys(limits).length) return null;
  const result: Record<string, string> = {};
  for (const [key, limit] of Object.entries(limits)) {
    const item = value[key];
    if (typeof item !== "string" || !item.length || item.length > limit) return null;
    result[key] = item;
  }
  return result;
}

type Called = { response: Response; value: unknown } | { failure: Response };
async function call(path: string, payload: unknown, extra: Record<string, string> = {}): Promise<Called> {
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return { failure: fail("服务尚未配置。", 503, "SOURCE_UNAVAILABLE") };
  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json", ...extra }, body: JSON.stringify(payload),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(20000),
    });
    return { response, value: await response.json().catch(() => null) };
  } catch { return { failure: fail("登录服务暂不可用，请稍后重试。", 503, "SOURCE_UNAVAILABLE") }; }
}

function relay(response: Response, value: unknown) {
  const body = isRecord(value) ? { code: value.code, message: value.message, detail: value.detail } : { code: "SOURCE_UNAVAILABLE", message: "登录服务暂不可用，请稍后重试。" };
  return Response.json(body, { status: response.status, headers });
}

async function keep(request: NextRequest, value: unknown) {
  if (!isRecord(value) || typeof value.session_token !== "string" || !token.test(value.session_token) || typeof value.expires_at !== "string") return fail("登录回执不完整，请重试。", 502, "SOURCE_UNAVAILABLE");
  const seconds = Math.floor((Date.parse(value.expires_at) - Date.now()) / 1000);
  if (!Number.isFinite(seconds) || seconds <= 0) return fail("登录回执已过期，请重试。", 502, "SOURCE_UNAVAILABLE");
  (await cookies()).set(SESSION, value.session_token, { httpOnly: true, sameSite: "strict", path: "/", secure: request.nextUrl.protocol === "https:", maxAge: Math.min(seconds, MAX_AGE) });
  return Response.json({ status: "signed_in", expires_at: value.expires_at, idle_timeout_seconds: value.idle_timeout_seconds }, { headers });
}

export async function signIn(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const input = await fields(request, { login_name: 64, password: 128 });
  if (!input) return fail("请输入登录名和密码。", 422);
  const called = await call("/v1/auth/sign-in", input, { "X-PDOS-Client-Address": clientAddress(request) });
  if ("failure" in called) return called.failure;
  return called.response.ok ? keep(request, called.value) : relay(called.response, called.value);
}

export async function signOut(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const jar = await cookies();
  const current = jar.get(SESSION)?.value;
  let server = "none";
  const base = process.env.PDOS_NEXT_API_URL;
  if (current && base) {
    try {
      const response = await fetch(`${base}/v1/auth/sign-out`, { method: "POST", headers: { Authorization: `Bearer ${current}` }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000) });
      server = response.ok ? "ended" : "unconfirmed";
    } catch { server = "unconfirmed"; }
  }
  jar.delete(SESSION);
  return Response.json({ status: "signed_out", server }, { headers });
}

export async function inspectInvitation(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const input = await fields(request, { token: 128 });
  if (!input || !token.test(input.token)) return fail("邀请链接无效，请向管理员索取新的链接。", 404, "NOT_FOUND");
  const called = await call("/v1/auth/invitations/inspect", input);
  if ("failure" in called) return called.failure;
  if (!called.response.ok) return relay(called.response, called.value);
  const value = isRecord(called.value) ? called.value : {};
  return Response.json({ purpose: value.purpose, display_name: value.display_name, login_name: value.login_name, expires_at: value.expires_at }, { headers });
}

export async function acceptInvitation(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const input = await fields(request, { token: 128, password: 128 });
  if (!input || !token.test(input.token)) return fail("请完整填写新密码。", 422);
  const called = await call("/v1/auth/invitations/accept", input);
  if ("failure" in called) return called.failure;
  return called.response.ok ? keep(request, called.value) : relay(called.response, called.value);
}
