import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

export async function GET() {
  const token = await currentSessionToken();
  if (!token) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    return forwardJson(
      await pdosApiFetch("/api/auth/me", {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "AUTH_SERVICE_UNAVAILABLE", "Authentication service unavailable");
  }
}
