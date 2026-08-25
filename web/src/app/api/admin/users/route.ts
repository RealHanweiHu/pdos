import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

const UPSTREAM_PATH = "/api/admin/users";

export async function GET() {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch(UPSTREAM_PATH, { headers: { Authorization: `Bearer ${token}` } }),
    );
  } catch {
    return sessionError(503, "USER_ADMINISTRATION_UNAVAILABLE", "User service unavailable");
  }
}

export async function POST(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(UPSTREAM_PATH, {
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
