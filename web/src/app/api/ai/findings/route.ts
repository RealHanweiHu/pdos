import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

const FILTERS = ["project_id", "status"] as const;

export async function GET(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const supplied = new URL(request.url).searchParams;
    const forwarded = new URLSearchParams();
    for (const name of FILTERS) {
      const value = supplied.get(name);
      if (value !== null) forwarded.set(name, value);
    }
    const query = forwarded.size > 0 ? `?${forwarded.toString()}` : "";
    return forwardJson(
      await pdosApiFetch(`/api/ai/findings${query}`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "FINDING_SERVICE_UNAVAILABLE", "Finding service unavailable");
  }
}
