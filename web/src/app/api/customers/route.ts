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
      await pdosApiFetch("/api/customers", {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(
      503,
      "REQUIREMENT_SERVICE_UNAVAILABLE",
      "Requirement service unavailable",
    );
  }
}
