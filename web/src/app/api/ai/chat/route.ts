import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

const AI_CHAT_UPSTREAM_TIMEOUT_MS = 35_000;

export async function POST(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(
        process.env.PDOS_AI_CHAT_ASYNC === "true" ? "/api/ai/chat/requests" : "/api/ai/chat",
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        },
        AI_CHAT_UPSTREAM_TIMEOUT_MS,
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "AI_CHAT_UNAVAILABLE", "AI chat unavailable");
  }
}
