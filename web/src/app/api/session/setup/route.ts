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
    const setup = await pdosApiFetch("/api/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!setup.ok) return forwardJson(setup);

    const login = await pdosApiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_slug: payload.tenant_slug,
        username: payload.username,
        password: payload.password,
      }),
    });
    if (!login.ok) {
      return sessionError(
        502,
        "SETUP_LOGIN_FAILED",
        "Workspace created; sign in with the administrator account",
      );
    }
    const token = await readTokenResponse(login);
    await persistSession(token);
    return sessionJson({ authenticated: true });
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "AUTH_SERVICE_UNAVAILABLE", "Authentication service unavailable");
  }
}
