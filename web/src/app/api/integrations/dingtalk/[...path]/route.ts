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
  if (parts.length === 0 || parts.length > 8 || parts.some((part) => !SAFE_SEGMENT.test(part))) {
    throw new InvalidRequestBodyError("Invalid integration path");
  }
  return `/api/integrations/dingtalk/${parts.map(encodeURIComponent).join("/")}`;
}

async function authorizationHeaders() {
  const token = await currentSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : null;
}

async function proxy(request: Request, context: RouteContext, method: "GET" | "POST" | "PUT") {
  const authorization = await authorizationHeaders();
  if (!authorization) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    const { path } = await context.params;
    const source = new URL(request.url);
    const query = method === "GET" ? source.search : "";
    const init: RequestInit = { method, headers: authorization };
    if (method !== "GET") {
      const payload = await readBoundedJson(request);
      init.headers = { ...authorization, "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    return forwardJson(await pdosApiFetch(`${upstreamPath(path)}${query}`, init));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded integration request is required");
    }
    return sessionError(503, "DINGTALK_UNAVAILABLE", "DingTalk integration unavailable");
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
