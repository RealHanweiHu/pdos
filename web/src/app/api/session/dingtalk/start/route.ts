import {
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
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
      const response = sessionError(429, "LOGIN_RATE_LIMITED", "Too many login attempts");
      response.headers.set("Retry-After", String(rateLimit.retryAfterSeconds));
      return response;
    }
    const upstream = await pdosApiFetch("/api/integrations/dingtalk/oauth/login/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (upstream.ok) clearLoginAttempts(reservedAttempt);
    else if (upstream.status !== 401) refundLoginAttempt(reservedAttempt);
    reservedAttempt = null;
    return forwardJson(upstream);
  } catch (error) {
    if (reservedAttempt) refundLoginAttempt(reservedAttempt);
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "DINGTALK_UNAVAILABLE", "DingTalk login unavailable");
  }
}
