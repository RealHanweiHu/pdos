import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

const FILTERS = ["after_id", "limit", "event_type", "project_id"] as const;
const MAX_BEARER_LENGTH = 4_096;

function requestBearer(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return null;
  const token = authorization.slice(7);
  if (!token || token.length > MAX_BEARER_LENGTH || !/^[A-Za-z0-9._~-]+$/.test(token)) {
    return null;
  }
  return token;
}

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
      await pdosApiFetch(`/api/events${query}`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "EVENT_SERVICE_UNAVAILABLE", "Event service unavailable");
  }
}

export async function POST(request: Request) {
  const token = requestBearer(request) ?? (await currentSessionToken());
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch("/api/events", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "EVENT_SERVICE_UNAVAILABLE", "Event service unavailable");
  }
}
