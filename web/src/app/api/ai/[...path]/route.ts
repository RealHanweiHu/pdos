/**
 * AI-surface proxy: review inbox, capabilities, touchpoints, usage, agent runs.
 *
 * Every one of these is authorized server-side against the caller's tenant and
 * project membership, so the browser layer only has to bound the path and
 * forward the session token.
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
    throw new InvalidRequestBodyError("Invalid AI path");
  }
  return `/api/ai/${parts.map(encodeURIComponent).join("/")}`;
}

async function proxy(request: Request, context: RouteContext, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { path } = await context.params;
    const source = new URL(request.url);
    const authorization = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { method, headers: authorization };
    if (method === "POST") {
      const payload = await readBoundedJson(request).catch(() => ({}));
      init.headers = { ...authorization, "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    const query = method === "GET" ? source.search : "";
    return forwardJson(await pdosApiFetch(`${upstreamPath(path)}${query}`, init));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded AI request is required");
    }
    return sessionError(503, "AI_SURFACE_UNAVAILABLE", "AI surface unavailable");
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxy(request, context, "GET");
}

export async function POST(request: Request, context: RouteContext) {
  return proxy(request, context, "POST");
}
