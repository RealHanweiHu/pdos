import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type UserRouteContext = { params: Promise<{ userId: string }> };

export async function POST(request: Request, context: UserRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { userId } = await context.params;
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "USER_ADMINISTRATION_UNAVAILABLE", "User service unavailable");
  }
}
