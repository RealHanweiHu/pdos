import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type UserRouteContext = { params: Promise<{ userId: string }> };

async function upstreamPath(context: UserRouteContext) {
  const { userId } = await context.params;
  return `/api/admin/users/${encodeURIComponent(userId)}`;
}

export async function PATCH(request: Request, context: UserRouteContext) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(await upstreamPath(context), {
        method: "PATCH",
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
