/**
 * Organization proxy: departments, reporting lines, delegation, handover.
 *
 * The API gates every one of these on user.manage, so the browser layer only
 * has to bound the path and forward the session token.
 */
import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

const SAFE_SEGMENT = /^[A-Za-z0-9._:-]{1,128}$/;

type RouteContext = { params: Promise<{ path: string[] }> };

function upstreamPath(parts: string[]) {
  if (parts.length === 0 || parts.length > 6 || parts.some((part) => !SAFE_SEGMENT.test(part))) {
    throw new InvalidRequestBodyError("Invalid organization path");
  }
  return `/api/admin/organization/${parts.map(encodeURIComponent).join("/")}`;
}

async function proxy(
  request: Request,
  context: RouteContext,
  method: "GET" | "POST" | "PUT",
) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { path } = await context.params;
    const source = new URL(request.url);
    const authorization = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { method, headers: authorization };
    if (method !== "GET") {
      const payload = path[0] === "process-templates"
        ? await readBoundedJson(request, 2 * 1024 * 1024)
        : await readBoundedJson(request).catch(() => ({}));
      init.headers = { ...authorization, "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    const query = method === "GET" ? source.search : "";
    const timeout = path[0] === "process-templates" && path.at(-1) === "generate" ? 120_000 : 5_000;
    return forwardJson(await pdosApiFetch(`${upstreamPath(path)}${query}`, init, timeout));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded organization request is required");
    }
    return sessionError(503, "ORGANIZATION_UNAVAILABLE", "Organization service unavailable");
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxy(request, context, "GET");
}

export async function POST(request: Request, context: RouteContext) {
  return proxy(request, context, "POST");
}

export async function PUT(request: Request, context: RouteContext) {
  return proxy(request, context, "PUT");
}
