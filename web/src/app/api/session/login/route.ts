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
import {
  clearLoginAttempts,
  consumeLoginAttempt,
  loginRateLimitKey,
  refundLoginAttempt,
} from "@/lib/login-rate-limit";

export async function POST(request: Request) {
  let reservedAttempt: string | null = null;
  try {
    const payload = await readBoundedJson(request);
    reservedAttempt = loginRateLimitKey(payload);
    const rateLimit = consumeLoginAttempt(reservedAttempt);
    if (!rateLimit.allowed) {
      const response = sessionError(
        429,
        "LOGIN_RATE_LIMITED",
        "Too many login attempts; try again later",
      );
      response.headers.set("Retry-After", String(rateLimit.retryAfterSeconds));
      return response;
    }
    const upstream = await pdosApiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!upstream.ok) {
      if (upstream.status !== 401) {
        refundLoginAttempt(reservedAttempt);
        reservedAttempt = null;
      }
      return forwardJson(upstream);
    }

    const token = await readTokenResponse(upstream);
    await persistSession(token);
    clearLoginAttempts(reservedAttempt);
    reservedAttempt = null;
    return sessionJson({ authenticated: true, expires_in: token.expires_in });
  } catch (error) {
    if (reservedAttempt) refundLoginAttempt(reservedAttempt);
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "AUTH_SERVICE_UNAVAILABLE", "Authentication service unavailable");
  }
}
