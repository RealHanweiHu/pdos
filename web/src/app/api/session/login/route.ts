import {
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  persistSession,
  readBoundedJson,
  readTokenResponse,
  sessionError,
  sessionJson,
} from "@/lib/pdos-api";

export async function POST(request: Request) {
  try {
    const payload = await readBoundedJson(request);
    const upstream = await pdosApiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!upstream.ok) return forwardJson(upstream);

    const token = await readTokenResponse(upstream);
    await persistSession(token);
    return sessionJson({ authenticated: true, expires_in: token.expires_in });
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "AUTH_SERVICE_UNAVAILABLE", "Authentication service unavailable");
  }
}
