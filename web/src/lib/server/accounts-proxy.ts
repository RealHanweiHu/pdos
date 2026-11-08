import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/server/request-origin";

/** Administrator account BFF (D214/D86/D192). The API decides who is an administrator. */
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const actions = new Set(["invitation", "password-reset", "deactivate", "reactivate", "sessions/revoke", "administrator"]);
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const fail = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

async function forward(path: string, method: "GET" | "POST", body?: unknown) {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return fail("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return fail("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}${path}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(30000),
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch {
    return method === "GET"
      ? fail("暂未读取到账户列表，请重新读取。", 503, "SOURCE_UNAVAILABLE")
      : fail("暂未取得账户操作的回执，请刷新账户列表核对结果。", 503, "EXTERNAL_OUTCOME_UNKNOWN");
  }
}

async function json(request: NextRequest): Promise<unknown> {
  const text = await request.text();
  if (!text) return {};
  try { return JSON.parse(text); } catch { return null; }
}

export async function listAccounts(request: NextRequest) {
  if (request.nextUrl.searchParams.size) return fail("账户列表只按当前租户读取。", 422);
  return forward("/v1/accounts", "GET");
}

export async function createAccount(request: NextRequest) {
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const value = await json(request);
  if (!isRecord(value) || Object.keys(value).some(key => !["display_name", "login_name"].includes(key)) || typeof value.display_name !== "string" || !value.display_name.trim() || value.display_name.length > 160 || typeof value.login_name !== "string" || !value.login_name.trim() || value.login_name.length > 64) return fail("请填写姓名和登录名。", 422);
  return forward("/v1/accounts", "POST", { display_name: value.display_name, login_name: value.login_name });
}

export async function accountAction(request: NextRequest, context: { params: Promise<{ principalId: string; action: string[] }> }) {
  const { principalId, action } = await context.params;
  const name = action.join("/");
  if (!uuid.test(principalId) || !actions.has(name)) return fail("此入口不可用。", 404, "NOT_FOUND");
  if (!sameOrigin(request)) return fail("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  if (request.nextUrl.searchParams.size) return fail("账户操作不接受查询参数。", 422);
  const value = await json(request);
  if (name === "administrator") {
    if (!isRecord(value) || Object.keys(value).length !== 1 || typeof value.administrator !== "boolean") return fail("请明确授予或取消管理员身份。", 422);
    return forward(`/v1/accounts/${principalId}/administrator`, "POST", { administrator: value.administrator });
  }
  if (!isRecord(value) || Object.keys(value).length) return fail("此操作不需要填写内容。", 422);
  return forward(`/v1/accounts/${principalId}/${name}`, "POST");
}
