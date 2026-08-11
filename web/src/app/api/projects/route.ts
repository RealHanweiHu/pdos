import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

async function authorizationHeaders() {
  const token = await currentSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : null;
}

export async function GET() {
  const headers = await authorizationHeaders();
  if (!headers) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(await pdosApiFetch("/api/projects", { headers }));
  } catch {
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "Project service unavailable");
  }
}

export async function POST(request: Request) {
  const authorization = await authorizationHeaders();
  if (!authorization) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch("/api/projects", {
        method: "POST",
        headers: { ...authorization, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "PROJECT_SERVICE_UNAVAILABLE", "Project service unavailable");
  }
}
